import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Rename Subscription to SubscriptionItem.

    Hand-written: non-interactively makemigrations emits CreateModel +
    DeleteModel for a rename, which would drop every subscription.

    Renamed on its own, before the new `Subscription` arrives, so every
    existing reference fails loudly rather than binding to a name that now
    means something different.
    """

    dependencies = [
        ("organizations", "0083_merge_20260909_1055"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Subscription",
            new_name="SubscriptionItem",
        ),
        # Relaxed here rather than alongside the data move so reversing
        # works: Postgres refuses to ALTER a table it has just written to.
        migrations.AlterField(
            model_name="subscriptionitem",
            name="organization",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="subscription_items",
                to="organizations.organization",
                verbose_name="organization",
            ),
        ),
        migrations.AlterField(
            model_name="subscriptionitem",
            name="plan",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="subscription_items",
                to="organizations.plan",
                verbose_name="plan",
            ),
        ),
        migrations.AlterField(
            model_name="subscriptionitem",
            name="plan_price",
            field=models.ForeignKey(
                blank=True,
                help_text="The price this subscription is billed at.  Nullable until every subscription has been migrated off the legacy plan foreign key.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="subscription_items",
                to="organizations.planprice",
                verbose_name="plan price",
            ),
        ),
    ]
