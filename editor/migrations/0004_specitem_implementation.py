# Generated by Django 3.1.7 on 2021-03-28 22:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('editor', '0003_specitem_change_log'),
    ]

    operations = [
        migrations.AddField(
            model_name='specitem',
            name='implementation',
            field=models.TextField(blank=True, default=''),
        ),
    ]