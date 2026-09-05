import json
from typing import List, Dict, Any, Optional
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import UnifiedThreadOrchestrationResponse
from app.core.services.utils.llm_content_compressor import LLMContentCompressorService

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

THREAD_ORCHESTRATION_SYSTEM_INSTRUCTION = """
You are an advanced email operations manager analyzing conversation threads.

INSTRUCTIONS:
1. Determine `has_actionable_tasks`. Set to True if there is at least one new, concrete task that demands human action. Set to False for generic system updates, newsletters, subscription notices, automated server stats, status alerts, or closures. Only focus on critical updates that demand task actions.
2. If `has_actionable_tasks` is False:
   - Set `task_generations` to an empty list.
   - Leave `thread_summary`, `thread_priority`, and `auto_draft` as null.
3. If `has_actionable_tasks` is True:
   - Evaluate action items. Set `is_actionable_task` to True only if it requires user action. Generate actionable `title`, `intent_label`, `priority`, and `due_date_iso` (relative to anchor date).
   - Generate `thread_summary` and `thread_priority` ('High', 'Medium', 'Low').
4. Auto-Draft Generation (when enabled):
   - Evaluate if the email conversation permits drafting an automated response.
   - If missing private/unknown user decisions, set `auto_draft.can_generate = False` and provide a brief `reason`.
   - If sufficient context exists, set `auto_draft.can_generate = True`, provide `recipient_to`, `subject`, and draft `body`.
""".strip()

MANUAL_DRAFT_SYSTEM_INSTRUCTION = """
You are an executive email communication assistant drafting direct replies on behalf of the user.

TONE DEFINITIONS:
- Professional: Maintain a polished, respectful, and professional executive tone.
- Concise: Keep the reply extremely brief, clear, and direct (max 2-3 short sentences).
- Friendly: Use a warm, collaborative, and approachable tone while remaining clear.
- Urgent: Communicate with a sense of urgency, highlighting deadlines and immediate next steps.

INSTRUCTIONS & CONSTRAINTS:
1. Write a contextually accurate email response addressing the latest received email.
2. Incorporate user directives and acknowledge task resolutions if specified.
3. Apply requested tone directive specified in the request. Output ONLY plain text response (greeting, body, sign-off).
4. Do NOT include robotic meta-commentary, subject headers, or intro lines like "Here is your draft:".
5. Use clean placeholders like [Insert Time] or [Insert Link] for minor missing variables.
""".strip()


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
        enable_auto_draft: bool = False,
        summary_format: str = "paragraph"
    ) -> str:
        """Constructs a consolidated prompt for Gemini to analyze the thread's initial tasks and metadata."""
        auto_draft_instruction = ""
        if enable_auto_draft:
            auto_draft_instruction = "\nNote: Auto-Draft generation is requested for this external actionable thread.\n"

        summary_style_text = "2-4 concise executive paragraph sentences"
        if summary_format == "bullets":
            summary_style_text = "3-4 concise bullet points separated by line breaks"
        elif summary_format == "concise":
            summary_style_text = "1-2 sharp, highly concise summary sentences"

        return f"""
Subject: {thread_subject}
Anchor Date: {anchor_date}
Requested Summary Format: {summary_style_text}

Pre-extracted action items (tasks, commitments, questions):
{json.dumps(actions_payload, indent=2)}

Email Manifest:
{json.dumps(email_manifest, indent=2)}
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
            auto_draft_instruction = "\nNote: Auto-Draft generation is requested for this external actionable thread.\n"

        return f"""
Subject: {thread_subject}
Anchor Date: {anchor_date}

Prior Thread Summary:
{existing_summary}

Currently Active Pending Tasks:
{json.dumps(pending_tasks, indent=2)}

New Incoming Email Snippet:
{new_email_snippet}

Pre-extracted action items from incoming email:
{json.dumps(new_actions_payload, indent=2)}
{auto_draft_instruction}
"""

    def orchestrate_thread_via_llm(
        self,
        thread_subject: str,
        actions_payload: List[Dict[str, Any]],
        email_manifest: List[Dict[str, Any]],
        anchor_date: str,
        enable_auto_draft: bool = False,
        summary_format: str = "paragraph",
        model: Optional[str] = None
    ) -> UnifiedThreadOrchestrationResponse:
        """Queries Gemini using the unified response schema to analyze thread actions and tasks."""
        prompt = self.build_orchestration_prompt(
            thread_subject=thread_subject,
            actions_payload=actions_payload,
            email_manifest=email_manifest,
            anchor_date=anchor_date,
            enable_auto_draft=enable_auto_draft,
            summary_format=summary_format
        )
        return self.llm.generate_structured_json(
            prompt=prompt,
            response_schema=UnifiedThreadOrchestrationResponse,
            model=model,
            system_instruction=THREAD_ORCHESTRATION_SYSTEM_INSTRUCTION
        )

    def orchestrate_thread_update_via_llm(
        self,
        thread_subject: str,
        existing_summary: str,
        pending_tasks: List[Dict[str, Any]],
        new_actions_payload: List[Dict[str, Any]],
        new_email_snippet: str,
        anchor_date: str,
        enable_auto_draft: bool = False,
        summary_format: str = "paragraph",
        model: Optional[str] = None
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
            response_schema=UnifiedThreadOrchestrationResponse,
            model=model,
            system_instruction=THREAD_ORCHESTRATION_SYSTEM_INSTRUCTION
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
        # Compress latest email text to strip HTML bloat, signatures, carriage returns, and tracking URLs
        compressed_latest_email = LLMContentCompressorService.compress_email_body(latest_email_snippet or "")

        # Smart Facts Inclusion: If existing_summary is present, it encapsulates historical context so omit email_facts.
        # If existing_summary is missing, cap historical email_facts at max 5 total.
        facts_section = ""
        if not existing_summary and email_facts:
            capped_facts = email_facts[:5]
            facts_block = json.dumps(capped_facts, indent=2)
            facts_section = f"\nPre-extracted Action Items / Historical Facts:\n{facts_block}\n"

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

        summary_block = f"\nPrior Thread Summary:\n{existing_summary}\n" if existing_summary else ""

        return f"""
Thread Subject: {thread_subject}
{summary_block}{facts_section}
Latest Received Email (Message you are replying to):
{compressed_latest_email or "No recent text."}

Tasks Selected for Resolution via this Reply:
{tasks_block}

User Directives: {instructions_text}
Tone Directive Requested: {selected_tone_rule} ({tone})
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
        raw_text = self.llm.generate_text(
            prompt=prompt,
            system_instruction=MANUAL_DRAFT_SYSTEM_INSTRUCTION
        )
        return raw_text.strip() if raw_text else ""

