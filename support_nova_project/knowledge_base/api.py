"""
Knowledge-base API.

Administrators upload and manage documents; all staff can read and search them.
Customers have no access (SOPs and routing rules are internal).
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import File, Form, Router, UploadedFile
from ninja.errors import HttpError

from accounts.auth import STAFF_ROLES, require_role
from accounts.models import User
from accounts.schemas import ErrorOut
from catalog.models import Category

from .models import DocumentStatus, PolicyDocument
from .retrieval import SEARCH_MODES, hybrid_search
from .schemas import ChunkOut, DocumentOut, DocumentUpdate, DocumentUploadForm, SearchHitOut, UploadOut
from .services import activate_document, ingest_document
from .validation import DocumentValidationError

router = Router(tags=["Knowledge Base"])

ADMIN = User.Role.ADMIN


def _documents():
    return PolicyDocument.objects.select_related("category", "uploaded_by")


@router.post("/documents", response={201: UploadOut, 400: ErrorOut, 409: ErrorOut})
def upload_document(request, file: File[UploadedFile], meta: Form[DocumentUploadForm]):
    """Upload a PDF/DOCX (or TXT/MD) document. Metadata may come from the form or the document header."""
    require_role(request, ADMIN)
    try:
        document, warnings = ingest_document(
            filename=file.name,
            data=file.read(),
            form_meta=meta.model_dump(),
            user=request.auth,
        )
    except DocumentValidationError as e:
        raise HttpError(e.status_code, str(e))
    return 201, {"document": document, "warnings": warnings}


@router.get("/documents", response=list[DocumentOut])
def list_documents(
    request,
    doc_id: str | None = None,
    status: DocumentStatus | None = None,
    doc_type: str | None = None,
    category: str | None = None,
    usable_only: bool = False,
):
    require_role(request, *STAFF_ROLES)
    qs = _documents()
    if doc_id:
        qs = qs.filter(doc_id=doc_id.upper())
    if status:
        qs = qs.filter(status=status)
    if doc_type:
        qs = qs.filter(doc_type=doc_type)
    if category:
        qs = qs.filter(category__code=category)
    if usable_only:
        return [d for d in qs if d.is_usable]
    return qs


@router.get("/documents/{int:id}", response=DocumentOut)
def get_document(request, id: int):
    require_role(request, *STAFF_ROLES)
    return get_object_or_404(_documents(), id=id)


@router.get("/documents/{int:id}/chunks", response=list[ChunkOut])
def get_document_chunks(request, id: int, section: str | None = None):
    require_role(request, *STAFF_ROLES)
    document = get_object_or_404(PolicyDocument, id=id)
    chunks = document.chunks.all()
    if section:
        chunks = chunks.filter(section=section)
    return chunks


@router.get("/documents/history/{doc_id}", response=list[DocumentOut])
def document_history(request, doc_id: str):
    """All versions of one document, newest first."""
    require_role(request, *STAFF_ROLES)
    return _documents().filter(doc_id=doc_id.upper()).order_by("-effective_date")


@router.patch("/documents/{int:id}", response={200: DocumentOut, 404: ErrorOut})
def update_document(request, id: int, data: DocumentUpdate):
    """Change title / category / expiry, or change status. Setting status=active re-applies versioning."""
    require_role(request, ADMIN)
    document = get_object_or_404(PolicyDocument, id=id)
    fields = data.model_dump(exclude_unset=True)

    if "category" in fields:
        code = fields.pop("category")
        document.category = get_object_or_404(Category, code=code) if code else None
    if "expiry_date" in fields and fields["expiry_date"] and fields["expiry_date"] <= document.effective_date:
        raise HttpError(400, "expiry_date must be after effective_date.")

    new_status = fields.pop("status", None)
    for field, value in fields.items():
        setattr(document, field, value)

    with transaction.atomic():
        document.save()
        if new_status == DocumentStatus.ACTIVE:
            activate_document(document)
        elif new_status:
            document.status = new_status
            document.save(update_fields=["status"])
    return _documents().get(id=document.id)


@router.delete("/documents/{int:id}", response={204: None, 409: ErrorOut})
def delete_document(request, id: int):
    """Only drafts can be deleted; approved versions are kept for traceability."""
    require_role(request, ADMIN)
    document = get_object_or_404(PolicyDocument, id=id)
    if document.status != DocumentStatus.DRAFT:
        raise HttpError(409, "Only draft documents can be deleted. Mark others as superseded instead.")
    document.file.delete(save=False)
    document.delete()
    return 204, None


@router.get("/search", response=list[SearchHitOut])
def search(request, q: str, mode: str = "hybrid", category: str | None = None, limit: int = 5):
    """Search usable (active, effective, not expired) policy chunks. mode = keyword | semantic | hybrid."""
    require_role(request, *STAFF_ROLES)
    if mode not in SEARCH_MODES:
        raise HttpError(400, f"mode must be one of {list(SEARCH_MODES)}")
    limit = min(limit, 20)
    if mode == "hybrid":
        hits = hybrid_search(q, category_code=category, limit=limit)
    elif mode == "keyword":
        hits = SEARCH_MODES[mode](q, category_code=category, limit=limit)
    else:
        hits = SEARCH_MODES[mode](q, limit=limit)
    return [
        {
            "score": h["score"],
            "keyword_score": h.get("keyword_score"),
            "semantic_score": h.get("semantic_score"),
            "chunk_id": h["chunk"].chunk_id,
            "doc_id": h["chunk"].document.doc_id,
            "version": h["chunk"].document.version,
            "doc_type": h["chunk"].document.doc_type,
            "title": h["chunk"].document.title,
            "section": h["chunk"].section,
            "heading": h["chunk"].heading,
            "page": h["chunk"].page,
            "text": h["chunk"].text,
        }
        for h in hits
    ]
