# Generated by Django 3.2.11 on 2023-06-21 14:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0031_auto_20221115_1637'),
    ]

    operations = [
        migrations.AlterField(
            model_name='organizationchangelog',
            name='reason',
            field=models.PositiveSmallIntegerField(choices=[(0, 'Created'), (1, 'Updated'), (2, 'Failed')], help_text='Which category of change occurred', verbose_name='reason'),
        ),
    ]