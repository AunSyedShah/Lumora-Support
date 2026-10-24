"""
Sign the support Gmail mailbox in, once. Opens a browser for Google's consent screen and saves the token
(GMAIL_TOKEN_PATH) that the email assistant uses afterwards.

Before this, in the Google Cloud console: enable the Gmail API, create an OAuth client (desktop app or web with
redirect http://127.0.0.1/) and put GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_PROJECT_ID in .env.

    uv run python manage.py gmail_login
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from email_agent.transport import GmailTransport, TransportError


class Command(BaseCommand):
    help = "Sign the support Gmail mailbox in (one time)."

    def handle(self, *args, **options):
        os.environ.pop("GOOGLE_OAUTH_NONINTERACTIVE", None)  # this one time a browser is wanted
        from agno.tools.google.gmail import GmailTools

        transport = GmailTransport(GmailTools(credentials_path=str(settings.GMAIL_CREDENTIALS_PATH), token_path=str(settings.GMAIL_TOKEN_PATH)))
        try:
            transport.check()
        except TransportError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Signed in. Token saved to {settings.GMAIL_TOKEN_PATH}. Now switch the email assistant on in Settings > Customer chat."))
