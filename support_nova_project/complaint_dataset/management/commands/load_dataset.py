"""
Step 3 of the dataset: submit the complaints in sample_complaints/complaints.csv through the
normal intake (no GenAI processing - evaluate_dataset does that).

Usage:  python manage.py load_dataset            # loads what is not loaded yet
        python manage.py load_dataset --reset    # remove the dataset customers/complaints first
"""

from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from complaint_dataset.csv_io import COMPLAINTS_FILE, read_rows, spec_from_row, text_from_row
from complaint_dataset.loader import load_dataset, remove_dataset


class Command(BaseCommand):
    help = "Load the synthetic complaint dataset into the database (intake only, no processing)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete previously loaded dataset data first.")

    def handle(self, *args, **options):
        if not COMPLAINTS_FILE.exists():
            raise CommandError("sample_complaints/complaints.csv not found. Run generate_complaint_text first.")
        if options["reset"]:
            self.stdout.write(f"Removed {remove_dataset()} dataset records.")

        rows = read_rows(COMPLAINTS_FILE)
        specs = [spec_from_row(r) for r in rows]
        texts = {r["case_id"]: text_from_row(r) for r in rows}
        settings.AUTO_PROCESS_ON_SUBMIT = False  # the loader never triggers GenAI calls
        cases = load_dataset(specs, texts)

        rejected = [c for c in cases if c.complaint is None]
        mismatched = [c for c in cases if c.fact_mismatches]
        matches = Counter(c.complaint.match_type or "none" for c in cases if c.complaint)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(cases) - len(rejected)} complaints "
                                             f"({len(rejected)} rejected at intake)."))
        self.stdout.write(f"Duplicate/repeat detection at intake: {dict(matches)}")
        for case in rejected:
            self.stdout.write(self.style.WARNING(f"{case.case_id}: {case.load_note}"))
        for case in mismatched:
            self.stdout.write(self.style.WARNING(f"{case.case_id} facts differ from the spec: {case.fact_mismatches}"))
