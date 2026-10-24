"""Customer chat assistant: ask a question (anyone signed in), and the administrator's switch, documents and log."""

import threading

from django.conf import settings
from django.db.models import Count, Q
from ninja import Router
from ninja.errors import HttpError

from accounts.auth import require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from email_agent.models import EmailMessage
from email_agent.transport import transport_class
from genai_pipeline.client import FRIENDLY
from knowledge_base.models import DocumentStatus, PolicyDocument

from . import service
from .models import ChatbotSettings, ChatExchange
from .schemas import ChatIn, ChatOut, ChatSettingsIn, ChatSettingsOut, ChatStatusOut, EmailExchangeOut, ExchangeOut

router = Router(tags=["Chat assistant"])
ADMIN = User.Role.ADMIN


@router.get("/status", response=ChatStatusOut)
def status(request):
    """Is the chat assistant switched on? The customer pages show the chat button only when it is."""
    return {"enabled": ChatbotSettings.get().enabled}


@router.post("/chat", response={200: ChatOut, 400: ErrorOut, 403: ErrorOut, 429: ErrorOut})
def chat(request, data: ChatIn):
    """Answer a general question from the shared company documents. It knows nothing about the person asking."""
    try:
        service.check_rate(request.auth)
        return service.ask(data.question, data.history)
    except service.ChatError as e:
        return e.status, {"detail": str(e)}


def _stats():
    counts = ChatExchange.objects.aggregate(
        total=Count("id"), answered=Count("id", filter=Q(status="answered")), unanswered=Count("id", filter=Q(status="unanswered")),
        blocked=Count("id", filter=Q(status="blocked")), failed=Count("id", filter=Q(status="failed")),
    )
    latest = ChatExchange.objects.first()
    # Only a failure on the most recent question is a current problem.
    failing = latest is not None and latest.status == ChatExchange.Status.FAILED
    counts["last_error"] = FRIENDLY.get(latest.error_kind, FRIENDLY["other"]) if failing else None
    return counts


def _email_out(config):
    ready, hint = transport_class().configured()
    counts = EmailMessage.objects.aggregate(
        total=Count("id"), replied=Count("id", filter=Q(outcome="replied")), lodged=Count("id", filter=Q(outcome="lodged")),
        forwarded=Count("id", filter=Q(outcome="forwarded")), ignored=Count("id", filter=Q(outcome="ignored")), failed=Count("id", filter=Q(outcome="failed")),
    )
    listener = next((t for t in threading.enumerate() if t.name == "email-assistant"), None)
    return {
        "enabled": config.email_enabled, "transport": settings.EMAIL_AGENT_TRANSPORT, "ready": ready, "setup_hint": hint,
        "last_poll_at": config.email_last_poll, "last_error": config.email_last_error or None,
        "listening": bool(listener and listener.is_alive()), "stats": counts,
    }


def _settings_out(config):
    documents = [
        {"doc_id": d.doc_id, "title": d.title, "doc_type": d.doc_type, "shared": d.doc_id in config.shared_docs}
        for d in PolicyDocument.objects.filter(status=DocumentStatus.ACTIVE).order_by("doc_id")
    ]
    return {"enabled": config.enabled, "updated_at": config.updated_at, "documents": documents, "stats": _stats(), "email": _email_out(config)}


@router.get("/settings", response=ChatSettingsOut)
def get_settings(request):
    require_role(request, ADMIN)
    return _settings_out(ChatbotSettings.get())


@router.put("/settings", response=ChatSettingsOut)
def update_settings(request, data: ChatSettingsIn):
    """Administrators: switch the assistant on or off, and choose which documents customers may ask about."""
    require_role(request, ADMIN)
    config = ChatbotSettings.get()
    if data.enabled is not None:
        config.enabled = data.enabled
    if data.email_enabled is not None:
        ready, hint = transport_class().configured()
        if data.email_enabled and not ready:
            raise HttpError(400, f"The mailbox is not set up yet. {hint}")
        config.email_enabled = data.email_enabled
        if not data.email_enabled:
            config.email_last_error = ""
    if data.shared_docs is not None:
        unknown = sorted(set(data.shared_docs) - set(PolicyDocument.objects.values_list("doc_id", flat=True)))
        if unknown:
            raise HttpError(400, f"Unknown documents: {', '.join(unknown)}.")
        config.shared_docs = sorted(set(data.shared_docs))
    config.updated_by = request.auth
    config.save()
    return _settings_out(config)


@router.get("/email-exchanges", response=list[EmailExchangeOut])
def email_exchanges(request, outcome: str | None = None, limit: int = 30):
    """Administrators: the latest customer emails and what the assistant did with them."""
    require_role(request, ADMIN)
    rows = EmailMessage.objects.select_related("customer")
    if outcome:
        rows = rows.filter(outcome=outcome)
    return [
        {"id": m.id, "customer_name": m.customer.display_name if m.customer else None, "subject": m.subject, "body": m.body, "reply": m.reply,
         "outcome": m.outcome, "reason": m.reason, "complaints": m.complaints, "received_at": m.received_at}
        for m in rows[: max(1, min(limit, 100))]
    ]


@router.get("/exchanges", response=list[ExchangeOut])
def exchanges(request, status: str | None = None, limit: int = 30):
    """Administrators: the latest questions and answers (no customer is recorded)."""
    require_role(request, ADMIN)
    rows = ChatExchange.objects.all()
    if status:
        rows = rows.filter(status=status)
    return list(rows[: max(1, min(limit, 100))])
