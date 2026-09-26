from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class SupportNovaUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "customer_type", "is_active")
    list_filter = ("role", "customer_type", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("SupportNova", {"fields": ("role", "customer_type", "phone")}),
    )
