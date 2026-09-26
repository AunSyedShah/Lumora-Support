"""
Knowledge base: approved company documents and their traceable chunks (SRS Steps 4-7, 25).

Version rules for documents sharing the same doc_id:
  ACTIVE      the one version used for complaint resolution
  PREVIOUS    the version that was active just before the current one
  SUPERSEDED  anything older than PREVIOUS
  DRAFT       uploaded but not approved yet; never used for resolutions
"""

from datetime import date

from django.conf import settings
from django.db import models


class DocumentType(models.TextChoices):
    POLICY = "policy", "Policy"
    COMPLIANCE = "compliance", "Compliance Guideline"
    SLA = "sla", "Service Level Agreement"
    ROUTING = "routing", "Department Routing Rules"
    SOP = "sop", "Standard Operating Procedure"
    TEMPLATE = "template", "Response Template"
    FAQ = "faq", "FAQ"
    OTHER = "other", "Other"


# Policy-precedence rule (SRS 1.8.10): when two documents contradict each other,
# the lower number wins. Same type -> the newer effective date wins.
PRECEDENCE = {
    DocumentType.POLICY: 1,
    DocumentType.COMPLIANCE: 1,
    DocumentType.SLA: 2,
    DocumentType.ROUTING: 2,
    DocumentType.SOP: 3,
    DocumentType.TEMPLATE: 4,
    DocumentType.FAQ: 5,
    DocumentType.OTHER: 6,
}


class DocumentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PREVIOUS = "previous", "Previous"
    SUPERSEDED = "superseded", "Superseded"
    DRAFT = "draft", "Draft"


class PolicyDocument(models.Model):
    doc_id = models.CharField(max_length=50)  # e.g. "REF-POL", shared by all versions
    title = models.CharField(max_length=200)
    doc_type = models.CharField(max_length=20, choices=DocumentType.choices)
    category = models.ForeignKey(
        "catalog.Category", on_delete=models.SET_NULL, null=True, blank=True, related_name="documents"
    )
    version = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, default=DocumentStatus.DRAFT)
    effective_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)

    file = models.FileField(upload_to="kb/%Y/%m/")
    original_filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    file_hash = models.CharField(max_length=64, unique=True)  # sha256, catches duplicate uploads
    page_count = models.PositiveIntegerField(null=True, blank=True)

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["doc_id", "-effective_date"]
        constraints = [
            models.UniqueConstraint(fields=["doc_id", "version"], name="unique_doc_version"),
        ]

    def __str__(self):
        return f"{self.doc_id} v{self.version} ({self.status})"

    @property
    def precedence(self):
        return PRECEDENCE.get(self.doc_type, 99)

    @property
    def is_usable(self):
        """Only an active, currently-effective, non-expired document may ground a resolution."""
        today = date.today()
        return (
            self.status == DocumentStatus.ACTIVE
            and self.effective_date <= today
            and (self.expiry_date is None or self.expiry_date >= today)
        )


class PolicyChunk(models.Model):
    document = models.ForeignKey(PolicyDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_id = models.CharField(max_length=100, unique=True)  # e.g. "REF-POL-v2.0-004"
    order = models.PositiveIntegerField()
    section = models.CharField(max_length=20, blank=True)  # e.g. "5.2"
    heading = models.CharField(max_length=255, blank=True)
    page = models.PositiveIntegerField(null=True, blank=True)  # PDFs only
    text = models.TextField()
    embedding = models.BinaryField(null=True)  # heading + text, for FAISS semantic search

    class Meta:
        ordering = ["document", "order"]

    def __str__(self):
        return f"{self.chunk_id} {self.section} {self.heading}".strip()
