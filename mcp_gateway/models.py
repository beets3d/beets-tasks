from django.db import models


class AccessLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    client_name = models.CharField(max_length=128, blank=True)
    actor = models.CharField(max_length=128, blank=True)
    method = models.CharField(max_length=64)
    tool_name = models.CharField(max_length=128, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    project_keys = models.CharField(max_length=512, blank=True)
    issue_key = models.CharField(max_length=64, blank=True)
    success = models.BooleanField(default=False)
    status_code = models.PositiveIntegerField(default=200)
    duration_ms = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at.isoformat()} {self.method} {self.tool_name} {self.success}"

