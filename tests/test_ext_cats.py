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

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        self.conn.calls.append((sql, params))
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
        self.calls = []          # (sql, params) of every execute
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


def diagram(id_, name, domain, kind='State Machine', svg='<svg xmlns="http://www.w3.org/2000/svg"></svg>', w=100, h=200,
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
# Visible models (upstream #91, Task 7.1): own models + models shared with the user's e-mail
# ---------------------------------------------------------------------------

VISIBLE_SQL = (
    'SELECT diagrams.* FROM diagrams WHERE ('
    'EXISTS (SELECT 1 FROM users WHERE users.id = diagrams.userID AND users.email = %s) OR '
    'EXISTS (SELECT 1 FROM shares WHERE shares.diagramID = diagrams.id '
    "AND shares.email = %s AND shares.perm IN ('ro', 'rw')))"
)


@pytest.fixture
def fake_visible_db(monkeypatch, fake_db):
    """fake_db that evaluates the visibility query against a small in-memory dataset
    (the fake understands exactly the query built by get_visible_models)."""
    data = {'users': {7: 'alice@example.com', 8: 'bob@example.com'},    # user id -> e-mail
            'shares': [],                                               # (diagram id, e-mail, perm)
            'diagrams': []}                                             # rows; row[1] is the owner's user id

    def execute(self, sql, params=None):
        assert sql.startswith('SELECT diagrams.* FROM diagrams WHERE (')
        self.conn.sql.append(sql)
        self.conn.calls.append((sql, params))
        email, wanted = params[0], (params[2] if len(params) > 2 else None)
        self.rows = [d for d in data['diagrams']
                     if (data['users'].get(d[1]) == email
                         or any(sh[0] == d[0] and sh[1] == email and sh[2] in ('ro', 'rw') for sh in data['shares']))
                     and (wanted is None or d[0] == wanted)]

    monkeypatch.setattr(FakeCursor, 'execute', execute)
    return data


def test_get_visible_models_sql_is_parameterized(fake_db):
    fake_db.responder = lambda sql: []
    request = make_request(User(username='mallory', email="x' OR '1'='1"))
    assert ext_cats.get_visible_models(request) == []
    assert fake_db.conn.calls == [(VISIBLE_SQL, ["x' OR '1'='1", "x' OR '1'='1"])]
    assert fake_db.conn.closed is True


def test_get_visible_models_with_id_adds_parameter(fake_db):
    fake_db.responder = lambda sql: []
    ext_cats.get_visible_models(make_request(), "7 OR 1=1")
    assert fake_db.conn.calls == [(VISIBLE_SQL + ' AND diagrams.id = %s',
                                   ['alice@example.com', 'alice@example.com', '7 OR 1=1'])]


@pytest.mark.parametrize('email', ['', None])
def test_get_visible_models_empty_email_no_query(fake_db, email):
    request = make_request(User(username='noemail', email=email or ''))
    request.user.email = email
    assert ext_cats.get_visible_models(request) == []
    assert fake_db.connect_args is None          # not even a connection
    assert fake_db.conn is None


def test_get_visible_models_connect_failure(fake_db):
    fake_db.connect_error = RuntimeError('boom')
    request = make_request()
    assert ext_cats.get_visible_models(request) == []
    assert msgs(request) == [('alert-danger', "Unable to connect to the FW Profile database: RuntimeError('boom')")]


def test_get_visible_models_closes_connection_on_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    with pytest.raises(RuntimeError):
        ext_cats.get_visible_models(make_request())
    assert fake_db.conn.closed is True


def _visible_data(fake_visible_db):
    d = fake_visible_db
    d['diagrams'] = [diagram(1, 'mine', 'DomA'), diagram(2, 'sharedro', 'DomB'), diagram(3, 'sharedrw', 'DomC'),
                     diagram(4, 'sharedother', 'DomD'), diagram(5, 'foreign', 'DomE')]
    # diagram() puts user id 7 in row[1]; make 2..5 belong to bob (8)
    d['diagrams'] = [r if r[0] == 1 else (r[0], 8) + r[2:] for r in d['diagrams']]
    d['shares'] = [(2, 'alice@example.com', 'ro'), (3, 'alice@example.com', 'rw'),
                   (4, 'alice@example.com', 'none'), (5, 'carol@example.com', 'rw')]
    return d


def test_visible_owner_sees_own_models(fake_visible_db):
    _visible_data(fake_visible_db)
    bob = User(username='bob', email='bob@example.com')
    ids = [r[0] for r in ext_cats.get_visible_models(make_request(bob))]
    assert ids == [2, 3, 4, 5]


def test_visible_shared_ro_and_rw_visible_other_perm_not(fake_visible_db):
    _visible_data(fake_visible_db)
    rows = ext_cats.get_visible_models(make_request())
    assert [r[0] for r in rows] == [1, 2, 3]           # own, shared ro, shared rw; not perm 'none', not foreign
    assert ext_cats.get_visible_models(make_request(), 4) == []
    assert ext_cats.get_visible_models(make_request(), 5) == []


def test_model_get_choices_includes_shared_models(fake_visible_db):
    _visible_data(fake_visible_db)
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(1, 'DomA : mine'), (2, 'DomB : sharedro'),
                                                       (3, 'DomC : sharedrw')]
    assert msgs(request) == []


