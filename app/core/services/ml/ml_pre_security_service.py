from bs4 import BeautifulSoup
from app.core.ml_models.security.pre_security import PreSecurityFilter


class MLPreSecurityService:
    def __init__(self):
        self.pre_security_engine = PreSecurityFilter()

    def preprocess_batch(self, email_nodes: list[dict]) -> list[dict]:
        """
        Ingests the pre-parsed 'body' string, normalizes formatting/whitespace,
        and cuts it at a safe length to protect regex engines.
        """
        for node in email_nodes:
            # 1. Strip out html
            raw_input = node.get("body") or node.get("snippet") or ""
            raw_text = self.html_to_text(raw_input)

            # 2. Standardize all line break formats and strip empty trailing gaps
            text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            text = "\n".join(lines)

            # 3. Truncate at 50,000 characters to prevent backtracking regex freezes
            if len(text) > 50000:
                text = text[:50000].rsplit(" ", 1)[0]

            # 4. Bind the final string directly back to the matrix node
            node["cleaned_body"] = text if text else "[EMPTY_EMAIL]"

        return email_nodes

    def evaluate_pre_security(self, email_nodes: list[dict]) -> list[dict]:
        """
        Runs Pass 1 Pre-Security Filter evaluation on cleaned email bodies.
        """
        cleaned_bodies = [node["cleaned_body"] for node in email_nodes]
        raw_payloads = [node.get("raw_payload", {}) for node in email_nodes]

        return self.pre_security_engine.predict(
            email_texts=cleaned_bodies,
            raw_payloads=raw_payloads
        )

    @staticmethod
    def html_to_text(html: str) -> str:
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        cleaned_text = soup.get_text(separator=" ")

        return cleaned_text
