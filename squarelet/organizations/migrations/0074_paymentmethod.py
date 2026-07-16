# Generated manually

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0073_merge_20260716_0928"),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentMethod",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "method_type",
                    models.CharField(
                        choices=[
                            ("card", "Card"),
                            ("bank_account", "Bank Account"),
                        ],
                        default="card",
                        max_length=20,
                    ),
                ),
                (
                    "brand",
                    models.CharField(
                        blank=True, default="", max_length=64
                    ),
                ),
                (
                    "last4",
                    models.CharField(
                        blank=True, default="", max_length=4
                    ),
                ),
                (
                    "exp_month",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True
                    ),
                ),
                (
                    "exp_year",
                    models.PositiveSmallIntegerField(
                        blank=True, null=True
                    ),
                ),
                (
                    "stripe_id",
                    models.CharField(
                        blank=True, default="", max_length=255
                    ),
                ),
                ("is_default", models.BooleanField(default=True)),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=(
                            django.db.models.deletion.CASCADE
                        ),
                        related_name="payment_methods",
                        to="organizations.customer",
                    ),
                ),
            ],
        ),
    ]
