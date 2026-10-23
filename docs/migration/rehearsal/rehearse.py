#!/usr/bin/env python3
"""
MySQL migration rehearsal driver (Django 3.2 -> 5.2 upgrade).  Run end to end with any python3:

    python3 docs/migration/rehearsal/rehearse.py [--keep] [--allow docs/fixes/expected-diffs.json]

What it does (details and last results: REPORT.md in this directory):
  1. creates database `cordetfw_rehearsal` on the disposable MySQL (docker container
     cordetfw-mysql-test, 127.0.0.1:33306, root/rootpw-test) and imports $REHEARSAL_DUMP (default tryout/mysql_init/cordetfw.sql)
  2. OLD stack (git worktree of baseline commit cd87ccb + .venv-baseline): migrate, populate data,
     fingerprint, snapshot (exports + HTML)
  3. NEW stack (this working tree + .venv): migrate, fingerprint, snapshot, session/password/admin checks
  4. rollback: OLD stack against the migrated database, snapshot + checks, then data written by the NEW
     stack read back by the OLD stack
  5. drops the database and removes the worktree (unless --keep)

--allow <json>: allowlist of expected OLD-vs-NEW HTML differences (docs/fixes/expected-diffs.json). Every HTML page
is classified identical / differs only by allowed ids / UNEXPLAINED; the exit status is non-zero if any page is
UNEXPLAINED (or any export, or any rollback comparison, differs). Exports are always compared byte for byte.
A .sql.bz2 dump is decompressed into the scratch dir and deleted afterwards.

Never touches test_cordetfw_migration_test; does not modify production code. Needs docker, the two venvs,
and REHEARSAL_SCRATCH (default: the session scratch dir below) for scratch output.
Helper: worker.py (runs inside one Django stack). Results: <scratch>/results.json, <scratch>/logs/.
"""
import bz2
import collections
import difflib
import html
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


# ---- HTML normalisers: named functions, applied to BOTH old and new HTML, each tied to an allowlist id.
# A normaliser maps a page to a canonical form; it never decides alone that a page is "fine" (equality of
# the two canonical forms does).

def norm_logout_post(t):
    """Task 3.5: logout link (GET) -> POST form."""
    return LOGOUT_RE.sub('<LOGOUT/>', t)


