import re
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


def _extract_email_address(raw_str: str) -> str:
    """Extracts clean email address from string format like 'John Doe <john@example.com>'."""
    if not raw_str:
        return ""
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', raw_str)
    return match.group(0).lower() if match else raw_str.strip().lower()


class CoreSearchService:
    """
    Core Domain Service for Dynamic Cosine Similarity Relaxation Search.
    Executes tiered vector search, early exit optimization, thread deduplication,
    contact extraction (sender + CC/To recipients), and hard capping without web layer dependencies.
    """

    def __init__(self, db_client: Optional[Client] = None):
        self.db = db_client or get_supabase_client()

    async def smart_search(
        self,
        account_id: str,
        query: str,
        max_results: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Executes dynamic threshold relaxation semantic search (0.65 -> 0.45 -> 0.25).
        Groups results by thread, extracts associated contacts (sender + CC/To),
        excludes tasks from search results, and hard caps output to max_results.
        """
        if not query or len(query.strip()) < 3:
            return []

        # 1. Fetch connected account's user provider email to filter out self from contacts
        user_email = ""
        try:
            acc_res = self.db.table("connected_accounts") \
                .select("provider_email") \
                .eq("id", account_id) \
                .single() \
                .execute()
            if acc_res and acc_res.data:
                user_email = (acc_res.data.get("provider_email") or "").lower()
        except Exception:
            pass

        # 2. Generate query embedding ONCE (local_files_only=True disk load)
        embedder = _get_embedder()
        query_embedding = embedder.generate_embeddings([query])[0]

        # 3. Tiered Threshold Schedule with Early Exit
        threshold_schedule = [
            (0.65, 3),  # Tier 1: High confidence (exit if >= 3 matches)
            (0.45, 1),  # Tier 2: Moderate confidence (exit if >= 1 match)
            (0.25, 1)   # Tier 3: Broad fallback
        ]

        matched_emails: List[Dict[str, Any]] = []

        for threshold, min_matches in threshold_schedule:
            try:
                res = self.db.rpc("match_emails", {
                    "query_embedding": query_embedding,
                    "match_threshold": threshold,
                    "match_count": max_results * 2,
                    "p_account_id": account_id
                }).execute()
                current_matches = res.data or []

                if len(current_matches) >= min_matches:
                    matched_emails = current_matches
                    print(f"🎯 [SEARCH LOG] Tier hit at threshold {threshold} ({len(current_matches)} matches found). Exiting early!")
                    break
                elif len(current_matches) > len(matched_emails):
                    matched_emails = current_matches
            except Exception as e:
                print(f"[SEARCH ERROR] match_emails RPC failed at threshold {threshold}: {e}")

        if not matched_emails:
            return []

        # 4. Build Thread Match Results (Deduplicated by thread_id) & Extract Contacts
        thread_results: List[Dict[str, Any]] = []
        seen_threads = set()
        contacts_map: Dict[str, Dict[str, Any]] = {}

        for email in matched_emails:
            t_id = str(email["thread_id"]) if email.get("thread_id") else None
            sim = email.get("similarity", 0.0)

            # Deduplicate threads
            if t_id and t_id not in seen_threads:
                seen_threads.add(t_id)
                thread_results.append({
                    "id": f"thread-{t_id}",
                    "type": "thread",
                    "title": email.get("subject") or "(No Subject)",
                    "snippet": email.get("snippet") or "",
                    "relevance_score": sim,
                    "timestamp": email.get("received_at"),
                    "metadata": {
                        "sender": email.get("sender_name") or email.get("sender", ""),
                        "priority": "medium",
                        "threadId": t_id,
                        "emailId": str(email["id"])
                    }
                })

            # Extract contacts from Sender and Recipients (To, CC, BCC)
            participants = []

            # Sender contact
            sender_raw = email.get("sender") or ""
            sender_name = email.get("sender_name") or ""
            sender_clean = _extract_email_address(sender_raw)
            if sender_clean:
                participants.append((sender_clean, sender_name or sender_clean.split("@")[0]))

            # Recipients contacts (To, CC, BCC)
            recipients_data = email.get("recipients") or []
            if isinstance(recipients_data, list):
                for r in recipients_data:
                    if isinstance(r, str):
                        clean_r = _extract_email_address(r)
                        if clean_r:
                            participants.append((clean_r, clean_r.split("@")[0]))
                    elif isinstance(r, dict):
                        raw_addr = r.get("email") or r.get("address") or ""
                        clean_r = _extract_email_address(raw_addr)
                        raw_name = r.get("name") or (clean_r.split("@")[0] if clean_r else "")
                        if clean_r:
                            participants.append((clean_r, raw_name))

            # Aggregate unique contacts (excluding user's own email)
            for p_email, p_name in participants:
                if p_email and p_email != user_email:
                    if p_email not in contacts_map:
                        contacts_map[p_email] = {
                            "id": f"contact-{p_email}",
                            "type": "contact",
                            "title": p_name.title() if p_name else p_email,
                            "snippet": f"Contact: {p_email}",
                            "relevance_score": max(0.0, sim - 0.05),
                            "timestamp": email.get("received_at"),
                            "metadata": {
                                "email": p_email,
                                "name": p_name
                            }
                        }

        # Combine Thread results + Contact results (sorted by relevance score)
        contact_results = list(contacts_map.values())
        combined_results = thread_results + contact_results
        combined_results.sort(key=lambda x: x["relevance_score"], reverse=True)

        return combined_results[:max_results]
