from typing import TypedDict, NotRequired, Any
from datetime import datetime

class EmailRow(TypedDict):
    thread_id: str
    connected_account_id: str

    gmail_message_id: str

    sender: str
    sender_name: str | None

    recipients: list[str]
    cc: list[str] | None
    bcc: list[str] | None

    subject: str | None
    body: str | None
    snippet: str | None

    has_attachments: bool

    received_at: datetime

    detected_entities: dict[str, Any] | None  # { people: ["name", "email"], organizations: [], urls: [], dates: [] }
    raw_payload: dict[str, Any] | None