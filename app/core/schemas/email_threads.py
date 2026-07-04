from typing import TypedDict, NotRequired
from datetime import datetime

class EmailThreadRow(TypedDict):
    gmail_thread_id: str

    connected_account_id: str

    subject: str | None
    snippet: str | None
    summary: str | None
    summary_generated_at: datetime | None

    is_processed: bool

    unread_messages_count: int

    last_message_at: datetime