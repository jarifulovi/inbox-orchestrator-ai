from typing import TypedDict, NotRequired

class PreSecurityPredictionRow(TypedDict):
    pre_security_passed: bool
    security_risks: list[str]
    extracted_spam_score: float | None
    has_reply_to_mismatch: bool
    is_possible_prompt_injection: bool
    raw_spf_result: str | None
    raw_dkim_result: str | None
    pass1_computed_score: float

PreSecurityPrediction = PreSecurityPredictionRow


class EmailSecurityAnalysisRow(TypedDict):
    email_id: str

    spf_pass: bool
    dkim_pass: bool
    dmarc_pass: bool

    is_whitelisted_sender: bool
    pre_security_passed: bool
    security_risks: list[str]  # e.g ["abuse", "financial_risk", "scam"]
    security_trust_score: float

    security_trust_level: str  # 'unverified', 'suspicious', 'neutral', 'trusted'