import json
from typing import List, Dict, Any
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import UnifiedThreadOrchestrationResponse

"""
================================================================================
TOKEN COST ESTIMATION ANALYSIS
================================================================================
Based on the optimized schema (no task resolutions, nullable output properties), 
here is the average token consumption model:

1. Actionable Threads (has_actionable_tasks = True):
   - Prompt Overhead (Instruction, Rules, Pydantic Schema): ~650 tokens
   - Facts/Actions Context (avg. 1 fact): ~100 tokens
   - Email Manifest Context (avg. 2 compressed emails): ~300 tokens
   - Total Input: ~1,050 tokens
   - Output (Full task list, summary, priority): ~200 tokens
   - Total Tokens: ~1,250 tokens
   - Cost (Input $0.075/1M, Output $0.30/1M): ~$0.000138 per thread ($0.14 / 1k threads)

2. Non-Actionable/System Threads (has_actionable_tasks = False):
   - Total Input: ~1,050 tokens
   - Output (Empty arrays/nulls): ~30 tokens
   - Total Tokens: ~1,080 tokens
   - Cost (Input $0.075/1M, Output $0.30/1M): ~$0.000088 per thread ($0.09 / 1k threads)
================================================================================
"""

class ThreadLLMService:
    """Dedicated service for LLM prompt construction, structured output, and schema validation."""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def build_orchestration_prompt(
        self,
        thread_subject: str,
        actions_payload: List[Dict[str, Any]],
        email_manifest: List[Dict[str, Any]],
        anchor_date: str
    ) -> str:
        """Constructs a consolidated prompt for Gemini to analyze the thread's initial tasks and metadata."""
        return f"""
You are an advanced email operations manager.
Subject: {thread_subject}
Anchor Date: {anchor_date}

Pre-extracted action items (tasks, commitments, questions):
{json.dumps(actions_payload, indent=2)}

Instructions:
1. Determine `has_actionable_tasks`. Set to True if there is at least one new, concrete task that demands human action. Set to False for generic system updates, newsletters, subscription notices, automated server stats, status alerts, or closures. Only focus on critical updates that demand task actions (e.g., Jira tickets, server down alerts, "action required" billing updates).
2. If `has_actionable_tasks` is False:
   - Set `task_generations` to an empty list.
   - Leave `thread_summary`, `thread_priority`, and `does_need_auto_draft` as null (do not generate them).
3. If `has_actionable_tasks` is True:
   - Evaluate the action items. Set `is_actionable_task` to True only if it requires user action. Generate the actionable `title`, `intent_label`, `priority`, and `due_date_iso` (relative to anchor date).
   - Generate `thread_summary` (2-4 concise sentences), `thread_priority` ('High', 'Medium', 'Low'), and `does_need_auto_draft` (True/False).
"""

    def build_thread_update_prompt(
        self,
        thread_subject: str,
        existing_summary: str,
        pending_tasks: List[Dict[str, Any]],
        new_actions_payload: List[Dict[str, Any]],
        new_email_snippet: str,
        anchor_date: str
    ) -> str:
        """Constructs a delta prompt for Gemini when a new email arrives on an existing thread."""
        return f"""
You are an advanced email operations manager.
Subject: {thread_subject}
Anchor Date: {anchor_date}

Prior Thread Summary:
{existing_summary}

Currently Active Pending Tasks:
{json.dumps(pending_tasks, indent=2)}

New Incoming Email Snippet:
{new_email_snippet}

Pre-extracted action items from incoming email (tasks, commitments, questions):
{json.dumps(new_actions_payload, indent=2)}

Instructions:
1. Analyze the new incoming email and action items in relation to the prior thread summary and pending tasks.
2. Determine `has_actionable_tasks`:
   - Set to True if there are NEW actionable tasks arising from the incoming email that demand human action.
   - Set to False if the incoming email is routine noise, autoreply, or simple acknowledgment without new task requirements.
3. If `has_actionable_tasks` is True:
   - Extract ONLY new, concrete actionable tasks created by this incoming email in `task_generations`.
   - Generate an updated, merged `thread_summary` (4-6 concise sentences incorporating the new development), updated `thread_priority`, and `does_need_auto_draft`.
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

    def orchestrate_thread_update_via_llm(
        self,
        thread_subject: str,
        existing_summary: str,
        pending_tasks: List[Dict[str, Any]],
        new_actions_payload: List[Dict[str, Any]],
        new_email_snippet: str,
        anchor_date: str
    ) -> UnifiedThreadOrchestrationResponse:
        """Queries Gemini for delta analysis on an existing thread when a new email arrives."""
        prompt = self.build_thread_update_prompt(
            thread_subject=thread_subject,
            existing_summary=existing_summary,
            pending_tasks=pending_tasks,
            new_actions_payload=new_actions_payload,
            new_email_snippet=new_email_snippet,
            anchor_date=anchor_date
        )
        return self.llm.generate_structured_json(
            prompt=prompt,
            response_schema=UnifiedThreadOrchestrationResponse
        )

