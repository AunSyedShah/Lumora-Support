"""
Load prompt templates from prompt_templates/<name>/v<version>.txt into the database.

Versions are immutable: if a version already exists with DIFFERENT text, it is not overwritten
(create a new version file instead). The highest version becomes active only if no version of
that prompt is active yet, so an admin's choice of active version is never undone.

Usage:  python manage.py load_prompts [--activate-latest]
"""

from django.core.management.base import BaseCommand, CommandError

from genai_pipeline.models import PromptTemplate
from genai_pipeline.prompts import PROMPT_DIR, PromptError, activate, parse_prompt_file


def version_key(version):
    return tuple(int(p) for p in version.split("."))


class Command(BaseCommand):
    help = "Load versioned prompt templates from prompt_templates/."

    def add_arguments(self, parser):
        parser.add_argument("--activate-latest", action="store_true", help="Make the highest version active")

    def handle(self, *args, **options):
        for folder in sorted(p for p in PROMPT_DIR.iterdir() if p.is_dir()):
            name = folder.name
            files = sorted(folder.glob("v*.txt"), key=lambda f: version_key(f.stem[1:]))
            for file in files:
                version = file.stem[1:]
                try:
                    parsed = parse_prompt_file(file.read_text(encoding="utf-8"))
                except PromptError as e:
                    raise CommandError(f"{file}: {e}")
                existing = PromptTemplate.objects.filter(name=name, version=version).first()
                if existing is None:
                    PromptTemplate.objects.create(name=name, version=version, **parsed)
                    self.stdout.write(f"added    {name} v{version}")
                elif (existing.system_prompt, existing.user_prompt) != (parsed["system_prompt"], parsed["user_prompt"]):
                    self.stderr.write(
                        f"CHANGED  {name} v{version} differs from the stored version - not overwritten. "
                        "Save your changes as a new version file."
                    )
                else:
                    self.stdout.write(f"same     {name} v{version}")

            no_active = not PromptTemplate.objects.filter(name=name, is_active=True).exists()
            if files and (no_active or options["activate_latest"]):
                latest = PromptTemplate.objects.get(name=name, version=files[-1].stem[1:])
                activate(latest)
                self.stdout.write(self.style.SUCCESS(f"activated {name} v{latest.version}"))
