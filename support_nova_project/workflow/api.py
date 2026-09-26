"""
Workflow API: manual review queue, reviewer actions, agent actions, SLA / follow-up lists,
audit trail, and customer replies / reopening.

Roles:  reviewer / manager / admin -> review actions, assignment, escalation
        agents (and above)         -> notes, status changes, sending responses, follow-ups
        customers                  -> reply to / reopen their own complaints
"""

from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from complaints.models import Complaint
from complaints.permissions import FULL_ACCESS_ROLES, get_visible_complaint, visible_complaints
from genai_pipeline.prompts import PromptError
from python_validation.schemas import ValidationOut

from . import services
from .lifecycle import sla_status
from .schemas import (
    AssignIn,
    AuditOut,
    CommentIn,
    CustomerTextIn,
    EscalateIn,
    ModifyIn,
    NoteIn,
    NoteOut,
    ReclassifyIn,
    RegenerateIn,
    RejectIn,
    SendResponseIn,
    StatusIn,
    WorkItemOut,
)

router = Router(tags=["Workflow"])

REVIEWERS = FULL_ACCESS_ROLES
PRIORITY_ORDER = Case(*[When(priority=p, then=Value(i)) for i, p in enumerate(["P0", "P1", "P2", "P3"])],
                      default=Value(9), output_field=IntegerField())


def _complaints():
    return Complaint.objects.select_related("customer", "category", "subcategory", "department", "assigned_to")


def _get(request, complaint_id):
    """The complaint, if this user may see it (agents: only their own assignments), else 404."""
    return get_visible_complaint(request.auth, complaint_id, _complaints())


def _run(action, *args, **kwargs):
    """Call a workflow service and turn its errors into HTTP errors."""
    try:
        return action(*args, **kwargs)
    except services.WorkflowError as e:
        raise HttpError(e.status_code, str(e))
    except PromptError as e:
        raise HttpError(503, str(e))


# ---------------- queues ----------------


@router.get("/review-queue", response=list[WorkItemOut])
def review_queue(request, department: str | None = None, priority: str | None = None,
                 include_rejected: bool = True):
    """Complaints waiting for a human decision (SRS Step 57), most urgent first."""
    require_role(request, *REVIEWERS)
    states = [Complaint.Review.PENDING] + ([Complaint.Review.REJECTED] if include_rejected else [])
    qs = _complaints().filter(review_status__in=states)
    if department:
        qs = qs.filter(department__code=department.upper())
    if priority:
        qs = qs.filter(priority=priority.upper())
    return qs.annotate(p=PRIORITY_ORDER).order_by("p", "sla_resolution_due", "created_at")


@router.get("/my-queue", response=list[WorkItemOut])
def my_queue(request):
    """Open complaints assigned to the logged-in staff member."""
    require_role(request, *STAFF_ROLES)
    qs = _complaints().filter(assigned_to=request.auth, status__in=Complaint.OPEN_STATUSES)
    return qs.annotate(p=PRIORITY_ORDER).order_by("p", "sla_resolution_due")


@router.get("/sla", response=list[WorkItemOut])
def sla_watch(request, state: str = "at_risk"):
    """Open complaints whose resolution SLA is 'at_risk' or 'breached' (SRS Step 56)."""
    require_role(request, *STAFF_ROLES)
    if state not in ("at_risk", "breached"):
        raise HttpError(400, "state must be 'at_risk' or 'breached'")
    qs = visible_complaints(request.auth, _complaints()).filter(
        status__in=Complaint.OPEN_STATUSES, sla_resolution_due__isnull=False
    )
    return [c for c in qs.order_by("sla_resolution_due") if sla_status(c)["resolution"] == state]


@router.get("/follow-ups", response=list[WorkItemOut])
def follow_ups(request, overdue_only: bool = False):
    """Scheduled follow-ups not done yet (SRS Step 41)."""
    require_role(request, *STAFF_ROLES)
    qs = visible_complaints(request.auth, _complaints()).filter(
        follow_up_due__isnull=False, follow_up_done_at__isnull=True
    )
    if overdue_only:
        qs = qs.filter(follow_up_due__lte=timezone.now())
    return qs.order_by("follow_up_due")


# ---------------- history ----------------


