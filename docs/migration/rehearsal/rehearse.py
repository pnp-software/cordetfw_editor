#!/usr/bin/env python3
"""
MySQL migration rehearsal driver (Django 3.2 -> 5.2 upgrade).  Run end to end with any python3:

    python3 docs/migration/rehearsal/rehearse.py [--keep]

What it does (details and last results: REPORT.md in this directory):
  1. creates database `cordetfw_rehearsal` on the disposable MySQL (docker container
     cordetfw-mysql-test, 127.0.0.1:33306, root/rootpw-test) and imports $REHEARSAL_DUMP (default tryout/mysql_init/cordetfw.sql)
  2. OLD stack (git worktree of baseline commit cd87ccb + .venv-baseline): migrate, populate data,
     fingerprint, snapshot (exports + HTML)
  3. NEW stack (this working tree + .venv): migrate, fingerprint, snapshot, session/password/admin checks
  4. rollback: OLD stack against the migrated database, snapshot + checks, then data written by the NEW
     stack read back by the OLD stack
  5. drops the database and removes the worktree (unless --keep)

Never touches test_cordetfw_migration_test; does not modify production code. Needs docker, the two venvs,
and REHEARSAL_SCRATCH (default: the session scratch dir below) for scratch output.
Helper: worker.py (runs inside one Django stack). Results: <scratch>/results.json, <scratch>/logs/.
"""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
SCRATCH = os.environ.get('REHEARSAL_SCRATCH', '/tmp/claude-1000/-home-pstump-Projects-cordetfweditor-migration/'
                         '2d4443f2-25ba-4bd2-b5c9-d9a3aa33ed64/scratchpad/rehearsal')
OLD_CODE = os.path.join(SCRATCH, 'old-code')
PY_OLD = os.path.join(REPO, '.venv-baseline', 'bin', 'python')
PY_NEW = os.path.join(REPO, '.venv', 'bin', 'python')
BASELINE_COMMIT = 'cd87ccb'
DB = 'cordetfw_rehearsal'
ROOT_PW = 'rootpw-test'
CONTAINER = 'cordetfw-mysql-test'
CONFIG = os.path.join(SCRATCH, 'rehearsal_config.json')
WORKER = os.path.join(HERE, 'worker.py')
LOGDIR = os.path.join(SCRATCH, 'logs')
RESULTS = {}
_step = [0]


def write_config():
    os.makedirs(os.path.join(SCRATCH, 'media'), exist_ok=True)
    cfg = {
        'SECURE_KEY': 'rehearsal-secret-key-same-for-old-and-new',
        'DEBUG': False,
        'ALLOWED_HOSTS': ['testserver', 'localhost'],
        'DATABASES': {'default': {'ENGINE': 'django.db.backends.mysql', 'NAME': DB, 'USER': 'root',
                                  'PASSWORD': ROOT_PW, 'HOST': '127.0.0.1', 'PORT': '33306'}},
        'MEDIA_ROOT': os.path.join(SCRATCH, 'media'),
        'LOG_FILE': os.path.join(SCRATCH, 'editor.log'),
        'BASE_URL': '/editor',
        'FWPROFILE_DB': {'HOST': 'unused-host', 'USER': 'x', 'PWD': 'x', 'NAME': 'x'},
    }
    with open(CONFIG, 'w') as f:
        json.dump(cfg, f, indent=1)


def env():
    e = dict(os.environ)
    e.update(CORDETFW_CONFIG_PATH=CONFIG, DJANGO_SETTINGS_MODULE='cordetfw_editor.settings',
             REHEARSAL_SCRATCH=SCRATCH, PYTHONDONTWRITEBYTECODE='1')
    return e


