# Offline Testing: Semantic Embedding and Cosine Similarity Verification
# 
# To run this offline test, execute the following command from the workspace root:
# PYTHONPATH=. .venv/bin/python tests/test_offline_similarity.py

import torch
from app.core.ml_models.embedder.embedder import EmailEmbedder

def calculate_cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    t1 = torch.tensor(vec1)
    t2 = torch.tensor(vec2)
    return float(torch.nn.functional.cosine_similarity(t1, t2, dim=0))

def test_offline_similarity():
    print("Initializing EmailEmbedder (Offline - No DB connection)...")
    embedder = EmailEmbedder()
    
    # 1. Define 3 simulated emails with metadata and facts
    emails = [
        {
            "subject": "Urgent Invoice payment request",
            "category": "financial",
            "label_ids": ["INBOX", "UNREAD"],
            "snippet": "Please process the attached invoice #84321 for the subscription renewal. The amount is $450 and payment is due by Friday.",
            "facts": [
                "The amount to be paid is $450.",
                "Payment is due by Friday."
            ]
        },
        {
            "subject": "Billing issue and payment reminder",
            "category": "financial",
            "label_ids": ["INBOX", "IMPORTANT"],
            "snippet": "This is a reminder that subscription invoice #84321 is still unpaid. Please clear the billing issue of $450 as soon as possible.",
            "facts": [
                "The subscription invoice #84321 is still unpaid.",
                "Please clear the billing issue of $450."
            ]
        },
        {
            "subject": "Weekly project status update",
            "category": "work_professional",
            "label_ids": ["INBOX"],
            "snippet": "Hi team, here is the summary of project status. All backend APIs are finished and integrated. The frontend team will deliver client builds tomorrow.",
            "facts": [
                "All backend APIs are finished and integrated.",
                "The frontend team will deliver client builds tomorrow."
            ]
        }
    ]
    
    # 2. Compile structured search documents
    documents = []
    print("\n--- Compiled Structured Search Documents ---")
    for idx, email in enumerate(emails):
        doc_parts = [
            f"Subject: {email['subject']}",
            f"Category: {email['category']}",
            f"Gmail Labels: {', '.join(email['label_ids'])}",
            f"Snippet: {email['snippet'][:400]}",
            "Facts:"
        ]
        for fact in email["facts"]:
            doc_parts.append(f"- {fact}")
            
        doc_text = "\n".join(doc_parts)
        documents.append(doc_text)
        print(f"\n[Email {idx} Document]:\n{doc_text}")
        print("-" * 40)
        
    # 3. Generate embeddings
    print("\nGenerating embeddings...")
    embeddings = embedder.generate_embeddings(documents)
    print(f"Generated {len(embeddings)} embeddings. Size: {len(embeddings[0])} dimensions.")
    
    # 4. Calculate similarities
    print("\n--- Cosine Similarity Matrix ---")
    sim_0_1 = calculate_cosine_similarity(embeddings[0], embeddings[1])
    sim_0_2 = calculate_cosine_similarity(embeddings[0], embeddings[2])
    sim_1_2 = calculate_cosine_similarity(embeddings[1], embeddings[2])
    
    print(f"Similarity (Email 0 VS Email 1): {sim_0_1:.4f} (Expected high)")
    print(f"Similarity (Email 0 VS Email 2): {sim_0_2:.4f} (Expected low)")
    print(f"Similarity (Email 1 VS Email 2): {sim_1_2:.4f} (Expected low)")

    # Assertions to ensure models work as expected
    assert sim_0_1 > 0.75, f"Similarity between similar financial emails should be high, got {sim_0_1}"
    assert sim_0_2 < 0.50, f"Similarity between financial and work emails should be low, got {sim_0_2}"
    assert sim_1_2 < 0.50, f"Similarity between financial and work emails should be low, got {sim_1_2}"
    print("\n✅ Offline test assertions passed successfully!")

if __name__ == "__main__":
    test_offline_similarity()
