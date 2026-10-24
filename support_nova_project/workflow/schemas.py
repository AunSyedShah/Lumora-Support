from datetime import datetime

from ninja import Schema
from pydantic import Field

from catalog.models import Priority, Urgency
from complaints.models import Complaint
from genai_pipeline.output_schema import Tone
from rules.models import EscalationLevel

from .lifecycle import sla_status

# ---------- input ----------


class CommentIn(Schema):
    comment: str = ""


class RejectIn(Schema):
    comment: str = Field(min_length=5, description="Why the recommendation is rejected")


class ModifyIn(Schema):
    priority: Priority | None = None
    urgency: Urgency | None = None
    escalation_level: EscalationLevel | None = None
    response_text: str | None = Field(None, min_length=20)
    resolution_steps: list[str] | None = None
    follow_up_days: int | None = Field(None, ge=0, le=90)
    comment: str = ""


class ReclassifyIn(Schema):
    subcategory: str
    department: str | None = Field(None, description="Override the rule-based department")
    comment: str = ""


class AssignIn(Schema):
    department: str | None = None
    assignee: str | None = Field(None, description="Username of the staff member")
    comment: str = ""


class EscalateIn(Schema):
    level: EscalationLevel
    comment: str = Field(min_length=5)


class RegenerateIn(Schema):
    tone: Tone | None = None


class NoteIn(Schema):
    text: str = Field(min_length=2, max_length=4000)
    customer_visible: bool = False


class StatusIn(Schema):
    status: Complaint.Status
    comment: str = ""


class SendResponseIn(Schema):
    text: str | None = Field(None, description="Leave empty to send the current response text")
    override_reason: str | None = Field(
        None, min_length=5, description="Reviewers only: send despite validation findings (audited)"
    )


class CustomerTextIn(Schema):
    text: str = Field(min_length=5, max_length=4000)


# ---------- output ----------


class AuditOut(Schema):
    id: int
    action: str
    actor: str | None = Field(None, alias="actor.username")
    actor_name: str | None = Field(None, alias="actor.display_name")
    before: dict
    after: dict
    comment: str
    created_at: datetime


class NoteOut(Schema):
    id: int
    author: str | None = Field(None, alias="author.username")
    author_name: str | None = Field(None, alias="author.display_name")
    text: str
    customer_visible: bool
    created_at: datetime


class WorkItemOut(Schema):
    """A complaint as it appears in work queues."""

    complaint_id: str
    title: str
    status: str
    customer: str = Field(alias="customer.username")
    customer_name: str = Field(alias="customer.display_name")
    category: str | None = Field(None, alias="category.code")
    subcategory: str | None = Field(None, alias="subcategory.code")
    department: str | None = Field(None, alias="department.code")
    assigned_to: str | None = Field(None, alias="assigned_to.username")
    assigned_to_name: str | None = Field(None, alias="assigned_to.display_name")
    priority: str
    urgency: str
    sentiment: str
    escalation_level: str
    verification_status: str
    verification_score: int | None
    review_status: str
    review_reasons: list[str]
    sla: dict
    follow_up_due: datetime | None
    created_at: datetime

    @staticmethod
    def resolve_review_reasons(obj):
        latest = obj.validations.first()
        return latest.review_reasons if latest else []

    @staticmethod
    def resolve_sla(obj):
        return sla_status(obj)
