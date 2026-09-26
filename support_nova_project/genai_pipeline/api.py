"""
Pipeline 1 API: run the GenAI analysis, inspect results and evidence, manage prompt versions.
"""

from string import Template

from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from complaints.models import Complaint
from complaints.permissions import get_visible_complaint, visible_complaints

from .models import GenAIAnalysis, PromptTemplate
from .output_schema import Tone, json_schema
from .pipeline import analyze_complaint
from .prompts import RETRY_MARKER, PromptError, activate
from .schemas import (
    AnalysisEvidenceOut,
    AnalysisOut,
    AnalysisSummaryOut,
    PromptDetailOut,
    PromptIn,
    PromptOut,
)

router = Router(tags=["GenAI Pipeline"])

ADMIN = User.Role.ADMIN
REQUIRED_PLACEHOLDERS = {
    "taxonomy", "departments", "allowed_values", "policy_excerpts",
    "customer_context", "security_notes", "tone", "complaint",
}


def _analyses():
    return GenAIAnalysis.objects.select_related("complaint", "prompt_template", "requested_by")


@router.post("/analyze/{complaint_id}", response={200: AnalysisOut, 503: ErrorOut})
def analyze(request, complaint_id: str, tone: Tone | None = None):
    """Run Pipeline 1 on a complaint (?tone=formal etc.). A failed run is still recorded (status 'failed')."""
    require_role(request, *STAFF_ROLES)
    complaint = get_visible_complaint(request.auth, complaint_id,
                                      Complaint.objects.select_related("customer", "order", "product"))
    try:
        analysis = analyze_complaint(complaint, tone=tone, requested_by=request.auth)
    except PromptError as e:
        raise HttpError(503, str(e))
    return _analyses().get(pk=analysis.pk)


@router.get("/complaints/{complaint_id}/analyses", response=list[AnalysisSummaryOut])
def complaint_analyses(request, complaint_id: str):
    require_role(request, *STAFF_ROLES)
    complaint = get_visible_complaint(request.auth, complaint_id)
    return _analyses().filter(complaint=complaint)


@router.get("/complaints/{complaint_id}/latest", response=AnalysisOut)
def latest_analysis(request, complaint_id: str, successful_only: bool = True):
    require_role(request, *STAFF_ROLES)
    qs = _analyses().filter(complaint=get_visible_complaint(request.auth, complaint_id))
    if successful_only:
        qs = qs.filter(status=GenAIAnalysis.Status.SUCCESS)
    analysis = qs.first()
    if analysis is None:
        raise HttpError(404, "No analysis found for this complaint.")
    return analysis


@router.get("/analyses/{int:analysis_id}", response=AnalysisEvidenceOut)
def analysis_evidence(request, analysis_id: int):
    """Full record including the exact request sent and the raw response received."""
    require_role(request, *STAFF_ROLES)
    return get_object_or_404(_analyses().filter(complaint__in=visible_complaints(request.auth)), pk=analysis_id)


@router.get("/output-schema")
def output_schema(request):
    """JSON Schema that every GenAI answer must satisfy."""
    return json_schema()


# ---------------- prompt templates ----------------


@router.get("/prompts", response=list[PromptOut])
def list_prompts(request):
    require_role(request, *STAFF_ROLES)
    return PromptTemplate.objects.all()


@router.get("/prompts/{name}/{version}", response=PromptDetailOut)
def get_prompt(request, name: str, version: str):
    require_role(request, *STAFF_ROLES)
    return get_object_or_404(PromptTemplate, name=name, version=version)


@router.post("/prompts", response={201: PromptDetailOut, 400: ErrorOut, 409: ErrorOut})
def create_prompt(request, data: PromptIn):
    """Add a NEW prompt version (existing versions are never edited, so old analyses stay traceable)."""
    require_role(request, ADMIN)
    if PromptTemplate.objects.filter(name=data.name, version=data.version).exists():
        raise HttpError(409, f"{data.name} v{data.version} already exists. Use a new version number.")
    if RETRY_MARKER not in data.user_prompt:
        raise HttpError(400, f"user_prompt must contain a '{RETRY_MARKER}' line followed by the retry message.")
    user_part = data.user_prompt.split(RETRY_MARKER)[0]
    used = {m.group("named") or m.group("braced") for m in Template.pattern.finditer(user_part) if m.group("named") or m.group("braced")}
    missing = REQUIRED_PLACEHOLDERS - used
    if missing:
        raise HttpError(400, f"user_prompt is missing placeholder(s): {sorted('${' + m + '}' for m in missing)}")
    if "json" not in (data.system_prompt + user_part).lower():
        raise HttpError(400, "The prompt must mention 'json' (required by the provider's JSON mode).")

    prompt = PromptTemplate.objects.create(
        name=data.name, version=data.version, description=data.description,
        system_prompt=data.system_prompt, user_prompt=data.user_prompt, created_by=request.auth,
    )
    if data.activate:
        activate(prompt)
    return 201, prompt


@router.post("/prompts/{name}/{version}/activate", response=PromptOut)
def activate_prompt(request, name: str, version: str):
    """Switch the active version (e.g. roll back to an earlier prompt)."""
    require_role(request, ADMIN)
    prompt = get_object_or_404(PromptTemplate, name=name, version=version)
    activate(prompt)
    return prompt
