"""
The second-look rules an administrator can set: how the verification score is worked out, which triggers send a
complaint to a person, and which problem types always go to one.

Safety net (never configurable): a possible manipulation attempt, a sensitive case, a complaint the rules cannot
classify (or cannot decide because facts are missing), a case no policy covers, a forbidden action / invented fact /
unsupported promise in the suggested reply, and a failed AI answer ALWAYS go to a person. The administrator can only
tune the rest, inside the limits below.

A change is a NEW VERSION (older ones are never edited) and every validation result records the version it was
decided with, so a past decision can always be explained and rolled back.
"""

from django.conf import settings
from rules.models import EscalationLevel

# What the system always does, shown to the administrator next to the settings.
ALWAYS_ON = [
    "A message that tries to give the system instructions (manipulation)",
    "Safety, security and privacy cases (compliance review or critical-management escalation)",
    "A complaint the rules cannot classify, or cannot decide because facts are missing",
    "No active policy supports the plan",
    "A forbidden action, an invented fact or reference, or a promise a policy does not back",
    "The AI could not produce a usable answer",
]
SENSITIVE_ALWAYS = (EscalationLevel.COMPLIANCE_REVIEW.value, EscalationLevel.CRITICAL_MANAGEMENT.value)
OPTIONAL_SENSITIVE = tuple(v for v in EscalationLevel.values if v not in SENSITIVE_ALWAYS and v != EscalationLevel.NONE.value)
TRIGGERS = {
    "low_score": "The verification score is below the cutoff",
    "policy_contradiction": "A lower-ranked or older document was used instead of the governing policy",
}
BOUNDS = {"score_threshold": (50, 95), "penalty": (0, 50)}
# Critical findings the rules fix by themselves in the final plan (escalation is never lower than the rules, disallowed
# compensation is removed, urgency and priority follow the rule matrix when the rule was decided on facts).
CORRECTED_BY_RULES = ("escalation", "compensation", "urgency", "priority")


class ReviewPolicyError(ValueError):
    def __init__(self, problems):
        super().__init__(" ".join(problems))
        self.problems = problems


def defaults():
    """Today's behaviour. The score cutoff starts from VALIDATION_REVIEW_SCORE so existing installations do not change."""
    return {
        "score_threshold": int(settings.VALIDATION_REVIEW_SCORE),
        "penalty": {"critical": 25, "major": 10, "minor": 3},
        "triggers": {name: True for name in TRIGGERS},
        "sensitive_levels": list(SENSITIVE_ALWAYS),
        "ignore_corrected_criticals": False,
        "always_review_categories": [],
    }


def merged(data):
    """Saved settings laid over the defaults (so a setting added later still has a value)."""
    base = defaults()
    data = data or {}
    for key, value in data.items():
        base[key] = {**base[key], **value} if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return base


def clean(data, category_codes=()):
    """Check administrator input and return a complete settings dict, or raise ReviewPolicyError in plain words."""
    problems = []
    known = set(defaults())
    unknown = sorted(set(data) - known)
    if unknown:
        problems.append(f"Unknown settings: {', '.join(unknown)}.")
    s = merged({k: v for k, v in data.items() if k in known})

    low, high = BOUNDS["score_threshold"]
    if not isinstance(s["score_threshold"], int) or isinstance(s["score_threshold"], bool) or not low <= s["score_threshold"] <= high:
        problems.append(f"The score cutoff must be a whole number from {low} to {high}.")

    low, high = BOUNDS["penalty"]
    weights = s["penalty"]
    if set(weights) != {"critical", "major", "minor"} or any(not isinstance(v, int) or isinstance(v, bool) or not low <= v <= high for v in weights.values()):
        problems.append(f"Each score weight must be a whole number from {low} to {high}.")
    elif not weights["critical"] >= weights["major"] >= weights["minor"]:
        problems.append("A critical finding must cost at least as much as a major one, and a major one at least as much as a minor one.")

    if set(s["triggers"]) != set(TRIGGERS) or any(not isinstance(v, bool) for v in s["triggers"].values()):
        problems.append("Triggers can only be switched on or off.")

    levels = s["sensitive_levels"]
    if not isinstance(levels, list) or not set(SENSITIVE_ALWAYS) <= set(levels) or not set(levels) <= set(SENSITIVE_ALWAYS) | set(OPTIONAL_SENSITIVE):
        problems.append("Compliance review and critical management always count as sensitive; the only other levels you can add are "
                        + ", ".join(v.replace("_", " ") for v in OPTIONAL_SENSITIVE) + ".")
    else:
        s["sensitive_levels"] = sorted(set(levels), key=EscalationLevel.values.index)

    if not isinstance(s["ignore_corrected_criticals"], bool):
        problems.append("The auto-corrected option can only be on or off.")

    categories = s["always_review_categories"]
    if not isinstance(categories, list) or any(c not in category_codes for c in categories):
        problems.append("Always-review problem types must be existing problem types.")
    else:
        s["always_review_categories"] = sorted(set(categories))

    if problems:
        raise ReviewPolicyError(problems)
    return s


def current():
    """(version, settings) in use. Version 0 means nobody has changed anything: the built-in defaults."""
    from .models import ReviewPolicy

    row = ReviewPolicy.objects.filter(is_active=True).order_by("-version").first()
    if row is None:
        return 0, defaults()
    return row.version, merged(row.config)


def reasons_for(result, policy):
    """The review reasons a stored validation result would get under `policy` (used by the preview)."""
    from .decision import review_reasons, score

    if not result.final_resolution:  # the AI failed: a person always decides
        return list(result.review_reasons)
    analysis = result.analysis
    out = analysis.output if analysis is not None and analysis.output else {}
    total = score(result.checks, policy["penalty"])
    escalation = result.final_resolution.get("escalation_level") or EscalationLevel.NONE.value
    return review_reasons(result.checks, total, result.independent_expected, result.genai_view_expected, escalation, result.complaint, out, policy)
