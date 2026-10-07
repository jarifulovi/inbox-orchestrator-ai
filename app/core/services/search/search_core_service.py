import re
from typing import List, Dict, Any, Optional
from supabase import Client
from app.core.db.supabase import get_supabase_client

import os
import math
import json
import httpx
import urllib.request


def _parse_hf_vector(data: Any) -> Optional[List[float]]:
    if isinstance(data, list):
        if data and isinstance(data[0], (int, float)):
            return [float(x) for x in data]
        if data and isinstance(data[0], list) and isinstance(data[0][0], (int, float)):
            return [float(x) for x in data[0]]
        if data and isinstance(data[0], list) and isinstance(data[0][0], list):
            tokens = data[0]
            dim = len(tokens[0])
            return [sum(float(token[i]) for token in tokens) / len(tokens) for i in range(dim)]
    return None


async def _get_query_embedding(query: str) -> List[float]:
    """
    Generates a 384-dimensional query vector for Smart Vector Search.
    1. Local Dev: Uses local EmailEmbedder if PyTorch is installed locally (~10ms).
    2. Deployed Production (Render): Uses Gemini Embedding API (0 MB RAM, 0 Cost, 384-dim).
    """
    # 1. Try local PyTorch EmailEmbedder first (fast local dev)
    try:
        from app.core.ml_models.embedder.embedder import EmailEmbedder
        vec = EmailEmbedder().generate_embeddings([query])[0]
        if vec and len(vec) == 384:
            return vec
    except Exception:
        pass

    # 2. Deployed Production Fallback: Gemini Embedding API (0 MB RAM)
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={gemini_key}"
            payload = {
                "content": {"parts": [{"text": query}]},
                "output_dimensionality": 384
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    vec = res.json().get("embedding", {}).get("values", [])
                    if vec and len(vec) == 384:
                        return vec
        except Exception as ex:
            print(f"[SEARCH EMBEDDING WARNING] Gemini Cloud Embedding failed: {ex}")

    return [0.0] * 384


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

        # 2. Generate query embedding via lightweight HTTP call
        query_embedding = await _get_query_embedding(query)
        is_zero_vector = not query_embedding or all(abs(v) < 1e-9 for v in query_embedding)

        matched_emails: List[Dict[str, Any]] = []

        if is_zero_vector:
            # Fallback to precise text keyword search if vector service is offline
            print("🔍 [SEARCH LOG] Vector service unavailable. Executing database text keyword fallback query...")
            try:
                text_res = self.db.table("emails") \
                    .select("id, thread_id, subject, snippet, sender, sender_name, received_at, recipients") \
                    .eq("connected_account_id", account_id) \
                    .or_(f"subject.ilike.%{query}%,snippet.ilike.%{query}%,body.ilike.%{query}%") \
                    .order("received_at", desc=True) \
                    .limit(max_results * 2) \
                    .execute()
                matched_emails = text_res.data or []
            except Exception as ex:
                print(f"[SEARCH ERROR] Text keyword search fallback failed: {ex}")
                matched_emails = []
        else:
            # 3. Tiered Threshold Schedule with Early Exit for Vector Search
            threshold_schedule = [
                (0.65, 3),  # Tier 1: High confidence (exit if >= 3 matches)
                (0.45, 1),  # Tier 2: Moderate confidence (exit if >= 1 match)
                (0.25, 1)   # Tier 3: Broad fallback
            ]

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

        # Fetch full email details for matched email IDs if missing subject/snippet
        matched_email_ids = [str(e["id"]) for e in matched_emails if e.get("id")]
        email_details_map = {}
        if matched_email_ids:
            try:
                details_res = self.db.table("emails") \
                    .select("id, thread_id, subject, snippet, sender, sender_name, received_at, recipients") \
                    .in_("id", matched_email_ids) \
                    .execute()
                if details_res and details_res.data:
                    email_details_map = {str(d["id"]): d for d in details_res.data}
            except Exception as ex:
                print(f"[SEARCH ERROR] Failed to fetch email details: {ex}")

        # 4. Build Thread Match Results (Deduplicated by thread_id) & Extract Contacts
        thread_results: List[Dict[str, Any]] = []
        seen_threads = set()
        contacts_map: Dict[str, Dict[str, Any]] = {}

        for email in matched_emails:
            e_id = str(email.get("id"))
            details = email_details_map.get(e_id, {})
            # Merge details into email dict
            subject_val = email.get("subject") or details.get("subject")
            snippet_val = email.get("snippet") or details.get("snippet")
            sender_val = email.get("sender") or details.get("sender")
            sender_name_val = email.get("sender_name") or details.get("sender_name")
            received_at_val = email.get("received_at") or details.get("received_at")
            t_id = str(email["thread_id"]) if email.get("thread_id") else None
            try:
                raw_sim = email.get("similarity")
                sim_val = float(raw_sim) if raw_sim is not None else 0.0
                if math.isnan(sim_val) or math.isinf(sim_val):
                    sim_val = 0.0
            except (ValueError, TypeError):
                sim_val = 0.0

            # Deduplicate threads
            if t_id and t_id not in seen_threads:
                seen_threads.add(t_id)
                thread_results.append({
                    "id": f"thread-{t_id}",
                    "type": "thread",
                    "title": subject_val or "(No Subject)",
                    "snippet": snippet_val or "",
                    "relevance_score": sim_val,
                    "timestamp": received_at_val,
                    "metadata": {
                        "sender": sender_name_val or sender_val or "",
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
                        contact_score = max(0.0, sim_val - 0.05)
                        if math.isnan(contact_score) or math.isinf(contact_score):
                            contact_score = 0.0
                        contacts_map[p_email] = {
                            "id": f"contact-{p_email}",
                            "type": "contact",
                            "title": p_name.title() if p_name else p_email,
                            "snippet": f"Contact: {p_email}",
                            "relevance_score": contact_score,
                            "timestamp": email.get("received_at"),
                            "metadata": {
                                "email": p_email,
                                "name": p_name
                            }
                        }

        # Combine Thread results + Contact results (sorted by relevance score)
        contact_results = list(contacts_map.values())
        combined_results = thread_results + contact_results

        def _safe_sort_key(item: Dict[str, Any]) -> float:
            try:
                val = float(item.get("relevance_score") or 0.0)
                return 0.0 if math.isnan(val) or math.isinf(val) else val
            except Exception:
                return 0.0

        combined_results.sort(key=_safe_sort_key, reverse=True)

        return combined_results[:max_results]
