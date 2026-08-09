import hashlib
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional
from app.core.llm.client import LLMClient
from app.core.schemas.tasks import UnifiedThreadOrchestrationResponse
from app.core.services.content_compressor import ContentCompressorService
from app.core.services.threads.thread_llm_service import ThreadLLMService
from app.core.services.threads.thread_rule_service import ThreadRuleService

class ThreadCoreService:
    """
    High-level domain coordinator for thread features.
    Delegates LLM operations to ThreadLLMService and rule/heuristic policies to ThreadRuleService.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()
        self.llm_service = ThreadLLMService(self.llm)
        self.rule_service = ThreadRuleService()

    def generate_action_fingerprint(self, thread_id: str, verb_primitive: str, object_primitive: str) -> str:
        """Generates a deterministic MD5 fingerprint for a task based on thread and action semantics."""
        raw_string = f"{thread_id}_{verb_primitive}_{object_primitive}".lower()
        return hashlib.md5(raw_string.encode('utf-8')).hexdigest()

    def derive_workflow_status(
        self,
        thread: Dict[str, Any],
        emails: List[Dict[str, Any]],
        user_email: str,
        has_pending_tasks: bool
    ) -> str:
        """Delegates workflow status derivation to ThreadRuleService."""
        return self.rule_service.derive_workflow_status(thread, emails, user_email, has_pending_tasks)

    def generate_rule_based_fallback(
        self,
        thread: Dict[str, Any],
        emails: List[Dict[str, Any]]
    ) -> Tuple[Optional[str], str, bool]:
        """Delegates rule-based fallback generation to ThreadRuleService."""
        return self.rule_service.generate_rule_based_fallback(thread, emails)

    def orchestrate_thread_via_llm(
        self,
        thread_subject: str,
        actions_payload: List[Dict[str, Any]],
        email_manifest: List[Dict[str, Any]],
        anchor_date: str
    ) -> UnifiedThreadOrchestrationResponse:
        """Delegates initial LLM orchestration to ThreadLLMService."""
        return self.llm_service.orchestrate_thread_via_llm(
            thread_subject=thread_subject,
            actions_payload=actions_payload,
            email_manifest=email_manifest,
            anchor_date=anchor_date
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
        """Delegates delta update LLM orchestration to ThreadLLMService."""
        return self.llm_service.orchestrate_thread_update_via_llm(
            thread_subject=thread_subject,
            existing_summary=existing_summary,
            pending_tasks=pending_tasks,
            new_actions_payload=new_actions_payload,
            new_email_snippet=new_email_snippet,
            anchor_date=anchor_date
        )

    def prepare_facts_payload(
        self,
        facts_to_process: List[Dict[str, Any]],
        default_anchor_date: str
    ) -> List[Dict[str, Any]]:
        """Formats extracted facts into context payload for LLM prompts."""
        return [
            {
                "id": f["id"],
                "verb_primitive": f.get("payload", {}).get("action") if f.get("payload") else None,
                "object_primitive": f.get("payload", {}).get("object") if f.get("payload") else None,
                "source_sent": f.get("source_sentence"),
                "raw_entities": f.get("payload", {}).get("entities") if f.get("payload") else None,
                "anchor_date": f.get("anchor_date") or default_anchor_date
            }
            for f in facts_to_process
        ]

    def prepare_email_manifest(self, emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compresses email bodies and formats message manifest for LLM prompts."""
        return [
            {
                "id": e["id"],
                "sender": e["sender"],
                "sender_name": e["sender_name"],
                "received_at": e["received_at"],
                "body_compressed": ContentCompressorService.compress_email_body(e["body"])
            }
            for e in emails
        ]

    def prepare_context_memory(self, emails: List[Dict[str, Any]], thread_summary: Optional[str]) -> Dict[str, Any]:
        """Serializes thread message manifest and summary into context_memory JSON."""
        manifest_items = []
        for e in reversed(emails):
            body_val = e.get("body") if isinstance(e.get("body"), str) else ""
            snippet_val = e.get("snippet") or (body_val[:200] if body_val else "")
            manifest_items.append({
                "message_id": e.get("id"),
                "sender_name": e.get("sender_name") or "",
                "sender_email": e.get("sender") or "",
                "received_at": e.get("received_at") or "",
                "snippet": snippet_val
            })
        return {
            "message_manifest": manifest_items,
            "aggregated_facts": [],
            "thread_summary": thread_summary or ""
        }

    def partition_unprocessed_facts(
        self,
        thread: Dict[str, Any],
        emails: List[Dict[str, Any]],
        facts: List[Dict[str, Any]],
        thread_tasks: List[Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Partitions active pending tasks and isolates facts from unprocessed new emails."""
        pending_tasks = [t for t in thread_tasks if t["status"] == "pending"]
        tasked_fact_ids = {t["email_fact_id"] for t in thread_tasks if t.get("email_fact_id")}
        existing_summary = thread.get("summary")
        context_memory = thread.get("context_memory") or {}
        message_manifest = context_memory.get("message_manifest") or []
        processed_email_ids = {
            m["message_id"] 
            for m in message_manifest 
            if isinstance(m, dict) and "message_id" in m
        }

        if existing_summary and processed_email_ids:
            # Re-processing existing thread: isolate emails not in message_manifest yet
            new_emails = [e for e in emails if e["id"] not in processed_email_ids]
            new_email_ids = {e["id"] for e in new_emails}
            facts_to_process = [
                f for f in facts 
                if f["email_id"] in new_email_ids and f["id"] not in tasked_fact_ids
            ]
        else:
            # Initial thread orchestration run
            facts_to_process = [f for f in facts if f["id"] not in tasked_fact_ids]

        return pending_tasks, facts_to_process

    def build_task_records(
        self,
        response: UnifiedThreadOrchestrationResponse,
        facts_to_process: List[Dict[str, Any]],
        thread_id: str,
        user_id: str,
        account_id: str
    ) -> List[Dict[str, Any]]:
        """Transforms Gemini ExtractedTaskBlueprint items into database task rows."""
        new_tasks = []
        facts_by_id = {f["id"]: f for f in facts_to_process}

        for blueprint in response.task_generations:
            if not blueprint.is_actionable_task:
                continue
            fact = facts_by_id.get(blueprint.email_fact_id)
            if not fact:
                continue

            payload = fact.get("payload") or {}
            verb = payload.get("action") or ""
            obj = payload.get("object") or ""

            fingerprint = self.generate_action_fingerprint(thread_id, verb, obj)

            new_tasks.append({
                "email_fact_id": blueprint.email_fact_id,
                "email_id": fact["email_id"],
                "thread_id": thread_id,
                "user_id": user_id,
                "connected_account_id": account_id,
                "source": "system",
                "title": blueprint.title,
                "status": "pending",
                "priority": (blueprint.priority or "medium").lower(),
                "intent_label": blueprint.intent_label,
                "action_fingerprint": fingerprint,
                "due_date": blueprint.due_date_iso
            })

        return new_tasks
