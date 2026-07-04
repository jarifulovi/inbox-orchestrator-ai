from typing import TypedDict, NotRequired, Any

class EmailClassificationPredictionRow(TypedDict):
    label_id: int
    label: str
    confidence: float
    probabilities: dict[str, float]


class EmailClassificationRow(TypedDict):
    email_id: str

    label_id: int
    label: str

    confidence: float

    probabilities: dict[str, Any]

    model_version: str