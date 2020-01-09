# Generated by Django 2.1.7 on 2019-12-20 16:22

# Django
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("organizations", "0010_auto_20191213_1627")]

    operations = [
        migrations.AlterField(
            model_name="organization",
            name="plan",
            field=models.ForeignKey(
                blank=True,
                db_column="plan_id",
                help_text="The current plan this organization is subscribed to",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="organizations.Plan",
                verbose_name="plan",
            ),
        ),
        migrations.RenameField(
            model_name="organization", old_name="plan", new_name="_plan"
        ),
        migrations.AlterField(
            model_name="entitlement",
            name="client",
            field=models.ForeignKey(
                help_text="Client this entitlement grants access to",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="entitlements",
                to="oidc_provider.Client",
                verbose_name="client",
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="plans",
            field=models.ManyToManyField(
                blank=True,
                help_text="Plans this organization is subscribed to",
                related_name="organizations",
                through="organizations.Subscription",
                to="organizations.Plan",
                verbose_name="plans",
            ),
        ),
        migrations.AlterField(
            model_name="organizationchangelog",
            name="reason",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "Created"), (0, "Updated"), (0, "Failed")],
                help_text="Which category of change occurred",
                verbose_name="reason",
            ),
        ),
        migrations.AlterField(
            model_name="plan",
            name="pay_to",
            field=models.PositiveSmallIntegerField(
                choices=[(0, "MuckRock"), (1, "PressPass")],
                default=0,
                help_text="Which company's stripe account is used for subscrpitions to this plan",
                verbose_name="pay to",
            ),
        ),
    ]
