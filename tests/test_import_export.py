"""
Characterization tests for CSV/ZIP import and export (export_project, import_project,
export_spec_items, import_spec_items) and for the django-import-export Resources.

This is the compatibility surface for the django-import-export 3.x -> 4.x upgrade.
The byte-level goldens under tests/golden/export/ are the contract.
"""

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
from unittest import mock
from django.contrib.auth.models import User
from django.contrib.messages import get_messages

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from tests.factories import FIXED_TIME, PASSWORD, make_user
from tests.golden import assert_golden

pytestmark = pytest.mark.django_db

T0 = datetime(2023, 12, 1, 8, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2024, 2, 20, 16, 45, 30, tzinfo=timezone.utc)
T2 = datetime(2024, 3, 3, 3, 3, 3, tzinfo=timezone.utc)
D_FIXED = datetime(2024, 1, 15).date()

PROJECT_MEMBERS = ['project.csv', 'applications.csv', 'val_sets.csv',
                   'project_users.csv', 'releases.csv', 'spec_items.csv']


# ---------------------------------------------------------------------------
# Deterministic synthetic project
# ---------------------------------------------------------------------------

class World:
    """Handles on the objects of the synthetic project."""


def build_world(name='Demo Proj'):
    w = World()
    w.owner = make_user('owner')
    w.ro = make_user('reader')
    w.rw = make_user('writer')

    # Project release chain: 0.0 <- 1.0
    r0 = Release.objects.create(id=1, release_author=w.owner, desc='Initial release for project',
                                updated_at=T0, project_version=0, application_version=0)
    r1 = Release.objects.create(id=2, release_author=w.rw, desc='First "release" | with pipe\nand newline',
                                updated_at=T1, project_version=1, application_version=0, previous=r0)
    # Application release chain: 0.0 <- 1.1
    a0 = Release.objects.create(id=3, release_author=w.owner, desc='Initial release for application',
                                updated_at=T0, project_version=0, application_version=0)
    a1 = Release.objects.create(id=4, release_author=w.owner, desc='Application release äµ',
                                updated_at=T1, project_version=1, application_version=1, previous=a0)
    w.releases = [r0, r1, a0, a1]

    w.project = Project.objects.create(
        id=1, name=name, desc='Demo project with unicode ä µ \u263A\nsecond line',
        cats='DataItem,EnumType,EnumValue,DataItemType', owner=w.owner, release=r1)
    w.default = ValSet.objects.create(id=1, project=w.project, name='Default', desc='Default ValSet')
    w.vs1 = ValSet.objects.create(id=2, project=w.project, name='VS1', desc='Alternative "values"')
    w.pu_ro = ProjectUser.objects.create(id=1, project=w.project, user=w.ro, role='RO')
    w.pu_rw = ProjectUser.objects.create(id=2, project=w.project, user=w.rw, role='RW')
    w.app = Application.objects.create(id=1, name='App One', desc='Application | desc',
                                       cats='Requirement', project=w.project, release=a1)

    def item(pk, cat, domain, name, **kw):
        kw.setdefault('title', 'Title of ' + name)
        kw.setdefault('updated_at', T1)
        kw.setdefault('created_at', T0)
        kw.setdefault('owner', w.owner)
        kw.setdefault('val_set', w.default)
        kw.setdefault('status', 'CNF')
        return SpecItem.objects.create(id=pk, project=w.project, cat=cat, domain=domain, name=name, **kw)

    w.uint8 = item(101, 'DataItemType', 'Types', 'uint8', title='Unsigned 8', n1=1,
                   implementation='unsigned char',
                   desc='Plain with | pipe and "quotes" and \'single\'')
    w.color_old = item(103, 'EnumType', 'Types', 'Color', status='OBS', updated_at=T0, n1=4,
                       desc='old description', title='Colour (old)')
    w.color = item(102, 'EnumType', 'Types', 'Color', n1=4, previous=w.color_old, title='Colour',
                   desc='Colors ä µ \u263A and **markdown**\n\n- bullet one\n- bullet two',
                   change_log='changed\r\nwith CRLF')
    w.red = item(104, 'EnumValue', 'Types', 'Red', s_link=w.color, value='0', status='NEW',
                 updated_at=T2, title='Red')
    w.green = item(105, 'EnumValue', 'Types', 'Green', s_link=w.color, value='1', title='Green')
    w.count = item(107, 'DataItem', 'Dom', 'Count', p_link=w.uint8, value='42', desc='', n1=0,
                   p_kind='CNS', s_kind='')
    w.colorvar = item(106, 'DataItem', 'Dom', 'ColorVar', p_link=w.color, value='#iref:104',
                      desc='See #iref:104 and #iref:101 and **bold**\nnewline "q" | pipe; dangling #iref:9999',
                      rationale='x | y', remarks='  padded  ', t1='1', t2='µm', p_kind='VAR',
                      status='MOD', updated_at=T2, n3=7, s_data={'a': 1, 'k': [1, 2], 'u': 'ä'})
    w.calc = item(108, 'DataItem', 'Dom', 'Calc', p_link=w.uint8, value='#iref:107 * 2', p_kind='CNS')
    w.count_vs1 = item(109, 'DataItem', 'Dom', 'Count', p_link=w.uint8, value='43', val_set=w.vs1,
                       status='NEW', p_kind='CNS')
    w.req = item(110, 'Requirement', 'AppDom', 'R1', application=w.app, owner=w.rw, status='NEW',
                 value='The app shall use #iref:107 and ä', p_kind='STD', s_kind='TST',
                 t1='close', t2='valid', title='Req 1')

    # Fixed values for the auto_now fields
    Project.objects.update(updated_at=T1)
    Application.objects.update(updated_at=T1)
    ValSet.objects.update(updated_at=D_FIXED)
    ProjectUser.objects.update(updated_at=D_FIXED)
    return w


@pytest.fixture
def world():
    return build_world()


@pytest.fixture
def fresh_temp(monkeypatch, tmp_path):
    """Return a function giving every call a new, empty temp_dir (make_temp_dir names
    directories by the second, so two calls within a second would otherwise collide)."""
    from editor.configs import configs
    counter = [0]

    def next_dir():
        counter[0] += 1
        d = tmp_path / ('t%d' % counter[0])
        d.mkdir()
        monkeypatch.setitem(configs['general'], 'temp_dir', str(d))
        return d
    return next_dir


def export_zip(client, project_id, fresh_temp):
    fresh_temp()
    response = client.get('/editor/%d/export_project' % project_id)
    assert response.status_code == 200
    data = b''.join(response.streaming_content)
    return response, data, zipfile.ZipFile(io.BytesIO(data))


# ---------------------------------------------------------------------------
# CSV helpers for id-insensitive comparison
# ---------------------------------------------------------------------------

def read_csv_member(zf, member):
    text = zf.read(member).decode('utf-8')
    return list(csv.DictReader(io.StringIO(text, newline='')))


# Which table's id space does each foreign-key-like column refer to?
ID_COLUMNS = {
    'project.csv': {'id': 'project', 'release': 'release'},
    'applications.csv': {'id': 'application', 'project': 'project', 'release': 'release'},
    'val_sets.csv': {'id': 'val_set', 'project': 'project'},
    'project_users.csv': {'id': 'project_user', 'project': 'project'},
    'releases.csv': {'id': 'release', 'previous': 'release'},
    'spec_items.csv': {'id': 'spec_item', 'project': 'project', 'application': 'application',
                       'previous': 'spec_item', 'val_set': 'val_set', 'p_link': 'spec_item',
                       's_link': 'spec_item'},
}


def canonical_tables(zf):
    """Return {member: [row dicts]} with every id replaced by '<space>#<rank>' where rank is
    the position of that id in the table defining the id space."""
    tables = {m: read_csv_member(zf, m) for m in PROJECT_MEMBERS}
    ranks = {}
    for member, cols in ID_COLUMNS.items():
        space = cols['id']
        ranks[space] = {row['id']: '%s#%d' % (space, i) for i, row in enumerate(tables[member])}
    result = {}
    for member, cols in ID_COLUMNS.items():
        rows = []
        for row in tables[member]:
            row = dict(row)
            for col, space in cols.items():
                if row[col] != '':
                    row[col] = ranks[space][row[col]]
            rows.append(row)
        result[member] = rows
    return result


# ---------------------------------------------------------------------------
# export_project
# ---------------------------------------------------------------------------

def test_export_project_response_headers_and_members(client, fresh_temp, world):
    client.force_login(world.owner)
    response, data, zf = export_zip(client, world.project.id, fresh_temp)
    assert response['Content-Type'] == 'application/zip'
    assert response['Content-Disposition'] == 'inline; filename="cordetfw_editor_Demo Proj.zip"'
    assert response['Content-Length'] == str(len(data))
    assert response.streaming is True
    assert zf.namelist() == PROJECT_MEMBERS
    assert zf.testzip() is None
    assert [i.compress_type for i in zf.infolist()] == [zipfile.ZIP_STORED] * 6


@pytest.mark.parametrize('member', PROJECT_MEMBERS)
def test_export_project_member_golden(client, fresh_temp, world, member):
    client.force_login(world.owner)
    response, data, zf = export_zip(client, world.project.id, fresh_temp)
    assert_golden('export/project/' + member, zf.read(member))


def test_export_project_golden_contains_real_data(client, fresh_temp, world):
    client.force_login(world.owner)
    response, data, zf = export_zip(client, world.project.id, fresh_temp)
    spec = zf.read('spec_items.csv').decode('utf-8')
    # header names and column order
    assert spec.split('\r\n')[0] == ('id,cat,name,domain,project,application,title,desc,owner,status,'
                                     'updated_at,created_at,previous,rationale,remarks,implementation,'
                                     'val_set,p_link,s_link,p_kind,s_kind,value,s_data,t1,t2,t3,t4,t5,'
                                     'n1,n2,n3,change_log')
    assert len(read_csv_member(zf, 'spec_items.csv')) == 10
    # convert_db_to_edit applied to text fields: #iref:N -> #cat:domain:name
    assert 'See #EnumValue:Types:Red and #DataItemType:Types:uint8' in spec
    assert '#iref:' not in spec
    # a dangling reference is rendered as ERROR:<id>
    assert 'dangling ERROR:9999' in spec
    # unicode is written as UTF-8
    assert 'ä µ \u263A'.encode('utf-8') in zf.read('spec_items.csv')
    # owner / user / release author are dehydrated to the user name
    rows = read_csv_member(zf, 'spec_items.csv')
    assert {r['owner'] for r in rows} == {'owner', 'writer'}
    assert [r['user'] for r in read_csv_member(zf, 'project_users.csv')] == ['reader', 'writer']
    assert [r['release_author'] for r in read_csv_member(zf, 'releases.csv')] == \
           ['owner', 'writer', 'owner', 'owner']
    assert read_csv_member(zf, 'project.csv')[0]['owner'] == 'owner'


