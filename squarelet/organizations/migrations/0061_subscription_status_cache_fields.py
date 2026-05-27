# Generated migration for subscription status cache fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0060_customer_card_cache_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="stripe_status",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
        migrations.AddField(
            model_name="subscription",
            name="current_period_end",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
