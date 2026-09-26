"""
Write the GenAI output JSON Schema to schemas/complaint_analysis.schema.json (project deliverable).
Usage:  python manage.py export_genai_schema
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from genai_pipeline.output_schema import json_schema


class Command(BaseCommand):
    help = "Export the GenAI output JSON Schema."

    def handle(self, *args, **options):
        path = settings.BASE_DIR / "schemas" / "complaint_analysis.schema.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {path.relative_to(settings.BASE_DIR)}"))
