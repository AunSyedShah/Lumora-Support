"""
Handle customer emails with the Agno agent.

For every unread email, in this order:
  1. robots and ourselves             -> ignored (two auto-responders would write to each other forever)
  2. the sender                       -> must be the registered address of exactly one customer, else ignored
  3. too many emails from them        -> ignored for now (a loop or a flood must not run up AI costs)
  4. an attempt to give the AI orders -> ignored
  5. the subject carries a complaint number ("Re: [CMP-00012] ...") of THEIR complaint
                                      -> their words go to that complaint for the team, as before. No AI.
  6. otherwise the agent reads it and, with tools tied to this customer, answers a question, reports a
     complaint's status or lodges a complaint; the reply goes back in the same thread.
Each email is recorded once (EmailMessage): a retry never answers twice or lodges a complaint twice.
"""

import logging
import re
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.models import User
from chatbot.models import ChatbotSettings
from chatbot.service import error_kind
from complaints.models import Complaint
from complaints.preprocessing import mask_card_numbers, sanitize
from complaints.security import detect_injection
from workflow.emails import COMPLAINT_ID
from workflow.services import WorkflowError, customer_reopen, customer_reply

from . import agent as email_agent
from .models import EmailMessage
from .tools import CustomerTools
from .transport import TransportError, get_transport, own_addresses

logger = logging.getLogger(__name__)
Outcome = EmailMessage.Outcome

MAX_BODY = 4000
HISTORY_EXCHANGES = 3
FOOTER = "\n\n--\nLumora Support's automated assistant. To reach a person, just reply and ask for one, and we will open a complaint for you."
# Where the quoted earlier mail starts in a reply; Gmail often wraps "On <date>, <name> <address> wrote:" over two lines.
QUOTE_START = re.compile(r"^\s*(>|-+\s*Original Message\s*-+|From:\s)", re.IGNORECASE)
WROTE_LINE = re.compile(r"^\s*On .{5,200}$")


def new_text(body):
    """What the customer wrote, without the quoted earlier mail below it."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    kept = []
    for i, line in enumerate(lines):
        wrapped = " ".join(lines[i:i + 2]).rstrip()
        if QUOTE_START.match(line) or (WROTE_LINE.match(line) and wrapped.endswith("wrote:")):
            break
        kept.append(line.rstrip())
    return mask_card_numbers(sanitize("\n".join(kept)))[0][:MAX_BODY]


def _finish(row, outcome, reason="", **fields):
    row.outcome, row.reason, row.handled_at = outcome, reason, timezone.now()
    for key, value in fields.items():
        setattr(row, key, value)
    row.save()
    return row


def _history(customer, row):
    """The last few exchanges with this customer in the same email thread, so "and for opened items?" makes sense."""
    if not row.thread_id:
        return []
    earlier = EmailMessage.objects.filter(customer=customer, thread_id=row.thread_id).exclude(pk=row.pk).exclude(reply="").order_by("-received_at")[:HISTORY_EXCHANGES]
    turns = []
    for m in reversed(list(earlier)):
        turns += [("user", m.body), ("assistant", m.reply)]
    return turns


def _forward(customer, complaint, text):
    """A customer's email about their complaint is for the team. Returns something to tell the customer only if it could not be added."""
    try:
        if complaint.status in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED):
            customer_reopen(complaint, customer, text)
        else:
            customer_reply(complaint, customer, text)
    except WorkflowError as e:  # e.g. too late to reopen: the message is friendly and says what to do
        return f"Hi {customer.first_name or 'there'},\n\n{e}"
    return None


def _fallback(row, transport, incoming, customer, text, kind):
    """The AI keeps failing (key, balance, outage): the customer's message must not be lost, so log it as a complaint."""
    tools = CustomerTools(customer)
    result = tools.lodge_complaint(incoming.subject or text[:80], text)
    if not tools.lodged:
        return _finish(row, Outcome.FAILED, "ai_unavailable", error_kind=kind)
    row.reply = f"Hi {customer.first_name or 'there'},\n\nOur assistant could not read your message just now, so we have logged it for the team. {result}"
    try:
        transport.reply(incoming, row.reply + FOOTER)
    except Exception:
        logger.exception("Could not confirm complaint %s by email", tools.lodged)
    return _finish(row, Outcome.LODGED, "ai_unavailable", complaints=tools.lodged, error_kind=kind)


