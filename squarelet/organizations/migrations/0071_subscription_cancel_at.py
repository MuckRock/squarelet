# Django
from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0070_backfill_billing_anchor"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="cancel_at",
            field=models.DateField(
                verbose_name=_("cancel at"),
                null=True,
                blank=True,
                help_text=_(
                    "Date when Stripe will terminate this subscription. "
                    "Set when cancel() is called. "
                    "Null for free plans or legacy records."
                ),
            ),
        ),
    ]
