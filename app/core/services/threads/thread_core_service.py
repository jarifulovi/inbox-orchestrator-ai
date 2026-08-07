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

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
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
        """Delegates LLM orchestration to ThreadLLMService."""
        return self.llm_service.orchestrate_thread_via_llm(
            thread_subject=thread_subject,
            actions_payload=actions_payload,
            email_manifest=email_manifest,
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
        return {
            "message_manifest": [
                {
                    "message_id": e["id"],
                    "sender_name": e["sender_name"],
                    "sender_email": e["sender"],
                    "received_at": e["received_at"],
                    "snippet": e.get("snippet") or (e.get("body")[:200] if e.get("body") else "")
                }
                for e in reversed(emails)  # Chronological order
            ],
            "aggregated_facts": [],
            "thread_summary": thread_summary or ""
        }
