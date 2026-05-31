from datetime import datetime
from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel


class EmailClassificationBatchRequest(BaseModel):
    email_texts: List[str]


class EmailClassificationPrediction(BaseModel):
    label_id: int
    label: str
    confidence: float
    probabilities: Dict[str, float]


class EmailClassificationCreate(BaseModel):
    email_id: UUID
    label_id: int
    label: str
    confidence: float
    probabilities: Dict[str, float]
    model_version: str


class EmailClassificationRecord(EmailClassificationCreate):
    id: UUID
    classified_at: datetime
