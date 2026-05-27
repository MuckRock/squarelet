from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0059_alter_organization_options"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="organization",
            name="subscription_id",
        ),
    ]
