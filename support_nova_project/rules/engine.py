"""
Deterministic rule engine: turns complaint facts into the rule-matrix EXPECTED result.

No GenAI is used here. The steps:
  1. classify   - keyword-match the text against every active subcategory's keywords
  2. choose     - for each detected issue, pick the most specific ResolutionRule whose conditions hold
  3. order      - the most serious issue becomes primary, the others are secondary issues
                 (a fallback or overridden subcategory is never primary when a better match exists)
  4. escalate   - apply EVERY matching EscalationRule (highest level wins, urgency/priority raised)
  5. combine    - final department, supporting departments, urgency, priority, escalation, actions
Every decision is recorded in `explanations` so disagreements with GenAI can be explained.
"""

from dataclasses import dataclass, field

from catalog.models import PRIORITY_RANK, URGENCY_RANK, Subcategory

from .conditions import Facts, evaluate_conditions, find_phrases, first_position, normalize_text
from .models import ESCALATION_RANK, EscalationLevel, EscalationRule, ResolutionRule


@dataclass
class Issue:
    subcategory: Subcategory
    score: int  # number of keyword hits (0 when the subcategory was given, not detected)
    matched_keywords: list[str]
    position: int  # where in the text the issue is first mentioned
    rule: ResolutionRule | None = None
    rule_decided: bool = False  # False = rule was a best guess because facts were missing
    rule_reasons: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)

    @property
    def severity(self):
        return PRIORITY_RANK[self.rule.priority] if self.rule else -1


# ---------------- 1. classification ----------------


def classify(normalized_text):
    """Return one Issue per subcategory whose keywords appear in the text, best match first."""
    issues = []
    for sub in Subcategory.objects.filter(is_active=True, category__is_active=True).select_related("category"):
        hits = find_phrases(sub.keywords, normalized_text)
        if hits:
            issues.append(Issue(sub, len(hits), hits, first_position(hits, normalized_text)))
    issues.sort(key=lambda i: (-i.score, i.position))
    return issues


# ---------------- 2. rule selection ----------------


def _specificity(rule):
    return len(rule.conditions)


def choose_rule(issue, facts, normalized_text):
    """
    Most specific matching rule wins (more conditions = more specific); ties go to the more
    severe priority, then the lower rule_id. Rules that could not be decided because a fact is
    unknown are reported in `missing_facts` (they might apply if the customer tells us more).
    If nothing matches at all, the best undecided rule is used as a guess (-> manual review).
    """
    rules = (
        ResolutionRule.objects.filter(subcategory=issue.subcategory, is_active=True)
        .select_related("department", "category", "subcategory")
        .prefetch_related("supporting_departments")
    )
    matched, undecided = [], []
    for rule in rules:
        result = evaluate_conditions(rule.conditions, facts, normalized_text)
        if result.matched:
            matched.append((rule, result))
        elif result.missing_facts:
            undecided.append((rule, result))

    def rank(pair):
        rule = pair[0]
        return (-_specificity(rule), -PRIORITY_RANK[rule.priority], rule.rule_id)

    issue.missing_facts = sorted({f for _, r in undecided for f in r.missing_facts})
    if matched:
        rule, result = sorted(matched, key=rank)[0]
        issue.rule, issue.rule_reasons, issue.rule_decided = rule, result.reasons, True
    elif undecided:
        rule, result = sorted(undecided, key=rank)[0]
        issue.rule, issue.rule_reasons = rule, result.reasons


# ---------------- 3. overlapping subcategories ----------------


def _demoted(issues):
    """
    Issues that must not be the primary one although they matched (they stay secondary issues):
      - a fallback subcategory when a more specific issue was found ("I complained before and it is
        still not fixed" + a late order -> the late order; the earlier complaints are counted anyway)
      - a subcategory another matched subcategory takes precedence over (firmware failure > malfunction)
    Returns {code: reason}.
    """
    codes = {i.subcategory.code for i in issues}
    demoted = {}
    for issue in issues:
        sub = issue.subcategory
        winners = [c for c in codes if sub.code in _precedence(issues, c)]
        if winners:
            demoted[sub.code] = f"{winners[0]} takes precedence over it"
        elif sub.is_fallback and len(codes) > 1:
            demoted[sub.code] = "a more specific issue was found"
    if len(demoted) == len(codes):  # everything demoted: keep the normal order
        return {}
    return demoted


def _precedence(issues, code):
    return next(i.subcategory.takes_precedence_over for i in issues if i.subcategory.code == code)


# ---------------- 4. escalation ----------------


def matching_escalations(facts, normalized_text):
    fired = []
    for rule in EscalationRule.objects.filter(is_active=True).select_related("target_department"):
        result = evaluate_conditions(rule.conditions, facts, normalized_text)
        if result.matched:
            fired.append((rule, result.reasons))
    return fired


def _max_by_rank(values, ranks):
    values = [v for v in values if v]
    return max(values, key=lambda v: ranks[v]) if values else None


# ---------------- main entry point ----------------