# ---------------------------------------------------------------------------
# ext_model_get_choices
# ---------------------------------------------------------------------------

def test_model_get_choices_sorted_and_sql(fake_db):
    fake_db.responder = lambda sql: [diagram(3, 'zeta', 'DomB'), diagram(1, 'beta', 'DomA'),
                                     diagram(2, 'alpha', 'DomA'), diagram(4, 'proc', 'DomC', kind='Procedure')]
    request = make_request()
    choices = ext_cats.ext_model_get_choices(request)
    assert choices == [(2, 'DomA : alpha'), (1, 'DomA : beta'), (3, 'DomB : zeta'), (4, 'DomC : proc')]
    # CHANGED: upstream #91 (was: "SELECT * FROM users WHERE email = ..." then "SELECT * FROM diagrams WHERE userID = 42")
    assert fake_db.conn.calls == [(VISIBLE_SQL, ['alice@example.com', 'alice@example.com'])]
    assert fake_db.conn.closed is True
    assert msgs(request) == []


def test_model_get_choices_sql_is_parameterized(fake_db):
    # CHANGED: upstream #91 (was: KNOWN-ISSUE ext-cats-sql-injection, e-mail spliced into the SQL text;
    # still open for the FCP functions, see test_fcp_get_choices_sql_is_string_concatenated)
    fake_db.responder = lambda sql: []
    request = make_request(User(username='mallory', email="x' OR '1'='1"))
    ext_cats.ext_model_get_choices(request)
    sql, params = fake_db.conn.calls[0]
    assert "x'" not in sql
    assert params == ["x' OR '1'='1", "x' OR '1'='1"]


def test_model_get_choices_empty_email_no_models_no_query(fake_db):
    # new with upstream #91: a user without e-mail sees no models and the DB is not queried
    request = make_request(User(username='noemail', email=''))
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert fake_db.conn is None
    assert msgs(request) == [('alert-danger', 'No models found in FW Profile Database for user "noemail')]


def test_model_get_choices_query_error(fake_db):
    # CHANGED: upstream #91 (was: separate users-query and diagrams-query error messages, connection left open)
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert msgs(request) == [('alert-danger', 'Error trying to retrieve the models from FW Profile DB: db down')]
    assert fake_db.conn.closed is True      # CHANGED: upstream #91 (was: KNOWN-ISSUE ext-cats-connection-leak, False)


def test_model_get_choices_no_models(fake_db):
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    # CHANGED: upstream #91 (was: '... for user "alice" with e-mail "alice@example.com')
    assert msgs(request) == [('alert-danger', 'No models found in FW Profile Database for user "alice')]
    assert fake_db.conn.closed is True      # CHANGED: upstream #91 (was: connection left open)


