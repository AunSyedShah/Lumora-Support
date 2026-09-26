"""
Report definitions (SRS Step 67 + deliverable 9). Every report returns the same shape:

    Report(title, description, columns, rows, summary)

so any report can be exported to CSV, Excel or PDF by the same code (export.py).
"""

from collections import Counter
from dataclasses import dataclass, field

from complaints.models import Complaint
from python_validation.comparison import comparison_row

from .analytics import analytics
from .dashboards import manual_review_summary, mismatch_summary, reason_type
from .data import complaint_frame, latest_validations


@dataclass
class Report:
    title: str
    description: str
    columns: list
    rows: list
    summary: dict = field(default_factory=dict)
    pdf_columns: list | None = None  # wide reports: the key columns that fit on a PDF page


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else 0.0


# ---------------- 1. complaint analysis ----------------

def complaint_analysis(qs):
    df = complaint_frame(qs)
    columns = ["complaint_id", "date", "customer_type", "channel", "category", "subcategory", "product", "department",
               "priority", "urgency", "sentiment", "escalation_level", "status", "verification_status",
               "verification_score", "is_repeat", "sla_resolution", "resolution_hours"]
    rows = df.sort_values("created_at")[columns].to_dict("records") if len(df) else []
    a = analytics(df)
    report = Report("Complaint Analysis", "Every complaint with its classification, priority, status and outcome.", columns, rows, {
        "total": a.get("total", 0),
        "open": a.get("open", 0),
        "escalation_rate_percent": a.get("escalations", {}).get("rate_percent"),
        "average_verification_score": a.get("verification", {}).get("average_score"),
        "median_resolution_hours": a.get("resolution_time", {}).get("median_hours"),
    })
    report.pdf_columns = ["complaint_id", "date", "category", "subcategory", "department", "priority", "sentiment",
                          "escalation_level", "status", "verification_status", "sla_resolution"]
    return report


# ---------------- 2. department performance ----------------

def department_performance(qs):
    df = complaint_frame(qs)
    rows = []
    for department, group in (df.groupby("department") if len(df) else []):
        done = group[group["sla_resolution"].isin(["met", "missed"])]
        rows.append({
            "department": department,
            "complaints": len(group),
            "open": int(group["is_open"].sum()),
            "resolved_or_closed": int((~group["is_open"]).sum()),
            "escalated": int(group["escalated"].sum()),
            "sla_met_percent": _pct(int((done["sla_resolution"] == "met").sum()), len(done)) if len(done) else None,
            "sla_breached_open": int((group["is_open"] & (group["sla_resolution"] == "breached")).sum()),
            "avg_resolution_hours": round(float(group["resolution_hours"].dropna().mean()), 1)
            if group["resolution_hours"].notna().any() else None,
            "avg_verification_score": round(float(group["verification_score"].dropna().mean()), 1)
            if group["verification_score"].notna().any() else None,
        })
    rows.sort(key=lambda r: -r["complaints"])
    columns = list(rows[0]) if rows else ["department", "complaints"]
    return Report("Department Performance", "Volume, SLA and resolution performance per department.", columns, rows,
                  {"departments": len(rows)})


# ---------------- 3. escalations ----------------

def escalations(qs):
    escalated = qs.exclude(escalation_level__in=["", "none"]).select_related("department", "assigned_to", "category")
    rows = [{
        "complaint_id": c.complaint_id,
        "created": c.created_at.strftime("%Y-%m-%d %H:%M"),
        "category": c.category.code if c.category else None,
        "escalation_level": c.escalation_level,
        "escalation_rules": ", ".join((c.resolution or {}).get("escalation_rules", [])),
        "department": c.department.code if c.department else None,
        "owner": c.assigned_to.username if c.assigned_to else None,
        "priority": c.priority,
        "status": c.status,
    } for c in escalated.order_by("-created_at")]
    levels = Counter(r["escalation_level"] for r in rows)
    columns = ["complaint_id", "created", "category", "escalation_level", "escalation_rules", "department", "owner",
               "priority", "status"]
    return Report("Escalations", "Escalated complaints, the level and the rules that triggered them.", columns, rows,
                  {"escalated": len(rows), "by_level": dict(levels),
                   "without_owner": sum(r["owner"] is None for r in rows)})


# ---------------- 4. SLA status ----------------

def sla_report(qs):
    df = complaint_frame(qs)
    columns = ["complaint_id", "priority", "department", "assigned_to", "status", "sla_response", "sla_resolution"]
    rows = df.sort_values("created_at")[columns].to_dict("records") if len(df) else []
    counts = Counter(r["sla_resolution"] for r in rows)
    finished = counts["met"] + counts["missed"]
    return Report("SLA Status", "Response and resolution SLA state of every complaint.", columns, rows, {
        "on_track": counts["on_track"], "at_risk": counts["at_risk"], "breached": counts["breached"],
        "met": counts["met"], "missed": counts["missed"], "met_percent_of_finished": _pct(counts["met"], finished),
    })


# ---------------- 5. policy usage ----------------

def policy_usage(qs):
    documents, sections = Counter(), Counter()
    for resolution in qs.values_list("resolution", flat=True):
        for ref in (resolution or {}).get("policy_references", []):
            documents[ref.split()[0]] += 1
            sections[ref] += 1
    rows = [{"policy_reference": ref, "policy_id": ref.split()[0], "times_cited": n} for ref, n in sections.most_common()]
    return Report("Policy Usage", "How often each approved policy section grounds a final resolution.",
                  ["policy_reference", "policy_id", "times_cited"], rows, {"by_document": dict(documents.most_common())})


