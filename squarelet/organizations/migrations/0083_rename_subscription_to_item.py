import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Rename Subscription to SubscriptionItem.

    Hand-written: makemigrations cannot infer a rename without being asked
    interactively, and non-interactively it emits CreateModel + DeleteModel,
    which would drop every subscription.

    First half of splitting the model in two.  A SubscriptionItem is one line
    on a Stripe subscription; the Subscription that owns those lines arrives
    next.  Renaming on its own first means every existing reference fails
    loudly rather than silently binding to a `Subscription` that now means
    something different.
    """

    dependencies = [
        ("organizations", "0082_plan_tiers_and_packs"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="Subscription",
            new_name="SubscriptionItem",
        ),
        # Nullable here, and dropped entirely by the next migration once the
        # organization has moved to the parent.  It is relaxed in *this*
        # migration rather than alongside the data move so that reversing
        # works: Postgres refuses to ALTER a table in the same transaction
        # that has just written to it, so the NOT NULL has to be restored in
        # a transaction of its own.
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
