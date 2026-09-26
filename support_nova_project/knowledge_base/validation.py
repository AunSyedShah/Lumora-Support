"""Checks run on every upload before anything is saved (SRS Step 4)."""

import hashlib
import re
from datetime import date
from pathlib import Path

from django.conf import settings

from .models import DocumentStatus, DocumentType, PolicyDocument

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# The first bytes of a real file of each type, so a renamed .exe can't pass as a .pdf.
MAGIC_BYTES = {".pdf": b"%PDF", ".docx": b"PK\x03\x04"}

DOC_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_\-]{1,49}$")


class DocumentValidationError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def validate_file(filename: str, data: bytes) -> str:
    """Check type, size, emptiness and file signature. Returns the lower-case extension."""
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(
            f"Unsupported file type '{extension}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
        )
    if len(data) == 0:
        raise DocumentValidationError("The uploaded file is empty.")

    max_bytes = settings.KB_MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise DocumentValidationError(f"File is larger than {settings.KB_MAX_UPLOAD_MB} MB.")

    magic = MAGIC_BYTES.get(extension)
    if magic and not data.startswith(magic):
        raise DocumentValidationError(f"File content does not match the '{extension}' extension.")
    return extension


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_duplicate_file(file_hash: str):
    existing = PolicyDocument.objects.filter(file_hash=file_hash).first()
    if existing:
        raise DocumentValidationError(
            f"This exact file was already uploaded as {existing.doc_id} v{existing.version}.", 409
        )


def _parse_date(value, field):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise DocumentValidationError(f"{field} must be a date in YYYY-MM-DD format.")


def _match_choice(value, choices, field):
    """Accept either the stored value ('sop') or the label ('Standard Operating Procedure')."""
    value = str(value).strip().lower()
    for choice in choices:
        if value in (choice.value, choice.label.lower()):
            return choice.value
    allowed = ", ".join(c.value for c in choices)
    raise DocumentValidationError(f"Invalid {field} '{value}'. Allowed: {allowed}.")


def validate_metadata(meta: dict) -> dict:
    """Normalise and check the merged metadata (form fields + document header)."""
    missing = [f for f in ("doc_id", "version", "doc_type", "effective_date") if not meta.get(f)]
    if missing:
        raise DocumentValidationError(
            f"Missing required metadata: {', '.join(missing)}. "
            "Send them as form fields or put them in the document header."
        )

    clean = dict(meta)
    clean["doc_id"] = meta["doc_id"].strip().upper()
    if not DOC_ID_PATTERN.match(clean["doc_id"]):
        raise DocumentValidationError("doc_id may only contain A-Z, 0-9, '-' and '_'.")

    clean["version"] = str(meta["version"]).strip().lstrip("vV")
    clean["doc_type"] = _match_choice(meta["doc_type"], DocumentType, "doc_type")
    clean["status"] = _match_choice(meta.get("status") or "draft", DocumentStatus, "status")
    clean["effective_date"] = _parse_date(meta["effective_date"], "effective_date")
    clean["expiry_date"] = _parse_date(meta.get("expiry_date"), "expiry_date")

    if clean["expiry_date"] and clean["expiry_date"] <= clean["effective_date"]:
        raise DocumentValidationError("expiry_date must be after effective_date.")

    if PolicyDocument.objects.filter(doc_id=clean["doc_id"], version=clean["version"]).exists():
        raise DocumentValidationError(
            f"{clean['doc_id']} version {clean['version']} already exists. Upload it with a new version number.",
            409,
        )
    return clean
