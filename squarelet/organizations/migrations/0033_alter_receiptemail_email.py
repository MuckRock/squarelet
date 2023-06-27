# Generated by Django 4.2 on 2023-06-26 20:19

# Django
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0032_alter_organizationchangelog_reason"),
        ("users", "0010_case_insenstive_collation"),
    ]

    operations = [
        migrations.AlterField(
            model_name="receiptemail",
            name="email",
            field=models.EmailField(
                db_collation="case_insensitive",
                help_text="The email address to send the receipt to",
                max_length=254,
                verbose_name="email",
            ),
        ),
    ]
