from datetime import datetime

from ninja import Schema
from pydantic import Field


class TurnIn(Schema):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(max_length=2000)


class ChatIn(Schema):
    question: str = Field(min_length=1, max_length=2000)
    history: list[TurnIn] = []  # earlier messages of this chat, kept by the browser


class SourceOut(Schema):
    title: str
    section: str


class ChatOut(Schema):
    answer: str
    status: str  # answered | unanswered | blocked | failed
    sources: list[SourceOut]
    suggest_complaint: bool  # the answer was not found: offer to send a complaint


class ChatStatusOut(Schema):
    enabled: bool


class SharedDocOut(Schema):
    doc_id: str
    title: str
    doc_type: str
    shared: bool


class ChatStatsOut(Schema):
    total: int
    answered: int
    unanswered: int
    blocked: int
    failed: int
    last_error: str | None  # plain words, when the latest question failed


class ChatSettingsOut(Schema):
    enabled: bool
    updated_at: datetime
    documents: list[SharedDocOut]
    stats: ChatStatsOut
    email: "EmailAssistantOut"


class ChatSettingsIn(Schema):
    enabled: bool | None = None
    email_enabled: bool | None = None
    shared_docs: list[str] | None = None


class ExchangeOut(Schema):
    id: int
    question: str
    answer: str
    status: str
    sources: list[SourceOut]
    error_kind: str
    created_at: datetime


class EmailStatsOut(Schema):
    total: int
    replied: int
    lodged: int  # complaints opened by an email
    forwarded: int  # emails added to a customer's existing complaint
    ignored: int
    failed: int


class EmailAssistantOut(Schema):
    enabled: bool
    transport: str  # gmail | imap
    ready: bool  # the mailbox is set up
    setup_hint: str  # what is missing, in plain words ("" when ready)
    last_poll_at: datetime | None
    last_error: str | None
    listening: bool  # the background listener is running in this server
    stats: EmailStatsOut


class EmailExchangeOut(Schema):
    id: int
    customer_name: str | None
    subject: str
    body: str
    reply: str
    outcome: str
    reason: str
    complaints: list[str]
    received_at: datetime


ChatSettingsOut.model_rebuild()  # EmailAssistantOut is defined after it