def run(name, cmd, cwd=None, stdin=None, check=True):
    _step[0] += 1
    log = os.path.join(LOGDIR, '%02d_%s.log' % (_step[0], name))
    p = subprocess.run(cmd, cwd=cwd, env=env(), stdin=stdin, capture_output=True, text=True)
    with open(log, 'w') as f:
        f.write('$ %s\n(cwd=%s)\n--- stdout\n%s\n--- stderr\n%s\n--- exit %d\n' % (cmd, cwd, p.stdout, p.stderr, p.returncode))
    print('[%02d] %-34s exit=%d' % (_step[0], name, p.returncode))
    if check and p.returncode != 0:
        print(p.stdout[-2000:], p.stderr[-3000:])
        raise SystemExit('step failed: ' + name)
    return p


def mysql(sql, stdin=None, db=None):
    cmd = ['docker', 'exec', '-i', CONTAINER, 'mysql', '-uroot', '-p' + ROOT_PW] + ([db] if db else []) + (['-e', sql] if sql else [])
    p = subprocess.run(cmd, stdin=stdin, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit('mysql failed: ' + p.stderr)
    return p.stdout


def worker(stack, name, *args):
    py, cwd = (PY_OLD, OLD_CODE) if stack == 'old' else (PY_NEW, REPO)
    p = run('%s_%s' % (stack, name), [py, WORKER, name] + list(args), cwd=cwd)
    for line in p.stdout.splitlines():
        if line.startswith('JSON_RESULT '):
            return json.loads(line[len('JSON_RESULT '):])
    raise SystemExit('no result from worker ' + name)


def manage(stack, label, *args, check=True):
    py, cwd = (PY_OLD, OLD_CODE) if stack == 'old' else (PY_NEW, REPO)
    p = run('%s_%s' % (stack, label), [py, 'manage.py'] + list(args), cwd=cwd, check=check)
    RESULTS.setdefault('manage', {})['%s_%s' % (stack, label)] = {'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    return p


# --------------------------------------------------------------------------- comparisons

LOGOUT_RE = re.compile(r'<li class="nav-item">\s*(?:<a class="nav-link" href="[^"]*logout/">\s*Logout\s*</a>|'
                       r'<form method="post" action="[^"]*logout/">.*?</form>)\s*</li>', re.S)


def tree(d):
    files = {}
    for root, _, names in os.walk(d):
        for n in names:
            p = os.path.join(root, n)
            files[os.path.relpath(p, d)] = p
    return files


def read(p):
    with open(p, 'rb') as f:
        return f.read()


def compare_trees(a, b, html_logout_normalize=False, skip=('_raw.zip',)):
    fa, fb = tree(a), tree(b)
    res = {'only_a': sorted(set(fa) - set(fb)), 'only_b': sorted(set(fb) - set(fa)), 'identical': 0,
           'different': [], 'logout_only': [], 'skipped_zip_raw': 0}
    for rel in sorted(set(fa) & set(fb)):
        if rel.endswith(skip):
            res['skipped_zip_raw'] += 1
            continue
        da, db = read(fa[rel]), read(fb[rel])
        if da == db:
            res['identical'] += 1
            continue
        if html_logout_normalize and rel.endswith('.html'):
            ta, tb = da.decode(), db.decode()
            na, nb = LOGOUT_RE.sub('<LOGOUT/>', ta), LOGOUT_RE.sub('<LOGOUT/>', tb)
            if na == nb and ta != na:
                res['logout_only'].append(rel)
                continue
            diff = ''.join(list(difflib.unified_diff(na.splitlines(1), nb.splitlines(1), 'a', 'b', n=1))[:60])
            res['different'].append({'file': rel, 'diff': diff})
        else:
            res['different'].append({'file': rel, 'diff': difflib.unified_diff and ''.join(list(difflib.unified_diff(
                da.decode('utf-8', 'replace').splitlines(1), db.decode('utf-8', 'replace').splitlines(1), 'a', 'b', n=1))[:40])})
    return res


def summarize_tree(name, r):
    print('  %s: identical=%d logout_only=%d different=%d only_a=%d only_b=%d' % (
        name, r['identical'], len(r['logout_only']), len(r['different']), len(r['only_a']), len(r['only_b'])))


def load(p):
    with open(p) as f:
        return json.load(f)


def compare_fingerprints(a, b):
    fa, fb = load(a), load(b)
    r = {'editor_rows_identical': fa['rows'] == fb['rows'], 'editor_checksums_identical': fa['checksums'] == fb['checksums'],
         'count_diffs': {t: [fa['counts'].get(t), fb['counts'].get(t)] for t in sorted(set(fa['counts']) | set(fb['counts']))
                         if fa['counts'].get(t) != fb['counts'].get(t)},
         'migrations_added': sorted(set(fb['migrations']) - set(fa['migrations'])),
         'migrations_removed': sorted(set(fa['migrations']) - set(fb['migrations'])),
         'schema_changed': [x for x in fb['schema'] if x not in fa['schema']],
         'schema_removed': [x for x in fa['schema'] if x not in fb['schema']]}
    return r


def main():
    keep = '--keep' in sys.argv
    shutil.rmtree(SCRATCH + '/logs', ignore_errors=True)
    for d in ('old', 'new', 'rollback', 'new_after', 'rollback_after', 'state.json', 'tmp_exports'):
        p = os.path.join(SCRATCH, d)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else (os.path.exists(p) and os.remove(p))
    os.makedirs(LOGDIR, exist_ok=True)
    write_config()
    try:
        # worktree with the baseline code (original app code + CORDETFW_CONFIG_PATH override only)
        if not os.path.isdir(OLD_CODE):
            run('worktree_add', ['git', 'worktree', 'add', '--detach', OLD_CODE, BASELINE_COMMIT], cwd=REPO)
        mysql('DROP DATABASE IF EXISTS %s; CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci' % (DB, DB))
        # REHEARSAL_DUMP: path of a SANITIZED production dump to rehearse on (default: 2022 tryout dump)
        dump = os.environ.get('REHEARSAL_DUMP', os.path.join(REPO, 'tryout/mysql_init/cordetfw.sql'))
        with open(dump, 'rb') as f:
            subprocess.run(['docker', 'exec', '-i', CONTAINER, 'mysql', '-uroot', '-p' + ROOT_PW, DB], stdin=f,
                           check=True, capture_output=True)
        print('[db] imported dump %s' % dump)

        # ---- Step 1/2: OLD stack
        manage('old', 'showmigrations_2022_schema', 'showmigrations')
        manage('old', 'migrate', 'migrate', '--noinput')
        manage('old', 'showmigrations_after_migrate', 'showmigrations')
        RESULTS['old_populate'] = worker('old', 'populate')
        RESULTS['old_admin'] = worker('old', 'admin_check')
        worker('old', 'fingerprint', os.path.join(SCRATCH, 'fp_old.json'))
        RESULTS['old_snapshot'] = worker('old', 'snapshot', os.path.join(SCRATCH, 'old'))

        # ---- Step 5: NEW stack
        manage('new', 'showmigrations_before', 'showmigrations')
        manage('new', 'migrate_plan', 'migrate', '--plan')
        manage('new', 'migrate', 'migrate', '--noinput')
        manage('new', 'showmigrations_after', 'showmigrations')
        manage('new', 'check', 'check')
        worker('new', 'fingerprint', os.path.join(SCRATCH, 'fp_new.json'))
        RESULTS['fp_old_vs_new'] = compare_fingerprints(os.path.join(SCRATCH, 'fp_old.json'), os.path.join(SCRATCH, 'fp_new.json'))
        print('  fingerprint editor rows identical:', RESULTS['fp_old_vs_new']['editor_rows_identical'])

        # ---- Step 6
        RESULTS['new_snapshot'] = worker('new', 'snapshot', os.path.join(SCRATCH, 'new'))
        RESULTS['cmp_old_new'] = compare_trees(os.path.join(SCRATCH, 'old'), os.path.join(SCRATCH, 'new'), html_logout_normalize=True)
        summarize_tree('old vs new', RESULTS['cmp_old_new'])
        # session cookie BEFORE password logins (a hash upgrade invalidates the owner's old sessions)
        RESULTS['new_session_old_cookie'] = worker('new', 'session_check', 'new_before_password_logins')
        RESULTS['new_admin'] = worker('new', 'admin_check')
        RESULTS['new_passwords'] = worker('new', 'passwords', 'new')
        RESULTS['new_session_old_cookie_after_pw'] = worker('new', 'session_check', 'new_after_password_logins')
        RESULTS['new_save_session'] = worker('new', 'save_session', 'new_writer_cookie')

        # ---- Step 7: rollback, old code against migrated DB (no restore)
        manage('old', 'rb_check', 'check')
        manage('old', 'rb_showmigrations', 'showmigrations')
        manage('old', 'rb_migrate_plan', 'migrate', '--plan')
        RESULTS['rb_snapshot'] = worker('old', 'snapshot', os.path.join(SCRATCH, 'rollback'))
        RESULTS['cmp_old_rollback'] = compare_trees(os.path.join(SCRATCH, 'old'), os.path.join(SCRATCH, 'rollback'))
        summarize_tree('old vs rollback', RESULTS['cmp_old_rollback'])
        worker('old', 'fingerprint', os.path.join(SCRATCH, 'fp_rollback.json'))
        RESULTS['fp_new_vs_rollback'] = compare_fingerprints(os.path.join(SCRATCH, 'fp_new.json'), os.path.join(SCRATCH, 'fp_rollback.json'))
        RESULTS['rb_verify_new_cookie'] = worker('old', 'verify_session', 'new_writer_cookie')
        RESULTS['rb_session_old_cookie'] = worker('old', 'session_check', 'rollback')
        RESULTS['rb_passwords'] = worker('old', 'passwords', 'rollback')
        RESULTS['rb_axes_fail'] = worker('old', 'axes_fail')
        RESULTS['rb_admin'] = worker('old', 'admin_check')

        # data written by the NEW code, read by the OLD code
        # (re-upgrade hashes first so the new stack's state is the realistic "after rollback" one)
        RESULTS['new_write'] = worker('new', 'write_new')
        worker('new', 'snapshot', os.path.join(SCRATCH, 'new_after'), 'exports_only')
        worker('old', 'snapshot', os.path.join(SCRATCH, 'rollback_after'), 'exports_only')
        RESULTS['cmp_newafter_rollbackafter'] = compare_trees(os.path.join(SCRATCH, 'new_after'), os.path.join(SCRATCH, 'rollback_after'))
        summarize_tree('new-after-write vs rollback-after-write', RESULTS['cmp_newafter_rollbackafter'])
        RESULTS['rb_passwords_newuser'] = worker('old', 'passwords', 'rollback_newuser')
        # sanity: the write really changed the export
        RESULTS['cmp_new_vs_newafter'] = compare_trees(os.path.join(SCRATCH, 'new'), os.path.join(SCRATCH, 'new_after'), html_logout_normalize=True)
        print('  (new vs new_after must differ: changed files = %d)' % len(RESULTS['cmp_new_vs_newafter']['different']))
    finally:
        with open(os.path.join(SCRATCH, 'results.json'), 'w') as f:
            json.dump(RESULTS, f, indent=1, default=str)
        if not keep:
            try:
                mysql('DROP DATABASE IF EXISTS %s' % DB)
                print('[cleanup] dropped database', DB)
            except SystemExit as e:
                print(e)
            if os.path.isdir(OLD_CODE):
                subprocess.run(['git', 'worktree', 'remove', '--force', OLD_CODE], cwd=REPO)
                subprocess.run(['git', 'worktree', 'prune'], cwd=REPO)
                print('[cleanup] removed worktree')


if __name__ == '__main__':
    main()
