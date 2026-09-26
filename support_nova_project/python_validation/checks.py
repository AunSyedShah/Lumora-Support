"""
Pipeline 2 - individual Python ground-truth checks.

Every check returns a dict:
    name      what was checked ("priority", "missing_required_action", ...)
    status    pass | fail | warning | info
    severity  critical | major | minor | none
    genai     what the GenAI pipeline said
    python    what the rule matrix / knowledge base says
    message   human-readable explanation (used as the "explanation of disagreement")

Two rule-engine results are used:
    independent  the rule engine classified the complaint itself (keywords) - the "Python expected category"
    genai_view   the rule engine evaluated for the subcategory GenAI chose - "given GenAI's own
                 classification, what do the rules require?"
"""

from catalog.models import PRIORITY_RANK, URGENCY_RANK
from knowledge_base.models import PolicyChunk, PolicyDocument
from rules.models import ESCALATION_RANK, EscalationLevel, ResolutionRule
from vector_search.embeddings import from_bytes

from . import text_checks

PASS, FAIL, WARNING, INFO = "pass", "fail", "warning", "info"
CRITICAL, MAJOR, MINOR, NONE = "critical", "major", "minor", "none"


def check(name, status, severity, genai, python, message):
    return {"name": name, "status": status, "severity": severity if status in (FAIL, WARNING) else NONE,
            "genai": genai, "python": python, "message": message}


def _rule_reason(view):
    """Short explanation of WHY the rules expect something (rule + fired escalation rules)."""
    parts = []
    if view.get("resolution_rule"):
        parts.append(f"rule {view['resolution_rule']}")
    parts += [f"{e['rule_id']} ({'; '.join(e['reasons'])})" for e in view.get("escalation_rules", [])]
    return ", ".join(parts) or "no matching rule"


# ---------------- classification ----------------


def classification_checks(out, independent):
    g_cat, g_sub = out["primary_issue"]["category"], out["primary_issue"]["subcategory"]
    p_cat, p_sub = independent.get("category"), independent.get("subcategory")
    kw = (independent.get("primary_issue") or {}).get("matched_keywords")

    if p_cat is None:
        return [check("category", WARNING, MAJOR, g_cat, None,
                      "The rule matrix could not classify this complaint independently (no subcategory keywords "
                      "matched), so GenAI's classification cannot be verified. The complaint may be ambiguous.")]
    results = []
    if g_cat == p_cat:
        results.append(check("category", PASS, NONE, g_cat, p_cat, "GenAI and rules agree on the category."))
        if g_sub == p_sub:
            results.append(check("subcategory", PASS, NONE, g_sub, p_sub, "GenAI and rules agree on the subcategory."))
        else:
            results.append(check("subcategory", FAIL, MAJOR, g_sub, p_sub,
                                 f"Same category, different subcategory. Rules chose {p_sub} from keywords {kw}."))
    else:
        g_secondary = {i["category"] for i in out.get("secondary_issues", [])}
        p_secondary = {i["category"] for i in independent.get("secondary_issues", [])}
        swapped = p_cat in g_secondary or g_cat in p_secondary
        results.append(check(
            "category", FAIL, MAJOR if swapped else CRITICAL, g_cat, p_cat,
            f"GenAI chose {g_cat}/{g_sub}; rules chose {p_cat}/{p_sub} from keywords {kw}."
            + (" Both found the same issues but ranked them differently (primary vs secondary)." if swapped else ""),
        ))

    g_all = {g_sub} | {i["subcategory"] for i in out.get("secondary_issues", [])}
    p_all = {p_sub} | {i["subcategory"] for i in independent.get("secondary_issues", [])}
    if p_all - g_all:
        results.append(check("secondary_issues", WARNING, MINOR, sorted(g_all), sorted(p_all),
                             f"Rules also detected {sorted(p_all - g_all)} which GenAI did not report."))
    return results


# ---------------- routing, urgency, priority ----------------


def routing_checks(out, view):
    expected = view.get("department")
    if not expected:
        return []
    results = []
    if out["department"] == expected:
        results.append(check("department", PASS, NONE, out["department"], expected, "Department matches the routing rules."))
    else:
        results.append(check("department", FAIL, MAJOR, out["department"], expected,
                             f"Routing rules send {out['primary_issue']['subcategory']} to {expected} ({_rule_reason(view)})."))
    missing = set(view.get("supporting_departments", [])) - set(out.get("supporting_departments", [])) - {out["department"]}
    if missing:
        results.append(check("supporting_departments", WARNING, MINOR, out.get("supporting_departments", []),
                             view.get("supporting_departments", []),
                             f"Rules also involve {sorted(missing)}."))
    return results


