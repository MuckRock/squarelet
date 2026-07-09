# Django
from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0068_subscription_quantity"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="billing_anchor",
            field=models.DateField(
                verbose_name=_("billing anchor"),
                null=True,
                blank=True,
                help_text=_(
                    "Stable Stripe billing_cycle_anchor for new subscriptions. "
                    "Set from first subscription period_end. Does not advance monthly."
                ),
            ),
        ),
    ]
