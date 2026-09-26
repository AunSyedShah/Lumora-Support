"""
Complaint intake API.

Customers submit complaints and see only their own (/complaints/my...).
Staff see everything, can submit on a customer's behalf, and get the internal analysis.
"""

from datetime import date

from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import File, Router, UploadedFile
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from rules.engine import evaluate
from rules.schemas import EvaluationOut

from .duplicates import similar_complaints
from .facts import rule_facts
from .models import Complaint, Order
from .permissions import get_visible_complaint, has_full_access, visible_complaints
from .schemas import (
    AttachmentOut,
    ComplaintCustomerOut,
    ComplaintIn,
    ComplaintListOut,
    ComplaintStaffOut,
    DuplicateErrorOut,
    OrderOut,
    SimilarComplaintOut,
    SubmitOut,
)
from workflow.services import auto_process

from .services import ComplaintValidationError, add_attachment, submit_complaint

router = Router(tags=["Complaints"])
orders_router = Router(tags=["Orders"])


def _complaints():
    return Complaint.objects.select_related(
        "customer", "submitted_by", "product", "order", "previous_complaint", "related_complaint",
        "category", "subcategory", "department", "assigned_to",
    ).prefetch_related("attachments")


# ---------------- submit ----------------


@router.post("", response={201: SubmitOut, 400: ErrorOut, 404: ErrorOut, 409: DuplicateErrorOut})
def submit(request, data: ComplaintIn):
    user = request.auth
    if data.customer_username:
        require_role(request, *STAFF_ROLES)
        customer = get_object_or_404(User, username=data.customer_username, role=User.Role.CUSTOMER)
    elif user.role == User.Role.CUSTOMER:
        customer = user
    else:
        raise HttpError(400, "Staff must give customer_username when submitting a complaint.")

    try:
        complaint, warnings = submit_complaint(data.model_dump(), customer=customer, submitted_by=user)
    except ComplaintValidationError as e:
        if e.status_code == 409:
            return 409, {"detail": str(e), "existing_complaint": e.existing_complaint.complaint_id}
        raise HttpError(e.status_code, str(e))

    # Analyse, validate and route straight away (a failure here never undoes the submission).
    auto_process(complaint)
    complaint.refresh_from_db()
    return 201, {
        "complaint_id": complaint.complaint_id,
        "status": complaint.status,
        "match_type": complaint.match_type,
        "related_complaint": complaint.related_complaint.complaint_id if complaint.related_complaint else None,
        "warnings": warnings,
    }


# ---------------- customer views ----------------


@router.get("/my", response=list[ComplaintCustomerOut])
def my_complaints(request, status: Complaint.Status | None = None):
    qs = _complaints().filter(customer=request.auth)
    return qs.filter(status=status) if status else qs


@router.get("/my/{complaint_id}", response=ComplaintCustomerOut)
def my_complaint(request, complaint_id: str):
    return get_object_or_404(_complaints(), complaint_id=complaint_id.upper(), customer=request.auth)


# ---------------- staff views ----------------


@router.get("", response=list[ComplaintListOut])
@paginate(PageNumberPagination, page_size=25)
def list_complaints(
    request,
    status: Complaint.Status | None = None,
    customer: str | None = None,
    channel: Complaint.Channel | None = None,
    match_type: str | None = None,
    category: str | None = None,
    department: str | None = None,
    priority: str | None = None,
    sentiment: str | None = None,
    escalated: bool | None = None,
    verification: str | None = None,
    assigned_to: str | None = None,
    flagged_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
):
    require_role(request, *STAFF_ROLES)
    qs = visible_complaints(request.auth, _complaints())
    if status:
        qs = qs.filter(status=status)
    if customer:
        qs = qs.filter(customer__username=customer)
    if channel:
        qs = qs.filter(channel=channel)
    if match_type:
        qs = qs.filter(match_type=match_type)
    if category:
        qs = qs.filter(category__code=category.upper())
    if department:
        qs = qs.filter(department__code=department.upper())
    if priority:
        qs = qs.filter(priority=priority.upper())
    if sentiment:
        qs = qs.filter(sentiment__iexact=sentiment)
    if escalated is not None:
        no_escalation = ["", "none"]
        qs = qs.exclude(escalation_level__in=no_escalation) if escalated else qs.filter(escalation_level__in=no_escalation)
    if verification:
        qs = qs.filter(verification_status=verification)
    if assigned_to:
        qs = qs.filter(assigned_to__username=assigned_to)
    if flagged_only:
        qs = qs.exclude(security_flags=[])
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if q:
        qs = qs.filter(
            Q(complaint_id__iexact=q) | Q(customer__username__iexact=q) | Q(order__order_ref__iexact=q)
            | Q(title__icontains=q) | Q(description__icontains=q)
        )
    return qs