def test_export_project_removes_temp_dir(client, fresh_temp, world):
    # FIXED: temp-dir-not-cleaned (was: the export directory with all files stayed behind)
    client.force_login(world.owner)
    tmp = fresh_temp()
    response = client.get('/editor/%d/export_project' % world.project.id)
    data = b''.join(response.streaming_content)
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == PROJECT_MEMBERS
    assert list(tmp.iterdir()) == []


def test_export_project_requires_read_access(client, fresh_temp, world):
    stranger = make_user('stranger')
    client.force_login(stranger)
    fresh_temp()
    response = client.get('/editor/%d/export_project' % world.project.id)
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert [m.message for m in get_messages(response.wsgi_request)] == \
           ['This operation requires read access to project Demo Proj']


def test_export_project_read_only_user_can_export(client, fresh_temp, world):
    client.force_login(world.ro)
    response, data, zf = export_zip(client, world.project.id, fresh_temp)
    assert zf.namelist() == PROJECT_MEMBERS


def test_make_temp_dir_collision_within_one_second(client, monkeypatch, world, tmp_path):
    # FIXED: temp-dir-collision (was: second export within the same second -> NameError / 500)
    import editor.utilities as utilities

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2024, 1, 1, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(utilities, 'datetime', FrozenDatetime)
    client.force_login(world.owner)
    first = client.get('/editor/%d/export_project' % world.project.id)
    assert first.status_code == 200
    second = client.get('/editor/%d/export_project' % world.project.id)
    assert second.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(b''.join(second.streaming_content))).namelist() == PROJECT_MEMBERS


# ---------------------------------------------------------------------------
# export_spec_items
# ---------------------------------------------------------------------------

SPEC_EXPORTS = [
    # name, url, expected filename, golden
    ('di_project', '/editor/DataItem/1/0/1/Sel_All/0/export_spec_items', 'Demo_ProjDataItem.csv'),
    ('di_project_latex', '/editor/DataItem/1/0/1/Sel_All/0/export_spec_items?export=latex_format',
     'Demo_ProjDataItem.csv'),
    ('di_project_domain', '/editor/DataItem/1/0/1/Dom/0/export_spec_items', 'Demo_ProjDataItem.csv'),
    ('di_project_vs1', '/editor/DataItem/1/0/2/Sel_All/0/export_spec_items', 'Demo_ProjDataItem.csv'),
    ('di_project_order_by_value', '/editor/DataItem/1/0/1/Sel_All/0/export_spec_items?order_by=value',
     'Demo_ProjDataItem.csv'),
    ('di_project_release2', '/editor/DataItem/1/0/1/Sel_All/2/export_spec_items', 'Demo_ProjDataItem.csv'),
    ('enumtype_project', '/editor/EnumType/1/0/1/Sel_All/0/export_spec_items', 'Demo_ProjEnumType.csv'),
    ('enumtype_project_latex', '/editor/EnumType/1/0/1/Sel_All/0/export_spec_items?export=latex_format',
     'Demo_ProjEnumType.csv'),
    ('enumvalue_project', '/editor/EnumValue/1/0/1/Sel_All/0/export_spec_items', 'Demo_ProjEnumValue.csv'),
    ('req_application', '/editor/Requirement/1/1/1/Sel_All/0/export_spec_items', 'AppOneRequirement.csv'),
    ('req_application_latex', '/editor/Requirement/1/1/1/Sel_All/0/export_spec_items?export=latex_format',
     'AppOneRequirement.csv'),
    ('req_no_application', '/editor/Requirement/1/0/1/Sel_All/0/export_spec_items', 'DemoProjRequirement.csv'),
]


@pytest.mark.parametrize('name,url,filename', SPEC_EXPORTS, ids=[s[0] for s in SPEC_EXPORTS])
def test_export_spec_items_golden(client, world, name, url, filename):
    client.force_login(world.owner)
    response = client.get(url)
    assert response.status_code == 200
    assert response['Content-Type'] == 'text/plain'
    assert response['Content-Disposition'] == 'attachment; filename= "%s"' % filename
    assert_golden('export/spec_items/%s.csv' % name, response.content)


def test_export_spec_items_content_details(client, world):
    client.force_login(world.owner)
    text = client.get('/editor/DataItem/1/0/1/Sel_All/0/export_spec_items').content.decode('utf-8')
    lines = text.split('\r\n')
    # labels (not field names) form the header; '|' is the separator
    assert lines[0] == ('Domain|Name|Title|Description|Value|Rationale|Remarks|Implementation|Type|Kind|'
                        'Multiplicity|Unit|Owner|Change Log|ValSet')
    # ordered by domain, name; OBS/DEL excluded; other ValSet excluded
    assert [l.split('|')[1] for l in lines[1:] if l and not l.startswith(' ')][:1] == ['Calc']
    # spec_item_ref is exported as domain:name
    assert 'Types:uint8' in text and 'Types:Color' in text
    # KNOWN-ISSUE: export-eval-ref-not-converted
    # 'Value' has kind eval_ref, which spec_item_to_export treats like plain text: the internal
    # reference is exported as '#iref:N' and not as '#cat:domain:name' (unlike ref_text fields).
    assert '#iref:107 * 2' in text
    assert '#iref:104' in text
    # ref_text fields are converted (and a dangling reference becomes ERROR:N)
    assert 'See #EnumValue:Types:Red and #DataItemType:Types:uint8' in text


def test_export_spec_items_latex_content(client, world):
    client.force_login(world.owner)
    text = client.get('/editor/DataItem/1/0/1/Sel_All/0/export_spec_items?export=latex_format').content.decode()
    header = text.split('\r\n')[0].split('|')
    assert header == ['Domain', 'Name', 'Title', 'Description', 'Value', 'NVal', 'Rationale', 'Remarks',
                      'Implementation', 'Type', 'Kind', 'Multiplicity', 'Unit', 'Owner', 'ChangeLog', 'ValSet',
                      'UpdatedAt', 'CreatedAt', 'Status', 'Project', 'Application', 'VerLink']
    assert 'Dom:Count * 2|84.0' in text           # NVal is the evaluated expression
    assert '\\textbf{bold} \\newline newline' in text
    assert '|Demo Proj|None|' in text             # Application of project items is the string 'None'


def test_export_spec_items_empty_queryset_gives_empty_body(client, world):
    client.force_login(world.owner)
    response = client.get('/editor/DataItem/1/0/1/NoSuchDomain/0/export_spec_items')
    assert response.status_code == 200
    assert response.content == b''
    assert response['Content-Length'] == '0'
    assert response['Content-Disposition'] == 'attachment; filename= "Demo_ProjDataItem.csv"'
    assert response['Content-Type'] == 'text/plain'


def test_export_spec_items_requires_read_access(client, world):
    client.force_login(make_user('stranger'))
    response = client.get('/editor/DataItem/1/0/1/Sel_All/0/export_spec_items')
    assert response.status_code == 302
    assert response['Location'] == '/editor'


# ---------------------------------------------------------------------------
# Resources (django-import-export API surface)
# ---------------------------------------------------------------------------

from editor import resources as R


def cells(rows):
    """Compare Dataset cells by value as written to CSV.

    Changed in Task 3.4b (import-export 3.3.9 -> 4.4.3): 4.x renders some integer cells as
    strings ('1' instead of 1). The CSV text written to the export files is byte-identical
    (verified against the 3.3.9 output for every resource), so integers are compared by
    their text form. Any other change (None vs '', different text) still fails.
    """
    def norm(row):
        return tuple(str(v) if isinstance(v, int) and not isinstance(v, bool) else v for v in row)
    return [norm(row) for row in rows]


def test_resource_project(world):
    ds = R.ProjectResource().export(queryset=Project.objects.all())
    assert ds.headers == ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release']
    assert len(ds) == 1
    assert cells([ds[0]]) == cells([(1, 'Demo Proj', 'Demo project with unicode ä µ \u263A\nsecond line',
                     'DataItem,EnumType,EnumValue,DataItemType', '2024-02-20 16:45:30', 'owner', 2)])
    assert ds.csv == ('id,name,desc,cats,updated_at,owner,release\r\n'
                      '1,Demo Proj,"Demo project with unicode ä µ \u263A\nsecond line",'
                      '"DataItem,EnumType,EnumValue,DataItemType",2024-02-20 16:45:30,owner,2\r\n')


def test_resource_release(world):
    ds = R.ReleaseResource().export(queryset=Release.objects.all())
    assert ds.headers == ['id', 'release_author', 'desc', 'updated_at', 'project_version',
                          'application_version', 'previous']
    assert cells(ds) == cells([
        (1, 'owner', 'Initial release for project', '2023-12-01 08:00:00', 0, 0, ''),
        (2, 'writer', 'First "release" | with pipe\nand newline', '2024-02-20 16:45:30', 1, 0, 1),
        (3, 'owner', 'Initial release for application', '2023-12-01 08:00:00', 0, 0, ''),
        (4, 'owner', 'Application release äµ', '2024-02-20 16:45:30', 1, 1, 3),
    ])


def test_resource_application(world):
    ds = R.ApplicationResource().export(queryset=Application.objects.all())
    assert ds.headers == ['id', 'name', 'desc', 'cats', 'project', 'updated_at', 'release']
    assert cells(ds) == cells([(1, 'App One', 'Application | desc', 'Requirement', 1, '2024-02-20 16:45:30', 4)])


def test_resource_project_user(world):
    ds = R.ProjectUserResource().export(queryset=ProjectUser.objects.all())
    assert ds.headers == ['id', 'updated_at', 'user', 'project', 'role']
    assert cells(ds) == cells([(1, '2024-01-15', 'reader', 1, 'RO'), (2, '2024-01-15', 'writer', 1, 'RW')])


def test_resource_val_set(world):
    ds = R.ValSetResource().export(queryset=ValSet.objects.all())
    assert ds.headers == ['id', 'updated_at', 'project', 'name', 'desc']
    assert cells(ds) == cells([(1, '2024-01-15', 1, 'Default', 'Default ValSet'),
                               (2, '2024-01-15', 1, 'VS1', 'Alternative "values"')])


SPEC_HEADERS = ['id', 'cat', 'name', 'domain', 'project', 'application', 'title', 'desc', 'owner', 'status',
                'updated_at', 'created_at', 'previous', 'rationale', 'remarks', 'implementation', 'val_set',
                'p_link', 's_link', 'p_kind', 's_kind', 'value', 's_data', 't1', 't2', 't3', 't4', 't5',
                'n1', 'n2', 'n3', 'change_log']


