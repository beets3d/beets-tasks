from django.db import migrations, models


def migrate_customer_type(apps, schema_editor):
    Customer = apps.get_model("crm", "Customer")
    CustomerType = apps.get_model("crm", "CustomerType")

    # collect distinct existing string values
    conn = schema_editor.connection
    with conn.cursor() as cursor:
        cursor.execute("SELECT DISTINCT customer_type FROM crm_customer WHERE customer_type IS NOT NULL AND customer_type != '';")
        rows = cursor.fetchall()
    existing = [r[0] for r in rows]

    mapping = {}
    for key in existing:
        ct = CustomerType.objects.create(key=key, label=key)
        mapping[key] = ct.id

    # assign FK where customer_type string exists
    for cust in Customer.objects.all():
        old = getattr(cust, "customer_type", None)
        if old:
            ct = CustomerType.objects.filter(key=old).first()
            if ct:
                # assign to temporary FK field
                setattr(cust, "customer_type_fk", ct)
                cust.save(update_fields=["customer_type_fk"]) 


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0004_merge_0003_add_lat_lng_0003_customer_customer_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ("key", models.CharField(max_length=64, unique=True)),
                ("label", models.CharField(max_length=255, blank=True)),
            ],
        ),
        # temporary FK field to hold CustomerType during migration
        migrations.AddField(
            model_name="customer",
            name="customer_type_fk",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, related_name="customers", to="crm.customertype"),
        ),
        migrations.RunPython(migrate_customer_type, reverse_code=migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="customer",
            name="customer_type",
        ),
        migrations.RenameField(
            model_name="customer",
            old_name="customer_type_fk",
            new_name="customer_type",
        ),
    ]
