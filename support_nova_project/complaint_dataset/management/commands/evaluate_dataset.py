"""
Step 4 of the dataset: score the system against the expected labels.

  --pipeline python   Pipeline 2 alone (rule engine on the complaint text). No GenAI, no cost.
  --pipeline full     process every selected complaint (GenAI + validation + final decision)
                      if it was not processed yet, then score Pipeline 1, Pipeline 2 and the final result.
  --split test        the 100 held-out complaints (default), or dev / all

Writes sample_complaints/evaluation/<split>_<pipeline>.csv (one row per complaint) and .json (summary).

Usage:  python manage.py evaluate_dataset --pipeline python --split all
        python manage.py evaluate_dataset --pipeline full --split test
"""

import csv
import json
import random

from django.core.management.base import BaseCommand, CommandError

from complaint_dataset.csv_io import COMPLAINTS_FILE, DATASET_DIR, read_rows, spec_from_row
from complaint_dataset.evaluation import VIEWS, evaluate_case, summarize
from complaint_dataset.models import DatasetCase
from complaints.models import Complaint
from workflow.services import WorkflowError, process_and_apply


class Command(BaseCommand):
    help = "Score the system against the dataset's expected labels."

    def add_arguments(self, parser):
        parser.add_argument("--pipeline", choices=["python", "full"], default="python")
        parser.add_argument("--split", choices=["test", "dev", "all"], default="test")
        parser.add_argument("--limit", type=int, help="Only the first N complaints (for a quick check).")
        parser.add_argument("--sample", type=int, help="A random sample of N complaints (fixed seed), e.g. for tuning.")
        parser.add_argument("--reprocess", action="store_true", help="Process again even if already processed.")

    def handle(self, *args, **options):
        if not COMPLAINTS_FILE.exists():
            raise CommandError("sample_complaints/complaints.csv not found.")
        specs = [spec_from_row(r) for r in read_rows(COMPLAINTS_FILE)]
        by_id = {s.case_id: s for s in specs}
        cases = {c.case_id: c for c in DatasetCase.objects.select_related("complaint")}
        if not cases:
            raise CommandError("The dataset is not loaded. Run load_dataset first.")

        selected = [s for s in specs if options["split"] == "all" or s.split == options["split"]]
        selected = [s for s in selected if s.case_id in cases and cases[s.case_id].complaint_id]
        if options["sample"]:
            selected = sorted(random.Random(7).sample(selected, min(options["sample"], len(selected))),
                              key=lambda s: s.case_id)
        if options["limit"]:
            selected = selected[: options["limit"]]

        views = ("python",) if options["pipeline"] == "python" else VIEWS
        if options["pipeline"] == "full":
            self.process(selected, cases, options["reprocess"])
            cases = {c.case_id: c for c in DatasetCase.objects.select_related("complaint")}

        rows = [evaluate_case(s, cases[s.case_id], by_id, cases, views) for s in selected]
        summary = summarize(rows, views)

        out_dir = DATASET_DIR / "evaluation"
        out_dir.mkdir(exist_ok=True)
        name = f"{options['split']}_{options['pipeline']}" + (f"_sample{options['sample']}" if options["sample"] else "")
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        (out_dir / f"{name}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        self.stdout.write(json.dumps(summary, indent=2))
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_dir / name}.csv and .json"))

    def process(self, specs, cases, reprocess):
        for i, spec in enumerate(specs, 1):
            complaint = Complaint.objects.get(pk=cases[spec.case_id].complaint_id)
            if complaint.verification_status != Complaint.Verification.PENDING and not reprocess:
                continue
            try:
                result = process_and_apply(complaint)
                decision = result["decision"] if isinstance(result, dict) else getattr(result, "decision", "")
            except WorkflowError as e:
                decision = f"error: {e}"
            self.stdout.write(f"[{i}/{len(specs)}] {spec.case_id} {complaint.complaint_id} {decision}")
