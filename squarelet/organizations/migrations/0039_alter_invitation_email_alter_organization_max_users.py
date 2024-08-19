# Generated by Django 4.2 on 2024-08-19 18:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0038_merge_20240603_1038"),
    ]

    operations = [
        migrations.AlterField(
            model_name="invitation",
            name="email",
            field=models.EmailField(
                blank=True,
                help_text="The email address to send this invitation to",
                max_length=254,
                verbose_name="email",
            ),
        ),
        migrations.AlterField(
            model_name="organization",
            name="max_users",
            field=models.IntegerField(
                default=5,
                help_text="The number of resource blocks this organization receives monthly",
                verbose_name="resource blocks",
            ),
        ),
    ]