# ---------------- 6. resolution compliance ----------------

def resolution_compliance(qs):
    rows = []
    for result in latest_validations(qs):
        checks = result.checks
        def count(name):
            return sum(1 for c in checks if c["name"] == name and c["status"] in ("fail", "warning"))
        issues = {
            "missing_required_actions": count("missing_required_action"),
            "prohibited_actions": count("prohibited_action"),
            "unsupported_promises": count("unsupported_promise"),
            "disallowed_compensation": count("compensation"),
            "hallucinated_facts": count("hallucinated_fact") + count("hallucinated_reference"),
        }
        rows.append({
            "complaint_id": result.complaint.complaint_id,
            "resolution_rule": (result.genai_view_expected or {}).get("resolution_rule"),
            **issues,
            "rules_enforced": len((result.final_resolution or {}).get("enforced", [])),
            "compliant": not any(issues.values()),
            "score": result.score,
        })
    rows.sort(key=lambda r: r["complaint_id"])
    compliant = sum(r["compliant"] for r in rows)
    columns = list(rows[0]) if rows else ["complaint_id", "compliant"]
    return Report("Resolution Compliance", "Did the GenAI resolution follow the rule matrix? (latest validation)",
                  columns, rows, {"validated": len(rows), "fully_compliant": compliant,
                                  "compliance_percent": _pct(compliant, len(rows))})


# ---------------- 7. GenAI / Python comparison ----------------

def genai_python_comparison(qs):
    rows = sorted((comparison_row(r) for r in latest_validations(qs)), key=lambda r: r["complaint_id"])
    for row in rows:
        row["mismatched_fields"] = ", ".join(row["mismatched_fields"])
    columns = list(rows[0]) if rows else ["complaint_id", "match"]
    return Report("GenAI vs Python Comparison", "Pipeline 1 (GenAI) against Pipeline 2 (Python rules), field by field.",
                  columns, rows, mismatch_summary(qs),
                  pdf_columns=["complaint_id", "genai_category", "python_category", "genai_priority", "python_priority",
                               "genai_escalation", "python_escalation", "match", "verification_status", "score",
                               "explanation"])


# ---------------- 8. manual reviews ----------------

def manual_reviews(qs):
    reviewed = qs.exclude(review_status=Complaint.Review.NOT_REQUIRED)
    latest = {r.complaint_id: r for r in latest_validations(reviewed)}
    rows = []
    for c in reviewed.select_related("assigned_to").order_by("-created_at"):
        validation = latest.get(c.pk)
        reasons = validation.review_reasons if validation else []
        decision = c.audit_log.filter(action__in=["approved", "rejected"]).select_related("actor").last()
        rows.append({
            "complaint_id": c.complaint_id,
            "review_status": c.review_status,
            "reason_types": ", ".join(sorted({reason_type(r) for r in reasons})),
            "reasons": " | ".join(reasons),
            "score": c.verification_score,
            "reviewer": decision.actor.username if decision and decision.actor else None,
            "decided_at": decision.created_at.strftime("%Y-%m-%d %H:%M") if decision else None,
        })
    columns = ["complaint_id", "review_status", "reason_types", "reasons", "score", "reviewer", "decided_at"]
    return Report("Manual Reviews", "Complaints sent to human review, why, and the reviewer's decision.", columns, rows,
                  manual_review_summary(qs))


# ---------------- 9. complaint intelligence (deliverable 9) ----------------

def complaint_intelligence(qs):
    df = complaint_frame(qs)
    a = analytics(df)
    rows = []
    for section, key in (("Category", "by_category"), ("Priority", "by_priority"), ("Sentiment", "by_sentiment"),
                         ("Department routing", "by_department"), ("SLA (resolution)", None)):
        items = a["sla"]["resolution"] if key is None and a.get("total") else a.get(key, [])
        rows += [{"section": section, "value": i["value"], "count": i["count"], "percent": i["percent"]} for i in items]
    total = a.get("total", 0)
    if total:
        for level in a["escalations"]["by_level"]:
            rows.append({"section": "Escalations", "value": level["level"], "count": level["count"],
                         "percent": _pct(level["count"], total)})
        rows.append({"section": "Repeat complaints", "value": "repeat or near-duplicate",
                     "count": a["repeat_complaints"]["count"], "percent": a["repeat_complaints"]["rate_percent"]})
    for ref in policy_usage(qs).rows[:10]:
        rows.append({"section": "Policy usage", "value": ref["policy_reference"], "count": ref["times_cited"], "percent": None})
    mismatches = mismatch_summary(qs)
    for fld, n in mismatches["by_field"].items():
        rows.append({"section": "GenAI/Python disagreements", "value": fld, "count": n,
                     "percent": _pct(n, mismatches["validated"])})
    for kind, n in manual_review_summary(qs)["by_reason"].items():
        rows.append({"section": "Manual review reasons", "value": kind, "count": n, "percent": None})
    return Report("Complaint Intelligence Report", "Distributions, routing, escalations, repeats, SLA risk, policy usage, "
                  "GenAI/Python disagreements and manual reviews.", ["section", "value", "count", "percent"], rows,
                  {"total_complaints": total, "agreement_rate_percent": mismatches["agreement_rate_percent"]})


REPORTS = {
    "complaint_analysis": complaint_analysis,
    "department_performance": department_performance,
    "escalations": escalations,
    "sla_status": sla_report,
    "policy_usage": policy_usage,
    "resolution_compliance": resolution_compliance,
    "genai_python_comparison": genai_python_comparison,
    "manual_reviews": manual_reviews,
    "complaint_intelligence": complaint_intelligence,
}
