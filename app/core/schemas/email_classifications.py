from typing import TypedDict, NotRequired, Any
from uuid import UUID
from datetime import datetime


class EmailClassificationPrediction(TypedDict):
    label_id: int
    label: str
    confidence: float
    probabilities: dict[str, float]


class EmailClassification(TypedDict):
    id: NotRequired[UUID]
    classified_at: NotRequired[datetime]

    email_id: UUID

    label_id: int
    label: str

    confidence: float

    probabilities: dict[str, Any]

    model_version: str