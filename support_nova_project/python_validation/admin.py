from django.contrib import admin

from .models import ValidationResult


@admin.register(ValidationResult)
class ValidationResultAdmin(admin.ModelAdmin):
    list_display = ("complaint", "decision", "score", "agreement_rate", "created_at")
    list_filter = ("decision",)
    search_fields = ("complaint__complaint_id",)
    readonly_fields = [f.name for f in ValidationResult._meta.fields]
