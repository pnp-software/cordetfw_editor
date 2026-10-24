"""
Import compatibility corpus (Task 7.0).

Every input under tests/golden/compat/inputs/ (and the export goldens under tests/golden/export/,
referenced from the manifest in tests/golden/compat/make_inputs.py) is imported with the CURRENT
importers into a fresh test DB; a deterministic fingerprint of the editor tables (plus the outcome:
exception / messages) is compared with tests/golden/compat/expected/<name>.json.

Purpose: prove that exports of the current release keep importing, and show exactly which DB
fields a fix of the importers changes.  A difference fails unless docs/fixes/expected-diffs.json
has an entry whose "compat" object lists it (see load_compat_allowlist).  Fixes promote the
changed expected/<name>.json one file at a time (UPDATE_GOLDEN=1 for that input, reviewed).

Fingerprint normalisation (only what the importer itself sets to "now"):
  * auto_now fields (Project/Application.updated_at, ValSet/ProjectUser.updated_at) and the
    SpecItem.updated_at / created_at written with datetime.now() by import_spec_items are replaced
    by "<now>" when within one hour of the test run; any other value is kept verbatim (so a fix that
    starts preserving the exported timestamp shows up as a diff of that field).
  * auto-increment ids are replaced by "#<rank>" (position when ordered by id) in the table's own
    "id" column and in every foreign key; user FKs become the username. Internal references
    "#iref:<id>" inside text fields become "#iref:<rank of the SpecItem>" (or "#iref:<missing>"),
    because auto-increment ids differ between SQLite and MySQL runs.
Known-issue inputs (import-project-*) are recorded as they behave today, including exceptions and
partial DB state; they are marked "# KNOWN-ISSUE: <id>" next to KNOWN_ISSUE_INPUTS below.
"""

import csv
import importlib.util
import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models as dj_models

from editor.models import Project
from tests.factories import make_user
from tests.golden import GOLDEN_DIR

pytestmark = pytest.mark.django_db

COMPAT_DIR = GOLDEN_DIR / 'compat'
INPUTS_DIR = COMPAT_DIR / 'inputs'
EXPECTED_DIR = COMPAT_DIR / 'expected'
ALLOWLIST = Path(__file__).resolve().parent.parent / 'docs' / 'fixes' / 'expected-diffs.json'

_spec = importlib.util.spec_from_file_location('compat_make_inputs', COMPAT_DIR / 'make_inputs.py')
make_inputs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_inputs)
MANIFEST = make_inputs.MANIFEST
NAMES = [m['name'] for m in MANIFEST]

# KNOWN-ISSUE markers (checked by scripts/known_issue_check.py): the recorded outcome of these inputs
# is the CURRENT buggy behaviour; the fix commit flips the expected file and lists the changed fields.
# KNOWN-ISSUE: import-project-empty-app-cats  (zip_app_empty_cats: rejected, nothing imported)
# KNOWN-ISSUE: import-project-owner-not-member  (zip_owner_not_member: orphan item dropped, message)
# KNOWN-ISSUE: import-project-dangling-link-crash  (zip_owner_not_member_linked: KeyError, partial project)
# KNOWN-ISSUE: import-project-role-lost  (zip_roles_valsets_releases: every member imported as role RO)
# KNOWN-ISSUE: import-project-application-version-lost  (zip_apps_versions: application_version not imported)


# ---------------------------------------------------------------------------
# allowlist
# ---------------------------------------------------------------------------

def load_compat_allowlist(path=ALLOWLIST):
    """Return {input name: set of allowed '<table>.<field>' patterns} merged over all entries.

    Format: any entry of docs/fixes/expected-diffs.json may carry an optional key
        "compat": {"<input name>": ["<table>.<field>", ...], ...}
    '<input name>' is a manifest name or '*'; '<table>.<field>' is e.g. 'editor_projectuser.role',
    (a bare '*' pattern is rejected: a fix must name the tables it changes),
    'editor_specitem.*', '_outcome.messages', '_outcome.exception', or 'editor_specitem.#rows' (row
    count differs).  Entries used only for compat have "applies_to": "compat" (ignored by
    docs/migration/rehearsal/rehearse.py).
    """
    allowed = {}
    for entry in json.loads(Path(path).read_text()):
        for name, fields in (entry.get('compat') or {}).items():
            assert '*' not in fields, 'compat allowlist: bare "*" pattern in %s' % entry.get('id')
            allowed.setdefault(name, set()).update(fields)
    return allowed


def is_allowed(path, patterns):
    table = path.split('.', 1)[0]
    return any(p in (path, table + '.*') for p in patterns)


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------

