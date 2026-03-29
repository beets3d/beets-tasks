from django.contrib import admin

from .models import AccessLog


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "client_name",
        "method",
        "tool_name",
        "actor",
        "project_keys",
        "issue_key",
        "success",
        "status_code",
        "duration_ms",
    )
    search_fields = ("client_name", "actor", "tool_name", "issue_key", "message")
    list_filter = ("success", "method", "tool_name", "created_at")
