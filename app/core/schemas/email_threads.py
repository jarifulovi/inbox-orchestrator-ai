from typing import TypedDict, NotRequired, Any, Set
from datetime import datetime

# =====================================================================
# THREAD WORKFLOW TAXONOMY CONSTANTS
# =====================================================================
# workflow_status represents the high-level operational state of a thread:
# - 'needs_action': Thread has at least 1 active pending task or open question requiring user action.
# - 'awaiting_reply': 0 pending user tasks, but user sent the latest email expecting a reply.
# - 'follow_up': 0 immediate tasks, but thread contains a past commitment, open question, or delegated item requiring future check-in or tracking.
# - 'informational': Default. 0 pending tasks, no reply or follow-up expected (newsletters, info updates, or resolved threads).
# - 'archived': Thread dismissed or archived from active inbox views.
VALID_WORKFLOW_STATUSES: Set[str] = {
    "needs_action",
    "awaiting_reply",
    "follow_up",
    "informational",
    "archived",
}

# priority represents thread urgency: 'high', 'medium', 'low' (default: 'medium')
VALID_THREAD_PRIORITIES: Set[str] = {"high", "medium", "low"}


class EmailThreadRow(TypedDict):
    """
    Direct 1:1 mapping of Database EmailThread record structure.
    """
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

    workflow_status: NotRequired[str]  # 'needs_action', 'awaiting_reply', 'follow_up', 'informational', 'archived'
    priority: NotRequired[str]  # 'high', 'medium', 'low'
    context_memory: NotRequired[dict[str, Any]]
