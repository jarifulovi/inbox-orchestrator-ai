from typing import TypedDict, NotRequired
from uuid import UUID
from datetime import datetime


class ConnectedAccount(TypedDict):
    id: NotRequired[UUID]
    connected_at: NotRequired[datetime]

    user_id: UUID

    provider: str
    provider_email: str

    access_token: str
    refresh_token: str

    token_expires_at: datetime

    is_active: bool

    sync_cursor: str | None

    scope: str

    sync_mode: str  # sync_mode_enum
    sync_status: str  # sync_status_enum

    last_sync_at: datetime | None