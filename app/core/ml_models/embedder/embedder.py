import os
import httpx
import threading

try:
    import torch
    from transformers import AutoTokenizer, AutoModel
except ImportError:
    torch = None
    AutoTokenizer = None
    AutoModel = None

from app.core.services.utils.memory_utils import force_garbage_collection, apply_thread_limits

apply_thread_limits()


class EmailEmbedder:
    _instance_lock = threading.Lock()
    _tokenizer = None
    _model = None
    _loaded_model_name = None

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Wrapper for generating 384-dimensional email embeddings.
        Tries Gemini Embedding API first (0 MB RAM), falling back to local PyTorch model.
        """
        self.model_name = model_name

    @classmethod
    def _ensure_model_loaded(cls, model_name: str):
        """Thread-safe lazy initializer for shared tokenizer and model weights."""
        if cls._model is None or cls._loaded_model_name != model_name:
            with cls._instance_lock:
                if cls._model is None or cls._loaded_model_name != model_name:
                    print(f"[EmailEmbedder] Lazy-loading shared local PyTorch embedding model: {model_name}")
                    try:
                        torch.set_num_threads(2)
                    except Exception:
                        pass

                    try:
                        cls._tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
                        cls._model = AutoModel.from_pretrained(model_name, local_files_only=True)
                    except Exception:
                        cls._tokenizer = AutoTokenizer.from_pretrained(model_name)
                        cls._model = AutoModel.from_pretrained(model_name)

                    cls._model.eval()
                    cls._loaded_model_name = model_name
                    force_garbage_collection()

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generates 384-dimensional embeddings for a list of input texts.
        Primary: Gemini Embedding API (0 MB RAM, 384-dim).
        Fallback: Local PyTorch sentence-transformers.
        """
        if not texts:
            return []

        # 1. Try Gemini Embedding API first (0 MB RAM, 384-dim)
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                results = []
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent?key={gemini_key}"
                with httpx.Client(timeout=10.0) as client:
                    for text in texts:
                        payload = {
                            "content": {"parts": [{"text": (text or "")[:1000]}]},
                            "output_dimensionality": 384
                        }
                        res = client.post(url, json=payload)
                        if res.status_code == 200:
                            vec = res.json().get("embedding", {}).get("values", [])
                            if vec and len(vec) == 384:
                                results.append(vec)
                                continue
                        results.append([0.0] * 384)
                if len(results) == len(texts):
                    return results
            except Exception as ex:
                print(f"[EmailEmbedder WARNING] Gemini Cloud Embedding failed, falling back to local model: {ex}")

        # 2. Local PyTorch model fallback
        if torch is not None:
            try:
                self._ensure_model_loaded(self.model_name)
                encoded_input = self._tokenizer(
                    texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt"
                )
                with torch.no_grad():
                    model_output = self._model(**encoded_input)

                token_embeddings = model_output[0]
                attention_mask = encoded_input['attention_mask']
                input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
                sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
                sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                embeddings = sum_embeddings / sum_mask
                result = embeddings.tolist()
                force_garbage_collection()
                return result
            except Exception as e:
                print(f"[EmailEmbedder ERROR] Local PyTorch embedding failed: {e}")

        return [[0.0] * 384 for _ in texts]

