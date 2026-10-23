"""
Task 6.8e: do exports of a production-shaped database still import with the new code?

Contains NO data. Needs the new venv (.venv), the disposable MySQL container and a (sanitised or real)
dump. Output is aggregate only (counts, hashes compared in-process, never printed); projects are
referred to by index 1..N. Everything is created in a scratch directory and a database that are removed
by the `cleanup` command.

    REIMPORT_DUMP=<dump.sql[.bz2]> REIMPORT_SCRATCH=<dir> .venv/bin/python docs/migration/rehearsal/reimport.py setup
    ... reimport.py run          # exports every project (ZIP + spec-item CSVs) and re-imports them
    ... reimport.py cleanup      # DROP DATABASE, delete scratch

`run` for every project (as its owner): export_project ZIP, export_spec_items CSV (normal format) of the
Default ValSet for every (category, application) that has items; then, as the project owner / a staff user:
import_project of the ZIP (project renamed in the ZIP copy), compare counts and SVG value hashes with the
source, import_spec_items of each CSV into the imported copy (update path) and into a fresh empty project
with the same applications (new-item path).
"""
import bz2
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCRATCH = os.environ['REIMPORT_SCRATCH']
DB = 'cordetfw_reimport'
ROOT_PW = 'rootpw-test'
CONTAINER = 'cordetfw-mysql-test'
CONFIG = os.path.join(SCRATCH, 'config.json')

os.environ.update(CORDETFW_CONFIG_PATH=CONFIG, DJANGO_SETTINGS_MODULE='cordetfw_editor.settings',
                  PYTHONDONTWRITEBYTECODE='1')


