from pydantic import BaseModel, EmailStr
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID


# =========================
# Core DB Schema
# =========================

class ConnectedAccountBase(BaseModel):
    user_id: UUID
    provider: Literal["google"]
    provider_email: EmailStr

    access_token: str
    refresh_token: str
    token_expires_at: datetime

    is_active: bool = True

    sync_cursor: Optional[str] = None
    sync_mode: Optional[
        Literal["INITIAL_BACKFILL", "BACKFILLING", "ACTIVE"]
    ] = None

    sync_status: Optional[
        Literal["IDLE", "SYNCING", "PAUSED", "FAILED"]
    ] = None

    scope: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None


# =========================
# Create Request Schema
# =========================

class ConnectedAccountCreate(ConnectedAccountBase):
    pass


# =========================
# Update Schema (partial updates)
# =========================

class ConnectedAccountUpdate(BaseModel):
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None

    is_active: Optional[bool] = None

    sync_cursor: Optional[str] = None
    sync_mode: Optional[
        Literal["INITIAL_BACKFILL", "BACKFILLING", "ACTIVE"]
    ] = None

    sync_status: Optional[
        Literal["IDLE", "SYNCING", "PAUSED", "FAILED"]
    ] = None

    last_sync_at: Optional[datetime] = None


# =========================
# Response Schema
# =========================

class ConnectedAccountResponse(BaseModel):
    id: UUID
    user_id: UUID

    provider: Literal["google"]
    provider_email: EmailStr

    is_active: bool

    sync_cursor: Optional[str]
    sync_mode: Optional[str]
    sync_status: Optional[str]

    scope: Optional[str]

    connected_at: Optional[datetime]
    last_sync_at: Optional[datetime]

    model_config = {
        "from_attributes": True
    }