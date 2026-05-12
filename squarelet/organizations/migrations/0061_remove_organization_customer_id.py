from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0060_remove_organization_subscription_id"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="organization",
            name="customer_id",
        ),
    ]
