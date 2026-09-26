"""GenAI vs Python comparison rows (SRS deliverable 8), shared by the API and the reports app."""

from .checks import expected_escalation

COMPARED = ("category", "subcategory", "department", "urgency", "priority", "escalation")


def comparison_row(result):
    out = result.analysis.output if result.analysis and result.analysis.output else {}
    ind, view = result.independent_expected, result.genai_view_expected
    primary = out.get("primary_issue", {})
    # Any difference counts as a mismatch in the report, including "GenAI was stricter" warnings.
    failed = [c for c in result.checks if c["name"] in COMPARED and c["status"] in ("fail", "warning")]
    return {
        "complaint_id": result.complaint.complaint_id,
        "genai_category": primary.get("category"),
        "python_category": ind.get("category"),
        "genai_subcategory": primary.get("subcategory"),
        "python_subcategory": ind.get("subcategory"),
        "genai_department": out.get("department"),
        "python_department": view.get("department") or ind.get("department"),
        "genai_urgency": out.get("urgency"),
        "python_urgency": view.get("urgency") or ind.get("urgency"),
        "genai_priority": out.get("priority"),
        "python_priority": view.get("priority") or ind.get("priority"),
        "genai_escalation": out.get("escalation_level"),
        "python_escalation": expected_escalation(ind, view) if view else ind.get("escalation_level"),
        "policy_reference": ", ".join(result.final_resolution.get("policy_references", [])) or None,
        "match": "mismatch" if failed else "match",
        "mismatched_fields": [c["name"] for c in failed],
        "verification_status": result.decision,
        "score": result.score,
        "explanation": " | ".join(c["message"] for c in failed) or "GenAI and Python agree on all compared fields.",
    }
