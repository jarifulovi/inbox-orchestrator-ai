import os
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client
from app.core.services.auth_service import ConnectedAccountService


class GoogleCalendarWebService:
    def __init__(self, db_client: Client):
        self.db = db_client
        self.auth_manager = ConnectedAccountService(db_client=self.db)

    async def get_calendar_client(self, account_id: str):
        response = self.db.table("connected_accounts") \
            .select("id, access_token, refresh_token, token_expires_at, is_active, scope") \
            .eq("id", account_id).eq("provider", "google").single().execute()

        account = response.data
        if not account or not account["is_active"]:
            raise Exception("No active Google account connection found.")

        access_token = account["access_token"]
        expires_at_str = account["token_expires_at"].replace('Z', '+00:00')
        token_expires_at = datetime.fromisoformat(expires_at_str)

        if token_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
            access_token = await self.auth_manager._refresh_google_token(account["id"], account["refresh_token"])

        granted_scopes = account.get("scope", "").split(" ")
        creds = Credentials(
            token=access_token,
            refresh_token=account["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.auth_manager.client_id,
            client_secret=self.auth_manager.client_secret,
            scopes=granted_scopes
        )

        return build('calendar', 'v3', credentials=creds)

    async def sync_task_to_gcal(self, task_id: str, account_id: str) -> dict:
        task_res = self.db.table("tasks") \
            .select("*") \
            .eq("id", task_id) \
            .eq("connected_account_id", account_id) \
            .single() \
            .execute()

        if not task_res.data:
            raise KeyError(f"Task {task_id} not found or access denied.")

        task = task_res.data
        due_date_str = task.get("due_date")

        if due_date_str:
            start_dt = datetime.fromisoformat(due_date_str.replace('Z', '+00:00'))
        else:
            start_dt = datetime.now(timezone.utc) + timedelta(hours=1)

        end_dt = start_dt + timedelta(hours=1)

        summary = f"[InboxOrchestrator AI] {task.get('title', 'Task Event')}"
        description = (
            f"Action Item: {task.get('title')}\n"
            f"Priority: {task.get('priority', 'medium').upper()}\n"
            f"Intent: {task.get('intent_label', 'other')}\n"
            f"Source: InboxOrchestrator AI Task ID {task_id}"
        )

        event_body = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "UTC"
            }
        }

        try:
            cal_client = await self.get_calendar_client(account_id)
            created_event = cal_client.events().insert(calendarId="primary", body=event_body).execute()
            html_link = created_event.get("htmlLink", "")

            return {
                "status": "success",
                "event_id": created_event.get("id"),
                "event_url": html_link,
                "message": "Event successfully exported to Google Calendar!"
            }
        except HttpError as err:
            if err.resp.status in (401, 403):
                return {
                    "status": "permission_required",
                    "message": "Google Calendar scope not granted. Please re-connect your Google Account in Settings to grant calendar permissions."
                }
            raise Exception(f"Google Calendar API Error: {str(err)}")