@router.get("/{complaint_id}", response=ComplaintStaffOut)
def get_complaint(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    return get_visible_complaint(request.auth, complaint_id, _complaints())


@router.get("/{complaint_id}/history", response=list[ComplaintListOut])
def customer_history(request, complaint_id: str):
    """All other complaints from the same customer (SRS Step 53) that this user may see."""
    require_role(request, *STAFF_ROLES)
    complaint = get_visible_complaint(request.auth, complaint_id)
    return visible_complaints(request.auth, _complaints()).filter(customer=complaint.customer).exclude(pk=complaint.pk)


@router.get("/{complaint_id}/similar", response=list[SimilarComplaintOut])
def similar(request, complaint_id: str, k: int = 5):
    """Semantically similar complaints (FAISS search), limited to complaints this user may see."""
    require_role(request, *STAFF_ROLES)
    complaint = get_visible_complaint(request.auth, complaint_id)
    allowed = None if has_full_access(request.auth) else set(visible_complaints(request.auth).values_list("pk", flat=True))
    return [
        {
            "complaint_id": other.complaint_id,
            "title": other.title,
            "customer": other.customer.username,
            "status": other.status,
            "similarity": round(score, 3),
            "same_customer": other.customer_id == complaint.customer_id,
        }
        for other, score in similar_complaints(complaint, k=min(k, 20))
        if allowed is None or other.pk in allowed
    ]


@router.get("/{complaint_id}/rule-preview", response=EvaluationOut)
def rule_preview(request, complaint_id: str):
    """What the Python rule matrix expects for this complaint (preview of Pipeline 2)."""
    require_role(request, *STAFF_ROLES)
    complaint = get_visible_complaint(request.auth, complaint_id)
    return evaluate(rule_facts(complaint))


# ---------------- attachments ----------------


@router.post("/{complaint_id}/attachments", response={201: AttachmentOut, 400: ErrorOut, 409: ErrorOut})
def upload_attachment(request, complaint_id: str, file: File[UploadedFile]):
    complaint = get_object_or_404(Complaint, complaint_id=complaint_id.upper())
    is_owner = complaint.customer_id == request.auth.id
    if not is_owner and not visible_complaints(request.auth).filter(pk=complaint.pk).exists():
        raise HttpError(404, "Not Found")  # don't reveal complaints outside the user's scope
    try:
        return 201, add_attachment(complaint, file.name, file.read())
    except ComplaintValidationError as e:
        raise HttpError(e.status_code, str(e))


# ---------------- orders (simulated) ----------------


def _orders():
    return Order.objects.select_related("customer", "product")


@orders_router.get("/my", response=list[OrderOut])
def my_orders(request):
    return _orders().filter(customer=request.auth)


@orders_router.get("", response=list[OrderOut])
@paginate(PageNumberPagination, page_size=50)
def list_orders(request, customer: str | None = None, status: Order.Status | None = None):
    require_role(request, *STAFF_ROLES)
    qs = _orders()
    if not has_full_access(request.auth):  # agents: only customers whose complaints they handle
        qs = qs.filter(customer__complaints__in=visible_complaints(request.auth)).distinct()
    if customer:
        qs = qs.filter(customer__username=customer)
    if status:
        qs = qs.filter(status=status)
    return qs


@orders_router.get("/{order_ref}", response=OrderOut)
def get_order(request, order_ref: str):
    order = get_object_or_404(_orders(), order_ref=order_ref.upper())
    handles_customer = visible_complaints(request.auth).filter(customer_id=order.customer_id).exists()
    if order.customer_id != request.auth.id and not has_full_access(request.auth) and not handles_customer:
        raise HttpError(404, "Not Found")
    return order
