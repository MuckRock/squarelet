# Django
from django.db import migrations, models
import django.db.models.deletion


def refuse_if_any_line_lacks_a_price(apps, schema_editor):
    """Stop before the column changes, with something an operator can act on.

    `AlterField` on its own answers a null row with an IntegrityError
    naming the constraint, which says what broke but not which
    subscriptions or what to do about them.

    Every line should have been given a price by `backfill_plan_prices`,
    which ran in release 5 and is deleted by this one - the state it
    existed to repair cannot exist once this migration has run.  So a
    database that arrives here with null rows has not had that release,
    and the fix is not in this checkout: deploy release 5's code there,
    run the backfill, and come back.
    """
    SubscriptionItem = apps.get_model("organizations", "SubscriptionItem")
    stranded = list(
        SubscriptionItem.objects.filter(plan_price__isnull=True).values_list(
            "subscription__organization__slug", "plan__slug"
        )[:20]
    )
    if not stranded:
        return
    total = SubscriptionItem.objects.filter(plan_price__isnull=True).count()
    listed = "\n".join(f"  - {org}: {plan}" for org, plan in stranded)
    more = f"\n  ... and {total - len(stranded)} more" if total > len(stranded) else ""
    raise RuntimeError(
        f"{total} subscription line(s) still have no plan_price, so this "
        f"column cannot be made non-null:\n"
        f"{listed}{more}\n\n"
        f"These should have been migrated by `backfill_plan_prices` in "
        f"release 5.  That command is deleted in this release, so the fix "
        f"is not in this checkout: run it from release 5's code against "
        f"this database until it reports none unexpected, then deploy "
        f"this again.  It was idempotent."
    )


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0087_merge_20260918_1220"),
    ]

    operations = [
        migrations.RunPython(
            refuse_if_any_line_lacks_a_price,
            migrations.RunPython.noop,
            elidable=False,
        ),
        migrations.AlterField(
            model_name="subscriptionitem",
            name="plan_price",
            field=models.ForeignKey(
                help_text=(
                    "The price this subscription is billed at.  Every line "
                    "has one: the plan a line is on is now a fact about its "
                    "price, not the other way round."
                ),
                on_delete=django.db.models.deletion.PROTECT,
                related_name="subscription_items",
                to="organizations.planprice",
                verbose_name="plan price",
            ),
        ),
    ]
