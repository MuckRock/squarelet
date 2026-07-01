# Django
from django.db import migrations, models


def migrate_quantity_from_org(apps, schema_editor):
    """Copy org.max_users to each of the org's subscriptions."""
    Subscription = apps.get_model("organizations", "Subscription")
    for sub in Subscription.objects.select_related("organization").iterator(
        chunk_size=200
    ):
        sub.quantity = sub.organization.max_users
        sub.save(update_fields=["quantity"])


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0067_remove_entitlementgrant_update_on"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="quantity",
            field=models.PositiveIntegerField(
                default=1,
                verbose_name="quantity",
                help_text=(
                    "Number of units of this plan's resources granted to the organization"
                ),
            ),
        ),
        migrations.RunPython(
            migrate_quantity_from_org,
            migrations.RunPython.noop,
        ),
    ]
