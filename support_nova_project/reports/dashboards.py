"""
Dashboards (SRS Steps 62-63). The customer dashboard (Step 61) is /api/complaints/my.

agent_dashboard  the agent's OWN assigned complaints with the GenAI recommendation, validation
                 status, suggested response and escalation warnings
admin_dashboard  organisation-wide metrics for reviewers, managers and administrators
"""

from django.utils import timezone

from complaints.models import Complaint
from complaints.permissions import visible_complaints
from python_validation.comparison import COMPARED
from workflow.lifecycle import sla_status

from .analytics import detect_trends, distribution
from .data import complaint_frame, latest_validations

REVIEW_REASON_TYPES = [
    # (type, text that identifies it in a validation review reason)
    ("genai_output_invalid", "could not be produced"),
    ("critical_finding", "Critical finding"),
    ("low_score", "Verification score"),
    ("ambiguous_complaint", "ambiguous"),
    ("eligibility_unclear", "Eligibility unclear"),
    ("missing_policy_support", "Policy support is missing"),
    ("policy_contradiction", "Policy contradiction"),
    ("sensitive_complaint", "Sensitive complaint"),
    ("possible_manipulation", "manipulation"),
    ("processing_failed", "Automatic processing failed"),
]


def reason_type(reason):
    for kind, marker in REVIEW_REASON_TYPES:
        if marker.lower() in reason.lower():
            return kind
    return "other"


def agent_dashboard(user):
    open_statuses = Complaint.OPEN_STATUSES
    mine = visible_complaints(user).filter(assigned_to=user).select_related("category", "subcategory")
    open_items = mine.filter(status__in=open_statuses)
    now = timezone.now()
    items = []
    for c in open_items.order_by("sla_resolution_due"):
        resolution = c.resolution or {}
        sla = sla_status(c, now=now)
        validation = c.validations.first()
        items.append({
            "complaint_id": c.complaint_id,
            "title": c.title,
            "status": c.status,
            "category": c.category.code if c.category else None,
            "subcategory": c.subcategory.code if c.subcategory else None,
            "priority": c.priority,
            "urgency": c.urgency,
            "sentiment": c.sentiment,
            "genai_recommendation": {
                "summary": resolution.get("summary"),
                "resolution_steps": resolution.get("resolution_steps", []),
                "compensation": (resolution.get("compensation") or {}).get("type"),
                "policy_references": resolution.get("policy_references", []),
                "enforced_by_rules": resolution.get("enforced", []),
            },
            "validation": {
                "status": c.verification_status,
                "score": c.verification_score,
                "review_status": c.review_status,
                "review_reasons": validation.review_reasons if validation else [],
            },
            "suggested_response": c.response_text,
            "response_requires_rewrite": resolution.get("response_requires_rewrite", False),
            "escalation_warning": (
                {"level": c.escalation_level, "rules": resolution.get("escalation_rules", [])}
                if (c.escalation_level or "none") != "none" else None
            ),
            "sla": {"response": sla["response"], "resolution": sla["resolution"], "resolution_due": sla["resolution_due"]},
            "follow_up_due": c.follow_up_due if c.follow_up_done_at is None else None,
        })
    return {
        "agent": user.username,
        "open_assigned": len(items),
        "by_status": _count(items, "status"),
        "by_priority": _count(items, "priority"),
        "sla_at_risk": sum(i["sla"]["resolution"] == "at_risk" for i in items),
        "sla_breached": sum(i["sla"]["resolution"] == "breached" for i in items),
        "escalated": sum(i["escalation_warning"] is not None for i in items),
        "follow_ups_due": sum(1 for i in items if i["follow_up_due"] and i["follow_up_due"] <= now),
        "resolved_total": mine.filter(status__in=[Complaint.Status.RESOLVED, Complaint.Status.CLOSED]).count(),
        "complaints": items,
    }


def _count(items, key):
    counts = {}
    for item in items:
        counts[item[key] or "unknown"] = counts.get(item[key] or "unknown", 0) + 1
    return counts


def mismatch_summary(queryset):
    """GenAI vs Python disagreements, from the latest validation of each complaint."""
    results = latest_validations(queryset)
    by_field = {field: 0 for field in COMPARED}
    with_mismatch = 0
    for result in results:
        failed = {c["name"] for c in result.checks if c["name"] in COMPARED and c["status"] in ("fail", "warning")}
        with_mismatch += bool(failed)
        for field in failed:
            by_field[field] += 1
    return {
        "validated": len(results),
        "with_mismatch": with_mismatch,
        "agreement_rate_percent": round(100 * (1 - with_mismatch / len(results)), 1) if results else None,
        "by_field": by_field,
    }


def manual_review_summary(queryset):
    pending = queryset.filter(review_status__in=[Complaint.Review.PENDING, Complaint.Review.REJECTED])
    reasons = {}
    for result in latest_validations(pending):
        for reason in result.review_reasons:
            kind = reason_type(reason)
            reasons[kind] = reasons.get(kind, 0) + 1
    return {
        "pending": pending.filter(review_status=Complaint.Review.PENDING).count(),
        "rejected_awaiting_decision": pending.filter(review_status=Complaint.Review.REJECTED).count(),
        "reviewed": queryset.filter(review_status=Complaint.Review.APPROVED).count(),
        "by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    }


def admin_dashboard(queryset):
    df = complaint_frame(queryset)
    total = len(df)
    at_risk = df[df["is_open"] & df["sla_resolution"].isin(["at_risk", "breached"])] if total else df
    trends = detect_trends(df)
    return {
        "total_complaints": total,
        "open": int(df["is_open"].sum()) if total else 0,
        "category_distribution": distribution(df, "category"),
        "department_distribution": distribution(df, "department"),
        "priority_levels": distribution(df, "priority"),
        "escalations": {
            "total": int(df["escalated"].sum()) if total else 0,
            "open": int((df["escalated"] & df["is_open"]).sum()) if total else 0,
            "by_level": distribution(df[df["escalated"]], "escalation_level") if total else [],
        },
        "resolution_status": distribution(df, "status"),
        "sla_risks": {
            "at_risk": int((at_risk["sla_resolution"] == "at_risk").sum()) if total else 0,
            "breached": int((at_risk["sla_resolution"] == "breached").sum()) if total else 0,
            "most_urgent": at_risk.sort_values("created_at")[
                ["complaint_id", "priority", "department", "assigned_to", "sla_resolution"]
            ].head(10).to_dict("records") if total else [],
        },
        "genai_python_mismatches": mismatch_summary(queryset),
        "manual_review": manual_review_summary(queryset),
        "trend_alerts": [t["message"] for key in ("rising", "recurring_product_issues", "repeated_service_failures",
                                                   "escalation_spikes") for t in trends[key]][:10],
    }
