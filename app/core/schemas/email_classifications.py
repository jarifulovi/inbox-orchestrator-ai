from typing import TypedDict, NotRequired, Any

class EmailClassificationPrediction(TypedDict):
    label_id: int
    label: str
    confidence: float
    probabilities: dict[str, float]