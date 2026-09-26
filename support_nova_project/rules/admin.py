from django.contrib import admin

from .models import EscalationRule, ResolutionRule


@admin.register(ResolutionRule)
class ResolutionRuleAdmin(admin.ModelAdmin):
    list_display = ("rule_id", "subcategory", "department", "urgency", "priority", "escalation_level", "policy_id", "is_active")
    list_filter = ("category", "priority", "escalation_level", "is_active")
    search_fields = ("rule_id", "description", "policy_id")
    filter_horizontal = ("supporting_departments",)


@admin.register(EscalationRule)
class EscalationRuleAdmin(admin.ModelAdmin):
    list_display = ("rule_id", "name", "escalation_level", "target_department", "min_priority", "is_active")
    list_filter = ("escalation_level", "is_active")
    search_fields = ("rule_id", "name")
