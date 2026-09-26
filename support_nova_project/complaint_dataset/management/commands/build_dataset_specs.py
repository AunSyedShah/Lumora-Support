"""
Step 1 of the dataset: decide what every complaint is about and its expected labels.

Writes sample_complaints/complaint_specs.csv. Needs the catalog and rules loaded
(seed_catalog, load_rules). Deterministic: the same seed gives the same specs.

Usage:  python manage.py build_dataset_specs [--seed 2026] [--force]
"""

from django.core.management.base import BaseCommand, CommandError

from complaint_dataset.csv_io import GENERATED_FILE, SPECS_FILE, write_specs
from complaint_dataset.specs import SEED, build_specs
from complaint_dataset.summary import coverage_lines
from rules.models import ResolutionRule


class Command(BaseCommand):
    help = "Build the complaint specs and expected labels (sample_complaints/complaint_specs.csv)."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=SEED)
        parser.add_argument("--force", action="store_true",
                            help="Overwrite the specs even though complaint text was already generated from them.")

    def handle(self, *args, **options):
        if not ResolutionRule.objects.exists():
            raise CommandError("No resolution rules in the database. Run seed_catalog and load_rules first.")
        if GENERATED_FILE.exists() and not options["force"]:
            raise CommandError(f"{GENERATED_FILE.name} exists: new specs would no longer match the generated text. "
                               "Use --force if you really want to rebuild.")

        specs, problems = build_specs(options["seed"])
        write_specs(specs)
        for problem in problems:
            self.stdout.write(self.style.WARNING(problem))
        for line in coverage_lines(specs):
            self.stdout.write(line)
        self.stdout.write(self.style.SUCCESS(f"Wrote {len(specs)} specs to {SPECS_FILE}"))
