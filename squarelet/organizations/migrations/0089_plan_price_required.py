from django.db import migrations, models
import django.db.models.deletion


def refuse_unpriced_lines(apps, schema_editor):
    """Name the lines still without a price, which the database error would not."""
    SubscriptionItem = apps.get_model("organizations", "SubscriptionItem")
    unpriced = SubscriptionItem.objects.filter(plan_price__isnull=True).values_list(
        "subscription__organization__slug", "plan__slug"
    )
    if unpriced:
        lines = "\n".join(f"  - {org}: {plan}" for org, plan in unpriced)
        raise RuntimeError(
            f"{len(unpriced)} line(s) have no price; price them first, with "
            f"release 5's backfill_plan_prices or by hand:\n{lines}"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0088_plan_archived"),
    ]

    operations = [
        migrations.RunPython(refuse_unpriced_lines, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subscriptionitem",
            name="plan_price",
            field=models.ForeignKey(
                help_text="The price this line is billed at",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="subscription_items",
                to="organizations.planprice",
                verbose_name="plan price",
            ),
        ),
    ]
