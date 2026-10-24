"""
Read new emails from the support inbox (IMAP) and bring them into SupportNova.

  - a reply about a complaint ("Re: [CMP-00012] ...") from that customer -> added to the complaint
  - an email from a registered customer without a complaint number     -> a new complaint (channel: email)
  - anything else is left unread in the inbox for a person to look at

Needs IMAP_HOST (and the mailbox login) in .env. Run it on a schedule, e.g. every 5 minutes:
    python manage.py fetch_emails
"""

import email
import imaplib
from collections import Counter
from email.policy import default

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from workflow.emails import import_email


class Command(BaseCommand):
    help = "Import new customer emails from the support inbox (IMAP)."

    def handle(self, *args, **options):
        if not settings.IMAP_HOST:
            raise CommandError("Set IMAP_HOST, and the mailbox username and password, in .env first.")
        counts = Counter()
        inbox = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        try:
            inbox.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
            inbox.select(settings.IMAP_FOLDER)
            _, found = inbox.search(None, "UNSEEN")
            for number in found[0].split():
                # BODY.PEEK reads the email without marking it as read; we mark it only once it is imported.
                _, data = inbox.fetch(number, "(BODY.PEEK[])")
                outcome = import_email(email.message_from_bytes(data[0][1], policy=default))
                if outcome != "skipped":
                    inbox.store(number, "+FLAGS", "\\Seen")
                counts[outcome] += 1
        finally:
            inbox.logout()
        self.stdout.write(self.style.SUCCESS(
            f"Replies: {counts['reply']} | reopened: {counts['reopened']} | new complaints: {counts['new']} | "
            f"left in the inbox: {counts['skipped']}"
        ))
