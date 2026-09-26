"""
Step 4 of the dataset: score the system against the expected labels.

Three views of every complaint are compared with the answer key:
  python  Pipeline 2 alone: the rule engine classifying the complaint text itself (no GenAI)
  genai   Pipeline 1 alone: the latest GenAI analysis
  final   what the system finally decided (after validation and rule enforcement)
Plus intake checks: duplicate / repeat linking, prompt-injection flags, and whether the cases that
need a human were sent to manual review.
"""

from collections import Counter, defaultdict

from complaints.facts import rule_facts
from genai_pipeline.models import GenAIAnalysis
from rules.engine import evaluate

FIELDS = ("category", "subcategory", "department", "urgency", "priority", "escalation")
VIEWS = ("python", "genai", "final")


def python_view(complaint):
    view = evaluate(rule_facts(complaint))  # classifies the text itself - independent of GenAI
    return {"category": view["category"], "subcategory": view["subcategory"], "department": view["department"],
            "urgency": view["urgency"], "priority": view["priority"], "escalation": view["escalation_level"],
            "review": view["needs_manual_review"]}


def genai_view(complaint):
    analysis = (GenAIAnalysis.objects.filter(complaint=complaint, output__isnull=False)
                .exclude(output={}).order_by("-created_at").first())
    if analysis is None:
        return None
    out = analysis.output
    primary = out.get("primary_issue") or {}
    return {"category": primary.get("category"), "subcategory": primary.get("subcategory"),
            "department": out.get("department"), "urgency": out.get("urgency"), "priority": out.get("priority"),
            "escalation": out.get("escalation_level"), "manipulation_detected": out.get("manipulation_detected")}


def final_view(complaint):
    if complaint.verification_status == complaint.Verification.PENDING:
        return None
    return {"category": complaint.category.code if complaint.category else None,
            "subcategory": complaint.subcategory.code if complaint.subcategory else None,
            "department": complaint.department.code if complaint.department else None,
            "urgency": complaint.urgency, "priority": complaint.priority,
            "escalation": complaint.escalation_level or "none",
            "review": complaint.verification_status == complaint.Verification.MANUAL_REVIEW}


def chain_complaint_ids(spec, by_id, cases):
    ids, current = set(), spec
    while current.related_to:
        current = by_id[current.related_to]
        case = cases.get(current.case_id)
        if case and case.complaint_id:
            ids.add(case.complaint_id)
    return ids


def evaluate_case(spec, case, by_id, cases, views):
    complaint = case.complaint
    expected = spec.expected
    row = {"case_id": spec.case_id, "complaint_id": complaint.complaint_id, "split": spec.split, "group": spec.group,
           "case_types": " | ".join(spec.case_types), "review_expected": expected["review_required"]}
    for field in FIELDS:
        row[f"expected_{field}"] = expected[field]
    scored = [f for f in FIELDS if expected[f]]  # ambiguous cases have no expected category
    for name in views:
        view = {"python": python_view, "genai": genai_view, "final": final_view}[name](complaint)
        for field in FIELDS:
            row[f"{name}_{field}"] = view.get(field) if view else None
        row[f"{name}_correct"] = (sum(view.get(f) == expected[f] for f in scored) if view else None)
        row[f"{name}_all_correct"] = (all(view.get(f) == expected[f] for f in scored) if view and scored else None)
        if name == "final" and view:
            row["final_review"] = view["review"]
        if name == "genai" and view:
            row["genai_manipulation_detected"] = view["manipulation_detected"]
    row["scored_fields"] = len(scored)

    # intake: injection flags and duplicate / repeat links
    row["security_flags"] = " | ".join(f["flag"] for f in complaint.security_flags)
    row["match_expected"] = {"near_duplicate": "near_duplicate", "repeat": "repeat"}.get(spec.group, "")
    row["match_actual"] = complaint.match_type
    links = {complaint.related_complaint_id, complaint.previous_complaint_id} - {None}
    if spec.related_to:
        row["link_correct"] = bool(links & chain_complaint_ids(spec, by_id, cases))
    else:
        row["link_correct"] = not complaint.match_type  # an unrelated complaint must not be linked
    row["fact_mismatches"] = " | ".join(case.fact_mismatches)
    return row


def _rate(values):
    values = [v for v in values if v is not None]
    return round(100 * sum(values) / len(values), 1) if values else None


