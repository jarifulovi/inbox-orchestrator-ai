from typing import TypedDict, NotRequired, Any
from uuid import UUID
from datetime import datetime


class ExtractedAction(TypedDict):
    id: NotRequired[UUID]
    extracted_at: NotRequired[datetime]

    email_id: UUID

    verb_primitive: str
    object_primitive: str | None

    source_sentence: str

    raw_entities: list[Any]  # JSONB array

    parsed_deadline: datetime | None

    model_version: str