"""
Comparison engine: verification score, Verified / Manual Review decision, final resolution.

Score (not a model's self-reported confidence - it is calculated from the checks):
    100 - 25 per critical - 10 per major - 3 per minor finding, never below 0.

Manual review (SRS Step 57) when ANY of:
    - a critical finding (e.g. missed escalation, unsupported promise, disallowed compensation)
    - score below settings.VALIDATION_REVIEW_SCORE
    - the rules could not classify the complaint / only guessed the rule (ambiguous, missing facts)
    - no applicable policy supports the resolution
    - sensitive case (compliance review or critical-management escalation)
    - possible manipulation attempt (intake flags or GenAI detected it)

The final resolution starts from the GenAI output and ENFORCES the rules (NFR 4):
priority / urgency follow the rule matrix (so tone cannot move them), escalation is never lower
than the rules, department follows the routing rules, missing mandatory actions are added,
disallowed compensation is removed.
"""

from django.conf import settings

from catalog.models import PRIORITY_RANK, URGENCY_RANK
from rules.models import ESCALATION_RANK, EscalationLevel

from .checks import CRITICAL, FAIL, MAJOR, MINOR, WARNING, expected_escalation

PENALTY = {CRITICAL: 25, MAJOR: 10, MINOR: 3}
COMPARED_FIELDS = ("category", "subcategory", "department", "urgency", "priority", "escalation", "compensation", "follow_up")
SENSITIVE_LEVELS = {EscalationLevel.COMPLIANCE_REVIEW, EscalationLevel.CRITICAL_MANAGEMENT}


def score(checks):
    penalty = sum(PENALTY.get(c["severity"], 0) for c in checks if c["status"] in (FAIL, WARNING))
    return max(0, 100 - penalty)


def agreement_rate(checks):
    compared = [c for c in checks if c["name"] in COMPARED_FIELDS and c["status"] != "info"]
    if not compared:
        return 0.0
    return round(sum(c["status"] == "pass" for c in compared) / len(compared), 3)


def review_reasons(checks, total, independent, view, final_escalation, complaint, out):
    reasons = []
    for c in checks:
        if c["status"] == FAIL and c["severity"] == CRITICAL:
            reasons.append(f"Critical finding ({c['name']}): {c['message']}")
    if total < settings.VALIDATION_REVIEW_SCORE:
        reasons.append(f"Verification score {total} is below {settings.VALIDATION_REVIEW_SCORE}.")
    if independent.get("category") is None:
        reasons.append("Complaint is ambiguous: the rule matrix could not classify it.")
    elif not view.get("rule_decided", True):
        reasons.append(f"Eligibility unclear: facts {view.get('missing_facts')} are missing.")
    if any(c["name"] == "policy_support" and c["status"] == FAIL for c in checks):
        reasons.append("Policy support is missing.")
    if any(c["name"] == "policy_precedence" for c in checks):
        reasons.append("Policy contradiction: lower-precedence document used instead of the governing policy.")
    if final_escalation in SENSITIVE_LEVELS:
        reasons.append(f"Sensitive complaint ({final_escalation.replace('_', ' ')}) requires human review.")
    if complaint.security_flags or out.get("manipulation_detected"):
        reasons.append("Possible manipulation / prompt-injection attempt in the complaint.")
    return list(dict.fromkeys(reasons))


def _max_rank(a, b, ranks):
    if not b:
        return a
    return a if ranks[a] >= ranks[b] else b


