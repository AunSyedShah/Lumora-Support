"""
Workflow actions. Every function changes the complaint's working state and writes an audit entry
with the state before and after, so the original recommendation and every human decision stay
visible side by side (SRS Step 59).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import User
from catalog.models import Category, Department, Subcategory
from complaints.facts import rule_facts
from complaints.models import Complaint
from python_validation.checks import expected_escalation
from python_validation.services import check_outgoing_response, process_complaint
from rules.engine import evaluate
from rules.models import ESCALATION_RANK, EscalationLevel

from .audit import log_event, snapshot
from .lifecycle import TransitionError, apply_status, can_move, set_sla_due_dates
from .models import AuditLog, ComplaintNote

logger = logging.getLogger(__name__)

S = Complaint.Status
A = AuditLog.Action
OPEN = Complaint.OPEN_STATUSES
REVIEW_OPEN = (Complaint.Review.PENDING, Complaint.Review.REJECTED)


class WorkflowError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def _move(complaint, target):
    """Automatic status change: only if the lifecycle allows it (never an error)."""
    if complaint.status != target and can_move(complaint.status, target):
        apply_status(complaint, target)


def _set_status(complaint, target):
    """Human status change: invalid transitions are reported."""
    try:
        apply_status(complaint, target)
    except TransitionError as e:
        raise WorkflowError(str(e), 409)


def _is_escalated(complaint):
    return (complaint.escalation_level or EscalationLevel.NONE) != EscalationLevel.NONE


# ---------------- assignment ----------------


def auto_assign(complaint):
    """The active agent in the complaint's department with the fewest open complaints."""
    if complaint.department is None:
        return None
    agent = (
        User.objects.filter(role=User.Role.AGENT, is_active=True, department=complaint.department)
        .annotate(open_count=Count("assigned_complaints", filter=Q(assigned_complaints__status__in=OPEN)))
        .order_by("open_count", "id")
        .first()
    )
    complaint.assigned_to = agent
    return agent


def _sync_escalation(complaint):
    """
    Keep status, owner and escalation level consistent after any change:
      escalated     -> status 'escalated' and someone owns it
      not escalated -> leaves 'escalated' status (back to its agent, or 'in progress')
    """
    if _is_escalated(complaint):
        if complaint.assigned_to is None:
            auto_assign(complaint)
        _move(complaint, S.ESCALATED)
    elif complaint.status == S.ESCALATED:
        if complaint.assigned_to is None:
            auto_assign(complaint)
        _move(complaint, S.ASSIGNED if complaint.assigned_to else S.IN_PROGRESS)


def _update_resolution(complaint, **extra):
    """Keep the working resolution in line with the complaint's working fields."""
    complaint.resolution = {
        **(complaint.resolution or {}),
        "category": complaint.category.code if complaint.category else None,
        "subcategory": complaint.subcategory.code if complaint.subcategory else None,
        "department": complaint.department.code if complaint.department else None,
        "priority": complaint.priority,
        "urgency": complaint.urgency,
        "escalation_level": complaint.escalation_level,
        "escalation_required": _is_escalated(complaint),
        **extra,
    }


# ---------------- processing -> working state ----------------


def _fallback_from_rules(independent):
    """
    GenAI failed: use the Python rule engine's own result, so escalation, routing and SLA still
    happen (a safety report must not wait just because the GenAI API is down).
    """
    if not independent.get("category"):
        return {}
    return {
        "source": "rule_engine_fallback",
        "category": independent["category"],
        "subcategory": independent["subcategory"],
        "department": independent["department"],
        "supporting_departments": independent.get("supporting_departments", []),
        "priority": independent.get("priority"),
        "urgency": independent.get("urgency"),
        "escalation_level": independent.get("escalation_level") or EscalationLevel.NONE,
        "escalation_required": independent.get("escalation_required", False),
        "escalation_rules": [e["rule_id"] for e in independent.get("escalation_rules", [])],
        "resolution_rule": independent.get("resolution_rule"),
        "resolution_steps": independent.get("required_actions", []),
        "prohibited_actions": independent.get("prohibited_actions", []),
        "policy_references": [f"{independent['policy_id']} {independent.get('policy_section') or ''}".strip()]
        if independent.get("policy_id") else [],
        "compensation": {"type": "none", "justification": "No GenAI analysis; decide manually.", "policy_id": None, "section": None},
        "customer_response": {"tone": "", "text": ""},
        "response_requires_rewrite": True,
        "follow_up": {"required": independent.get("follow_up_required", False), "type": "none",
                      "days": independent.get("follow_up_days", 0), "message": ""},
        "enforced": ["GenAI output unavailable: working state taken from the rule matrix"],
    }


