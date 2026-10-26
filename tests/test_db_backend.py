"""Database-backend behaviour that the upgrade must not change silently."""

import pytest
from django.db import OperationalError, transaction

from editor.models import SpecItem
from tests.backend import is_mysql
from tests.factories import make_project, make_spec_item, make_user

pytestmark = pytest.mark.django_db

EMOJI = '\U0001F600'


def test_four_byte_unicode_storage():
    # Django's MySQL backend connects with charset 'utf8' (3-byte utf8mb3) unless the
    # DATABASES OPTIONS say otherwise, so 4-byte characters (emoji) cannot be stored
    # there. SQLite stores them. Pinned so a changed connection charset is noticed.
    project = make_project(make_user())
    if is_mysql():
        with pytest.raises(OperationalError) as excinfo:
            with transaction.atomic():
                make_spec_item(project, desc='smile ' + EMOJI)
        assert excinfo.value.args[0] == 1366
        assert not SpecItem.objects.filter(project=project).exists()
    else:
        item = make_spec_item(project, desc='smile ' + EMOJI)
        assert SpecItem.objects.get(id=item.id).desc == 'smile ' + EMOJI


def test_bmp_unicode_round_trip():
    project = make_project(make_user())
    text = 'ä µ ☺ ß € Ω'
    item = make_spec_item(project, desc=text, title=text)
    stored = SpecItem.objects.get(id=item.id)
    assert (stored.desc, stored.title) == (text, text)


def test_s_data_json_round_trip():
    project = make_project(make_user())
    data = {'a': [1, 2.5, None, True], 'nested': {'k': 'ä'}, 'empty': {}}
    item = make_spec_item(project, s_data=data)
    assert SpecItem.objects.get(id=item.id).s_data == data


def _mysql_one(sql, params=None):
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchall()


def test_connection_charset_and_collation():
    # Records the character set / collation the connection actually uses.
    # Task 3.5: Django 5.2 would default to utf8mb4; settings.apply_mysql_connection_defaults()
    # keeps the Django 3.2 charset 'utf8' (reported as utf8mb3) for compatibility and rollback
    # safety, so this value and test_four_byte_unicode_storage are unchanged.
    from django.db import connection
    if not is_mysql():
        assert connection.vendor == 'sqlite'
        return
    row = _mysql_one('SELECT @@character_set_connection, @@collation_connection')[0]
    assert tuple(row) == ('utf8mb3', 'utf8mb3_general_ci')


@pytest.mark.skipif(not is_mysql(), reason='information_schema collation check is MySQL specific')
def test_mysql_specitem_table_and_column_charset():
    # Table/column character set and collation of editor_specitem in the MySQL TEST database
    # (created by Django's test runner with the server defaults: utf8mb4 / utf8mb4_unicode_ci
    # on the disposable server started as documented in CLAUDE.md).
    # TODO(operator): these values MUST be compared with the PRODUCTION database
    # (SELECT TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_NAME='editor_specitem';
    #  and the COLUMNS view) before the Django 5.2 upgrade; production value pending. See
    # docs/migration/baseline.md, 'Pending: production DB collation'.
    table = _mysql_one(
        "SELECT TABLE_COLLATION FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'editor_specitem'")
    assert [tuple(r) for r in table] == [('utf8mb4_unicode_ci',)]
    cols = _mysql_one(
        "SELECT COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'editor_specitem' "
        "AND COLLATION_NAME IS NOT NULL ORDER BY ORDINAL_POSITION")
    assert {(c[1], c[2]) for c in cols} == {('utf8mb4', 'utf8mb4_unicode_ci')}
    assert [c[0] for c in cols] == ['cat', 'name', 'domain', 'title', 'desc', 'status', 'rationale',
                                    'remarks', 'p_kind', 's_kind', 'value',
                                    't1', 't2', 't3', 't4', 't5', 'change_log', 'implementation']


def test_mysql_connection_defaults_keep_old_charset_unless_configured():
    # Task 3.5: Django 5.2 defaults MySQL connections to utf8mb4; the settings keep 'utf8'
    # (the Django 3.2 behaviour) unless the deployment config sets a charset explicitly.
    from cordetfw_editor.settings import apply_mysql_connection_defaults
    dbs = apply_mysql_connection_defaults({
        'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': 'a'},
        'explicit': {'ENGINE': 'django.db.backends.mysql', 'NAME': 'b', 'OPTIONS': {'charset': 'utf8mb4'}},
        'sqlite': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'},
    })
    assert dbs['default']['OPTIONS'] == {'charset': 'utf8'}
    assert dbs['explicit']['OPTIONS'] == {'charset': 'utf8mb4'}
    assert 'OPTIONS' not in dbs['sqlite']
