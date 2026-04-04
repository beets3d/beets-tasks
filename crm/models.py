from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=255)
    # Reference to the Google Sheets 'Customer' tag / identifier (removed)
    external_id = models.CharField(max_length=255, blank=True, help_text="External Id from sheet", db_index=True)

    company_name = models.CharField(max_length=255, blank=True)
    street_address = models.TextField(blank=True)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=128, blank=True)
    country = models.CharField(max_length=128, blank=True)
    zip_code = models.CharField(max_length=32, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    mobile = models.CharField(max_length=64, blank=True)
    # Attention contact person and fax number
    attn = models.CharField(max_length=255, blank=True)
    fax = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    # Additional contact persons (up to 3 total)
    attn_2 = models.CharField(max_length=255, blank=True)
    phone_2 = models.CharField(max_length=64, blank=True)
    email_2 = models.EmailField(blank=True)
    attn_3 = models.CharField(max_length=255, blank=True)
    phone_3 = models.CharField(max_length=64, blank=True)
    email_3 = models.EmailField(blank=True)
    # Optional website / URL for the customer
    website_url = models.URLField(blank=True, help_text="Customer website or URL")

    # CRM-specific fields requested
    remark = models.TextField(blank=True)
    # Long-form customer profile or description
    profile = models.TextField(blank=True, help_text="Customer profile / description")
    important = models.BooleanField(default=False)
    last_contact = models.DateTimeField(null=True, blank=True)

    # QuickBooks Integration
    quickbooks_id = models.CharField(max_length=64, blank=True, help_text="QuickBooks Customer ID", db_index=True)
    in_quickbooks = models.BooleanField(default=False, help_text="Indicates if this customer is synced with QuickBooks")



    # customer_type is now a foreign key to CustomerType (see below)
    customer_type = models.ForeignKey("crm.CustomerType", null=True, blank=True, on_delete=models.SET_NULL, related_name="customers")
    sheet_last_updated = models.DateTimeField(null=True, blank=True)
    sheet_updated_by = models.CharField(max_length=255, blank=True)
    # optional geolocation for map display (latitude/longitude)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "name"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.name



class CustomerType(models.Model):
    """Extendable customer type records; `key` is the stable identifier used by integrations."""
    key = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.label or self.key
