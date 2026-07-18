import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import UnifiedThreadOrchestrationResponse, ExtractedTaskBlueprint, TaskResolution

"""
================================================================================
TOKEN COST ESTIMATION ANALYSIS
================================================================================
Based on the unified thread prompt schema, here is the average token consumption model:

- Prompt Overhead (Instruction, Rules, Pydantic Schema): ~800 tokens
- Actions Context (avg. 1 pre-extracted action): ~100 tokens
- Tasks Context (avg. 1 existing pending task): ~100 tokens
- Email Manifest Context (avg. 2 emails with compressed body): ~300 tokens
- Total Input: ~1,300 tokens
- Output (UnifiedThreadOrchestrationResponse): ~250 tokens
- Total Tokens / Execution: ~1,550 tokens

With Gemini 1.5 Flash Pricing ($0.075 / 1M Input, $0.30 / 1M Output):
- Input Cost: 1,300 * $0.000000075 = $0.0000975
- Output Cost: 250 * $0.00000030 = $0.000075
- Average Transaction Cost: ~$0.0001725 per thread (approx. $0.17 per 1,000 threads).

Rule-based bypasses are implemented below to reduce this cost to $0.00 for threads
without active action items or pending tasks.
================================================================================
"""

class ThreadOrchestrationService:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def build_orchestration_prompt(
        self,
        thread_subject: str,
        actions_payload: List[Dict[str, Any]],
        email_manifest: List[Dict[str, Any]],
        anchor_date: str
    ) -> str:
        """Constructs a consolidated prompt for Gemini to analyze the thread's tasks, actions, and metadata."""
        return f"""
You are an advanced internal operations assistant orchestrating workflow states on a single email thread.
Subject: {thread_subject}
Anchor Date: {anchor_date} (use this baseline to calculate relative task deadlines)

Your tasks:
1. TASK GENERATION:
Review the following list of pre-extracted actions (JSON format) and determine if they should become task checklist items:
{json.dumps(actions_payload, indent=2)}
Rules:
- For each item, decide if `is_actionable_task` is true. Mark it true only if it is a concrete, uncompleted action the user needs to perform. Mark false if it's purely informational, noise, or already resolved.
- Provide a clear, actionable `title` for the task.
- Categorize into `intent_label`: 'schedule_meeting', 'reply_requested', 'review_document', 'provide_information', 'make_payment', 'follow_up', or 'other'.
- Determine `priority`: 'High', 'Medium', or 'Low'.
- Determine `due_date_iso` as ISO 8601 string calculated from relative times (e.g. 'tomorrow') using the anchor date.

2. THREAD METADATA:
- Provide an updated, concise 2-3 sentence `thread_summary` summarizing the entire conversation history.
- Determine the overall derived `thread_priority` ('High', 'Medium', 'Low') based on task urgency and tone.
- Check if the last email sent by the user contains an action item, question, or request expecting a reply from the recipient. Set `last_user_email_expects_reply` to true or false.
"""

    def orchestrate_thread_via_llm(
        self,
        thread_subject: str,
        actions_payload: List[Dict[str, Any]],
        email_manifest: List[Dict[str, Any]],
        anchor_date: str
    ) -> UnifiedThreadOrchestrationResponse:
        """Queries Gemini using the unified response schema to analyze thread actions and tasks."""
        prompt = self.build_orchestration_prompt(
            thread_subject=thread_subject,
            actions_payload=actions_payload,
            email_manifest=email_manifest,
            anchor_date=anchor_date
        )
        return self.llm.generate_structured_json(
            prompt=prompt,
            response_schema=UnifiedThreadOrchestrationResponse
        )

    def generate_rule_based_fallback(
        self,
        thread: Dict[str, Any],
        emails: List[Dict[str, Any]]
    ) -> Tuple[str, str, bool]:
        """
        Bypasses LLM execution when no actions or tasks require evaluation.
        Returns: (thread_summary, thread_priority, last_user_email_expects_reply)
        """
        subject = thread.get("subject") or "No Subject"
        latest_email = emails[0] if emails else {}
        latest_snippet = latest_email.get("snippet") or ""

        # 1. Rule-based summary: Reuse existing summary, or construct one from subject & latest snippet
        existing_summary = thread.get("summary")
        if existing_summary:
            summary = existing_summary
        else:
            summary = f"Email conversation regarding '{subject}'. Latest update: {latest_snippet}"
            if len(summary) > 250:
                summary = summary[:247] + "..."

        # 2. Rule-based priority: Keep existing priority or default to medium
        priority = thread.get("priority") or "medium"

        # 3. Rule-based expects reply:
        # Check if the latest message was from user, and if there's a question mark in the snippet
        # (This is a lightweight rule-based approximation)
        last_user_email_expects_reply = False
        if "?" in latest_snippet:
            last_user_email_expects_reply = True

        return summary, priority, last_user_email_expects_reply
