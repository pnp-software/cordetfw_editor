import csv
import io
import re
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from editor.convert import convert_db_to_edit
from editor.forms import identifier_error
from editor.models import Application, Project, ProjectUser, SpecItem, ValSet
from editor.project_config import new_project_config
from tests.project_config.base import (TEMPLATE, World, make_application, make_item, make_project, make_user,
                                       messages_of, refresh)

pytestmark = pytest.mark.django_db

TEXT_ATTRS = ('desc', 'rationale', 'remarks', 'implementation', 'value', 't1', 't2', 't3', 't4', 't5')
# s_data and created_at are not restored by import
PLAIN_ATTRS = ('domain', 'name', 'title', 'p_kind', 's_kind', 'n1', 'n2', 'n3', 'status', 'change_log')
CSV_NAMES = ['project.csv', 'applications.csv', 'val_sets.csv', 'project_users.csv', 'releases.csv', 'spec_items.csv']
SERVICE_ATTRS = TEMPLATE['cats']['Service']['attrs']


@pytest.fixture
def w(client):
    return World(client)


@pytest.fixture
def exportable(w):
    """Service svc and Packet pkt referring to it."""
    w.service = make_item(w.project, 'Service', 'S', 'svc', title='Svc title', value='Type 1')
    w.packet = make_item(w.project, 'Packet', 'P', 'pkt', title='a_b & c', p_link=w.service,
                         p_kind='TC', value='sub', t1='x', t2='y', desc='refers #iref:%d' % w.service.id)
    return w


@pytest.fixture
def archived(w, settings, tmp_path):
    """Project Proj with items of all statuses, an alias in ValSet Alt, links, references and a second application."""
    settings.TEMP_DIR = str(tmp_path)
    p = w.project
    w.alt = ValSet.objects.create(project=p, name='Alt', desc='Alternative')
    w.svc = make_item(p, 'Service', 'S', 'svc', title='Svc', value='Type', owner=w.owner)
    w.pkt = make_item(p, 'Packet', 'P', 'pkt', title='Pkt', p_link=w.svc, p_kind='TC', t1='a', t2='b',
                      desc='uses #iref:%d' % w.svc.id, owner=w.rw_user, status='CNF')
    w.enum = make_item(p, 'EnumType', 'E', 'color', n1=1)
    w.val = make_item(p, 'EnumValue', 'E', 'red', s_link=w.enum, value='1', title='Red')
    w.der = make_item(p, 'DerPacket', 'P', 'der', p_link=w.val, s_link=w.pkt, t1='x')
    obsolete = make_item(p, 'Service', 'S', 'old', title='before', status='OBS')
    make_item(p, 'Service', 'S', 'old', title='after', status='MOD', previous=obsolete)
    make_item(p, 'Service', 'S', 'removed', status='DEL')
    w.alias = make_item(p, 'Service', 'S', 'svc', val_set=w.alt, p_link=w.svc, title='Svc alias', value='T2')
    w.req = make_item(p, 'Requirement', 'R', 'req', value='r #iref:%d' % w.svc.id, p_kind='STD', s_kind='TST')
    w.ver = make_item(p, 'VerItem', 'V', 'ver', title='Ver', p_kind='TST', s_kind='OPEN')
    make_item(p, 'VerLink', 'L', 'link', p_link=w.ver, s_link=w.req, title='l')
    w.hidden_app = make_application(p, 'Second', cats=['Requirement'])
    make_item(p, 'Requirement', 'R', 'req2', application=w.hidden_app, value='v2')
    return w


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text), delimiter='|'))


# ------------------------------------------------------------------ export of spec items

def export(w, cat, query='', application_id=None, sel_val='Sel_All'):
    if application_id is None:
        application_id = w.app_id(cat)
    url = w.url('export_spec_items', cat, w.project.id, application_id, w.default_val_set.id, sel_val, 0)
    return w.client.get(url + query)