@router.get("/complaints/{complaint_id}/audit", response=list[AuditOut])
def audit_trail(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    return _get(request, complaint_id).audit_log.select_related("actor")


@router.get("/complaints/{complaint_id}/notes", response=list[NoteOut])
def notes(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    return _get(request, complaint_id).notes.select_related("author")


@router.get("/complaints/{complaint_id}", response=WorkItemOut)
def work_item(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    return _get(request, complaint_id)


# ---------------- reviewer actions ----------------


@router.post("/complaints/{complaint_id}/approve", response={200: WorkItemOut, 409: ErrorOut})
def approve(request, complaint_id: str, data: CommentIn):
    require_role(request, *REVIEWERS)
    return _run(services.approve, _get(request, complaint_id), request.auth, data.comment)


@router.post("/complaints/{complaint_id}/reject", response={200: WorkItemOut, 409: ErrorOut})
def reject(request, complaint_id: str, data: RejectIn):
    require_role(request, *REVIEWERS)
    return _run(services.reject, _get(request, complaint_id), request.auth, data.comment)


@router.post("/complaints/{complaint_id}/modify", response=WorkItemOut)
def modify(request, complaint_id: str, data: ModifyIn):
    require_role(request, *REVIEWERS)
    changes = data.model_dump(exclude_unset=True, exclude={"comment"})
    if not changes:
        raise HttpError(400, "Nothing to modify.")
    return _run(services.modify, _get(request, complaint_id), request.auth, changes, data.comment)


@router.post("/complaints/{complaint_id}/reclassify", response={200: WorkItemOut, 404: ErrorOut})
def reclassify(request, complaint_id: str, data: ReclassifyIn):
    require_role(request, *REVIEWERS)
    return _run(services.reclassify, _get(request, complaint_id), request.auth,
                data.subcategory.upper(), data.department.upper() if data.department else None, data.comment)


@router.post("/complaints/{complaint_id}/assign", response={200: WorkItemOut, 404: ErrorOut})
def assign(request, complaint_id: str, data: AssignIn):
    require_role(request, *REVIEWERS)
    if not data.department and not data.assignee:
        raise HttpError(400, "Give a department and/or an assignee.")
    return _run(services.reassign, _get(request, complaint_id), request.auth,
                data.department.upper() if data.department else None, data.assignee, data.comment)


@router.post("/complaints/{complaint_id}/escalate", response={200: WorkItemOut, 409: ErrorOut})
def escalate(request, complaint_id: str, data: EscalateIn):
    require_role(request, *REVIEWERS)
    return _run(services.escalate, _get(request, complaint_id), request.auth, data.level, data.comment)


@router.post("/complaints/{complaint_id}/regenerate", response={200: ValidationOut, 503: ErrorOut})
def regenerate(request, complaint_id: str, data: RegenerateIn):
    """Run the GenAI + validation pipeline again (optionally with another tone)."""
    require_role(request, *REVIEWERS)
    return _run(services.regenerate, _get(request, complaint_id), request.auth, data.tone)


# ---------------- agent actions ----------------


@router.post("/complaints/{complaint_id}/notes", response=NoteOut)
def add_note(request, complaint_id: str, data: NoteIn):
    require_role(request, *STAFF_ROLES)
    return services.add_note(_get(request, complaint_id), request.auth, data.text, data.customer_visible)


@router.post("/complaints/{complaint_id}/status", response={200: WorkItemOut, 409: ErrorOut})
def change_status(request, complaint_id: str, data: StatusIn):
    require_role(request, *STAFF_ROLES)
    return _run(services.change_status, _get(request, complaint_id), request.auth, data.status, data.comment)


@router.post("/complaints/{complaint_id}/send-response", response={200: WorkItemOut, 409: ErrorOut})
def send_response(request, complaint_id: str, data: SendResponseIn):
    require_role(request, *STAFF_ROLES)
    if data.override_reason:
        require_role(request, *REVIEWERS)  # only reviewers may send despite validation findings
    return _run(services.send_response, _get(request, complaint_id), request.auth, data.text, data.override_reason)


@router.post("/complaints/{complaint_id}/follow-up-done", response={200: WorkItemOut, 409: ErrorOut})
def follow_up_done(request, complaint_id: str, data: CommentIn):
    require_role(request, *STAFF_ROLES)
    return _run(services.follow_up_done, _get(request, complaint_id), request.auth, data.comment)


# ---------------- customer actions ----------------


def _own(request, complaint_id):
    return get_object_or_404(_complaints(), complaint_id=complaint_id.upper(), customer=request.auth)


@router.post("/my/complaints/{complaint_id}/reply", response={200: None, 409: ErrorOut})
def customer_reply(request, complaint_id: str, data: CustomerTextIn):
    """Customer adds information. If we were waiting for them, the complaint moves back to 'in progress'."""
    _run(services.customer_reply, _own(request, complaint_id), request.auth, data.text)
    return 200, None


@router.post("/my/complaints/{complaint_id}/reopen", response={200: None, 409: ErrorOut})
def customer_reopen(request, complaint_id: str, data: CustomerTextIn):
    _run(services.customer_reopen, _own(request, complaint_id), request.auth, data.text)
    return 200, None
