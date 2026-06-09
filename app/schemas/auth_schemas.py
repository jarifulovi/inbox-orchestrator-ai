from pydantic import BaseModel
from typing import List, Optional


class SyncInfo(BaseModel):
    mode: Optional[str] = None
    cursor: Optional[str] = None
    last_sync_at: Optional[str] = None


class GmailAccountSchema(BaseModel):
    id: str
    provider: str
    email: str
    is_active: bool
    sync: SyncInfo

class GmailAccountsSchema(BaseModel):
    connected: bool
    accounts: list[GmailAccountSchema]

class MeUserSchema(BaseModel):
    id: str
    email: Optional[str]


class MeResponseSchema(BaseModel):
    user: MeUserSchema
    gmail: GmailAccountsSchema


# Google connect response
class GoogleAuthUrlResponse(BaseModel):
    auth_url: str


class GoogleCallbackResponse(BaseModel):
    status: str
    connected_account_id: str
    provider_email: str