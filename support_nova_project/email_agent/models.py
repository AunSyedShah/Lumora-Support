"""
Every customer email the email assistant has looked at, once. The message id makes handling safe to repeat:
an email that was already answered is never answered again, even if the mailbox still shows it as unread.
"""

from django.conf import settings
from django.db import models


class EmailMessage(models.Model):
    class Outcome(models.TextChoices):
        PENDING = "pending", "Being handled"
        REPLIED = "replied", "Answered by the assistant"
        LODGED = "lodged", "A complaint was lodged"
        FORWARDED = "forwarded", "Added to the customer's complaint"
        IGNORED = "ignored", "Not answered (unknown sender, automatic mail or refused)"
        FAILED = "failed", "The assistant could not answer"

    FINAL = (Outcome.REPLIED, Outcome.LODGED, Outcome.FORWARDED, Outcome.IGNORED, Outcome.FAILED)

    message_id = models.CharField(max_length=255, unique=True)  # the mailbox's own id for the email
    thread_id = models.CharField(max_length=255, blank=True, db_index=True)
    sender = models.EmailField()
    subject = models.CharField(max_length=300, blank=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField(blank=True)  # what the customer wrote, without the quoted earlier mail
    reply = models.TextField(blank=True)  # what we answered
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.PENDING)
    reason = models.CharField(max_length=60, blank=True)  # why it was ignored or failed
    complaints = models.JSONField(default=list)  # complaint ids lodged or added to by this email
    lodged = models.BooleanField(default=False)  # this email created (not just added to) a complaint
    attempts = models.PositiveSmallIntegerField(default=0)
    error_kind = models.CharField(max_length=20, blank=True)  # genai_pipeline.client.FRIENDLY kinds
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    received_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]