def test_resource_spec_item_headers_and_dehydrate(world):
    ds = R.SpecItemResource().export(queryset=SpecItem.objects.filter(id__in=[102, 106]).order_by('id'))
    assert ds.headers == SPEC_HEADERS
    enum_type, color_var = list(ds)
    # an empty JSON value is exported as None (-> empty CSV cell); FKs as ids; None FKs as ''
    [enum_type, color_var] = cells([enum_type, color_var])
    assert enum_type == cells([(102, 'EnumType', 'Color', 'Types', 1, '', 'Colour',
                         'Colors ä µ \u263A and **markdown**\n\n- bullet one\n- bullet two',
                         'owner', 'CNF', '2024-02-20 16:45:30', '2023-12-01 08:00:00', 103, '', '', '', 1,
                         '', '', '', '', '', None, '', '', '', '', '', 4, 0, 0, 'changed\r\nwith CRLF')])[0]
    # text fields: internal references converted to edit form; owner dehydrated; s_data is JSON text
    assert color_var == cells([(106, 'DataItem', 'ColorVar', 'Dom', 1, '', 'Title of ColorVar',
                         'See #EnumValue:Types:Red and #DataItemType:Types:uint8 and **bold**\n'
                         'newline "q" | pipe; dangling ERROR:9999',
                         'owner', 'MOD', '2024-03-03 03:03:03', '2023-12-01 08:00:00', '', 'x | y',
                         '  padded  ', '', 1, 102, '', 'VAR', '', '#EnumValue:Types:Red',
                         '{"a": 1, "k": [1, 2], "u": "\\u00e4"}', '1', 'µm', '', '', '', 0, 0, 7, '')])[0]


def test_resource_spec_item_dict_rows_are_ordered(world):
    ds = R.SpecItemResource().export(queryset=SpecItem.objects.filter(id=104))
    row = ds.dict[0]
    assert list(row.keys()) == SPEC_HEADERS
    assert row['s_link'] == 102 and row['value'] == '0' and row['status'] == 'NEW'
    assert row['updated_at'] == '2024-03-03 03:03:03'


def test_resource_export_without_queryset_exports_all_rows(world):
    assert len(R.SpecItemResource().export()) == 10
    assert len(R.SpecItemResource().export(queryset=SpecItem.objects.none())) == 0
    assert R.SpecItemResource().export(queryset=SpecItem.objects.none()).headers == SPEC_HEADERS


def test_resource_field_names_and_headers(world):
    r = R.SpecItemResource()
    assert list(r.fields) == SPEC_HEADERS
    assert r.get_export_headers() == SPEC_HEADERS
    assert list(R.ProjectResource().fields) == ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release']


def test_resource_csv_matches_zip_member(client, fresh_temp, world):
    client.force_login(world.owner)
    response, data, zf = export_zip(client, world.project.id, fresh_temp)
    csv_text = R.SpecItemResource().export(queryset=SpecItem.objects.filter(project_id=1)).csv
    assert csv_text.encode('utf-8') == zf.read('spec_items.csv')


# ---------------------------------------------------------------------------
# import_project and round trip
# ---------------------------------------------------------------------------

from django.core.files.uploadedfile import SimpleUploadedFile


def messages_of(response):
    return [(m.level_tag, m.message) for m in get_messages(response.wsgi_request)]


def upload_zip(client, data, fresh_temp, name='project.zip'):
    fresh_temp()
    return client.post('/editor/import_project', {'upload_file': SimpleUploadedFile(name, data)})


def make_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def modified_zip(zf, **replacements):
    """Copy of the exported zip in which members are replaced (value None drops the member)."""
    members = {}
    for name in zf.namelist():
        content = replacements.get(name, zf.read(name))
        if content is not None:
            members[name] = content
    return make_zip(members)


@pytest.fixture
def exported(client, fresh_temp, world):
    """Export the world's project, then rename the original so that it can be imported again."""
    world.admin = make_user('admin', is_staff=True)
    client.force_login(world.owner)
    response, data, zf = export_zip(client, world.project.id, fresh_temp)
    world.zip_bytes, world.zip = data, zf
    return world


@pytest.fixture
def renamed_original(exported):
    Project.objects.filter(id=exported.project.id).update(name='Original (renamed)')
    return exported


def release_chain(release):
    chain = []
    while release is not None:
        chain.append((release.release_author.username, release.desc, release.updated_at,
                      release.project_version, release.application_version))
        release = release.previous
    return chain


def item_key(item):
    if item is None:
        return None
    return (item.cat, item.domain, item.name, item.val_set.name, item.status)


def snapshot(project):
    """Id-free description of a project, as far as the importer is expected to preserve it."""
    return {
        'name': project.name, 'desc': project.desc, 'cats': project.cats, 'owner': project.owner.username,
        'release': release_chain(project.release),
        'val_sets': sorted((v.name, v.desc) for v in project.val_sets.all()),
        'users': sorted((pu.user.username, pu.role) for pu in project.project_users.all()),
        'applications': sorted((a.name, a.desc, a.cats, release_chain(a.release))
                               for a in project.applications.all()),
        'items': {item_key(s): {
            'title': s.title, 'desc': s.desc, 'owner': s.owner.username, 'updated_at': s.updated_at,
            'created_at': s.created_at, 'application': s.application.name if s.application else None,
            'previous': item_key(s.previous), 'p_link': item_key(s.p_link), 's_link': item_key(s.s_link),
            'rationale': s.rationale, 'remarks': s.remarks, 'implementation': s.implementation,
            'p_kind': s.p_kind, 's_kind': s.s_kind, 'value': s.value, 's_data': s.s_data,
            't1': s.t1, 't2': s.t2, 'n1': s.n1, 'n2': s.n2, 'n3': s.n3, 'change_log': s.change_log,
        } for s in project.project_spec_items.select_related('val_set', 'owner', 'application')},
    }


def test_import_project_get_renders_upload_form(client, world):
    admin = make_user('admin', is_staff=True)
    client.force_login(admin)
    response = client.get('/editor/import_project')
    assert response.status_code == 200
    assert response.context['title'] == 'Upload Zip File'
    assert 'upload_file.html' in [t.name for t in response.templates]


def test_import_project_requires_staff(client, exported, fresh_temp):
    client.force_login(exported.owner)      # owner, but not staff
    response = upload_zip(client, exported.zip_bytes, fresh_temp)
    assert response.status_code == 302 and response['Location'] == '/editor'
    assert messages_of(response) == [('alert-danger', 'This operation is only accessible to a staff user')]
    assert Project.objects.count() == 1


def test_import_project_success_has_no_message_and_redirects(client, renamed_original, fresh_temp):
    client.force_login(renamed_original.admin)
    response = upload_zip(client, renamed_original.zip_bytes, fresh_temp)
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert messages_of(response) == []          # no success message is issued
    assert Project.objects.filter(name='Demo Proj').count() == 1


def test_import_project_round_trip_semantics(client, renamed_original, fresh_temp):
    w = renamed_original
    client.force_login(w.admin)
    upload_zip(client, w.zip_bytes, fresh_temp)
    new = Project.objects.get(name='Demo Proj')
    old = Project.objects.get(id=w.project.id)
    assert new.id != old.id

    before, after = snapshot(old), snapshot(new)
    before['name'] = after['name']       # the original was renamed to make room for the import

    # --- preserved --------------------------------------------------------------------------
    assert after['desc'] == before['desc']
    assert after['cats'] == before['cats']
    assert after['owner'] == 'owner'
    assert after['val_sets'] == [('Default', 'Default ValSet'), ('VS1', 'Alternative "values"')]
    assert sorted(u for u, _ in after['users']) == ['reader', 'writer']
    assert after['release'] == before['release']
    assert [r[3:] for r in after['release']] == [(1, 0), (0, 0)]
    assert len(after['applications']) == 1
    app = after['applications'][0]
    assert app[:3] == ('App One', 'Application | desc', 'Requirement')
    assert set(after['items']) == set(before['items'])
    assert len(after['items']) == 10

    for key, b in before['items'].items():
        a = after['items'][key]
        for field in ('title', 'owner', 'updated_at', 'application', 'previous', 'p_link', 's_link',
                      'rationale', 'remarks', 'implementation', 'p_kind', 's_kind', 't1', 't2',
                      'n1', 'n2', 'n3'):
            assert a[field] == b[field], (key, field)

    # references are remapped to the new ids: stored text holds '#iref:<new id>'
    new_ids = {item_key(s): s.id for s in new.project_spec_items.all()}
    old_ids = {item_key(s): s.id for s in old.project_spec_items.all()}
    assert set(new_ids.values()).isdisjoint(old_ids.values())
    color_var = ('DataItem', 'Dom', 'ColorVar', 'Default', 'MOD')
    assert after['items'][color_var]['desc'] == (
        'See #iref:%d and #iref:%d and **bold**\nnewline "q" | pipe; dangling ERROR:9999'
        % (new_ids[('EnumValue', 'Types', 'Red', 'Default', 'NEW')],
           new_ids[('DataItemType', 'Types', 'uint8', 'Default', 'CNF')]))
    assert after['items'][color_var]['value'] == '#iref:%d' % new_ids[('EnumValue', 'Types', 'Red', 'Default', 'NEW')]
    calc = ('DataItem', 'Dom', 'Calc', 'Default', 'CNF')
    assert after['items'][calc]['value'] == '#iref:%d * 2' % new_ids[('DataItem', 'Dom', 'Count', 'Default', 'CNF')]
    req = ('Requirement', 'AppDom', 'R1', 'Default', 'NEW')
    assert after['items'][req]['value'] == \
           'The app shall use #iref:%d and ä' % new_ids[('DataItem', 'Dom', 'Count', 'Default', 'CNF')]
    assert after['items'][req]['application'] == 'App One'

    # previous / p_link / s_link point at the new items
    obs_color = SpecItem.objects.get(id=new_ids[('EnumType', 'Types', 'Color', 'Default', 'CNF')]).previous
    assert obs_color.status == 'OBS' and obs_color.project_id == new.id
    assert SpecItem.objects.get(id=new_ids[color_var]).p_link_id == new_ids[('EnumType', 'Types', 'Color', 'Default', 'CNF')]
    assert SpecItem.objects.get(id=new_ids[('EnumValue', 'Types', 'Red', 'Default', 'NEW')]).s_link_id == \
           new_ids[('EnumType', 'Types', 'Color', 'Default', 'CNF')]

    # --- KNOWN-ISSUE losses ----------------------------------------------------------------
    # KNOWN-ISSUE: import-project-role-lost -- every ProjectUser is imported as 'RO'
    assert before['users'] == [('reader', 'RO'), ('writer', 'RW')]
    assert after['users'] == [('reader', 'RO'), ('writer', 'RO')]
    # KNOWN-ISSUE: import-project-created-at-lost -- SpecItem.created_at falls back to its default
    assert {b['created_at'] for b in before['items'].values()} == {T0}
    assert {a['created_at'] for a in after['items'].values()} == {datetime(2000, 1, 1, tzinfo=timezone.utc)}
    # KNOWN-ISSUE: import-project-application-version-lost -- Release.application_version is not imported
    assert before['applications'][0][3][0][4] == 1
    assert after['applications'][0][3][0][4] == 0
    # KNOWN-ISSUE: import-project-s-data-double-encoded -- s_data JSON is stored as a JSON *string*
    assert before['items'][color_var]['s_data'] == {'a': 1, 'k': [1, 2], 'u': 'ä'}
    assert after['items'][color_var]['s_data'] == '{"a": 1, "k": [1, 2], "u": "\\u00e4"}'
    assert before['items'][calc]['s_data'] == {} and after['items'][calc]['s_data'] == ''
    # KNOWN-ISSUE: import-project-auto-now-timestamps -- updated_at of Project/Application/ValSet/ProjectUser
    # are auto_now fields and are overwritten with the import time
    assert old.updated_at == T1 and new.updated_at > T1
    assert new.applications.get().updated_at > T1
    assert all(v.updated_at > D_FIXED for v in new.val_sets.all())
    assert all(pu.updated_at > D_FIXED for pu in new.project_users.all())
    # KNOWN-ISSUE: import-project-crlf-lost -- CR LF inside a field is read back as LF
    assert before['items'][('EnumType', 'Types', 'Color', 'Default', 'CNF')]['change_log'] == 'changed\r\nwith CRLF'
    assert after['items'][('EnumType', 'Types', 'Color', 'Default', 'CNF')]['change_log'] == 'changed\nwith CRLF'


