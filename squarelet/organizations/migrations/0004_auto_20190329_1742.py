# Generated by Django 2.1.7 on 2019-03-29 17:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0003_auto_20190321_1524'),
    ]

    operations = [
        migrations.AlterField(
            model_name='charge',
            name='amount',
            field=models.PositiveIntegerField(help_text='Amount in cents', verbose_name='amount'),
        ),
    ]