def norm_post_only_mutations(t):
    """Tasks 6.3/6.3b: style.css link, confirm-delete.js, delete modal, GET links vs POST forms for
    delete/remove/refresh/member add/role, removed onclick confirm, data-confirm-message."""
    t = re.sub(r'\s*<link href="/static/style\.css" rel="stylesheet">', '', t)
    t = re.sub(r'\s*<div class="modal fade" id="deleteConfirmModal".*?(?=\s*<script)', '', t, flags=re.S)
    t = re.sub(r'\s*<script src="/static/confirm-delete\.js"></script>', '', t)
    # project delete (index): old anchor <a ... href=".../del_project" ...title="T"></a>;
    # new button form="del-project-N" + hidden form with the action. Both -> <DELCTL url title/>
    forms = {}

    def hidden_form(m):
        forms[m.group(1)] = m.group(2)
        return '\n\x00\n'
    t = re.sub(r'\s*<form id="(del-project-\d+)" class="d-none" method="post"\s+action="([^"]*)"\s+'
               r'data-confirm-message="[^"]*">\s*<input type="hidden" name="csrfmiddlewaretoken" value="[^"]*">\s*</form>',
               hidden_form, t)
    t = re.sub(r'<button type="submit" form="(del-project-\d+)"\s+class="btn btn-outline-danger bi-trash-fill"\s+'
               r'title="([^"]*)">\s*</button>',
               lambda m: '<DELCTL %s %s/>' % (forms.get(m.group(1), '??' + m.group(1)), m.group(2)), t)
    t = re.sub(r'<a class="btn btn-outline-danger bi-trash-fill"\s+href="([^"]*del_project)"\s+'
               r'onclick="return confirm\(\'Are you sure you want to delete this item\?\'\);"\s+title="([^"]*)">\s*</a>',
               lambda m: '<DELCTL %s %s/>' % (m.group(1), m.group(2)), t)
    # refresh spec item (list): old link, new POST form + button
    t = re.sub(r'<a class="bi-arrow-clockwise me-1 text-decoration-none"\s+href="([^"]*)"\s+title="([^"]*)">\s*</a>',
               lambda m: '<REFRESHCTL %s %s/>' % (m.group(1), m.group(2)), t)
    t = re.sub(r'<form class="d-inline" method="post"\s+action="([^"]*)">\s*'
               r'<input type="hidden" name="csrfmiddlewaretoken" value="[^"]*">\s*'
               r'<button type="submit" class="btn btn-link bi-arrow-clockwise me-1 text-decoration-none p-0 align-baseline"\s+'
               r'title="([^"]*)">\s*</button>\s*</form>',
               lambda m: '<REFRESHCTL %s %s/>' % (m.group(1), m.group(2)), t)
    # removed onclick confirm on the delete link of NEW items (the link itself stays a GET confirmation page)
    t = re.sub(r'(href="[^"]*/del_spec_item[^"]*")\s+(?:onclick="return confirm\(\'Are you sure you want to delete this item\?\'\);"\s+)?(?=title=)',
               r'\1 ', t)
    # edit_project: delete user / delete ValSet controls (old GET links, new POST forms with confirm message)
    t = re.sub(r'<form[^>]*action="[^"]*"[^>]*data-confirm-message=.*?</form>', '<DELCTL2/>', t, flags=re.S)
    t = re.sub(r'<a [^>]*href="[^"]*(?:del_user_id=|del_val_set_id=)[^"]*"[^>]*>\s*</a>', '<DELCTL2/>', t, flags=re.S)
    t = re.sub(r'\s*data-confirm-message="[^"]*"', '', t)

    # edit_project: add-member menu items (old GET link, new POST form) and role controls
    def member_old(m):
        return '<MEMBERCTL %s %s %s/>' % (m.group(1), m.group(2), m.group(3).strip())
    t = re.sub(r'<a class="dropdown-item"\s+href="[^"]*\?user_id=(\d+)&amp;role=(\w+)">\s*(.*?)</a>', member_old, t, flags=re.S)
    t = re.sub(r'<a class="dropdown-item"\s+href="[^"]*\?user_id=(\d+)&role=(\w+)">\s*(.*?)</a>', member_old, t, flags=re.S)

    def member_new(m):
        f = m.group(0)
        uid = re.search(r'name="user_id" value="(\d+)"', f).group(1)
        role = re.search(r'name="role" value="(\w+)"', f).group(1)
        if 'csrfmiddlewaretoken' not in f or 'method="post"' not in f:
            return f
        name = re.search(r'<button[^>]*>(.*?)</button>', f, re.S).group(1).strip()
        return '<MEMBERCTL %s %s %s/>' % (uid, role, name)
    t = re.sub(r'<form method="post" action="[^"]*edit_project">(?:(?!</form>).)*name="user_id".*?</form>', member_new, t, flags=re.S)
    t = re.sub(r'<li>\s+<MEMBERCTL', '<li><MEMBERCTL', t)
    t = re.sub(r'(<MEMBERCTL [^>]*/>)\s+</li>', r'\1</li>', t)
    return _fold_whitespace_near_controls(t)


