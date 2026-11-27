from datetime import datetime, timezone

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# The SQLite schema editor cannot run inside the transaction of a normal test.
pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [('editor', '0013_release_version_int_default')]
AFTER = [('editor', '0014_project_config')]


def project_columns():
    with connection.cursor() as cursor:
        return [column.name for column in connection.introspection.get_table_description(cursor, 'editor_project')]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def migrated_back():
    """Migrate to `BEFORE`; afterwards to the latest migrations again."""
    old_apps = migrate(BEFORE)
    yield old_apps
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())


def create_data(apps):
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


def snapshot(apps):
    Project, SpecItem = apps.get_model('editor', 'Project'), apps.get_model('editor', 'SpecItem')
    project = {k: v for k, v in Project.objects.values().get().items() if k != 'config'}
    return project, list(SpecItem.objects.values())


def test_forward_and_backward_keep_all_project_data(migrated_back):
    assert 'config' not in project_columns()
    create_data(migrated_back)
    before = snapshot(migrated_back)

    new_apps = migrate(AFTER)
    assert 'config' in project_columns()
    NewProject = new_apps.get_model('editor', 'Project')
    assert NewProject.objects.get().config == {}              # existing rows get the default
    assert snapshot(new_apps) == before
    NewProject.objects.update(config={'cats': {}})
    assert NewProject.objects.get().config == {'cats': {}}

    back_apps = migrate(BEFORE)
    assert 'config' not in project_columns()
    assert snapshot(back_apps) == before

    again = migrate(AFTER)
    assert again.get_model('editor', 'Project').objects.get().config == {}
    assert snapshot(again) == before
