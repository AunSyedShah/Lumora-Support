from ninja import Schema
from pydantic import Field, field_validator

from catalog.models import Priority, Urgency

from .conditions import clean_conditions
from .models import Compensation, EscalationLevel

# ---------- resolution rules ----------


class ResolutionRuleOut(Schema):
    rule_id: str
    description: str
    category: str = Field(alias="category.code")
    subcategory: str = Field(alias="subcategory.code")
    conditions: dict
    department: str = Field(alias="department.code")
    supporting_departments: list[str]
    urgency: str
    priority: str
    escalation_level: str
    policy_id: str
    policy_section: str
    required_actions: list[str]
    prohibited_actions: list[str]
    allowed_compensation: list[str]
    follow_up_required: bool
    follow_up_days: int
    is_active: bool

    @staticmethod
    def resolve_supporting_departments(obj):
        return [d.code for d in obj.supporting_departments.all()]


class _WithConditions(Schema):
    """Validates the `conditions` dict of subclasses against the condition language."""

    @field_validator("conditions", check_fields=False)
    @classmethod
    def check_conditions(cls, value):
        return clean_conditions(value) if value is not None else value


class ResolutionRuleIn(_WithConditions):
    rule_id: str = Field(pattern=r"^[A-Z0-9\-]{2,20}$")
    description: str = ""
    subcategory: str  # code; the category is taken from it
    conditions: dict = {}
    department: str | None = None  # blank = subcategory's routed department
    supporting_departments: list[str] = []
    urgency: Urgency
    priority: Priority
    escalation_level: EscalationLevel = EscalationLevel.NONE
    policy_id: str
    policy_section: str = ""
    required_actions: list[str] = []
    prohibited_actions: list[str] = []
    allowed_compensation: list[Compensation] = [Compensation.NONE]
    follow_up_days: int = Field(0, ge=0, le=90)
    is_active: bool = True


class ResolutionRuleUpdate(_WithConditions):
    description: str | None = None
    conditions: dict | None = None
    department: str | None = None
    supporting_departments: list[str] | None = None
    urgency: Urgency | None = None
    priority: Priority | None = None
    escalation_level: EscalationLevel | None = None
    policy_id: str | None = None
    policy_section: str | None = None
    required_actions: list[str] | None = None
    prohibited_actions: list[str] | None = None
    allowed_compensation: list[Compensation] | None = None
    follow_up_days: int | None = Field(None, ge=0, le=90)
    is_active: bool | None = None


# ---------- escalation rules ----------


class EscalationRuleOut(Schema):
    rule_id: str
    name: str
    description: str
    conditions: dict
    escalation_level: str
    target_department: str | None = Field(None, alias="target_department.code")
    min_urgency: str
    min_priority: str
    policy_id: str
    policy_section: str
    is_active: bool


class EscalationRuleIn(_WithConditions):
    rule_id: str = Field(pattern=r"^[A-Z0-9\-]{2,20}$")
    name: str = Field(min_length=3, max_length=150)
    description: str = ""
    conditions: dict = Field(min_length=1)
    escalation_level: EscalationLevel
    target_department: str | None = None
    min_urgency: Urgency | None = None
    min_priority: Priority | None = None
    policy_id: str = ""
    policy_section: str = ""
    is_active: bool = True


class EscalationRuleUpdate(_WithConditions):
    name: str | None = None
    description: str | None = None
    conditions: dict | None = None
    escalation_level: EscalationLevel | None = None
    target_department: str | None = None
    min_urgency: Urgency | None = None
    min_priority: Priority | None = None
    policy_id: str | None = None
    policy_section: str | None = None
    is_active: bool | None = None


# ---------- import / evaluate / policy check ----------


class ImportResultOut(Schema):
    created: int
    updated: int
    total: int


class ImportErrorOut(Schema):
    detail: str
    errors: list[str]


class FactsIn(Schema):
    """Complaint facts to run through the rule matrix."""

    text: str = Field(min_length=3, description="Complaint title + description")
    customer_type: str | None = None
    product: str | None = None
    amount: float | None = Field(None, ge=0)
    days_since_purchase: int | None = Field(None, ge=0)
    days_since_delivery: int | None = Field(None, ge=0)
    days_late: int | None = Field(None, ge=0)
    previous_complaints: int = Field(0, ge=0)
    subcategory: str | None = Field(None, description="Skip classification and evaluate this subcategory")


class IssueOut(Schema):
    category: str
    subcategory: str
    score: int
    matched_keywords: list[str]
    rule_id: str | None


class FiredEscalationOut(Schema):
    rule_id: str
    name: str
    level: str
    reasons: list[str]
    target_department: str | None = None


class EvaluationOut(Schema):
    classification_method: str
    primary_issue: IssueOut | None
    secondary_issues: list[IssueOut]
    category: str | None
    subcategory: str | None
    department: str | None
    supporting_departments: list[str]
    urgency: str | None
    priority: str | None
    escalation_level: str
    escalation_required: bool
    resolution_rule: str | None
    policy_id: str | None
    policy_section: str | None
    required_actions: list[str]
    prohibited_actions: list[str]
    allowed_compensation: list[str]
    follow_up_required: bool
    follow_up_days: int
    escalation_rules: list[FiredEscalationOut]
    missing_facts: list[str]
    rule_decided: bool
    needs_manual_review: bool
    explanations: list[str]


class PolicyCheckOut(Schema):
    rule_type: str
    rule_id: str
    policy_id: str
    policy_section: str
    status: str
    active_version: str | None


class RuleStatsOut(Schema):
    resolution_rules: int
    escalation_rules: int
    subcategories_without_rules: list[str]
    subcategories_without_keywords: list[str]
