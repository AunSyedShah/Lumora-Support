from datetime import date, datetime

from ninja import Schema
from pydantic import Field, field_validator

from .models import DocumentStatus, DocumentType


class DocumentUploadForm(Schema):
    """
    All optional: anything left empty is read from the document's metadata header.
    Form values override the header.
    """

    doc_id: str | None = None
    title: str | None = None
    doc_type: DocumentType | None = None
    category: str | None = None  # catalog category code, e.g. "REFUND"
    version: str | None = None
    status: DocumentStatus | None = None
    effective_date: str | None = Field(None, description="YYYY-MM-DD")
    expiry_date: str | None = Field(None, description="YYYY-MM-DD")

    @field_validator("*", mode="before")
    @classmethod
    def blank_means_missing(cls, value):
        # HTML/Swagger forms send "" for fields left empty; treat that as "not provided".
        return None if isinstance(value, str) and value.strip() == "" else value


class DocumentOut(Schema):
    id: int
    doc_id: str
    title: str
    doc_type: str
    category: str | None = Field(None, alias="category.code")
    version: str
    status: str
    effective_date: date
    expiry_date: date | None
    is_usable: bool
    precedence: int
    original_filename: str
    file_size: int
    page_count: int | None
    file_hash: str
    chunk_count: int
    uploaded_by: str | None = Field(None, alias="uploaded_by.username")
    uploaded_at: datetime

    @staticmethod
    def resolve_chunk_count(obj):
        return obj.chunks.count()


class UploadOut(Schema):
    document: DocumentOut
    warnings: list[str]


class DocumentUpdate(Schema):
    title: str | None = None
    status: DocumentStatus | None = None
    category: str | None = None
    expiry_date: date | None = None


class ChunkOut(Schema):
    chunk_id: str
    order: int
    section: str
    heading: str
    page: int | None
    text: str


class SearchHitOut(Schema):
    score: float
    keyword_score: float | None = None
    semantic_score: float | None = None
    chunk_id: str
    doc_id: str
    version: str
    doc_type: str
    title: str
    section: str
    heading: str
    page: int | None
    text: str