def test_import_project_reexport_equals_first_export_modulo_ids(client, renamed_original, fresh_temp):
    w = renamed_original
    client.force_login(w.admin)
    upload_zip(client, w.zip_bytes, fresh_temp)
    new = Project.objects.get(name='Demo Proj')
    client.force_login(w.owner)
    response, data2, zf2 = export_zip(client, new.id, fresh_temp)
    assert zf2.namelist() == PROJECT_MEMBERS

    first, second = canonical_tables(w.zip), canonical_tables(zf2)
    differences = {}
    for member in PROJECT_MEMBERS:
        assert len(first[member]) == len(second[member]), member
        for i, (a, b) in enumerate(zip(first[member], second[member])):
            assert list(a) == list(b)       # same columns in the same order
            for col in a:
                if a[col] != b[col]:
                    differences.setdefault((member, col), []).append((a[col], b[col]))

    # Everything else (ids aside) is identical; the only differences are the documented losses
    assert sorted(differences) == [
        ('applications.csv', 'updated_at'),
        ('project.csv', 'updated_at'),
        ('project_users.csv', 'role'),
        ('project_users.csv', 'updated_at'),
        ('releases.csv', 'application_version'),
        ('spec_items.csv', 'change_log'),
        ('spec_items.csv', 'created_at'),
        ('spec_items.csv', 's_data'),
        ('val_sets.csv', 'updated_at'),
    ]
    assert differences[('project_users.csv', 'role')] == [('RW', 'RO')]
    assert differences[('releases.csv', 'application_version')] == [('1', '0')]
    assert differences[('spec_items.csv', 'created_at')] == [('2023-12-01 08:00:00', '2000-01-01 00:00:00')] * 10
    assert differences[('spec_items.csv', 'change_log')] == [('changed\r\nwith CRLF', 'changed\nwith CRLF')]
    assert differences[('spec_items.csv', 's_data')] == [
        ('{"a": 1, "k": [1, 2], "u": "\\u00e4"}', '"{\\"a\\": 1, \\"k\\": [1, 2], \\"u\\": \\"\\\\u00e4\\"}"')]
    assert differences[('val_sets.csv', 'updated_at')][0][0] == '2024-01-15'


def test_import_project_after_deleting_original(client, exported, fresh_temp):
    # The alternative to renaming: delete the original project first
    w = exported
    SpecItem.objects.filter(project=w.project).update(previous=None, p_link=None, s_link=None)
    SpecItem.objects.filter(project=w.project).delete()
    Application.objects.filter(project=w.project).delete()
    ValSet.objects.filter(project=w.project).delete()
    ProjectUser.objects.filter(project=w.project).delete()
    Project.objects.filter(id=w.project.id).delete()
    client.force_login(w.admin)
    response = upload_zip(client, w.zip_bytes, fresh_temp)
    assert messages_of(response) == []
    new = Project.objects.get(name='Demo Proj')
    assert new.project_spec_items.count() == 10


def test_import_project_rejects_existing_name(client, exported, fresh_temp):
    client.force_login(exported.admin)
    response = upload_zip(client, exported.zip_bytes, fresh_temp)
    assert response['Location'] == '/editor'
    assert messages_of(response) == [('alert-danger', 'A project called Demo Proj already exists')]
    assert Project.objects.count() == 1
    assert Release.objects.count() == 4


def _project_csv_with(zf, **changes):
    row = read_csv_member(zf, 'project.csv')[0]
    row.update(changes)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(row), lineterminator='\r\n')
    writer.writeheader()
    writer.writerow(row)
    return out.getvalue().encode('utf-8')


def test_import_project_rejects_unknown_owner(client, renamed_original, fresh_temp):
    w = renamed_original
    data = modified_zip(w.zip, **{'project.csv': _project_csv_with(w.zip, owner='ghost')})
    client.force_login(w.admin)
    response = upload_zip(client, data, fresh_temp)
    [(level, text)] = messages_of(response)
    assert level == 'alert-danger'
    assert text.startswith('The project owner ghost does not exist: ')
    assert 'User matching query does not exist' in text       # Django-provided part
    assert Project.objects.count() == 1


def test_import_project_rejects_undefined_project_category(client, renamed_original, fresh_temp):
    w = renamed_original
    data = modified_zip(w.zip, **{'project.csv': _project_csv_with(w.zip, cats='DataItem,Bogus')})
    client.force_login(w.admin)
    response = upload_zip(client, data, fresh_temp)
    assert messages_of(response) == [('alert-danger', 'The project category Bogus is not defined in configs.json')]
    assert Project.objects.count() == 1


def _applications_csv_with(zf, cats):
    rows = read_csv_member(zf, 'applications.csv')
    rows[0]['cats'] = cats
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator='\r\n')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode('utf-8')


def test_import_project_rejects_undefined_application_category(client, renamed_original, fresh_temp):
    w = renamed_original
    data = modified_zip(w.zip, **{'applications.csv': _applications_csv_with(w.zip, 'Requirement,Nope')})
    client.force_login(w.admin)
    response = upload_zip(client, data, fresh_temp)
    assert messages_of(response) == [
        ('alert-danger', 'The category Nope in application App One is not defined in configs.json')]
    assert Project.objects.count() == 1


def test_import_project_rejects_application_with_empty_categories(client, renamed_original, fresh_temp):
    # KNOWN-ISSUE: import-project-empty-app-cats
    # An application without categories (cats='') cannot be imported: ''.split(',') == [''] and
    # '' is not a configured category. The message therefore contains two spaces.
    w = renamed_original
    data = modified_zip(w.zip, **{'applications.csv': _applications_csv_with(w.zip, '')})
    client.force_login(w.admin)
    response = upload_zip(client, data, fresh_temp)
    assert messages_of(response) == [
        ('alert-danger', 'The category  in application App One is not defined in configs.json')]
    assert Project.objects.count() == 1


@pytest.mark.parametrize('member,label', [
    ('project.csv', 'project'), ('releases.csv', 'release'), ('val_sets.csv', 'ValSet'),
    ('project_users.csv', 'ProjectUser'), ('applications.csv', 'Application'),
    ('spec_items.csv', 'SpecItem')])
def test_import_project_missing_member(client, renamed_original, fresh_temp, member, label):
    w = renamed_original
    client.force_login(w.admin)
    response = upload_zip(client, modified_zip(w.zip, **{member: None}), fresh_temp)
    [(level, text)] = messages_of(response)
    assert level == 'alert-danger'
    assert text.startswith('Failure to open or read import %s file ' % label)
    assert member in text
    assert 'No such file or directory' in text
    assert Project.objects.count() == 1       # nothing imported (the check precedes any write)


def test_import_project_not_a_zip(client, renamed_original, fresh_temp):
    client.force_login(renamed_original.admin)
    response = upload_zip(client, b'this is not a zip file', fresh_temp)
    assert response['Location'] == '/editor'
    [(level, text)] = messages_of(response)
    assert level == 'alert-danger'
    assert text.startswith('Unable to import project zip file: BadZipFile(')


def test_import_project_no_file_uploaded(client, renamed_original, fresh_temp):
    client.force_login(renamed_original.admin)
    fresh_temp()
    response = client.post('/editor/import_project', {})
    assert response['Location'] == '/editor'
    assert messages_of(response) == [('alert-danger', "Unable to upload file: MultiValueDictKeyError('upload_file')")]


def test_import_project_unknown_project_user(client, renamed_original, fresh_temp):
    w = renamed_original
    users = read_csv_member(w.zip, 'project_users.csv')
    users[0]['user'] = 'ghost'
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(users[0]), lineterminator='\r\n')
    writer.writeheader(); writer.writerows(users)
    client.force_login(w.admin)
    response = upload_zip(client, modified_zip(w.zip, **{'project_users.csv': out.getvalue().encode()}), fresh_temp)
    [(level, text)] = messages_of(response)
    assert text.startswith('The project user ghost does not exist: ')
    assert Project.objects.count() == 1 and Release.objects.count() == 4


def test_import_project_unknown_release_author_leaves_partial_data(client, renamed_original, fresh_temp):
    # KNOWN-ISSUE: import-project-not-atomic
    # Releases are written one at a time; a later failure leaves the earlier ones behind
    # (IMPORT_EXPORT_USE_TRANSACTIONS does not apply, import_project_tables does not use a Resource).
    w = renamed_original
    rows = read_csv_member(w.zip, 'releases.csv')
    rows[2]['release_author'] = 'ghost'
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator='\r\n')
    writer.writeheader(); writer.writerows(rows)
    client.force_login(w.admin)
    response = upload_zip(client, modified_zip(w.zip, **{'releases.csv': out.getvalue().encode()}), fresh_temp)
    [(level, text)] = messages_of(response)
    assert text.startswith('The release author ghost does not exist: ')
    assert Project.objects.count() == 1
    assert Release.objects.count() == 4 + 2        # the two releases before the bad one were committed


def _spec_items_csv_with(zf, mutate):
    rows = read_csv_member(zf, 'spec_items.csv')
    mutate(rows)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator='\r\n')
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue().encode('utf-8')


