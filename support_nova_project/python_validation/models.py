"""
Pipeline 2 result: the Python ground-truth validation of one GenAI analysis.

`checks` holds every individual comparison, e.g.
  {"name": "priority", "status": "fail", "severity": "critical",
   "genai": "P2", "python": "P0", "message": "GenAI priority P2 is below the rule-matrix priority P0 ..."}
`final_resolution` is the recommendation after the rules have been enforced on top of the GenAI output.
"""

from django.db import models

from complaints.models import Complaint
from genai_pipeline.models import GenAIAnalysis


class ValidationResult(models.Model):
    class Decision(models.TextChoices):
        VERIFIED = "verified", "Verified"
        MANUAL_REVIEW = "manual_review", "Manual Review"

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="validations")
    analysis = models.ForeignKey(GenAIAnalysis, on_delete=models.CASCADE, related_name="validations", null=True)

    independent_expected = models.JSONField(default=dict)  # rule engine, its own keyword classification
    genai_view_expected = models.JSONField(default=dict)  # rule engine, evaluated for GenAI's subcategory
    checks = models.JSONField(default=list)
    score = models.PositiveSmallIntegerField()  # 0-100, from the check results
    agreement_rate = models.FloatField()  # share of comparable fields where GenAI == Python
    decision = models.CharField(max_length=20, choices=Decision.choices)
    review_reasons = models.JSONField(default=list)
    final_resolution = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.complaint.complaint_id} {self.decision} ({self.score})"

    @property
    def counts(self):
        result = {"critical": 0, "major": 0, "minor": 0}
        for check in self.checks:
            if check["status"] in ("fail", "warning") and check["severity"] in result:
                result[check["severity"]] += 1
        return result