def _fold_whitespace_near_controls(t):
    """The old and new templates differ in the template-tag lines around the converted controls, which leaves
    blank lines and indentation differences. Lines holding a converted-control marker are stripped, and
    whitespace-only lines are dropped, except inside <textarea>/<pre> where whitespace is content."""
    parts = re.split(r'(<(?:textarea|pre)\b.*?</(?:textarea|pre)>)', t, flags=re.S | re.I)
    out = []
    for k, part in enumerate(parts):
        if k % 2:
            out.append(part)
            continue
        lines = []
        for l in part.split('\n'):
            if '\x00' in l or re.search(r'<(?:DELCTL2?|REFRESHCTL|MEMBERCTL)[ /]', l):
                l = l.replace('\x00', '').strip()
                if not l:
                    continue
            elif not l.strip():
                continue
            lines.append(l)
        out.append('\n'.join(lines))
    return ''.join(out)


def norm_link_suggest_js(t):
    """Tasks 6.6b/6.6d: backslash, CR, LF, U+2028/9 escaped in the link_suggest `linkElements` JS literals.
    Only inside `var linkElements = [ ... ];`; decodes those escapes (single pass, left to right)."""
    def block(m):
        body = re.sub(r'\\(\\|r|n|u2028|u2029)',
                      lambda x: {'\\': '\\', 'r': '\r', 'n': '\n', 'u2028': ' ', 'u2029': ' '}[x.group(1)],
                      m.group(2))
        return m.group(1) + body + m.group(3)
    return re.sub(r'(var linkElements = \[)(.*?)(\n\];)', block, t, flags=re.S)


