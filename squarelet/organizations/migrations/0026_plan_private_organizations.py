# Generated by Django 2.0.6 on 2019-02-13 20:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0025_auto_20190212_1657'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='private_organizations',
            field=models.ManyToManyField(help_text='For private plans, organizations which should have access to this plan', related_name='private_plans', to='organizations.Organization'),
        ),
    ]