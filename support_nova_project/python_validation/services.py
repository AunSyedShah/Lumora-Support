"""
Pipeline 2 entry points.

validate_analysis(analysis)   run every ground-truth check on one GenAI analysis
process_complaint(complaint)  Pipeline 1 + Pipeline 2 + comparison + decision in one call
"""

from complaints.facts import rule_facts
from complaints.models import Complaint
from genai_pipeline.models import GenAIAnalysis
from genai_pipeline.pipeline import analyze_complaint
from knowledge_base.models import PolicyChunk
from rules.engine import evaluate
from vector_search.embeddings import from_bytes

from . import checks as c
from .decision import agreement_rate, final_resolution, review_reasons, score
from .models import ValidationResult


def policy_texts_for(analysis, view):
    """Approved text the response may rely on: excerpts given to the model + the rule's policy."""
    chunk_ids = [ch["chunk_id"] for ch in (analysis.retrieved_chunks if analysis else None) or []]
    texts = list(PolicyChunk.objects.filter(chunk_id__in=chunk_ids).values_list("text", flat=True))
    if view.get("policy_id"):
        texts += list(PolicyChunk.objects.filter(
            document__doc_id=view["policy_id"], document__status="active"
        ).values_list("text", flat=True))
    texts += view.get("required_actions", [])  # e.g. "Reschedule within 3 business days"
    return texts


def _failed_result(complaint, analysis, independent):
    reason = f"GenAI output could not be produced or validated: {analysis.error if analysis else 'no analysis'}"
    return ValidationResult.objects.create(
        complaint=complaint, analysis=analysis, independent_expected=independent, genai_view_expected={},
        checks=[c.check("schema_validation", c.FAIL, c.CRITICAL, None, None, reason)],
        score=0, agreement_rate=0.0, decision=ValidationResult.Decision.MANUAL_REVIEW,
        review_reasons=[reason], final_resolution={},
    )


def validate_analysis(analysis: GenAIAnalysis):
    complaint = analysis.complaint
    facts = rule_facts(complaint)
    independent = evaluate(facts)  # Python's own classification
    if analysis.status != GenAIAnalysis.Status.SUCCESS or not analysis.output:
        return _failed_result(complaint, analysis, independent)

    out = analysis.output
    view = evaluate(rule_facts(complaint), subcategory_code=out["primary_issue"]["subcategory"])
    policy_texts = policy_texts_for(analysis, view)

    results = [c.check("schema_validation", c.PASS, c.NONE, "valid", "valid", "GenAI output passed JSON schema validation.")]
    results += c.classification_checks(out, independent)
    results += c.routing_checks(out, view)
    results += c.urgency_priority_checks(out, view)
    results += c.escalation_checks(out, independent, view)
    results += c.compensation_checks(out, view)
    results += c.follow_up_checks(out, view)
    results += c.missing_information_checks(out, independent)
    complaint_vector = from_bytes(complaint.embedding) if complaint.embedding else None
    results += c.policy_checks(out, view, independent, analysis, complaint_vector)
    results += c.action_checks(out, view)
    results += c.promise_and_fact_checks(out, view, complaint, policy_texts)
    results += c.consistency_checks(out)

    total = score(results)
    final = final_resolution(out, independent, view, results)
    reasons = review_reasons(results, total, independent, view, final["escalation_level"], complaint, out)
    return ValidationResult.objects.create(
        complaint=complaint,
        analysis=analysis,
        independent_expected=independent,
        genai_view_expected=view,
        checks=results,
        score=total,
        agreement_rate=agreement_rate(results),
        decision=ValidationResult.Decision.MANUAL_REVIEW if reasons else ValidationResult.Decision.VERIFIED,
        review_reasons=reasons,
        final_resolution=final,
    )


def process_complaint(complaint: Complaint, tone=None, requested_by=None, reuse_analysis=False):
    """
    Pipeline 1 + Pipeline 2. With reuse_analysis=True the latest successful GenAI analysis is
    re-validated instead of calling the model again. Routing / status changes are done by the
    workflow app (workflow.services.process_and_apply), not here.
    """
    analysis = None
    if reuse_analysis:
        analysis = complaint.genai_analyses.filter(status=GenAIAnalysis.Status.SUCCESS).first()
    if analysis is None:
        analysis = analyze_complaint(complaint, tone=tone, requested_by=requested_by)
    return validate_analysis(analysis)


def check_outgoing_response(complaint, text):
    """
    Re-check ANY text about to be sent to the customer - AI-written, edited or written by a human -
    for unsupported promises, prohibited actions and invented references (SRS Steps 34-35).
    Returns the blocking findings (critical / major); an empty list means it is safe to send.
    """
    latest = complaint.validations.select_related("analysis").first()
    view = (latest.genai_view_expected or latest.independent_expected) if latest else {}
    if not view:
        view = evaluate(rule_facts(complaint))
    out = {
        "customer_response": {"text": text},
        "follow_up": {"message": ""},
        "resolution_steps": [],
    }
    findings = c.promise_and_fact_checks(out, view, complaint, policy_texts_for(latest.analysis if latest else None, view))
    findings += [f for f in c.action_checks(out, view) if f["name"] == "prohibited_action"]
    return [f for f in findings if f["severity"] in (c.CRITICAL, c.MAJOR)]
