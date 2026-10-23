"""
Characterization tests for editor.ext_cats (access to the external FW Profile
MySQL database). Only MySQLdb.connect is faked; everything else is real.
"""

import json
from datetime import datetime

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from editor import ext_cats
from editor.models import SpecItem

DB_KEY = 'svg-old'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows = []

    def execute(self, sql):
        self.conn.sql.append(sql)
        result = self.conn.responder(sql)
        if isinstance(result, Exception):
            raise result
        self.rows = result

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, responder):
        self.responder = responder
        self.sql = []
        self.closed = False
        self.cursor_obj = FakeCursor(self)

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


@pytest.fixture
def fake_db(monkeypatch):
    """Install a fake MySQLdb.connect; returns a holder with .conn, .connect_args, .responder."""
    class Holder:
        responder = staticmethod(lambda sql: [])
        connect_args = None
        conn = None
        connect_error = None

    holder = Holder()

    def fake_connect(*args, **kwargs):
        holder.connect_args = (args, kwargs)
        if holder.connect_error is not None:
            raise holder.connect_error
        holder.conn = FakeConnection(lambda sql: holder.responder(sql))
        return holder.conn

    monkeypatch.setattr(ext_cats.mdb, 'connect', fake_connect)
    return holder


def make_request(user=None):
    request = RequestFactory().get('/')
    request.user = user if user is not None else User(username='alice', email='alice@example.com')
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def msgs(request):
    return [(m.level_tag, m.message) for m in get_messages(request)]


def model_json(domain, extra=None):
    d = {'globals': {'fwprop': {'smTags': domain}}}
    if extra:
        d.update(extra)
    return json.dumps(d)


def diagram(id_, name, domain, kind='State Machine', svg='<svg/>', w=100, h=200,
            updated=datetime(2024, 3, 4, 5, 6, 7), json_rep=None):
    return (id_, 7, name, 'x', kind, updated,
            json_rep if json_rep is not None else model_json(domain), svg, w, h)


def fcp_json(domain, note):
    return model_json(domain, {'states': [{'fwprop': {'note': note}}]})


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

def test_connect_success_passes_config_positionally(fake_db):
    request = make_request()
    fw_db, cur = ext_cats.connect(request)
    assert fw_db is fake_db.conn
    assert cur is fake_db.conn.cursor_obj
    assert fake_db.connect_args == (('fwprofile-test-host', 'test', 'test', 'fwprofile_test'), {})
    assert msgs(request) == []


def test_connect_config_read_error(monkeypatch, fake_db, tmp_path):
    monkeypatch.setenv('CORDETFW_CONFIG_PATH', str(tmp_path / 'missing.json'))
    request = make_request()
    assert ext_cats.connect(request) == (None, None)
    assert msgs(request) == [('alert-danger', 'Unable to access credentials for FW Profile database')]
    assert fake_db.connect_args is None


