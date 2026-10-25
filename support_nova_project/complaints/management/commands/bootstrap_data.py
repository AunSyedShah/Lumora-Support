"""
First-run setup in one command. Used by docker compose so a new developer only types `docker compose up`.

Every step looks first and only runs when its data is missing, so this is safe to run on every start and never
touches a database that already has data (for example one loaded from an earlier copy).

    uv run manage.py bootstrap_data                  catalog, rules, AI instructions, sample policies, demo accounts
    uv run manage.py bootstrap_data --dataset        also the 500 sample complaints (intake only, no AI cost)
    uv run manage.py bootstrap_data --skip-documents skip the sample policies (they need the embedding model, ~190 MB once)
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import User
from catalog.models import Department
from complaint_dataset.models import DatasetCase
from genai_pipeline.models import PromptTemplate
from knowledge_base.models import PolicyDocument
from rules.models import EscalationRule, ResolutionRule


class Command(BaseCommand):
    help = "Load the catalog, rules, prompts, sample policies and demo accounts that are not there yet."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", action="store_true", help="Also load the sample complaint dataset (no AI calls).")
        parser.add_argument("--skip-documents", action="store_true", help="Do not load the sample policy documents.")
        parser.add_argument("--migrate", action="store_true", help="Apply database migrations first (one process instead of two).")

    def handle(self, *args, **options):
        if options["migrate"]:
            self.stdout.write("  applying database migrations ...")
            call_command("migrate", interactive=False, verbosity=0)

        steps = [
            ("catalog (teams, problem types, products)", Department.objects.exists, lambda: call_command("seed_catalog", verbosity=0)),
            ("decision rules", lambda: ResolutionRule.objects.exists() and EscalationRule.objects.exists(), lambda: call_command("load_rules", verbosity=0)),
            ("AI instructions", lambda: PromptTemplate.objects.filter(is_active=True).exists(), lambda: call_command("load_prompts", activate_latest=True, verbosity=0)),
        ]
        if not options["skip_documents"]:
            steps.append(("sample policy documents", PolicyDocument.objects.exists, lambda: call_command("load_sample_documents", verbosity=0)))
        steps.append(("demo accounts and orders", lambda: User.objects.filter(role=User.Role.CUSTOMER).exists() or User.objects.filter(role=User.Role.ADMIN).exists(),
                      lambda: call_command("seed_demo_data", verbosity=0)))
        if options["dataset"]:
            steps.append(("sample complaint dataset", DatasetCase.objects.exists, lambda: call_command("load_dataset", spread_days=60, verbosity=0)))

        for name, present, load in steps:
            if present():
                self.stdout.write(f"  already there: {name}")
            else:
                self.stdout.write(f"  loading: {name} ...")
                load()
                self.stdout.write(self.style.SUCCESS(f"  loaded: {name}"))
        self.stdout.write(self.style.SUCCESS("Data is ready."))
