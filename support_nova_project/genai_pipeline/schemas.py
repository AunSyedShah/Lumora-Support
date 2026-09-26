from datetime import datetime

from ninja import Schema
from pydantic import Field


class AnalysisSummaryOut(Schema):
    id: int
    complaint_id: str = Field(alias="complaint.complaint_id")
    status: str
    prompt: str
    provider: str
    model: str
    attempt_count: int
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    cache_hit_tokens: int
    created_at: datetime

    @staticmethod
    def resolve_prompt(obj):
        return f"{obj.prompt_template.name} v{obj.prompt_template.version}"

    @staticmethod
    def resolve_attempt_count(obj):
        return len(obj.attempts)


class AnalysisOut(AnalysisSummaryOut):
    generation_config: dict
    policy_versions: dict
    retrieved_chunks: list[dict]
    attempts: list[dict]
    output: dict | None
    validation_issues: list[dict]
    error: str
    requested_by: str | None = Field(None, alias="requested_by.username")


class AnalysisEvidenceOut(AnalysisOut):
    """Adds the exact request and raw response (GenAI pipeline evidence deliverable)."""

    request_messages: list[dict]
    raw_response: str


class PromptOut(Schema):
    id: int
    name: str
    version: str
    description: str
    is_active: bool
    created_at: datetime
    analyses: int

    @staticmethod
    def resolve_analyses(obj):
        return obj.analyses.count()


class PromptDetailOut(PromptOut):
    system_prompt: str
    user_prompt: str


class PromptIn(Schema):
    name: str = Field("complaint_analysis", pattern=r"^[a-z0-9_]+$")
    version: str = Field(pattern=r"^\d+(\.\d+){0,2}$")
    description: str = ""
    system_prompt: str = Field(min_length=20)
    user_prompt: str = Field(min_length=20, description="USER part, then a line '### RETRY', then the retry message")
    activate: bool = False
