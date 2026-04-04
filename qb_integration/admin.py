from django import forms
from django.contrib import admin
from django.urls import reverse
from .models import QuickBooksConfig, QuickBooksWebhookLog, QuickBooksAuditLog
from django.utils.html import format_html

class QuickBooksConfigForm(forms.ModelForm):
    class Meta:
        model = QuickBooksConfig
        fields = '__all__'
        widgets = {
            'client_secret': forms.PasswordInput(render_value=True),
            'webhook_token': forms.PasswordInput(render_value=True),
        }

@admin.register(QuickBooksConfig)
class QuickBooksConfigAdmin(admin.ModelAdmin):
    form = QuickBooksConfigForm
    list_display = ("environment", "client_id", "realm_id", "updated_at", "oauth_login_button")
    search_fields = ("client_id", "realm_id")
    list_filter = ("environment",)
    readonly_fields = ("updated_at", "oauth_login_button")

    fieldsets = (
        ("API Credentials", {
            "fields": ("environment", "client_id", "client_secret", "redirect_uri", "webhook_token")
        }),
        ("OAuth State", {
            "fields": ("realm_id", "refresh_token", "updated_at", "oauth_login_button"),
            "description": 'Use the "Login to QuickBooks" button below to automatically generate the token and realm ID.'
        }),
    )

    def oauth_login_button(self, obj):
        url = reverse("quickbooks-login")
        return format_html(
            f'<a class="button" href="{url}">Login to QuickBooks</a>'
        )
    oauth_login_button.short_description = "OAuth Login"
    oauth_login_button.allow_tags = True

@admin.register(QuickBooksWebhookLog)
class QuickBooksWebhookLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "is_verified", "signature")
    list_filter = ("is_verified", "created_at")
    search_fields = ("body", "signature", "error_message")
    readonly_fields = ("created_at", "body", "signature", "is_verified", "error_message")

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False

@admin.register(QuickBooksAuditLog)
class QuickBooksAuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "method", "status_code", "duration_ms", "success")
    list_filter = ("method", "status_code", "success", "created_at")
    search_fields = ("url", "request_body", "response_body")
    readonly_fields = ("created_at", "method", "url", "status_code", "duration_ms", "success", "request_body", "response_body")

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
