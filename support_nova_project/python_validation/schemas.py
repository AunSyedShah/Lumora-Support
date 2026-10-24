from datetime import datetime

from ninja import Schema
from pydantic import Field

from .comparison import comparison_row


class ValidationOut(Schema):
    id: int
    complaint_id: str = Field(alias="complaint.complaint_id")
    analysis_id: int | None
    decision: str
    score: int
    agreement_rate: float
    counts: dict
    review_reasons: list[str]
    checks: list[dict]
    final_resolution: dict
    created_at: datetime


class ValidationDetailOut(ValidationOut):
    independent_expected: dict
    genai_view_expected: dict
    comparison: dict  # what GenAI said next to what the rule matrix says, field by field (SRS Steps 46-49)
    genai_available: bool  # False when the AI failed and the rules alone decided

    @staticmethod
    def resolve_comparison(obj):
        return comparison_row(obj)

    @staticmethod
    def resolve_genai_available(obj):
        return bool(obj.analysis and obj.analysis.output)


class ComparisonRowOut(Schema):
    """One row of the GenAI vs Python comparison report (SRS deliverable 8)."""

    complaint_id: str
    genai_category: str | None
    python_category: str | None
    genai_subcategory: str | None
    python_subcategory: str | None
    genai_department: str | None
    python_department: str | None
    genai_urgency: str | None
    python_urgency: str | None
    genai_priority: str | None
    python_priority: str | None
    genai_escalation: str | None
    python_escalation: str | None
    policy_reference: str | None
    match: str  # "match" | "mismatch"
    mismatched_fields: list[str]
    verification_status: str
    score: int
    explanation: str
