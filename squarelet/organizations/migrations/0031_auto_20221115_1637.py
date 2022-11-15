# Generated by Django 3.2.11 on 2022-11-15 21:37

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0030_auto_20220817_1454'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='charge',
            name='stripe_account',
        ),
        migrations.RemoveField(
            model_name='plan',
            name='stripe_account',
        ),
        migrations.AlterField(
            model_name='customer',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='customers', to='organizations.organization', unique=True, verbose_name='organization'),
        ),
        migrations.AlterUniqueTogether(
            name='customer',
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name='customer',
            name='stripe_account',
        ),
    ]
