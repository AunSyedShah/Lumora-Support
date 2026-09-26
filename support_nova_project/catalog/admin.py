from django.contrib import admin

from .models import Category, Department, Product, SLARule, Subcategory


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")


class SubcategoryInline(admin.TabularInline):
    model = Subcategory
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_department", "is_active")
    search_fields = ("code", "name")
    inlines = [SubcategoryInline]


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "department", "is_active")
    list_filter = ("category",)
    search_fields = ("code", "name")


@admin.register(SLARule)
class SLARuleAdmin(admin.ModelAdmin):
    list_display = ("priority", "response_hours", "resolution_hours", "at_risk_percent")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "price", "is_active")
