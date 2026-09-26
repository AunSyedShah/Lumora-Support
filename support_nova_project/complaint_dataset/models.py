"""Which complaint in the database is which dataset case (the expected labels stay in the CSV)."""

from django.db import models

from complaints.models import Complaint


class DatasetCase(models.Model):
    case_id = models.CharField(max_length=10, unique=True)  # "DS-0042"
    split = models.CharField(max_length=10)  # dev | test
    group = models.CharField(max_length=30)
    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="dataset_case")
    load_note = models.CharField(max_length=300, blank=True)  # e.g. rejected at intake as an exact duplicate
    fact_mismatches = models.JSONField(default=list)  # facts the system calculated differently from the spec
    loaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["case_id"]

    def __str__(self):
        return self.case_id
