from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0076_remove_customer_payment_cache_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="charge",
            name="receipt_pdf",
            field=models.FileField(
                blank=True,
                null=True,
                upload_to="receipts/",
                verbose_name="receipt pdf",
            ),
        ),
    ]
