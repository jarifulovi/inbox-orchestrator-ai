from typing import TypedDict, NotRequired, Any
from datetime import datetime

class ClassifierMetadataDict(TypedDict, total=False):
    is_proc: bool
    label_id: int
    label: str
    confidence: float
    probabilities: dict[str, float]
    model_version: str

class FactExtractionMetadataDict(TypedDict, total=False):
    is_proc: bool
    quarantined: bool

class SecurityAnalysisMetadataDict(TypedDict, total=False):
    is_proc: bool
    pre_security_passed: bool
    security_risks: list[str]
    extracted_spam_score: float | None
    has_reply_to_mismatch: bool
    is_possible_prompt_injection: bool
    raw_spf_result: str | None
    raw_dkim_result: str | None
    pass1_computed_score: float
    security_trust_score: float
    security_trust_level: str

class AIMetadataDict(TypedDict, total=False):
    classifier: ClassifierMetadataDict
    fact_extraction: FactExtractionMetadataDict
    security_analysis: SecurityAnalysisMetadataDict

class EmailRow(TypedDict):
    thread_id: str
    connected_account_id: str

    gmail_message_id: str

    sender: str
    sender_name: str | None

    recipients: list[str]
    cc: list[str] | None
    bcc: list[str] | None

    subject: str | None
    body: str | None
    snippet: str | None

    has_attachments: bool

    received_at: datetime

    category: str | None  # email classification category from classifier model or gmail
    ai_metadata: AIMetadataDict | None # metadata for each models(classifier+fact ext+security and their statuses)

    detected_entities: dict[str, Any] | None  # { people: ["name", "email"], organizations: [], urls: [], dates: [] }
    raw_payload: dict[str, Any] | None
    embedding: NotRequired[list[float]]