def _models():
    return sorted(apps.get_app_config('editor').get_models(), key=lambda m: m._meta.db_table)


def _norm_value(value, now):
    if isinstance(value, datetime):
        if abs(value - now) < timedelta(hours=1):
            return '<now>'
        return value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value, date):
        if abs(value - now.date()) <= timedelta(days=1):
            return '<now>'
        return value.isoformat()
    return value


IREF_RE = re.compile(r'#iref:(\d+)')


def fingerprint():
    """{table: [row dict, ...]} for all editor tables, ordered by id, ids replaced by ranks."""
    now = datetime.now(timezone.utc)
    ranks = {}
    for model in _models():
        ranks[model] = {pk: '#%d' % i for i, pk in
                        enumerate(model.objects.order_by('id').values_list('id', flat=True))}
    item_ranks = ranks[apps.get_model('editor', 'SpecItem')]
    result = {}
    for model in _models():
        rows = []
        for obj in model.objects.order_by('id'):
            row = {}
            for field in model._meta.concrete_fields:
                if field.name == 'id':
                    row['id'] = ranks[model][obj.pk]
                elif isinstance(field, dj_models.ForeignKey):
                    raw = getattr(obj, field.attname)
                    rel = field.related_model
                    if raw is None:
                        row[field.name] = None
                    elif rel is User:
                        row[field.name] = User.objects.get(pk=raw).username
                    else:
                        row[field.name] = ranks[rel][raw]
                else:
                    value = _norm_value(getattr(obj, field.name), now)
                    if isinstance(value, str):
                        value = IREF_RE.sub(lambda m: '#iref:<%s>' % item_ranks.get(int(m.group(1)), 'missing'),
                                            value)
                    row[field.name] = value
            rows.append(row)
        result[model._meta.db_table] = rows
    return result


def diff_paths(expected, actual):
    """Set of '<table>.<field>' (or '<table>.#rows') paths in which the two fingerprints differ."""
    paths = set()
    for table in sorted(set(expected) | set(actual)):
        e, a = expected.get(table), actual.get(table)
        if table == '_outcome':
            for key in sorted(set(e or {}) | set(a or {})):
                if (e or {}).get(key) != (a or {}).get(key):
                    paths.add('_outcome.' + key)
            continue
        if e is None or a is None or len(e) != len(a):
            paths.add(table + '.#rows')
        for re_, ra in zip(e or [], a or []):
            for col in sorted(set(re_) | set(ra)):
                if re_.get(col) != ra.get(col):
                    paths.add('%s.%s' % (table, col))
    return paths


# ---------------------------------------------------------------------------
# running an input
# ---------------------------------------------------------------------------

def _messages(response):
    out = []
    for m in get_messages(response.wsgi_request):
        # import_spec_items appends a traceback (with file paths) after this marker
        out.append([m.level_tag, m.message.split('; traceback:')[0]])
    return out


def _input_bytes(entry):
    if 'members_dir' in entry:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            for member in sorted((GOLDEN_DIR / entry['members_dir']).glob('*.csv')):
                zf.writestr(member.name, member.read_bytes())
        return buf.getvalue()
    if 'golden' in entry:
        return (GOLDEN_DIR / entry['golden']).read_bytes()
    return (INPUTS_DIR / entry['file']).read_bytes()


def run_input(client, entry):
    """Import the input with the current code; return {table: rows..., '_outcome': {...}}."""
    outcome = {'exception': None, 'status': None, 'messages': []}
    data = _input_bytes(entry)
    if entry['kind'] == 'project_zip':
        for username in entry['users']:
            make_user(username)
        importer = make_user('importer', is_staff=True)
        client.force_login(importer)
        url = '/editor/import_project'
        upload = SimpleUploadedFile('project.zip', data)
    else:
        from tests.test_import_export import build_world
        world = build_world()
        client.force_login(world.rw)
        url = '/editor/%s/1/%d/%d/Sel_All/import_spec_items' % (entry['cat'], entry['application'], entry['val_set'])
        upload = SimpleUploadedFile('items.csv', data)
    try:
        response = client.post(url, {'upload_file': upload})
        outcome['status'] = response.status_code
        outcome['messages'] = _messages(response)
    except Exception as e:  # recorded as expected outcome of known-issue inputs
        outcome['exception'] = type(e).__name__
        outcome['message'] = str(e)
    fp = fingerprint()
    fp['_outcome'] = outcome
    return fp


def _dump(fp):
    return (json.dumps(fp, indent=1, sort_keys=True, ensure_ascii=False, default=str) + '\n').encode('utf-8')


