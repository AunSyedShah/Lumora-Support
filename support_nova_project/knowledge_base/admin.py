from django.contrib import admin

from .models import PolicyChunk, PolicyDocument


class PolicyChunkInline(admin.TabularInline):
    model = PolicyChunk
    extra = 0
    fields = ("chunk_id", "section", "heading", "page")
    readonly_fields = fields
    show_change_link = True


@admin.register(PolicyDocument)
class PolicyDocumentAdmin(admin.ModelAdmin):
    list_display = ("doc_id", "version", "title", "doc_type", "status", "effective_date", "expiry_date")
    list_filter = ("status", "doc_type")
    search_fields = ("doc_id", "title")
    readonly_fields = ("file_hash", "file_size", "page_count", "uploaded_by", "uploaded_at")
    inlines = [PolicyChunkInline]


@admin.register(PolicyChunk)
class PolicyChunkAdmin(admin.ModelAdmin):
    list_display = ("chunk_id", "section", "heading", "page")
    search_fields = ("chunk_id", "heading", "text")
