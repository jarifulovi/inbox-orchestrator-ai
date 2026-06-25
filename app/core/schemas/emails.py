from typing import TypedDict, NotRequired, Any
from uuid import UUID
from datetime import datetime


class Email(TypedDict):
    id: NotRequired[UUID]
    ingested_at: NotRequired[datetime]

    thread_id: UUID
    connected_account_id: UUID

    gmail_message_id: str

    sender: str
    sender_name: str | None

    recipients: list[str]
    cc: list[str] | None
    bcc: list[str] | None

    subject: str | None
    body: str | None
    snippet: str | None
    summary: str | None

    has_attachments: bool

    received_at: datetime

    raw_payload: dict[str, Any] | None