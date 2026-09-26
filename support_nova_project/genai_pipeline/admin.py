from django.contrib import admin

from .models import GenAIAnalysis, PromptTemplate


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "version", "is_active", "created_at")
    list_filter = ("name", "is_active")
    readonly_fields = ("created_at",)


@admin.register(GenAIAnalysis)
class GenAIAnalysisAdmin(admin.ModelAdmin):
    list_display = ("complaint", "status", "prompt_template", "model", "latency_ms", "created_at")
    list_filter = ("status", "model", "prompt_template")
    search_fields = ("complaint__complaint_id",)
    readonly_fields = [f.name for f in GenAIAnalysis._meta.fields]
