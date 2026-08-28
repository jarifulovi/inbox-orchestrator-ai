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
        anchor_date: str,
        enable_auto_draft: bool = False
    ) -> str:
        """Constructs a consolidated prompt for Gemini to analyze the thread's initial tasks and metadata."""
        auto_draft_instruction = ""
        if enable_auto_draft:
            auto_draft_instruction = """
4. Auto-Draft Generation (because enable_auto_draft is True):
   - Evaluate if the email conversation permits drafting an automated response.
   - If missing private/unknown user decisions or policies, set `auto_draft.can_generate = False` and provide a brief `reason`.
   - If sufficient context exists, set `auto_draft.can_generate = True`, provide `recipient_to`, `subject` (e.g. 'Re: ...'), and draft `body`.
   - Use clear placeholders like [Insert Meeting Time] for minor missing variables.
"""
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
   - Leave `thread_summary`, `thread_priority`, `does_need_auto_draft`, and `auto_draft` as null (do not generate them).
3. If `has_actionable_tasks` is True:
   - Evaluate the action items. Set `is_actionable_task` to True only if it requires user action. Generate the actionable `title`, `intent_label`, `priority`, and `due_date_iso` (relative to anchor date).
   - Generate `thread_summary` (2-4 concise sentences), `thread_priority` ('High', 'Medium', 'Low'), and `does_need_auto_draft` (True/False).
{auto_draft_instruction}
"""

    def build_thread_update_prompt(
        self,
        thread_subject: str,
        existing_summary: str,
        pending_tasks: List[Dict[str, Any]],
        new_actions_payload: List[Dict[str, Any]],
        new_email_snippet: str,
        anchor_date: str,
        enable_auto_draft: bool = False
    ) -> str:
        """Constructs a delta prompt for Gemini when a new email arrives on an existing thread."""
        auto_draft_instruction = ""
        if enable_auto_draft:
            auto_draft_instruction = """
4. Auto-Draft Generation (because enable_auto_draft is True):
   - Evaluate if the email conversation permits drafting an automated response.
   - If missing private/unknown user decisions or policies, set `auto_draft.can_generate = False` and provide a brief `reason`.
   - If sufficient context exists, set `auto_draft.can_generate = True`, provide `recipient_to`, `subject`, and draft `body`.
   - Use clear placeholders like [Insert Meeting Time] for minor missing variables.
"""
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
2. Determine `has_actionable_tasks`.
3. If `has_actionable_tasks` is True:
   - Extract ONLY new, concrete actionable tasks created by this incoming email in `task_generations`.
   - Generate an updated, merged `thread_summary` (4-6 concise sentences incorporating the new development), updated `thread_priority`, and `does_need_auto_draft`.
{auto_draft_instruction}
"""

    def orchestrate_thread_via_llm(
        self,
        thread_subject: str,
        actions_payload: List[Dict[str, Any]],
        email_manifest: List[Dict[str, Any]],
        anchor_date: str,
        enable_auto_draft: bool = False
    ) -> UnifiedThreadOrchestrationResponse:
        """Queries Gemini using the unified response schema to analyze thread actions and tasks."""
        prompt = self.build_orchestration_prompt(
            thread_subject=thread_subject,
            actions_payload=actions_payload,
            email_manifest=email_manifest,
            anchor_date=anchor_date,
            enable_auto_draft=enable_auto_draft
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
        anchor_date: str,
        enable_auto_draft: bool = False
    ) -> UnifiedThreadOrchestrationResponse:
        """Queries Gemini for delta analysis on an existing thread when a new email arrives."""
        prompt = self.build_thread_update_prompt(
            thread_subject=thread_subject,
            existing_summary=existing_summary,
            pending_tasks=pending_tasks,
            new_actions_payload=new_actions_payload,
            new_email_snippet=new_email_snippet,
            anchor_date=anchor_date,
            enable_auto_draft=enable_auto_draft
        )
        return self.llm.generate_structured_json(
            prompt=prompt,
            response_schema=UnifiedThreadOrchestrationResponse
        )

    def build_manual_draft_prompt(
        self,
        thread_subject: str,
        existing_summary: str,
        latest_email_snippet: str,
        email_facts: List[Dict[str, Any]],
        resolved_tasks: List[Dict[str, Any]],
        ai_instructions: str,
        tone: str = "Professional"
    ) -> str:
        """Constructs an engineered prompt for user-triggered (manual) AI draft reply generation."""
        facts_block = json.dumps(email_facts, indent=2) if email_facts else "None"
        tasks_block = json.dumps(resolved_tasks, indent=2) if resolved_tasks else "None"
        clean_instr = (ai_instructions or "").strip()
        instructions_text = clean_instr if clean_instr else "Respond appropriately to the incoming email."

        tone_rules = {
          "Professional": "Maintain a polished, respectful, and professional executive tone.",
          "Concise": "Keep the reply extremely brief, clear, and direct (max 2-3 short sentences).",
          "Friendly": "Use a warm, collaborative, and approachable tone while remaining clear.",
          "Urgent": "Communicate with a sense of urgency, highlighting deadlines and immediate next steps.",
        }
        selected_tone_rule = tone_rules.get(tone, tone_rules["Professional"])

        return f"""
You are an executive email communication assistant drafting a direct reply on behalf of the user.

Thread Subject: {thread_subject}

Prior Thread Summary:
{existing_summary or "Initial conversation thread."}

Pre-extracted Action Items / Facts:
{facts_block}

Latest Received Email (Message you are replying to):
{latest_email_snippet or "No recent text."}

Tasks Selected for Resolution via this Reply:
{tasks_block}

User's Specific Directives / Instructions:
{instructions_text}

Tone Directive: {selected_tone_rule}

Instructions & Constraints:
1. Write a contextually accurate, high-quality email response addressing the latest received email.
2. Incorporate the user's specific directives and acknowledge the task resolutions if tasks are specified.
3. Apply the requested tone ({tone}).
4. Output ONLY the plain text email response content (greeting, body paragraphs, and sign-off).
5. Do NOT include robotic meta-commentary, subject headers, or intro lines like "Here is your draft:".
6. If critical specific details requested by the user are missing, use clean placeholders like [Insert Time] or [Insert Link].
"""

    def generate_manual_draft(
        self,
        thread_subject: str,
        existing_summary: str,
        latest_email_snippet: str,
        email_facts: List[Dict[str, Any]],
        resolved_tasks: List[Dict[str, Any]],
        ai_instructions: str,
        tone: str = "Professional"
    ) -> str:
        """Queries Gemini LLM API to generate plain text manual draft reply content."""
        prompt = self.build_manual_draft_prompt(
            thread_subject=thread_subject,
            existing_summary=existing_summary,
            latest_email_snippet=latest_email_snippet,
            email_facts=email_facts,
            resolved_tasks=resolved_tasks,
            ai_instructions=ai_instructions,
            tone=tone
        )
        raw_text = self.llm.generate_text(prompt=prompt)
        return raw_text.strip() if raw_text else ""

