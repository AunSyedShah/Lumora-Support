"""
Rule-matrix API.

Staff can read rules, run the evaluator and check policy references.
Only administrators can change rules (create / update / delete / import).
"""

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, UploadedFile
from ninja.errors import HttpError

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from catalog.models import Department, Subcategory

from .conditions import Facts
from .engine import evaluate
from .importer import (
    RuleImportError,
    export_escalation_rules,
    export_resolution_rules,
    import_escalation_rules,
    import_resolution_rules,
)
from .models import EscalationRule, ResolutionRule
from .references import check_all_references
from .schemas import (
    EscalationRuleIn,
    EscalationRuleOut,
    EscalationRuleUpdate,
    EvaluationOut,
    FactsIn,
    ImportErrorOut,
    ImportResultOut,
    PolicyCheckOut,
    ResolutionRuleIn,
    ResolutionRuleOut,
    ResolutionRuleUpdate,
    RuleStatsOut,
)

router = Router(tags=["Rule Matrix"])

ADMIN = User.Role.ADMIN


def _dept(code):
    return get_object_or_404(Department, code=code.upper())


def _resolution_qs():
    return ResolutionRule.objects.select_related("category", "subcategory", "department").prefetch_related(
        "supporting_departments"
    )


# ---------------- resolution rules ----------------


@router.get("/resolution", response=list[ResolutionRuleOut])
def list_resolution_rules(
    request, category: str | None = None, subcategory: str | None = None, department: str | None = None,
    active_only: bool = False,
):
    require_role(request, *STAFF_ROLES)
    qs = _resolution_qs()
    if category:
        qs = qs.filter(category__code=category.upper())
    if subcategory:
        qs = qs.filter(subcategory__code=subcategory.upper())
    if department:
        qs = qs.filter(department__code=department.upper())
    return qs.filter(is_active=True) if active_only else qs


@router.get("/resolution/{rule_id}", response=ResolutionRuleOut)
def get_resolution_rule(request, rule_id: str):
    require_role(request, *STAFF_ROLES)
    return get_object_or_404(_resolution_qs(), rule_id=rule_id.upper())


@router.post("/resolution", response={201: ResolutionRuleOut, 404: ErrorOut, 409: ErrorOut})
def create_resolution_rule(request, data: ResolutionRuleIn):
    require_role(request, ADMIN)
    if ResolutionRule.objects.filter(rule_id=data.rule_id).exists():
        raise HttpError(409, f"Rule {data.rule_id} already exists.")
    subcategory = get_object_or_404(Subcategory.objects.select_related("category"), code=data.subcategory.upper())
    fields = data.model_dump(exclude={"subcategory", "department", "supporting_departments"})
    rule = ResolutionRule.objects.create(
        **fields,
        category=subcategory.category,
        subcategory=subcategory,
        department=_dept(data.department) if data.department else subcategory.routed_department,
    )
    rule.supporting_departments.set([_dept(c) for c in data.supporting_departments])
    return 201, _resolution_qs().get(pk=rule.pk)


@router.patch("/resolution/{rule_id}", response=ResolutionRuleOut)
def update_resolution_rule(request, rule_id: str, data: ResolutionRuleUpdate):
    require_role(request, ADMIN)
    rule = get_object_or_404(ResolutionRule, rule_id=rule_id.upper())
    fields = data.model_dump(exclude_unset=True)
    if "department" in fields:
        code = fields.pop("department")
        rule.department = _dept(code) if code else rule.subcategory.routed_department
    supporting = fields.pop("supporting_departments", None)
    for field, value in fields.items():
        setattr(rule, field, value)
    rule.save()
    if supporting is not None:
        rule.supporting_departments.set([_dept(c) for c in supporting])
    return _resolution_qs().get(pk=rule.pk)


@router.delete("/resolution/{rule_id}", response={204: None})
def delete_resolution_rule(request, rule_id: str):
    require_role(request, ADMIN)
    get_object_or_404(ResolutionRule, rule_id=rule_id.upper()).delete()
    return 204, None


# ---------------- escalation rules ----------------


@router.get("/escalation", response=list[EscalationRuleOut])
def list_escalation_rules(request, active_only: bool = False):
    require_role(request, *STAFF_ROLES)
    qs = EscalationRule.objects.select_related("target_department")
    return qs.filter(is_active=True) if active_only else qs


@router.get("/escalation/{rule_id}", response=EscalationRuleOut)
def get_escalation_rule(request, rule_id: str):
    require_role(request, *STAFF_ROLES)
    return get_object_or_404(EscalationRule, rule_id=rule_id.upper())


