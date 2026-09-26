"""
Pipeline 1 records.

PromptTemplate  - centrally stored, versioned prompts (SRS Step 48). A version is never edited:
                  a change means a new version. Only one version per name is active.
GenAIAnalysis   - one GenAI run for one complaint, with everything needed as evidence (Step 49):
                  prompt version, provider, model, generation config, the exact request, the raw
                  response, every attempt, the validated JSON output, and the policy versions used.
"""

from django.conf import settings
from django.db import models

from complaints.models import Complaint


class PromptTemplate(models.Model):
    name = models.CharField(max_length=100)  # e.g. "complaint_analysis"
    version = models.CharField(max_length=20)  # e.g. "1.0"
    system_prompt = models.TextField()
    user_prompt = models.TextField()  # uses ${placeholders} filled by the context builder
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "-created_at"]
        constraints = [models.UniqueConstraint(fields=["name", "version"], name="unique_prompt_version")]

    def __str__(self):
        return f"{self.name} v{self.version}{' (active)' if self.is_active else ''}"


class GenAIAnalysis(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"  # valid JSON that passed schema validation
        FAILED = "failed", "Failed"  # no valid output after all attempts -> manual review

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="genai_analyses")
    prompt_template = models.ForeignKey(PromptTemplate, on_delete=models.PROTECT, related_name="analyses")
    provider = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    generation_config = models.JSONField(default=dict)  # temperature, max_tokens, tone, ...

    request_messages = models.JSONField(default=list)  # exact messages sent (first attempt)
    retrieved_chunks = models.JSONField(default=list)  # policy excerpts given to the model
    policy_versions = models.JSONField(default=dict)  # {"REF-POL": "2.0", ...}

    status = models.CharField(max_length=20, choices=Status.choices)
    attempts = models.JSONField(default=list)  # [{"attempt": 1, "ok": false, "errors": [...], ...}]
    raw_response = models.TextField(blank=True)  # last raw text returned by the model
    output = models.JSONField(null=True, blank=True)  # validated structured result
    validation_issues = models.JSONField(default=list)  # non-fatal problems, e.g. unknown policy IDs
    error = models.TextField(blank=True)

    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    cache_hit_tokens = models.PositiveIntegerField(default=0)  # prompt tokens served from DeepSeek's context cache
    latency_ms = models.PositiveIntegerField(default=0)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "GenAI analyses"

    def __str__(self):
        return f"{self.complaint.complaint_id} {self.status} ({self.created_at:%Y-%m-%d %H:%M})"