def test_plain_export_uses_attribute_labels_as_header(exportable):
    response = export(exportable, 'Packet')
    assert response['Content-Type'] == 'text/plain'
    assert response['Content-Disposition'] == 'attachment; filename= "ProjPacket.csv"'
    rows = parse_csv(response.content.decode())
    labels = [spec['label'] for spec in TEMPLATE['cats']['Packet']['attrs'].values()]
    assert list(rows[0].keys()) == labels
    assert len(rows) == 1
    row = rows[0]
    assert (row['Domain'], row['Name'], row['Title']) == ('P', 'pkt', 'a_b & c')
    assert row['Description'] == 'refers #Service:S:svc'            # references exported in edit notation
    assert row['Type'] == 'S:svc'                                   # spec_item_ref exported as domain:name
    assert row['Sub-Type'] == 'sub'
    assert row['Owner'] == 'owner'
    attrs = TEMPLATE['cats']['Packet']['attrs']
    assert (row['Val Set'] if 'Val Set' in row else row[attrs['val_set']['label']]) == 'Default'
    assert row[attrs['s_link']['label']] == 'None'


def test_export_file_name_depends_on_the_category_level_and_application(exportable):
    make_item(exportable.project, 'Requirement', 'R', 'req', value='v')
    assert export(exportable, 'Requirement')['Content-Disposition'] == 'attachment; filename= "AppRequirement.csv"'
    assert export(exportable, 'Requirement', application_id=0)['Content-Disposition'] == \
        'attachment; filename= "ProjRequirement.csv"'


def test_export_of_an_empty_list_is_empty(exportable):
    assert export(exportable, 'InfoItem').content == b''


def test_export_honours_domain_filter_and_excludes_deleted_items(exportable):
    make_item(exportable.project, 'Service', 'T', 'other')
    make_item(exportable.project, 'Service', 'S', 'gone', status='DEL')
    rows = parse_csv(export(exportable, 'Service', sel_val='S').content.decode())
    assert [r['Name'] for r in rows] == ['svc']


def test_latex_export_escapes_text_and_adds_traceability_columns(exportable):
    ver_item = make_item(exportable.project, 'VerItem', 'V', 'ver', title='Verifier')
    make_item(exportable.project, 'VerLink', 'L', 'link', p_link=ver_item, s_link=exportable.packet, title='l')
    rows = parse_csv(export(exportable, 'Packet', '?export=latex_format').content.decode())
    row = rows[0]
    assert row['Title'] == 'a\\_b \\& c'
    assert row['Description'] == 'refers S:svc'
    assert row['Type'] == 'S:svc'
    assert row['Owner'] == 'owner'
    assert row['Status'] == 'NEW'
    assert row['Project'] == 'Proj'
    assert row['Application'] == 'None'
    assert row['VerLink'] == 'V:ver (Verifier)'               # from tracs: trac_cat VerLink via s_link
    for key in ('UpdatedAt', 'CreatedAt'):
        assert re.search(r'^\d\d-\d\d-\d{4} \d\d:\d\d$', row[key])


def test_spec_item_export_requires_read_access(exportable):
    exportable.login(make_user('stranger'))
    response = export(exportable, 'Service')
    assert (response.status_code, response.url) == (302, '/editor')


# ------------------------------------------------------------------ import of spec items

def import_url(w, cat='Service', val_set=None, sel_val='Sel_All'):
    val_set = val_set or w.default_val_set
    return w.url('import_spec_items', cat, w.project.id, w.app_id(cat), val_set.id, sel_val)


def service_row(**values):
    """A complete CSV row for category Service keyed by column label."""
    base = {'domain': 'D', 'name': 'n1', 'title': 'Imported', 'desc': 'd', 'value': 'Type', 'rationale': 'r',
            'remarks': 'm', 'implementation': 'i', 'val_set': 'Default', 'change_log': '', 'owner': 'rw_user'}
    base.update(values)
    return {SERVICE_ATTRS[attr]['label']: base.get(attr, '') for attr in SERVICE_ATTRS}


