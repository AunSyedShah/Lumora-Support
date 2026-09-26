from django.contrib import admin

from .models import Complaint, ComplaintAttachment, Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_ref", "customer", "product", "amount", "status", "order_date", "delivery_date")
    list_filter = ("status", "product")
    search_fields = ("order_ref", "customer__username")


class AttachmentInline(admin.TabularInline):
    model = ComplaintAttachment
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("complaint_id", "title", "customer", "status", "channel", "match_type", "created_at")
    list_filter = ("status", "channel", "match_type")
    search_fields = ("complaint_id", "title", "description", "customer__username")
    readonly_fields = ("normalized_text", "text_hash", "extracted_metadata", "security_flags", "facts", "similarity")
    exclude = ("embedding",)
    inlines = [AttachmentInline]
