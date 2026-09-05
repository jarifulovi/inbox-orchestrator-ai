import threading
import torch
from transformers import AutoTokenizer, AutoModel


class EmailEmbedder:
    _instance_lock = threading.Lock()
    _tokenizer = None
    _model = None
    _loaded_model_name = None

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Lightweight wrapper for generating email embeddings.
        Tokenizer and model weights are lazy-loaded on demand and cached globally as a singleton.
        """
        self.model_name = model_name

    @classmethod
    def _ensure_model_loaded(cls, model_name: str):
        """Thread-safe lazy initializer for shared tokenizer and model weights."""
        if cls._model is None or cls._loaded_model_name != model_name:
            with cls._instance_lock:
                if cls._model is None or cls._loaded_model_name != model_name:
                    print(f"[EmailEmbedder] Lazy-loading shared local embedding model: {model_name}")
                    try:
                        torch.set_num_threads(2)
                    except Exception:
                        pass
                    cls._tokenizer = AutoTokenizer.from_pretrained(model_name)
                    cls._model = AutoModel.from_pretrained(model_name)
                    cls._model.eval()
                    cls._loaded_model_name = model_name

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generates 384-dimensional embeddings for a list of input texts.
        Uses Mean Pooling over token embeddings.
        """
        if not texts:
            return []

        self._ensure_model_loaded(self.model_name)

        # Tokenize sentences
        encoded_input = self._tokenizer(
            texts, 
            padding=True, 
            truncation=True, 
            max_length=512, 
            return_tensors='pt'
        )

        # Compute token embeddings
        with torch.no_grad():
            model_output = self._model(**encoded_input)

        # Perform mean pooling
        token_embeddings = model_output[0]  # First element contains token embeddings
        attention_mask = encoded_input['attention_mask']
        
        # Expand attention mask to match token embeddings size
        input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        
        # Sum token embeddings weighted by attention mask
        sum_embeddings = torch.sum(token_embeddings * input_mask_expanded, 1)
        
        # Avoid division by zero
        sum_mask = torch.clamp(input_mask_expanded.sum(1), min=1e-9)
        
        embeddings = sum_embeddings / sum_mask
        
        # Return as list of list of floats
        return embeddings.tolist()