@pytest.mark.parametrize('name', NAMES)
def test_compat_import_fingerprint(client, name):
    entry = next(m for m in MANIFEST if m['name'] == name)
    actual = run_input(client, entry)
    path = EXPECTED_DIR / (name + '.json')
    if os.environ.get('UPDATE_GOLDEN') == '1':
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_dump(actual))
        return
    assert path.exists(), 'Missing %s (record with UPDATE_GOLDEN=1 on the baseline)' % path
    expected = json.loads(path.read_text(encoding='utf-8'))
    actual_norm = json.loads(_dump(actual).decode('utf-8'))    # same JSON round trip as the file
    if actual_norm == expected:
        return
    diffs = diff_paths(expected, actual_norm)
    patterns = load_compat_allowlist().get(name, set()) | load_compat_allowlist().get('*', set())
    unexplained = sorted(p for p in diffs if not is_allowed(p, patterns))
    # Always leave the .actual file: the gate's "no golden diffs" step then fails until the reviewed
    # file is promoted, so an allowlisted field is never left unchecked for later changes.
    actual_path = path.with_name(path.name + '.actual')
    actual_path.write_bytes(_dump(actual))
    if not unexplained:
        return      # every differing field is declared by a fix in docs/fixes/expected-diffs.json
    raise AssertionError('Import fingerprint of %s differs from %s in undeclared fields %s; actual written to %s'
                         % (name, path, unexplained, actual_path))


# ---------------------------------------------------------------------------
# corpus self-checks and deliberate regeneration
# ---------------------------------------------------------------------------

def test_compat_manifest_and_inputs_consistent():
    on_disk = json.loads((INPUTS_DIR / 'manifest.json').read_text())
    assert on_disk == json.loads(json.dumps(MANIFEST)), 'inputs/manifest.json is stale (COMPAT_REGEN=1)'
    for m in MANIFEST:
        assert len(set(NAMES)) == len(NAMES)
        assert 'file' in m or 'golden' in m or 'members_dir' in m
        if 'file' in m:
            assert (INPUTS_DIR / m['file']).is_file(), m['file']
        if m['kind'] == 'project_zip':
            data = _input_bytes(m)
            assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == sorted(
                ['project.csv', 'applications.csv', 'val_sets.csv', 'project_users.csv', 'releases.csv',
                 'spec_items.csv'])


def test_compat_allowlist_is_valid_and_empty_of_stale_names():
    allowed = load_compat_allowlist()
    for name in allowed:
        assert name == '*' or name in NAMES, 'expected-diffs.json compat: unknown input %r' % name


def test_compat_diff_machinery():
    e = {'t': [{'id': '#0', 'a': 1, 'b': 2}], '_outcome': {'exception': None}}
    a = {'t': [{'id': '#0', 'a': 1, 'b': 3}, {'id': '#1', 'a': 1, 'b': 2}], '_outcome': {'exception': 'KeyError'}}
    assert diff_paths(e, a) == {'t.#rows', 't.b', '_outcome.exception'}
    assert is_allowed('t.b', {'t.*'}) and not is_allowed('t.b', {'*'}) and not is_allowed('t.b', {'t.a'})


def _zip_fixed(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 15, 10, 30, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, members[name])
    return buf.getvalue()


@pytest.mark.parametrize('name', sorted(list(make_inputs.ZIP_WORLDS) + list(make_inputs.CSV_EXPORTS)))
def test_compat_regenerate_inputs(client, name):
    """No-op unless COMPAT_REGEN=1: re-export the synthetic worlds with the CURRENT code and rewrite
    inputs/ (and manifest.json).  Run deliberately, on the baseline code only."""
    if os.environ.get('COMPAT_REGEN') != '1':
        assert (INPUTS_DIR / 'manifest.json').is_file()
        return
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (INPUTS_DIR / 'manifest.json').write_text(json.dumps(MANIFEST, indent=1, ensure_ascii=False) + '\n')
    if name in make_inputs.ZIP_WORLDS:
        build, project_name = make_inputs.ZIP_WORLDS[name]
        build()
        project = Project.objects.get(name=project_name)
        client.force_login(project.owner)
        response = client.get('/editor/%d/export_project' % project.id)
        assert response.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
        (INPUTS_DIR / (name + '.zip')).write_bytes(_zip_fixed({n: zf.read(n) for n in zf.namelist()}))
    else:
        world = make_inputs.build_csv_extended()
        client.force_login(world.owner)
        response = client.get(make_inputs.CSV_EXPORTS[name])
        assert response.status_code == 200
        (INPUTS_DIR / (name + '.csv')).write_bytes(response.content)
