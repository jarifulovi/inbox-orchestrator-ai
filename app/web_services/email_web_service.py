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
        # 1. Correct Select Query using category and ai_metadata from emails table directly
        select_query = (
            "id, thread_id, gmail_message_id, sender, sender_name, "
            "recipients, cc, bcc, subject, snippet, summary, received_at, ingested_at, raw_payload->labelIds, "
            "category, ai_metadata"
        )

        # 2. Correct order syntax using desc=True and matching connected_account_id
        query = self.db.table(self.table).select(select_query).eq("connected_account_id", account_id).order("received_at",
                                                                                                  desc=True)
        # 3. Filter directly matching the category column
        if classification:
            query = query.eq("category", classification)

        query = query.range(offset, offset + limit - 1)
        response = query.execute()

        emails_list = response.data or []
        for email in emails_list:
            category = email.get("category")
            ai_metadata = email.get("ai_metadata") or {}
            clf_meta = ai_metadata.get("classifier") or {}
            if category:
                email["email_classifications"] = [{
                    "email_id": email["id"],
                    "label": category,
                    "label_id": clf_meta.get("label_id", -1),
                    "confidence": clf_meta.get("confidence", 0.0),
                    "probabilities": clf_meta.get("probabilities", {}),
                    "model_version": clf_meta.get("model_version", "v1.0")
                }]
            else:
                email["email_classifications"] = []
        return emails_list


    async def get_email_details(self, email_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves full email content alongside category, metadata,
        and extracted facts in a single join query.
        """
        response = self.db.table(self.table).select(
            "id, thread_id, gmail_message_id, sender, sender_name, "
            "recipients, cc, bcc, subject, snippet, summary, received_at, ingested_at, "
            "raw_payload->labelIds, raw_payload->payload, "
            "category, ai_metadata, "
            "email_facts(*)"
        ).eq("id", email_id).eq("connected_account_id", account_id).single().execute()

        data = response.data
        if not data:
            return None

        # Construct backward-compatible email_classifications and security analysis lists
        category = data.get("category")
        ai_metadata = data.get("ai_metadata") or {}
        clf_meta = ai_metadata.get("classifier") or {}
        sec_meta = ai_metadata.get("security_analysis") or {}

        if category:
            data["email_classifications"] = [{
                "email_id": email_id,
                "label": category,
                "label_id": clf_meta.get("label_id", -1),
                "confidence": clf_meta.get("confidence", 0.0),
                "probabilities": clf_meta.get("probabilities", {}),
                "model_version": clf_meta.get("model_version", "v1.0")
            }]
        else:
            data["email_classifications"] = []

        if sec_meta:
            spf_res = sec_meta.get("raw_spf_result")
            dkim_res = sec_meta.get("raw_dkim_result")
            data["email_security_analysis"] = [{
                "email_id": email_id,
                "spf_pass": (spf_res == "pass" if spf_res else False),
                "dkim_pass": (dkim_res == "pass" if dkim_res else False),
                "dmarc_pass": None,
                "is_whitelisted_sender": False,
                "pre_security_passed": sec_meta.get("pre_security_passed", True),
                "security_risks": sec_meta.get("security_risks", []),
                "is_phishing_anomaly": sec_meta.get("is_phishing_anomaly", False),
                "security_trust_score": sec_meta.get("security_trust_score", 0.0),
                "security_trust_level": sec_meta.get("security_trust_level", "unverified")
            }]
        else:
            data["email_security_analysis"] = []

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
        self.db.table(self.table).update({"is_read": is_read}).eq("id", email_id).eq("connected_account_id", account_id).execute()
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