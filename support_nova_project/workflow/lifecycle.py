"""
Complaint status lifecycle (SRS Step 60) and SLA tracking (Steps 55-56).

Allowed transitions are listed explicitly: anything not in the table is refused, so a complaint
cannot jump from "new" to "closed" or be "resolved" twice.

SLA: due dates = clock start + the hours in the SLARule for the complaint's priority
     + time spent waiting for the customer (SLA-POL 2.1: that time is not counted).
     The clock starts at submission and restarts when a complaint is reopened.
     A complaint with no priority yet uses settings.DEFAULT_SLA_PRIORITY.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from catalog.models import SLARule
from complaints.models import Complaint

S = Complaint.Status

TRANSITIONS = {
    S.NEW: {S.ANALYZED, S.ASSIGNED, S.ESCALATED, S.CLOSED},
    S.ANALYZED: {S.ASSIGNED, S.IN_PROGRESS, S.AWAITING_CUSTOMER, S.ESCALATED, S.RESOLVED, S.CLOSED},
    S.ASSIGNED: {S.IN_PROGRESS, S.AWAITING_CUSTOMER, S.ESCALATED, S.RESOLVED},
    S.IN_PROGRESS: {S.AWAITING_CUSTOMER, S.ESCALATED, S.RESOLVED},
    S.AWAITING_CUSTOMER: {S.IN_PROGRESS, S.ESCALATED, S.RESOLVED, S.CLOSED},
    S.ESCALATED: {S.ASSIGNED, S.IN_PROGRESS, S.AWAITING_CUSTOMER, S.RESOLVED},
    S.RESOLVED: {S.CLOSED, S.REOPENED},
    S.CLOSED: {S.REOPENED},
    S.REOPENED: {S.ASSIGNED, S.IN_PROGRESS, S.AWAITING_CUSTOMER, S.ESCALATED, S.RESOLVED},
}


class TransitionError(Exception):
    pass


def can_move(current, target):
    return target in TRANSITIONS.get(current, set())


def apply_status(complaint, target, now=None):
    """Change status in memory (caller saves), keeping SLA pause and timestamps correct."""
    now = now or timezone.now()
    if complaint.status == target:
        return
    if not can_move(complaint.status, target):
        allowed = sorted(TRANSITIONS.get(complaint.status, set()))
        raise TransitionError(f"Cannot change status from '{complaint.status}' to '{target}'. Allowed: {allowed}")

    # Leaving "awaiting customer": that waiting time is added to the SLA clock (not counted).
    if complaint.status == S.AWAITING_CUSTOMER and complaint.awaiting_since:
        paused = int((now - complaint.awaiting_since).total_seconds())
        complaint.sla_paused_seconds += max(paused, 0)
        complaint.awaiting_since = None
        set_sla_due_dates(complaint)
    if target == S.AWAITING_CUSTOMER:
        complaint.awaiting_since = now
    if target == S.RESOLVED:
        complaint.resolved_at = now
    if target == S.CLOSED:
        complaint.closed_at = now
    if target == S.REOPENED:
        # A reopened complaint is new work: the resolution clock starts again.
        complaint.resolved_at = complaint.closed_at = None
        complaint.sla_clock_start = now
        complaint.sla_paused_seconds = 0
        set_sla_due_dates(complaint)
    complaint.status = target


# ---------------- SLA ----------------


def _clock_start(complaint):
    return complaint.sla_clock_start or complaint.created_at


def _rule(complaint, rules=None):
    """SLA rule for the complaint's priority. `rules` = optional {priority: SLARule} cache for bulk use."""
    priority = complaint.priority or settings.DEFAULT_SLA_PRIORITY
    if rules is not None:
        return rules.get(priority)
    return SLARule.objects.filter(priority=priority).first()


def set_sla_due_dates(complaint):
    rule = _rule(complaint)
    if rule is None:
        complaint.sla_response_due = complaint.sla_resolution_due = None
        return
    paused = timedelta(seconds=complaint.sla_paused_seconds)
    complaint.sla_response_due = complaint.created_at + timedelta(hours=rule.response_hours)
    complaint.sla_resolution_due = _clock_start(complaint) + timedelta(hours=rule.resolution_hours) + paused


def _state(start, due, done_at, now, at_risk_percent):
    if due is None:
        return "not_set"
    if done_at:
        return "met" if done_at <= due else "missed"
    if now > due:
        return "breached"
    total = (due - start).total_seconds()
    elapsed = (now - start).total_seconds()
    return "at_risk" if total > 0 and elapsed >= total * at_risk_percent / 100 else "on_track"


def sla_status(complaint, now=None, rules=None):
    """{"response": state, "resolution": state, ...} where state is on_track/at_risk/breached/met/missed/not_set."""
    now = now or timezone.now()
    rule = _rule(complaint, rules)
    at_risk = rule.at_risk_percent if rule else 75
    # While waiting for the customer the resolution clock is paused, so measure up to when it paused.
    clock = complaint.awaiting_since or now
    # Closing a complaint (e.g. customer never replied) also ends the resolution clock.
    finished = complaint.resolved_at or complaint.closed_at
    return {
        "response": _state(complaint.created_at, complaint.sla_response_due, complaint.first_response_at, now, at_risk),
        "resolution": _state(_clock_start(complaint), complaint.sla_resolution_due, finished, clock, at_risk),
        "response_due": complaint.sla_response_due,
        "resolution_due": complaint.sla_resolution_due,
        "paused": complaint.status == S.AWAITING_CUSTOMER,
    }
