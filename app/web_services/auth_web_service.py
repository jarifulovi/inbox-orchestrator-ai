from google.auth.aio import credentials
from google_auth_oauthlib.flow import Flow
import httpx
import os
from datetime import datetime
from app.schemas.auth_schemas import (
    MeResponseSchema,
    MeUserSchema,
    GmailAccountsSchema,
    GmailAccountSchema,
    SyncInfo,
    GoogleAuthUrlResponse,
    GoogleCallbackResponse
)



class AuthWebService:
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
    GOOGLE_PROFILE_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_SCOPES = [
        "openid",
        "email",
        "profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify"
    ]
    GOOGLE_CLIENT_CONFIG = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }

    def __init__(self, db_client):
        self.db = db_client

    async def get_me(self, auth_user: dict):
        user_id = auth_user.get("id")

        if not user_id:
            raise Exception("Invalid auth user")

        # Fetch connected accounts (source of truth)
        accounts_res = self.db.table("connected_accounts") \
            .select("*") \
            .eq("user_id", user_id) \
            .execute()

        accounts = accounts_res.data or []

        gmail_accounts = [
            GmailAccountSchema(
                id=acc["id"],
                provider=acc["provider"],
                email=acc["provider_email"],
                is_active=acc["is_active"],
                sync=SyncInfo(
                    mode=acc.get("sync_mode"),
                    cursor=acc.get("sync_cursor"),
                    last_sync_at=acc.get("last_sync_at")
                )
            )
            for acc in accounts
        ]

        return MeResponseSchema(
            user=MeUserSchema(
                id=user_id,
                email=auth_user.get("email")
            ),
            gmail=GmailAccountsSchema(
                connected=len(accounts) > 0,
                accounts=gmail_accounts
            )
        )

    def verify_jwt(self, jwt: str):
        user_response = self.db.auth.get_user(jwt)
        user = user_response.user

        if not user:
            raise Exception("AUTH_INVALID_TOKEN")

        return {
            "id": user.id,
            "email": user.email,
            "role": user.role
        }

    async def generate_google_auth_url(self, auth_user: dict) -> GoogleAuthUrlResponse:

        flow = Flow.from_client_config(
            self.GOOGLE_CLIENT_CONFIG,
            scopes=self.GOOGLE_SCOPES
        )

        flow.redirect_uri = self.GOOGLE_REDIRECT_URI

        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=auth_user["id"]
        )

        return GoogleAuthUrlResponse(auth_url=auth_url)

    async def handle_google_callback(
            self,
            code: str,
            state: str
    ) -> GoogleCallbackResponse:

        flow = Flow.from_client_config(
            self.GOOGLE_CLIENT_CONFIG,
            scopes=self.GOOGLE_SCOPES
        )

        flow.redirect_uri = self.GOOGLE_REDIRECT_URI

        # --- token exchange ---
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # --- fetch google profile ---
        gmail_profile = await self._fetch_google_profile(
            credentials.token
        )

        # --- protect refresh token (IMPORTANT FIX) ---
        existing = self.db.table("connected_accounts") \
            .select("*") \
            .eq("user_id", state) \
            .eq("provider_email", gmail_profile["email"]) \
            .maybe_single() \
            .execute()

        existing_data = existing.data if existing else None

        refresh_token = (
                credentials.refresh_token
                or (existing_data.get("refresh_token") if existing_data else None)
        )

        # --- upsert ---
        connected_account = self._upsert_connected_account(
            user_id=state,
            provider_email=gmail_profile["email"],
            access_token=credentials.token,
            refresh_token=refresh_token,
            token_expiry=credentials.expiry
        )

        return GoogleCallbackResponse(
            status="success",
            connected_account_id=connected_account["id"],
            provider_email=gmail_profile["email"]
        )


    async def _fetch_google_profile(self, access_token: str) -> dict:

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self.GOOGLE_PROFILE_URL,
                headers={
                    "Authorization": f"Bearer {access_token}"
                }
            )

        try:
            response.raise_for_status()
        except Exception:
            raise Exception("GOOGLE_PROFILE_FETCH_FAILED")

        return response.json()

    def _upsert_connected_account(
            self,
            user_id: str,
            provider_email: str,
            access_token: str,
            refresh_token: str | None,
            token_expiry
    ):

        refresh_token_final = refresh_token or self._get_existing_refresh_token(
            user_id,
            provider_email
        )

        response = self.db.table("connected_accounts").upsert(
            {
                "user_id": user_id,
                "provider": "google",
                "provider_email": provider_email,

                "access_token": access_token,
                "refresh_token": refresh_token_final,
                "token_expires_at": token_expiry.isoformat() if token_expiry else None,

                "is_active": True,

                # lifecycle state (IMPORTANT)
                "sync_mode": "INITIAL_BACKFILL",
                "sync_status": "IDLE",
                "sync_cursor": None,

                # audit fields
                "connected_at": datetime.utcnow().isoformat(),
                "last_sync_at": None
            },
            on_conflict="user_id,provider,provider_email"
        ).execute()

        return response.data[0]


    def _get_existing_refresh_token(self, user_id: str, email: str) -> str | None:

        response = (
            self.db.table("connected_accounts")
            .select("refresh_token")
            .eq("user_id", user_id)
            .eq("provider", "google")
            .eq("provider_email", email)
            .maybe_single()
            .execute()
        )

        if not response.data:
            return None

        return response.data.get("refresh_token")