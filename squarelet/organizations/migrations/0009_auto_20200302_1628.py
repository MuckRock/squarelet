# Generated by Django 2.1.7 on 2020-03-02 21:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0008_plan_requires_updates'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='verified_journalist',
            field=models.BooleanField(default=False, help_text='This organization is a verified jorunalistic organization', verbose_name='verified journalist'),
        ),
        migrations.AlterField(
            model_name='plan',
            name='private_organizations',
            field=models.ManyToManyField(blank=True, help_text='For private plans, organizations which should have access to this plan', related_name='private_plans', to='organizations.Organization', verbose_name='private organizations'),
        ),
    ]
