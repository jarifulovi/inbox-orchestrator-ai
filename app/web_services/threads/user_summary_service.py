import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.core.llm.client import LLMClient
from app.schemas.thread_schemas import UserThreadSummaryOutput
from app.core.services.utils.llm_content_compressor import LLMContentCompressorService


class UserThreadSummaryService:
    """
    Service for user-initiated manual thread summary generation.
    Employs a hybrid context strategy:
    - Newest 3 emails: Full content (no facts needed).
    - Older emails (4+): Pre-extracted facts + capped snippet (150 chars max).
    - Strict output boundary: 3-5 concise sentences summary.
    """

    RECENT_MESSAGES_COUNT = 3
    MAX_HISTORICAL_SNIPPET_LENGTH = 150

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def build_user_summary_prompt(
        self,
        thread_subject: str,
        emails: List[Dict[str, Any]],
        facts: List[Dict[str, Any]],
        pending_tasks: List[Dict[str, Any]],
        existing_summary: Optional[str] = None,
        summary_format: str = "paragraph"
    ) -> str:
        """
        Constructs prompt partitioning recent vs historical emails into a hybrid context payload.
        emails are expected to be ordered by received_at DESC (newest first).
        """
        # 1. Partition emails (Top 3 = Recent Full Content, 4+ = Historical Facts + Capped Snippet)
        recent_emails = emails[:self.RECENT_MESSAGES_COUNT]
        historical_emails = emails[self.RECENT_MESSAGES_COUNT:]

        facts_by_email_id: Dict[str, List[Dict[str, Any]]] = {}
        for f in facts:
            e_id = f.get("email_id")
            if e_id:
                facts_by_email_id.setdefault(e_id, []).append(f)

        # Format Recent Messages (Full Content)
        recent_formatted = []
        for idx, e in enumerate(reversed(recent_emails), start=1):
            sender_info = f"{e.get('sender_name') or ''} <{e.get('sender') or ''}>".strip()
            body_clean = LLMContentCompressorService.compress_email_body(e.get("body") or "")
            recent_formatted.append(
                f"--- [Recent Message #{idx}] ---\n"
                f"From: {sender_info}\n"
                f"Received: {e.get('received_at')}\n"
                f"Body:\n{body_clean}\n"
            )

        recent_context_str = "\n".join(recent_formatted) if recent_formatted else "No recent messages."

        # Format Historical Messages (Facts + 150-char Capped Snippet)
        historical_formatted = []
        if historical_emails:
            for idx, e in enumerate(reversed(historical_emails), start=1):
                e_id = e.get("id")
                e_facts = facts_by_email_id.get(e_id, [])
                sender_info = f"{e.get('sender_name') or ''} <{e.get('sender') or ''}>".strip()
                
                # Cap snippet strictly to MAX_HISTORICAL_SNIPPET_LENGTH
                hist_body = e.get("body") if isinstance(e.get("body"), str) else ""
                raw_snippet = e.get("snippet") or (hist_body[:150] if hist_body else "")
                capped_snippet = raw_snippet[:self.MAX_HISTORICAL_SNIPPET_LENGTH]

                facts_summary = []
                for f in e_facts:
                    source_sent = f.get("source_sentence")
                    if source_sent:
                        facts_summary.append(f"- Fact: {source_sent}")

                facts_str = "\n".join(facts_summary) if facts_summary else "No pre-extracted facts available."

                historical_formatted.append(
                    f"--- [Older Message #{idx}] ---\n"
                    f"From: {sender_info} | Received: {e.get('received_at')}\n"
                    f"Snippet: {capped_snippet}\n"
                    f"Extracted Facts:\n{facts_str}\n"
                )

        historical_context_str = "\n".join(historical_formatted) if historical_formatted else "None (Thread has 3 or fewer total messages)."

        # Format Pending Tasks
        tasks_formatted = [
            f"- Task: {t.get('title')} (Status: {t.get('status', 'pending')})"
            for t in pending_tasks
        ]
        tasks_str = "\n".join(tasks_formatted) if tasks_formatted else "None."

        # Format Existing Summary
        summary_refinement = f"Previous Summary:\n{existing_summary}\n" if existing_summary else ""

        summary_style_text = "3 to 5 concise sentences (max 120 words)"
        if summary_format == "bullets":
            summary_style_text = "3 to 4 concise bullet points separated by line breaks"
        elif summary_format == "concise":
            summary_style_text = "1 to 2 sharp, highly concise sentences"

        # Construct Final Prompt
        return f"""
You are an expert executive email assistant synthesizing an email thread into a clear summary.

Thread Subject: {thread_subject}
{summary_refinement}
Active Pending Tasks:
{tasks_str}

### SECTION 1: RECENT MESSAGES
{recent_context_str}

### SECTION 2: HISTORICAL CONVERSATION BACKGROUND
{historical_context_str}

### INSTRUCTIONS FOR SUMMARY GENERATION:
1. Synthesize the entire conversation thread into a clean `summary`.
2. **STRICT SIZE BOUNDARY**: The `summary` MUST be {summary_style_text}. Focus on key topics discussed, current decisions/status, and what action remains. Avoid long text walls.
3. Determine `priority`: 'high', 'medium', or 'low' based on urgency and importance.
4. Provide `key_takeaways`: exactly 2 to 3 concise bullet point key takeaways.
"""

    def generate_summary_via_llm(
        self,
        thread_subject: str,
        emails: List[Dict[str, Any]],
        facts: List[Dict[str, Any]],
        pending_tasks: List[Dict[str, Any]],
        existing_summary: Optional[str] = None,
        summary_format: str = "paragraph",
        model: Optional[str] = None
    ) -> UserThreadSummaryOutput:
        """
        Executes summary generation via Gemini LLM with Pydantic structured output.
        Falls back gracefully to rule-based fallback if LLM call fails.
        """
        if not emails:
            return UserThreadSummaryOutput(
                summary="No email messages available in this thread to summarize.",
                priority="low",
                key_takeaways=["No messages found."]
            )

        prompt = self.build_user_summary_prompt(
            thread_subject=thread_subject,
            emails=emails,
            facts=facts,
            pending_tasks=pending_tasks,
            existing_summary=existing_summary,
            summary_format=summary_format
        )

        try:
            output = self.llm.generate_structured_json(
                prompt=prompt,
                response_schema=UserThreadSummaryOutput,
                model=model
            )
            return output
        except Exception as e:
            print(f"[UserThreadSummaryService ERROR] LLM summary generation failed: {e}. Utilizing fallback.")
            return self.generate_fallback_summary(thread_subject, emails, existing_summary)

    def generate_fallback_summary(
        self,
        thread_subject: str,
        emails: List[Dict[str, Any]],
        existing_summary: Optional[str] = None
    ) -> UserThreadSummaryOutput:
        """Generates a rule-based fallback summary when LLM is unavailable."""
        import html
        newest = emails[0] if emails else {}
        body_text = newest.get("body") if isinstance(newest.get("body"), str) else ""
        raw_snippet = newest.get("snippet") or (body_text[:300] if body_text else "")
        cleaned_snippet = html.unescape(raw_snippet).strip()

        if existing_summary:
            fallback_text = existing_summary
        elif cleaned_snippet:
            fallback_text = cleaned_snippet
        else:
            fallback_text = f"Email discussion regarding {thread_subject}."

        sender_label = newest.get("sender_name") or newest.get("sender") or "sender"
        return UserThreadSummaryOutput(
            summary=fallback_text,
            priority="medium",
            key_takeaways=[f"Latest update from {sender_label}."]
        )
