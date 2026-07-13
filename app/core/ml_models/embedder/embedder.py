import torch
from transformers import AutoTokenizer, AutoModel

class EmailEmbedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """
        Initializes the tokenizer and model for generating email embeddings.
        Uses sentence-transformers/all-MiniLM-L6-v2 by default, which is
        highly optimized and lightweight (approx 120MB).
        """
        print(f"[EmailEmbedder] Initializing local optimized model: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        # Put model in eval mode for inference
        self.model.eval()

    def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generates 384-dimensional embeddings for a list of input texts.
        Uses Mean Pooling over token embeddings.
        """
        if not texts:
            return []

        # Tokenize sentences
        encoded_input = self.tokenizer(
            texts, 
            padding=True, 
            truncation=True, 
            max_length=512, 
            return_tensors='pt'
        )

        # Compute token embeddings
        with torch.no_grad():
            model_output = self.model(**encoded_input)

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
