# Django
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0066_org_update_on_from_subscription"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="entitlementgrant",
            name="update_on",
        ),
    ]