ENTITY_RE = re.compile(r'&(?:amp|lt|gt|quot|#x27);')
ENTITY_RAW = {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#x27;': "'"}


def escape_stored_text_hunks(old, new):
    """Task 6.6: stored text is now escaped (&amp; &lt; &gt; &quot; &#x27;) where it used to be output raw.
    A line hunk of old-vs-new (after all other normalisers) counts as escape-only iff html.unescape of both
    sides is identical AND the new side contains an entity whose raw character the old side contained.
    Returns (ok, stats). Nothing else is explained by this function: a hunk that does not satisfy this makes
    the page UNEXPLAINED."""
    a, b = old.split('\n'), new.split('\n')
    stats = collections.Counter()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        A, B = '\n'.join(a[i1:i2]), '\n'.join(b[j1:j2])
        ents = {e for e in ENTITY_RE.findall(B) if ENTITY_RAW[e] in A}
        if not ents or html.unescape(A) != html.unescape(B):
            return False, stats
        stats['hunks'] += 1
        stats['lines'] += j2 - j1
        for e in ents:
            stats['has ' + e] += 1
    return True, stats


# id -> function. A normaliser listed in the allowlist must exist here; "hunk" kinds compare, not map.
NORMALISERS = {'logout-post': norm_logout_post, 'post-only-mutations': norm_post_only_mutations,
               'link-suggest-js': norm_link_suggest_js}
HUNK_NORMALISERS = {'escape-stored-text': escape_stored_text_hunks}
NORMALISER_FUNCS = {'norm_logout_post': 'logout-post', 'norm_post_only_mutations': 'post-only-mutations',
                    'norm_link_suggest_js': 'link-suggest-js', 'escape_stored_text_hunks': 'escape-stored-text'}


def load_allowlist(path):
    """Returns the ordered list of allowed ids. Exports can never be allowlisted."""
    if not path:
        return ['logout-post']
    with open(path) as f:
        entries = json.load(f)
    ids = []
    for e in entries:
        if e.get('applies_to') != 'html':
            raise SystemExit('allowlist entry %r: only applies_to "html" is supported (exports must be byte-identical)' % e.get('id'))
        if NORMALISER_FUNCS.get(e.get('normaliser')) != e['id']:
            raise SystemExit('allowlist entry %r: unknown normaliser %r' % (e['id'], e.get('normaliser')))
        ids.append(e['id'])
    return ids


def classify_html(ta, tb, allowed):
    """-> ('identical' | 'allowed' | 'unexplained', [ids], stats, diff-or-None)"""
    if ta == tb:
        return 'identical', [], {}, None
    used = []
    na, nb = ta, tb
    for i in ('logout-post', 'post-only-mutations', 'link-suggest-js'):
        if i not in allowed:
            continue
        xa, xb = NORMALISERS[i](na), NORMALISERS[i](nb)
        if (xa, xb) != (na, nb):
            used.append(i)
        na, nb = xa, xb
    stats = {}
    if na != nb and 'escape-stored-text' in allowed:
        ok, st = escape_stored_text_hunks(na, nb)
        if ok:
            used.append('escape-stored-text')
            stats = dict(st)
            na = nb
    if na == nb:
        return 'allowed', used, stats, None
    diff = ''.join(list(difflib.unified_diff(na.splitlines(1), nb.splitlines(1), 'old', 'new', n=1))[:80])
    return 'unexplained', used, stats, diff


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


def compare_trees(a, b, allowed=(), skip=('_raw.zip',)):
    """Non-HTML files (exports, headers, ZIP members) must be byte-identical. HTML files are classified with
    the allowed ids (none -> byte-identical required)."""
    fa, fb = tree(a), tree(b)
    res = {'only_a': sorted(set(fa) - set(fb)), 'only_b': sorted(set(fb) - set(fa)), 'identical': 0,
           'different': [], 'logout_only': [], 'skipped_zip_raw': 0,
           'html_identical': 0, 'html_allowed': 0, 'html_unexplained': 0, 'allowed_by_id': {}, 'allowed_combos': {},
           'escape_stats': {}, 'exports_identical': 0, 'exports_different': 0}
    allowed = list(allowed)
    esc = collections.Counter()
    esc_pages = 0
    for rel in sorted(set(fa) & set(fb)):
        if rel.endswith(skip):
            res['skipped_zip_raw'] += 1
            continue
        da, db = read(fa[rel]), read(fb[rel])
        is_html = rel.endswith('.html')
        if not is_html:
            if da == db:
                res['identical'] += 1
                res['exports_identical'] += 1
            else:
                res['exports_different'] += 1
                res['different'].append({'file': rel, 'diff': ''.join(list(difflib.unified_diff(
                    da.decode('utf-8', 'replace').splitlines(1), db.decode('utf-8', 'replace').splitlines(1), 'a', 'b', n=1))[:40])})
            continue
        kind, ids, stats, diff = classify_html(da.decode(), db.decode(), allowed)
        if kind == 'identical':
            res['identical'] += 1
            res['html_identical'] += 1
        elif kind == 'allowed':
            res['html_allowed'] += 1
            for i in ids:
                res['allowed_by_id'][i] = res['allowed_by_id'].get(i, 0) + 1
            combo = '+'.join(ids)
            res['allowed_combos'][combo] = res['allowed_combos'].get(combo, 0) + 1
            if ids == ['logout-post']:
                res['logout_only'].append(rel)
            if 'escape-stored-text' in ids:
                esc_pages += 1
                esc.update(stats)
        else:
            res['html_unexplained'] += 1
            res['different'].append({'file': rel, 'diff': diff, 'ids_applied': ids})
    res['escape_stats'] = dict(esc, pages=esc_pages)
    return res


def snapshot_summary(name, snap, reference=None):
    """Print what a snapshot covered; with a reference, require the same set of failing requests
    (pre-existing crashes on real data are allowed, but must not appear or disappear)."""
    print('  %s: zip=%d csv=%d html=%d errors=%d' % (name, snap['zip'], snap['csv'], snap['html'], len(snap['errors'])))
    if reference is not None and sorted(snap['errors']) != sorted(reference['errors']):
        added = sorted(set(snap['errors']) - set(reference['errors']))
        gone = sorted(set(reference['errors']) - set(snap['errors']))
        RESULTS.setdefault('error_set_mismatch', {})[name] = {'added': added, 'gone': gone}
        raise SystemExit('%s: failing requests differ from the reference (added %d, gone %d)' % (name, len(added), len(gone)))


def summarize_tree(name, r):
    print('  %s: identical=%d (exports %d, html %d) html_allowed=%d html_unexplained=%d exports_different=%d only_a=%d only_b=%d' % (
        name, r['identical'], r['exports_identical'], r['html_identical'], r['html_allowed'], r['html_unexplained'],
        r['exports_different'], len(r['only_a']), len(r['only_b'])))
    if r['allowed_by_id']:
        print('    allowed by id: %s' % json.dumps(r['allowed_by_id'], sort_keys=True))
        print('    allowed combos: %s' % json.dumps(r['allowed_combos'], sort_keys=True))
        if r['escape_stats']:
            print('    escape-stored-text: %s' % json.dumps(r['escape_stats'], sort_keys=True))


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
    allow_path = sys.argv[sys.argv.index('--allow') + 1] if '--allow' in sys.argv else None
    allowed = load_allowlist(allow_path)
    print('[allow] %s' % (allowed,))
    RESULTS['allowed_ids'] = allowed
    decompressed = None
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
        if dump.endswith('.bz2'):
            decompressed = os.path.join(SCRATCH, 'dump_decompressed.sql')
            with bz2.open(dump, 'rb') as src, open(decompressed, 'wb') as dst:
                shutil.copyfileobj(src, dst)
            dump = decompressed
        with open(dump, 'rb') as f:
            subprocess.run(['docker', 'exec', '-i', CONTAINER, 'mysql', '-uroot', '-p' + ROOT_PW, DB], stdin=f,
                           check=True, capture_output=True)
        print('[db] imported dump (%s)' % ('bz2, decompressed' if decompressed else 'plain'))

        # ---- Step 1/2: OLD stack
        manage('old', 'showmigrations_2022_schema', 'showmigrations')
        manage('old', 'migrate', 'migrate', '--noinput')
        manage('old', 'showmigrations_after_migrate', 'showmigrations')
        RESULTS['old_populate'] = worker('old', 'populate')
        RESULTS['old_admin'] = worker('old', 'admin_check')
        worker('old', 'fingerprint', os.path.join(SCRATCH, 'fp_old.json'))
        RESULTS['old_snapshot'] = worker('old', 'snapshot', os.path.join(SCRATCH, 'old'))
        snapshot_summary('old snapshot', RESULTS['old_snapshot'])

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
        snapshot_summary('new snapshot', RESULTS['new_snapshot'], RESULTS['old_snapshot'])
        RESULTS['cmp_old_new'] = compare_trees(os.path.join(SCRATCH, 'old'), os.path.join(SCRATCH, 'new'), allowed=allowed)
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
        snapshot_summary('rollback snapshot', RESULTS['rb_snapshot'], RESULTS['old_snapshot'])
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
        RESULTS['cmp_new_vs_newafter'] = compare_trees(os.path.join(SCRATCH, 'new'), os.path.join(SCRATCH, 'new_after'), allowed=allowed)
        print('  (new vs new_after must differ: changed files = %d)' % len(RESULTS['cmp_new_vs_newafter']['different']))
    finally:
        if decompressed and os.path.exists(decompressed):
            os.remove(decompressed)
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
    return verdict()


def verdict():
    """Non-zero if anything is unexplained or differs where it must not."""
    bad = []
    on = RESULTS.get('cmp_old_new')
    if not on:
        return 1
    if on['html_unexplained']:
        bad.append('%d UNEXPLAINED html page(s) old vs new (diffs: results.json)' % on['html_unexplained'])
    if on['exports_different']:
        bad.append('%d export file(s) differ old vs new' % on['exports_different'])
    if on['only_a'] or on['only_b']:
        bad.append('file sets differ old vs new')
    for k in ('cmp_old_rollback', 'cmp_newafter_rollbackafter'):
        r = RESULTS.get(k)
        if r is None or r['different'] or r['only_a'] or r['only_b']:
            bad.append(k + ' not identical')
    print('VERDICT: ' + ('FAIL: ' + '; '.join(bad) if bad else 'PASS (every html difference explained, exports byte-identical)'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
