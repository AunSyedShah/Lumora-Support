"""
Email with customers.

Outgoing (SMTP): the customer gets an email when we receive their complaint, when we reply or post an
update, and when it is resolved - only if they chose email as their contact and have an address.
Every subject carries the complaint number, e.g. "[CMP-00012] Parcel not delivered".

Incoming (IMAP, see `manage.py fetch_emails`): import_email() turns one email into
  - a customer reply   : the subject has a complaint number and it comes from that complaint's customer
                         (a resolved complaint is reopened if it is still within the reopen window)
  - a new complaint    : it comes from a registered customer and has no complaint number (channel "email")
  - nothing ("skipped"): unknown sender or empty text, left for a person to look at

Sending never breaks the workflow: a failed email is logged and the complaint carries on.
"""

import logging
import re

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from complaints.models import Complaint

logger = logging.getLogger(__name__)

COMPLAINT_ID = re.compile(r"CMP-\d{5}", re.IGNORECASE)
# Where the quoted earlier email starts in a reply ("On Mon, 1 Sep ... wrote:", "> ...", Outlook's header)
QUOTE_START = re.compile(r"^\s*(>|On .+wrote:\s*$|-+\s*Original Message\s*-+|From:\s)", re.IGNORECASE)


# ---------------- outgoing ----------------


def _when(value):
    return timezone.localtime(value).strftime("%d %b, %H:%M") if value else None


def notify_customer(complaint, headline, text=""):
    """Email the customer about their complaint (after the database change is saved)."""
    customer = complaint.customer
    if not customer.email or complaint.preferred_contact != Complaint.ContactChannel.EMAIL:
        return
    link = f"{settings.FRONTEND_URL}/my/complaints/{complaint.complaint_id}"
    body = "\n\n".join(part for part in [
        f"Hi {customer.first_name or 'there'},",
        headline,
        text,
        f"You can follow your complaint here: {link}\nOr simply reply to this email - your answer is added to your complaint.",
        "Lumora Support",
    ] if part)
    subject = f"[{complaint.complaint_id}] {complaint.title}"

    def send():
        try:
            send_mail(subject, body, None, [customer.email])
        except Exception:  # a mail server problem must never undo the customer's complaint or our reply
            logger.exception("Could not email %s about %s", customer.email, complaint.complaint_id)

    transaction.on_commit(send)


def acknowledge(complaint):
    due = _when(complaint.sla_response_due)
    notify_customer(complaint, f"Thanks for telling us - we've got your complaint (reference {complaint.complaint_id})."
                               + (f" We'll reply by {due}." if due else ""))


# ---------------- incoming ----------------


def new_text(message):
    """The plain text the customer wrote, without the quoted earlier email below it."""
    part = message.get_body(preferencelist=("plain", "html"))
    text = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for line in text.splitlines():
        if QUOTE_START.match(line):
            break
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def import_email(message):
    """Bring one email into SupportNova. Returns "reply", "reopened", "new" or "skipped"."""
    # Imported here: the workflow services import this module to send emails.
    from complaints.services import ComplaintValidationError, submit_complaint

    from .services import WorkflowError, auto_process, customer_reopen, customer_reply

    address = (message.get("From") and message["From"].addresses[0].addr_spec or "").lower()
    subject = str(message.get("Subject") or "").strip()
    text = new_text(message)
    customer = User.objects.filter(email__iexact=address, role=User.Role.CUSTOMER).first() if address else None
    if customer is None or not text:
        return "skipped"

    reference = COMPLAINT_ID.search(subject)
    if reference:
        complaint = Complaint.objects.filter(complaint_id=reference.group().upper(), customer=customer).first()
        if complaint is None:
            return "skipped"
        try:
            if complaint.status in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED):
                customer_reopen(complaint, customer, text)
                return "reopened"
            customer_reply(complaint, customer, text)
            return "reply"
        except WorkflowError:  # e.g. too late to reopen
            return "skipped"

    fields = {"title": subject[:200] or text[:80], "description": text, "product": None, "order_ref": None,
              "channel": Complaint.Channel.EMAIL, "preferred_contact": Complaint.ContactChannel.EMAIL,
              "previous_complaint_ref": None, "requested_resolution": "", "supporting_information": ""}
    try:
        complaint, _warnings = submit_complaint(fields, customer=customer, submitted_by=customer)
    except ComplaintValidationError:  # too short, or the same complaint again
        return "skipped"
    auto_process(complaint)
    complaint.refresh_from_db()
    acknowledge(complaint)
    return "new"
