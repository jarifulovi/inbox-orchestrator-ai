from typing import TypedDict, NotRequired

class PreSecurityPrediction(TypedDict):
    pre_security_passed: bool
    security_risks: list[str]
    extracted_spam_score: float | None
    has_reply_to_mismatch: bool
    is_possible_prompt_injection: bool
    raw_spf_result: str | None
    raw_dkim_result: str | None
    pass1_computed_score: float