def _level_check(name, genai, expected, ranks, reason, critical_value):
    if expected is None:
        return check(name, INFO, NONE, genai, None, f"No rule-based {name} available.")
    diff = ranks[expected] - ranks[genai]  # > 0: GenAI is LESS severe than the rules
    if diff == 0:
        return check(name, PASS, NONE, genai, expected, f"{name.capitalize()} matches the rule matrix.")
    if diff > 0:
        severity = CRITICAL if diff >= 2 or expected == critical_value else MAJOR
        return check(name, FAIL, severity, genai, expected,
                     f"GenAI {name} {genai} is below the rule-matrix {name} {expected} ({reason}). Enforced.")
    return check(name, WARNING, MINOR if diff == -1 else MAJOR, genai, expected,
                 f"GenAI {name} {genai} is higher than the rule-matrix {name} {expected} ({reason}).")


def urgency_priority_checks(out, view):
    reason = _rule_reason(view)
    return [
        _level_check("urgency", out["urgency"], view.get("urgency"), URGENCY_RANK, reason, "Critical"),
        _level_check("priority", out["priority"], view.get("priority"), PRIORITY_RANK, reason, "P0"),
    ]


# ---------------- escalation ----------------


def expected_escalation(independent, view):
    """Mandatory escalation = the most serious level either rule view requires."""
    levels = [independent.get("escalation_level") or "none", view.get("escalation_level") or "none"]
    return max(levels, key=lambda l: ESCALATION_RANK[l])


def escalation_checks(out, independent, view):
    expected = expected_escalation(independent, view)
    genai = out["escalation_level"]
    fired = {e["rule_id"]: e for e in independent.get("escalation_rules", []) + view.get("escalation_rules", [])}
    reason = "; ".join(f"{r} {e['name']}" for r, e in fired.items()) or _rule_reason(view)
    diff = ESCALATION_RANK[expected] - ESCALATION_RANK[genai]
    if diff == 0:
        return [check("escalation", PASS, NONE, genai, expected, "Escalation matches the rules.")]
    if expected != EscalationLevel.NONE and genai == EscalationLevel.NONE:
        return [check("escalation", FAIL, CRITICAL, genai, expected,
                      f"Mandatory escalation missed by GenAI: {reason}. Escalation enforced by Python rules.")]
    if diff > 0:
        return [check("escalation", FAIL, MAJOR, genai, expected,
                      f"GenAI escalation level is lower than required ({reason}). Enforced.")]
    return [check("escalation", WARNING, MINOR, genai, expected,
                  "GenAI escalated further than the rules require (allowed, noted for review).")]


# ---------------- compensation, follow-up, missing information ----------------


def compensation_checks(out, view):
    offered = out["compensation"]["type"]
    allowed = view.get("allowed_compensation") or ["none"]
    if offered in allowed or offered == "none":
        results = [check("compensation", PASS, NONE, offered, allowed, "Compensation is permitted by the rules.")]
        extra = set(allowed) - {"none", offered}
        if offered == "none" and extra and view.get("rule_decided", True):
            results.append(check("compensation_not_offered", WARNING, MINOR, offered, allowed,
                                 f"The rules allow {sorted(extra)} which GenAI did not offer."))
        return results
    return [check("compensation", FAIL, CRITICAL, offered, allowed,
                  f"'{offered}' is not permitted for this case ({_rule_reason(view)}). Removed from the final resolution.")]


def follow_up_checks(out, view):
    required, days = view.get("follow_up_required"), view.get("follow_up_days")
    genai = out["follow_up"]
    if required and not genai["required"]:
        return [check("follow_up", FAIL, MAJOR, False, f"required within {days} days",
                      "The rules require a follow-up but GenAI did not schedule one. Enforced.")]
    if required and genai["days"] > days:
        return [check("follow_up", WARNING, MINOR, f"{genai['days']} days", f"{days} days",
                      "GenAI follow-up is later than the rule's follow-up period. Enforced.")]
    return [check("follow_up", PASS, NONE, genai["required"], required, "Follow-up requirement satisfied.")]


def missing_information_checks(out, independent):
    missing = independent.get("missing_facts", [])
    if missing and not out.get("clarification_questions"):
        return [check("clarification", WARNING, MINOR, [], missing,
                      f"Rules need {missing} to decide eligibility, but GenAI asked no clarification questions.")]
    return []


# ---------------- policy grounding ----------------


RELATED_SECTION_SIMILARITY = 0.6


