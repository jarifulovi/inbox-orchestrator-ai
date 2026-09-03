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
    url: Optional[str] = None

    def model_post_init(self, __context):
        if not self.url and self.auth_url:
            self.url = self.auth_url
        elif not self.auth_url and self.url:
            self.auth_url = self.url


class GoogleCallbackResponse(BaseModel):
    status: str
    connected_account_id: str
    provider_email: str


class ToggleAccountSyncPayload(BaseModel):
    is_active: bool