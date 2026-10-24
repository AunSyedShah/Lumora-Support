"""
Run the email assistant as its own process (instead of the web server's background thread):

    uv run python manage.py run_email_agent          # keep listening
    uv run python manage.py run_email_agent --once   # one round, e.g. from a scheduler

It still only works while an administrator has the email assistant switched on (Settings > Customer chat).
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from email_agent.service import poll_once


class Command(BaseCommand):
    help = "Read new customer emails and let the assistant answer them."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Do one round and stop.")

    def handle(self, *args, **options):
        while True:
            handled = poll_once()
            if options["once"]:
                self.stdout.write("Switched off by an administrator." if handled is None else f"Handled {handled} email(s).")
                return
            time.sleep(settings.EMAIL_AGENT_POLL_SECONDS)
