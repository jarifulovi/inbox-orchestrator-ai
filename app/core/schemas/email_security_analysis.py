from typing import TypedDict, NotRequired
from uuid import UUID
from datetime import datetime


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