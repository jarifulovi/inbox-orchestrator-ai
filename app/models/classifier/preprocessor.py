import re
from typing import List

class EmailPreprocessor:
    """
    Preprocessing steps specific to classifier models.
    Any details which are considered noise for the classifier models will be excluded here.
    """
    def __init__(self, lowercase: bool = True, remove_urls: bool = True, remove_emails: bool = True):
        self.lowercase = lowercase
        self.remove_urls = remove_urls
        self.remove_emails = remove_emails
        self.url_pattern = re.compile(r'https?://\S+|www\.\S+')
        self.email_pattern = re.compile(r'\b[\w.-]+?@[\w.-]+?\.[a-zA-Z]{2,6}\b')

    def preprocess(self, text: str) -> str:
        if self.lowercase:
            text = text.lower()
        if self.remove_urls:
            text = self.url_pattern.sub('', text)
        if self.remove_emails:
            text = self.email_pattern.sub('', text)
        text = text.strip()
        return text

    def batch_preprocess(self, texts: List[str]) -> List[str]:
        return [self.preprocess(t) for t in texts]