def apply_validation(complaint, result, actor=None):
    """Copy the validated final resolution (or the rule-engine fallback) onto the complaint and route it."""
    before = snapshot(complaint)
    final = result.final_resolution or _fallback_from_rules(result.independent_expected or {})
    if final:
        complaint.category = Category.objects.filter(code=final["category"]).first()
        complaint.subcategory = Subcategory.objects.filter(code=final["subcategory"]).first()
        complaint.department = Department.objects.filter(code=final["department"]).first()
        complaint.supporting_departments = final.get("supporting_departments", [])
        complaint.priority = final.get("priority") or complaint.priority
        complaint.urgency = final.get("urgency") or complaint.urgency
        complaint.escalation_level = final["escalation_level"]
        complaint.sentiment = (result.analysis.output or {}).get("sentiment", "") if result.analysis else ""
        complaint.resolution = final
        complaint.response_text = final["customer_response"]["text"]
        follow_up = final.get("follow_up") or {}
        if follow_up.get("required"):
            complaint.follow_up_due = timezone.now() + timedelta(days=follow_up.get("days") or 1)
            complaint.follow_up_done_at = None
    complaint.verification_status = result.decision
    complaint.verification_score = result.score
    manual = result.decision == Complaint.Verification.MANUAL_REVIEW
    complaint.review_status = Complaint.Review.PENDING if manual else Complaint.Review.NOT_REQUIRED
    set_sla_due_dates(complaint)

    if complaint.status == S.NEW:
        _move(complaint, S.ANALYZED)
    # Escalated complaints get an owner immediately, even while a manual review is pending:
    # e.g. a safety report must reach Product Safety within 1 hour (SAF-POL 2.2).
    if not manual or final.get("escalation_required"):
        if complaint.assigned_to is None or complaint.assigned_to.department_id != complaint.department_id:
            auto_assign(complaint)
    if final.get("escalation_required"):
        _move(complaint, S.ESCALATED)
    elif not manual and complaint.assigned_to:
        _move(complaint, S.ASSIGNED)
    complaint.save()
    log_event(complaint, actor, A.PROCESSED, before,
              f"{result.decision} (score {result.score}); {'; '.join(result.review_reasons) or 'no review needed'}")
    return complaint


def auto_process(complaint):
    """
    Called right after submission, so every complaint is analysed, validated and routed without
    anyone pressing "process". It never raises: submission must succeed even if processing fails.
      - GenAI failure  -> handled inside the pipeline (rule-engine fallback, manual review)
      - anything else  -> the complaint goes to the manual review queue with the error, and an SLA,
                          so a person picks it up (`manage.py process_pending` can retry it later)
    """
    if not settings.AUTO_PROCESS_ON_SUBMIT:
        return None
    try:
        return process_and_apply(complaint)
    except Exception as exc:  # deliberately broad: nothing here may break the customer's submission
        logger.exception("Automatic processing failed for %s", complaint.complaint_id)
        complaint.refresh_from_db()
        before = snapshot(complaint)
        complaint.verification_status = Complaint.Verification.MANUAL_REVIEW
        complaint.review_status = Complaint.Review.PENDING
        set_sla_due_dates(complaint)
        complaint.save()
        log_event(complaint, None, A.PROCESSED, before, f"Automatic processing failed: {exc}")
        return None


