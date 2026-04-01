from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="customer",
            name="sheet_tag",
        ),
    ]