def test_connect_config_invalid_json(monkeypatch, fake_db, tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text('{not json')
    monkeypatch.setenv('CORDETFW_CONFIG_PATH', str(bad))
    request = make_request()
    assert ext_cats.connect(request) == (None, None)
    assert msgs(request) == [('alert-danger', 'Unable to access credentials for FW Profile database')]


def test_connect_config_missing_key_is_reported_as_connect_error(monkeypatch, fake_db, tmp_path):
    cfg = tmp_path / 'nokey.json'
    cfg.write_text('{}')
    monkeypatch.setenv('CORDETFW_CONFIG_PATH', str(cfg))
    request = make_request()
    assert ext_cats.connect(request) == (None, None)
    assert msgs(request) == [('alert-danger', "Unable to connect to the FW Profile database: KeyError('FWPROFILE_DB')")]


def test_connect_database_error(fake_db):
    fake_db.connect_error = RuntimeError('boom')
    request = make_request()
    assert ext_cats.connect(request) == (None, None)
    assert msgs(request) == [('alert-danger', "Unable to connect to the FW Profile database: RuntimeError('boom')")]


def test_get_model_domain():
    assert ext_cats.get_model_domain(model_json('DomX')) == 'DomX'
    assert ext_cats.get_model_domain(model_json(None)) is None


# ---------------------------------------------------------------------------
# ext_model_get_choices
# ---------------------------------------------------------------------------

def test_model_get_choices_sorted_and_sql(fake_db):
    def responder(sql):
        if sql.startswith('SELECT * FROM users'):
            return [(42, 'alice@example.com')]
        return [diagram(3, 'zeta', 'DomB'), diagram(1, 'beta', 'DomA'), diagram(2, 'alpha', 'DomA'),
                diagram(4, 'proc', 'DomC', kind='Procedure')]
    fake_db.responder = responder
    request = make_request()
    choices = ext_cats.ext_model_get_choices(request)
    assert choices == [(2, 'DomA : alpha'), (1, 'DomA : beta'), (3, 'DomB : zeta'), (4, 'DomC : proc')]
    assert fake_db.conn.sql == ["SELECT * FROM users WHERE email = 'alice@example.com'",
                                'SELECT * FROM diagrams WHERE userID = 42']
    assert fake_db.conn.closed is True
    assert msgs(request) == []


def test_model_get_choices_sql_is_string_concatenated(fake_db):
    # KNOWN-ISSUE: ext-cats-sql-injection
    # The user e-mail is spliced into the SQL text without escaping or parameters.
    fake_db.responder = lambda sql: []
    request = make_request(User(username='mallory', email="x' OR '1'='1"))
    ext_cats.ext_model_get_choices(request)
    assert fake_db.conn.sql[0] == "SELECT * FROM users WHERE email = 'x' OR '1'='1'"


def test_model_get_choices_unknown_user(fake_db):
    # users query returns no rows -> user[0][0] raises IndexError inside the second try block
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert msgs(request) == [('alert-danger',
                              'Error trying to retrieve the models for user "alice@example.com:list index out of range')]
    assert fake_db.conn.closed is False     # KNOWN-ISSUE: ext-cats-connection-leak (early returns never close)


def test_model_get_choices_users_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert msgs(request) == [('alert-danger',
                              'User "alice" with e-mail "alice@example.com" not found in FW Profile DB: db down')]


def test_model_get_choices_diagrams_query_error(fake_db):
    def responder(sql):
        if sql.startswith('SELECT * FROM users'):
            return [(42,)]
        return RuntimeError('db down')
    fake_db.responder = responder
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert msgs(request) == [('alert-danger',
                              'Error trying to retrieve the models for user "alice@example.com:db down')]


def test_model_get_choices_no_models(fake_db):
    fake_db.responder = lambda sql: [(42,)] if sql.startswith('SELECT * FROM users') else []
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    # note the missing closing quote after the e-mail: pinned as is
    assert msgs(request) == [('alert-danger',
                              'No models found in FW Profile Database for user "alice" with e-mail "alice@example.com')]


def test_model_get_choices_connect_failure_cascades(fake_db):
    # connect() returns (None, None); the AttributeError is swallowed by the first try block
    fake_db.connect_error = RuntimeError('boom')
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert msgs(request) == [
        ('alert-danger', "Unable to connect to the FW Profile database: RuntimeError('boom')"),
        ('alert-danger', 'User "alice" with e-mail "alice@example.com" not found in FW Profile DB: '
                         "'NoneType' object has no attribute 'execute'"),
    ]


def test_model_get_choices_null_domain_crashes(fake_db):
    # KNOWN-ISSUE: ext-cats-null-domain
    fake_db.responder = lambda sql: [(42,)] if sql.startswith('SELECT * FROM users') \
        else [diagram(1, 'n', None)]
    with pytest.raises(TypeError):
        ext_cats.ext_model_get_choices(make_request())


# ---------------------------------------------------------------------------
# ext_model_get_choice
# ---------------------------------------------------------------------------

def test_model_get_choice_state_machine(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA', kind='State Machine', svg='<svg>1</svg>', w=11, h=22)]
    request = make_request()
    result = ext_cats.ext_model_get_choice(request, 7)
    assert result == {'domain': 'DomA', 'name': 'nm', 'p_kind': 'SM',
                      'updated_at': datetime(2024, 3, 4, 5, 6, 7), 'value': '<svg>1</svg>',
                      'n1': 11, 'n2': 22, 'n3': 7}
    assert fake_db.conn.sql == ['SELECT * FROM diagrams WHERE ID = 7']
    assert fake_db.conn.closed is True


def test_model_get_choice_procedure(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA', kind='Procedure')]
    assert ext_cats.ext_model_get_choice(make_request(), 7)['p_kind'] == 'PR'


def test_model_get_choice_unknown_kind_defaults_to_sm(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA', kind='Whatever')]
    assert ext_cats.ext_model_get_choice(make_request(), 7)['p_kind'] == 'SM'


def test_model_get_choice_sql_is_string_concatenated(fake_db):
    # KNOWN-ISSUE: ext-cats-sql-injection
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA')]
    ext_cats.ext_model_get_choice(make_request(), '7 OR 1=1')
    assert fake_db.conn.sql == ['SELECT * FROM diagrams WHERE ID = 7 OR 1=1']


def test_model_get_choice_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_model_get_choice(request, 7) is None
    assert msgs(request) == [('alert-danger', 'Error while accessing model with ID "7: db down')]


def test_model_get_choice_not_found_raises(fake_db):
    # KNOWN-ISSUE: ext-cats-get-choice-not-found
    # Contrary to its docstring ("or None if the model cannot be found") an empty result raises.
    fake_db.responder = lambda sql: []
    with pytest.raises(IndexError):
        ext_cats.ext_model_get_choice(make_request(), 7)


# ---------------------------------------------------------------------------
# ext_model_refresh
# ---------------------------------------------------------------------------

def make_item(n3=7, value='<svg>old</svg>'):
    return SpecItem(n3=n3, value=value, domain='OldDom', name='old', p_kind='SM', n1=1, n2=2)


def test_model_refresh_refresh(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'newname', 'NewDom', kind='Procedure',
                                             svg='<svg>new</svg>', w=33, h=44)]
    item = make_item()
    request = make_request()
    assert ext_cats.ext_model_refresh(request, item) == 'REFRESH'
    assert (item.domain, item.name, item.p_kind, item.value, item.n1, item.n2, item.n3) == \
           ('NewDom', 'newname', 'PR', '<svg>new</svg>', 33, 44, 7)
    assert item.updated_at == datetime(2024, 3, 4, 5, 6, 7)
    assert fake_db.conn.sql == ['SELECT * FROM diagrams WHERE ID = 7']
    assert fake_db.conn.closed is True
    assert msgs(request) == []


def test_model_refresh_no_change(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'other', 'Other', svg='<svg>old</svg>')]
    item = make_item()
    assert ext_cats.ext_model_refresh(make_request(), item) == 'NO_CHANGE'
    assert (item.domain, item.name) == ('OldDom', 'old')
    assert fake_db.conn.closed is False     # KNOWN-ISSUE: ext-cats-connection-leak


def test_model_refresh_not_found(fake_db):
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    assert msgs(request) == [('alert-warning', 'Model not found in FW Profile Database (its ID is: 9)')]


def test_model_refresh_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    assert msgs(request) == [('alert-danger', 'Error while accessing model with ID "9: db down')]


def test_model_refresh_connect_failure(fake_db):
    fake_db.connect_error = RuntimeError('boom')
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    assert msgs(request) == [
        ('alert-danger', "Unable to connect to the FW Profile database: RuntimeError('boom')"),
        ('alert-danger', "Error while accessing model with ID \"9: 'NoneType' object has no attribute 'execute'"),
    ]


# ---------------------------------------------------------------------------
# FCP functions
# ---------------------------------------------------------------------------

def test_get_fcp_desc():
    note = 'Title: My Title\nFirst line\nSecond line'
    assert ext_cats.get_fcp_desc(fcp_json('XFcp', note)) == {'title': 'My Title', 'desc': 'First line Second line'}


def test_get_fcp_desc_no_title():
    assert ext_cats.get_fcp_desc(fcp_json('XFcp', 'no title here')) is None
    assert ext_cats.get_fcp_desc(model_json('XFcp', {'states': []})) is None


def test_fcp_get_choices_filters_on_fcp_suffix_and_sorts(fake_db):
    def responder(sql):
        if sql.startswith('SELECT * FROM users'):
            return [(42,)]
        return [diagram(1, 'z', 'BFcp'), diagram(2, 'a', 'AFcp'), diagram(3, 'm', 'NotFcpX'),
                diagram(4, 'b', 'AFcp')]
    fake_db.responder = responder
    request = make_request()
    assert ext_cats.ext_fcp_get_choices(request) == [(2, 'AFcp : a'), (4, 'AFcp : b'), (1, 'BFcp : z')]
    assert fake_db.conn.sql == ["SELECT * FROM users WHERE email = 'alice@example.com'",
                                'SELECT * FROM diagrams WHERE userID = 42']
    assert fake_db.conn.closed is True


def test_fcp_get_choices_none_found(fake_db):
    fake_db.responder = lambda sql: [(42,)] if sql.startswith('SELECT * FROM users') else [diagram(1, 'x', 'Other')]
    request = make_request()
    assert ext_cats.ext_fcp_get_choices(request) == [(0, 'No FCP Found')]
    assert msgs(request) == [('alert-danger',
                              'No FCPs found in FW Profile Database for user "alice" with e-mail "alice@example.com')]


def test_fcp_get_choices_users_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_fcp_get_choices(request) == [(0, 'No FCP Found')]
    assert msgs(request) == [('alert-danger',
                              'User "alice" with e-mail "alice@example.com" not found in FW Profile DB: db down')]


def test_fcp_get_choices_diagrams_query_error(fake_db):
    fake_db.responder = lambda sql: [(42,)] if sql.startswith('SELECT * FROM users') else RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_fcp_get_choices(request) == [(0, 'No FCP Found')]
    assert msgs(request) == [('alert-danger',
                              'Error trying to retrieve the FCPs for user "alice@example.com:db down')]


def test_fcp_get_choices_unknown_user(fake_db):
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_fcp_get_choices(request) == [(0, 'No FCP Found')]
    assert msgs(request) == [('alert-danger',
                              'Error trying to retrieve the FCPs for user "alice@example.com:list index out of range')]


def test_fcp_get_choices_null_domain_crashes(fake_db):
    # KNOWN-ISSUE: ext-cats-null-domain
    fake_db.responder = lambda sql: [(42,)] if sql.startswith('SELECT * FROM users') else [diagram(1, 'n', None)]
    with pytest.raises(TypeError):
        ext_cats.ext_fcp_get_choices(make_request())


def test_fcp_get_choice(fake_db):
    note = 'Title: My Title\nSome description'
    fake_db.responder = lambda sql: [diagram(5, 'fcpname', 'XFcp', svg='<svg>f</svg>', w=5, h=6,
                                             json_rep=fcp_json('XFcp', note))]
    result = ext_cats.ext_fcp_get_choice(make_request(), 5)
    assert result == {'domain': 'XFcp', 'name': 'fcpname', 'updated_at': datetime(2024, 3, 4, 5, 6, 7),
                      'title': 'My Title', 'desc': 'Some description', 'value': '<svg>f</svg>',
                      'n1': 5, 'n2': 6, 'n3': 5}
    assert fake_db.conn.sql == ['SELECT * FROM diagrams WHERE ID = 5']
    assert fake_db.conn.closed is True


def test_fcp_get_choice_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_fcp_get_choice(request, 5) is None
    assert msgs(request) == [('alert-danger', 'Error while accessing model with ID "5: db down')]


def test_fcp_get_choice_not_found_raises(fake_db):
    # KNOWN-ISSUE: ext-cats-get-choice-not-found
    fake_db.responder = lambda sql: []
    with pytest.raises(IndexError):
        ext_cats.ext_fcp_get_choice(make_request(), 5)


def test_fcp_get_choice_without_title_raises(fake_db):
    # KNOWN-ISSUE: ext-cats-fcp-no-title
    # get_fcp_desc returns None when no state note holds 'Title:'; the subscript then fails.
    fake_db.responder = lambda sql: [diagram(5, 'n', 'XFcp', json_rep=fcp_json('XFcp', 'no title'))]
    with pytest.raises(TypeError):
        ext_cats.ext_fcp_get_choice(make_request(), 5)


def test_fcp_refresh_not_found(fake_db):
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_fcp_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    assert msgs(request) == [('alert-warning', 'FCP not found in FW Profile Database (its ID is: 9)')]


def test_fcp_refresh_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_fcp_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    assert msgs(request) == [('alert-danger', 'Error while accessing model with ID "9: db down')]


def test_fcp_refresh_no_change(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'n', 'XFcp', svg='<svg>old</svg>',
                                             json_rep=fcp_json('XFcp', 'Title: T\nd'))]
    assert ext_cats.ext_fcp_refresh(make_request(), make_item()) == 'NO_CHANGE'


def test_fcp_refresh_changed_raises_name_error(fake_db):
    # KNOWN-ISSUE: ext-fcp-refresh-nameerror
    # ext_fcp_refresh writes into an undefined variable 'ext_item_dict' (copy/paste from
    # ext_fcp_get_choice) so any real refresh raises NameError. By then domain and name of
    # the spec_item have already been overwritten, and the connection is left open.
    fake_db.responder = lambda sql: [diagram(7, 'newname', 'NewFcp', svg='<svg>new</svg>',
                                             json_rep=fcp_json('NewFcp', 'Title: T\nd'))]
    item = make_item()
    with pytest.raises(NameError) as excinfo:
        ext_cats.ext_fcp_refresh(make_request(), item)
    assert 'ext_item_dict' in str(excinfo.value)
    assert (item.domain, item.name) == ('NewFcp', 'newname')
    assert item.value == '<svg>old</svg>'
    assert fake_db.conn.closed is False


# ---------------------------------------------------------------------------
# Opt-in REAL-driver tests (MySQL backend runs only)
# ---------------------------------------------------------------------------
#
# These run the real MySQLdb driver against a scratch database on the disposable test MySQL
# server (never a real FW Profile database). They exist because every other test in this module
# fakes MySQLdb.connect, so driver behaviour (returned Python types, str vs bytes, datetimes,
# tuple rows) would otherwise be untested across the mysqlclient upgrade.
#
# One-time setup of the privileges (the test creates/drops the scratch database itself):
#   docker exec cordetfw-mysql-test mysql -uroot -prootpw-test \
#     -e "GRANT ALL ON test_fwprofile_scratch.* TO 'cftest'@'%'"
#
# Credentials come from the same environment variables as settings_test_mysql.py.
# These tests are backend-specific by nature, hence skipif (not a skipped failing test).

import os

from tests.backend import is_mysql

SCRATCH_DB = 'test_fwprofile_scratch'
SCRATCH_PORT = int(os.environ.get('CORDETFW_TEST_MYSQL_PORT', '3306'))
SCRATCH_HOST = os.environ.get('CORDETFW_TEST_MYSQL_HOST', '127.0.0.1')
SCRATCH_USER = os.environ.get('CORDETFW_TEST_MYSQL_USER', '')
SCRATCH_PWD = os.environ.get('CORDETFW_TEST_MYSQL_PASSWORD', '')

REAL_SVG = '<svg width="10"/>'
REAL_JSON = model_json('Dom')
REAL_UPDATED = datetime(2024, 3, 4, 5, 6, 7)


@pytest.fixture
def real_fwprofile(monkeypatch, tmp_path):
    """Create the FW Profile tables in the scratch database and point ext_cats.connect at it."""
    import MySQLdb
    admin = MySQLdb.connect(host=SCRATCH_HOST, port=SCRATCH_PORT, user=SCRATCH_USER, passwd=SCRATCH_PWD)
    cur = admin.cursor()
    cur.execute('DROP DATABASE IF EXISTS ' + SCRATCH_DB)
    cur.execute('CREATE DATABASE ' + SCRATCH_DB + ' CHARACTER SET utf8mb4')
    cur.execute('USE ' + SCRATCH_DB)
    # Column positions matter: ext_cats indexes rows positionally (diagrams[0][0..9])
    cur.execute('CREATE TABLE users (ID INT PRIMARY KEY, email VARCHAR(255) NOT NULL)')
    cur.execute('CREATE TABLE diagrams ('
                'ID INT PRIMARY KEY, userID INT NOT NULL, name VARCHAR(255), title VARCHAR(255), '
                'type VARCHAR(64), updated DATETIME, model JSON, svg LONGTEXT, width INT, height INT)')
    cur.execute("INSERT INTO users VALUES (42, 'alice@example.com')")
    cur.execute("INSERT INTO diagrams VALUES (7, 42, 'Sm1', 'x', 'State Machine', %s, %s, %s, 100, 200)",
                (REAL_UPDATED, REAL_JSON, REAL_SVG))
    cur.execute("INSERT INTO diagrams VALUES (8, 42, 'Pr1', 'x', 'Procedure', %s, %s, %s, 11, 22)",
                (REAL_UPDATED, model_json('Dom2'), '<svg id="p"/>'))
    admin.commit()

    config = {'FWPROFILE_DB': {'HOST': SCRATCH_HOST, 'USER': SCRATCH_USER, 'PWD': SCRATCH_PWD,
                               'NAME': SCRATCH_DB}}
    path = tmp_path / 'fwprofile_config.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('CORDETFW_CONFIG_PATH', str(path))

    real_connect = ext_cats.mdb.connect

    def connect_with_port(*args, **kwargs):
        # ext_cats.connect passes (host, user, pwd, name) positionally and cannot name a port;
        # the disposable server listens on a non-default port. Still the real driver.
        kwargs.setdefault('port', SCRATCH_PORT)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(ext_cats.mdb, 'connect', connect_with_port)
    yield
    cur.execute('DROP DATABASE IF EXISTS ' + SCRATCH_DB)
    admin.close()


@pytest.mark.skipif(not is_mysql(), reason='real MySQLdb driver test, MySQL backend only')
class TestRealDriver:
    def test_connect_returns_real_connection(self, real_fwprofile):
        request = make_request()
        fw_db, cur = ext_cats.connect(request)
        assert fw_db is not None and type(fw_db).__module__.startswith('MySQLdb')
        assert msgs(request) == []
        fw_db.close()

    def test_row_types_from_real_driver(self, real_fwprofile):
        fw_db, cur = ext_cats.connect(make_request())
        cur.execute('SELECT * FROM diagrams WHERE ID = 7')
        row = cur.fetchall()[0]
        fw_db.close()
        assert isinstance(row, tuple)
        assert [type(v) for v in row] == [int, int, str, str, str, datetime, str, str, int, int]
        assert row[5] == REAL_UPDATED

    def test_model_get_choice_types(self, real_fwprofile):
        request = make_request()
        result = ext_cats.ext_model_get_choice(request, 7)
        assert type(result['domain']) is str and type(result['name']) is str
        assert type(result['value']) is str and type(result['p_kind']) is str
        assert type(result['n1']) is int and type(result['n3']) is int
        assert result['updated_at'] == REAL_UPDATED
        assert (result['domain'], result['name'], result['value']) == ('Dom', 'Sm1', REAL_SVG)
        assert (result['n1'], result['n2'], result['n3']) == (100, 200, 7)
        assert result['p_kind'] == 'SM'
        procedure = ext_cats.ext_model_get_choice(request, 8)
        assert procedure['p_kind'] == 'PR'
        assert msgs(request) == []

    def test_model_get_choices_types(self, real_fwprofile):
        request = make_request()
        choices = ext_cats.ext_model_get_choices(request)
        assert choices == [(7, 'Dom : Sm1'), (8, 'Dom2 : Pr1')]
        assert all(type(i) is int and type(label) is str for i, label in choices)
        assert msgs(request) == []

    def test_model_get_choices_unknown_user(self, real_fwprofile):
        # an unknown e-mail: user[0][0] raises IndexError inside the try block, which is reported
        # as a generic error and the empty choice list is returned
        request = make_request(User(username='nobody', email='nobody@example.com'))
        assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
        [(level, text)] = msgs(request)
        assert level == 'alert-danger'
        assert text.startswith('Error trying to retrieve the models for user "nobody@example.com:')

    def test_model_refresh_no_change_then_refresh(self, real_fwprofile):
        request = make_request()
        item = SpecItem(cat='Model', domain='Old', name='Old', value=REAL_SVG, n3=7, p_kind='STD',
                        n1=1, n2=2)
        assert ext_cats.ext_model_refresh(request, item) == 'NO_CHANGE'
        assert (item.domain, item.name, item.n1, item.n2) == ('Old', 'Old', 1, 2)
        assert msgs(request) == []

        item.value = '<svg old/>'
        assert ext_cats.ext_model_refresh(request, item) == 'REFRESH'
        assert (item.domain, item.name, item.value) == ('Dom', 'Sm1', REAL_SVG)
        assert (item.n1, item.n2, item.n3) == (100, 200, 7)
        assert item.updated_at == REAL_UPDATED
        assert type(item.domain) is str and type(item.value) is str
        assert msgs(request) == []

    def test_model_refresh_not_found(self, real_fwprofile):
        request = make_request()
        item = SpecItem(cat='Model', value='x', n3=999)
        assert ext_cats.ext_model_refresh(request, item) == 'NOT_FOUND'
        assert msgs(request) == [('alert-warning', 'Model not found in FW Profile Database (its ID is: 999)')]

    def test_connect_failure_is_reported(self, real_fwprofile, monkeypatch, tmp_path):
        config = {'FWPROFILE_DB': {'HOST': SCRATCH_HOST, 'USER': SCRATCH_USER, 'PWD': 'wrong-password',
                                   'NAME': SCRATCH_DB}}
        path = tmp_path / 'bad_config.json'
        path.write_text(json.dumps(config))
        monkeypatch.setenv('CORDETFW_CONFIG_PATH', str(path))
        request = make_request()
        assert ext_cats.connect(request) == (None, None)
        [(level, text)] = msgs(request)
        assert level == 'alert-danger' and text.startswith('Unable to connect to the FW Profile database: ')
