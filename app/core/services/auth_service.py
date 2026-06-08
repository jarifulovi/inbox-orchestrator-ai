import os
from datetime import datetime, timedelta, timezone
import httpx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from supabase import Client
from app.db.supabase import get_supabase_client


class ConnectedAccountService:
    def __init__(self, db_client: Client = None):
        # Gracefully accept an injected client or pull your global singleton connection
        self.supabase = db_client or get_supabase_client()
        self.client_id = os.getenv("OAUTH_CLIENT_ID")
        self.client_secret = os.getenv("OAUTH_CLIENT_SECRET")

        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Critical Configuration Failure: OAUTH_CLIENT_ID or "
                "OAUTH_CLIENT_SECRET is missing from the environment variables."
            )

    async def _refresh_google_token(self, account_id: str, refresh_token: str) -> str:
        """
        Asynchronously communicates with Google's OAuth2 token endpoint to
        exchange a long-lived refresh token for a brand new temporary access token.
        """
        url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=payload)

        if response.status_code != 200:
            # Defensive Action: Flag the integration as inactive if authorization was
            # revoked externally by the user inside their Google Account Security settings.
            self.supabase.table("connected_accounts").update({"is_active": False}).eq("id", account_id).execute()
            raise Exception(
                f"Google Token Rotation rejected by upstream provider. Disabling sync. Detail: {response.text}")

        data = response.json()
        new_access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)  # Standard default is 1 hour
        new_expiration = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Persistence: Commit the freshly minted access window back to Supabase
        self.supabase.table("connected_accounts").update({
            "access_token": new_access_token,
            "token_expires_at": new_expiration.isoformat()
        }).eq("id", account_id).execute()

        print(f"[CORE AUTH] Tokens successfully rotated and committed for account record: {account_id}")
        return new_access_token

    async def get_authenticated_gmail_client(self, user_id: str):
        """
        Looks up user credentials, calculates expiration boundaries, forces background
        token updates if necessary, and instantiates a fully authenticated Google SDK Client.
        """
        response = self.supabase.table("connected_accounts") \
            .select("id, access_token, refresh_token, token_expires_at, is_active, scope") \
            .eq("id", user_id).eq("provider", "google").single().execute()

        account = response.data
        if not account:
            raise Exception(f"No active database integration record found matching user UUID: {user_id}")
        if not account["is_active"]:
            raise Exception(f"Google sync engine has been manually deactivated or revoked for user: {user_id}")

        access_token = account["access_token"]

        # Cleanly digest the DB timestamp. Replace 'Z' formatting if present to enforce strict offset-aware types.
        expires_at_str = account["token_expires_at"].replace('Z', '+00:00')
        token_expires_at = datetime.fromisoformat(expires_at_str)

        # Performance Threshold: If the token is dead or expires within the next 60 seconds, trigger rotation.
        if token_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
            print(f"[CORE AUTH] Detected expired access window for user {user_id}. Executing silent rotation...")
            access_token = await self._refresh_google_token(account["id"], account["refresh_token"])

        # Pack credentials into the native Google SDK resource container
        creds = Credentials(
            token=access_token,
            refresh_token=account["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=account["scope"].split(" ")
        )

        # Generate and return a thread-safe Gmail engine resource instance
        return build('gmail', 'v1', credentials=creds)

    def get_account_by_id(self, account_id: str) -> dict | None:
        response = (
            self.supabase
            .table("connected_accounts")
            .select("*")
            .eq("id", account_id)
            .single()
            .execute()
        )

        return response.data if response.data else None

    def get_active_google_accounts(self) -> list[dict]:
        response = (
            self.supabase
            .table("connected_accounts")
            .select("*")
            .eq("is_active", True)
            .eq("provider", "google")
            .execute()
        )
        return response.data or []