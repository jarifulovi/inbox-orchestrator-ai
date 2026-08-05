import base64
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client


class EmailWebService:
    """
    Dedicated web service for Raw Email operations:
    email fetching, body extraction, detail resolution, read status updates, and email replies.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client or get_supabase_client()
        self.table = "emails"

    async def get_user_emails(
            self,
            account_id: str,
            limit: int = 20,
            offset: int = 0,
            q: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches user email records with optional keyword filtering.
        """
        query = self.db.table(self.table) \
            .select("id, thread_id, connected_account_id, sender, sender_name, subject, snippet, raw_payload->labelIds, received_at, category") \
            .eq("connected_account_id", account_id)

        if q and q.strip():
            keyword = q.strip()
            query = query.or_(f"subject.ilike.%{keyword}%,sender.ilike.%{keyword}%,sender_name.ilike.%{keyword}%")

        res = query.order("received_at", desc=True) \
            .range(offset, offset + limit - 1) \
            .execute()

        emails = res.data or []

        formatted_emails = []
        for e in emails:
            sender_email = e.get("sender", "")
            sender_name = e.get("sender_name")
            if not sender_name:
                sender_name = sender_email.split("<")[0].strip() if "<" in sender_email else sender_email

            label_ids = e.get("labelIds") or []
            is_read = True
            if isinstance(label_ids, list) and "UNREAD" in label_ids:
                is_read = False

            formatted_emails.append({
                "id": e["id"],
                "thread_id": e.get("thread_id"),
                "connected_account_id": e.get("connected_account_id"),
                "sender": sender_email,
                "sender_name": sender_name,
                "subject": e.get("subject") or "(No Subject)",
                "snippet": e.get("snippet") or "",
                "is_read": is_read,
                "received_at": e.get("received_at"),
                "category": e.get("category") or "Primary"
            })

        return formatted_emails

    async def get_email_details(self, email_id: str, account_id: str) -> Dict[str, Any]:
        """
        Fetches the complete details for a single email, decoding body text and expanding metadata.
        """
        res = self.db.table(self.table).select("*").eq("id", email_id).eq("connected_account_id", account_id).single().execute()
        if not res.data:
            raise KeyError(f"Email {email_id} not found.")

        data = res.data

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

        if not parts and "body" in payload_node:
            body_data = payload_node["body"].get("data", "")
            data["body"] = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8", errors="ignore") if body_data else ""
        else:
            data["body"] = self._extract_body_text(parts)

        return data

    def _extract_body_text(self, parts: list) -> str:
        """
        Helper function to iterate over Gmail payload parts and decode readable text.
        """
        html_content = ""
        text_content = ""

        for part in parts:
            mime_type = part.get("mimeType", "")
            body_data = part.get("body", {}).get("data", "")

            if body_data:
                decoded = base64.urlsafe_b64decode(body_data.encode("utf-8")).decode("utf-8", errors="ignore")
                if mime_type == "text/html":
                    html_content = decoded
                elif mime_type == "text/plain":
                    text_content = decoded

            if "parts" in part:
                sub_body = self._extract_body_text(part["parts"])
                if sub_body:
                    return sub_body

        return html_content or text_content
