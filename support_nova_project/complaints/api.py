"""
Complaint intake API.

Customers submit complaints and see only their own (/complaints/my...).
Staff see everything, can submit on a customer's behalf, and get the internal analysis.
"""

from datetime import date

from django.conf import settings
from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, UploadedFile
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from catalog.models import Product
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
    OrderIn,
    OrderOut,
    OrderStatusIn,
    ShopCatalogOut,
    SimilarComplaintOut,
    SubmitOut,
)
from workflow.emails import acknowledge, notify_order
from workflow.services import auto_process

from . import ordering
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
    acknowledge(complaint)
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
    open_only: bool = False,
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
    if open_only:
        qs = qs.filter(status__in=Complaint.OPEN_STATUSES)
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


def _own_or_visible(request, complaint_id):
    """The complaint's customer, or staff allowed to see it (404 otherwise, so nothing is revealed)."""
    complaint = get_object_or_404(Complaint, complaint_id=complaint_id.upper())
    is_owner = complaint.customer_id == request.auth.id
    if not is_owner and not visible_complaints(request.auth).filter(pk=complaint.pk).exists():
        raise HttpError(404, "Not Found")
    return complaint


@router.post("/{complaint_id}/attachments", response={201: AttachmentOut, 400: ErrorOut, 409: ErrorOut})
def upload_attachment(request, complaint_id: str, file: File[UploadedFile]):
    complaint = _own_or_visible(request, complaint_id)
    try:
        return 201, add_attachment(complaint, file.name, file.read())
    except ComplaintValidationError as e:
        raise HttpError(e.status_code, str(e))


@router.get("/{complaint_id}/attachments/{int:attachment_id}", response={200: None, 404: ErrorOut})
def download_attachment(request, complaint_id: str, attachment_id: int):
    """The file itself, for the customer who sent it and the staff handling the complaint."""
    complaint = _own_or_visible(request, complaint_id)
    attachment = get_object_or_404(complaint.attachments, pk=attachment_id)
    return FileResponse(attachment.file.open("rb"), content_type=attachment.content_type,
                        filename=attachment.original_filename)


# ---------------- orders (simulated) ----------------


def _orders():
    return Order.objects.select_related("customer", "product")


@orders_router.get("/my", response=list[OrderOut])
def my_orders(request):
    return _orders().filter(customer=request.auth)


@orders_router.get("/catalog", response=ShopCatalogOut)
def shop_catalog(request):
    """What a customer can order, and what delivery costs. Prices are decided here, never by the browser."""
    products = Product.objects.filter(is_active=True).order_by("kind", "name")
    return {"products": products, "express_fee": float(ordering.express_fee()), "max_quantity": settings.ORDER_MAX_QUANTITY,
            "standard_days": settings.STANDARD_DELIVERY_DAYS, "express_days": settings.EXPRESS_DELIVERY_DAYS}


def _customer_only(request):
    if request.auth.role != User.Role.CUSTOMER:
        raise HttpError(403, "Only customers can place orders.")


def _ordering(action, *args):
    try:
        return action(*args)
    except ordering.OrderError as e:
        raise HttpError(e.status, str(e))


@orders_router.post("", response={201: OrderOut, 400: ErrorOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut, 429: ErrorOut})
def place_order(request, data: OrderIn):
    """A customer places an order. No payment is taken: payment is arranged on delivery."""
    _customer_only(request)
    order = _ordering(ordering.place_order, request.auth, data.product, data.quantity, data.express, data.delivery_address)
    when = f"expected by {order.estimated_delivery_date:%d %b %Y}" if order.estimated_delivery_date else "active now"
    notify_order(order, f"Thanks for your order {order.order_ref}: {order.quantity} x {order.product.name}, total {order.amount + order.shipping_fee:.2f}. It is {when}.",
                 "Payment is arranged on delivery." if order.product.kind == Product.Kind.DEVICE else "")
    return 201, _orders().get(pk=order.pk)


@orders_router.post("/{order_ref}/cancel", response={200: OrderOut, 404: ErrorOut, 409: ErrorOut})
def cancel_order(request, order_ref: str):
    """A customer cancels their own order until it is dispatched."""
    order = get_object_or_404(_orders(), order_ref=order_ref.upper(), customer=request.auth)
    _ordering(ordering.cancel_order, order)
    notify_order(order, f"Your order {order.order_ref} was cancelled. Because it had not been dispatched, it is refunded in full.")
    return order


@orders_router.patch("/{order_ref}/status", response={200: OrderOut, 404: ErrorOut, 409: ErrorOut})
def advance_order(request, order_ref: str, data: OrderStatusIn):
    """Managers and administrators mark an order shipped, then delivered."""
    require_role(request, User.Role.MANAGER, User.Role.ADMIN)
    order = get_object_or_404(_orders(), order_ref=order_ref.upper())
    _ordering(ordering.advance_order, order, data.status)
    if data.status == Order.Status.SHIPPED:
        notify_order(order, f"Your order {order.order_ref} is on its way. Expected by {order.estimated_delivery_date:%d %b %Y}.")
    return order


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