def process_and_apply(complaint, tone=None, actor=None, reuse_analysis=False):
    if complaint.status in (S.RESOLVED, S.CLOSED):
        # Re-processing would overwrite the final decisions of a finished case.
        raise WorkflowError("This complaint is resolved or closed. Reopen it before processing it again.", 409)
    result = process_complaint(complaint, tone=tone, requested_by=actor, reuse_analysis=reuse_analysis)
    apply_validation(complaint, result, actor)
    return result


# ---------------- reviewer actions (SRS Step 58) ----------------


def _require_review(complaint):
    if complaint.review_status not in REVIEW_OPEN:
        raise WorkflowError("This complaint has no pending manual review.", 409)


def approve(complaint, actor, comment=""):
    _require_review(complaint)
    before = snapshot(complaint)
    complaint.review_status = Complaint.Review.APPROVED
    if complaint.assigned_to is None:
        auto_assign(complaint)
    if _is_escalated(complaint):
        _move(complaint, S.ESCALATED)
    elif complaint.assigned_to:
        _move(complaint, S.ASSIGNED)
    complaint.save()
    log_event(complaint, actor, A.APPROVED, before, comment)
    return complaint


def reject(complaint, actor, comment):
    _require_review(complaint)
    if not comment.strip():
        raise WorkflowError("A comment explaining the rejection is required.")
    before = snapshot(complaint)
    complaint.review_status = Complaint.Review.REJECTED
    complaint.save()
    log_event(complaint, actor, A.REJECTED, before, comment)
    return complaint


def modify(complaint, actor, changes, comment=""):
    """changes may contain: priority, urgency, escalation_level, response_text, resolution_steps, follow_up_days."""
    before = snapshot(complaint)
    lowering_escalation = (
        changes.get("escalation_level") is not None
        and ESCALATION_RANK[changes["escalation_level"]] < ESCALATION_RANK.get(complaint.escalation_level or "none", 0)
    )
    if lowering_escalation and not comment.strip():
        raise WorkflowError("Lowering an escalation requires a comment explaining why.")

    for field in ("priority", "urgency", "escalation_level", "response_text"):
        if changes.get(field) is not None:
            setattr(complaint, field, changes[field])
    extra = {}
    if changes.get("resolution_steps") is not None:
        extra["resolution_steps"] = changes["resolution_steps"]
    if changes.get("response_text") is not None:
        extra["response_edited_by_reviewer"] = True
    if changes.get("follow_up_days") is not None:
        complaint.follow_up_due = timezone.now() + timedelta(days=changes["follow_up_days"])
    _update_resolution(complaint, **extra)
    if changes.get("priority") is not None:
        set_sla_due_dates(complaint)
    _sync_escalation(complaint)
    complaint.save()
    log_event(complaint, actor, A.MODIFIED, before, comment)
    return complaint


def reclassify(complaint, actor, subcategory_code, department_code=None, comment=""):
    """New subcategory -> the rules for it decide department, urgency, priority and escalation."""
    subcategory = Subcategory.objects.select_related("category").filter(code=subcategory_code, is_active=True).first()
    if subcategory is None:
        raise WorkflowError(f"Unknown subcategory '{subcategory_code}'.", 404)
    department = None
    if department_code:
        department = Department.objects.filter(code=department_code, is_active=True).first()
        if department is None:
            raise WorkflowError(f"Unknown department '{department_code}'.", 404)

    before = snapshot(complaint)
    view = evaluate(rule_facts(complaint), subcategory_code=subcategory.code)
    independent = evaluate(rule_facts(complaint))

    complaint.category, complaint.subcategory = subcategory.category, subcategory
    complaint.department = department or Department.objects.filter(code=view["department"]).first()
    # A newly configured subcategory may have no rules yet: then keep the current priority / urgency
    # (or the default SLA priority) instead of blanking them.
    complaint.priority = view["priority"] or complaint.priority or settings.DEFAULT_SLA_PRIORITY
    complaint.urgency = view["urgency"] or complaint.urgency or "Medium"
    complaint.escalation_level = expected_escalation(independent, view)
    _update_resolution(
        complaint,
        resolution_rule=view["resolution_rule"],
        required_actions=view["required_actions"],
        prohibited_actions=view["prohibited_actions"],
        allowed_compensation=view["allowed_compensation"],
        policy_references=[f"{view['policy_id']} {view['policy_section'] or ''}".strip()] if view["policy_id"] else [],
    )
    set_sla_due_dates(complaint)
    if complaint.assigned_to and complaint.assigned_to.department_id != complaint.department_id:
        auto_assign(complaint)
    _sync_escalation(complaint)
    complaint.save()
    note = f"Rules applied: {view['resolution_rule']}" if view["resolution_rule"] else "No rule exists for this subcategory yet"
    log_event(complaint, actor, A.RECLASSIFIED, before, comment or note)
    return complaint