def upload(w, rows, url=None, fieldnames=None):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames or [s['label'] for s in SERVICE_ATTRS.values()], delimiter='|')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    csv_file = SimpleUploadedFile('items.csv', out.getvalue().encode('utf-8'), content_type='text/csv')
    response = w.client.post(url or import_url(w), {'upload_file': csv_file})
    return response, messages_of(response)


def test_upload_form_is_offered(w):
    response = w.client.get(import_url(w))
    assert response.status_code == 200
    assert 'Upload CSV File' in response.content.decode()


def test_new_rows_create_new_items(w):
    response, messages = upload(w, [service_row(), service_row(name='n2', title='Second')])
    assert response.status_code == 302
    assert response.url == '/editor/Service/%d/0/%d/Sel_All/0/list_spec_items' % (w.project.id, w.default_val_set.id)
    assert messages == ['2 imported, 0 rejected']
    items = SpecItem.objects.filter(cat='Service').order_by('name')
    assert [(i.domain, i.name, i.title, i.status, i.owner_id, i.project_id, i.val_set_id) for i in items] == [
        ('D', 'n1', 'Imported', 'NEW', w.rw_user.id, w.project.id, w.default_val_set.id),
        ('D', 'n2', 'Second', 'NEW', w.rw_user.id, w.project.id, w.default_val_set.id)]
    assert (items[0].desc, items[0].value, items[0].rationale) == ('d', 'Type', 'r')


def test_references_are_converted_to_database_notation(w):
    target = make_item(w.project, 'Service', 'S', 'target')
    upload(w, [service_row(desc='see #Service:S:target')])
    assert SpecItem.objects.get(name='n1').desc == 'see #iref:%d' % target.id


def test_existing_new_item_is_updated_in_place(w):
    item = make_item(w.project, 'Service', 'D', 'n1', title='old', value='v')
    _, messages = upload(w, [service_row(title='updated')])
    assert messages == ['1 imported, 0 rejected']
    assert refresh(item).title == 'updated'
    assert SpecItem.objects.filter(cat='Service').count() == 1


def test_existing_confirmed_item_gets_an_obsolete_copy(w):
    item = make_item(w.project, 'Service', 'D', 'n1', title='old', value='v', status='CNF')
    upload(w, [service_row(title='updated')])
    item = refresh(item)
    assert (item.title, item.status) == ('updated', 'MOD')
    assert (item.previous.title, item.previous.status) == ('old', 'OBS')


def test_header_must_match_the_category(w):
    labels = [s['label'] for s in SERVICE_ATTRS.values()]
    _, messages = upload(w, [], fieldnames=labels[1:] + ['Bogus'])
    assert len(messages) == 1
    assert messages[0] == ('Uploaded CSV does not match the selected Service category: missing column(s): %s; '
                           'unexpected column(s): Bogus' % labels[0])
    assert not SpecItem.objects.exists()


def test_rejected_rows_are_summarised_by_reason(w):
    make_item(w.project, 'Packet', 'D', 'taken')
    rows = [service_row(name='ok'), service_row(name='', title='x'), service_row(name='bad name'),
            service_row(name='taken'), service_row(name='wrongvs', val_set='Other')]
    _, messages = upload(w, rows)
    bad_identifier = "['%s']" % identifier_error
    assert messages == [
        '1 imported, 4 rejected. Rejected: line 3: %s; line 4: %s; line 5: identifier already in use outside '
        'selected category; line 6: incorrect ValSet' % (bad_identifier, bad_identifier)]
    assert list(SpecItem.objects.filter(cat='Service').values_list('name', flat=True)) == ['ok']


def test_domain_must_match_the_selected_domain(w):
    _, messages = upload(w, [service_row(domain='D'), service_row(domain='E', name='n2')],
                         url=import_url(w, sel_val='D'))
    assert messages == ['1 imported, 1 rejected. Rejected: line 3: incorrect Domain']


def test_import_into_another_val_set_requires_the_item_in_the_default_val_set(w):
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    make_item(w.project, 'Service', 'D', 'n1')
    rows = [service_row(val_set='Alt'), service_row(val_set='Alt', name='n2')]
    _, messages = upload(w, rows, url=import_url(w, val_set=alt))
    assert messages == ['1 imported, 1 rejected. Rejected: line 3: missing from Default ValSet']
    assert SpecItem.objects.filter(cat='Service', val_set=alt).count() == 1