def _related_policy_ids(categories):
    """Policies the rule matrix uses anywhere in these categories."""
    return set(ResolutionRule.objects.filter(category__code__in=categories, is_active=True).values_list("policy_id", flat=True))


def _section_similarity(document, section, complaint_vector):
    chunk = document.chunks.filter(section=section).first() if section else document.chunks.first()
    if chunk is None or chunk.embedding is None or complaint_vector is None:
        return 0.0
    return float(from_bytes(chunk.embedding) @ complaint_vector)


def _applicability(ref, view, categories, related_ids, complaint_vector):
    """
    SRS Step 26: Applicable / Conditionally Applicable / Not Applicable / Outdated.
      applicable               the policy the rule matrix designates for this case
      conditionally applicable the document's category matches, OR a rule in this category cites it,
                               OR the cited section is semantically close to the complaint
      not applicable           none of the above, or the policy / section does not exist
      outdated                 only non-active versions exist / section only in an older version
    """
    documents = list(PolicyDocument.objects.filter(doc_id=ref["policy_id"]).select_related("category"))
    if not documents:
        return "not_applicable", "No such policy exists (possible hallucination)."
    usable = [d for d in documents if d.is_usable]
    if not usable:
        return "outdated", "Only draft, previous, superseded or expired versions of this policy exist."
    doc = usable[0]
    if ref.get("section") and not doc.chunks.filter(section=ref["section"]).exists():
        older = PolicyChunk.objects.filter(document__doc_id=doc.doc_id, section=ref["section"]).exclude(document=doc)
        if older.exists():
            return "outdated", f"Section {ref['section']} only exists in an older version of {doc.doc_id}."
        return "not_applicable", f"Section {ref['section']} does not exist in {doc.doc_id} v{doc.version}."
    if ref["policy_id"] == view.get("policy_id"):
        return "applicable", "This is the policy the rule matrix uses for this case."
    if doc.category is None or doc.category.code in categories:
        return "conditionally_applicable", "Related policy, but not the one the rule matrix designates."
    if doc.doc_id in related_ids:
        return "conditionally_applicable", "The rule matrix uses this policy for other cases in this category."
    similarity = _section_similarity(doc, ref.get("section"), complaint_vector)
    if similarity >= RELATED_SECTION_SIMILARITY:
        return "conditionally_applicable", f"Section is semantically related to the complaint ({similarity:.2f})."
    return "not_applicable", f"{doc.doc_id} covers {doc.category.code} and the section is unrelated ({similarity:.2f})."


def policy_checks(out, view, independent, analysis, complaint_vector=None):
    results = []
    refs = out.get("policy_references", [])
    categories = {out["primary_issue"]["category"], independent.get("category")} | {
        i["category"] for i in out.get("secondary_issues", [])
    }
    categories.discard(None)
    related_ids = _related_policy_ids(categories)

    assessed = []
    for ref in refs:
        status, why = _applicability(ref, view, categories, related_ids, complaint_vector)
        assessed.append((f"{ref['policy_id']} {ref.get('section') or ''}".strip(), status, why))
    statuses = [status for _, status, _ in assessed]
    has_support = any(s in ("applicable", "conditionally_applicable") for s in statuses)
    for label, status, why in assessed:
        if status == "applicable":
            results.append(check("policy_applicability", PASS, NONE, label, status, why))
        elif status == "conditionally_applicable":
            results.append(check("policy_applicability", INFO, NONE, label, status, why))
        else:
            # An extra irrelevant citation matters less when the resolution is otherwise well supported.
            results.append(check("policy_applicability", FAIL, MINOR if has_support else MAJOR, label, status, why))

    if not has_support:
        results.append(check("policy_support", FAIL, MAJOR, [r["policy_id"] for r in refs], view.get("policy_id"),
                             "No applicable approved policy supports this resolution."))
    elif view.get("policy_id") and view["policy_id"] not in {r["policy_id"] for r in refs}:
        results.append(check("policy_support", WARNING, MINOR, [r["policy_id"] for r in refs],
                             f"{view['policy_id']} {view.get('policy_section', '')}".strip(),
                             "GenAI did not cite the policy the rule matrix designates for this case."))

    # Precedence: the resolution leans on lower-precedence documents (SOP / FAQ) but does not cite the
    # governing document the rule matrix designates. (For some areas, e.g. tech support, the governing
    # document IS an SOP - so precedence is measured against the designated document, not "a policy".)
    cited_ids = {r["policy_id"] for r in refs}
    cited_usable = [d for d in PolicyDocument.objects.filter(doc_id__in=cited_ids) if d.is_usable]
    governing = next((d for d in PolicyDocument.objects.filter(doc_id=view.get("policy_id")) if d.is_usable), None)
    if governing and governing.doc_id not in cited_ids:
        lower = sorted({d.doc_id for d in cited_usable if d.precedence > governing.precedence})
        if lower and not any(d.precedence <= governing.precedence for d in cited_usable):
            results.append(check("policy_precedence", FAIL, MAJOR, lower, governing.doc_id,
                                 f"Resolution relies on lower-precedence document(s) {lower} instead of the governing "
                                 f"{governing.doc_id} ({governing.get_doc_type_display()}). Higher precedence wins."))

    # Policy version: has a cited policy been revised since the analysis ran? (hidden policy update)
    for doc_id, version in (analysis.policy_versions or {}).items():
        current = PolicyDocument.objects.filter(doc_id=doc_id, status="active").first()
        if current and current.version != version:
            results.append(check("policy_version", FAIL, MAJOR, f"{doc_id} v{version}", f"{doc_id} v{current.version}",
                                 "The analysis used a policy version that has since been replaced. Re-run the analysis."))

    for issue in analysis.validation_issues or []:
        if issue["type"] in ("unknown_policy", "unknown_section", "chunk_not_provided"):
            results.append(check("hallucinated_reference", FAIL, MAJOR, issue["reference"], None, issue["detail"]))
    return results