def _answer(row, transport, incoming, customer, text):
    """Ask the agent (once) and send its reply. Returns the row; outcome stays PENDING when it will be retried."""
    if not row.reply:  # a reply that was written but not sent yet is simply sent again, without asking the AI twice
        row.attempts += 1
        tools = CustomerTools(customer)
        try:
            result = email_agent.run(customer, tools, _history(customer, row), incoming.subject, text)
            answer = email_agent.final_text(result)
            if not answer:
                raise ValueError("The assistant gave an empty answer.")
        except Exception as e:
            logger.warning("Email assistant failed on %s (attempt %s): %s", incoming.id, row.attempts, e)
            row.error_kind = error_kind(e)
            if row.attempts >= settings.EMAIL_AGENT_MAX_ATTEMPTS:
                return _fallback(row, transport, incoming, customer, text, row.error_kind)
            row.save()
            return row
        metrics = getattr(result, "metrics", None)
        row.input_tokens = getattr(metrics, "input_tokens", 0) or 0
        row.output_tokens = getattr(metrics, "output_tokens", 0) or 0
        row.reply, row.complaints, row.lodged = answer, tools.lodged + tools.touched, bool(tools.lodged)
        row.save()
    try:
        transport.reply(incoming, row.reply + FOOTER)
    except Exception as e:
        logger.warning("Reply to %s was not sent: %s", incoming.id, e)
        row.attempts += 1
        if row.attempts >= settings.EMAIL_AGENT_MAX_ATTEMPTS:
            return _finish(row, Outcome.FAILED, "reply_not_sent")
        row.save()
        return row
    return _finish(row, Outcome.LODGED if row.lodged else Outcome.REPLIED)


def _handle_customer(row, transport, incoming, customer, text):
    hour_ago = timezone.now() - timedelta(hours=1)
    recent = EmailMessage.objects.filter(sender=incoming.sender, handled_at__gte=hour_ago).exclude(outcome=Outcome.IGNORED).count()
    if recent >= settings.EMAIL_AGENT_MAX_PER_HOUR:
        return _finish(row, Outcome.IGNORED, "too_many_emails")
    if not text:
        return _finish(row, Outcome.IGNORED, "empty")
    if detect_injection(text):
        return _finish(row, Outcome.IGNORED, "refused")

    reference = COMPLAINT_ID.search(incoming.subject or "")
    complaint = Complaint.objects.filter(complaint_id=reference.group().upper(), customer=customer).first() if reference else None
    if complaint is not None:
        notice = _forward(customer, complaint, text)
        if notice:
            try:
                transport.reply(incoming, notice + FOOTER)
            except Exception:
                logger.exception("Could not tell %s why their message was not added", incoming.sender)
        return _finish(row, Outcome.FORWARDED, complaints=[complaint.complaint_id])
    return _answer(row, transport, incoming, customer, text)


def handle(incoming, transport):
    """Look at one email once. Returns the outcome; "pending" means it will be retried on the next round."""
    row, _ = EmailMessage.objects.get_or_create(
        message_id=incoming.id,
        defaults={"thread_id": incoming.thread_id, "sender": incoming.sender or "unknown@invalid.example", "subject": incoming.subject[:300]},
    )
    if row.outcome not in EmailMessage.FINAL:
        row.body = new_text(incoming.body)
        if incoming.automated or incoming.sender in own_addresses():
            _finish(row, Outcome.IGNORED, "automatic_mail")
        else:
            customers = list(User.objects.filter(email__iexact=incoming.sender, role=User.Role.CUSTOMER, is_active=True)[:2])
            if len(customers) != 1:
                _finish(row, Outcome.IGNORED, "unknown_sender" if not customers else "ambiguous_sender")
            else:
                row.customer = customers[0]
                _handle_customer(row, transport, incoming, customers[0], row.body)
    if row.outcome != Outcome.PENDING:
        try:
            transport.mark_read(incoming)
        except Exception:  # it is recorded, so it is not answered again either way
            logger.exception("Could not mark email %s as read", incoming.id)
    return row.outcome


def poll_once(transport=None):
    """One round: read the unread emails and handle each. Does nothing while an administrator has it switched off."""
    config = ChatbotSettings.get()
    if not config.email_enabled:
        return None
    store = ChatbotSettings.objects.filter(pk=config.pk)
    try:
        transport = transport or get_transport()
        # Only mail from registered customers is ever read; everything else in the mailbox is left untouched.
        customers = {e.lower() for e in User.objects.filter(role=User.Role.CUSTOMER, is_active=True).exclude(email="").values_list("email", flat=True)}
        emails = transport.fetch(settings.EMAIL_AGENT_BATCH, accept=customers.__contains__)
    except TransportError as e:
        store.update(email_last_poll=timezone.now(), email_last_error=str(e)[:300])
        return None
    handled = 0
    for incoming in emails:
        try:
            handle(incoming, transport)
            handled += 1
        except Exception:  # one bad email must never stop the others
            logger.exception("Email %s could not be handled", incoming.id)
    store.update(email_last_poll=timezone.now(), email_last_error="")
    return handled
