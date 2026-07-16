# Generated manually

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        (
            "organizations",
            "0075_migrate_payment_cache_to_paymentmethod",
        ),
    ]

    operations = [
        migrations.RemoveField(
            model_name="customer",
            name="payment_brand",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="payment_last4",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="payment_exp_month",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="payment_exp_year",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="stripe_payment_method_id",
        ),
    ]
