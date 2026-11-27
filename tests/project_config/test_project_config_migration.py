"""Phase 1: migration 0012 (Project.config) applies forward and backward without touching existing data."""
from datetime import datetime, timezone

from django.db import connection
from django.core.management import call_command
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [('editor', '0013_release_version_int_default')]
AFTER = [('editor', '0014_project_config')]


def project_columns():
    with connection.cursor() as cursor:
        return [column.name for column in connection.introspection.get_table_description(cursor, 'editor_project')]


class ProjectConfigMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def create_data(self, apps):
        User = apps.get_model('auth', 'User')
        Release = apps.get_model('editor', 'Release')
        Project = apps.get_model('editor', 'Project')
        ValSet = apps.get_model('editor', 'ValSet')
        SpecItem = apps.get_model('editor', 'SpecItem')
        stamp = datetime(2023, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        owner = User.objects.create(username='owner')
        release = Release.objects.create(release_author=owner, desc='r', updated_at=stamp)
        project = Project.objects.create(name='P', desc='d', cats='Service', owner=owner, release=release)
        val_set = ValSet.objects.create(project=project, name='Default', desc='d')
        SpecItem.objects.create(cat='Service', name='n', domain='d', project=project, title='t', owner=owner,
                                val_set=val_set, updated_at=stamp, created_at=stamp, value='v', t1='x', n1=3)

    def snapshot(self, apps):
        Project, SpecItem = apps.get_model('editor', 'Project'), apps.get_model('editor', 'SpecItem')
        project = {k: v for k, v in Project.objects.values().get().items() if k != 'config'}
        return project, list(SpecItem.objects.values())

    def test_forward_and_backward_keep_all_project_data(self):
        old_apps = self.migrate(BEFORE)
        self.assertNotIn('config', project_columns())
        self.create_data(old_apps)
        before = self.snapshot(old_apps)

        new_apps = self.migrate(AFTER)
        self.assertIn('config', project_columns())
        NewProject = new_apps.get_model('editor', 'Project')
        self.assertEqual(NewProject.objects.get().config, {})              # existing rows get the default
        self.assertEqual(self.snapshot(new_apps), before)
        NewProject.objects.update(config={'cats': {}})
        self.assertEqual(NewProject.objects.get().config, {'cats': {}})

        back_apps = self.migrate(BEFORE)
        self.assertNotIn('config', project_columns())
        self.assertEqual(self.snapshot(back_apps), before)

        again = self.migrate(AFTER)                                        # and forward once more
        self.assertEqual(again.get_model('editor', 'Project').objects.get().config, {})
        self.assertEqual(self.snapshot(again), before)

    def test_migration_state_matches_the_models(self):
        call_command('makemigrations', 'editor', check=True, dry_run=True, verbosity=0)
