import base64
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from app.core.ml_models.embedder.embedder import EmailEmbedder
        _embedder = EmailEmbedder()
    return _embedder


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

    async def get_user_threads(
            self,
            account_id: str,
            limit: int = 20,
            offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetches parent thread records dynamically, resolves the latest email sender & security trust level,
        bulk-counts pending tasks, and returns real priority & workflow metadata with safe defaults.
        """
        # 1. Fetch account email
        account_email = ""
        try:
            acc_res = self.db.table("connected_accounts").select("provider_email").eq("id", account_id).single().execute()
            if acc_res and acc_res.data:
                account_email = acc_res.data.get("provider_email") or ""
        except Exception as e:
            print(f"[THREADS WARNING] Failed to fetch provider_email for connected account {account_id}: {e}")

        # 2. Fetch threads
        try:
            threads_res = self.db.table("email_threads") \
                .select("*") \
                .eq("connected_account_id", account_id) \
                .order("last_message_at", desc=True) \
                .range(offset, offset + limit - 1) \
                .execute()
            threads = threads_res.data or []
        except Exception as e:
            print(f"[THREADS ERROR] Failed to fetch email_threads: {e}")
            return []

        if not threads:
            return []

        thread_ids = [t["id"] for t in threads if t.get("id")]
        if not thread_ids:
            return []

        # 3. Bulk fetch emails for these threads to resolve latest sender info, latest email security_trust_level, and message_count
        emails_by_thread = {}
        latest_email_info = {}
        try:
            emails_res = self.db.table("emails") \
                .select("thread_id, sender, sender_name, received_at, ai_metadata") \
                .in_("thread_id", thread_ids) \
                .order("received_at", desc=True) \
                .execute()

            for email in (emails_res.data or []):
                t_id = email.get("thread_id")
                if not t_id:
                    continue

                if t_id not in emails_by_thread:
                    emails_by_thread[t_id] = []
                emails_by_thread[t_id].append(email)

                # The first email seen per thread is the latest (due to received_at desc ordering)
                if t_id not in latest_email_info:
                    sender_str = email.get("sender") or ""
                    name = email.get("sender_name")
                    email_addr = sender_str

                    if not name and "<" in sender_str and ">" in sender_str:
                        parts = sender_str.split("<")
                        name = parts[0].strip().replace('"', '')
                        email_addr = parts[1].split(">")[0].strip()
                        if not name:
                            name = email_addr.split("@")[0].strip() if "@" in email_addr else email_addr
                    elif not name:
                        name = sender_str.split("@")[0].strip() if "@" in sender_str else sender_str

                    # Extract security_trust_level from ai_metadata -> security_analysis -> security_trust_level
                    ai_meta = email.get("ai_metadata") or {}
                    sec_meta = ai_meta.get("security_analysis") or {}
                    sec_trust_level = sec_meta.get("security_trust_level", "unverified")
                    if sec_trust_level not in ["unverified", "suspicious", "neutral", "trusted"]:
                        sec_trust_level = "unverified"

                    latest_email_info[t_id] = {
                        "sender_name": name or "Unknown",
                        "sender_email": email_addr or "unknown@email.com",
                        "security_trust_level": sec_trust_level
                    }
        except Exception as e:
            print(f"[THREADS WARNING] Failed to query emails for threads: {e}")

        # 4. Bulk fetch pending tasks for these threads to resolve tasks_count
        tasks_counts = {t_id: 0 for t_id in thread_ids}
        try:
            tasks_res = self.db.table("tasks") \
                .select("thread_id, status") \
                .in_("thread_id", thread_ids) \
                .execute()

            if tasks_res and tasks_res.data:
                for task in tasks_res.data:
                    t_id = task.get("thread_id")
                    st = task.get("status")
                    if t_id and st == "pending":
                        tasks_counts[t_id] = tasks_counts.get(t_id, 0) + 1
        except Exception as e:
            print(f"[THREADS WARNING] Failed to query tasks for threads: {e}")

        # 5. Format response to match frontend thread schema
        formatted_threads = []
        VALID_PRIORITIES = {"high", "medium", "low"}
        VALID_WORKFLOWS = {"needs_action", "awaiting_reply", "informational", "follow_up", "archived"}

        for t in threads:
            t_id = t["id"]
            e_info = latest_email_info.get(t_id, {})
            sender_name = e_info.get("sender_name", "Unknown")
            sender_email = e_info.get("sender_email", "unknown@email.com")
            security_trust_level = e_info.get("security_trust_level", "unverified")

            # Priority from email_threads DB column (default: "medium")
            raw_priority = (t.get("priority") or "").lower()
            priority = raw_priority if raw_priority in VALID_PRIORITIES else "medium"

            # Workflow status from email_threads DB column (default: "informational")
            raw_workflow = (t.get("workflow_status") or "").lower()
            workflow_status = raw_workflow if raw_workflow in VALID_WORKFLOWS else "informational"

            # Tasks count from tasks table
            tasks_count = tasks_counts.get(t_id, 0)

            # Unread status
            unread_count = t.get("unread_messages_count", 0)
            unread = bool(unread_count > 0 or t.get("unread", False))

            # Message count from emails in thread
            thread_emails = emails_by_thread.get(t_id, [])
            message_count = len(thread_emails) if thread_emails else 1

            formatted_threads.append({
                "id": t_id,
                "subject": t.get("subject") or "(No Subject)",
                "sender_name": sender_name,
                "sender_email": sender_email,
                "preview": t.get("snippet") or "",
                "summary": t.get("summary") or f"This is an automated AI summary of the thread '{t.get('subject') or '(No Subject)'}'.",
                "priority": priority,
                "workflow_status": workflow_status,
                "security_trust_level": security_trust_level,
                "tasks_count": tasks_count,
                "timestamp": t.get("last_message_at"),
                "unread": unread,
                "message_count": message_count,
                "account_email": account_email
            })

        return formatted_threads

    async def sync_user_inbox(self, account_id: str) -> bool:
        """
        Trigger backend email ingestion synchronously, skipping ML for performance.
        """
        from app.core.workers.sync_worker import EmailSyncWorker
        from app.core.services.auth_service import ConnectedAccountService

        auth_service = ConnectedAccountService(db_client=self.db)
        account = auth_service.get_account_by_id(account_id)
        if not account:
            raise Exception("Connected account profile not found.")

        # Initialize the sync worker with our active db client
        worker = EmailSyncWorker(db_client=self.db)
        
        # Execute the gmail fetch and database save cycle synchronously, skipping ML models
        await worker._process_account(account, skip_ml=True)
        return True

    async def smart_search(
        self,
        account_id: str,
        query: str,
        limit: int = 20,
        offset: int = 0,
        similarity_cutoff: float = 0.35
    ) -> List[Dict[str, Any]]:
        """
        Executes a semantic vector search using the match_emails Supabase RPC function.
        Derives associated tasks and contacts from the matched emails.
        """
        if not query or len(query.strip()) < 3:
            return []

        # 1. Embed the search query
        embedder = _get_embedder()
        query_embedding = embedder.generate_embeddings([query])[0]

        # 2. Call the database RPC match_emails function
        try:
            res = self.db.rpc("match_emails", {
                "query_embedding": query_embedding,
                "match_threshold": similarity_cutoff,
                "match_count": 100,  # search pool limit
                "p_account_id": account_id
            }).execute()
            matched_emails = res.data or []
        except Exception as e:
            print(f"[SEARCH ERROR] match_emails RPC execution failed: {e}")
            return []

        if not matched_emails:
            return []

        # 3. Extract thread IDs to fetch minimal associated tasks metadata in bulk
        thread_ids = list({e["thread_id"] for e in matched_emails if e.get("thread_id")})
        
        tasks_map = {}
        if thread_ids:
            try:
                tasks_res = self.db.table("tasks") \
                    .select("id, title, status, priority, thread_id") \
                    .in_("thread_id", thread_ids) \
                    .execute()
                
                for task in (tasks_res.data or []):
                    t_id = task["thread_id"]
                    if t_id not in tasks_map:
                        tasks_map[t_id] = []
                    tasks_map[t_id].append(task)
            except Exception as e:
                print(f"[SEARCH WARNING] Failed to query associated tasks: {e}")

        # 4. Format search results mapping (thread matches, task matches, contact matches)
        results = []
        contacts = {}

        for email in matched_emails:
            t_id = str(email["thread_id"]) if email.get("thread_id") else None
            sim = email["similarity"]
            
            # Add Thread match result (pointing directly to the email message)
            results.append({
                "id": f"email-{email['id']}",
                "type": "thread",
                "title": email["subject"] or "(No Subject)",
                "snippet": email["snippet"] or "",
                "relevance_score": sim,
                "timestamp": email["received_at"],
                "metadata": {
                    "sender": email["sender_name"] or email["sender"],
                    "priority": "medium",  # default priority
                    "threadId": t_id,
                    "emailId": str(email["id"])
                }
            })

            # Add associated Tasks results (inheriting match similarity slightly discounted)
            if t_id:
                assoc_tasks = tasks_map.get(t_id, [])
                for task in assoc_tasks:
                    results.append({
                        "id": f"task-{task['id']}",
                        "type": "task",
                        "title": task["title"],
                        "snippet": f"Task extracted from email: {email['subject'] or '(No Subject)'}",
                        "relevance_score": sim - 0.02,
                        "timestamp": email["received_at"],
                        "metadata": {
                            "priority": task.get("priority") or "medium",
                            "status": task.get("status") or "pending",
                            "threadId": t_id,
                            "emailId": str(email["id"])
                        }
                    })

                # Collect senders for Contact results mapping
                sender_name = email.get("sender_name")
                sender_email = email.get("sender")
                if sender_email:
                    contact_name = sender_name or sender_email.split("@")[0]
                    if sender_email not in contacts:
                        contacts[sender_email] = {
                            "name": contact_name,
                            "email": sender_email,
                            "max_score": sim,
                            "thread_count": 1,
                            "task_count": len(assoc_tasks),
                            "timestamp": email["received_at"],
                            "thread_id": t_id,
                            "email_id": str(email["id"])
                        }
                    else:
                        contacts[sender_email]["max_score"] = max(contacts[sender_email]["max_score"], sim)
                        contacts[sender_email]["thread_count"] += 1
                        contacts[sender_email]["task_count"] += len(assoc_tasks)

        # Append Contacts results compiled
        for email_addr, c_info in contacts.items():
            results.append({
                "id": f"contact-{email_addr}",
                "type": "contact",
                "title": c_info["name"],
                "snippet": f"Contact: {c_info['email']} — Linked to {c_info['thread_count']} thread(s) and {c_info['task_count']} task(s).",
                "relevance_score": c_info["max_score"] - 0.05,
                "timestamp": c_info["timestamp"],
                "metadata": {
                    "sender": c_info["email"],
                    "threadId": c_info["thread_id"],
                    "emailId": c_info["email_id"]
                }
            })

        # 5. Sort by relevance_score descending
        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        return results[offset : offset + limit]