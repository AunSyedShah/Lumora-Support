"""
Customer complaints and the (simulated) orders they refer to.

Orders exist so that complaint references can be validated (SRS Step 10) and so the rule
facts - days since delivery, business days late, amount - are CALCULATED from data instead
of being guessed from the complaint text.
"""

from django.conf import settings
from django.db import models

from catalog.models import Category, Department, Priority, Product, Subcategory, Urgency


class Order(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    order_ref = models.CharField(max_length=20, unique=True)  # e.g. "ORD-10042"
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="orders")
    quantity = models.PositiveSmallIntegerField(default=1)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    express = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices)
    order_date = models.DateField()
    estimated_delivery_date = models.DateField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-order_date"]

    def __str__(self):
        return self.order_ref


class Complaint(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "New"
        ANALYZED = "analyzed", "Analyzed"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        AWAITING_CUSTOMER = "awaiting_customer", "Awaiting Customer"
        ESCALATED = "escalated", "Escalated"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        REOPENED = "reopened", "Reopened"

    OPEN_STATUSES = [
        Status.NEW, Status.ANALYZED, Status.ASSIGNED, Status.IN_PROGRESS,
        Status.AWAITING_CUSTOMER, Status.ESCALATED, Status.REOPENED,
    ]

    class Channel(models.TextChoices):
        WEB = "web", "Web form"
        EMAIL = "email", "E-mail"
        CHAT = "chat", "Chat"
        UPLOAD = "upload", "Uploaded complaint"

    class ContactChannel(models.TextChoices):
        EMAIL = "email", "E-mail"
        PHONE = "phone", "Phone"
        CHAT = "chat", "Chat"

    class MatchType(models.TextChoices):
        NONE = "", "None"
        NEAR_DUPLICATE = "near_duplicate", "Near-duplicate"
        REPEAT = "repeat", "Repeat of an earlier complaint"

    complaint_id = models.CharField(max_length=20, unique=True, blank=True)  # "CMP-00001"
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="complaints_submitted"
    )

    # --- what the customer entered (after sanitisation) ---
    title = models.CharField(max_length=200)
    description = models.TextField()
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    customer_type = models.CharField(max_length=20)  # snapshot at submission time
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.WEB)
    preferred_contact = models.CharField(max_length=10, choices=ContactChannel.choices, default=ContactChannel.EMAIL)
    previous_complaint = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="follow_up_complaints"
    )
    requested_resolution = models.CharField(max_length=500, blank=True)
    supporting_information = models.TextField(blank=True)

    # --- pre-processing results (SRS Step 11) ---
    normalized_text = models.TextField()  # lower-case, cleaned title + description
    text_hash = models.CharField(max_length=64, db_index=True)  # sha256 of normalized_text
    extracted_metadata = models.JSONField(default=dict)  # order refs, amounts, dates found in the text
    security_flags = models.JSONField(default=list)  # e.g. suspected prompt-injection phrases
    intake_warnings = models.JSONField(default=list)  # e.g. "no order reference provided"
    embedding = models.BinaryField(null=True)  # 384 float32 values, used by the FAISS index

    # --- duplicate / repeat detection (SRS Steps 52-54) ---
    match_type = models.CharField(max_length=20, choices=MatchType.choices, blank=True, default="")
    related_complaint = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="later_related_complaints"
    )
    similarity = models.FloatField(null=True, blank=True)
    previous_related_count = models.PositiveSmallIntegerField(default=0)

    # --- facts for the rule engine, calculated at submission time ---
    facts = models.JSONField(default=dict)

    # --- working state (set by processing, changed by reviewers / agents; history in the audit log) ---
    class Verification(models.TextChoices):
        PENDING = "pending", "Not processed yet"
        VERIFIED = "verified", "Verified"
        MANUAL_REVIEW = "manual_review", "Manual Review"

    class Review(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Recommendation rejected"

    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    subcategory = models.ForeignKey(Subcategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="complaints")
    supporting_departments = models.JSONField(default=list, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_complaints"
    )
    priority = models.CharField(max_length=2, choices=Priority.choices, blank=True)
    urgency = models.CharField(max_length=10, choices=Urgency.choices, blank=True)
    sentiment = models.CharField(max_length=20, blank=True)
    escalation_level = models.CharField(max_length=30, blank=True, default="none")
    verification_status = models.CharField(max_length=20, choices=Verification.choices, default=Verification.PENDING)
    verification_score = models.PositiveSmallIntegerField(null=True, blank=True)
    review_status = models.CharField(max_length=20, choices=Review.choices, default=Review.NOT_REQUIRED)
    resolution = models.JSONField(default=dict, blank=True)  # working copy of the final resolution
    response_text = models.TextField(blank=True)  # the reply that will be / was sent to the customer
    response_sent_at = models.DateTimeField(null=True, blank=True)

    # --- SLA and follow-up (SRS Steps 41, 55-56) ---
    sla_response_due = models.DateTimeField(null=True, blank=True)
    sla_resolution_due = models.DateTimeField(null=True, blank=True)
    sla_clock_start = models.DateTimeField(null=True, blank=True)  # submission time, or when it was reopened
    sla_paused_seconds = models.PositiveIntegerField(default=0)  # time spent waiting for the customer
    awaiting_since = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    follow_up_due = models.DateTimeField(null=True, blank=True)
    follow_up_done_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.complaint_id}: {self.title}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.complaint_id:  # needs the primary key, so set after the first save
            self.complaint_id = f"CMP-{self.pk:05d}"
            super().save(update_fields=["complaint_id"])

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="complaints/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    file_size = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename
