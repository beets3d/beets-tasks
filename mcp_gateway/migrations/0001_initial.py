from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AccessLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client_name", models.CharField(blank=True, max_length=128)),
                ("actor", models.CharField(blank=True, max_length=128)),
                ("method", models.CharField(max_length=64)),
                ("tool_name", models.CharField(blank=True, max_length=128)),
                ("request_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("project_keys", models.CharField(blank=True, max_length=512)),
                ("issue_key", models.CharField(blank=True, max_length=64)),
                ("success", models.BooleanField(default=False)),
                ("status_code", models.PositiveIntegerField(default=200)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                ("message", models.TextField(blank=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