@router.post("/escalation", response={201: EscalationRuleOut, 404: ErrorOut, 409: ErrorOut})
def create_escalation_rule(request, data: EscalationRuleIn):
    require_role(request, ADMIN)
    if EscalationRule.objects.filter(rule_id=data.rule_id).exists():
        raise HttpError(409, f"Rule {data.rule_id} already exists.")
    fields = data.model_dump(exclude={"target_department"})
    fields["min_urgency"] = fields["min_urgency"] or ""
    fields["min_priority"] = fields["min_priority"] or ""
    rule = EscalationRule.objects.create(
        **fields, target_department=_dept(data.target_department) if data.target_department else None
    )
    return 201, rule


@router.patch("/escalation/{rule_id}", response=EscalationRuleOut)
def update_escalation_rule(request, rule_id: str, data: EscalationRuleUpdate):
    require_role(request, ADMIN)
    rule = get_object_or_404(EscalationRule, rule_id=rule_id.upper())
    fields = data.model_dump(exclude_unset=True)
    if "target_department" in fields:
        code = fields.pop("target_department")
        rule.target_department = _dept(code) if code else None
    for field in ("min_urgency", "min_priority"):
        if field in fields and fields[field] is None:
            fields[field] = ""  # null clears the minimum
    for field, value in fields.items():
        if value is not None:
            setattr(rule, field, value)
    rule.save()
    return rule


@router.delete("/escalation/{rule_id}", response={204: None})
def delete_escalation_rule(request, rule_id: str):
    require_role(request, ADMIN)
    get_object_or_404(EscalationRule, rule_id=rule_id.upper()).delete()
    return 204, None


# ---------------- import / export ----------------


@router.post("/import/{rule_type}", response={200: ImportResultOut, 400: ImportErrorOut})
def import_rules(request, rule_type: str, file: File[UploadedFile]):
    """Upload a CSV of 'resolution' or 'escalation' rules. Rows are upserted by rule_id."""
    require_role(request, ADMIN)
    importers = {"resolution": import_resolution_rules, "escalation": import_escalation_rules}
    if rule_type not in importers:
        raise HttpError(404, "rule_type must be 'resolution' or 'escalation'.")
    try:
        text = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HttpError(400, "The CSV file must be UTF-8 encoded.")
    try:
        return importers[rule_type](text)
    except RuleImportError as e:
        return 400, {"detail": str(e), "errors": e.errors}


@router.get("/export/{rule_type}")
def export_rules(request, rule_type: str, format: str = "csv"):
    """Download all rules as CSV (spreadsheet-friendly) or JSON."""
    require_role(request, *STAFF_ROLES)
    if rule_type == "resolution":
        qs, to_csv, schema = _resolution_qs(), export_resolution_rules, ResolutionRuleOut
    elif rule_type == "escalation":
        qs, to_csv, schema = EscalationRule.objects.select_related("target_department"), export_escalation_rules, EscalationRuleOut
    else:
        raise HttpError(404, "rule_type must be 'resolution' or 'escalation'.")

    if format == "json":
        data = [schema.from_orm(r).model_dump() for r in qs]
        return JsonResponse(data, safe=False, json_dumps_params={"indent": 2})
    response = HttpResponse(to_csv(qs), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{rule_type}_rules.csv"'
    return response


# ---------------- evaluation & checks ----------------


@router.post("/evaluate", response=EvaluationOut)
def evaluate_facts(request, data: FactsIn):
    """Run complaint facts through the rule matrix and return the EXPECTED (ground-truth) result."""
    require_role(request, *STAFF_ROLES)
    facts = Facts(**data.model_dump(exclude={"subcategory"}))
    return evaluate(facts, subcategory_code=data.subcategory.upper() if data.subcategory else None)


@router.get("/policy-check", response=list[PolicyCheckOut])
def policy_check(request, include_ok: bool = False):
    """Rules whose policy reference is missing, outdated, or points to a section that doesn't exist."""
    require_role(request, *STAFF_ROLES)
    return check_all_references(include_ok=include_ok)


@router.get("/stats", response=RuleStatsOut)
def rule_stats(request):
    """Coverage check: every active subcategory should have keywords and at least one rule."""
    require_role(request, *STAFF_ROLES)
    active_subs = Subcategory.objects.filter(is_active=True, category__is_active=True)
    return {
        "resolution_rules": ResolutionRule.objects.filter(is_active=True).count(),
        "escalation_rules": EscalationRule.objects.filter(is_active=True).count(),
        "subcategories_without_rules": list(
            active_subs.exclude(resolution_rules__is_active=True).values_list("code", flat=True)
        ),
        "subcategories_without_keywords": [s.code for s in active_subs if not s.keywords],
    }
