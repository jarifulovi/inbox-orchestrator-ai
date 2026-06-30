import base64
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client

class EmailWebService:
    def __init__(self, db_client: Optional[Client] = None):
        """
        Initializes the Email Web Service with a Supabase client.
        """
        self.db = db_client or get_supabase_client()
        self.table = "emails"

    async def get_user_emails(
            self,
            account_id: str,
            limit: int = 20,
            offset: int = 0,
            classification: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches a paginated list of emails for a specific account, joined with classification data.
        """
        # 1. Correct Select Query using inner join
        select_query = (
            "id, thread_id, gmail_message_id, sender, sender_name, "
            "recipients, cc, bcc, subject, snippet, summary, received_at, ingested_at, raw_payload->labelIds, "
            "email_classifications!inner(user_id)"
        )

        # 2. Correct order syntax using desc=True
        query = self.db.table(self.table).select(select_query).eq("account_id", account_id).order("received_at",
                                                                                                  desc=True)
        # 3. Filter directly matching the PostgREST inner join path syntax
        if classification:
            query = query.eq("email_classifications.user_id", classification)

        query = query.range(offset, offset + limit - 1)
        response = query.execute()
        return response.data or []


    async def get_email_details(self, email_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves full email content alongside pre-computed ML classification,
        extracted actions, and security analysis records in a single join query.
        """
        response = self.db.table(self.table).select(
            "id, thread_id, gmail_message_id, sender, sender_name, "
            "recipients, cc, bcc, subject, snippet, summary, received_at, ingested_at, "
            "raw_payload->labelIds, raw_payload->payload, "
            "email_classifications(*), "
            "extracted_actions(*), "
            "email_security_analysis(*)"
        ).eq("id", email_id).eq("account_id", account_id).single().execute()

        data = response.data
        if not data:
            return None

        # Clean up the payload keys into direct, lightweight API properties
        payload_node = data.pop("payload", {}) or {}
        parts = payload_node.get("parts", [])

        # If there are no parts, check the top-level body node directly (occurs on short plain-text emails)
        if not parts and "body" in payload_node:
            body_data = payload_node["body"].get("data", "")
            data["body"] = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8",
                                                                                      errors="ignore") if body_data else ""
        else:
            data["body"] = self._extract_body_text(parts)

        return data

    async def update_read_status(self, email_id: str, account_id: str, is_read: bool) -> bool:
        """
        Updates the read state of an email.
        """
        self.db.table(self.table).update({"is_read": is_read}).eq("id", email_id).eq("account_id", account_id).execute()
        return True

    def _extract_body_text(self, parts: list) -> str:
        """
        A helper function that looks through the nested Gmail parts array,
        decodes the Base64 data, and extracts the readable body text.
        """
        html_content = ""
        text_content = ""

        for part in parts:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data", "")

            if body_data:
                # Decode Google's URL-safe Base64 payload string
                decoded = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8", errors="ignore")
                if mime_type == "text/html":
                    html_content = decoded
                elif mime_type == "text/plain":
                    text_content = decoded

            # If there are deeply nested parts (like inline images/attachments), look inside them too
            if "parts" in part:
                sub_body = self._extract_body_text(part["parts"])
                if sub_body:
                    return sub_body

        return html_content or text_content