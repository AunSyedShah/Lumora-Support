"""
The one table every dashboard, analytic and report is built from.

`complaint_frame()` turns a (role-scoped, filtered) complaint queryset into a pandas DataFrame
with one row per complaint. Computing everything from the same frame keeps all numbers
consistent: the dashboard total, the analytics total and the report row count always agree.
"""

import pandas as pd
from django.utils import timezone

from catalog.models import SLARule
from complaints.models import Complaint
from complaints.permissions import visible_complaints
from python_validation.models import ValidationResult
from workflow.lifecycle import sla_status

COLUMNS = [
    "complaint_id", "title", "created_at", "date", "customer", "customer_type", "channel", "category", "subcategory",
    "product", "department", "assigned_to", "assigned_to_name", "priority", "urgency", "sentiment", "escalation_level", "escalated",
    "status", "is_open", "verification_status", "verification_score", "review_status", "match_type", "is_repeat",
    "previous_complaints", "resolution_hours", "sla_response", "sla_resolution", "response_sent",
    "has_security_flags", "policy_references", "resolution_rule",
]


def filtered_complaints(user, date_from=None, date_to=None, department=None, category=None,
                        priority=None, channel=None, sentiment=None):
    """Complaints this user may see (agents: own assignments), narrowed by the common report filters."""
    qs = visible_complaints(user)
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if department:
        qs = qs.filter(department__code=department.upper())
    if category:
        qs = qs.filter(category__code=category.upper())
    if priority:
        qs = qs.filter(priority=priority.upper())
    if channel:
        qs = qs.filter(channel=channel)
    if sentiment:
        qs = qs.filter(sentiment__iexact=sentiment)
    return qs


def complaint_frame(queryset, now=None):
    now = now or timezone.now()
    rules = {r.priority: r for r in SLARule.objects.all()}  # one query instead of one per complaint
    records = []
    for c in queryset.select_related("customer", "category", "subcategory", "product", "department", "assigned_to"):
        sla = sla_status(c, now=now, rules=rules)
        finished = c.resolved_at or c.closed_at
        escalated = (c.escalation_level or "none") != "none"
        records.append({
            "complaint_id": c.complaint_id,
            "title": c.title,
            "created_at": c.created_at,
            "date": timezone.localtime(c.created_at).date(),
            "customer": c.customer.username,
            "customer_type": c.customer_type,
            "channel": c.channel,
            "category": c.category.code if c.category else None,
            "subcategory": c.subcategory.code if c.subcategory else None,
            "product": c.product.name if c.product else None,
            "department": c.department.code if c.department else None,
            "assigned_to": c.assigned_to.username if c.assigned_to else None,
            "assigned_to_name": c.assigned_to.display_name if c.assigned_to else None,
            "priority": c.priority or None,
            "urgency": c.urgency or None,
            "sentiment": c.sentiment or None,
            "escalation_level": c.escalation_level or "none",
            "escalated": escalated,
            "status": c.status,
            "is_open": c.status in Complaint.OPEN_STATUSES,
            "verification_status": c.verification_status,
            "verification_score": c.verification_score,
            "review_status": c.review_status,
            "match_type": c.match_type or None,
            "is_repeat": bool(c.match_type) or (c.facts or {}).get("previous_complaints", 0) > 0,
            "previous_complaints": (c.facts or {}).get("previous_complaints", 0),
            "resolution_hours": round((finished - c.created_at).total_seconds() / 3600, 1) if finished else None,
            "sla_response": sla["response"],
            "sla_resolution": sla["resolution"],
            "response_sent": c.response_sent_at is not None,
            "has_security_flags": bool(c.security_flags),
            "policy_references": (c.resolution or {}).get("policy_references", []),
            "resolution_rule": (c.resolution or {}).get("resolution_rule"),
        })
    return pd.DataFrame(records, columns=COLUMNS)


def latest_validations(queryset):
    """The most recent ValidationResult for each complaint in the queryset."""
    latest = {}
    results = ValidationResult.objects.filter(complaint__in=queryset).select_related("complaint", "analysis")
    for result in results.order_by("-created_at"):
        latest.setdefault(result.complaint_id, result)
    return list(latest.values())
