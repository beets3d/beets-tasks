from django.contrib import admin

from .models import AccessLog


class IntegrationFilter(admin.SimpleListFilter):
    title = "integration"
    parameter_name = "integration"

    def lookups(self, request, model_admin):
        return (
            ("jira", "Jira"),
            ("waha", "WAHA"),
            ("core", "MCP Core"),
            ("other", "Other"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "jira":
            return queryset.filter(tool_name__startswith="jira_")
        if value == "waha":
            return queryset.filter(tool_name__startswith="waha_")
        if value == "core":
            return queryset.filter(tool_name="")
        if value == "other":
            return queryset.exclude(tool_name="").exclude(tool_name__startswith="jira_").exclude(tool_name__startswith="waha_")
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
    search_fields = ("client_name", "actor", "tool_name", "issue_key", "message")
    list_filter = (IntegrationFilter, "success", "method", "tool_name", "created_at")
