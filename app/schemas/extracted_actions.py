from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ==========================================
# Action Extractor Schemas
# ==========================================

class ExtractedActionPrediction(BaseModel):
    """
    Represents a single raw linguistic primitive unit extracted from a sentence.
    Matches the direct return type from your spaCy/dateparser engine.
    """
    verb_primitive: str
    object_primitive: Optional[str] = None
    source_sentence: str
    parsed_deadline: Optional[datetime] = None
    raw_entities: List[dict] = Field(default_factory=list)


class ExtractedActionBatchResponse(BaseModel):
    """
    Wraps all actions mined from a single email body text string.
    An individual message can produce zero, one, or many action metrics.
    """
    email_id: UUID
    actions: List[ExtractedActionPrediction]


class ExtractedActionCreate(BaseModel):
    """
    The data payload format required to execute an INSERT command into
    the public.extracted_actions persistence layer.
    """
    email_id: UUID
    verb_primitive: str
    object_primitive: Optional[str] = None
    source_sentence: str
    parsed_deadline: Optional[datetime] = None
    raw_entities: List[dict] = Field(default_factory=list)
    model_version: str


class ExtractedActionRecord(ExtractedActionCreate):
    """
    Represents a fully hydrated row fetched directly out of the
    public.extracted_actions table, including system-generated fields.
    """
    id: UUID
    extracted_at: datetime