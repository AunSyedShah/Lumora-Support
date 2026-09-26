"""
Workflow records.

AuditLog      append-only history of everything that happened to a complaint, with the state
              before and after each action (SRS Steps 59, FR lxiv). There is no API to edit or delete it.
ComplaintNote internal notes and customer-visible updates (reviewer comments, agent updates,
              customer replies).
"""

from django.conf import settings
from django.db import models

from complaints.models import Complaint


class AuditLog(models.Model):
    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        PROCESSED = "processed", "GenAI analysis + validation"
        STATUS_CHANGED = "status_changed", "Status changed"
        ASSIGNED = "assigned", "Assigned / reassigned"
        APPROVED = "approved", "Recommendation approved"
        REJECTED = "rejected", "Recommendation rejected"
        MODIFIED = "modified", "Recommendation modified"
        RECLASSIFIED = "reclassified", "Reclassified"
        ESCALATED = "escalated", "Escalated"
        REGENERATED = "regenerated", "Response regenerated"
        COMMENTED = "commented", "Comment added"
        RESPONSE_SENT = "response_sent", "Response sent to customer"
        FOLLOW_UP_DONE = "follow_up_done", "Follow-up completed"
        CUSTOMER_REPLY = "customer_reply", "Customer replied"
        REOPENED = "reopened", "Reopened"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="audit_log")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)  # null = system
    action = models.CharField(max_length=30, choices=Action.choices)
    before = models.JSONField(default=dict, blank=True)  # only the fields that changed
    after = models.JSONField(default=dict, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.complaint.complaint_id} {self.action} by {self.actor or 'system'}"


class ComplaintNote(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    text = models.TextField()
    customer_visible = models.BooleanField(default=False)  # False = internal staff note
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.complaint.complaint_id}: {self.text[:40]}"
