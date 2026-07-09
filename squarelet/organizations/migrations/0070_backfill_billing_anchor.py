# Django
from django.db import migrations
from django.db.models import F


def backfill_billing_anchor(apps, schema_editor):
    """Copy update_on -> billing_anchor for all orgs where update_on is set."""
    Organization = apps.get_model("organizations", "Organization")
    Organization.objects.filter(update_on__isnull=False).update(
        billing_anchor=F("update_on")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0069_organization_billing_anchor"),
    ]

    operations = [
        migrations.RunPython(
            backfill_billing_anchor,
            migrations.RunPython.noop,
        ),
    ]
