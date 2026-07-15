from typing import TypedDict, List, Dict, Any, Optional, Literal, NotRequired
from datetime import datetime

class EmailFactPayloadDict(TypedDict, total=False):
    action: Optional[str]
    object: Optional[str]
    actor: Optional[str]
    raw_temporal_hint: Optional[str]
    entities: Dict[str, List[str]]

class EmailFactPredictionDict(TypedDict):
    sentence_index: int
    fact_type: Literal["task", "commitment", "decision", "question", "fact"]
    payload: EmailFactPayloadDict
    source_sentence: str
    confidence: float
    model_version: str


class EmailFactRow(TypedDict):
    id: NotRequired[str]
    email_id: str  # UUID referencing public.emails
    user_id: str  # UUID referencing auth.users
    connected_account_id: str  # UUID referencing public.connected_accounts
    sentence_index: int
    fact_type: Literal["task", "commitment", "decision", "question", "fact"]
    payload: EmailFactPayloadDict
    source_sentence: str
    anchor_date: Optional[datetime]
    confidence: float
    model_version: str
    extracted_at: datetime

class EmailFactBatchResponse(TypedDict):
    email_id: str
    facts: List[EmailFactPredictionDict]