def mysql(sql=None, db=None, stdin=None):
    cmd = ['docker', 'exec', '-i', CONTAINER, 'mysql', '-uroot', '-p' + ROOT_PW] + ([db] if db else []) + \
          (['-e', sql] if sql else [])
    p = subprocess.run(cmd, stdin=stdin, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit('mysql failed: ' + p.stderr[-500:])


def setup():
    os.makedirs(os.path.join(SCRATCH, 'media'), exist_ok=True)
    os.makedirs(os.path.join(SCRATCH, 'tmp'), exist_ok=True)
    cfg = {'SECURE_KEY': 'reimport-key', 'DEBUG': False, 'ALLOWED_HOSTS': ['testserver', 'localhost'],
           'DATABASES': {'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': DB, 'USER': 'root',
                                     'PASSWORD': ROOT_PW, 'HOST': '127.0.0.1', 'PORT': '33306'}},
           'MEDIA_ROOT': os.path.join(SCRATCH, 'media'), 'LOG_FILE': os.path.join(SCRATCH, 'editor.log'),
           'BASE_URL': '/editor', 'FWPROFILE_DB': {'HOST': 'unused-host', 'USER': 'x', 'PWD': 'x', 'NAME': 'x'}}
    with open(CONFIG, 'w') as f:
        json.dump(cfg, f)
    mysql('DROP DATABASE IF EXISTS %s; CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci' % (DB, DB))
    dump = os.environ['REIMPORT_DUMP']
    if dump.endswith('.bz2'):
        plain = os.path.join(SCRATCH, 'dump.sql')
        with bz2.open(dump, 'rb') as src, open(plain, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        dump = plain
    with open(dump, 'rb') as src:
        subprocess.run(['docker', 'exec', '-i', CONTAINER, 'mysql', '-uroot', '-p' + ROOT_PW, DB],
                       stdin=src, check=True, capture_output=True)
    p = subprocess.run([sys.executable, 'manage.py', 'migrate', '--noinput'], cwd=REPO, capture_output=True, text=True)
    print(re.sub(r'\n+', '\n', p.stdout[-800:]), p.stderr[-800:], 'migrate exit', p.returncode)


def cleanup():
    mysql('DROP DATABASE IF EXISTS %s' % DB)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    print('cleaned')


def sha(x):
    return hashlib.sha256(str(x).encode()).hexdigest()[:16]


def run():
    sys.path.insert(0, REPO)
    import django
    django.setup()
    from django.contrib.auth.models import User
    from django.contrib.messages import get_messages
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from django.utils import timezone
    from editor.configs import configs
    from editor.models import Application, Project, Release, SpecItem, ValSet

    n = [0]

    def fresh_temp_dir():
        n[0] += 1
        d = os.path.join(SCRATCH, 'tmp', 'd%d_%d' % (os.getpid(), n[0]))
        os.makedirs(d)
        configs['general']['temp_dir'] = d

    def msgs(resp):
        return [(m.level_tag, str(m.message)) for m in get_messages(resp.wsgi_request)]

    def generic(level, text):
        """Message kind without any data (names are cut)."""
        t = re.sub(r'\d+', 'N', text)
        for key in ('Failure to import spec_item', 'disallowed content', 'already exists', 'does not exist',
                    'Unable to', 'row(s) imported successfully', 'row(s) could not be imported',
                    'does not match', 'not defined in configs', 'Failure to open', 'too big'):
            if key in t:
                if key == 'Failure to import spec_item':
                    m = re.search(r'Error is: (\w+)', t)
                    return level + ':' + key + ' [' + (m.group(1) if m else '?') + ']'
                if key == 'row(s) could not be imported':
                    return level + ':' + key + ': ' + re.sub(r'^.*?: ', '', t)[:150]
                return level + ':' + key
        return level + ':OTHER ' + t[:30]

    staff = User.objects.filter(is_staff=True, is_active=True).order_by('id').first()
    FIELDS = ['title', 'desc', 'rationale', 'implementation', 'remarks', 'value', 't1', 't2', 't3', 't4', 't5',
              'n1', 'n2', 'n3', 'p_kind', 's_kind', 'change_log', 'owner_id']

    def item_rows(project):
        """list of (key, {field: hash}) with app/valset referred to by name."""
        rows = []
        for it in SpecItem.objects.filter(project=project).select_related('application', 'val_set', 'owner'):
            key = (it.cat, it.domain, it.name, it.status, it.val_set.name, it.application.name if it.application else None)
            h = {f: sha(getattr(it, f)) for f in FIELDS if f != 'owner_id'}
            # normalised: object ids in #iref:N differ by nature, CR LF is lost on import (known issue)
            h.update({f + '~': sha(re.sub(r'#iref:\d+', '#iref:N', str(getattr(it, f))).replace('\r\n', '\n'))
                      for f in FIELDS if f != 'owner_id'})
            h['owner'] = sha(it.owner.username)
            h['s_data'] = sha(json.dumps(it.s_data, sort_keys=True))
            rows.append((key, h))
        return rows

    def compare(src, imp):
        a, b = item_rows(src), item_rows(imp)
        res = {'items_src': len(a), 'items_imp': len(b)}
        ca = Counter((k[0], k[3], k[4], k[5] is None) for k, _ in a)
        cb = Counter((k[0], k[3], k[4], k[5] is None) for k, _ in b)
        res['count_groups_differ'] = sum(1 for k in set(ca) | set(cb) if ca[k] != cb[k])
        res['valsets'] = (ValSet.objects.filter(project=src).count(), ValSet.objects.filter(project=imp).count())
        res['apps'] = (Application.objects.filter(project=src).count(), Application.objects.filter(project=imp).count())
        kinds = Counter()
        ma = {}
        for k, h in a:
            ma.setdefault(k, []).append(h)
        mb = {}
        for k, h in b:
            mb.setdefault(k, []).append(h)
        for k in set(ma) | set(mb):
            la, lb = ma.get(k, []), mb.get(k, [])
            for f in [x for x in FIELDS if x != 'owner_id'] + [x + '~' for x in FIELDS if x != 'owner_id'] + ['s_data', 'owner']:
                if f == 'owner_id':
                    continue
                ca_, cb_ = Counter(x[f] for x in la), Counter(x[f] for x in lb)
                kinds[f] += sum((ca_ - cb_).values())
        res['field_diffs_raw'] = {k: v for k, v in kinds.items() if v and not k.endswith('~')}
        res['field_diffs_after_iref_crlf_normalisation'] = {k[:-1]: v for k, v in kinds.items() if v and k.endswith('~')}
        svg = [(k, h['value']) for k, h in a if k[0] in ('Model', 'FCP')]
        svgb = Counter((k, v) for k, v in [(k, h['value']) for k, h in b if k[0] in ('Model', 'FCP')])
        res['svg_total'] = len(svg)
        res['svg_identical'] = sum(1 for kv in svg if svgb[kv] > 0)
        return res

    def upload(client, url, name, data):
        return client.post(url, {'upload_file': SimpleUploadedFile(name, data)})

    projects = list(Project.objects.order_by('id'))
    ids = [p.id for p in projects]
    report = {'projects': {}, 'totals': Counter(), 'msg_kinds_zip': Counter(), 'msg_kinds_csv_update': Counter(),
              'msg_kinds_csv_new': Counter()}
    for idx, pid in enumerate(ids, 1):
        src = Project.objects.get(id=pid)
        r = {}
        report['projects'][idx] = r
        c = Client()
        c.force_login(src.owner)
        fresh_temp_dir()
        resp = c.get('/editor/%d/export_project' % pid)
        if resp.status_code != 200:
            r['export_zip'] = 'HTTP %s' % resp.status_code
            continue
        zdata = b''.join(resp.streaming_content)
        # ---- spec item CSV exports (Default ValSet), every (cat, application) with items
        vs_def = ValSet.objects.get(project=src, name='Default')
        combos = sorted({(i.cat, i.application_id) for i in SpecItem.objects.filter(project=src, val_set=vs_def)},
                        key=lambda t: (t[0], t[1] or 0))
        csvs = []
        r['csv_exports'] = 0
        r['csv_empty'] = 0
        for cat, aid in combos:
            resp = c.get('/editor/%s/%d/%d/%d/Sel_All/0/export_spec_items' % (cat, pid, aid or 0, vs_def.id))
            if resp.status_code != 200:
                r.setdefault('csv_export_http_err', 0)
                r['csv_export_http_err'] += 1
                continue
            if not resp.content.strip():
                r['csv_empty'] += 1
                continue
            csvs.append((cat, aid, resp.content))
            r['csv_exports'] += 1
        # ---- rename project in the ZIP copy
        zin = zipfile.ZipFile(io.BytesIO(zdata))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zout:
            for name in zin.namelist():
                data = zin.read(name)
                if name == 'project.csv':
                    text = data.decode('utf-8')
                    rows = list(csv.DictReader(io.StringIO(text)))
                    o = io.StringIO()
                    w = csv.DictWriter(o, fieldnames=list(rows[0].keys()), lineterminator='\r\n')
                    w.writeheader()
                    rows[0]['name'] = 'reimport_%d_copy' % idx
                    w.writerow(rows[0])
                    data = o.getvalue().encode('utf-8')
                zout.writestr(name, data)
        # ---- diagnosis of rows that cannot import (which cross-reference of the CSV is dangling), no data kept
        zr = {m: list(csv.DictReader(io.StringIO(zin.read(m).decode('utf-8')))) for m in
              ('project.csv', 'project_users.csv', 'val_sets.csv', 'applications.csv', 'spec_items.csv')}
        okusers = {u['user'] for u in zr['project_users.csv']} | {zr['project.csv'][0]['owner']}
        okvs = {v['id'] for v in zr['val_sets.csv']}
        okapp = {a['id'] for a in zr['applications.csv']} | {''}
        diag = Counter()
        for row in zr['spec_items.csv']:
            if row['owner'] not in okusers:
                diag['item owner is neither project owner nor project user'] += 1
            if row['val_set'] not in okvs:
                diag['val_set id not in val_sets.csv'] += 1
            if row['application'] not in okapp:
                diag['application id not in applications.csv'] += 1
        r['zip_diag_rows_expected_to_fail'] = dict(diag)
        # ---- import project as staff user
        before = set(Project.objects.values_list('id', flat=True))
        ic = Client()
        ic.force_login(staff)
        fresh_temp_dir()
        try:
            resp = upload(ic, '/editor/import_project', 'p.zip', buf.getvalue())
            ms = msgs(resp)
            r['zip_http'] = resp.status_code
        except Exception as e:
            ms = [('error', 'Unable to EXC ' + type(e).__name__)]
            r['zip_http'] = 'EXC ' + type(e).__name__
        kinds = Counter(generic(l, t) for l, t in ms)
        r['zip_msgs'] = dict(kinds)
        report['msg_kinds_zip'].update(kinds)
        new = Project.objects.exclude(id__in=before)
        if new.count() != 1:
            r['zip_import'] = 'FAILED (projects created: %d)' % new.count()
            report['totals']['zip_failed'] += 1
            continue
        imp = new[0]
        bad = [k for k in kinds if k.startswith('error')]
        r['zip_import'] = 'ok' if not bad else 'FAILED'
        report['totals']['zip_ok' if not bad else 'zip_failed'] += 1
        r['compare'] = compare(src, imp)
        t = r['compare']
        report['totals']['svg_total'] += t['svg_total']
        report['totals']['svg_identical'] += t['svg_identical']
        report['totals']['items_src'] += t['items_src']
        report['totals']['items_imp'] += t['items_imp']
        # ---- fresh empty project, same applications / categories
        rel = Release.objects.create(release_author=src.owner, desc='x', project_version=0, application_version=0, updated_at=timezone.now())
        fresh = Project.objects.create(name='reimport_%d_fresh' % idx, desc='x', cats=src.cats, owner=src.owner, release=rel)
        ValSet.objects.create(project=fresh, name='Default', desc='Default')
        appmap_fresh = {}
        for a in Application.objects.filter(project=src).order_by('id'):
            ar = Release.objects.create(release_author=src.owner, desc='x', project_version=0, application_version=0, updated_at=timezone.now())
            appmap_fresh[a.name] = Application.objects.create(name=a.name, desc='x', cats=a.cats, project=fresh, release=ar)
        appname = {a.id: a.name for a in Application.objects.filter(project=src)}
        appmap_imp = {a.name: a for a in Application.objects.filter(project=imp)}
        vs_imp = ValSet.objects.get(project=imp, name='Default')
        vs_fresh = ValSet.objects.get(project=fresh, name='Default')
        oc = Client()
        oc.force_login(src.owner)
        r['csv_update'] = Counter()
        r['csv_new'] = Counter()
        for cat, aid, data in csvs:
            nm = appname.get(aid)
            for tag, target, vs, amap, bucket in (('update', imp, vs_imp, appmap_imp, 'msg_kinds_csv_update'),
                                                  ('new', fresh, vs_fresh, appmap_fresh, 'msg_kinds_csv_new')):
                app_id = amap[nm].id if nm else 0
                n_before = SpecItem.objects.filter(project=target).count()
                oc = Client()          # messages accumulate in a client's cookie; one client per upload
                oc.force_login(src.owner)
                try:
                    resp = upload(oc, '/editor/%s/%d/%d/%d/Sel_All/import_spec_items' % (cat, target.id, app_id, vs.id),
                                  'i.csv', data)
                    ms = msgs(resp)
                except Exception as e:
                    ms = [('error', 'Unable to EXC ' + type(e).__name__)]
                imported = sum(int(m.group(1)) for l, t in ms for m in [re.match(r'(\d+) row\(s\) imported', t)] if m)
                rows = max(0, len(list(csv.DictReader(io.StringIO(data.decode('utf-8')), delimiter='|'))))
                kinds = Counter(generic(l, t) for l, t in ms)
                report[bucket].update(kinds)
                n_after = SpecItem.objects.filter(project=target).count()
                cnt = r['csv_' + tag]
                cnt['csv_files'] += 1
                cnt['rows'] += rows
                cnt['imported'] += imported
                cnt['rows_rejected'] += sum(int(m.group(1)) for l, t in ms for m in [re.match(r'(\d+) row\(s\) could not', t)] if m)
                cnt['db_items_added'] += n_after - n_before
                cnt['files_with_error_msgs'] += 1 if any(k.startswith('error') for k in kinds) else 0
                report['totals']['csv_%s_rows' % tag] += rows
                report['totals']['csv_%s_imported' % tag] += imported
                report['totals']['csv_%s_added' % tag] += n_after - n_before
        r['csv_update'] = dict(r['csv_update'])
        r['csv_new'] = dict(r['csv_new'])
    report['totals'] = dict(report['totals'])
    for k in ('msg_kinds_zip', 'msg_kinds_csv_update', 'msg_kinds_csv_new'):
        report[k] = dict(report[k])
    print(json.dumps(report, indent=1, sort_keys=True, default=str))


if __name__ == '__main__':
    {'setup': setup, 'run': run, 'cleanup': cleanup}[sys.argv[1]]()
