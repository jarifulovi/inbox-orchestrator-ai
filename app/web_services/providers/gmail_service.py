import re
import httpx
from typing import Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client
from app.core.services.auth_service import ConnectedAccountService
from googleapiclient.discovery import build


class GmailProviderService:
    """
    Dedicated Web Service for Provider-Level (Gmail API & RFC 8058) operations:
    One-Click HTTP Unsubscribe, Mailto Unsubscribe, and Gmail Spam Filter rules creation.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client or get_supabase_client()
        self.account_service = ConnectedAccountService(db_client=self.db)

    async def unsubscribe_sender(
        self,
        account_id: str,
        sender_email: str
    ) -> Dict[str, Any]:
        """
        Executes One-Click Unsubscribe for a sender at the provider level.
        Inspects headers from the sender's latest email for RFC 8058 List-Unsubscribe URL or mailto.
        If unavailable, falls back to creating a Gmail Spam Filter rule via Gmail API.
        """
        clean_sender = sender_email.strip().lower()
        if not account_id or not clean_sender:
            return {"status": "error", "message": "Invalid parameters."}

        try:
            # 1. Fetch latest email from sender for connected account
            email_res = self.db.table("emails") \
                .select("id, sender, headers, gmail_message_id") \
                .eq("connected_account_id", account_id) \
                .ilike("sender", f"%{clean_sender}%") \
                .order("received_at", desc=True) \
                .limit(1) \
                .execute()

            matched_emails = email_res.data or []
            headers_dict: Dict[str, str] = {}

            if matched_emails:
                raw_headers = matched_emails[0].get("headers") or {}
                if isinstance(raw_headers, dict):
                    headers_dict = {k.lower(): str(v) for k, v in raw_headers.items()}
                elif isinstance(raw_headers, list):
                    for h in raw_headers:
                        if isinstance(h, dict) and "name" in h and "value" in h:
                            headers_dict[h["name"].lower()] = str(h["value"])

            list_unsub_header = headers_dict.get("list-unsubscribe", "")

            # 2. Extract HTTP URLs and mailto links from List-Unsubscribe header
            http_url = None
            mailto_addr = None

            if list_unsub_header:
                # Find HTTP/HTTPS URLs inside <...>
                urls = re.findall(r'<(https?://[^>]+)>', list_unsub_header)
                if urls:
                    http_url = urls[0]

                # Find mailto: addresses inside <...>
                mailtos = re.findall(r'<(mailto:[^>]+)>', list_unsub_header)
                if mailtos:
                    mailto_addr = mailtos[0].replace("mailto:", "")

            # 3. Strategy A: HTTP One-Click Unsubscribe (RFC 8058)
            if http_url:
                try:
                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                        resp = await client.post(
                            http_url,
                            headers={"List-Unsubscribe": "One-Click"},
                            data={"List-Unsubscribe": "One-Click"}
                        )
                    if resp.status_code in (200, 201, 202, 204):
                        return {
                            "status": "success",
                            "method_used": "http_one_click",
                            "message": f"Successfully unsubscribed from {clean_sender} via One-Click HTTP."
                        }
                except Exception as http_err:
                    print(f"[UNSUBSCRIBE HTTP WARNING] HTTP unsubscribe failed for {clean_sender}: {http_err}")

            # 4. Strategy B: Mailto Unsubscribe via Gmail API
            if mailto_addr:
                try:
                    creds = self.account_service.get_valid_user_credentials(account_id)
                    service = build('gmail', 'v1', credentials=creds)

                    import base64
                    from email.message import EmailMessage

                    msg = EmailMessage()
                    msg['To'] = mailto_addr
                    msg['Subject'] = "Unsubscribe"
                    msg.set_content("Unsubscribe request sent automatically by InboxOrchestrator AI.")

                    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
                    service.users().messages().send(userId='me', body={'raw': raw_b64}).execute()

                    return {
                        "status": "success",
                        "method_used": "mailto",
                        "message": f"Sent automated unsubscribe request to {mailto_addr}."
                    }
                except Exception as mail_err:
                    print(f"[UNSUBSCRIBE MAILTO WARNING] Mailto unsubscribe failed for {clean_sender}: {mail_err}")

            # 5. Strategy C: Fallback to Gmail Spam Filter Creation
            try:
                creds = self.account_service.get_valid_user_credentials(account_id)
                service = build('gmail', 'v1', credentials=creds)

                filter_body = {
                    "criteria": {"from": clean_sender},
                    "action": {
                        "addLabelIds": ["SPAM"]
                    }
                }
                service.users().settings().filters().create(userId='me', body=filter_body).execute()

                return {
                    "status": "success",
                    "method_used": "gmail_spam_filter",
                    "message": f"Created Gmail Spam filter rule for {clean_sender}."
                }
            except Exception as filter_err:
                print(f"[UNSUBSCRIBE FILTER ERROR] Spam filter creation failed for {clean_sender}: {filter_err}")
                return {
                    "status": "error",
                    "message": f"Could not unsubscribe or block {clean_sender}."
                }

        except Exception as e:
            print(f"[UNSUBSCRIBE FATAL] Unsubscribe failed for {clean_sender}: {e}")
            return {"status": "error", "message": str(e)}
