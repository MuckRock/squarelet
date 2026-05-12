from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0062_remove_organization_update_on"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="organization",
            name="_plan",
        ),
    ]
