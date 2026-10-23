"""
Worker for the MySQL migration rehearsal (see rehearse.py for the driver).

Runs inside ONE Django stack (old or new) with cwd = the code tree and
DJANGO_SETTINGS_MODULE=cordetfw_editor.settings, CORDETFW_CONFIG_PATH=<rehearsal config>.

    python worker.py <command> [args]

Commands (each prints one JSON document on stdout):
    populate                 build realistic data (old stack only)
    fingerprint <file>       row counts per table, CHECKSUM TABLE and row dumps of editor_* tables
    snapshot <dir>           HTML pages, spec-item CSV exports, project ZIP exports
    session_check <label>    saved OLD session cookie still authenticated?
    passwords <label>        POST /editor/login/ for every user, report hash change
    admin_check              axes AccessAttempt / honeypot LoginAttempt visible in /pnpAdmin/ ?
    save_session <name>      log in rehearsal_writer by POST and save its session cookie
    verify_session <name>    is a session cookie saved by `save_session` accepted?
    axes_fail                one failed POST login (rehearsal_reader)
    write_new                (new stack) create a release, user and spec items after migration
"""
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())
import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from django.db import connection  # noqa: E402
from django.test import Client  # noqa: E402

from editor.configs import configs  # noqa: E402
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet  # noqa: E402