def reassign(complaint, actor, department_code=None, assignee_username=None, comment=""):
    before = snapshot(complaint)
    if department_code:
        department = Department.objects.filter(code=department_code, is_active=True).first()
        if department is None:
            raise WorkflowError(f"Unknown department '{department_code}'.", 404)
        complaint.department = department
    if assignee_username:
        agent = User.objects.filter(username=assignee_username, is_active=True).exclude(role=User.Role.CUSTOMER).first()
        if agent is None:
            raise WorkflowError(f"No active staff member '{assignee_username}'.", 404)
        complaint.assigned_to = agent
    elif department_code:
        auto_assign(complaint)  # may find nobody -> the complaint waits unassigned in the department
    if complaint.assigned_to and complaint.status in (S.NEW, S.ANALYZED, S.REOPENED):
        _move(complaint, S.ASSIGNED)
    _update_resolution(complaint)
    complaint.save()
    log_event(complaint, actor, A.ASSIGNED, before, comment)
    return complaint


def escalate(complaint, actor, level, comment):
    if level == EscalationLevel.NONE:
        raise WorkflowError("Choose an escalation level.")
    if not comment.strip():
        raise WorkflowError("A comment explaining the escalation is required.")
    if ESCALATION_RANK[level] < ESCALATION_RANK.get(complaint.escalation_level or "none", 0):
        raise WorkflowError(f"The complaint is already escalated to '{complaint.escalation_level}'.", 409)
    before = snapshot(complaint)
    complaint.escalation_level = level
    if complaint.status != S.ESCALATED:
        _set_status(complaint, S.ESCALATED)
    if complaint.assigned_to is None:
        auto_assign(complaint)
    _update_resolution(complaint)
    complaint.save()
    log_event(complaint, actor, A.ESCALATED, before, comment)
    return complaint


def regenerate(complaint, actor, tone=None):
    """New GenAI analysis + validation. The review restarts if the new result needs one."""
    if complaint.status in (S.RESOLVED, S.CLOSED):
        raise WorkflowError("This complaint is resolved or closed. Reopen it before regenerating.", 409)
    log_event(complaint, actor, A.REGENERATED, snapshot(complaint), f"tone={tone or settings.GENAI_DEFAULT_TONE}")
    return process_and_apply(complaint, tone=tone, actor=actor)


# ---------------- agent actions ----------------


def add_note(complaint, actor, text, customer_visible=False):
    note = ComplaintNote.objects.create(complaint=complaint, author=actor, text=text, customer_visible=customer_visible)
    if customer_visible and complaint.first_response_at is None:
        complaint.first_response_at = note.created_at
        complaint.save(update_fields=["first_response_at", "updated_at"])
    log_event(complaint, actor, A.COMMENTED, {}, ("[to customer] " if customer_visible else "[internal] ") + text)
    return note


