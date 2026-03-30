from django.contrib import admin

from .models import AccessLog


admin.site.site_title = "Beets Task"
admin.site.site_header = "Beets Task"
admin.site.index_title = "Beets Task Admin"


class IntegrationFilter(admin.SimpleListFilter):
    title = "integration"
    parameter_name = "integration"

    def lookups(self, request, model_admin):
        return (
            ("jira", "Jira"),
            ("waha", "WAHA"),
            ("google", "Google Sheets"),
            ("core", "MCP Core"),
            ("other", "Other"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "jira":
            return queryset.filter(tool_name__startswith="jira_")
        if value == "waha":
            return queryset.filter(tool_name__startswith="waha_")
        if value == "google":
            return queryset.filter(tool_name__startswith="google_sheets_")
        if value == "core":
            return queryset.filter(tool_name="")
        if value == "other":
            return (
                queryset.exclude(tool_name="")
                .exclude(tool_name__startswith="jira_")
                .exclude(tool_name__startswith="waha_")
                .exclude(tool_name__startswith="google_sheets_")
            )
        return queryset


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
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    search_fields = ("client_name", "actor", "tool_name", "issue_key", "message")
    list_filter = (IntegrationFilter, "success", "method", "tool_name", "created_at")
    readonly_fields = (
        "created_at",
        "client_name",
        "actor",
        "method",
        "tool_name",
        "request_ip",
        "project_keys",
        "issue_key",
        "success",
        "status_code",
        "duration_ms",
        "message",
    )
    list_per_page = 50

    fieldsets = (
        (None, {"fields": ("created_at", "success", "status_code", "duration_ms")}),
        ("Request", {"fields": ("client_name", "actor", "request_ip", "method", "tool_name")}),
        ("Issue Context", {"fields": ("project_keys", "issue_key")}),
        ("Details", {"fields": ("message",)}),
    )
