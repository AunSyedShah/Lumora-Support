"""
The email assistant listens in a background thread: every EMAIL_AGENT_POLL_SECONDS it looks at the mailbox,
as long as an administrator has it switched on. The switch is read from the database each round, so
turning it on or off needs no restart.

A thread lives only as long as the web server process. For a server that is not always running (for
example serverless hosting) run the same loop as its own process instead:  manage.py run_email_agent
"""

import logging
import sys
import threading

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)
_thread = None


class EmailListener(threading.Thread):
    def __init__(self, interval=None):
        super().__init__(name="email-assistant", daemon=True)  # daemon: it never keeps the server from stopping
        self.interval = interval or settings.EMAIL_AGENT_POLL_SECONDS
        self.stopping = threading.Event()

    def run(self):
        # Imported here, in the background thread: the AI libraries are slow to load and every manage.py command
        # (migrate, check, shell ...) would otherwise pay for them just to start up.
        from .service import poll_once

        logger.info("Email assistant is listening (every %s s).", self.interval)
        while not self.stopping.is_set():
            try:
                poll_once()
            except Exception:  # whatever happens, the next round still runs
                logger.exception("Email assistant round failed")
            finally:
                close_old_connections()  # a thread owns its database connection; do not let it go stale
            self.stopping.wait(self.interval)

    def stop(self):
        self.stopping.set()


def start():
    """Start the listener once per process. Returns the thread."""
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = EmailListener()
        _thread.start()
    return _thread


def should_autostart(argv=None, environ=None):
    """Only in a running web server: not in tests, migrations, shells or other manage.py commands."""
    import os

    argv = sys.argv if argv is None else argv
    environ = os.environ if environ is None else environ
    if not settings.EMAIL_AGENT_THREAD:
        return False
    if argv and argv[0].endswith("manage.py"):
        if len(argv) < 2 or argv[1] != "runserver":
            return False
        # runserver starts a second process that reloads on every edit; only that one serves requests
        return environ.get("RUN_MAIN") == "true" or "--noreload" in argv
    return True  # started by a WSGI / ASGI server such as gunicorn
