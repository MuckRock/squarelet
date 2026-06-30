from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0063_remove_organization_plan"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="organization",
            name="next_plan",
        ),
    ]
