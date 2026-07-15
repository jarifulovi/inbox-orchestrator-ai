from typing import TypedDict, NotRequired, Any
from datetime import datetime

class EmailThreadRow(TypedDict):
    id: NotRequired[str]  # UUID primary key (auto-generated)
    gmail_thread_id: str
    connected_account_id: str

    subject: str | None
    snippet: str | None
    summary: str | None
    summary_generated_at: datetime | None

    is_processed: NotRequired[bool]
    unread_messages_count: NotRequired[int]
    last_message_at: datetime

    workflow_status: NotRequired[str]  # 'needs_action', 'awaiting_reply', etc. (defaults to 'informational')
    priority: NotRequired[str]  # 'high', 'medium', etc. (defaults to 'medium')
    context_memory: NotRequired[dict[str, Any]]
