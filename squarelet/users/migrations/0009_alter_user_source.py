# Generated by Django 3.2.11 on 2023-06-21 14:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_user_bio'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='source',
            field=models.CharField(choices=[('muckrock', 'MuckRock'), ('documentcloud', 'DocumentCloud'), ('foiamachine', 'FOIA Machine'), ('squarelet', 'Squarelet'), ('biglocalnews', 'Big Local News'), ('agendawatch', 'Agenda Watch')], default='squarelet', help_text='Which service did this user originally sign up for?', max_length=13, verbose_name='source'),
        ),
    ]
