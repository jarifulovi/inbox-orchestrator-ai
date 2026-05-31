try:
    from .ensemble_loader import EnsembleEmailClassifier
    from .preprocessor import EmailPreprocessor
except ImportError:
    # Fallback for CLI usage
    from app.models.classifier.ensemble_loader import EnsembleEmailClassifier
    from app.models.classifier.preprocessor import EmailPreprocessor


class EmailClassifier:
    def __init__(self):
        self.ensemble = EnsembleEmailClassifier()
        self.preprocess = EmailPreprocessor()

    def predict(self, email_texts: list[str]):
        """
        Predict classes for a batch of emails using the ensemble classifier.
        Args:
            email_texts (list[str]): List of email contents.
        Returns:
            list[dict]: Batch predictions with labels, confidences, and probabilities.
        """
        processed_texts = self.preprocess.batch_preprocess(email_texts)
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
