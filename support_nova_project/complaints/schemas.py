from datetime import date, datetime

from ninja import Schema
from pydantic import Field

from .models import Complaint

# ---------- input ----------


class ComplaintIn(Schema):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    product: str | None = Field(None, description="Product code or name, e.g. 'PLUG' or 'Smart Plug'")
    order_ref: str | None = Field(None, description="e.g. ORD-10042")
    channel: Complaint.Channel = Complaint.Channel.WEB
    preferred_contact: Complaint.ContactChannel = Complaint.ContactChannel.EMAIL
    previous_complaint_ref: str | None = Field(None, description="e.g. CMP-00012")
    requested_resolution: str = Field("", max_length=500)
    supporting_information: str = Field("", max_length=2000)
    customer_username: str | None = Field(None, description="Staff only: submit on behalf of this customer")


# ---------- output ----------


class AttachmentOut(Schema):
    id: int
    original_filename: str
    content_type: str
    file_size: int
    uploaded_at: datetime


class SubmitOut(Schema):
    complaint_id: str
    status: str
    match_type: str
    related_complaint: str | None = None  # complaint_id of the linked earlier complaint
    warnings: list[str]


RESOLUTION_STATUS = {
    "new": "Received", "analyzed": "Received", "assigned": "Being handled", "in_progress": "Being handled",
    "awaiting_customer": "Waiting for your reply", "escalated": "Being handled by a specialist team",
    "resolved": "Resolved", "closed": "Closed", "reopened": "Reopened",
}


class MessageOut(Schema):
    """One message in the customer-facing conversation (replies sent, customer replies, visible notes)."""

    sender: str  # "customer" | "lumora"
    name: str  # e.g. "You", "Sara from Logistics & Delivery", "Lumora team"
    text: str
    at: datetime


def _sender_name(note, complaint):
    if note.author_id == complaint.customer_id:
        return "customer", "You"
    author = note.author
    if author is None or not author.first_name:
        return "lumora", "Lumora team"
    # Staff without a team (reviewers, managers) still say where they are from.
    team = author.department.name if author.department_id else "Lumora Support"
    return "lumora", f"{author.first_name} from {team}"


class ComplaintCustomerOut(Schema):
    """What customers see about their own complaints (SRS Step 61) - no internal analysis."""

    complaint_id: str
    title: str
    description: str
    status: str
    resolution_status: str
    department: str | None = Field(None, alias="department.name")
    latest_update: dict | None
    messages: list[MessageOut]  # oldest first; the original complaint is `description`
    product: str | None = Field(None, alias="product.name")
    order_ref: str | None = Field(None, alias="order.order_ref")
    channel: str
    preferred_contact: str
    requested_resolution: str
    attachments: list[AttachmentOut]
    created_at: datetime
    updated_at: datetime
    reply_expected_by: datetime | None  # our next promise: the first reply, then the resolution
    last_message_from: str | None  # "customer" | "lumora" | None: who wrote last in the conversation
    safety_concern: bool  # classified as a safety problem: the customer sees "stay safe" advice straight away

    @staticmethod
    def resolve_safety_concern(obj):
        return bool(obj.category_id and obj.category.code == "SAFETY")

    @staticmethod
    def resolve_resolution_status(obj):
        return RESOLUTION_STATUS.get(obj.status, obj.status)

    @staticmethod
    def resolve_reply_expected_by(obj):
        if obj.status not in Complaint.OPEN_STATUSES or obj.status == Complaint.Status.AWAITING_CUSTOMER:
            return None  # finished, or we are waiting for the customer
        return obj.sla_response_due if obj.first_response_at is None else obj.sla_resolution_due

    @staticmethod
    def resolve_last_message_from(obj):
        note = obj.notes.filter(customer_visible=True).order_by("-created_at", "-id").first()
        return (_sender_name(note, obj)[0]) if note else None

    @staticmethod
    def resolve_latest_update(obj):
        note = obj.notes.filter(customer_visible=True).order_by("-created_at").first()
        if note:
            return {"text": note.text, "at": note.created_at}
        return {"text": f"Status: {RESOLUTION_STATUS.get(obj.status, obj.status)}", "at": obj.updated_at}

    @staticmethod
    def resolve_messages(obj):
        notes = obj.notes.filter(customer_visible=True).select_related("author__department").order_by("created_at")
        messages = []
        for note in notes:
            sender, name = _sender_name(note, obj)
            messages.append({"sender": sender, "name": name, "text": note.text, "at": note.created_at})
        return messages


class ComplaintListOut(Schema):
    complaint_id: str
    title: str
    status: str
    customer: str = Field(alias="customer.username")
    customer_name: str = Field(alias="customer.display_name")
    customer_type: str
    product: str | None = Field(None, alias="product.name")
    order_ref: str | None = Field(None, alias="order.order_ref")
    channel: str
    category: str | None = Field(None, alias="category.code")
    department: str | None = Field(None, alias="department.code")
    assigned_to: str | None = Field(None, alias="assigned_to.username")
    assigned_to_name: str | None = Field(None, alias="assigned_to.display_name")
    priority: str
    sentiment: str
    escalation_level: str
    verification_status: str
    review_status: str
    match_type: str
    has_security_flags: bool
    created_at: datetime

    @staticmethod
    def resolve_has_security_flags(obj):
        return bool(obj.security_flags)


class ComplaintStaffOut(ComplaintCustomerOut):
    """Full detail for staff, including pre-processing results."""

    customer: str = Field(alias="customer.username")
    customer_name: str  # full name for people to read, the username if no name was given
    submitted_by: str | None = Field(None, alias="submitted_by.username")
    customer_type: str
    previous_complaint: str | None = Field(None, alias="previous_complaint.complaint_id")
    supporting_information: str
    extracted_metadata: dict
    security_flags: list[dict]
    intake_warnings: list[str]
    match_type: str
    related_complaint: str | None = Field(None, alias="related_complaint.complaint_id")
    similarity: float | None
    previous_related_count: int
    facts: dict
    category: str | None = Field(None, alias="category.code")
    subcategory: str | None = Field(None, alias="subcategory.code")
    department_code: str | None = Field(None, alias="department.code")
    supporting_departments: list[str]
    assigned_to: str | None = Field(None, alias="assigned_to.username")
    assigned_to_name: str | None = Field(None, alias="assigned_to.display_name")
    priority: str
    urgency: str
    sentiment: str
    escalation_level: str
    verification_status: str
    verification_score: int | None
    review_status: str
    resolution: dict
    response_text: str
    response_sent_at: datetime | None
    sla_response_due: datetime | None
    sla_resolution_due: datetime | None
    follow_up_due: datetime | None

    emotions: list[str] = []  # tone indicators from the latest analysis (Step 18) - context, never priority

    @staticmethod
    def resolve_customer_name(obj):
        return obj.customer.display_name

    @staticmethod
    def resolve_emotions(obj):
        analysis = obj.genai_analyses.exclude(output={}).filter(output__isnull=False).order_by("-created_at").first()
        if analysis is None:
            return []
        return analysis.output.get("emotions") or []


class SimilarComplaintOut(Schema):
    complaint_id: str
    title: str
    customer: str
    status: str
    similarity: float
    same_customer: bool


class OrderOut(Schema):
    order_ref: str
    customer: str = Field(alias="customer.username")
    product: str = Field(alias="product.name")
    quantity: int
    amount: float
    express: bool
    status: str
    order_date: date
    estimated_delivery_date: date | None
    delivery_date: date | None


class DuplicateErrorOut(Schema):
    detail: str
    existing_complaint: str | None = None
