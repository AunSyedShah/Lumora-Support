"""Ingestion pipeline: validate -> parse -> read header metadata -> chunk -> save -> apply versioning."""

from datetime import date

from django.core.files.base import ContentFile
from django.db import transaction

from catalog.models import Category
from vector_search.embeddings import embed_texts, to_bytes

from .chunking import chunk_blocks
from .models import DocumentStatus, PolicyChunk, PolicyDocument
from .parsing import count_header_blocks, extract_header_metadata, parse_file
from .validation import (
    DocumentValidationError,
    check_duplicate_file,
    file_sha256,
    validate_file,
    validate_metadata,
)


def ingest_document(filename: str, data: bytes, form_meta: dict, user):
    """
    Process one uploaded file end to end. Returns (document, warnings).
    Raises DocumentValidationError when the upload must be rejected.
    """
    warnings = []

    # 1. File-level checks
    extension = validate_file(filename, data)
    file_hash = file_sha256(data)
    check_duplicate_file(file_hash)

    # 2. Parse
    try:
        parsed = parse_file(extension, data)
    except Exception as exc:  # corrupt or password-protected file
        raise DocumentValidationError(f"Could not read the document: {exc}")
    if len(parsed.full_text.strip()) < 50:
        raise DocumentValidationError(
            "No readable text found in the document (is it a scanned image PDF?)."
        )

    # 3. Metadata: header values first, explicit form values override them
    header_meta = extract_header_metadata(parsed)
    form_values = {k: v for k, v in form_meta.items() if v not in (None, "")}
    taken_from_header = sorted(set(header_meta) - set(form_values))
    if taken_from_header:
        warnings.append(f"Read from document header: {', '.join(taken_from_header)}.")
    meta = validate_metadata({**header_meta, **form_values})

    category = None
    if meta.get("category"):
        category = Category.objects.filter(code=meta["category"].upper()).first()
        if category is None:
            warnings.append(f"Unknown category '{meta['category']}' ignored.")

    if meta["status"] == DocumentStatus.ACTIVE:
        _check_not_older_than_active(meta)
    if meta["expiry_date"] and meta["expiry_date"] < date.today():
        warnings.append("This document has already expired and will not be used for resolutions.")

    # 4. Chunk (skip the title + metadata header blocks)
    header_blocks = count_header_blocks(parsed, header_meta.get("title"))
    chunks = chunk_blocks(parsed.blocks, skip_first=header_blocks)
    if not any(c.section for c in chunks):
        warnings.append("No numbered sections found; chunks cannot be cited by section number.")

    # 5. Save everything in one transaction
    with transaction.atomic():
        document = PolicyDocument(
            doc_id=meta["doc_id"],
            title=meta.get("title") or filename,
            doc_type=meta["doc_type"],
            category=category,
            version=meta["version"],
            status=meta["status"],
            effective_date=meta["effective_date"],
            expiry_date=meta["expiry_date"],
            original_filename=filename,
            file_size=len(data),
            file_hash=file_hash,
            page_count=parsed.page_count,
            uploaded_by=user,
        )
        document.file.save(filename, ContentFile(data), save=False)
        document.save()

        vectors = embed_texts([chunk_embedding_text(c.heading, c.text) for c in chunks])
        PolicyChunk.objects.bulk_create(
            PolicyChunk(
                document=document,
                chunk_id=f"{document.doc_id}-v{document.version}-{i:03d}",
                order=i,
                section=c.section,
                heading=c.heading[:255],
                page=c.page,
                text=c.text,
                embedding=to_bytes(vector),
            )
            for i, (c, vector) in enumerate(zip(chunks, vectors), start=1)
        )

        if document.status == DocumentStatus.ACTIVE:
            replaced = activate_document(document)
            if replaced:
                warnings.append(f"Replaced active version {replaced.version}; it is now marked Previous.")

    return document, warnings


def chunk_embedding_text(heading, text):
    return f"{heading}. {text}" if heading else text


def _check_not_older_than_active(meta):
    current = PolicyDocument.objects.filter(doc_id=meta["doc_id"], status=DocumentStatus.ACTIVE).first()
    if current and meta["effective_date"] < current.effective_date:
        raise DocumentValidationError(
            f"Active version {current.version} is newer (effective {current.effective_date}). "
            "Upload this one as 'previous' or 'draft' instead.",
            409,
        )


def activate_document(document):
    """
    Make `document` the single active version of its doc_id.
    The old active version becomes PREVIOUS; the old PREVIOUS becomes SUPERSEDED.
    Returns the document that was active before, if any.
    """
    others = PolicyDocument.objects.filter(doc_id=document.doc_id).exclude(pk=document.pk)
    old_active = others.filter(status=DocumentStatus.ACTIVE).first()

    others.filter(status=DocumentStatus.PREVIOUS).update(status=DocumentStatus.SUPERSEDED)
    others.filter(status=DocumentStatus.ACTIVE).update(status=DocumentStatus.PREVIOUS)

    if document.status != DocumentStatus.ACTIVE:
        document.status = DocumentStatus.ACTIVE
        document.save(update_fields=["status"])
    return old_active
