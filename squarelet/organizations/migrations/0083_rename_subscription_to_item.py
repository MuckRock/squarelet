from django.db import migrations


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
    ]