def test_model_get_choices_connect_failure(fake_db):
    # CHANGED: upstream #91 (was: connect error followed by "'NoneType' object has no attribute 'execute'")
    fake_db.connect_error = RuntimeError('boom')
    request = make_request()
    assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
    assert msgs(request) == [
        ('alert-danger', "Unable to connect to the FW Profile database: RuntimeError('boom')"),
        ('alert-danger', 'No models found in FW Profile Database for user "alice'),
    ]


def test_model_get_choices_null_domain_crashes(fake_db):
    # KNOWN-ISSUE: ext-cats-null-domain
    fake_db.responder = lambda sql: [diagram(1, 'n', None)]
    with pytest.raises(TypeError):
        ext_cats.ext_model_get_choices(make_request())
    assert fake_db.conn.closed is True      # the connection is closed before the crash


# ---------------------------------------------------------------------------
# ext_model_get_choice
# ---------------------------------------------------------------------------

def test_model_get_choice_state_machine(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA', kind='State Machine', svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>1</desc></svg>', w=11, h=22)]
    request = make_request()
    result = ext_cats.ext_model_get_choice(request, 7)
    assert result == {'domain': 'DomA', 'name': 'nm', 'p_kind': 'SM',
                      'updated_at': datetime(2024, 3, 4, 5, 6, 7), 'value': '<svg xmlns="http://www.w3.org/2000/svg"><desc>1</desc></svg>',
                      'n1': 11, 'n2': 22, 'n3': 7}
    # CHANGED: upstream #91 (was: ['SELECT * FROM diagrams WHERE ID = 7'])
    assert fake_db.conn.calls == [(VISIBLE_SQL + ' AND diagrams.id = %s',
                                   ['alice@example.com', 'alice@example.com', 7])]
    assert fake_db.conn.closed is True