def test_import_project_failing_spec_item_is_reported_and_others_imported(client, renamed_original, fresh_temp):
    w = renamed_original

    def mutate(rows):
        for row in rows:
            if row['name'] == 'Calc':
                row['owner'] = 'ghost'
    client.force_login(w.admin)
    response = upload_zip(client, modified_zip(w.zip, **{'spec_items.csv': _spec_items_csv_with(w.zip, mutate)}),
                          fresh_temp)
    [(level, text)] = messages_of(response)
    assert level == 'alert-danger'
    assert text == ('Failure to import spec_item DataItem:Dom:Calc (staus: CNF) Probable causes are: '
                    '(a) application identifier () is not recognized; '
                    '(b) spec_item owner ghost is not a project user '
                    '(c) ValSet identifier (1) is not recognized; '
                    '(d) Update time (2024-02-20 16:45:30) is not in format Y-m-d H-M-S; '
                    "Error is: KeyError('ghost')")
    new = Project.objects.get(name='Demo Proj')
    assert new.project_spec_items.count() == 9
    assert not new.project_spec_items.filter(name='Calc').exists()


def test_import_project_failing_referenced_spec_item_crashes(client, renamed_original, fresh_temp):
    # KNOWN-ISSUE: import-project-dangling-link-crash
    # When a spec_item that is the target of p_link/previous/s_link fails to import, the link
    # resolution step raises KeyError (not caught): the user sees a 500 and a half-imported project.
    w = renamed_original

    def mutate(rows):
        for row in rows:
            if row['name'] == 'uint8':
                row['owner'] = 'ghost'
    client.force_login(w.admin)
    with pytest.raises(KeyError):
        upload_zip(client, modified_zip(w.zip, **{'spec_items.csv': _spec_items_csv_with(w.zip, mutate)}),
                   fresh_temp)
    assert Project.objects.filter(name='Demo Proj').exists()


def test_import_project_removes_temp_dir(client, renamed_original, fresh_temp):
    # FIXED: temp-dir-not-cleaned (was: the unpacked archive stayed behind)
    w = renamed_original
    client.force_login(w.admin)
    tmp = fresh_temp()
    client.post('/editor/import_project', {'upload_file': SimpleUploadedFile('p.zip', w.zip_bytes)})
    assert Project.objects.filter(name='Demo Proj').exists()
    assert list(tmp.iterdir()) == []
    # also when the archive is unusable
    client.post('/editor/import_project', {'upload_file': SimpleUploadedFile('p.zip', b'not a zip')})
    assert list(tmp.iterdir()) == []


# ---------------------------------------------------------------------------
# import_spec_items
# ---------------------------------------------------------------------------

DI_LABELS = ['Domain', 'Name', 'Title', 'Description', 'Value', 'Rationale', 'Remarks', 'Implementation',
             'Type', 'Kind', 'Multiplicity', 'Unit', 'Owner', 'Change Log', 'ValSet']
ET_LABELS = ['Domain', 'Name', 'Title', 'Description', 'Default Value', 'Rationale', 'Remarks', 'Native Type',
             'ValSet', 'Change Log', 'Owner', 'Size']
REQ_LABELS = ['Domain', 'Name', 'Title', 'Text', 'Rationale', 'Remarks', 'Implementation', 'Close Out',
              'Validation', 'Kind', 'ValSet', 'Change Log', 'Owner', 'Ver']

DI_URL = '/editor/DataItem/1/0/1/Sel_All/import_spec_items'
DI_LIST_URL = '/editor/DataItem/1/0/1/Sel_All/0/list_spec_items'


def di_row(**kw):
    row = {'Domain': 'Dom', 'Name': 'NewItem', 'Title': 'A title', 'Description': '', 'Value': '5',
           'Rationale': '', 'Remarks': '', 'Implementation': '', 'Type': 'Types:uint8', 'Kind': 'CNS',
           'Multiplicity': '', 'Unit': '', 'Owner': 'ignored', 'Change Log': '', 'ValSet': 'Default'}
    row.update(kw)
    return row


def csv_bytes(labels, rows, sep='|'):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=labels, delimiter=sep, lineterminator='\r\n')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode('utf-8')


def post_csv(client, url, content, name='items.csv'):
    return client.post(url, {'upload_file': SimpleUploadedFile(name, content)})


def get_item(world, cat, domain, name, val_set='Default', exclude_status=('OBS', 'DEL')):
    return SpecItem.objects.exclude(status__in=exclude_status).get(
        project=world.project, cat=cat, domain=domain, name=name, val_set__name=val_set)


def test_import_spec_items_get_renders_form(client, world):
    client.force_login(world.rw)
    response = client.get(DI_URL)
    assert response.status_code == 200
    assert response.context['title'] == 'Upload CSV File'
    assert 'upload_file.html' in [t.name for t in response.templates]


@pytest.mark.parametrize('user_attr,allowed', [('owner', True), ('rw', True), ('ro', False)])
def test_import_spec_items_write_access(client, world, user_attr, allowed):
    client.force_login(getattr(world, user_attr))
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row()]))
    assert response.status_code == 302
    if allowed:
        assert response['Location'] == DI_LIST_URL
        assert SpecItem.objects.filter(name='NewItem').count() == 1
    else:
        assert response['Location'] == '/editor'
        assert messages_of(response) == [('alert-danger', 'This operation requires read/write access to project Demo Proj')]
        assert not SpecItem.objects.filter(name='NewItem').exists()


def test_import_spec_items_non_member_refused(client, world):
    client.force_login(make_user('stranger'))
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row()]))
    assert response['Location'] == '/editor'
    assert messages_of(response) == [('alert-danger', 'This operation requires read/write access to project Demo Proj')]


def test_import_spec_items_new_item(client, world):
    client.force_login(world.rw)
    row = di_row(Name='Fresh', Description='Refers to #DataItem:Dom:Count and #EnumValue:Types:Red',
                 Value='#iref:107 + 1', Type='Types:Color', Kind='VAR', Multiplicity='2', Unit='µm',
                 Owner='someone-else', Title='Tä')
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [row]))
    assert response['Location'] == DI_LIST_URL
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]
    item = get_item(world, 'DataItem', 'Dom', 'Fresh')
    assert item.status == 'NEW'
    assert item.owner == world.rw                          # Owner column is ignored
    assert item.project == world.project and item.application is None
    assert item.val_set == world.default
    assert item.previous is None
    assert item.desc == 'Refers to #iref:107 and #iref:104'   # references converted to db form
    assert item.value == '#iref:107 + 1'                    # eval_ref values are stored as is
    assert item.p_link == world.color                       # 'Types:Color' resolved to the spec_item
    assert (item.p_kind, item.t1, item.t2, item.title) == ('VAR', '2', 'µm', 'Tä')
    assert item.created_at > T2 and item.updated_at > T2
    assert item.n1 == 0 and item.s_data == {}


def test_import_spec_items_unresolvable_link_becomes_none(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Name='L1', Type='Nope:Nothing')]))
    assert get_item(world, 'DataItem', 'Dom', 'L1').p_link is None
    # FIXED: import-link-ambiguous (was: an unknown link was dropped without any message)
    assert messages_of(response) == [(
        'alert-warning', '1 imported, 0 rejected. Warnings: line 2: link Type "Nope:Nothing" matches no item, '
                         'imported without link')]


def test_import_spec_items_ambiguous_link_becomes_none_with_warning(client, world):
    # convert_exp_to_db looks the target up by domain:name only (any category, any ValSet), and the export
    # writes nothing more: Dom:Count exists in two ValSets, so the link cannot be resolved and is stored
    # empty as before; the row is imported and the line is reported.
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Name='L2', Type='Dom:Count'),
                                                              di_row(Name='L3', Type='Types:Color')]))
    assert get_item(world, 'DataItem', 'Dom', 'L2').p_link is None
    assert get_item(world, 'DataItem', 'Dom', 'L3').p_link == world.color
    # FIXED: import-link-ambiguous (was: the link was lost silently, no message)
    assert messages_of(response) == [(
        'alert-warning', '2 imported, 0 rejected. Warnings: line 2: link Type "Dom:Count" is ambiguous '
                         '(several items have this domain:name), imported without link')]


def test_import_spec_items_empty_or_none_link_gives_no_warning(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='L4', Type='None'), di_row(Name='L5', Type='')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [('alert-warning', '2 imported, 0 rejected. Warnings: line 3: '
                                      'empty required field(s) Type')]
    assert get_item(world, 'DataItem', 'Dom', 'L4').p_link is None


def test_import_spec_items_existing_confirmed_item_gets_obs_copy(client, world):
    client.force_login(world.rw)
    count_id = world.count.id
    row = di_row(Name='Count', Title='Count v2', Value='99', Description='now see #DataItem:Dom:Calc')
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [row]))
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]
    item = SpecItem.objects.get(id=count_id)                # original row is updated in place
    assert (item.status, item.title, item.value) == ('MOD', 'Count v2', '99')
    assert item.desc == 'now see #iref:108'
    assert item.owner == world.rw and item.updated_at > T2
    obs = item.previous
    assert obs.id != count_id
    assert (obs.status, obs.title, obs.value, obs.owner) == ('OBS', 'Title of Count', '42', world.rw)
    assert obs.previous is None
    assert obs.updated_at > T2
    assert obs.created_at == T0
    assert SpecItem.objects.filter(project=world.project, name='Count', domain='Dom', val_set=world.default).count() == 2


def test_import_spec_items_existing_modified_item_updated_in_place(client, world):
    client.force_login(world.rw)
    before = SpecItem.objects.count()
    row = di_row(Name='ColorVar', Title='Edited', Value='7', Type='Types:uint8', Kind='PAR')
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [row]))
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]
    assert SpecItem.objects.count() == before                # no OBS copy, no new row
    item = SpecItem.objects.get(id=world.colorvar.id)
    assert (item.status, item.title, item.value, item.p_kind) == ('MOD', 'Edited', '7', 'PAR')
    assert item.p_link == world.uint8
    assert item.owner == world.rw and item.updated_at > T2
    assert item.previous is None


def test_import_spec_items_existing_new_item_updated_in_place(client, world):
    client.force_login(world.rw)
    before = SpecItem.objects.count()
    row = {'Domain': 'Types', 'Name': 'Red', 'Title': 'Rot', 'Description': 'd', 'Value': '10',
           'Rationale': '', 'Remarks': '', 'Implementation': '', 'Type': 'Types:Color', 'Owner': 'x',
           'Change Log': '', 'ValSet': 'Default'}
    labels = ['Domain', 'Name', 'Title', 'Description', 'Value', 'Rationale', 'Remarks', 'Implementation',
              'Type', 'Owner', 'Change Log', 'ValSet']
    response = post_csv(client, '/editor/EnumValue/1/0/1/Sel_All/import_spec_items', csv_bytes(labels, [row]))
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]
    assert SpecItem.objects.count() == before
    item = SpecItem.objects.get(id=world.red.id)
    assert (item.status, item.title, item.value, item.s_link) == ('NEW', 'Rot', '10', world.color)
    assert item.owner == world.rw


