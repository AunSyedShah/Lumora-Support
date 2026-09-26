"""
Load the rule matrix from config/rules/*.csv (safe to re-run; rules are upserted by rule_id).
Usage:  python manage.py load_rules
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from rules.importer import RuleImportError, import_escalation_rules, import_resolution_rules

RULES_DIR = settings.BASE_DIR / "config" / "rules"


class Command(BaseCommand):
    help = "Import resolution and escalation rules from config/rules/."

    def handle(self, *args, **options):
        for filename, importer in (
            ("resolution_rules.csv", import_resolution_rules),
            ("escalation_rules.csv", import_escalation_rules),
        ):
            path = RULES_DIR / filename
            try:
                result = importer(path.read_text(encoding="utf-8"))
            except RuleImportError as e:
                raise CommandError(f"{filename}:\n  " + "\n  ".join(e.errors))
            self.stdout.write(self.style.SUCCESS(
                f"{filename}: {result['created']} created, {result['updated']} updated ({result['total']} rules)"
            ))
