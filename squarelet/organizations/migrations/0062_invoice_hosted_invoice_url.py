# Generated migration for invoice hosted URL cache field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0061_subscription_status_cache_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="hosted_invoice_url",
            field=models.URLField(blank=True, default=""),
        ),
    ]
