from typing import TypedDict, NotRequired
from uuid import UUID
from datetime import datetime


class EmailThread(TypedDict):
    id: NotRequired[UUID]
    created_at: NotRequired[datetime]

    gmail_thread_id: str

    connected_account_id: UUID

    subject: str | None
    snippet: str | None
    summary: str | None

    is_processed: bool

    unread_messages_count: int

    last_message_at: datetime