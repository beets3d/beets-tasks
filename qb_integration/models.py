from django.db import models

class QuickBooksConfig(models.Model):
    client_id = models.CharField(max_length=255, blank=True, help_text="QuickBooks Client ID")
    client_secret = models.CharField(max_length=255, blank=True, help_text="QuickBooks Client Secret")
    environment = models.CharField(
        max_length=20,
        choices=[("sandbox", "Sandbox"), ("production", "Production")],
        default="sandbox"
    )
    redirect_uri = models.URLField(max_length=255, blank=True, help_text="OAuth Redirect URI")
    realm_id = models.CharField(max_length=64, blank=True, help_text="Company ID (Realm ID)")
    refresh_token = models.TextField(blank=True, help_text="OAuth Refresh Token")
    webhook_token = models.CharField(max_length=255, blank=True, help_text="Webhook Verifier Token")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "QuickBooks Configuration"
        verbose_name_plural = "QuickBooks Configurations"

    def __str__(self) -> str:
        return f"QuickBooks Config ({self.environment})"


class QuickBooksWebhookLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    body = models.TextField(blank=True, help_text="Raw payload body")
    signature = models.CharField(max_length=255, blank=True, help_text="Intuit Signature")
    is_verified = models.BooleanField(default=False, help_text="Signature verified successfully")
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Webhook Log"
        verbose_name_plural = "Webhook Logs"

    def __str__(self) -> str:
        return f"Webhook Log {self.id} on {self.created_at.strftime('%Y-%m-%d %H:%M:%S')} - Verified: {self.is_verified}"

class QuickBooksAuditLog(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=10, blank=True)
    url = models.URLField(max_length=1024, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    request_body = models.TextField(blank=True, help_text="Request Payload")
    response_body = models.TextField(blank=True, help_text="Response Payload")
    success = models.BooleanField(default=False)
    duration_ms = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self) -> str:
        return f"{self.created_at.strftime('%Y-%m-%d %H:%M:%S')} - {self.method} {self.status_code} - {self.success}"