def evaluate(facts: Facts, subcategory_code: str | list | None = None) -> dict:
    """subcategory_code: None = classify the text; a code or a list of codes = check those issues."""
    text = normalize_text(facts.text)
    explanations = []

    # 1. classification (or use the subcategories we were told to check)
    if subcategory_code:
        codes = [subcategory_code] if isinstance(subcategory_code, str) else list(subcategory_code)
        by_code = Subcategory.objects.select_related("category").in_bulk(codes, field_name="code")
        issues = [Issue(by_code[code], 0, [], position) for position, code in enumerate(codes) if code in by_code]
        method = "given" if issues else "unknown_subcategory"
    else:
        issues = classify(text)
        method = "keywords" if issues else "none"

    facts.categories = {i.subcategory.category.code for i in issues}
    facts.subcategories = {i.subcategory.code for i in issues}

    # 2. + 3. choose a rule per issue, then put the most serious issue first
    for issue in issues:
        choose_rule(issue, facts, text)
    demoted = _demoted(issues)
    issues.sort(key=lambda i: (i.subcategory.code in demoted, -i.severity, -i.score, i.position))
    primary, secondary = (issues[0], issues[1:]) if issues else (None, [])
    for code, reason in demoted.items():
        explanations.append(f"{code} is not the primary issue: {reason}.")

    if primary:
        explanations.append(
            f"Primary issue {primary.subcategory.code} (keywords: {primary.matched_keywords or 'given'})."
        )
        for s in secondary:
            explanations.append(f"Secondary issue {s.subcategory.code} (keywords: {s.matched_keywords}).")
    else:
        explanations.append("No subcategory keywords matched; category could not be determined by rules.")

    rule = primary.rule if primary else None
    if primary and rule is None:
        explanations.append(f"No active resolution rule exists for {primary.subcategory.code}.")
    if rule:
        explanations.append(f"Resolution rule {rule.rule_id} applies ({'; '.join(primary.rule_reasons) or 'no conditions'}).")

    # 4. escalation rules
    fired = matching_escalations(facts, text)
    for esc, reasons in fired:
        explanations.append(f"Escalation rule {esc.rule_id} '{esc.name}' fired ({'; '.join(reasons)}).")

    # 5. combine
    urgency = _max_by_rank([rule.urgency if rule else None] + [e.min_urgency for e, _ in fired], URGENCY_RANK)
    priority = _max_by_rank([rule.priority if rule else None] + [e.min_priority for e, _ in fired], PRIORITY_RANK)
    escalation_level = _max_by_rank(
        [rule.escalation_level if rule else EscalationLevel.NONE] + [e.escalation_level for e, _ in fired],
        ESCALATION_RANK,
    )

    department = rule.department.code if rule else (primary.subcategory.routed_department.code if primary else None)
    if department is None and fired:  # unclassified but e.g. a safety keyword fired
        department = next((e.target_department.code for e, _ in fired if e.target_department), None)

    supporting = []
    if rule:
        supporting += [d.code for d in rule.supporting_departments.all()]
    for s in secondary:
        supporting.append(s.rule.department.code if s.rule else s.subcategory.routed_department.code)
    supporting += [e.target_department.code for e, _ in fired if e.target_department]
    supporting = [d for d in dict.fromkeys(supporting) if d != department]

    missing_facts = primary.missing_facts if primary else []
    if missing_facts:
        explanations.append(f"More specific rules may apply if these facts were known: {missing_facts}.")
    if rule and not primary.rule_decided:
        explanations.append(f"{rule.rule_id} is only a best guess: no rule fully matched the known facts.")

    def issue_dict(i):
        return {
            "category": i.subcategory.category.code,
            "subcategory": i.subcategory.code,
            "score": i.score,
            "matched_keywords": i.matched_keywords,
            "rule_id": i.rule.rule_id if i.rule else None,
        }

    return {
        "classification_method": method,
        "primary_issue": issue_dict(primary) if primary else None,
        "secondary_issues": [issue_dict(s) for s in secondary],
        "category": primary.subcategory.category.code if primary else None,
        "subcategory": primary.subcategory.code if primary else None,
        "department": department,
        "supporting_departments": supporting,
        "urgency": urgency,
        "priority": priority,
        "escalation_level": escalation_level,
        "escalation_required": escalation_level != EscalationLevel.NONE,
        "resolution_rule": rule.rule_id if rule else None,
        "policy_id": rule.policy_id if rule else None,
        "policy_section": rule.policy_section if rule else None,
        "required_actions": rule.required_actions if rule else [],
        "prohibited_actions": rule.prohibited_actions if rule else [],
        "allowed_compensation": rule.allowed_compensation if rule else [],
        "follow_up_required": rule.follow_up_required if rule else False,
        "follow_up_days": rule.follow_up_days if rule else 0,
        "escalation_rules": [
            {"rule_id": e.rule_id, "name": e.name, "level": e.escalation_level, "reasons": r,
             "target_department": e.target_department.code if e.target_department else None}
            for e, r in fired
        ],
        "missing_facts": missing_facts,
        "rule_decided": bool(primary and primary.rule_decided),
        "needs_manual_review": primary is None or rule is None or not primary.rule_decided,
        "explanations": explanations,
    }
