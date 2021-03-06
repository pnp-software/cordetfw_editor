# Generated by Django 3.1.7 on 2021-07-18 12:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('editor', '0005_auto_20210416_1234'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='cluster',
            field=models.CharField(default='Basic', max_length=24),
        ),
        migrations.AlterField(
            model_name='specitem',
            name='cat',
            field=models.CharField(max_length=24),
        ),
        migrations.AlterField(
            model_name='specitem',
            name='p_kind',
            field=models.CharField(max_length=24),
        ),
        migrations.AlterField(
            model_name='specitem',
            name='s_kind',
            field=models.CharField(max_length=24),
        ),
        migrations.AlterField(
            model_name='specitem',
            name='status',
            field=models.CharField(default='NEW', max_length=20),
        ),
    ]