def test_import_spec_items_existing_in_non_default_valset(client, world):
    client.force_login(world.rw)
    before = SpecItem.objects.count()
    url = '/editor/DataItem/1/0/2/Sel_All/import_spec_items'
    response = post_csv(client, url, csv_bytes(DI_LABELS, [di_row(Name='Count', ValSet='VS1', Value='44')]))
    assert response['Location'] == '/editor/DataItem/1/0/2/Sel_All/0/list_spec_items'
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]
    assert SpecItem.objects.count() == before
    assert SpecItem.objects.get(id=world.count_vs1.id).value == '44'
    assert SpecItem.objects.get(id=world.count.id).value == '42'


def test_import_spec_items_application_level(client, world):
    client.force_login(world.rw)
    row = {'Domain': 'AppDom', 'Name': 'R2', 'Title': 'Second', 'Text': 'Needs #DataItem:Dom:Count',
           'Rationale': '', 'Remarks': '', 'Implementation': '', 'Close Out': '', 'Validation': '',
           'Kind': 'STD', 'ValSet': 'Default', 'Change Log': '', 'Owner': 'x', 'Ver': 'TST'}
    url = '/editor/Requirement/1/1/1/Sel_All/import_spec_items'
    response = post_csv(client, url, csv_bytes(REQ_LABELS, [row]))
    assert response['Location'] == '/editor/Requirement/1/1/1/Sel_All/0/list_spec_items'
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]
    item = get_item(world, 'Requirement', 'AppDom', 'R2')
    assert item.application == world.app
    assert item.value == 'Needs #iref:107'


def test_import_spec_items_header_mismatch(client, world):
    client.force_login(world.rw)
    labels = [l for l in DI_LABELS if l != 'Unit'] + ['Extra', 'Another']
    response = post_csv(client, DI_URL, csv_bytes(labels, [{l: 'x' for l in labels}]))
    assert response['Location'] == DI_LIST_URL
    assert messages_of(response) == [(
        'alert-danger',
        'Uploaded CSV does not match the selected DataItem category: missing column(s): Unit; '
        'unexpected column(s): Another, Extra')]
    assert not SpecItem.objects.filter(title='x').exists()


def test_import_spec_items_wrong_category_file(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(ET_LABELS, [{l: 'x' for l in ET_LABELS}]))
    [(level, text)] = messages_of(response)
    assert level == 'alert-danger'
    assert text == ('Uploaded CSV does not match the selected DataItem category: missing column(s): '
                    'Implementation, Kind, Multiplicity, Type, Unit, Value; unexpected column(s): Default Value, Native Type, Size')


def test_import_spec_items_separator_matters(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row()], sep=','))
    [(level, text)] = messages_of(response)
    assert text.startswith('Uploaded CSV does not match the selected DataItem category: missing column(s): ')


def test_import_spec_items_empty_file_reports_all_columns_missing(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, b'')
    assert messages_of(response) == [(
        'alert-danger',
        'Uploaded CSV does not match the selected DataItem category: missing column(s): Change Log, Description, '
        'Domain, Implementation, Kind, Multiplicity, Name, Owner, Rationale, Remarks, Title, Type, Unit, '
        'ValSet, Value')]


def test_import_spec_items_utf8_bom_breaks_first_header(client, world):
    client.force_login(world.rw)
    content = b'\xef\xbb\xbf' + csv_bytes(DI_LABELS, [di_row()])
    response = post_csv(client, DI_URL, content)
    assert messages_of(response) == [(
        'alert-danger',
        'Uploaded CSV does not match the selected DataItem category: missing column(s): Domain; '
        'unexpected column(s): ﻿Domain')]


def test_import_spec_items_header_only_file_imports_nothing(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, []))
    assert response['Location'] == DI_LIST_URL
    # Task 7.4b: every import ends with a summary (was: no message)
    assert messages_of(response) == [('alert-success', '0 imported, 0 rejected')]


def test_import_spec_items_empty_required_fields_are_imported_with_warning(client, world):
    # FIXED: csv-export-not-reimportable (was: rows with an empty required (req_in_form) field were rejected
    # as 'missing <field>', so exports of production data (empty Ver/Value/Destination ...) could not be
    # imported again; operator 2026-10-24: accept them and list them as warnings)
    client.force_login(world.rw)
    rows = [di_row(Name='Q1', Value=''), di_row(Name='Q2', Value='   '), di_row(Name='Q3', Kind='', Type=''),
            di_row(Name='Okay')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [
        ('alert-warning', '4 imported, 0 rejected. Warnings: line 2: empty required field(s) Value; '
                          'line 3: empty required field(s) Value; line 4: empty required field(s) Kind, Type')]
    assert SpecItem.objects.filter(project=world.project, name__in=['Q1', 'Q2', 'Q3']).count() == 3
    assert get_item(world, 'DataItem', 'Dom', 'Okay')
    assert get_item(world, 'DataItem', 'Dom', 'Q1').value == ''
    assert get_item(world, 'DataItem', 'Dom', 'Q3').p_kind == ''


def test_import_spec_items_warnings_and_rejections_in_one_summary(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='W1', Value=''), di_row(Name='Bad Name'), di_row(Name='W2')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [(
        'alert-danger', '2 imported, 1 rejected. Rejected: line 3: ' + IDENT_ERR +
        '. Warnings: line 2: empty required field(s) Value')]


def test_import_spec_items_empty_domain_or_name_is_rejected(client, world):
    # an empty Domain or Name fails the identifier rule (it used to be reported as a missing required field)
    client.force_login(world.rw)
    rows = [di_row(Domain='', Name='A1'), di_row(Name=''), di_row(Domain='', Name='')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    # (identifier rule: an empty Domain or Name is still rejected, with the identifier message)
    assert messages_of(response) == [(
        'alert-danger', '0 imported, 3 rejected. Rejected: line 2: %s; line 3: %s; line 4: %s'
                        % (IDENT_ERR, IDENT_ERR, IDENT_ERR))]
    assert not SpecItem.objects.filter(name='A1').exists()


IDENT_ERR = "['Error: Only alphanumeric characters, underscores and dashes allowed; dots must be internal']"


@pytest.mark.parametrize('domain,name', [
    ('Do m', 'Ok'), ('Dom', 'bad name'), ('Dom', 'a/b'), ('.Dom', 'Ok'), ('Dom.', 'Ok'), ('Dom', 'a..b'),
    ('Dom', 'äbc'), ('Dom', 'x:y'), ('Dom', 'a|b')])
def test_import_spec_items_invalid_identifier(client, world, domain, name):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Domain=domain, Name=name)]))
    assert messages_of(response) == [(
        'alert-danger', '0 imported, 1 rejected. Rejected: line 2: ' + IDENT_ERR)]
    assert SpecItem.objects.filter(project=world.project).count() == 10


def test_import_spec_items_valid_identifiers_with_inner_dots_and_dashes(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Domain='a.b-c_d', Name='x.y.z-1')]))
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]


def test_import_spec_items_incorrect_domain_when_domain_selected(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='InDom'), di_row(Domain='Other', Name='OutDom')]
    response = post_csv(client, '/editor/DataItem/1/0/1/Dom/import_spec_items', csv_bytes(DI_LABELS, rows))
    assert response['Location'] == '/editor/DataItem/1/0/1/Dom/0/list_spec_items'
    assert messages_of(response) == [
        ('alert-danger', '1 imported, 1 rejected. Rejected: line 3: incorrect Domain')]
    assert get_item(world, 'DataItem', 'Dom', 'InDom')
    assert not SpecItem.objects.filter(name='OutDom').exists()


def test_import_spec_items_incorrect_valset(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='ToVs1', ValSet='VS1'), di_row(Name='ToNowhere', ValSet='Nope')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [(
        'alert-danger', '0 imported, 2 rejected. Rejected: line 2: incorrect ValSet; line 3: incorrect ValSet')]
    assert not SpecItem.objects.filter(name__in=['ToVs1', 'ToNowhere']).exists()


def test_import_spec_items_identifier_used_outside_category(client, world):
    client.force_login(world.rw)
    rows = [di_row(Domain='Types', Name='Color'), di_row(Domain='Types', Name='uint8')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [(
        'alert-danger', '0 imported, 2 rejected. Rejected: line 2: identifier already in use outside selected '
                        'category; line 3: identifier already in use outside selected category')]
    assert SpecItem.objects.filter(project=world.project).count() == 10


def test_import_spec_items_obs_and_del_identifiers_do_not_block(client, world):
    # the OBS predecessor 'Types:Color' (EnumType) does not count as "in use"; a DEL one neither
    SpecItem.objects.filter(id=world.color.id).update(status='DEL')
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Domain='Types', Name='Color')]))
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]


def test_import_spec_items_missing_from_default_valset(client, world):
    client.force_login(world.rw)
    url = '/editor/DataItem/1/0/2/Sel_All/import_spec_items'
    rows = [di_row(Name='OnlyVs1', ValSet='VS1'), di_row(Name='Count', ValSet='VS1', Value='45')]
    response = post_csv(client, url, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [
        ('alert-danger', '1 imported, 1 rejected. Rejected: line 2: missing from Default ValSet')]
    assert not SpecItem.objects.filter(name='OnlyVs1').exists()
    assert SpecItem.objects.get(id=world.count_vs1.id).value == '45'


def test_import_spec_items_aggregated_messages_are_sorted_and_counted(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='G1'), di_row(Name='G2', Title='x'), di_row(Name='Bad Name'), di_row(Name='M1', Value=''),
            di_row(Name='V1', ValSet='VS1'), di_row(Name='M2', Value=''), di_row(Domain='Types', Name='Color'),
            di_row(Domain='Other', Name='O1')]
    response = post_csv(client, '/editor/DataItem/1/0/1/Dom/import_spec_items', csv_bytes(DI_LABELS, rows))
    # Task 7.4b (import-spec-items-no-rollback): one summary message, one entry per rejected row (CSV line)
    assert messages_of(response) == [(
        'alert-danger',
        '4 imported, 4 rejected. Rejected: line 4: ' + IDENT_ERR + '; line 6: incorrect ValSet; '
        'line 8: incorrect Domain; line 9: incorrect Domain. '
        'Warnings: line 5: empty required field(s) Value; line 7: empty required field(s) Value')]


