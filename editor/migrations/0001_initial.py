# Generated by Django 3.1.1 on 2021-01-03 16:42

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Application',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('desc', models.TextField()),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='Packet',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('desc_pars', models.TextField()),
                ('desc_dest', models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name='PacketBehaviour',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('acceptance_check', models.TextField(blank=True, default='')),
                ('enable_check', models.TextField(blank=True, default='')),
                ('repeat_check', models.TextField(blank=True, default='')),
                ('update_action', models.TextField(blank=True, default='')),
                ('start_action', models.TextField(blank=True, default='')),
                ('progress_action', models.TextField(blank=True, default='')),
                ('termination_action', models.TextField(blank=True, default='')),
                ('abort_action', models.TextField(blank=True, default='')),
            ],
        ),
        migrations.CreateModel(
            name='PacketPar',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order', models.SmallIntegerField(default=0)),
                ('group', models.SmallIntegerField(default=0)),
                ('repetition', models.SmallIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='Project',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('desc', models.TextField()),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='owned_projects', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Requirement',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ver_method', models.CharField(choices=[('TST', 'Verification by Test'), ('ANA', 'Verification by Analysis'), ('REV', 'Verification by Review')], max_length=24)),
            ],
        ),
        migrations.CreateModel(
            name='SpecItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cat', models.CharField(choices=[('Requirement', 'An application requirement'), ('DataItemType', 'a data item type'), ('EnumItem', 'An enumerated item'), ('Model', 'A behavioural model for an application feature'), ('Service', 'A cordet service'), ('Packet', 'A packet implementing a service command or report'), ('PacketPar', 'A parameter in a packet'), ('PacketBehaviour', 'The behaviour associated to a packet in an application'), ('VerItem', 'A verification item')], max_length=24)),
                ('name', models.CharField(max_length=255)),
                ('domain', models.CharField(max_length=255)),
                ('title', models.CharField(max_length=255)),
                ('desc', models.TextField(blank=True, default='')),
                ('value', models.TextField(blank=True, default='')),
                ('status', models.CharField(choices=[('DEL', 'Deleted'), ('OBS', 'Obsolete'), ('CNF', 'Confirmed'), ('MOD', 'Modified'), ('NEW', 'New')], default='NEW', max_length=20)),
                ('updated_at', models.DateTimeField()),
                ('justification', models.TextField(blank=True, default='')),
                ('remarks', models.TextField(blank=True, default='')),
                ('kind', models.CharField(choices=[('STD', 'Standard Requirement'), ('CNS', 'Constraint Requirement'), ('AP', 'Adaptation Point Requirement'), ('CNS', 'Constant'), ('PAR', 'Configuration Parameter'), ('VAR', 'Global Variable'), ('PCK', 'Packet Parameter'), ('ENUM', 'Enumerated'), ('NOT_ENUM', 'Not Enumerated'), ('SM', 'State Machine'), ('PR', 'Procedure'), ('REP', 'Report'), ('CMD', 'Command'), ('DISC', 'Discriminant'), ('HK', 'Housekeeping Parameter'), ('PCK', 'Packet Parameter'), ('PROV', 'Service Provider'), ('USER', 'Service User'), ('TST', 'Test Case'), ('REV', 'Review Item'), ('ANA', 'Analysis Item')], max_length=24)),
                ('application', models.ForeignKey(default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='application_spec_items', to='editor.application')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='owned_spec_items', to=settings.AUTH_USER_MODEL)),
                ('packet', models.OneToOneField(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, to='editor.packet')),
                ('packet_behaviour', models.OneToOneField(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, to='editor.packetbehaviour')),
                ('packet_par', models.OneToOneField(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, to='editor.packetpar')),
                ('parent', models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='children', to='editor.specitem')),
                ('previous', models.OneToOneField(default=None, null=True, on_delete=django.db.models.deletion.SET_DEFAULT, to='editor.specitem')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='project_spec_items', to='editor.project')),
                ('req', models.OneToOneField(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, to='editor.requirement')),
            ],
        ),
        migrations.CreateModel(
            name='VerItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pre_cond', models.TextField(blank=True, default='')),
                ('post_cond', models.TextField(blank=True, default='')),
                ('close_out', models.TextField(blank=True, default='')),
                ('ver_status', models.CharField(choices=[('OPEN', 'Verification Still Open'), ('CLOSED', 'Verification Closed')], max_length=24)),
            ],
        ),
        migrations.CreateModel(
            name='VerItemToSpecItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('desc', models.TextField(blank=True, default='')),
                ('spec_item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ver_item_links', to='editor.specitem')),
                ('ver_item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='spec_item_links', to='editor.specitem')),
            ],
        ),
        migrations.CreateModel(
            name='ValSet',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('updated_at', models.DateField(auto_now=True)),
                ('name', models.CharField(default='Default', max_length=24)),
                ('desc', models.TextField()),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='val_sets', to='editor.project')),
            ],
        ),
        migrations.AddField(
            model_name='specitem',
            name='val_set',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='val_set_spec_items', to='editor.valset'),
        ),
        migrations.AddField(
            model_name='specitem',
            name='ver_item',
            field=models.OneToOneField(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, to='editor.veritem'),
        ),
        migrations.CreateModel(
            name='Release',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('desc', models.TextField()),
                ('updated_at', models.DateTimeField()),
                ('project_version', models.PositiveSmallIntegerField(default='0')),
                ('application_version', models.PositiveSmallIntegerField(default='0')),
                ('previous', models.OneToOneField(default=None, null=True, on_delete=django.db.models.deletion.SET_DEFAULT, to='editor.release')),
                ('release_author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ProjectUser',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('updated_at', models.DateField(auto_now=True)),
                ('role', models.CharField(choices=[('R1', 'Role 1'), ('R2', 'Role 2')], default='R1', max_length=16)),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='project_users', to='editor.project')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='used_projects', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='project',
            name='release',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='editor.release'),
        ),
        migrations.AddField(
            model_name='packet',
            name='disc',
            field=models.ForeignKey(blank=True, default=None, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='der_packets', to='editor.specitem'),
        ),
        migrations.AddField(
            model_name='application',
            name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='applications', to='editor.project'),
        ),
        migrations.AddField(
            model_name='application',
            name='release',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='editor.release'),
        ),
    ]