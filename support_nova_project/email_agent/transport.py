"""
How emails get in and out. Two interchangeable transports, chosen with EMAIL_AGENT_TRANSPORT:

  gmail  (default)  Agno's GmailTools: reads unread mail and replies inside the same Gmail thread.
                    One-time setup: Google OAuth client in .env, then `manage.py gmail_login`.
  imap              the plain IMAP / SMTP settings the rest of the system already uses.

A transport only moves mail. Who the sender is and what to answer is decided in service.py.
"""

import email
import imaplib
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from email.policy import default as default_policy
from email.utils import parseaddr
from html import escape
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage as DjangoEmail


class TransportError(Exception):
    """The mailbox could not be read or written (not set up, signed out, offline ...). Plain words."""


@dataclass
class Incoming:
    id: str  # the mailbox's id for this email
    thread_id: str
    sender: str  # address only, lower case
    name: str
    subject: str
    body: str  # the whole text, quoted earlier mail included
    automated: bool = False  # a robot (auto-reply, bounce, newsletter): never answered
    rfc_id: str = ""  # the Message-ID header, for threading
    references: str = ""
    uid: bytes | None = None  # IMAP only


# Mail from robots, and from ourselves, is never answered: two auto-responders would write to each other forever.
ROBOT_SENDER = re.compile(r"(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounce|notifications?@|newsletter)", re.IGNORECASE)
ROBOT_SUBJECT = re.compile(r"^\s*(automatic reply|auto(matic)?[- ]?reply|out of office|undeliverable|delivery status|mail delivery)", re.IGNORECASE)


def looks_automated(sender, subject, headers=None):
    headers = headers or {}
    return bool(
        ROBOT_SENDER.search(sender or "") or ROBOT_SUBJECT.search(subject or "")
        or str(headers.get("Auto-Submitted", "no")).lower() != "no" or str(headers.get("Precedence", "")).lower() in ("bulk", "junk", "list")
    )


def own_addresses():
    addresses = {parseaddr(settings.DEFAULT_FROM_EMAIL)[1].lower(), (settings.SMTP_USER or "").lower(), (settings.EMAIL_AGENT_ADDRESS or "").lower()}
    return {a for a in addresses if a}


# ---------------- Gmail through Agno ----------------


