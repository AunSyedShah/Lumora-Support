"""Audit trail helpers: snapshot the complaint's working state and log what changed."""

from .models import AuditLog

TRACKED = [
    "status", "category", "subcategory", "department", "supporting_departments", "assigned_to", "priority",
    "urgency", "escalation_level", "verification_status", "verification_score", "review_status", "response_text",
]


def snapshot(complaint):
    return {
        "status": complaint.status,
        "category": complaint.category.code if complaint.category else None,
        "subcategory": complaint.subcategory.code if complaint.subcategory else None,
        "department": complaint.department.code if complaint.department else None,
        "supporting_departments": list(complaint.supporting_departments or []),
        "assigned_to": complaint.assigned_to.username if complaint.assigned_to else None,
        "priority": complaint.priority or None,
        "urgency": complaint.urgency or None,
        "escalation_level": complaint.escalation_level or None,
        "verification_status": complaint.verification_status,
        "verification_score": complaint.verification_score,
        "review_status": complaint.review_status,
        "response_text": complaint.response_text or None,
    }


def log_event(complaint, actor, action, before=None, comment=""):
    """Store only the fields that changed between `before` and now."""
    after_all = snapshot(complaint)
    before = before or {}
    changed = [f for f in TRACKED if f in before and before[f] != after_all[f]]
    return AuditLog.objects.create(
        complaint=complaint,
        actor=actor if actor and actor.is_authenticated else None,
        action=action,
        before={f: before[f] for f in changed},
        after={f: after_all[f] for f in changed},
        comment=comment,
    )
