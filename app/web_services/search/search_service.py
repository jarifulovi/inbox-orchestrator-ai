# app/web_services/search/search_service.py
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


class SearchWebService:
    """
    Dedicated web service for Semantic & Hybrid Vector Search operations.
    Encapsulates ML embedding generation and vector RPC execution.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client or get_supabase_client()

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
                            "id": f"contact-{sender_email}",
                            "type": "contact",
                            "title": contact_name,
                            "snippet": f"Contact: {sender_email}",
                            "relevance_score": sim - 0.05,
                            "timestamp": email["received_at"],
                            "metadata": {
                                "email": sender_email,
                                "name": contact_name
                            }
                        }

        # Append aggregated contacts to search results
        results.extend(list(contacts.values()))

        # Sort combined results by relevance score in descending order
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results[offset:offset + limit]
