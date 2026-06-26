# app/model/security/pre_security.py
import re
from typing import List, Dict, Tuple, Optional
from app.core.schemas.email_security_analysis import PreSecurityPrediction


class PreSecurityFilter:
    def __init__(self):
        print("[PRE-SECURITY] Initializing Pass 1 Context-Free Core Engine...")
        # Compile heavy regex patterns once during initialization for high-speed performance
        self.injection_patterns = [
            re.compile(r"ignore\s+(?:all\s+)?prior\s+instructions", re.IGNORECASE),
            re.compile(r"system\s+override", re.IGNORECASE),
            re.compile(r"override\s+this\s+prompt", re.IGNORECASE)
        ]
        self.abuse_patterns = [
            re.compile(r"(?:hacker|exploit|drop\s+table|delete\s+from)", re.IGNORECASE)
        ]
        self.financial_patterns = [
            re.compile(r"(?:wire\s+transfer|update\s+banking|routing\s+number|swift\s+code)", re.IGNORECASE),
            re.compile(r"(?:urgent\s+payment|invoice\s+overdue)", re.IGNORECASE)
        ]

    def predict(self, email_texts: list[str], raw_payloads: list[dict]) -> list[PreSecurityPrediction]:
        """
        Executes a context-free Pass 1 evaluation over matching parallel lists
        of body text strings and structural JSONB payloads.
        """
        batch_predictions = []

        for idx, text in enumerate(email_texts):
            payload = raw_payloads[idx] if idx < len(raw_payloads) else {}

            # 1. Execute granular evaluation pipelines
            is_injection = self._evaluate_prompt_injection(text)
            triggered_risks, is_abusive, is_financial = self._evaluate_text_patterns(text)
            spam_score, has_mismatch, spf_res, dkim_res = self._evaluate_raw_headers(payload)

            # 2. Consolidate contextual warnings into risk categories
            if has_mismatch or (spam_score and spam_score > 5.0):
                if "scam" not in triggered_risks:
                    triggered_risks.append("scam")

            # 3. Handle the structural pass/fail criteria (Master Switch)
            # If a prompt injection is detected, fail the gate instantly to protect downstream LLMs
            pre_passed = not is_injection

            # 4. Compute defensive Pass 1 markdown penalty score
            pass1_score = self._compute_pass1_score(
                pre_passed, triggered_risks, spam_score, has_mismatch
            )

            batch_predictions.append(
                PreSecurityPrediction(
                    pre_security_passed=pre_passed,
                    security_risks=triggered_risks,
                    extracted_spam_score=spam_score,
                    has_reply_to_mismatch=has_mismatch,
                    is_possible_prompt_injection=is_injection,
                    raw_spf_result=spf_res,
                    raw_dkim_result=dkim_res,
                    pass1_computed_score=pass1_score
                )
            )

        return batch_predictions

    def _evaluate_prompt_injection(self, text: str) -> bool:
        """Checks raw strings for adversarial prompt injections."""
        return any(pattern.search(text) for pattern in self.injection_patterns)

    def _evaluate_text_patterns(self, text: str) -> Tuple[List[str], bool, bool]:
        """Runs fast regex search groupings across body strings to isolate hazards."""
        risks = []
        is_abusive = any(pattern.search(text) for pattern in self.abuse_patterns)
        is_financial = any(pattern.search(text) for pattern in self.financial_patterns)

        if is_abusive:
            risks.append("abuse")
        if is_financial:
            risks.append("financial_risk")

        return risks, is_abusive, is_financial

    def _evaluate_raw_headers(self, payload: dict) -> Tuple[Optional[float], bool, Optional[str], Optional[str]]:
        """Parses the raw_payload JSONB dictionary structure for deep header anomalies."""
        headers: Dict[str, str] = payload.get("headers", {})

        # Pull typical upstream spam scoring if visible in routing headers
        spam_header = headers.get("X-Spam-Score", "0")
        try:
            spam_score = float(spam_header)
        except ValueError:
            spam_score = 0.0

        # Detect domain mismatch schemes (From vs Reply-To)
        from_header = headers.get("From", "").lower()
        reply_header = headers.get("Reply-To", "").lower()

        has_mismatch = False
        if reply_header and from_header:
            # Basic domain extraction pattern
            from_domain = from_header.split("@")[-1].strip("> ")
            reply_domain = reply_header.split("@")[-1].strip("> ")
            if from_domain != reply_domain:
                has_mismatch = True

        # Extract textual raw verification values from authentication headers
        spf_res = headers.get("Received-SPF") or headers.get("X-SPF-Result")
        dkim_res = headers.get("Authentication-Results")  # Can be parsed for dkim=pass strings

        return spam_score, has_mismatch, spf_res, dkim_res

    def _compute_pass1_score(self, pre_passed: bool, risks: List[str], spam_score: Optional[float],
                             has_mismatch: bool) -> float:
        """Applies a strict context-free markdown starting from a perfect 1.00 score."""
        if not pre_passed:
            return 0.00  # Ultimate failure condition

        score = 1.00

        # Deduct for pattern triggers
        if "financial_risk" in risks:
            score -= 0.20
        if "abuse" in risks:
            score -= 0.30

        # Deduct for header warnings
        if has_mismatch:
            score -= 0.35
        if spam_score and spam_score > 3.0:
            score -= (spam_score * 0.05)  # Scale deduction based on severity

        return max(0.00, round(score, 2))