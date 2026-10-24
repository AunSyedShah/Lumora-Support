"""
Customer chat assistant: a general question-and-answer helper that answers only from the company documents
an administrator has chosen to share. It knows nothing about who is asking (no account, order or complaint
data), so nothing here links a chat to a customer.

ChatbotSettings  - one row: on/off switch and which documents customers may ask about.
ChatExchange     - one question and answer, kept so administrators can see what customers ask and where
                   the documents have gaps. No user is stored.
"""

from django.conf import settings
from django.db import models

# Documents of these types are offered to customers by default (internal guides, routing rules and
# response templates are not). "Compensation" guidelines are for staff, so they start switched off.
CUSTOMER_FACING_TYPES = ("policy", "faq", "sla")


class ChatbotSettings(models.Model):
    enabled = models.BooleanField(default=False)
    shared_docs = models.JSONField(default=list)  # doc_ids customers may ask about
    # The same assistant answering customers' emails (see email_agent). Off until an administrator switches it on.
    email_enabled = models.BooleanField(default=False)
    email_last_poll = models.DateTimeField(null=True, blank=True)  # when the mailbox was last checked
    email_last_error = models.CharField(max_length=300, blank=True)  # why the last check failed, in plain words
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        """The single settings row. On first use it shares the customer-facing documents that exist."""
        obj = cls.objects.first()
        if obj is None:
            from knowledge_base.models import DocumentStatus, PolicyDocument

            documents = PolicyDocument.objects.filter(status=DocumentStatus.ACTIVE, doc_type__in=CUSTOMER_FACING_TYPES)
            shared = sorted({d.doc_id for d in documents if "compensation" not in d.title.lower()})
            obj = cls.objects.create(shared_docs=shared)
        return obj


class ChatExchange(models.Model):
    class Status(models.TextChoices):
        ANSWERED = "answered", "Answered from the documents"
        UNANSWERED = "unanswered", "The documents do not cover it"
        BLOCKED = "blocked", "Blocked (not a real question)"
        FAILED = "failed", "The assistant was not available"

    question = models.TextField()
    answer = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices)
    sources = models.JSONField(default=list)  # [{"title", "section", "heading"}]
    error_kind = models.CharField(max_length=20, blank=True)  # same kinds as genai_pipeline.client.FRIENDLY
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
