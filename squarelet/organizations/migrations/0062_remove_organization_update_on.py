from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0061_remove_organization_customer_id"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="organization",
            name="update_on",
        ),
    ]
