from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "external_id",
        "company_name",
        "sheet_tag",
        "customer_type",
        "email",
        "phone",
        "mobile",
        "important",
        "last_contact",
        "sheet_last_updated",
        "updated_at",
    )
    list_editable = ("important",)
    list_filter = (
        "important",
        "customer_type",
        "country",
        ("last_contact", admin.DateFieldListFilter),
    )
    search_fields = ("name", "sheet_tag", "remark", "company_name", "email", "phone", "external_id")
    date_hierarchy = "last_contact"
    ordering = ("-updated_at",)
    list_per_page = 50
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("name", "external_id", "company_name", "sheet_tag", "customer_type")} ),
        ("Address", {"fields": ("street_address", ("city", "state", "zip_code"), "country")} ),
        ("Contact", {"fields": ("email", ("phone", "mobile"), "last_contact")} ),
        ("CRM", {"fields": ("remark", "important")} ),
        ("Sheet Metadata", {"fields": ("sheet_last_updated", "sheet_updated_by")} ),
        ("Timestamps", {"fields": ("created_at", "updated_at")} ),
    )

    actions = ("mark_important", "mark_not_important")

    def mark_important(self, request, queryset):
        updated = queryset.update(important=True)
        self.message_user(request, f"Marked {updated} customers as important")

    mark_important.short_description = "Mark selected customers as important"

    def mark_not_important(self, request, queryset):
        updated = queryset.update(important=False)
        self.message_user(request, f"Marked {updated} customers as not important")

    mark_not_important.short_description = "Unmark selected customers as important"
