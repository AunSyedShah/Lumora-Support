"""
Load every PDF / DOCX in sample_documents/ into the knowledge base.

Files are ingested oldest effective date first, so older versions are replaced by newer ones
through the normal versioning logic. Files already uploaded (same hash) are skipped.
Usage:  python manage.py load_sample_documents
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from knowledge_base.models import PolicyDocument
from knowledge_base.parsing import extract_header_metadata, parse_file
from knowledge_base.services import ingest_document
from knowledge_base.validation import DocumentValidationError, file_sha256

SAMPLE_DIR = settings.BASE_DIR / "sample_documents"


class Command(BaseCommand):
    help = "Upload the sample knowledge-base documents."

    def handle(self, *args, **options):
        files = []
        for path in SAMPLE_DIR.iterdir():
            if path.suffix.lower() not in (".pdf", ".docx"):
                continue
            data = path.read_bytes()
            header = extract_header_metadata(parse_file(path.suffix.lower(), data))
            files.append((header.get("effective_date", "9999-12-31"), path, data))

        for _, path, data in sorted(files):
            if PolicyDocument.objects.filter(file_hash=file_sha256(data)).exists():
                self.stdout.write(f"skip     {path.name} (already uploaded)")
                continue
            try:
                document, warnings = ingest_document(path.name, data, {}, user=None)
            except DocumentValidationError as e:
                self.stderr.write(f"FAILED   {path.name}: {e}")
                continue
            self.stdout.write(
                f"loaded   {path.name} -> {document.doc_id} v{document.version} "
                f"({document.status}, {document.chunks.count()} chunks)"
            )
            for w in warnings:
                if not w.startswith("Read from document header"):
                    self.stdout.write(f"         ! {w}")
