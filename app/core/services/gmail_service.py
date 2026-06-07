# app/core/services/gmail_service.py
import base64
import email.utils
from datetime import datetime, timezone
from googleapiclient.discovery import Resource


class GmailIngestionService:
    def __init__(self, gmail_client: Resource):
        self.client = gmail_client

    def _clean_address_header(self, raw_header: str) -> list[str]:
        """Converts raw comma-separated header fields into clean list arrays."""
        if not raw_header:
            return []
        parsed_addresses = email.utils.getaddresses([raw_header])
        return [addr for _, addr in parsed_addresses if addr]

    def _extract_email_body(self, payload: dict) -> str:
        """Recursively parses and decodes the multi-part MIME payload body text."""
        if 'body' in payload and 'data' in payload['body']:
            b64_data = payload['body']['data']
            clean_b64 = b64_data.replace('-', '+').replace('_', '/')
            return base64.b64decode(clean_b64).decode('utf-8', errors='ignore')

        if 'parts' in payload:
            body_text = ""
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                    b64_data = part['body']['data']
                    clean_b64 = b64_data.replace('-', '+').replace('_', '/')
                    body_text += base64.b64decode(clean_b64).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    body_text += self._extract_email_body(part)
            return body_text
        return ""

    def _get_email_details(self, message_id: str) -> dict:
        """Fetches and transforms single raw message properties into structured nodes."""
        msg_detail = self.client.users().messages().get(userId='me', id=message_id, format='full').execute()

        payload = msg_detail.get('payload', {})
        headers = payload.get('headers', [])

        raw_from = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
        raw_to = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
        raw_cc = next((h['value'] for h in headers if h['name'].lower() == 'cc'), '')
        raw_bcc = next((h['value'] for h in headers if h['name'].lower() == 'bcc'), '')

        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '(No Subject)')
        raw_date = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')

        # Safe ISO-8601 formatting for Postgres TIMESTAMPTZ compatibility
        try:
            if raw_date:
                parsed_dt = email.utils.parsedate_to_datetime(raw_date)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                date_sent = parsed_dt.isoformat()
            else:
                date_sent = datetime.now(timezone.utc).isoformat()
        except Exception:
            date_sent = datetime.now(timezone.utc).isoformat()
        # Native extraction transformations completely isolated here
        sender_name, sender_email = email.utils.parseaddr(raw_from)

        return {
            "message_id": message_id,
            "thread_id": msg_detail.get("threadId"),
            "sender": sender_email if sender_email else raw_from,
            "sender_name": sender_name if sender_name else None,
            "recipients": self._clean_address_header(raw_to),
            "cc": self._clean_address_header(raw_cc),
            "bcc": self._clean_address_header(raw_bcc),
            "subject": subject,
            "date_sent": date_sent,
            "snippet": msg_detail.get("snippet", ""),
            "body_content": self._extract_email_body(payload).strip(),
            "raw_payload": msg_detail
        }

    async def fetch_historical_batch(self, page_token: str = None, max_results: int = 50) -> dict:
        list_params = {'userId': 'me', 'q': 'is:unread', 'maxResults': max_results}
        if page_token:
            list_params['pageToken'] = page_token

        result = self.client.users().messages().list(**list_params).execute()
        messages = result.get('messages', [])
        next_page_token = result.get('nextPageToken')

        processed_emails = [self._get_email_details(msg['id']) for msg in messages]

        # 💡 FIX: Fetch the absolute real, global current historyId from the user's profile status!
        try:
            profile = self.client.users().getProfile(userId='me').execute()
            current_history_id = str(profile.get('historyId', '0'))
        except Exception as profile_err:
            print(f"[SERVICE WARNING] Failed to fetch live mailbox profile history ID: {str(profile_err)}")
            current_history_id = "0"

        return {
            "emails": processed_emails,
            "next_page_token": next_page_token,
            "history_id": current_history_id
        }

    async def fetch_delta_changes(self, start_history_id: str) -> dict:
        """
        Production-safe Gmail delta sync engine.
        - Fully paginated history consumption
        - Idempotent message extraction
        - Safe cursor advancement
        """

        discovered_msg_ids = set()
        page_token = None
        final_history_id = start_history_id

        # =========================================================
        # 1. FULL HISTORY PAGINATION (CRITICAL FIX)
        # =========================================================
        while True:
            try:
                response = self.client.users().history().list(
                    userId='me',
                    startHistoryId=start_history_id,
                    pageToken=page_token,
                    historyTypes=[
                        'messageAdded',
                        'messageDeleted',
                        'labelAdded',
                        'labelRemoved'
                    ]
                ).execute()

            except Exception as e:
                print(f"[GMAIL HISTORY ERROR] {str(e)}")
                break

            history_blocks = response.get('history', [])

            # update cursor snapshot (latest known state)
            final_history_id = response.get('historyId', final_history_id)

            # =========================================================
            # 2. EXTRACT MESSAGE IDS FROM ALL EVENTS
            # =========================================================
            for block in history_blocks:

                for entry in block.get('messagesAdded', []):
                    msg = entry.get('message', {})
                    if msg.get('id'):
                        discovered_msg_ids.add(msg['id'])

                for entry in block.get('labelAdded', []):
                    msg = entry.get('message', {})
                    if msg.get('id'):
                        discovered_msg_ids.add(msg['id'])

                for entry in block.get('messageChanged', []):
                    msg = entry.get('message', {})
                    if msg.get('id'):
                        discovered_msg_ids.add(msg['id'])

            # =========================================================
            # 3. PAGINATION CONTROL
            # =========================================================
            page_token = response.get('nextPageToken')
            if not page_token:
                break

        # =========================================================
        # 4. RESOLVE FULL EMAIL OBJECTS (IDEMPOTENT)
        # =========================================================
        processed_emails = []

        for msg_id in discovered_msg_ids:
            try:
                email_detail = self._get_email_details(msg_id)
                processed_emails.append(email_detail)
            except Exception as e:
                print(f"[MESSAGE FETCH ERROR] {msg_id}: {str(e)}")
                continue

        return {
            "emails": processed_emails,
            "history_id": final_history_id
        }

    def format_thread_records(self, emails_to_process: list[dict], account_id: str) -> list[dict]:
        """Aggregates and formats distinct parent thread records for a batch of emails."""
        unique_threads = {}
        for email in emails_to_process:
            t_id = email["thread_id"]

            # Capture the message timestamp for the schema's NOT NULL constraint
            msg_date = email.get("date_sent")

            if t_id not in unique_threads:
                unique_threads[t_id] = {
                    "connected_account_id": account_id,
                    "gmail_thread_id": t_id,
                    "subject": email.get("subject", "(No Subject)"),
                    "snippet": email.get("snippet", ""),
                    "is_processed": False,
                    "last_message_at": msg_date,  # <-- FIX: Added to satisfy DB constraint
                    "unread_messages_count": 0
                }
            else:
                # Optional: Ensure the thread tracks the newest message timestamp in the batch
                if msg_date and unique_threads[t_id]["last_message_at"] < msg_date:
                    unique_threads[t_id]["last_message_at"] = msg_date

        return list(unique_threads.values())