class GmailTransport:
    name = "gmail"
    QUERY = "is:unread in:inbox -from:me -category:promotions -category:social -category:forums"

    def __init__(self, tools=None):
        self._tools = tools

    @staticmethod
    def configured():
        """(ready, what is missing in plain words)."""
        have_client = all(getattr(settings, k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_PROJECT_ID"))
        if not (have_client or Path(settings.GMAIL_CREDENTIALS_PATH).exists()):
            return False, "Add GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_PROJECT_ID to .env (Google Cloud console, Gmail API)."
        if not Path(settings.GMAIL_TOKEN_PATH).exists():
            return False, "Sign the mailbox in once: python manage.py gmail_login"
        return True, ""

    @property
    def tools(self):
        if self._tools is None:
            from agno.tools.google.gmail import GmailTools

            # Never open a browser from a background thread: an expired sign-in is reported instead.
            import os

            os.environ.setdefault("GOOGLE_OAUTH_NONINTERACTIVE", "1")
            self._tools = GmailTools(credentials_path=str(settings.GMAIL_CREDENTIALS_PATH), token_path=str(settings.GMAIL_TOKEN_PATH),
                                     max_results=settings.EMAIL_AGENT_BATCH)
        return self._tools

    def _json(self, raw):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            raise TransportError(f"Gmail gave an unreadable answer: {str(raw)[:120]}")
        if isinstance(data, dict) and data.get("error"):
            raise TransportError(f"Gmail: {str(data['error'])[:200]}")
        return data

    def fetch(self, limit, accept=None):
        data = self._json(self.tools.search_emails(query=f"{self.QUERY} newer_than:{settings.EMAIL_AGENT_SINCE_DAYS}d", count=limit))
        found = []
        for m in data.get("emails", []):
            name, address = parseaddr(m.get("from") or "")
            subject = m.get("subject") or ""
            if accept and not accept(address.lower()):
                continue  # not a customer: left alone
            found.append(Incoming(
                id=m["id"], thread_id=m.get("thread_id") or "", sender=address.lower(), name=name, subject=subject, body=m.get("body") or "",
                automated=looks_automated(address, subject), references=m.get("references") or "",
            ))
        return found

    def reply(self, incoming, body):
        subject = incoming.subject or "Your message to Lumora Support"
        # Gmail sends the body as HTML: escape it so nothing the customer or the AI wrote can be read as markup.
        sent = self.tools.send_email_reply(thread_id=incoming.thread_id, message_id=incoming.id, to=incoming.sender, subject=subject, body=escape(body.strip()))
        if not str(sent).lstrip().startswith("{"):
            raise TransportError(f"Gmail could not send the reply: {str(sent)[:200]}")

    def mark_read(self, incoming):
        self.tools.mark_email_as_read(message_id=incoming.id)

    def check(self):
        self.fetch(1)


# ---------------- plain IMAP / SMTP ----------------


class ImapTransport:
    name = "imap"

    @staticmethod
    def configured():
        if not (settings.IMAP_HOST and settings.IMAP_USER and settings.IMAP_PASSWORD):
            return False, "Set IMAP_HOST (imap.gmail.com) and the mailbox login (EMAIL_HOST_USER and EMAIL_HOST_PASSWORD, an app password) in .env."
        if not settings.SMTP_HOST:
            return False, "Set EMAIL_HOST (smtp.gmail.com) in .env too: without it replies are only saved as files and never sent."
        return True, ""

    def _inbox(self):
        try:
            inbox = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
            inbox.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
            inbox.select(settings.IMAP_FOLDER)
            return inbox
        except (OSError, imaplib.IMAP4.error) as e:
            raise TransportError(f"The mailbox could not be opened: {e}")

    def fetch(self, limit, accept=None, unseen=True):
        """
        Recent unread mail, newest first. The mailbox may be a busy one (thousands of unread emails), so only
        the last EMAIL_AGENT_SINCE_DAYS days are looked at, the sender is read from the headers alone, and the
        body of an email is downloaded only when `accept(sender address)` says the sender matters. Everything
        else is left exactly as it was: not downloaded, not recorded, not marked read.
        """
        inbox = self._inbox()
        found = []
        since = (date.today() - timedelta(days=settings.EMAIL_AGENT_SINCE_DAYS)).strftime("%d-%b-%Y")
        try:
            _, ids = inbox.uid("search", None, *(["UNSEEN"] if unseen else []), "SINCE", since)
            recent = ids[0].split()[-settings.EMAIL_AGENT_SCAN:]
            senders = self._senders(inbox, recent) if recent else {}
            for uid in reversed(recent):
                if len(found) >= limit:
                    break
                if accept and not accept(senders.get(uid, "")):
                    continue
                _, data = inbox.uid("fetch", uid, "(BODY.PEEK[])")  # PEEK: reading does not mark it as read
                found.append(self._incoming(uid, email.message_from_bytes(data[0][1], policy=default_policy)))
        finally:
            inbox.logout()
        return found

    @staticmethod
    def _senders(inbox, uids):
        """{uid: sender address} for many emails in ONE request: only the From header is downloaded."""
        _, data = inbox.uid("fetch", b",".join(uids), "(BODY.PEEK[HEADER.FIELDS (FROM)])")
        senders = {}
        for part in data:
            if isinstance(part, tuple):
                uid = re.search(rb"UID (\d+)", part[0])
                if uid:
                    message = email.message_from_bytes(part[1], policy=default_policy)
                    senders[uid.group(1)] = parseaddr(str(message.get("From") or ""))[1].lower()
        return senders

    @staticmethod
    def _incoming(uid, message):
        name, address = parseaddr(str(message.get("From") or ""))
        part = message.get_body(preferencelist=("plain", "html"))
        text = part.get_content() if part else ""
        if part is not None and part.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
        subject = str(message.get("Subject") or "")
        refs = str(message.get("References") or "")
        rfc_id = str(message.get("Message-ID") or "")
        return Incoming(
            id=rfc_id or f"imap-{uid.decode()}", thread_id=(refs.split() or [rfc_id])[0], sender=address.lower(), name=name, subject=subject,
            body=text, automated=looks_automated(address, subject, message), rfc_id=rfc_id, references=refs, uid=uid,
        )

    def reply(self, incoming, body):
        subject = incoming.subject if incoming.subject.lower().startswith("re:") else f"Re: {incoming.subject}"
        headers = {"In-Reply-To": incoming.rfc_id, "References": f"{incoming.references} {incoming.rfc_id}".strip()} if incoming.rfc_id else {}
        sender = f"Lumora Support <{settings.EMAIL_AGENT_ADDRESS}>" if settings.EMAIL_AGENT_ADDRESS else None
        try:
            DjangoEmail(subject, body.strip(), sender, [incoming.sender], headers=headers).send()
        except Exception as e:
            raise TransportError(f"The reply could not be sent: {e}")

    def mark_read(self, incoming):
        uid = incoming.uid
        if uid is None:
            return
        inbox = self._inbox()
        try:
            inbox.uid("store", uid, "+FLAGS", "\\Seen")
        finally:
            inbox.logout()

    def check(self):
        self._inbox().logout()


TRANSPORTS = {"gmail": GmailTransport, "imap": ImapTransport}


def transport_class():
    return TRANSPORTS.get(settings.EMAIL_AGENT_TRANSPORT, GmailTransport)


def get_transport():
    cls = transport_class()
    ready, missing = cls.configured()
    if not ready:
        raise TransportError(missing)
    return cls()
