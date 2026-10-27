"""
Administrator actions on the second-look rules: show them, preview a change on real complaints, save a new version,
roll back. See review_policy.py for what can be set and the limits.
"""

from django.db import transaction

from catalog.models import Category
from complaint_dataset.csv_io import read_specs
from complaint_dataset.models import DatasetCase
from rules.models import EscalationLevel

from . import review_policy as rp
from .models import ReviewPolicy, ValidationResult

EXAMPLES = 6


def category_codes():
    return set(Category.objects.values_list("code", flat=True))


def _author(row):
    return row.created_by.display_name if row.created_by_id else None


def _row(row):
    return {"version": row.version, "settings": rp.merged(row.config), "comment": row.comment, "is_active": row.is_active,
            "created_by_name": _author(row), "created_at": row.created_at}


def state():
    version, active = rp.current()
    history = [_row(r) for r in ReviewPolicy.objects.select_related("created_by")[:20]]
    row = next((h for h in history if h["version"] == version), None)
    labels = dict(EscalationLevel.choices)
    return {
        "active": row or {"version": 0, "settings": active, "comment": "Built-in defaults (nothing has been changed yet).", "is_active": True,
                          "created_by_name": None, "created_at": None},
        "defaults": rp.defaults(),
        "bounds": {"score_threshold": list(rp.BOUNDS["score_threshold"]), "penalty": list(rp.BOUNDS["penalty"])},
        "always_on": rp.ALWAYS_ON,
        "triggers": [{"key": k, "label": v} for k, v in rp.TRIGGERS.items()],
        "optional_sensitive_levels": [{"value": v, "label": labels[v]} for v in rp.OPTIONAL_SENSITIVE],
        "corrected_by_rules": list(rp.CORRECTED_BY_RULES),
        "categories": [{"code": c.code, "name": c.name} for c in Category.objects.filter(is_active=True)],
        "history": history,
    }


def _latest_results():
    latest = {}
    for result in ValidationResult.objects.select_related("complaint__category", "analysis").order_by("-created_at"):
        latest.setdefault(result.complaint_id, result)
    return list(latest.values())


def _should_review():
    """Complaint ids of sample-dataset cases whose correct outcome is a second look (ambiguous, injection, incomplete ...)."""
    try:
        expected = {spec.case_id: spec.expected.get("review_required") for spec in read_specs()}
    except OSError:
        return set()
    return {d.complaint_id for d in DatasetCase.objects.exclude(complaint=None) if expected.get(d.case_id)}


def preview(candidate):
    """What the candidate settings would have decided for every complaint checked so far, next to what is in use now."""
    from reports.dashboards import reason_type

    _, now = rp.current()
    policy = rp.clean(candidate, category_codes())
    results = _latest_results()
    should = _should_review()
    before = {r.complaint_id: rp.reasons_for(r, now) for r in results}
    after = {r.complaint_id: rp.reasons_for(r, policy) for r in results}
    by_id = {r.complaint_id: r for r in results}

    def example(pk, reasons):
        c = by_id[pk].complaint
        return {"complaint_id": c.complaint_id, "title": c.title, "reasons": reasons[pk][:2]}

    dropped = [pk for pk in before if before[pk] and not after[pk]]
    added = [pk for pk in before if after[pk] and not before[pk]]
    reasons_after = {}
    for pk, texts in after.items():
        for kind in {reason_type(t) for t in texts}:
            reasons_after[kind] = reasons_after.get(kind, 0) + 1
    return {
        "checked": len(results),
        "review_now": sum(bool(v) for v in before.values()),
        "review_after": sum(bool(v) for v in after.values()),
        "no_longer_review": len(dropped),
        "newly_review": len(added),
        "dropped_examples": [example(pk, before) for pk in dropped[:EXAMPLES]],
        "added_examples": [example(pk, after) for pk in added[:EXAMPLES]],
        "reasons_after": reasons_after,
        # The safety figure: cases that SHOULD go to a person (known from the sample dataset) and still do.
        "must_review": len(should & set(before)),
        "must_review_caught_now": sum(bool(before[pk]) for pk in should if pk in before),
        "must_review_caught_after": sum(bool(after[pk]) for pk in should if pk in after),
        "settings": policy,
    }


def _next_version():
    last = ReviewPolicy.objects.order_by("-version").first()
    return (last.version if last else 0) + 1


def _activate(config, comment, user):
    with transaction.atomic():
        ReviewPolicy.objects.filter(is_active=True).update(is_active=False)
        return ReviewPolicy.objects.create(version=_next_version(), config=config, comment=comment, is_active=True, created_by=user)


def _comment(text):
    text = (text or "").strip()
    if len(text) < 5:
        raise rp.ReviewPolicyError(["Please say why you are changing this (at least 5 characters). It is kept with the version."])
    return text[:300]


def save(candidate, comment, user):
    comment = _comment(comment)
    policy = rp.clean(candidate, category_codes())
    if policy == rp.current()[1]:
        raise rp.ReviewPolicyError(["Nothing is different from the rules in use now."])
    return _activate(policy, comment, user)


def rollback(version, comment, user):
    """Make an earlier version the rules in use again. It is saved as a new version, so the history only grows."""
    comment = _comment(comment)
    if version == 0:
        config = rp.defaults()
    else:
        row = ReviewPolicy.objects.filter(version=version).first()
        if row is None:
            raise rp.ReviewPolicyError([f"There is no version {version}."])
        config = rp.merged(row.config)
    if config == rp.current()[1]:
        raise rp.ReviewPolicyError(["Those are already the rules in use."])
    return _activate(config, f"Back to version {version}: {comment}"[:300], user)
