# Generated by Django 2.0.6 on 2018-12-14 18:27

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('oidc', '0001_initial'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='clientprofile',
            name='secret_key',
        ),
    ]
