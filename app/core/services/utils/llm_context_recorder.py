import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel


class LLMContextRecorder:
    """
    Utility service to record LLM inputs and outputs locally in JSON files for auditing & debugging.
    All disk I/O operations are strictly wrapped in try/except blocks to ensure unhandled file errors 
    never break application runtime or LLM execution.
    """

    def __init__(self, log_dir: Optional[str] = None):
        if log_dir:
            self.log_dir = log_dir
        else:
            # Default to logs/llm_contexts relative to workspace root
            self.log_dir = os.path.join(os.getcwd(), "logs", "llm_contexts")

    def _ensure_directory_exists(self):
        os.makedirs(self.log_dir, exist_ok=True)

    def record_context(
        self,
        prompt: str,
        response_data: Any,
        model: str = "",
        metadata: Optional[dict] = None
    ) -> Optional[str]:
        """
        Saves prompt input and response output payload to a timestamped JSON file.
        Returns the saved log filepath or None if writing fails.
        """
        try:
            self._ensure_directory_exists()

            now = datetime.now(timezone.utc)
            timestamp_str = now.strftime("%Y%m%d_%H%M%S")
            short_id = uuid.uuid4().hex[:6]
            clean_model = (model or "unknown_model").replace("/", "_").replace(":", "_")

            filename = f"{timestamp_str}_{clean_model}_{short_id}.json"
            filepath = os.path.join(self.log_dir, filename)

            serialized_response = self._serialize_response(response_data)
            token_stats = self.calculate_token_stats(prompt, serialized_response)

            payload = {
                "timestamp": now.isoformat(),
                "model": model,
                "token_stats": token_stats,
                "metadata": metadata or {},
                "prompt": prompt,
                "response": serialized_response
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)

            return filepath

        except Exception as e:
            print(f"⚠️ [LLMContextRecorder WARNING] Failed to record LLM context: {e}")
            return None

    @staticmethod
    def estimate_token_count(text: str) -> int:
        """
        Fast, lightweight token count estimation (~1 token per 4 characters).
        """
        if not text:
            return 0
        return max(1, len(text) // 4)

    def calculate_token_stats(self, prompt: str, response_data: Any) -> dict:
        """
        Calculates estimated input prompt tokens, output response tokens, and total tokens.
        """
        prompt_tokens = self.estimate_token_count(prompt or "")

        response_str = ""
        if response_data is not None:
            if isinstance(response_data, str):
                response_str = response_data
            else:
                response_str = json.dumps(response_data, ensure_ascii=False)

        response_tokens = self.estimate_token_count(response_str)

        return {
            "prompt_tokens_est": prompt_tokens,
            "response_tokens_est": response_tokens,
            "total_tokens_est": prompt_tokens + response_tokens
        }

    def _serialize_response(self, data: Any) -> Any:
        if data is None:
            return None
        if isinstance(data, BaseModel):
            return data.model_dump(mode="json")
        if isinstance(data, (dict, list, str, int, float, bool)):
            return data
        try:
            return str(data)
        except Exception:
            return "Unserializable Response"