def summarize(rows, views):
    summary = {"complaints": len(rows), "accuracy_percent": {}, "by_group": {}, "intake": {}, "review": {}}
    for name in views:
        per_field = {}
        for field in FIELDS:
            pairs = [(r[f"{name}_{field}"], r[f"expected_{field}"]) for r in rows
                     if r[f"expected_{field}"] and r.get(f"{name}_correct") is not None]
            per_field[field] = _rate([got == want for got, want in pairs])
        per_field["all_fields"] = _rate([r[f"{name}_all_correct"] for r in rows])
        summary["accuracy_percent"][name] = per_field

    groups = defaultdict(list)
    for row in rows:
        groups[row["group"]].append(row)
    main = "final" if "final" in views else "python"
    for group, group_rows in sorted(groups.items()):
        summary["by_group"][group] = {
            "complaints": len(group_rows),
            f"{main}_all_fields_percent": _rate([r[f"{main}_all_correct"] for r in group_rows]),
            f"{main}_priority_percent": _rate([r[f"{main}_priority"] == r["expected_priority"]
                                               for r in group_rows if r["expected_priority"]]),
            f"{main}_escalation_percent": _rate([r[f"{main}_escalation"] == r["expected_escalation"]
                                                 for r in group_rows if r["expected_escalation"]]),
        }

    injection = [r for r in rows if r["group"] == "prompt_injection"]
    linked = [r for r in rows if r["match_expected"]]
    unlinked = [r for r in rows if not r["match_expected"]]
    summary["intake"] = {
        "injection_cases": len(injection),
        "injection_flagged_at_intake": sum(bool(r["security_flags"]) for r in injection),
        "injection_detected_by_genai": sum(bool(r.get("genai_manipulation_detected")) for r in injection),
        "false_injection_flags": sum(bool(r["security_flags"]) for r in rows if r["group"] != "prompt_injection"),
        "repeat_or_duplicate_cases": len(linked),
        "linked_to_the_right_complaint": sum(r["link_correct"] for r in linked),
        "match_type_correct": sum(r["match_actual"] == r["match_expected"] for r in linked),
        "unrelated_complaints_wrongly_linked": sum(not r["link_correct"] for r in unlinked),
        "fact_mismatches": sum(bool(r["fact_mismatches"]) for r in rows),
    }
    if "final" in views:
        done = [r for r in rows if r.get("final_review") is not None]
        need = [r for r in done if r["review_expected"]]
        rest = [r for r in done if not r["review_expected"]]
        # A review is justified when the complaint needs a person anyway, or when the GenAI got a
        # label wrong (catching that is the point of Pipeline 2). It is unnecessary when the GenAI
        # was completely right on a complaint that did not need a person.
        genai_wrong = [r for r in done if r.get("genai_all_correct") is False]
        summary["review"] = {
            "sent_to_review_percent": _rate([r["final_review"] for r in done]),
            "needed_review": len(need),
            "sent_to_review": sum(r["final_review"] for r in need),
            "review_recall_percent": _rate([r["final_review"] for r in need]),
            "other_complaints_sent_to_review_percent": _rate([r["final_review"] for r in rest]),
            "genai_was_wrong": len(genai_wrong),
            "genai_errors_caught_by_review_percent": _rate([r["final_review"] for r in genai_wrong]),
            "genai_errors_missed_and_final_wrong": sum(not r["final_review"] and r.get("final_all_correct") is False
                                                       for r in genai_wrong),
            "unnecessary_reviews": sum(r["final_review"] for r in rest if r.get("genai_all_correct") is True),
            "by_group_percent": {g: _rate([r["final_review"] for r in rs if r.get("final_review") is not None])
                                 for g, rs in sorted(groups.items())},
        }
    summary["confusions"] = {
        f"{main}_priority": Counter(f"{r['expected_priority']}->{r[f'{main}_priority']}" for r in rows
                                    if r["expected_priority"] and r[f"{main}_priority"] != r["expected_priority"]).most_common(8),
        f"{main}_subcategory": Counter(f"{r['expected_subcategory']}->{r[f'{main}_subcategory']}" for r in rows
                                       if r["expected_subcategory"] and r[f"{main}_subcategory"] != r["expected_subcategory"]).most_common(8),
    }
    return summary
