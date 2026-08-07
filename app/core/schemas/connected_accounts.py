from typing import TypedDict, NotRequired
from datetime import datetime

class ConnectedAccountRow(TypedDict):
    id: NotRequired[str]  # UUID primary key (auto-generated)
    user_id: str  # UUID foreign key to auth.users
    connected_at: NotRequired[datetime]

    provider: str
    provider_email: str

    access_token: str
    refresh_token: str
    token_expires_at: datetime

    is_active: bool
    sync_cursor: str | None
    scope: str

    sync_mode: str  # 'INITIAL_BACKFILL', 'BACKFILLING', 'ACTIVE'
    sync_status: str  # 'IDLE', 'SYNCING', 'PAUSED', 'FAILED'
