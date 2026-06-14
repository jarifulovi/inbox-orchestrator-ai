# app/web_services/auth_web_service.py
import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx
from dateutil.parser import isoparse
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

from app.schemas.auth_schemas import (
    MeResponseSchema,
    MeUserSchema,
    GmailAccountsSchema,
    GmailAccountSchema,
    SyncInfo,
    GoogleAuthUrlResponse,
)


class AuthWebService:
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
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

    async def generate_google_auth_url(self, auth_user: dict) -> GoogleAuthUrlResponse:
        flow = Flow.from_client_config(
            self.GOOGLE_CLIENT_CONFIG,
            scopes=self.GOOGLE_SCOPES,
            redirect_uri=self.GOOGLE_REDIRECT_URI
        )
        state = str(uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        # 💡 FIX 1: Explicitly generate a cryptographically secure manual PKCE Code Verifier string
        # Must be an unpadded Base64URL safe string (between 43 and 128 characters)
        code_verifier = secrets.token_urlsafe(64)[:128]

        # 💡 FIX 2: Generate the matching Code Challenge (S256 hashing format)
        hashed_verifier = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(hashed_verifier).decode('utf-8').replace('=', '')

        # 💡 FIX 3: Force the custom challenges down into Google's request params
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
            code_challenge=code_challenge,
            code_challenge_method="S256"
        )

        # Store state along with your validated code verifier string (Guaranteed to be populated!)
        self.db.table("oauth_states").insert({
            "state": state,
            "user_id": auth_user["id"],
            "code_verifier": code_verifier,
            "provider": "google",
            "expires_at": expires_at.isoformat()
        }).execute()

        return GoogleAuthUrlResponse(auth_url=auth_url)

    async def handle_google_callback(self, code: str, state: str) -> RedirectResponse:
        # =========================
        # 1. Fetch OAuth state
        # =========================
        state_row = self.db.table("oauth_states") \
            .select("*") \
            .eq("state", state) \
            .maybe_single() \
            .execute()

        if not state_row.data:
            raise Exception("INVALID_OAUTH_STATE")

        state_data = state_row.data

        # =========================
        # 2. Validate state
        # =========================
        if not state_data.get("expires_at"):
            raise Exception("INVALID_OAUTH_STATE")

        if isoparse(state_data["expires_at"]) < datetime.now(timezone.utc):
            raise Exception("OAUTH_STATE_EXPIRED")

        if state_data.get("used_at") is not None:
            raise Exception("OAUTH_STATE_ALREADY_USED")

        user_id = state_data["user_id"]
        code_verifier = state_data["code_verifier"]

        # =========================
        # 3. Google OAuth flow
        # =========================
        token_url = self.GOOGLE_CLIENT_CONFIG["web"]["token_uri"]

        exchange_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.GOOGLE_REDIRECT_URI,
            "client_id": self.GOOGLE_CLIENT_CONFIG["web"]["client_id"],
            "client_secret": self.GOOGLE_CLIENT_CONFIG["web"]["client_secret"],
        }

        # Force send the code verifier extracted from Supabase
        if code_verifier:
            exchange_data["code_verifier"] = code_verifier

        try:
            # Send raw POST straight to Google
            with httpx.Client(timeout=10.0) as client:
                token_response = client.post(token_url, data=exchange_data)

            # If Google rejects it, this raises an error and prints the exact reason below
            token_response.raise_for_status()
            res_json = token_response.json()

            # Format the output so the downstream profile fetch & upsert code still works perfectly
            expiry = None
            if "expires_in" in res_json:
                expiry = datetime.now(timezone.utc) + timedelta(seconds=int(res_json["expires_in"]))

            credentials = Credentials(
                token=res_json.get("access_token"),
                refresh_token=res_json.get("refresh_token"),
                token_uri=token_url,
                client_id=self.GOOGLE_CLIENT_CONFIG["web"]["client_id"],
                client_secret=self.GOOGLE_CLIENT_CONFIG["web"]["client_secret"],
                scopes=self.GOOGLE_SCOPES,
                expiry=expiry
            )

        except Exception as exchange_error:
            print("\n" + "=" * 50)
            print("[OAUTH CRITICAL FAILURE] Complete Handshake Failure details:")
            print(f"Exception Type: {type(exchange_error).__name__}")
            print(f"Exception Message: {str(exchange_error)}")

            if 'token_response' in locals() and token_response:
                print(f"Raw Google Server Response Status: {token_response.status_code}")
                print(f"Raw Google Server Response Body: {token_response.text}")
            print("=" * 50 + "\n")

            raise Exception("GOOGLE_TOKEN_EXCHANGE_FAILED")

        # =========================
        # 4. Fetch Google profile
        # =========================
        gmail_profile = await self._fetch_google_profile(credentials.token)

        # =========================
        # 5. Preserve refresh token safely
        # =========================
        existing = self.db.table("connected_accounts") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("provider_email", gmail_profile["email"]) \
            .maybe_single() \
            .execute()

        existing_data = existing.data if existing else None

        refresh_token: str | None = (
                credentials.refresh_token
                or (existing_data.get("refresh_token") if existing_data else None)
        )

        # =========================
        # 6. Upsert connected account
        # =========================
        self._upsert_connected_account(
            user_id=user_id,
            provider_email=gmail_profile["email"],
            access_token=credentials.token,
            refresh_token=refresh_token,
            token_expiry=credentials.expiry
        )

        # =========================
        # 7. Mark state as used (ONLY after success)
        # =========================
        self.db.table("oauth_states") \
            .update({"used_at": datetime.now(timezone.utc).isoformat()}) \
            .eq("state", state) \
            .execute()

        print("STATE RECEIVED AND VERIFIED:", state)

        return RedirectResponse(
            url=f"{self.FRONTEND_URL}/success?status=success"
        )

    async def _fetch_google_profile(self, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self.GOOGLE_PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"}
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
        refresh_token_final = refresh_token or self._get_existing_refresh_token(user_id, provider_email)
        scope_string = " ".join(self.GOOGLE_SCOPES)
        response = self.db.table("connected_accounts").upsert(
            {
                "user_id": user_id,
                "provider": "google",
                "provider_email": provider_email,
                "access_token": access_token,
                "refresh_token": refresh_token_final,
                "token_expires_at": token_expiry.isoformat() if token_expiry else None,
                "is_active": True,
                "sync_mode": "INITIAL_BACKFILL",
                "sync_status": "IDLE",
                "sync_cursor": None,
                "connected_at": datetime.now(timezone.utc).isoformat(),
                "last_sync_at": None,
                "scope": scope_string
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