from typing import TypedDict, NotRequired, Any
from datetime import datetime

class ExtractedActionPredictionRow(TypedDict):
    verb_primitive: str
    object_primitive: str | None
    source_sentence: str
    parsed_deadline: datetime | str | None
    raw_entities: list[dict]


class ExtractedActionBatchResponse(TypedDict):
    email_id: str
    actions: list[ExtractedActionPredictionRow]


class ExtractedActionRow(TypedDict):
    user_id: str
    email_id: str
    anchor_date: datetime | str | None

    verb_primitive: str
    object_primitive: str | None

    source_sentence: str

    raw_entities: list[Any]  # JSONB array { actors: [], intent_label: ["send", "reply"], raw_temporal_hints: [], people: [], organizations: [], quoted_text: [] }

    parsed_deadline: datetime | None

    model_version: str