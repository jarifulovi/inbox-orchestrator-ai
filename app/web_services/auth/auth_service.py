# app/web_services/auth/auth_service.py
import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4
import httpx
from dateutil.parser import isoparse
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from fastapi import BackgroundTasks, HTTPException

from app.core.workers.sync_worker import EmailSyncWorker
from app.core.schemas.connected_accounts import ConnectedAccountRow
from app.schemas.auth_schemas import (
    MeResponseSchema,
    MeUserSchema,
    GmailAccountsSchema,
    GmailAccountSchema,
    SyncInfo,
    GoogleAuthUrlResponse,
)


# Enable relaxed token scope in oauthlib to handle Google's scope URL normalization
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"


class AuthWebService:
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
    GOOGLE_PROFILE_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    GOOGLE_SCOPES = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify"
    ]
    GOOGLE_CLIENT_CONFIG = {
        "web": {
            "client_id": os.getenv("OAUTH_CLIENT_ID"),
            "client_secret": os.getenv("OAUTH_CLIENT_SECRET"),
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
            user=MeUserSchema(id=user_id, email=auth_user.get("email")),
            gmail=GmailAccountsSchema(connected=len(accounts) > 0, accounts=gmail_accounts)
        )

    def verify_jwt(self, jwt: str):
        user_response = self.db.auth.get_user(jwt)
        user = user_response.user
        if not user:
            raise Exception("AUTH_INVALID_TOKEN")

        return {"id": user.id, "email": user.email, "role": user.role}

    async def generate_google_auth_url(self, auth_user: dict, login_hint: str | None = None) -> GoogleAuthUrlResponse:
        try:
            flow = Flow.from_client_config(
                self.GOOGLE_CLIENT_CONFIG,
                scopes=self.GOOGLE_SCOPES,
                redirect_uri=self.GOOGLE_REDIRECT_URI
            )
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

            # Explicitly generate a cryptographically secure manual PKCE Code Verifier string
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            ).decode("utf-8").rstrip("=")

            flow.code_verifier = code_verifier

            extra_params = {
                "access_type": "offline",
                "prompt": "consent",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256"
            }
            if login_hint:
                extra_params["login_hint"] = login_hint

            authorization_url, state = flow.authorization_url(**extra_params)

            self.db.table("oauth_states").insert({
                "state": state,
                "user_id": auth_user.get("id"),
                "code_verifier": code_verifier,
                "expires_at": expires_at.isoformat(),
            }).execute()

            return GoogleAuthUrlResponse(auth_url=authorization_url, url=authorization_url)
        except Exception as e:
            print(f"[AUTH ERROR] Failed to generate Google auth URL: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to generate Google auth URL: {str(e)}")

    async def handle_google_callback(
            self,
            state: str,
            code: str | None = None,
            error: str | None = None,
            background_tasks: BackgroundTasks = None
    ) -> RedirectResponse:
        if error:
            return RedirectResponse(url=f"{self.FRONTEND_URL}/dashboard/settings?error={error}")

        if not code or not state:
            return RedirectResponse(url=f"{self.FRONTEND_URL}/dashboard/settings?error=missing_params")

        res = self.db.table("oauth_states").select("*").eq("state", state).execute()
        if not res.data:
            return RedirectResponse(url=f"{self.FRONTEND_URL}/dashboard/settings?error=invalid_state")

        state_record = res.data[0]
        user_id = state_record["user_id"]
        code_verifier = state_record.get("code_verifier")
        expires_at = isoparse(state_record["expires_at"])

        if datetime.now(timezone.utc) > expires_at:
            self.db.table("oauth_states").delete().eq("state", state).execute()
            return RedirectResponse(url=f"{self.FRONTEND_URL}/dashboard/settings?error=state_expired")

        self.db.table("oauth_states").delete().eq("state", state).execute()

        try:
            flow = Flow.from_client_config(
                self.GOOGLE_CLIENT_CONFIG,
                scopes=self.GOOGLE_SCOPES,
                redirect_uri=self.GOOGLE_REDIRECT_URI
            )
            flow.code_verifier = code_verifier

            flow.fetch_token(code=code)
            credentials: Credentials = flow.credentials

            async with httpx.AsyncClient() as client:
                profile_res = await client.get(
                    self.GOOGLE_PROFILE_URL,
                    headers={"Authorization": f"Bearer {credentials.token}"}
                )
                if profile_res.status_code != 200:
                    raise Exception("Failed to fetch Google profile info")
                profile_data = profile_res.json()

            provider_email = profile_data.get("email")
            if not provider_email:
                raise Exception("No email associated with Google account")

            existing_account = (
                self.db.table("connected_accounts")
                .select("*")
                .eq("user_id", user_id)
                .eq("provider", "google")
                .eq("provider_email", provider_email)
                .maybe_single()
                .execute()
            )
            existing_account_data = existing_account.data if existing_account else None
            now_iso = datetime.now(timezone.utc).isoformat()

            # Retrieve refresh_token safely (credentials or preserve existing)
            refresh_token = credentials.refresh_token
            if not refresh_token and existing_account_data:
                refresh_token = existing_account_data.get("refresh_token")
            if not refresh_token:
                refresh_token = ""

            token_expires_at = credentials.expiry.isoformat() if credentials.expiry else (
                datetime.now(timezone.utc) + timedelta(hours=1)
            ).isoformat()

            granted_scopes = getattr(credentials, "scopes", None) or self.GOOGLE_SCOPES
            scope_str = " ".join(granted_scopes) if isinstance(granted_scopes, (list, set, tuple)) else str(granted_scopes)

            account_data = {
                "user_id": user_id,
                "provider": "google",
                "provider_email": provider_email,
                "access_token": credentials.token,
                "refresh_token": refresh_token,
                "token_expires_at": token_expires_at,
                "is_active": True,
                "scope": scope_str,
                "sync_mode": existing_account_data.get("sync_mode", "INITIAL_BACKFILL") if existing_account_data else "INITIAL_BACKFILL",
                "sync_status": existing_account_data.get("sync_status", "IDLE") if existing_account_data else "IDLE",
                "connected_at": existing_account_data.get("connected_at", now_iso) if existing_account_data else now_iso
            }

            if existing_account_data:
                account_id = existing_account_data["id"]
                self.db.table("connected_accounts").update(account_data).eq("id", account_id).execute()
            else:
                new_account_res = self.db.table("connected_accounts").insert(account_data).execute()
                if not new_account_res.data:
                    raise Exception("Failed to save connected account record")
                account_id = new_account_res.data[0]["id"]

            return RedirectResponse(url=f"{self.FRONTEND_URL}/dashboard/settings?google_connected=true")

        except Exception as e:
            print(f"Error handling OAuth callback: {e}")
            return RedirectResponse(url=f"{self.FRONTEND_URL}/dashboard/settings?error=oauth_failed")

    def refresh_access_token(self, account_id: str) -> str:
        res = self.db.table("connected_accounts").select("*").eq("id", account_id).single().execute()
        if not res.data:
            raise Exception("Account not found")

        account = res.data
        refresh_token = account.get("refresh_token")
        if not refresh_token:
            raise Exception("No refresh token available for account")

        client_id = os.getenv("OAUTH_CLIENT_ID")
        client_secret = os.getenv("OAUTH_CLIENT_SECRET")

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        with httpx.Client() as client:
            response = client.post(token_url, data=payload)
            if response.status_code != 200:
                raise Exception(f"Failed to refresh access token: {response.text}")

            token_data = response.json()
            new_access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            new_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

            update_payload = {
                "access_token": new_access_token,
                "token_expires_at": new_expiry.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            if "refresh_token" in token_data:
                update_payload["refresh_token"] = token_data["refresh_token"]

            self.db.table("connected_accounts").update(update_payload).eq("id", account_id).execute()

            return new_access_token

    def get_valid_access_token(self, account_id: str) -> str:
        res = self.db.table("connected_accounts").select("*").eq("id", account_id).single().execute()
        if not res.data:
            raise Exception("Account not found")

        account = res.data
        expires_at_str = account.get("token_expires_at")
        access_token = account.get("access_token")

        if expires_at_str:
            expires_at = isoparse(expires_at_str)
            if datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5):
                return self.refresh_access_token(account_id)

        if not access_token:
            return self.refresh_access_token(account_id)

        return access_token

    def get_refresh_token_by_email(self, email: str) -> Optional[str]:
        response = (
            self.db.table("connected_accounts")
            .select("refresh_token")
            .eq("provider", "google")
            .eq("provider_email", email)
            .maybe_single()
            .execute()
        )

        if not response.data:
            return None

        return response.data.get("refresh_token")
