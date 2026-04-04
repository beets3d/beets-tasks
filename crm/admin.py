from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import Customer
from .models import CustomerType


class CustomerAdminForm(forms.ModelForm):
    # Treat email as plain text in admin to allow multiple emails in one field
    email = forms.CharField(required=False, widget=forms.TextInput())

    class Meta:
        model = Customer
        fields = "__all__"


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    form = CustomerAdminForm
    list_display = (
        "name",
        "external_id",
        "company_name",
        "address_display",
        "customer_type",
        "email",
        "attn",
        "fax",
        "website_link",
        "phone",
        "mobile",
        "important",
        "last_contact",
        "in_quickbooks",
        "sheet_last_updated",
        "updated_at",
    )
    list_editable = ("important",)
    list_filter = (
        "important",
        "in_quickbooks",
        "customer_type",
        "country",
        ("last_contact", admin.DateFieldListFilter),
    )
    search_fields = ("name", "remark", "company_name", "email", "phone", "external_id")
    date_hierarchy = "last_contact"
    ordering = ("-updated_at",)
    list_per_page = 50
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("name", "external_id", "company_name", "customer_type")} ),
        ("Address", {"fields": ("street_address", ("city", "state", "zip_code"), "country")} ),
        ("Location", {"fields": (("latitude", "longitude"),)} ),
        ("Contact", {"fields": ("email", "website_url", ("phone", "mobile", "fax"), "attn", "last_contact")} ),
        ("CRM", {"fields": ("remark", "profile", "important")} ),
        ("QuickBooks", {"fields": (("in_quickbooks", "quickbooks_id"),)} ),
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

    def website_link(self, obj):
        url = getattr(obj, "website_url", None)
        if not url:
            return ""
        return format_html('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>', url, url)

    website_link.short_description = "Website"
    website_link.admin_order_field = "website_url"

    def address_display(self, obj):
        parts = [
            (obj.street_address or "").strip(),
            (obj.city or "").strip(),
            (obj.state or "").strip(),
            (obj.zip_code or "").strip(),
            (obj.country or "").strip(),
        ]
        addr = ", ".join([p for p in parts if p])
        if not addr:
            return ""
        return addr if len(addr) <= 60 else addr[:57] + "..."

    address_display.short_description = "Address"


@admin.register(CustomerType)
class CustomerTypeAdmin(admin.ModelAdmin):
    list_display = ("key", "label")
    search_fields = ("key", "label")
