from django.contrib import admin

from .models import AuditLog, ComplaintNote


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: the audit trail must not be edited."""

    list_display = ("complaint", "action", "actor", "created_at")
    list_filter = ("action",)
    search_fields = ("complaint__complaint_id", "comment")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ComplaintNote)
class ComplaintNoteAdmin(admin.ModelAdmin):
    list_display = ("complaint", "author", "customer_visible", "created_at")
    list_filter = ("customer_visible",)