def test_import_spec_items_mixed_file_keeps_valid_rows_and_ends_with_one_summary(client, world):
    # FIXED: import-spec-items-no-rollback (was: valid rows committed and two separate messages, a success
    # count and an aggregated error count without line numbers; operator 2026-10-24: keep per-row import,
    # always one summary with the rejected CSV lines)
    client.force_login(world.rw)
    rows = [di_row(Name='Keep1'), di_row(Name='Bad Name'), di_row(Name='Keep2'), di_row(Name='Gone', Value='')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [(
        'alert-danger',
        '3 imported, 1 rejected. Rejected: line 3: ' + IDENT_ERR + '. Warnings: line 5: empty required field(s) Value')]
    assert SpecItem.objects.filter(project=world.project, name__in=['Keep1', 'Keep2']).count() == 2
    assert SpecItem.objects.filter(project=world.project).count() == 13


def test_import_spec_items_summary_lists_at_most_20_rejected_lines(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='Bad Name %d' % n) for n in range(23)] + [di_row(Name='Fine')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    [(level, text)] = messages_of(response)
    assert level == 'alert-danger'
    assert text.startswith('1 imported, 23 rejected. Rejected: line 2: ')
    assert text.count('line ') == 20
    assert text.endswith('; line 21: ' + IDENT_ERR + '; ... and 3 more')


def test_import_spec_items_summary_line_number_is_the_end_of_a_multiline_record(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='Bad Name', Description='two\nlines'), di_row(Name='Bad Name2')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    [(level, text)] = messages_of(response)
    assert text == '0 imported, 2 rejected. Rejected: line 3: %s; line 4: %s' % (IDENT_ERR, IDENT_ERR)


def test_import_spec_items_failing_row_leaves_no_half_saved_obs_copy(client, world, monkeypatch):
    # a row that fails after the OBS copy of a CNF item was made is rolled back completely
    import editor.views as views
    client.force_login(world.rw)
    def boom(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(views, 'export_to_spec_item', boom)
    before = list(SpecItem.objects.order_by('id').values_list('id', 'status', 'title', 'previous_id'))
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Name='Count', Title='Count v2')]))
    assert messages_of(response) == [(
        'alert-danger', '0 imported, 1 rejected. Rejected: line 2: unexpected error (details in the server log)')]
    assert list(SpecItem.objects.order_by('id').values_list('id', 'status', 'title', 'previous_id')) == before


def test_import_spec_items_duplicate_rows_in_file_second_updates_first(client, world):
    client.force_login(world.rw)
    rows = [di_row(Name='Dup', Value='1'), di_row(Name='Dup', Value='2')]
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, rows))
    assert messages_of(response) == [('alert-success', '2 imported, 0 rejected')]
    item = get_item(world, 'DataItem', 'Dom', 'Dup')
    assert item.value == '2' and item.status == 'NEW'


def test_import_spec_items_bad_number_cell_rejected_with_reason(client, world):
    # Task 7.4b review: an integer column (Size) that is empty or not a whole number is rejected with a clear
    # reason instead of 'unexpected error' (empty required number fields cannot be accepted like text fields)
    client.force_login(world.rw)
    row = {'Domain': 'Types', 'Title': 't', 'Description': '', 'Default Value': '', 'Rationale': '',
           'Remarks': '', 'Native Type': '', 'ValSet': 'Default', 'Change Log': '', 'Owner': 'x', 'Size': '1'}
    rows = [dict(row, Name='N1', Size=''), dict(row, Name='N2', Size='abc'), dict(row, Name='N3', Size=' -4 ')]
    response = post_csv(client, '/editor/EnumType/1/0/1/Sel_All/import_spec_items', csv_bytes(ET_LABELS, rows))
    assert messages_of(response) == [(
        'alert-danger', '1 imported, 2 rejected. Rejected: line 2: missing Size (number); '
                        'line 3: Size is not a whole number')]
    assert get_item(world, 'EnumType', 'Types', 'N3').n1 == -4


def test_import_spec_items_link_warning_truncates_long_cell(client, world):
    client.force_login(world.rw)
    response = post_csv(client, DI_URL, csv_bytes(DI_LABELS, [di_row(Name='L1', Type='X:' + 'y' * 200)]))
    [(level, text)] = messages_of(response)
    assert 'y' * 78 + '...' in text and 'y' * 81 not in text


def test_import_spec_items_exception_in_row_rejects_that_row_only(client, world, caplog):
    # FIXED: import-spec-items-abort-no-summary (was: a row that raises aborted the whole loop with a
    # message 'Unable to read or process uploaded file at line 3'; neither the success nor the error
    # summary was shown and the rows after it were not read)
    import logging
    client.force_login(world.rw)
    row = {'Domain': 'Types', 'Title': 't', 'Description': '', 'Default Value': '', 'Rationale': '',
           'Remarks': '', 'Native Type': '', 'ValSet': 'Default', 'Change Log': '', 'Owner': 'x', 'Size': '1'}
    rows = [dict(row, Name='E1'), dict(row, Name='E2'), dict(row, Name='E3')]
    original_save = SpecItem.save

    def failing_save(self, *args, **kwargs):     # an unexpected error while saving row E2
        if self.name == 'E2':
            raise ValueError('simulated failure')
        return original_save(self, *args, **kwargs)
    with caplog.at_level(logging.ERROR, logger='editor.views'), mock.patch.object(SpecItem, 'save', failing_save):
        response = post_csv(client, '/editor/EnumType/1/0/1/Sel_All/import_spec_items', csv_bytes(ET_LABELS, rows))
    assert response['Location'] == '/editor/EnumType/1/0/1/Sel_All/0/list_spec_items'
    assert messages_of(response) == [(
        'alert-danger', '2 imported, 1 rejected. Rejected: line 3: unexpected error (details in the server log)')]
    names = set(SpecItem.objects.filter(project=world.project, cat='EnumType').values_list('name', flat=True))
    assert 'E1' in names and 'E3' in names and 'E2' not in names
    logged = [rec for rec in caplog.records if rec.name == 'editor.views' and rec.exc_info]
    assert len(logged) == 1 and logged[0].exc_info[0] is ValueError


def test_import_spec_items_short_row_is_rejected_with_line_number(client, world):
    client.force_login(world.rw)
    content = csv_bytes(DI_LABELS, [di_row(Name='S1')]) + b'Dom|Short|only|three\r\n'
    response = post_csv(client, DI_URL, content)
    # FIXED: import-spec-items-abort-no-summary (was: the import aborted with 'Unable to read or process
    # uploaded file at line 3; the details were written to the server log')
    assert messages_of(response) == [(
        'alert-danger', '1 imported, 1 rejected. Rejected: line 3: row has fewer columns than the header')]
    assert get_item(world, 'DataItem', 'Dom', 'S1')


def test_import_spec_items_non_utf8_file_is_refused(client, world):
    # FIXED: import-spec-items-undefined-i (was: UnboundLocalError, HTTP 500; the decode error happened
    # before the loop variable 'i' existed)
    client.force_login(world.rw)
    before = SpecItem.objects.count()
    response = post_csv(client, DI_URL, b'\xff\xfe\x00bad bytes')
    assert response.status_code == 302
    assert response['Location'] == DI_LIST_URL
    assert messages_of(response) == [
        ('alert-danger', 'Uploaded file items.csv is not UTF-8 encoded; nothing was imported')]
    assert SpecItem.objects.count() == before


def test_import_spec_items_no_file(client, world):
    client.force_login(world.rw)
    response = client.post(DI_URL, {})
    assert response['Location'] == DI_LIST_URL
    assert messages_of(response) == [('alert-danger', "Unable to upload file: MultiValueDictKeyError('upload_file')")]


def test_import_spec_items_file_too_large(client, world, settings):
    # multiple_chunks() uses UploadedFile.DEFAULT_CHUNK_SIZE (64 KiB), independent of
    # FILE_UPLOAD_MAX_MEMORY_SIZE; shrinking the latter only forces a temporary file upload handler.
    settings.FILE_UPLOAD_MAX_MEMORY_SIZE = 1024
    client.force_login(world.rw)
    content = csv_bytes(DI_LABELS, [di_row(Name='Big', Description='x' * 70000)])
    size = len(content)
    assert size > 65536
    response = post_csv(client, DI_URL, content, name='big.csv')
    assert response['Location'] == DI_LIST_URL
    assert messages_of(response) == [(
        'alert-danger', 'Uploaded file big.csv is too big, size in MB is: ' + str(size / (1000 * 1000)))]
    assert not SpecItem.objects.filter(name='Big').exists()


def test_import_spec_items_file_just_below_chunk_size_is_accepted(client, world):
    client.force_login(world.rw)
    base = csv_bytes(DI_LABELS, [di_row(Name='Edge', Description='')])
    pad = 65536 - len(base)
    content = csv_bytes(DI_LABELS, [di_row(Name='Edge', Description='x' * pad)])
    assert len(content) == 65536
    response = post_csv(client, DI_URL, content)
    assert messages_of(response) == [('alert-success', '1 imported, 0 rejected')]


def test_import_spec_items_roundtrip_of_export(client, world):
    # Exporting DataItems and re-importing the file into the same project leaves it semantically unchanged
    client.force_login(world.owner)
    exported = client.get('/editor/DataItem/1/0/1/Sel_All/0/export_spec_items').content
    before = {(i.domain, i.name): (i.title, i.desc, i.value, i.p_link_id, i.rationale, i.remarks, i.p_kind)
              for i in SpecItem.objects.filter(project=world.project, cat='DataItem', val_set=world.default)
              .exclude(status='OBS')}
    response = post_csv(client, DI_URL, exported)
    assert messages_of(response) == [('alert-success', '3 imported, 0 rejected')]
    after = {(i.domain, i.name): (i.title, i.desc, i.value, i.p_link_id, i.rationale, i.remarks, i.p_kind)
             for i in SpecItem.objects.filter(project=world.project, cat='DataItem', val_set=world.default)
             .exclude(status='OBS')}
    # KNOWN-ISSUE: export-dangling-ref-literal
    # a dangling '#iref:9999' is exported as 'ERROR:9999' and comes back as that literal text
    key = ('Dom', 'ColorVar')
    assert before[key][1].endswith('dangling #iref:9999')
    assert after[key][1].endswith('dangling ERROR:9999')
    before[key] = (before[key][0], before[key][1].replace('#iref:9999', 'ERROR:9999')) + before[key][2:]
    assert after == before
    # CNF items (Calc, Count) were copied to OBS and are now MOD
    assert get_item(world, 'DataItem', 'Dom', 'Calc').status == 'MOD'
    assert get_item(world, 'DataItem', 'Dom', 'Count').status == 'MOD'
    assert get_item(world, 'DataItem', 'Dom', 'ColorVar').status == 'MOD'


