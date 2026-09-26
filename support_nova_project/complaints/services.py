"""
Complaint submission pipeline (SRS Steps 9-11, 52-54):

  sanitise -> validate fields & references -> exact-duplicate check -> embed -> repeat detection
  -> security flags -> calculate facts -> save
"""

from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q

from catalog.models import Product
from vector_search.embeddings import embed_text, to_bytes
from workflow.audit import log_event

from .duplicates import find_exact_duplicate, find_related
from .facts import compute_facts
from .models import Complaint, ComplaintAttachment, Order
from .preprocessing import (
    extract_metadata,
    mask_card_numbers,
    normalized_for_matching,
    sanitize,
    text_fingerprint,
)
from .security import detect_injection

MIN_TITLE_CHARS = 5
MIN_DESCRIPTION_CHARS = 20
MIN_DESCRIPTION_WORDS = 4


class ComplaintValidationError(Exception):
    def __init__(self, message, status_code=400, existing_complaint=None):
        super().__init__(message)
        self.status_code = status_code
        self.existing_complaint = existing_complaint


def _find_product(value):
    if not value:
        return None
    product = Product.objects.filter(Q(code__iexact=value) | Q(name__iexact=value), is_active=True).first()
    if product is None:
        raise ComplaintValidationError(f"Unknown product '{value}'.")
    return product


def _find_order(customer, order_ref):
    order = Order.objects.select_related("product").filter(order_ref=order_ref.upper(), customer=customer).first()
    if order is None:
        # Same message whether the order doesn't exist or belongs to someone else (no data leak).
        raise ComplaintValidationError(f"Order reference {order_ref.upper()} was not found on this account.")
    return order


def submit_complaint(data: dict, customer, submitted_by):
    """Validate, pre-process and store a complaint. Returns (complaint, warnings)."""
    warnings = []

    # 1. Sanitise + mask card numbers
    title = sanitize(data["title"])
    description, masked = mask_card_numbers(sanitize(data["description"]))
    supporting, masked_extra = mask_card_numbers(sanitize(data.get("supporting_information", "")))
    if masked or masked_extra:
        warnings.append("A card number was removed from your complaint for your security. Never send full card numbers.")

    # 2. Field validation
    if len(title) < MIN_TITLE_CHARS:
        raise ComplaintValidationError(f"Title must be at least {MIN_TITLE_CHARS} characters.")
    if not description:
        raise ComplaintValidationError("Complaint description is empty.")
    if len(description) < MIN_DESCRIPTION_CHARS or len(description.split()) < MIN_DESCRIPTION_WORDS:
        raise ComplaintValidationError(
            "Complaint description is too short. Please describe what happened in a few sentences."
        )

    # 3. References
    metadata = extract_metadata(f"{title}\n{description}\n{supporting}")
    order = _find_order(customer, data["order_ref"]) if data.get("order_ref") else None
    if order is None and metadata["order_refs"]:
        candidate = Order.objects.filter(order_ref__in=metadata["order_refs"], customer=customer).first()
        if candidate:
            order = candidate
            warnings.append(f"Order {order.order_ref} was linked from the complaint text.")

    product = _find_product(data.get("product"))
    if product is None and order:
        product = order.product
    elif product and order and order.product_id != product.id:
        warnings.append(f"The product you selected is different from the product on order {order.order_ref}.")

    previous = None
    if data.get("previous_complaint_ref"):
        previous = Complaint.objects.filter(
            complaint_id=data["previous_complaint_ref"].upper(), customer=customer
        ).first()
        if previous is None:
            raise ComplaintValidationError(
                f"Previous complaint {data['previous_complaint_ref'].upper()} was not found on this account."
            )

    if order is None:
        warnings.append("No order reference was provided; some checks (e.g. return windows) need one.")
    if product is None:
        warnings.append("No product was specified.")

    # 4. Exact duplicate of a complaint that is still open?
    normalized = normalized_for_matching(title, description)
    fingerprint = text_fingerprint(normalized)
    existing = find_exact_duplicate(customer, fingerprint)
    if existing:
        raise ComplaintValidationError(
            f"This complaint was already submitted as {existing.complaint_id} and is still being handled.",
            409,
            existing_complaint=existing,
        )

    # 5. Near-duplicate / repeat detection with embeddings + FAISS
    embedding = embed_text(f"{title}. {description}")
    related = find_related(customer, embedding, normalized, previous_complaint=previous)
    if related.match_type == Complaint.MatchType.NEAR_DUPLICATE:
        warnings.append(f"This looks very similar to your open complaint {related.related.complaint_id}.")
    elif related.match_type == Complaint.MatchType.REPEAT:
        warnings.append(f"Linked to your earlier complaint {related.related.complaint_id}.")

    # 6. Security flags + facts
    security_flags = detect_injection(f"{title}\n{description}\n{supporting}")
    facts = compute_facts(customer, order, product, metadata, len(related.related_ids))

    complaint = Complaint.objects.create(
        customer=customer,
        submitted_by=submitted_by,
        title=title,
        description=description,
        product=product,
        order=order,
        customer_type=customer.customer_type,
        channel=data.get("channel") or Complaint.Channel.WEB,
        preferred_contact=data.get("preferred_contact") or Complaint.ContactChannel.EMAIL,
        previous_complaint=previous,
        requested_resolution=sanitize(data.get("requested_resolution", "")),
        supporting_information=supporting,
        normalized_text=normalized,
        text_hash=fingerprint,
        extracted_metadata=metadata,
        security_flags=security_flags,
        intake_warnings=warnings,
        embedding=to_bytes(embedding),
        match_type=related.match_type,
        related_complaint=related.related,
        similarity=related.similarity,
        previous_related_count=len(related.related_ids),
        facts=facts,
    )
    log_event(complaint, submitted_by, "submitted", comment="; ".join(warnings))
    return complaint, warnings


# ---------------- attachments ----------------

ALLOWED_ATTACHMENTS = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".png": ("image/png", b"\x89PNG"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".txt": ("text/plain", None),
}
MAX_ATTACHMENTS = 5


def add_attachment(complaint, filename, data):
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_ATTACHMENTS:
        raise ComplaintValidationError(
            f"Unsupported attachment type '{extension}'. Allowed: {', '.join(ALLOWED_ATTACHMENTS)}."
        )
    content_type, magic = ALLOWED_ATTACHMENTS[extension]
    if not data:
        raise ComplaintValidationError("The attachment is empty.")
    if len(data) > settings.COMPLAINT_MAX_ATTACHMENT_MB * 1024 * 1024:
        raise ComplaintValidationError(f"Attachments must be smaller than {settings.COMPLAINT_MAX_ATTACHMENT_MB} MB.")
    if magic and not data.startswith(magic):
        raise ComplaintValidationError(f"File content does not match the '{extension}' extension.")
    if complaint.attachments.count() >= MAX_ATTACHMENTS:
        raise ComplaintValidationError(f"A complaint can have at most {MAX_ATTACHMENTS} attachments.", 409)

    with transaction.atomic():
        attachment = ComplaintAttachment(
            complaint=complaint, original_filename=filename, content_type=content_type, file_size=len(data)
        )
        attachment.file.save(filename, ContentFile(data), save=False)
        attachment.save()
    return attachment