def final_resolution(out, independent, view, checks):
    """GenAI result with the rule matrix enforced on top. Each enforced field says so in `enforced`."""
    enforced = []
    final = {
        "category": out["primary_issue"]["category"],
        "subcategory": out["primary_issue"]["subcategory"],
        "secondary_issues": [i["subcategory"] for i in out.get("secondary_issues", [])],
        "summary": out["complaint_summary"],
    }

    department = view.get("department") or out["department"]
    if department != out["department"]:
        enforced.append(f"department {out['department']} -> {department} (routing rules)")
    final["department"] = department
    final["supporting_departments"] = sorted(
        (set(out.get("supporting_departments", [])) | set(view.get("supporting_departments", []))
         | ({out["department"]} if department != out["department"] else set())) - {department}
    )

    # Urgency / priority come from the rules (they already include every escalation trigger), so the
    # customer's tone cannot raise or lower them. Only when the rule was a guess (facts missing) is the
    # more cautious of the two values kept.
    for field, ranks in (("urgency", URGENCY_RANK), ("priority", PRIORITY_RANK)):
        rule_value = view.get(field)
        if rule_value and view.get("rule_decided", False):
            value = rule_value
        else:
            value = _max_rank(out[field], rule_value, ranks)
        if value != out[field]:
            enforced.append(f"{field} {out[field]} -> {value} (rule matrix)")
        final[field] = value

    required_level = expected_escalation(independent, view)
    level = out["escalation_level"] if ESCALATION_RANK[out["escalation_level"]] >= ESCALATION_RANK[required_level] else required_level
    if level != out["escalation_level"]:
        enforced.append(f"escalation {out['escalation_level']} -> {level} (mandatory escalation rules)")
    final["escalation_level"] = level
    final["escalation_required"] = level != EscalationLevel.NONE

    # Critical routing (NFR 4): if the GenAI MISSED a mandatory escalation, the department named by
    # the strongest escalation rule (e.g. Product Safety for a safety hazard) takes ownership.
    if out["escalation_level"] == EscalationLevel.NONE and level != EscalationLevel.NONE:
        fired = independent.get("escalation_rules", []) + view.get("escalation_rules", [])
        targeted = [e for e in fired if e.get("target_department")]
        if targeted:
            strongest = max(targeted, key=lambda e: ESCALATION_RANK[e["level"]])
            target = strongest["target_department"]
            if target != final["department"]:
                enforced.append(f"department {final['department']} -> {target} ({strongest['rule_id']} {strongest['name']})")
                final["supporting_departments"] = sorted(
                    (set(final["supporting_departments"]) | {final["department"]}) - {target}
                )
                final["department"] = target
    final["escalation_rules"] = sorted({e["rule_id"] for e in independent.get("escalation_rules", []) + view.get("escalation_rules", [])})
    final["escalation_notes"] = out.get("escalation_notes")

    steps = list(out.get("resolution_steps", []))
    for c in checks:
        if c["name"] == "missing_required_action":
            steps.append(f"[Required by {view.get('resolution_rule')}] {c['python']}")
            enforced.append(f"added required action: {c['python']}")
    final["resolution_steps"] = steps
    final["prohibited_actions"] = view.get("prohibited_actions", [])

    compensation = dict(out["compensation"])
    if any(c["name"] == "compensation" and c["status"] == FAIL for c in checks):
        enforced.append(f"compensation {compensation['type']} removed (not permitted)")
        compensation = {"type": "none", "justification": "Removed by rule validation: not permitted for this case.",
                        "policy_id": None, "section": None}
    final["compensation"] = compensation

    follow_up = dict(out["follow_up"])
    if view.get("follow_up_required"):
        if not follow_up["required"] or follow_up["days"] > view["follow_up_days"]:
            enforced.append(f"follow-up within {view['follow_up_days']} days (rule)")
        follow_up["required"] = True
        follow_up["days"] = min(follow_up["days"] or view["follow_up_days"], view["follow_up_days"])
    final["follow_up"] = follow_up

    applicable = [c["genai"] for c in checks if c["name"] == "policy_applicability" and c["python"] in ("applicable", "conditionally_applicable")]
    rule_ref = f"{view.get('policy_id')} {view.get('policy_section') or ''}".strip() if view.get("policy_id") else None
    if rule_ref and rule_ref not in applicable:
        applicable.append(rule_ref)
    final["policy_references"] = applicable
    final["resolution_rule"] = view.get("resolution_rule")

    unsafe = [c for c in checks if c["name"] in ("unsupported_promise", "hallucinated_fact", "prohibited_action")
              and c["severity"] in (CRITICAL, MAJOR)]
    final["customer_response"] = out["customer_response"]
    final["response_requires_rewrite"] = bool(unsafe)
    final["clarification_questions"] = out.get("clarification_questions", [])
    final["agent_guidance"] = out.get("agent_guidance", [])
    final["enforced"] = enforced
    return final
