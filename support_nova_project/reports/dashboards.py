"""
Dashboards (SRS Steps 62-63). The customer dashboard (Step 61) is /api/complaints/my.

agent_dashboard  the agent's OWN assigned complaints with the GenAI recommendation, validation
                 status, suggested response and escalation warnings
admin_dashboard  organisation-wide metrics for reviewers, managers and administrators
"""

import math
from datetime import timedelta

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


def next_deadline(sla):
    """The deadline the agent must beat next: the first reply until we have replied, then the resolution."""
    if sla["response"] in ("on_track", "at_risk", "breached"):
        return {"kind": "reply", "due": sla["response_due"], "state": sla["response"]}
    return {"kind": "resolve", "due": sla["resolution_due"], "state": sla["resolution"]}


def agent_dashboard(user):
    open_statuses = Complaint.OPEN_STATUSES
    mine = visible_complaints(user).filter(assigned_to=user).select_related("category", "subcategory")
    open_items = mine.filter(status__in=open_statuses)
    now = timezone.now()
    items = []
    for c in open_items:
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
            "sla": {"response": sla["response"], "resolution": sla["resolution"], "response_due": sla["response_due"],
                    "resolution_due": sla["resolution_due"], "paused": sla["paused"]},
            "next_deadline": next_deadline(sla),
            "follow_up_due": c.follow_up_due if c.follow_up_done_at is None else None,
        })
    # Most pressing first: overdue ones by priority, then everything else by the nearest deadline.
    far = now + timedelta(days=3650)
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

    def pressing(item):
        overdue = item["next_deadline"]["state"] == "breached"
        return (not overdue, rank.get(item["priority"], 9) if overdue else 0, item["next_deadline"]["due"] or far)

    items.sort(key=pressing)
    return {
        "agent": user.username,
        "open_assigned": len(items),
        "by_status": _count(items, "status"),
        "by_priority": _count(items, "priority"),
        # counted on the next deadline, so a late first reply shows up as overdue too
        "sla_at_risk": sum(i["next_deadline"]["state"] == "at_risk" for i in items),
        "sla_breached": sum(i["next_deadline"]["state"] == "breached" for i in items),
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


PENDING = ("on_track", "at_risk", "breached")


def with_next_deadline(df):
    """Add the deadline that matters now (as in next_deadline): the first reply until it is sent, then the resolution."""
    if not len(df):
        return df.assign(deadline_kind=[], deadline_state=[])
    reply_pending = df["sla_response"].isin(PENDING)
    return df.assign(deadline_kind=reply_pending.map({True: "reply", False: "resolve"}),
                     deadline_state=df["sla_response"].where(reply_pending, df["sla_resolution"]))


def department_rows(df):
    """Per-team numbers (used by this report and the manager's overview)."""
    df = with_next_deadline(df)
    rows = []
    for department, group in (df.groupby("department") if len(df) else []):
        done = group[group["sla_resolution"].isin(["met", "missed"])]
        rows.append({
            "department": department,
            "complaints": len(group),
            "open": int(group["is_open"].sum()),
            "resolved_or_closed": int((~group["is_open"]).sum()),
            "escalated": int(group["escalated"].sum()),
            "sla_met_percent": round(100 * int((done["sla_resolution"] == "met").sum()) / len(done), 1) if len(done) else None,
            # late on whichever deadline comes next, so an unanswered customer counts too
            "sla_breached_open": int((group["is_open"] & (group["deadline_state"] == "breached")).sum()),
            "avg_resolution_hours": round(float(group["resolution_hours"].dropna().mean()), 1)
            if group["resolution_hours"].notna().any() else None,
            "avg_verification_score": round(float(group["verification_score"].dropna().mean()), 1)
            if group["verification_score"].notna().any() else None,
        })
    rows.sort(key=lambda r: -r["complaints"])
    return rows


def _records(frame):
    """DataFrame rows as dicts, with pandas' NaN (an empty value) turned into None - NaN is not valid JSON."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in row.items()}
            for row in frame.to_dict("records")]


def admin_dashboard(queryset):
    df = with_next_deadline(complaint_frame(queryset))
    total = len(df)
    at_risk = df[df["is_open"] & df["deadline_state"].isin(["at_risk", "breached"])] if total else df
    trends = detect_trends(df)
    return {
        "total_complaints": total,
        "open": int(df["is_open"].sum()) if total else 0,
        "category_distribution": distribution(df, "category"),
        "department_distribution": distribution(df, "department"),
        "priority_levels": distribution(df, "priority"),
        "sentiment_distribution": distribution(df, "sentiment"),
        "escalations": {
            "total": int(df["escalated"].sum()) if total else 0,
            "open": int((df["escalated"] & df["is_open"]).sum()) if total else 0,
            "by_level": distribution(df[df["escalated"]], "escalation_level") if total else [],
        },
        "resolution_status": distribution(df, "status"),
        "sla_risks": {
            "at_risk": int((at_risk["deadline_state"] == "at_risk").sum()) if total else 0,
            "breached": int((at_risk["deadline_state"] == "breached").sum()) if total else 0,
            # overdue first, then the oldest
            "most_urgent": _records(at_risk.assign(late=at_risk["deadline_state"] != "breached").sort_values(["late", "created_at"])[
                ["complaint_id", "title", "priority", "department", "assigned_to", "assigned_to_name", "sla_resolution", "deadline_kind",
                 "deadline_state"]
            ].head(10)) if total else [],
        },
        "teams": department_rows(df),
        "genai_python_mismatches": mismatch_summary(queryset),
        "manual_review": manual_review_summary(queryset),
        "trend_alerts": [t["message"] for key in ("rising", "recurring_product_issues", "repeated_service_failures",
                                                   "escalation_spikes") for t in trends[key]][:10],
    }