# ---------------------------------------------------------------------------
# Content-Disposition filenames (quotes / non-latin-1 / non-ASCII in names)
# ---------------------------------------------------------------------------

from tests.backend import is_mysql

PROJECT_URL = '/editor/%d/export_project'
SPEC_PROJECT_LEVEL_URL = '/editor/DataItem/1/0/1/Sel_All/0/export_spec_items'
SPEC_APP_LEVEL_URL = '/editor/Requirement/1/1/1/Sel_All/0/export_spec_items'
SPEC_APP_LEVEL_NOAPP_URL = '/editor/Requirement/1/0/1/Sel_All/0/export_spec_items'

# project name -> expected export_project Content-Disposition (FileResponse)
PROJECT_DISPOSITIONS = {
    # Changed in Task 3.2 (Django 3.2.0 -> 3.2.25): CVE-2022-36359 fix escapes the quotes.
    # Django 3.2.0 sent: inline; filename="cordetfw_editor_A "q" B.zip"
    'A "q" B': 'inline; filename="cordetfw_editor_A \\"q\\" B.zip"',
    'Größe': "inline; filename*=utf-8''cordetfw_editor_Gr%C3%B6%C3%9Fe.zip",
    '日本 X': "inline; filename*=utf-8''cordetfw_editor_%E6%97%A5%E6%9C%AC%20X.zip",
}


@pytest.mark.parametrize('name', list(PROJECT_DISPOSITIONS), ids=['quotes', 'latin1', 'cjk'])
def test_export_project_content_disposition_special_names(client, fresh_temp, name):
    # 'quotes' changed as expected in Task 3.2 (CVE-2022-36359), accepted by the operator.
    # 'latin1' and 'cjk' were predicted to gain an ASCII 'filename="..."' fallback on Django 4.2+;
    # verified unchanged on Django 4.2.30 (Task 3.4). Kept as a guard for Django 5.2.
    w = build_world(name)
    client.force_login(w.owner)
    response, data, zf = export_zip(client, w.project.id, fresh_temp)
    assert response['Content-Disposition'] == PROJECT_DISPOSITIONS[name]
    assert zf.namelist() == PROJECT_MEMBERS


# project name -> (project-level filename header, app-level w/o application header)
SPEC_DISPOSITIONS = {
    'A "q" B': ('attachment; filename= "A_"q"_BDataItem.csv"',
                'attachment; filename= "A"q"BRequirement.csv"'),
    'Größe': ('attachment; filename= "GrößeDataItem.csv"',
              'attachment; filename= "GrößeRequirement.csv"'),
    # HttpResponse encodes a header value that is not latin-1 as an RFC 2047 encoded word
    # (base64 of the whole 'attachment; filename= "..."' value)
    '日本 X': ('=?utf-8?b?YXR0YWNobWVudDsgZmlsZW5hbWU9ICLml6XmnKxfWERhdGFJdGVtLmNzdiI=?=',
              '=?utf-8?b?YXR0YWNobWVudDsgZmlsZW5hbWU9ICLml6XmnKxYUmVxdWlyZW1lbnQuY3N2Ig==?='),
}


@pytest.mark.parametrize('name', list(SPEC_DISPOSITIONS), ids=['quotes', 'latin1', 'cjk'])
def test_export_spec_items_content_disposition_special_names(client, name):
    # export_spec_items builds the header by hand on a plain HttpResponse (not FileResponse), so
    # Django's FileResponse filename escaping does not apply: quotes are NOT escaped
    # (KNOWN-ISSUE: export-filename-not-escaped), and the CJK name is sent as an RFC 2047
    # encoded word, which browsers do not decode for Content-Disposition.
    w = build_world(name)
    client.force_login(w.owner)
    proj_header, noapp_header = SPEC_DISPOSITIONS[name]
    assert client.get(SPEC_PROJECT_LEVEL_URL)['Content-Disposition'] == proj_header
    assert client.get(SPEC_APP_LEVEL_NOAPP_URL)['Content-Disposition'] == noapp_header
    # project-level category: spaces become '_'; app-level without application: spaces removed
    # application-level with application: the application name is used
    assert client.get(SPEC_APP_LEVEL_URL)['Content-Disposition'] == 'attachment; filename= "AppOneRequirement.csv"'


APP_DISPOSITIONS = {
    'App "q" B': 'attachment; filename= "App"q"BRequirement.csv"',
    'Größe App': 'attachment; filename= "GrößeAppRequirement.csv"',
    '日本 X': '=?utf-8?b?YXR0YWNobWVudDsgZmlsZW5hbWU9ICLml6XmnKxYUmVxdWlyZW1lbnQuY3N2Ig==?=',
}


@pytest.mark.parametrize('app_name', list(APP_DISPOSITIONS), ids=['quotes', 'latin1', 'cjk'])
def test_export_spec_items_content_disposition_special_application_names(client, world, app_name):
    # KNOWN-ISSUE: export-filename-not-escaped (see above); application-level filename rule
    Application.objects.filter(id=world.app.id).update(name=app_name)
    client.force_login(world.owner)
    response = client.get(SPEC_APP_LEVEL_URL)
    assert response['Content-Disposition'] == APP_DISPOSITIONS[app_name]


# ---------------------------------------------------------------------------
# Numbers and JSON in exports (dedicated dataset; leaves the main goldens untouched)
# ---------------------------------------------------------------------------

def build_numbers_world():
    w = build_world('Num Proj')
    # A release with multi-digit versions, becoming the project's current release
    r5 = Release.objects.create(id=5, release_author=w.owner, desc='Release twelve', updated_at=T2,
                                project_version=12, application_version=11, previous=w.releases[1])
    Project.objects.filter(id=w.project.id).update(release=r5)
    kw = dict(project=w.project, owner=w.owner, val_set=w.default, status='CNF', updated_at=T1,
              created_at=T0)
    w.big = SpecItem.objects.create(id=1234, cat='PacketPar', domain='Pkt', name='Big', title='Big numbers',
                                    n1=12345, n2=-7, n3=0, **kw)
    w.big2 = SpecItem.objects.create(id=1000, cat='PacketPar', domain='Pkt', name='Edge', title='Edge numbers',
                                     n1=2147483647, n2=-2147483648, n3=1000000, **kw)
    w.sdata = SpecItem.objects.create(id=1235, cat='DataItem', domain='Json', name='Order', title='Json order',
                                      s_data={'zz': 1, 'a': 2, 'nested': {'y': 1, 'b': [1, 2]}}, **kw)
    return w


def test_export_project_numbers_golden(client, fresh_temp):
    # django-import-export 4 renders numbers differently (e.g. ints/floats in CSV cells),
    # so releases.csv / spec_items.csv of this dataset are pinned byte for byte.
    # Verified byte-identical with django-import-export 4.4.3 (Task 3.4b); kept as a guard.
    w = build_numbers_world()
    client.force_login(w.owner)
    response, data, zf = export_zip(client, w.project.id, fresh_temp)
    assert_golden('export/project_numbers/releases.csv', zf.read('releases.csv'))
    assert_golden('export/project_numbers/project.csv', zf.read('project.csv'))
    rows = {r['id']: r for r in read_csv_member(zf, 'spec_items.csv')}
    big = rows['1234']
    assert (big['n1'], big['n2'], big['n3'], big['id']) == ('12345', '-7', '0', '1234')
    edge = rows['1000']
    assert (edge['n1'], edge['n2'], edge['n3']) == ('2147483647', '-2147483648', '1000000')
    rel = {r['id']: r for r in read_csv_member(zf, 'releases.csv')}
    assert (rel['5']['project_version'], rel['5']['application_version']) == ('12', '11')
    assert read_csv_member(zf, 'project.csv')[0]['release'] == '5'


def test_export_project_numbers_spec_items_golden(client, fresh_temp):
    # Verified byte-identical with django-import-export 4.4.3 (Task 3.4b); kept as a guard
    w = build_numbers_world()
    client.force_login(w.owner)
    response, data, zf = export_zip(client, w.project.id, fresh_temp)
    # s_data is excluded: its key order differs per backend (see test_export_project_s_data_key_order)
    spec = [{k: v for k, v in r.items() if k != 's_data'}
            for r in read_csv_member(zf, 'spec_items.csv') if r['id'] in ('1000', '1234', '1235')]
    assert [r['id'] for r in spec] == ['1000', '1234', '1235']
    out = io.StringIO()
    csv.writer(out, lineterminator='\n').writerows(
        [list(spec[0].keys())] + [list(r.values()) for r in spec])
    assert_golden('export/project_numbers/spec_items_subset.csv', out.getvalue())


def test_export_spec_items_numbers_golden(client):
    # Numbers are str()-ed by the app (django-import-export is not involved); pinned so that a
    # change of integer rendering is noticed.
    w = build_numbers_world()
    client.force_login(w.owner)
    response = client.get('/editor/PacketPar/1/0/1/Sel_All/0/export_spec_items')
    assert response.status_code == 200
    assert_golden('export/spec_items/numbers_packetpar.csv', response.content)
    text = response.content.decode('utf-8')
    assert '|12345|' in text and '|-7|' in text and '|2147483647|' in text and '|-2147483648|' in text
    assert 'Big' in text and 'Edge' in text
    # s_data is not an exported attribute of any category
    assert 'zz' not in text


S_DATA_RAW = '{"zz": 1, "a": 2, "nested": {"y": 1, "b": [1, 2]}}'
# MySQL's JSON type normalises objects: keys sorted by length, then bytewise
S_DATA_MYSQL = '{"a": 2, "zz": 1, "nested": {"b": [1, 2], "y": 1}}'


def test_export_project_s_data_key_order(client, fresh_temp):
    w = build_numbers_world()
    client.force_login(w.owner)
    response, data, zf = export_zip(client, w.project.id, fresh_temp)
    row = [r for r in read_csv_member(zf, 'spec_items.csv') if r['id'] == '1235'][0]
    # KNOWN-ISSUE: export-s-data-key-order (key order of s_data in the export depends on the
    # database backend; MySQL reorders JSON keys on storage, SQLite keeps insertion order)
    if is_mysql():
        assert row['s_data'] == S_DATA_MYSQL
    else:
        assert row['s_data'] == S_DATA_RAW
    # semantically identical on both backends
    assert json.loads(row['s_data']) == {'zz': 1, 'a': 2, 'nested': {'y': 1, 'b': [1, 2]}}


def test_export_spec_items_does_not_export_s_data(client):
    w = build_numbers_world()
    client.force_login(w.owner)
    response = client.get('/editor/DataItem/1/0/1/Json/0/export_spec_items')
    text = response.content.decode('utf-8')
    assert 'Order' in text
    assert 'zz' not in text and 'nested' not in text
