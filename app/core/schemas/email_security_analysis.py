from typing import TypedDict, NotRequired
from uuid import UUID
from datetime import datetime


class PreSecurityPrediction(TypedDict):
    pre_security_passed: bool
    security_risks: list[str]
    extracted_spam_score: float | None
    has_reply_to_mismatch: bool
    is_possible_prompt_injection: bool
    raw_spf_result: str | None
    raw_dkim_result: str | None
    pass1_computed_score: float


class EmailSecurityAnalysis(TypedDict):
    id: NotRequired[UUID]
    analyzed_at: NotRequired[datetime]

    email_id: UUID

    spf_pass: bool
    dkim_pass: bool
    dmarc_pass: bool

    is_whitelisted_sender: bool

    contains_abuse: bool

    is_financial_risk: bool

    security_trust_score: float

    security_trust_level: str