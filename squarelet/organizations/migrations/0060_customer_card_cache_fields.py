# Generated migration for customer card cache fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0059_alter_organization_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="card_brand",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="customer",
            name="card_last4",
            field=models.CharField(blank=True, default="", max_length=4),
        ),
        migrations.AddField(
            model_name="customer",
            name="card_exp_month",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customer",
            name="card_exp_year",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customer",
            name="stripe_payment_method_id",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