def test_import_requires_write_access(w):
    w.login(make_user('stranger'))
    response, _ = upload(w, [service_row()])
    assert response.status_code == 302
    assert response.url == '/editor'
    assert not SpecItem.objects.exists()


# ------------------------------------------------------------------ project archive

def export_bytes(w, project=None):
    response = w.client.get(w.url('export_project', (project or w.project).id))
    return b''.join(response.streaming_content)


def export_zip(w, project=None):
    return zipfile.ZipFile(io.BytesIO(export_bytes(w, project)))


def import_zip(w, archive_bytes, user=None):
    w.login(user or make_user('boss', is_staff=True))
    response = w.client.post(w.url('import_project'), {'upload_file': SimpleUploadedFile('p.zip', archive_bytes)})
    return response, messages_of(response)


def zip_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return out.getvalue()


def zip_texts(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {n: archive.read(n).decode('utf-8') for n in archive.namelist()}


def read_csv(archive, name):
    text = archive.read(name).decode('utf-8')
    return list(csv.DictReader(io.StringIO(text)))


def item_key(item):
    if item is None:
        return None
    return (item.cat, item.domain, item.name, item.val_set.name, item.status)


def describe(project):
    """Content of a project independent of database ids."""
    items = {}
    for item in SpecItem.objects.filter(project=project):
        text = {a: convert_db_to_edit(getattr(item, a)) for a in TEXT_ATTRS}
        plain = {a: getattr(item, a) for a in PLAIN_ATTRS}
        items[item_key(item)] = dict(text, **plain, owner=item.owner.username, p_link=item_key(item.p_link),
                                     s_link=item_key(item.s_link), previous=item_key(item.previous),
                                     application=item.application.name if item.application else None)
    releases = []
    release = project.release
    while release is not None:
        releases.append((release.desc, release.project_version, release.release_author.username))
        release = release.previous
    applications = {a.name: (a.cats, a.desc) for a in Application.objects.filter(project=project)}
    return {'name_independent': (project.cats, project.desc, project.owner.username),
            'items': items, 'releases': releases, 'applications': applications,
            'val_sets': sorted(v.name for v in ValSet.objects.filter(project=project)),
            'users': sorted(u.user.username for u in ProjectUser.objects.filter(project=project))}


def test_export_contains_the_six_tables(archived):
    archive = export_zip(archived)
    # The configuration is a seventh member (see test_project_config_archive.py); the tables are unchanged
    assert sorted(archive.namelist()) == sorted(CSV_NAMES + ['config.json'])
    project = read_csv(archive, 'project.csv')
    assert len(project) == 1
    assert list(project[0].keys()) == ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release']
    assert (project[0]['name'], project[0]['owner'], project[0]['cats']) == ('Proj', 'owner', archived.project.cats)
    assert project[0]['release'] == str(archived.project.release_id)


def test_export_tables_hold_the_project_data(archived):
    archive = export_zip(archived)
    items = read_csv(archive, 'spec_items.csv')
    assert len(items) == SpecItem.objects.filter(project=archived.project).count()
    packet = [i for i in items if i['cat'] == 'Packet'][0]
    assert packet['desc'] == 'uses #Service:S:svc'                     # edit notation
    assert (packet['owner'], packet['p_link'], packet['status']) == ('rw_user', str(archived.svc.id), 'CNF')
    assert sorted(v['name'] for v in read_csv(archive, 'val_sets.csv')) == ['Alt', 'Default']
    assert [(u['user'], u['role']) for u in read_csv(archive, 'project_users.csv')] == [('rw_user', 'RW')]
    assert sorted(a['name'] for a in read_csv(archive, 'applications.csv')) == ['App', 'Second']
    assert len(read_csv(archive, 'releases.csv')) == 3


def test_export_excludes_other_projects(archived):
    other, _ = make_project('Other', owner=archived.owner)
    make_item(other, 'Service', 'X', 'foreign')
    archive = export_zip(archived)
    assert 'foreign' not in archive.read('spec_items.csv').decode()


def test_project_export_requires_read_access(archived):
    archived.login(make_user('stranger'))
    response = archived.client.get(archived.url('export_project', archived.project.id))
    assert (response.status_code, response.url) == (302, '/editor')


def test_round_trip_recreates_the_project(archived):
    # The archive carries the configuration, which must allow the stored Service -> Service link of
    # the alias item (the template has no such rule); the owner would have added it.
    config = new_project_config()
    config['cats']['Service']['links']['p_link'] = {'targets': ['Service']}
    Project.objects.filter(id=archived.project.id).update(config=config)
    data = export_bytes(archived)
    original = describe(archived.project)
    Project.objects.filter(id=archived.project.id).update(name='Proj_original')
    response, messages = import_zip(archived, data)
    assert (response.status_code, messages) == (302, [])
    imported = Project.objects.get(name='Proj')
    assert imported.id != archived.project.id
    copy = describe(imported)
    assert copy['name_independent'] == original['name_independent']
    assert copy['val_sets'] == original['val_sets']
    assert copy['users'] == original['users']
    assert copy['applications'] == original['applications']
    assert copy['releases'] == original['releases']
    assert copy['items'] == original['items']
    assert len(copy['items']) == 13
    assert SpecItem.objects.filter(project=imported).count() == 13
    assert not (set(SpecItem.objects.filter(project=imported).values_list('id', flat=True)) &
                set(SpecItem.objects.filter(project=archived.project).values_list('id', flat=True)))


def test_import_is_refused_for_existing_project_names(archived):
    _, messages = import_zip(archived, export_bytes(archived))
    assert messages == ['A project called Proj already exists']
    assert Project.objects.filter(name='Proj').count() == 1


def test_import_requires_a_staff_user(archived):
    data = export_bytes(archived)
    Project.objects.filter(id=archived.project.id).update(name='Proj_original')
    _, messages = import_zip(archived, data, user=archived.owner)
    assert messages == ['This operation is only accessible to a staff user']
    assert not Project.objects.filter(name='Proj').exists()


def test_import_rejects_categories_missing_from_the_template(archived):
    data = export_bytes(archived)
    Project.objects.filter(id=archived.project.id).update(name='Proj_original')
    files = zip_texts(data)
    reader = list(csv.DictReader(io.StringIO(files['project.csv'])))
    reader[0]['cats'] = reader[0]['cats'] + ',Bogus'
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(reader[0].keys()))
    writer.writeheader()
    writer.writerows(reader)
    files['project.csv'] = out.getvalue()
    _, messages = import_zip(archived, zip_bytes(files))
    assert messages == ['The project category Bogus is not defined in configs.json']
    assert not Project.objects.filter(name='Proj').exists()


def test_import_of_an_application_category_missing_from_the_template_is_rejected(archived):
    data = export_bytes(archived)
    Project.objects.filter(id=archived.project.id).update(name='Proj_original')
    files = zip_texts(data)
    files['applications.csv'] = files['applications.csv'].replace('Requirement', 'Nothing', 1)
    _, messages = import_zip(archived, zip_bytes(files))
    assert len(messages) == 1
    assert re.search(r'The category .*Nothing.* in application .* is not defined in configs.json', messages[0])
    assert not Project.objects.filter(name='Proj').exists()


def test_import_rejects_unknown_owner(archived):
    data = export_bytes(archived)
    Project.objects.filter(id=archived.project.id).update(name='Proj_original')
    files = zip_texts(data)
    lines = files['project.csv'].splitlines()
    files['project.csv'] = '\n'.join([lines[0], lines[1].replace(',owner,', ',nobody,')]) + '\n'
    _, messages = import_zip(archived, zip_bytes(files))
    assert messages[0].startswith('The project owner nobody does not exist')
    assert not Project.objects.filter(name='Proj').exists()
