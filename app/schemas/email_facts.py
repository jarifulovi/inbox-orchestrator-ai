from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

# ==========================================
# Email Fact Extractor Pydantic Schemas
# ==========================================

class EmailFactPayload(BaseModel):
    """
    Structured semantic representation of the extracted fact.
    """
    action: Optional[str] = None
    object: Optional[str] = None
    actor: Optional[str] = None
    raw_temporal_hint: Optional[str] = None
    entities: Dict[str, List[str]] = Field(default_factory=dict)


class EmailFactPrediction(BaseModel):
    """
    Represents a single parsed sentence fact prediction.
    """
    sentence_index: int
    fact_type: str  # task, commitment, decision, question, or fact
    payload: EmailFactPayload
    source_sentence: str
    confidence: float
    model_version: str


class EmailFactBatchResponse(BaseModel):
    """
    Wraps all facts mined from a single email.
    """
    email_id: UUID
    facts: List[EmailFactPrediction]


class EmailFactCreate(BaseModel):
    """
    The data payload format required to execute an INSERT command into
    the public.email_facts persistence layer.
    """
    email_id: UUID
    user_id: UUID
    connected_account_id: UUID
    sentence_index: int
    fact_type: str
    payload: Dict[str, Any]  # Store serialized payload dictionary directly
    source_sentence: str
    anchor_date: Optional[datetime] = None
    confidence: float
    model_version: str


class EmailFactRecord(EmailFactCreate):
    """
    Represents a fully hydrated row fetched directly out of the
    public.email_facts table, including system-generated fields.
    """
    id: UUID
    extracted_at: datetime
