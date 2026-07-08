from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime

class EmailFactPayloadDict(TypedDict, total=False):
    action: Optional[str]
    object: Optional[str]
    actor: Optional[str]
    raw_temporal_hint: Optional[str]
    entities: Dict[str, List[str]]

class EmailFactPredictionDict(TypedDict):
    sentence_index: int
    fact_type: str
    payload: EmailFactPayloadDict
    source_sentence: str
    confidence: float
    model_version: str

class EmailFactBatchResponse(TypedDict):
    email_id: str
    facts: List[EmailFactPredictionDict]
