# Generated by Django 4.2.18 on 2025-04-04 15:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0039_alter_invitation_email_alter_organization_max_users"),
    ]

    operations = [
        migrations.AddField(
            model_name="membership",
            name="created_at",
            field=models.DateTimeField(
                blank=True, default=None, null=True, verbose_name="created_at"
            ),
        ),
    ]