SCRATCH = os.environ['REHEARSAL_SCRATCH']
STATE = os.path.join(SCRATCH, 'state.json')
PASSWORD = 'Rehearsal-pw-1'
T0 = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
T1 = datetime(2024, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
USERS = ['rehearsal_owner', 'rehearsal_writer', 'rehearsal_reader', 'rehearsal_super']


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(st):
    with open(STATE, 'w') as f:
        json.dump(st, f, indent=1, sort_keys=True)


def out(obj):
    print('JSON_RESULT ' + json.dumps(obj, sort_keys=True, default=str))


_tmp_counter = [0]


def fresh_temp_dir():
    """export_project names its directory by the second; give every call its own temp_dir."""
    _tmp_counter[0] += 1
    d = os.path.join(SCRATCH, 'tmp_exports', '%s_%d_%d' % (os.getpid(), int(datetime.now().timestamp()), _tmp_counter[0]))
    os.makedirs(d)
    configs['general']['temp_dir'] = d
    return d


def csrf_normalize(text):
    return re.sub(r'(name="csrfmiddlewaretoken" value=")[^"]*', r'\1CSRF', text)


# ----------------------------------------------------------------------------------------
# populate
# ----------------------------------------------------------------------------------------

def populate():
    st = {}
    owner = User.objects.create_user('rehearsal_owner', 'o@example.com', PASSWORD, is_staff=True)
    writer = User.objects.create_user('rehearsal_writer', 'w@example.com', PASSWORD)
    reader = User.objects.create_user('rehearsal_reader', 'r@example.com', PASSWORD)
    User.objects.create_user('rehearsal_super', 's@example.com', PASSWORD, is_staff=True, is_superuser=True)
    st['old_hash_prefixes'] = {u.username: u.password.rsplit('$', 2)[0] for u in User.objects.all()}

    def rel(author, desc, pv, av, previous=None, at=T0, pk=None):
        kw = {'id': pk} if pk else {}
        return Release.objects.create(release_author=author, desc=desc, updated_at=at, project_version=pv,
                                      application_version=av, previous=previous, **kw)

    # ---- Project 1: with application, ValSets, users
    r0 = rel(owner, 'Initial release for project Alpha', 0, 0)
    p1 = Project.objects.create(name='Alpha Proj', desc='Alpha with unicode ä µ ☺\nsecond line',
                                cats='DataItem,EnumType,EnumValue,DataItemType,PacketPar', owner=owner, release=r0)
    vs_def = ValSet.objects.create(project=p1, name='Default', desc='Default ValSet')
    vs1 = ValSet.objects.create(project=p1, name='VS1', desc='Alternative "values"')
    vs2 = ValSet.objects.create(project=p1, name='VSä', desc='Third | set')
    ProjectUser.objects.create(project=p1, user=reader, role='RO')
    ProjectUser.objects.create(project=p1, user=writer, role='RW')
    a0 = rel(owner, 'Initial release for application', 0, 0)
    app = Application.objects.create(name='App One', desc='Application | desc', cats='Requirement,ParReq',
                                     project=p1, release=a0)

    def item(project, cat, domain, name, **kw):
        kw.setdefault('title', 'Title of ' + name)
        kw.setdefault('updated_at', T1)
        kw.setdefault('created_at', T0)
        kw.setdefault('owner', owner)
        kw.setdefault('val_set', vs_def if project is p1 else ValSet.objects.get(project=project, name='Default'))
        kw.setdefault('status', 'NEW')
        return SpecItem.objects.create(project=project, cat=cat, domain=domain, name=name, **kw)

    uint8 = item(p1, 'DataItemType', 'Types', 'uint8', title='Unsigned 8', n1=1, implementation='unsigned char',
                 desc='Plain with | pipe and "quotes" and \'single\'')
    color_old = item(p1, 'EnumType', 'Types', 'Color', status='OBS', updated_at=T0, n1=4, title='Colour (old)',
                     desc='old description')
    color_old2 = item(p1, 'EnumType', 'Types', 'Color', status='OBS', updated_at=T1, n1=4, previous=color_old,
                      title='Colour (older)', desc='second description')
    color = item(p1, 'EnumType', 'Types', 'Color', n1=4, previous=color_old2, title='Colour',
                 desc='Colors ä µ ☺ and **markdown**\n\n- bullet one\n- bullet two',
                 change_log='changed\r\nwith CRLF')
    red = item(p1, 'EnumValue', 'Types', 'Red', s_link=color, value='0', title='Red')
    green = item(p1, 'EnumValue', 'Types', 'Green', s_link=color, value='1', title='Green')
    count = item(p1, 'DataItem', 'Dom', 'Count', p_link=uint8, value='42', p_kind='CNS', s_kind='')
    colorvar = item(p1, 'DataItem', 'Dom', 'ColorVar', p_link=color, value='#iref:%d' % red.id,
                    desc='See #iref:%d and #iref:%d and **bold**\nnewline "q" | pipe; dangling #iref:99999'
                         % (red.id, uint8.id),
                    rationale='x | y', remarks='  padded  ', t1='1', t2='µm', p_kind='VAR', status='MOD',
                    n3=7, s_data={'a': 1, 'k': [1, 2], 'u': 'ä'})
    item(p1, 'DataItem', 'Dom', 'Calc', p_link=uint8, value='#iref:%d * 2' % count.id, p_kind='CNS')
    item(p1, 'DataItem', 'Dom', 'Count', p_link=uint8, value='43', val_set=vs1, p_kind='CNS')
    item(p1, 'DataItem', 'Dom', 'Count', p_link=uint8, value='44', val_set=vs2, p_kind='CNS')
    req1 = item(p1, 'Requirement', 'AppDom', 'R1', application=app, owner=writer, p_kind='STD', s_kind='TST',
                value='The app shall use #iref:%d and ä' % count.id, t1='close', t2='valid', title='Req 1')
    item(p1, 'Requirement', 'AppDom', 'R2', application=app, status='MOD', value='Second requirement',
         p_link=req1, s_link=req1)
    item(p1, 'ParReq', 'AppDom', 'PR1', application=app, value='Parent req', title='Parent requirement')

    # ---- Project 2: unicode name, no application
    r20 = rel(owner, 'Initial release for project Beta', 0, 0)
    p2 = Project.objects.create(name='Größe Beta ☺', desc='Second project',
                                cats='DataItem,EnumType,EnumValue,DataItemType', owner=owner, release=r20)
    ValSet.objects.create(project=p2, name='Default', desc='Default ValSet')
    ProjectUser.objects.create(project=p2, user=writer, role='RO')
    t2 = item(p2, 'DataItemType', 'T', 'uint16', n1=2, title='Unsigned 16')
    item(p2, 'DataItem', 'D', 'X', p_link=t2, value='-5', p_kind='CNS')

    # ---- Real login (creates a DB session) for the owner; keep the cookie
    c = Client()
    r = c.post('/editor/login/', {'username': 'rehearsal_owner', 'password': PASSWORD})
    assert r.status_code == 302, r.status_code
    st['old_session_cookie'] = c.cookies[settings.SESSION_COOKIE_NAME].value
    assert 'rehearsal_owner' in c.get('/editor/').content.decode()

    # ---- Releases through the real views (do_project_release / do_application_release)
    r = c.post('/editor/%d/make_project_release' % p1.id, {'description': 'First ä release | with pipe\nand newline'})
    assert r.status_code == 302
    r = c.post('/editor/%d/make_application_release' % app.id, {'description': 'Application release µ'})
    assert r.status_code == 302
    r = c.post('/editor/%d/make_project_release' % p2.id, {'description': 'Beta first'})
    assert r.status_code == 302
    # second project release of p1, then more items in every state on top of it
    r = c.post('/editor/%d/make_project_release' % p1.id, {'description': 'Second release of Alpha'})
    assert r.status_code == 302

    # ---- Items after the releases: states NEW / MOD / CNF / OBS / DEL, numbers, JSON
    item(p1, 'DataItemType', 'Types', 'int16', title='New type after release', n1=2)
    item(p1, 'DataItem', 'Dom', 'Modified', status='MOD', p_link=uint8, value='#iref:%d' % count.id)
    item(p1, 'DataItem', 'Dom', 'Confirmed', status='CNF', p_link=uint8, value='1')
    item(p1, 'DataItem', 'Dom', 'Deleted', status='DEL', p_link=uint8, value='2')
    old_o = item(p1, 'DataItem', 'Dom', 'Chained', status='OBS', p_link=uint8, value='1', updated_at=T0)
    old_o2 = item(p1, 'DataItem', 'Dom', 'Chained', status='OBS', p_link=uint8, value='2', previous=old_o)
    item(p1, 'DataItem', 'Dom', 'Chained', status='MOD', p_link=uint8, value='3', previous=old_o2)
    # explicit ids (>= 1000, for number rendering) placed above existing rows (production dumps)
    id_base = max(0, (SpecItem.objects.order_by('-id').values_list('id', flat=True).first() or 0) + 1 - 1000)
    SpecItem.objects.create(id=id_base + 1000, cat='PacketPar', domain='Pkt', name='Edge', title='Edge numbers', project=p1,
                            owner=owner, val_set=vs_def, status='CNF', updated_at=T1, created_at=T0,
                            n1=2147483647, n2=-2147483648, n3=1000000)
    SpecItem.objects.create(id=id_base + 1234, cat='PacketPar', domain='Pkt', name='Big', title='Big numbers', project=p1,
                            owner=owner, val_set=vs_def, status='NEW', updated_at=T2, created_at=T0,
                            n1=12345, n2=-7, n3=0, s_data={'zz': 1, 'a': 2, 'nested': {'y': 1, 'b': [1, 2]}})
    SpecItem.objects.create(id=id_base + 2001, cat='DataItem', domain='Json', name='Order', title='Json order', project=p1,
                            owner=owner, val_set=vs_def, status='NEW', updated_at=T1, created_at=T0,
                            s_data={'list': [3, 1, 2], 'text': 'ä☺ "q"', 'empty': {}, 'num': -1.5})
    item(p2, 'DataItem', 'D', 'Y', status='MOD', value='1000')

    # ---- axes AccessAttempt (1 failed login) and honeypot LoginAttempt
    c2 = Client()
    r = c2.post('/editor/login/', {'username': 'rehearsal_writer', 'password': 'wrong-password'})
    assert r.status_code == 200, r.status_code
    c3 = Client()
    r = c3.post('/admin/login/', {'username': 'honeypot_visitor', 'password': 'guess'})
    assert r.status_code in (200, 302), r.status_code

    st['project_ids'] = [p1.id, p2.id]
    save_state(st)
    out({'projects': st['project_ids'], 'spec_items': SpecItem.objects.count(), 'releases': Release.objects.count(),
         'users': User.objects.count(), 'old_hash_prefixes': st['old_hash_prefixes']})


# ----------------------------------------------------------------------------------------
# fingerprint
# ----------------------------------------------------------------------------------------

def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode('utf-8', 'replace')
    return v


def fingerprint(path):
    res = {'counts': {}, 'checksums': {}, 'rows': {}}
    with connection.cursor() as cur:
        tables = sorted(connection.introspection.table_names())
        for t in tables:
            cur.execute('SELECT COUNT(*) FROM `%s`' % t)
            res['counts'][t] = cur.fetchone()[0]
        for t in tables:
            if t.startswith('editor_'):
                cur.execute('CHECKSUM TABLE `%s`' % t)
                res['checksums'][t] = cur.fetchone()[1]
                cur.execute('SELECT * FROM `%s` ORDER BY id' % t)
                cols = [c[0] for c in cur.description]
                res['rows'][t] = [dict(zip(cols, map(_jsonable, row))) for row in cur.fetchall()]
        cur.execute("SELECT app, name FROM django_migrations ORDER BY app, name")
        res['migrations'] = ['%s.%s' % tuple(r) for r in cur.fetchall()]
        cur.execute("SELECT @@version, @@character_set_database, @@collation_database")
        res['server'] = list(cur.fetchone())
        cur.execute("SELECT table_name, column_name, column_type, is_nullable, character_set_name, collation_name "
                    "FROM information_schema.columns WHERE table_schema = DATABASE() "
                    "ORDER BY table_name, ordinal_position")
        res['schema'] = [[_jsonable(x) for x in r] for r in cur.fetchall()]
    with open(path, 'w') as f:
        json.dump(res, f, indent=1, sort_keys=True, default=str)
    out({'tables': len(res['counts']), 'editor_rows': {t: len(r) for t, r in res['rows'].items()}})


# ----------------------------------------------------------------------------------------
# snapshot
# ----------------------------------------------------------------------------------------

def snapshot(outdir, exports_only=False):
    owner = User.objects.get(username='rehearsal_owner')
    c = Client()
    c.force_login(owner)
    os.makedirs(outdir, exist_ok=True)
    summary = {'zip': 0, 'csv': 0, 'html': 0, 'errors': []}
    headers = {}

    def save(rel, data):
        p = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f:
            f.write(data if isinstance(data, bytes) else data.encode('utf-8'))

    for p in Project.objects.order_by('id'):
        pid = p.id
        c.force_login(p.owner)   # read access requires ownership/membership; staff alone is not enough
        r = c.get('/editor/%d/export_project' % pid) if fresh_temp_dir() else None
        data = b''.join(r.streaming_content) if r.status_code == 200 else b''
        if r.status_code != 200:
            summary['errors'].append('export_project %d -> %s' % (pid, r.status_code))
            continue
        save('export_project/%d/_raw.zip' % pid, data)
        zf = zipfile.ZipFile(io.BytesIO(data))
        save('export_project/%d/_namelist.txt' % pid, '\n'.join(zf.namelist()))
        for m in zf.namelist():
            save('export_project/%d/%s' % (pid, m), zf.read(m))
        summary['zip'] += 1
        vs_default = ValSet.objects.get(project=p, name='Default')
        vsets = list(ValSet.objects.filter(project=p).order_by('id'))
        pcats = [x.strip() for x in p.cats.split(',')]
        targets = [(cat, 0) for cat in pcats if configs['cats'][cat]['level'] == 'project']
        for app in Application.objects.filter(project=p).order_by('id'):
            targets += [(cat.strip(), app.id) for cat in app.cats.split(',') if cat.strip()]
        for cat, aid in targets:
            for vs in (vsets if aid == 0 and cat == 'DataItem' else [vs_default]):
                base = '/editor/%s/%d/%d/%d/Sel_All/0/' % (cat, pid, aid, vs.id)
                for suffix, tag in (('export_spec_items', 'csv'), ('export_spec_items?export=latex_format', 'latex')):
                    r = c.get(base + suffix)
                    if r.status_code != 200:
                        summary['errors'].append('%s%s -> %s' % (base, suffix, r.status_code))
                        continue
                    name = 'export_spec_items/%d_%d_%s_vs%d_%s.txt' % (pid, aid, cat, vs.id, tag)
                    save(name, r.content)
                    headers[name] = r['Content-Disposition']
                    summary['csv'] += 1
                if exports_only:
                    continue
                r = c.get(base + 'list_spec_items')
                if r.status_code != 200:
                    summary['errors'].append('%slist_spec_items -> %s' % (base, r.status_code))
                    continue
                save('html/list_%d_%d_%s_vs%d.html' % (pid, aid, cat, vs.id), csrf_normalize(r.content.decode()))
                summary['html'] += 1
    save('export_headers.json', json.dumps(headers, indent=1, sort_keys=True))
    if not exports_only:
        r = c.get('/editor/')
        save('html/index.html', csrf_normalize(r.content.decode()))
        summary['html'] += 1
    out(summary)


# ----------------------------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------------------------

def session_check(label):
    st = load_state()
    c = Client()
    c.cookies[settings.SESSION_COOKIE_NAME] = st['old_session_cookie']
    r = c.get('/editor/')
    body = r.content.decode()
    out({'label': label, 'status': r.status_code, 'username_shown': 'rehearsal_owner' in body})


def passwords(label):
    res = {}
    users = USERS + (['rehearsal_newuser'] if User.objects.filter(username='rehearsal_newuser').exists() else [])
    for u in users:
        before = User.objects.get(username=u).password.rsplit('$', 2)[0]
        c = Client()
        r = c.post('/editor/login/', {'username': u, 'password': PASSWORD})
        shown = False
        if r.status_code == 302:
            shown = u in c.get('/editor/').content.decode()
        after = User.objects.get(username=u).password.rsplit('$', 2)[0]
        res[u] = {'login_status': r.status_code, 'username_shown': shown, 'hash_before': before, 'hash_after': after}
    out({'label': label, 'users': res})


def admin_check():
    c = Client()
    c.force_login(User.objects.get(username='rehearsal_super'))
    res = {}
    for key, url, needle in (
            ('axes_accessattempt', '/pnpAdmin/axes/accessattempt/', 'rehearsal_writer'),
            ('honeypot_loginattempt', '/pnpAdmin/admin_honeypot/loginattempt/', 'honeypot_visitor')):
        r = c.get(url)
        body = r.content.decode()
        m = re.search(r'(\d+) (?:access attempt|login attempt)s?', body)
        res[key] = {'status': r.status_code, 'needle_present': needle in body,
                    'count_text': m.group(0) if m else None}
    with connection.cursor() as cur:
        for t in ('axes_accessattempt', 'admin_honeypot_loginattempt', 'axes_accesslog'):
            try:
                cur.execute('SELECT COUNT(*) FROM `%s`' % t)
                res[t + '_rows'] = cur.fetchone()[0]
            except Exception as e:  # table might not exist
                res[t + '_rows'] = 'ERR ' + str(e)[:60]
    out(res)


def save_session(name):
    c = Client()
    r = c.post('/editor/login/', {'username': 'rehearsal_writer', 'password': PASSWORD})
    st = load_state()
    st[name] = c.cookies[settings.SESSION_COOKIE_NAME].value
    save_state(st)
    out({'status': r.status_code, 'saved': name})


def verify_session(name):
    st = load_state()
    c = Client()
    c.cookies[settings.SESSION_COOKIE_NAME] = st[name]
    r = c.get('/editor/')
    out({'cookie': name, 'status': r.status_code, 'username_shown': 'rehearsal_writer' in r.content.decode()})


def axes_fail():
    c = Client()
    r = c.post('/editor/login/', {'username': 'rehearsal_reader', 'password': 'wrong-again'})
    with connection.cursor() as cur:
        cur.execute('SELECT username, failures_since_start FROM axes_accessattempt ORDER BY id')
        rows = cur.fetchall()
    out({'status': r.status_code, 'attempts': rows})


def write_new():
    """Data written by the NEW stack, to be read back by the OLD stack after a rollback."""
    owner = User.objects.get(username='rehearsal_owner')
    c = Client()
    c.force_login(owner)
    p2 = Project.objects.get(name__startswith='Gr')
    r = c.post('/editor/%d/make_project_release' % p2.id, {'description': 'Release written by the new stack ä'})
    vs = ValSet.objects.get(project=p2, name='Default')
    t = SpecItem.objects.create(project=p2, cat='DataItemType', domain='T', name='int32', title='Written by new',
                                owner=owner, val_set=vs, status='NEW', updated_at=T2, created_at=T2, n1=-123456,
                                n2=2147483647, desc='new-stack ä☺', s_data={'k': [1, {'z': None}]})
    SpecItem.objects.create(project=p2, cat='DataItem', domain='D', name='Z', title='Linked by new', owner=owner,
                            val_set=vs, status='MOD', updated_at=T2, created_at=T2, p_link=t,
                            value='#iref:%d' % t.id, previous=None)
    newu = User.objects.create_user('rehearsal_newuser', 'n@example.com', PASSWORD)
    out({'release_status': r.status_code, 'new_user_hash': newu.password.rsplit('$', 2)[0]})
    # also a new-user login for the old stack to try
    st = load_state()
    st['newuser'] = 'rehearsal_newuser'
    save_state(st)


if __name__ == '__main__':
    cmd, args = sys.argv[1], sys.argv[2:]
    {
        'populate': populate,
        'fingerprint': fingerprint,
        'snapshot': lambda d, *a: snapshot(d, exports_only=bool(a)),
        'session_check': session_check,
        'passwords': passwords,
        'admin_check': admin_check,
        'save_session': save_session,
        'verify_session': verify_session,
        'axes_fail': axes_fail,
        'write_new': write_new,
    }[cmd](*args)
