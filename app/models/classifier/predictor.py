try:
    from .ensemble_loader import EnsembleEmailClassifier
    from .preprocessor import EmailPreprocessor
    from ...schemas.email_classification import (
        EmailClassificationBatchRequest,
        EmailClassificationPrediction
    )
except ImportError:
    # Fallback for CLI usage
    from app.models.classifier.ensemble_loader import EnsembleEmailClassifier
    from app.models.classifier.preprocessor import EmailPreprocessor
    from app.schemas.email_classification import (
        EmailClassificationBatchRequest,
        EmailClassificationPrediction
    )


class EmailClassifier:
    def __init__(self):
        self.ensemble = EnsembleEmailClassifier()
        self.preprocess = EmailPreprocessor()

    def predict(self, safe_nodes: list[dict]) -> list[EmailClassificationPrediction]:
        """
        Extracts [Subject + Body] matrices from safe nodes, cleanses them via
        the Preprocessor, and delivers batch classifications using the ensemble.
        """
        combined_texts = []
        for node in safe_nodes:
            # 1. Extract Subject out of raw_payload headers matrix
            payload = node.get("raw_payload", {})
            headers = payload.get("headers", {})
            subject = headers.get("Subject", "").strip()

            # 2. Extract the clean plain-text body built by ML Service
            body = node.get("cleaned_body", "")

            # 3. Format into a combined string structure
            combined_input = f"Subject: {subject}\nBody: {body}"
            combined_texts.append(combined_input)

        # 4. Pass the combined string array to your original internal pipelines
        processed_texts = self.preprocess.batch_preprocess(combined_texts)
        return self.ensemble.predict(processed_texts)



if __name__ == "__main__":
    clf = EmailClassifier()
    emails = [
        "Project sync tomorrow Hi, can we schedule a quick sync tomorrow at 3 PM to discuss API integration progress and deployment updates?",

        "Payment failed alert Your recent transaction was declined due to insufficient balance. Please update your payment method to continue service.",

        "Hey, how have you been? Just wanted to check in and see what you've been up to lately. It’s been a long time!",

        "50% OFF limited time offer Upgrade to premium today and unlock all features at half price. Offer expires tonight.",

        "Your account statement is ready Please review your monthly bank statement and verify all transactions for accuracy.",

        "System maintenance completed All backend services were successfully updated. No downtime was recorded during deployment.",

        "Weekly newsletter: AI trends This week we explore new transformer architectures, open-source LLM tools, and research breakthroughs.",

        "Urgent security alert Unusual login attempt detected from a new device. If this wasn’t you, reset your password immediately.",

        "Invoice for subscription renewal Please find attached your invoice for the next billing cycle. Payment is due within 7 days.",

        "Congratulations! You won a prize Click here immediately to claim your reward. This offer is only valid for a limited time."
    ]
    results = clf.predict(emails)
    for i, res in enumerate(results):
        print(f"Email {i}: {res}")
