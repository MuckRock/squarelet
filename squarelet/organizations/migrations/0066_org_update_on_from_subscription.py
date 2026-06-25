# Django
from django.db import migrations, models


def migrate_update_on_to_org(apps, schema_editor):
    """Copy the earliest subscription update_on to each organization."""
    Organization = apps.get_model("organizations", "Organization")
    for org in Organization.objects.prefetch_related("subscriptions").iterator(
        chunk_size=200
    ):
        dates = [
            sub.update_on
            for sub in org.subscriptions.all()
            if sub.update_on is not None
        ]
        if dates:
            org.update_on = min(dates)
            org.save(update_fields=["update_on"])


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0065_merge_20260612_1043"),
    ]

    operations = [
        # Step 1: add nullable update_on to Organization
        migrations.AddField(
            model_name="organization",
            name="update_on",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="date update",
                help_text=(
                    "Anchor date for monthly resource refreshes "
                    "across all subscriptions"
                ),
            ),
        ),
        # Step 2: copy existing data from subscriptions to org
        migrations.RunPython(
            migrate_update_on_to_org,
            migrations.RunPython.noop,
        ),
        # Step 3: remove update_on from Subscription
        migrations.RemoveField(
            model_name="subscription",
            name="update_on",
        ),
    ]