def test_model_get_choice_procedure(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA', kind='Procedure')]
    assert ext_cats.ext_model_get_choice(make_request(), 7)['p_kind'] == 'PR'


def test_model_get_choice_unknown_kind_defaults_to_sm(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA', kind='Whatever')]
    assert ext_cats.ext_model_get_choice(make_request(), 7)['p_kind'] == 'SM'


def test_model_get_choice_sql_is_parameterized(fake_db):
    # CHANGED: upstream #91 (was: KNOWN-ISSUE ext-cats-sql-injection, 'SELECT * FROM diagrams WHERE ID = 7 OR 1=1')
    fake_db.responder = lambda sql: [diagram(7, 'nm', 'DomA')]
    ext_cats.ext_model_get_choice(make_request(), '7 OR 1=1')
    sql, params = fake_db.conn.calls[0]
    assert '7 OR 1=1' not in sql and params[2] == '7 OR 1=1'


def test_model_get_choice_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_model_get_choice(request, 7) is None
    assert msgs(request) == [('alert-danger', 'Error while accessing model with ID "7: db down')]
    assert fake_db.conn.closed is True      # CHANGED: upstream #91 (was: connection left open)


def test_model_get_choice_not_found_returns_none(fake_db):
    # CHANGED: upstream #91 (was: KNOWN-ISSUE ext-cats-get-choice-not-found, IndexError; still open for FCP)
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_model_get_choice(request, 7) is None
    assert msgs(request) == [('alert-warning', 'Model not found or not shared with you in FW Profile Database')]
    assert fake_db.conn.closed is True


def test_model_get_choice_not_visible_and_empty_email(fake_visible_db):
    _visible_data(fake_visible_db)
    assert ext_cats.ext_model_get_choice(make_request(), 5) is None       # foreign model
    assert ext_cats.ext_model_get_choice(make_request(), 2)['name'] == 'sharedro'
    noemail = make_request(User(username='n', email=''))
    assert ext_cats.ext_model_get_choice(noemail, 1) is None


# ---------------------------------------------------------------------------
# ext_model_refresh
# ---------------------------------------------------------------------------

def make_item(n3=7, value='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>'):
    return SpecItem(n3=n3, value=value, domain='OldDom', name='old', p_kind='SM', n1=1, n2=2)


def test_model_refresh_refresh(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'newname', 'NewDom', kind='Procedure',
                                             svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>', w=33, h=44)]
    item = make_item()
    request = make_request()
    assert ext_cats.ext_model_refresh(request, item) == 'REFRESH'
    assert (item.domain, item.name, item.p_kind, item.value, item.n1, item.n2, item.n3) == \
           ('NewDom', 'newname', 'PR', '<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>', 33, 44, 7)
    assert item.updated_at == datetime(2024, 3, 4, 5, 6, 7)
    # CHANGED: upstream #91 (was: ['SELECT * FROM diagrams WHERE ID = 7'])
    assert fake_db.conn.calls == [(VISIBLE_SQL + ' AND diagrams.id = %s',
                                   ['alice@example.com', 'alice@example.com', 7])]
    assert fake_db.conn.closed is True
    assert msgs(request) == []


def test_model_refresh_no_change(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'other', 'Other', svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>')]
    item = make_item()
    assert ext_cats.ext_model_refresh(make_request(), item) == 'NO_CHANGE'
    assert (item.domain, item.name) == ('OldDom', 'old')
    assert fake_db.conn.closed is True      # CHANGED: upstream #91 (was: KNOWN-ISSUE ext-cats-connection-leak, False)


def test_model_refresh_not_found(fake_db):
    fake_db.responder = lambda sql: []
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    # CHANGED: upstream #91 (was: 'Model not found in FW Profile Database (its ID is: 9)')
    assert msgs(request) == [('alert-warning',
                              'Model not found or not shared with you in FW Profile Database (its ID is: 9)')]
    assert fake_db.conn.closed is True


def test_model_refresh_not_visible_model_is_not_found(fake_visible_db):
    _visible_data(fake_visible_db)
    request = make_request()
    item = make_item(n3=5)                    # belongs to bob, shared only with carol
    assert ext_cats.ext_model_refresh(request, item) == 'NOT_FOUND'
    assert msgs(request) == [('alert-warning',
                              'Model not found or not shared with you in FW Profile Database (its ID is: 5)')]
    assert item.value == '<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>'
    shared = make_item(n3=2)
    assert ext_cats.ext_model_refresh(make_request(), shared) == 'REFRESH'    # shared ro: refreshable


def test_model_refresh_query_error(fake_db):
    fake_db.responder = lambda sql: RuntimeError('db down')
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    assert msgs(request) == [('alert-danger', 'Error while accessing model with ID "9: db down')]
    assert fake_db.conn.closed is True


def test_model_refresh_connect_failure(fake_db):
    fake_db.connect_error = RuntimeError('boom')
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item(n3=9)) == 'NOT_FOUND'
    # CHANGED: upstream #91 (was: connect error + "'NoneType' object has no attribute 'execute'")
    assert msgs(request) == [
        ('alert-danger', "Unable to connect to the FW Profile database: RuntimeError('boom')"),
        ('alert-warning', 'Model not found or not shared with you in FW Profile Database (its ID is: 9)'),
    ]


def test_model_refresh_invalid_svg_closes_connection(fake_db):
    fake_db.responder = lambda sql: [diagram(7, 'n', 'D', svg='<svg onload="x"/>')]
    request = make_request()
    assert ext_cats.ext_model_refresh(request, make_item()) == 'INVALID'
    assert fake_db.conn.closed is True


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
    # CHANGED: ext-cats-sql-injection (was: queries with the e-mail / user id spliced into the SQL text)
    assert fake_db.conn.calls == [('SELECT * FROM users WHERE email = %s', ['alice@example.com']),
                                  ('SELECT * FROM diagrams WHERE userID = %s', [42])]
    assert fake_db.conn.closed is True


def test_fcp_get_choices_sql_is_parameterized(fake_db):
    # FIXED: ext-cats-sql-injection (was: the e-mail was spliced into the SQL text of the FCP queries)
    fake_db.responder = lambda sql: []
    request = make_request(User(username='mallory', email="x' OR '1'='1"))
    ext_cats.ext_fcp_get_choices(request)
    assert fake_db.conn.calls[0] == ('SELECT * FROM users WHERE email = %s', ["x' OR '1'='1"])
    assert "x' OR" not in fake_db.conn.calls[0][0]


def test_fcp_get_choice_and_refresh_sql_is_parameterized_and_owner_only(fake_db):
    # FIXED: ext-cats-sql-injection (was: 'SELECT * FROM diagrams WHERE ID = <id>', any user's diagram)
    owned_sql = ('SELECT diagrams.* FROM diagrams WHERE diagrams.id = %s AND '
                 'EXISTS (SELECT 1 FROM users WHERE users.id = diagrams.userID AND users.email = %s)')
    fake_db.responder = lambda sql: [diagram(5, 'n', 'XFcp', json_rep=fcp_json('XFcp', 'Title: T\nd'))]
    ext_cats.ext_fcp_get_choice(make_request(), "5 OR 1=1")
    assert fake_db.conn.calls == [(owned_sql, ["5 OR 1=1", 'alice@example.com'])]
    assert fake_db.conn.closed is True
    fake_db.responder = lambda sql: []
    ext_cats.ext_fcp_refresh(make_request(), make_item(n3="9 OR 1=1"))
    assert fake_db.conn.calls == [(owned_sql, ["9 OR 1=1", 'alice@example.com'])]
    assert fake_db.conn.closed is True


def test_fcp_connections_closed_on_every_path(fake_db):
    # FIXED: ext-cats-connection-leak (was: FCP functions left the connection open on early return / NO_CHANGE)
    fake_db.responder = lambda sql: []
    assert ext_cats.ext_fcp_get_choices(make_request()) == [(0, 'No FCP Found')]
    assert fake_db.conn.closed is True
    fake_db.responder = lambda sql: RuntimeError('db down')
    ext_cats.ext_fcp_get_choices(make_request())
    assert fake_db.conn.closed is True
    fake_db.responder = lambda sql: [diagram(7, 'n', 'XFcp', svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>',
                                             json_rep=fcp_json('XFcp', 'Title: T\nd'))]
    assert ext_cats.ext_fcp_refresh(make_request(), make_item()) == 'NO_CHANGE'
    assert fake_db.conn.closed is True
    fake_db.responder = lambda sql: RuntimeError('db down')
    assert ext_cats.ext_fcp_refresh(make_request(), make_item()) == 'NOT_FOUND'
    assert fake_db.conn.closed is True
    assert ext_cats.ext_fcp_get_choice(make_request(), 5) is None
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
    fake_db.responder = lambda sql: [diagram(5, 'fcpname', 'XFcp', svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>f</desc></svg>', w=5, h=6,
                                             json_rep=fcp_json('XFcp', note))]
    result = ext_cats.ext_fcp_get_choice(make_request(), 5)
    assert result == {'domain': 'XFcp', 'name': 'fcpname', 'updated_at': datetime(2024, 3, 4, 5, 6, 7),
                      'title': 'My Title', 'desc': 'Some description', 'value': '<svg xmlns="http://www.w3.org/2000/svg"><desc>f</desc></svg>',
                      'n1': 5, 'n2': 6, 'n3': 5}
    assert fake_db.conn.calls[0][1] == [5, 'alice@example.com']       # CHANGED: ext-cats-sql-injection
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
    fake_db.responder = lambda sql: [diagram(7, 'n', 'XFcp', svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>',
                                             json_rep=fcp_json('XFcp', 'Title: T\nd'))]
    assert ext_cats.ext_fcp_refresh(make_request(), make_item()) == 'NO_CHANGE'


def test_fcp_refresh_changed_raises_name_error(fake_db):
    # KNOWN-ISSUE: ext-fcp-refresh-nameerror
    # ext_fcp_refresh writes into an undefined variable 'ext_item_dict' (copy/paste from
    # ext_fcp_get_choice) so any real refresh raises NameError. By then domain and name of
    # the spec_item have already been overwritten, and the connection is left open.
    fake_db.responder = lambda sql: [diagram(7, 'newname', 'NewFcp', svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>',
                                             json_rep=fcp_json('NewFcp', 'Title: T\nd'))]
    item = make_item()
    with pytest.raises(NameError) as excinfo:
        ext_cats.ext_fcp_refresh(make_request(), item)
    assert 'ext_item_dict' in str(excinfo.value)
    assert (item.domain, item.name) == ('NewFcp', 'newname')
    assert item.value == '<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>'
    assert fake_db.conn.closed is True      # CHANGED: ext-cats-connection-leak (was: False; connection left open)


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

REAL_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10"></svg>'
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
    cur.execute('CREATE TABLE shares (diagramID INT NOT NULL, email VARCHAR(255) NOT NULL, perm VARCHAR(8) NOT NULL)')
    cur.execute("INSERT INTO users VALUES (42, 'alice@example.com')")
    cur.execute("INSERT INTO users VALUES (43, 'bob@example.com')")
    cur.execute("INSERT INTO diagrams VALUES (7, 42, 'Sm1', 'x', 'State Machine', %s, %s, %s, 100, 200)",
                (REAL_UPDATED, REAL_JSON, REAL_SVG))
    cur.execute("INSERT INTO diagrams VALUES (8, 42, 'Pr1', 'x', 'Procedure', %s, %s, %s, 11, 22)",
                (REAL_UPDATED, model_json('Dom2'), '<svg xmlns="http://www.w3.org/2000/svg" width="11"></svg>'))
    # bob's models: 9 shared with alice read-only, 10 shared with perm 'none', 11 not shared
    for dia_id, name in ((9, 'Shared'), (10, 'Hidden'), (11, 'Private')):
        cur.execute("INSERT INTO diagrams VALUES (%s, 43, %s, 'x', 'State Machine', %s, %s, %s, 5, 6)",
                    (dia_id, name, REAL_UPDATED, model_json('DomB'), REAL_SVG))
    cur.execute("INSERT INTO shares VALUES (9, 'alice@example.com', 'ro'), (10, 'alice@example.com', 'none'), "
                "(11, 'carol@example.com', 'rw')")
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
        # own models 7, 8 and bob's model 9 shared read-only (not 10: perm 'none', not 11: not shared)
        assert choices == [(7, 'Dom : Sm1'), (8, 'Dom2 : Pr1'), (9, 'DomB : Shared')]
        assert all(type(i) is int and type(label) is str for i, label in choices)
        assert msgs(request) == []

    def test_model_get_choices_unknown_user(self, real_fwprofile):
        # CHANGED: upstream #91 (was: IndexError reported as 'Error trying to retrieve the models for user ...')
        request = make_request(User(username='nobody', email='nobody@example.com'))
        assert ext_cats.ext_model_get_choices(request) == [(0, 'No Model Found')]
        assert msgs(request) == [('alert-danger', 'No models found in FW Profile Database for user "nobody')]

    def test_shared_visibility_with_real_driver(self, real_fwprofile):
        request = make_request()
        assert sorted(r[0] for r in ext_cats.get_visible_models(request)) == [7, 8, 9]
        assert ext_cats.get_visible_models(request, 10) == ()        # share with another perm
        assert ext_cats.get_visible_models(request, 11) == ()        # shared with somebody else
        assert ext_cats.ext_model_get_choice(request, 9)['name'] == 'Shared'
        bob = make_request(User(username='bob', email='bob@example.com'))
        assert sorted(r[0] for r in ext_cats.get_visible_models(bob)) == [9, 10, 11]

    def test_model_refresh_no_change_then_refresh(self, real_fwprofile):
        request = make_request()
        item = SpecItem(cat='Model', domain='Old', name='Old', value=REAL_SVG, n3=7, p_kind='STD',
                        n1=1, n2=2)
        assert ext_cats.ext_model_refresh(request, item) == 'NO_CHANGE'
        assert (item.domain, item.name, item.n1, item.n2) == ('Old', 'Old', 1, 2)
        assert msgs(request) == []

        item.value = '<svg xmlns="http://www.w3.org/2000/svg" width="12"></svg>'
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
        # CHANGED: upstream #91 (was: 'Model not found in FW Profile Database (its ID is: 999)')
        assert msgs(request) == [('alert-warning',
                                  'Model not found or not shared with you in FW Profile Database (its ID is: 999)')]

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