def change_status(complaint, actor, target, comment=""):
    # These states have their own actions that also set the escalation level / owner.
    if target == S.ESCALATED:
        raise WorkflowError("Use the escalate action (it records the escalation level and reason).")
    if target == S.ASSIGNED and complaint.assigned_to is None:
        raise WorkflowError("Use the assign action: the complaint has no assignee.")
    if target in (S.RESOLVED, S.CLOSED) and complaint.review_status in REVIEW_OPEN:
        raise WorkflowError("The recommendation is still waiting for manual review.", 409)
    before = snapshot(complaint)
    _set_status(complaint, target)
    complaint.save()
    log_event(complaint, actor, A.STATUS_CHANGED, before, comment)
    return complaint


def send_response(complaint, actor, text=None, override_reason=None):
    """
    'Send' the reply to the customer (simulated: stored as a customer-visible update).
    Every outgoing text is re-checked for unsupported promises / invented facts - whoever wrote it.
    A reviewer may override the check with a written reason (kept in the audit log).
    """
    text = (text or complaint.response_text or "").strip()
    if not text:
        raise WorkflowError("There is no response text to send.")
    if complaint.review_status in REVIEW_OPEN:
        raise WorkflowError("The recommendation is waiting for manual review; it cannot be sent yet.", 409)

    findings = check_outgoing_response(complaint, text)
    if findings and not override_reason:
        details = "; ".join(f"{f['python'] or f['name']}: \"{f['genai']}\"" for f in findings)
        raise WorkflowError(f"The response contains unsupported content ({details}). Edit it before sending.", 409)

    before = snapshot(complaint)
    now = timezone.now()
    complaint.response_text, complaint.response_sent_at = text, now
    complaint.first_response_at = complaint.first_response_at or now
    if complaint.status in (S.ANALYZED, S.ASSIGNED, S.REOPENED):
        _move(complaint, S.IN_PROGRESS)
    complaint.save()
    ComplaintNote.objects.create(complaint=complaint, author=actor, text=text, customer_visible=True)
    comment = f"OVERRIDE of validation findings: {override_reason}" if findings else ""
    log_event(complaint, actor, A.RESPONSE_SENT, before, comment)
    return complaint


def follow_up_done(complaint, actor, comment=""):
    if complaint.follow_up_due is None:
        raise WorkflowError("This complaint has no follow-up scheduled.", 409)
    complaint.follow_up_done_at = timezone.now()
    complaint.save(update_fields=["follow_up_done_at", "updated_at"])
    log_event(complaint, actor, A.FOLLOW_UP_DONE, {}, comment)
    return complaint


# ---------------- customer actions ----------------


def customer_reply(complaint, customer, text):
    if complaint.status in (S.RESOLVED, S.CLOSED):
        raise WorkflowError("This complaint is resolved. Reopen it if the problem is not fixed.", 409)
    before = snapshot(complaint)
    ComplaintNote.objects.create(complaint=complaint, author=customer, text=text, customer_visible=True)
    if complaint.status == S.AWAITING_CUSTOMER:
        apply_status(complaint, S.IN_PROGRESS)  # the SLA clock starts again
        complaint.save()
    log_event(complaint, customer, A.CUSTOMER_REPLY, before, text)
    return complaint


REOPEN_WINDOW_DAYS = 7  # TPL-RSP 5: "reply within 7 days and we will reopen your case"


def customer_reopen(complaint, customer, reason):
    if complaint.status not in (S.RESOLVED, S.CLOSED):
        raise WorkflowError("Only resolved or closed complaints can be reopened.", 409)
    finished = complaint.closed_at or complaint.resolved_at
    if finished and timezone.now() - finished > timedelta(days=REOPEN_WINDOW_DAYS):
        raise WorkflowError(f"Complaints can be reopened within {REOPEN_WINDOW_DAYS} days. Please submit a new complaint.", 409)
    before = snapshot(complaint)
    apply_status(complaint, S.REOPENED)
    complaint.save()
    ComplaintNote.objects.create(complaint=complaint, author=customer, text=reason, customer_visible=True)
    log_event(complaint, customer, A.REOPENED, before, reason)
    return complaint