# ---------------- actions, promises, hallucinations ----------------


def action_checks(out, view):
    results = []
    steps = out.get("resolution_steps", [])
    required = view.get("required_actions", [])
    missing = text_checks.missing_required_actions(required, steps)
    for action, sim in missing:
        results.append(check("missing_required_action", FAIL, MINOR, None, action,
                             f"Mandatory action not found in GenAI steps (best similarity {sim}). Added to the final resolution."))
    if required and len(missing) > len(required) / 2:
        results.append(check("required_actions", FAIL, MAJOR, len(required) - len(missing), len(required),
                             "Most mandatory actions for this rule are missing."))

    texts = steps + [out["customer_response"]["text"], out["follow_up"]["message"]]
    for action, sentence, sim in text_checks.prohibited_action_hits(view.get("prohibited_actions", []), texts):
        results.append(check("prohibited_action", FAIL, CRITICAL, sentence, action,
                             f"Output appears to perform a prohibited action (similarity {sim})."))
    return results


def promise_and_fact_checks(out, view, complaint, policy_texts):
    results = []
    response = out["customer_response"]["text"]
    outgoing = f"{response}\n{out['follow_up']['message']}"
    for kind, excerpt, why in text_checks.unsupported_promises(
        outgoing, view.get("allowed_compensation"), view.get("rule_decided", True), policy_texts
    ):
        severity = MINOR if kind == "unsupported_timeline" else CRITICAL
        results.append(check("unsupported_promise", FAIL, severity, excerpt, kind, why))

    known_refs = {complaint.complaint_id}
    if complaint.order:
        known_refs.add(complaint.order.order_ref)
    known_refs |= set(complaint.customer.complaints.values_list("complaint_id", flat=True))
    known_refs |= set(complaint.customer.orders.values_list("order_ref", flat=True))
    known_amounts = {float(complaint.order.amount)} if complaint.order else set()
    source = f"{complaint.title}\n{complaint.description}\n{complaint.supporting_information}\n" + "\n".join(policy_texts)
    for kind, value, why in text_checks.untraceable_facts(outgoing + "\n" + " ".join(out["resolution_steps"]),
                                                          source, known_refs, known_amounts):
        results.append(check("hallucinated_fact", FAIL, CRITICAL, value, None, why))
    return results


# ---------------- internal consistency ----------------


def consistency_checks(out):
    """Contradictory instructions inside the GenAI output itself."""
    results = []
    if out["urgency"] == "Critical" and not out["escalation_required"]:
        results.append(check("consistency", FAIL, MAJOR, "Critical urgency, no escalation", None,
                             "A critical complaint is not escalated."))
    if out["priority"] == "P0" and out["urgency"] in ("Low", "Medium"):
        results.append(check("consistency", FAIL, MINOR, f"P0 with {out['urgency']} urgency", None,
                             "Priority and urgency contradict each other."))
    if out["compensation"]["type"] == "none" and text_checks.promises_refund(out["customer_response"]["text"]):
        results.append(check("consistency", FAIL, MAJOR, "compensation none, response promises refund", None,
                             "The customer response promises a refund that the structured result does not include."))
    if out.get("missing_information") and not out.get("clarification_questions"):
        results.append(check("consistency", WARNING, MINOR, out["missing_information"], None,
                             "Missing information listed but no clarification question asked."))
    return results
