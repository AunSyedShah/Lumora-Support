"""
Pipeline 2 + comparison API.

POST /process/{complaint_id}   GenAI analysis -> Python validation -> comparison -> decision (one call)
POST /validate/{analysis_id}    re-validate an existing GenAI analysis (e.g. after a rule or policy change)
GET  /comparison                 GenAI vs Python comparison report (JSON or CSV)
"""

import csv
import io

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from complaints.models import Complaint
from complaints.permissions import FULL_ACCESS_ROLES, get_visible_complaint, visible_complaints
from genai_pipeline.models import GenAIAnalysis
from genai_pipeline.output_schema import Tone
from genai_pipeline.prompts import PromptError

from . import review_admin, review_policy
from .comparison import comparison_row
from .models import ValidationResult
from .schemas import (
    ComparisonRowOut,
    ReviewPolicyIn,
    ReviewPolicyRollbackIn,
    ReviewPolicyStateOut,
    ReviewPreviewOut,
    ValidationDetailOut,
    ValidationOut,
)
from workflow.services import WorkflowError, process_and_apply

from .services import validate_analysis

router = Router(tags=["Validation & Comparison"])



def _results():
    return ValidationResult.objects.select_related("complaint", "analysis")


@router.post("/process/{complaint_id}", response={200: ValidationOut, 409: ErrorOut, 503: ErrorOut})
def process(request, complaint_id: str, tone: Tone | None = None, reuse_analysis: bool = False):
    """
    Run the full pipeline for a complaint and route it: verified -> assigned / escalated,
    manual review -> review queue. reuse_analysis=true skips the GenAI call if a valid analysis exists.
    """
    require_role(request, *STAFF_ROLES)
    complaint = get_visible_complaint(request.auth, complaint_id)
    try:
        return process_and_apply(complaint, tone=tone, actor=request.auth, reuse_analysis=reuse_analysis)
    except WorkflowError as e:
        raise HttpError(e.status_code, str(e))
    except PromptError as e:
        raise HttpError(503, str(e))


@router.post("/validate/{int:analysis_id}", response=ValidationOut)
def validate(request, analysis_id: int):
    require_role(request, *STAFF_ROLES)
    analyses = GenAIAnalysis.objects.filter(complaint__in=visible_complaints(request.auth))
    return validate_analysis(get_object_or_404(analyses, pk=analysis_id))


@router.get("/complaints/{complaint_id}/latest", response=ValidationDetailOut)
def latest(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    result = _results().filter(complaint=get_visible_complaint(request.auth, complaint_id)).first()
    if result is None:
        raise HttpError(404, "This complaint has not been validated yet.")
    return result


@router.get("/complaints/{complaint_id}/history", response=list[ValidationOut])
def history(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    return _results().filter(complaint=get_visible_complaint(request.auth, complaint_id))


@router.get("/results/{int:result_id}", response=ValidationDetailOut)
def result_detail(request, result_id: int):
    require_role(request, *STAFF_ROLES)
    return get_object_or_404(_results().filter(complaint__in=visible_complaints(request.auth)), pk=result_id)


# ---------------- comparison report ----------------


@router.get("/comparison", response=list[ComparisonRowOut])
def comparison(request, format: str = "json", decision: str | None = None):
    """Latest validation per complaint as a comparison table. ?format=csv downloads it."""
    require_role(request, *FULL_ACCESS_ROLES)  # a report across all complaints
    latest_ids, seen = [], set()
    for result_id, complaint_id in ValidationResult.objects.values_list("id", "complaint_id"):  # newest first
        if complaint_id not in seen:
            seen.add(complaint_id)
            latest_ids.append(result_id)
    results = _results().filter(id__in=latest_ids).order_by("complaint__complaint_id")
    if decision:
        results = results.filter(decision=decision)
    rows = [comparison_row(r) for r in results]
    if format != "csv":
        return rows

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(ComparisonRowOut.model_fields))
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "mismatched_fields": ";".join(row["mismatched_fields"])})
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="genai_python_comparison.csv"'
    return response


# ---------------- second-look rules (administrators) ----------------


def _admin(request):
    require_role(request, User.Role.ADMIN)


def _guarded(action, *args):
    try:
        return action(*args)
    except review_policy.ReviewPolicyError as e:
        raise HttpError(400, str(e))


@router.get("/review-policy", response=ReviewPolicyStateOut)
def review_policy_state(request):
    """The second-look rules in use, their limits and their history."""
    _admin(request)
    return review_admin.state()


@router.post("/review-policy/preview", response=ReviewPreviewOut)
def review_policy_preview(request, data: ReviewPolicyIn):
    """What these settings would have decided for the complaints checked so far. Nothing is saved."""
    _admin(request)
    return _guarded(review_admin.preview, data.settings)


@router.post("/review-policy", response=ReviewPolicyStateOut)
def review_policy_save(request, data: ReviewPolicyIn):
    """Save the settings as a new version and start using it for the next complaints."""
    _admin(request)
    _guarded(review_admin.save, data.settings, data.comment, request.auth)
    return review_admin.state()


@router.post("/review-policy/{int:version}/rollback", response=ReviewPolicyStateOut)
def review_policy_rollback(request, version: int, data: ReviewPolicyRollbackIn):
    """Use an earlier version again (saved as a new version; version 0 is the built-in defaults)."""
    _admin(request)
    _guarded(review_admin.rollback, version, data.comment, request.auth)
    return review_admin.state()
