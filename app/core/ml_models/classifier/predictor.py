from app.core.ml_models.classifier.model_loader import ClassifierModelLoader
from app.core.ml_models.classifier.preprocessor import EmailPreprocessor
from app.core.schemas.email_classifications import EmailClassificationPrediction


class EmailClassifier:
    def __init__(self):
        self.model_loader = ClassifierModelLoader()
        self.preprocess = EmailPreprocessor()

    def predict(self, safe_nodes: list[dict]) -> list[EmailClassificationPrediction]:
        """
        Extracts [Subject + Body] matrices from safe nodes, cleanses them via
        the Preprocessor, and delivers batch classifications using the ClassifierModelLoader.
        """
        combined_texts = []
        for node in safe_nodes:
            # 1. Extract Subject out of raw_payload headers matrix
            payload = node.get("raw_payload", {})
            headers = payload.get("headers", {})
            # Case-insensitive subject fallback check
            subject = (
                    headers.get("Subject") or
                    headers.get("subject") or
                    headers.get("SUBJECT") or
                    node.get("subject", "")
            ).strip()

            # 2. Extract the clean plain-text body built by ML Service
            body = node.get("cleaned_body", "")

            # 3. Format into a combined string structure
            combined_input = f"{subject} {body}"
            combined_texts.append(combined_input)

        # 4. Pass the combined string array to your original internal pipelines
        processed_texts = self.preprocess.batch_preprocess(combined_texts)
        return self.model_loader.predict(processed_texts)



if __name__ == "__main__":
    import time
    t0 = time.time()
    clf = EmailClassifier()
    print(f"[EmailClassifier] Initialization time: {time.time()-t0:.4f}s")

    test_nodes = [
        {"subject": "Project sync tomorrow", "cleaned_body": "Hi, can we schedule a quick sync tomorrow at 3 PM to discuss API integration progress and deployment updates?"},
        {"subject": "Payment failed alert", "cleaned_body": "Your recent transaction was declined due to insufficient balance. Please update your payment method to continue service."},
        {"subject": "Casual catchup", "cleaned_body": "Hey, how have you been? Just wanted to check in and see what you've been up to lately. It's been a long time!"},
        {"subject": "System maintenance completed", "cleaned_body": "All backend services were successfully updated. No downtime was recorded during deployment."},
        {"subject": "Security notification", "cleaned_body": "You allowed InboxOrchestratorAI access to some of your Google Account data roversteve772@gmail.com."},
        {"subject": "Monthly Invoice #1042", "cleaned_body": "Please find attached your monthly invoice for cloud infrastructure hosting fees due on Sept 15."},
        {"subject": "Q3 Roadmap Strategy Review", "cleaned_body": "Team, please review the attached slide deck for our upcoming Q3 product roadmap meeting."}
    ]

    t1 = time.time()
    results = clf.predict(test_nodes)
    print(f"[EmailClassifier] Batch prediction latency ({len(test_nodes)} emails): {time.time()-t1:.4f}s\n")

    for i, res in enumerate(results):
        print(f"Sample {i+1} | Subject: '{test_nodes[i]['subject']}' -> Label: '{res['label']}' (ID: {res['label_id']}, Confidence: {res['confidence']})")

