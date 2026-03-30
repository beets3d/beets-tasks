from django.db import models


class Customer(models.Model):
    name = models.CharField(max_length=255)
    # Reference to the Google Sheets 'Customer' tag / identifier

    sheet_tag = models.CharField(max_length=255, blank=True, help_text="Google Sheets customer tag")
    external_id = models.CharField(max_length=255, blank=True, help_text="External Id from sheet", db_index=True)

    company_name = models.CharField(max_length=255, blank=True)
    street_address = models.TextField(blank=True)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=128, blank=True)
    country = models.CharField(max_length=128, blank=True)
    zip_code = models.CharField(max_length=32, blank=True)
    phone = models.CharField(max_length=64, blank=True)
    mobile = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)

    # CRM-specific fields requested
    remark = models.TextField(blank=True)
    important = models.BooleanField(default=False)
    last_contact = models.DateTimeField(null=True, blank=True)

    # Classification maintained by admin: retail, school, partner, etc.
    CUSTOMER_TYPE_RETAIL = "retail"
    CUSTOMER_TYPE_SCHOOL = "school"
    CUSTOMER_TYPE_PARTNER = "partner"
    CUSTOMER_TYPE_INSTITUTION = "institution"
    CUSTOMER_TYPE_OTHER = "other"

    CUSTOMER_TYPE_CHOICES = [
        (CUSTOMER_TYPE_RETAIL, "Retail Customer"),
        (CUSTOMER_TYPE_SCHOOL, "School"),
        (CUSTOMER_TYPE_PARTNER, "Partner"),
        (CUSTOMER_TYPE_INSTITUTION, "Institution"),
        (CUSTOMER_TYPE_OTHER, "Other"),
    ]

    customer_type = models.CharField(max_length=32, choices=CUSTOMER_TYPE_CHOICES, blank=True, help_text="Type/class of customer")
    sheet_last_updated = models.DateTimeField(null=True, blank=True)
    sheet_updated_by = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "name"]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.name} ({self.sheet_tag})" if self.sheet_tag else self.name
