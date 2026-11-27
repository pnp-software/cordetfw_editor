"""One end-to-end test per acceptance criterion, through the real endpoints and views; finer grained tests live in
the other modules of this package."""
import csv
import io
import json
import re
import zipfile
from pathlib import Path

import pytest
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db import models as dj_models
from django.test import Client

from editor import config_validation
from editor.config_cleanup import copy_config
from editor.config_store import config_token
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.project_config import get_project_config, load_template, new_project_config
from tests.project_config.base import BACKEND, add_payload, make_item, make_user, messages_of, refresh
from tests.project_config.test_project_config_endpoints import (ALL_ENDPOINTS, GET_ENDPOINTS, LOGIN_URL, OWNER_ONLY,
                                                                EndpointWorld, refusal)

pytestmark = pytest.mark.django_db

PRODUCTION = Path(__file__).resolve().parents[2] / 'editor'


@pytest.fixture
def w(client):
    """EndpointWorld whose client acts as the owner of Proj."""
    w = EndpointWorld(client)
    w.other_owner_client = w.client_for(w.other_owner)
    w.login(w.owner)
    return w


def cfg(project):
    return get_project_config(Project.objects.get(id=project.id))


def save_ok(w, config, project=None, client=None):
    project = project or w.project
    client = client or (w.owner_client if project == w.project else w.other_owner_client)
    response = w.save(client, config, project=project)
    assert response.status_code == 200, response.content
    return response.json()['token']


def widget(config, source='Service', **changes):
    definition = copy_config(config['cats'][source])
    definition.update(name='Widget', abbr='Wdg', expand={'s_link': 'None', 'p_link': 'None'}, tracs=[])
    definition.update(changes)
    config['cats']['Widget'] = definition
    return config


def add_to_project_cats(project, cat):
    Project.objects.filter(id=project.id).update(cats=project.cats + ',' + cat)


def snapshot(project):
    return {
        'items': list(SpecItem.objects.filter(project=project).order_by('id').values()),
        'releases': list(Release.objects.order_by('id').values()),
        'applications': list(Application.objects.filter(project=project).order_by('id')
                             .values('id', 'name', 'cats', 'release_id')),
        'project_cats': Project.objects.get(id=project.id).cats,
        'val_sets': list(ValSet.objects.filter(project=project).order_by('id').values()),
        'users': list(ProjectUser.objects.filter(project=project).order_by('id').values()),
    }


def page_content(response):
    assert response.status_code == 200
    return response.content.decode()


def export_bytes(w, project, client=None):
    response = (client or w.owner_client).get(w.curl('export_project', project))
    assert response.status_code == 200
    return b''.join(response.streaming_content)


def archived_config_text(w, project):
    """config.json of the project archive, as text."""
    archive = export_bytes(w, project, w.other_owner_client if project == w.other_project else None)
    return zipfile.ZipFile(io.BytesIO(archive)).read('config.json').decode()


def spec_item_rows(archive):
    member = zipfile.ZipFile(io.BytesIO(archive)).read('spec_items.csv').decode()
    return list(csv.DictReader(io.StringIO(member, newline='')))


def import_archive(w, data):
    response = w.client_for(w.staff).post(w.url('import_project'), {'upload_file': SimpleUploadedFile('p.zip', data)})
    return messages_of(response)


def remove(w, config, cat, attr=None):
    body = {'config': config, 'cat': cat}
    if attr:
        body['attr'] = attr
    response = w.post_json(w.owner_client, 'project_config_remove', body)
    assert response.status_code == 200, response.content
    return response.json()['config']


def test_criterion_01_two_projects_have_the_same_category_with_different_settings(w):
    first, second = cfg(w.project), cfg(w.other_project)
    first['cats']['Service'].update(name='Alpha Service', page_size=2)
    first['cats']['Service']['attrs']['title']['label'] = 'Alpha Title'
    second['cats']['Service'].update(name='Beta Service', page_size=3, abbr='BSvc')
    second['cats']['Service']['attrs']['title']['label'] = 'Beta Title'
    save_ok(w, first)
    save_ok(w, second, w.other_project)
    for project in (w.project, w.other_project):
        for n in range(1, 5):
            make_item(project, 'Service', 'D', 'svc%d' % n, title='T%d' % n, status='CNF')

    alpha = w.owner_client.get(w.list_url('Service'))
    beta = w.other_owner_client.get(w.list_url('Service', project=w.other_project, val_set=w.other_val_set))
    assert (alpha.context['config']['name'], len(alpha.context['page_items'])) == ('Alpha Service', 2)
    assert (beta.context['config']['name'], len(beta.context['page_items'])) == ('Beta Service', 3)
    assert 'Beta Service' not in page_content(alpha)
    assert 'Alpha Service' not in page_content(beta)
    form = w.owner_client.get(w.add_url('Service')).context['form']
    other_form = w.other_owner_client.get(
        w.url('add_spec_item', 'Service', w.other_project.id, 0, 'Sel_All', 0)).context['form']
    assert (form.fields['title'].label, other_form.fields['title'].label) == ('Alpha Title', 'Beta Title')
    assert w.stored()['cats']['Service']['name'] == 'Alpha Service'
    assert w.stored(w.other_project)['cats']['Service']['abbr'] == 'BSvc'
    assert w.stored()['cats']['Service']['abbr'] != 'BSvc'


def test_criterion_02_the_owner_adds_a_category_saves_and_creates_an_item_without_code(w):
    assert not w.owner.is_staff                         # the owner needs no staff status
    config = widget(cfg(w.project), page_size=5)
    save_ok(w, config)
    assert 'Widget' in w.stored()['cats']

    add_url = w.add_url('Widget')
    payload = w.form_payload(add_url, domain='W', name='w1', title='First widget', value='v')
    response = w.client.post(add_url, payload)
    assert response.status_code == 302, response.context['form'].errors if response.status_code == 200 else ''
    item = SpecItem.objects.get(cat='Widget', name='w1')
    assert (item.project_id, item.title, item.value) == (w.project.id, 'First widget', 'v')
    listed = w.client.get(w.list_url('Widget'))
    assert 'First widget' in page_content(listed)
    assert listed.context['config']['name'] == 'Widget'

    # Menus also need the category in Project.cats (changed by staff through "edit project").
    assert 'Manage Widgets' not in page_content(w.client.get('/editor/'))
    add_to_project_cats(w.project, 'Widget')
    assert 'Manage Widgets' in page_content(w.client.get('/editor/'))


def test_criterion_03_validation_checks_structure_types_limits_references_and_data(w):
    make_item(w.project, 'Requirement', 'R', 'req', p_kind='STD', title='t')
    invalid = [
        ('structure: unknown top-level key', lambda c: c.update(extra={}), 'extra'),
        ('structure: category setting missing', lambda c: c['cats']['Service'].pop('page_size'),
         'cats.Service.page_size'),
        ('type: page size is not a number', lambda c: c['cats']['Service'].update(page_size='many'),
         'cats.Service.page_size'),
        ('limit: page size out of range', lambda c: c['cats']['Service'].update(page_size=100000),
         'cats.Service.page_size'),
        ('model limit: attribute is not a SpecItem field',
         lambda c: c['cats']['Service']['attrs'].update(bogus={'label': 'B', 'kind': 'plain_text', 'req_in_form': False}),
         'cats.Service.attrs.bogus'),
        ('field kind not allowed for the field', lambda c: c['cats']['Service']['attrs']['n1'].update(kind='image')
         if 'n1' in c['cats']['Service']['attrs'] else c['cats']['Service']['attrs']['title'].update(kind='image'),
         'cats.Service.attrs.'),
        ('reference: layout names an unknown attribute',
         lambda c: c['cats']['Service']['disp_def'][0]['attrs'].append('nope'), 'cats.Service.disp_def[0].attrs'),
        ('reference: relationship names an unknown category',
         lambda c: c['cats']['Packet']['links']['p_link'].update(targets=['NoSuchCat']), 'cats.Packet.links.p_link'),
        ('server setting inside the project configuration', lambda c: c['general'].update(temp_dir='/etc'),
         'general.temp_dir'),
        ('data: a stored kind is no longer offered',
         lambda c: c['cats']['Requirement']['p_kind_choices'].pop('STD'), 'cats.Requirement.p_kind_choices'),
    ]
    stored = w.stored()
    for name, mutate, path in invalid:
        config = cfg(w.project)
        mutate(config)
        response = w.save(w.owner_client, config)
        assert response.status_code == 422, name
        assert any(e['path'].startswith(path) for e in response.json()['errors']), (name, response.json()['errors'])
        assert w.stored() == stored, name

    # Removing definitions is allowed with data when the remaining JSON is consistent; no data is deleted.
    before = snapshot(w.project)
    config = remove(w, cfg(w.project), 'Requirement')
    assert config_validation.validate_config(config, w.project) == []
    save_ok(w, config)
    assert 'Requirement' not in w.stored()['cats']
    assert snapshot(w.project) == before
    assert SpecItem.objects.filter(cat='Requirement', name='req', p_kind='STD').exists()


def test_criterion_04_a_saved_configuration_applies_to_the_next_request_without_restart(w):
    make_item(w.project, 'Service', 'D', 'svc', title='T')
    url = w.list_url('Service')
    assert 'Renamed Service' not in page_content(w.client.get(url))
    config = cfg(w.project)
    config['cats']['Service']['name'] = 'Renamed Service'
    save_ok(w, config)
    for client in (w.client, w.client_for(w.rw_user), Client()):       # other session, other user
        if client is not w.client and client.session.get('_auth_user_id') is None:
            client.force_login(w.rw_user, backend=BACKEND)
        assert 'Renamed Service' in page_content(client.get(url))
    # the same request path in a fresh Client: no per-process or shared state needed
    assert w.client_for(w.rw_user).get(url).context['config']['name'] == 'Renamed Service'


def test_criterion_05_preview_failed_saves_reload_and_stale_saves(w):
    stored = w.stored()
    draft = cfg(w.project)
    draft['cats']['Service']['name'] = 'Draft Service'
    response = w.post_json(w.owner_client, 'project_config_preview', draft)
    assert response.status_code == 200
    assert 'Draft Service' in response.json()['html']
    assert w.stored() == stored
    broken = copy_config(draft)
    broken['cats']['Service']['page_size'] = 0
    response = w.save(w.owner_client, broken)
    assert response.status_code == 422
    assert w.stored() == stored
    assert 'html' not in w.post_json(w.owner_client, 'project_config_preview', broken).json()
    reloaded = w.owner_client.get(w.curl('project_config_reload')).json()
    assert reloaded['config'] == cfg(w.project)
    assert reloaded['token'] == config_token(w.stored())
    assert w.stored() == stored
    # Two editors started from the same state: the second save is a conflict and does not overwrite
    editor_token = reloaded['token']
    first = cfg(w.project)
    first['cats']['Service']['name'] = 'First Writer'
    second = cfg(w.project)
    second['cats']['Service']['name'] = 'Second Writer'
    assert w.save(w.owner_client, first, editor_token).status_code == 200
    conflict = w.save(w.owner_client, second, editor_token)
    assert conflict.status_code == 409
    assert 'token' not in conflict.json()               # a client cannot go on without reloading
    assert w.stored()['cats']['Service']['name'] == 'First Writer'
    fresh = w.owner_client.get(w.curl('project_config_reload')).json()
    assert fresh['config']['cats']['Service']['name'] == 'First Writer'
    assert w.save(w.owner_client, second, fresh['token']).status_code == 200
    # The editor asks before discarding unsaved changes on reload (browser behavior, static guard + manual check)
    script = (PRODUCTION / 'static' / 'project_config.js').read_text(encoding='utf-8')
    assert 'Discard unsaved changes?' in script
    assert 'state.conflict = true' in script


def test_criterion_06_removing_a_field_does_not_delete_its_values_also_after_editing(w):
    item = make_item(w.project, 'Requirement', 'R', 'req', title='Req', value='v', p_kind='STD', s_kind='TST',
                     rationale='keep this rationale', remarks='keep these remarks')
    config = remove(w, cfg(w.project), 'Requirement', 'rationale')
    config = remove(w, config, 'Requirement', 'remarks')
    save_ok(w, config)
    assert 'rationale' not in w.stored()['cats']['Requirement']['attrs']
    edit_url = w.item_url('edit_spec_item', item)
    form = w.client.get(edit_url).context['form']
    assert [f.name for f in form if f.name in ('rationale', 'remarks') and not f.is_hidden] == []
    payload = w.form_payload(edit_url, title='Edited')
    for hidden in ('rationale', 'remarks'):             # a client may omit or forge the hidden values
        payload.pop(hidden, None)
    payload['rationale'] = 'forged'
    response = w.client.post(edit_url, payload)
    assert response.status_code == 302, response.context['form'].errors if response.status_code == 200 else ''
    item = refresh(item)
    assert (item.title, item.rationale, item.remarks, item.p_kind, item.s_kind) == \
        ('Edited', 'keep this rationale', 'keep these remarks', 'STD', 'TST')
    restored = cfg(w.project)
    restored['cats']['Requirement']['attrs']['rationale'] = load_template()['cats']['Requirement']['attrs']['rationale']
    save_ok(w, restored)
    assert 'keep this rationale' in page_content(w.client.get(edit_url))


def test_criterion_07_a_category_can_be_hidden_without_touching_items_history_releases_or_assignments(w):
    project = w.project
    info = make_item(project, 'InfoItem', 'I', 'info', title='Info', value='iv')
    info2 = make_item(project, 'InfoItem', 'I', 'info2', title='Info 2', previous=info, status='MOD')
    svc = make_item(project, 'Service', 'S', 'svc', title='Svc')
    pkt = make_item(project, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc)
    Release.objects.create(release_author=w.owner, desc='R1', updated_at=info.updated_at, project_version=1,
                           application_version=0)
    before = snapshot(project)
    config = remove(w, cfg(project), 'Service')         # a category others link to
    config = remove(w, config, 'InfoItem')
    save_ok(w, config)
    assert 'Service' not in w.stored()['cats']
    assert snapshot(project) == before                  # items (previous, links), releases, apps, cats, users
    assert refresh(pkt).p_link_id == svc.id
    assert refresh(info2).previous_id == info.id
    assert w.client.get(w.list_url('Packet')).status_code == 200


def test_criterion_08_restoring_a_category_shows_its_items_hidden_ones_do_not_break_references_and_export_keeps_them(w):
    svc = make_item(w.project, 'Service', 'S', 'svc', title='Svc', status='CNF')
    pkt = make_item(w.project, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc, status='CNF')
    full = cfg(w.project)
    save_ok(w, remove(w, cfg(w.project), 'Service'))
    assert w.client.get(w.list_url('Service')).status_code == 404
    # references and other pages still render; the reference is the plain identifier
    assert 'S:svc' in page_content(w.client.get(w.list_url('Packet')))
    assert w.client.get('/editor/').status_code == 200
    assert w.client.get(w.item_url('edit_spec_item', pkt)).status_code == 200
    rows = spec_item_rows(export_bytes(w, w.project))
    assert ('Service', 'svc') in [(r['cat'], r['name']) for r in rows]
    save_ok(w, full)
    restored = w.client.get(w.list_url('Service'))
    assert restored.status_code == 200
    assert [i.name for i in restored.context['page_items']] == ['svc']


def test_criterion_09_only_the_project_owner_can_access_or_modify_the_configuration(w):
    stored = w.stored()
    valid = cfg(w.project)
    valid['cats']['Service']['name'] = 'Hijacked'
    token = w.token()
    non_owners = {'rw member': w.rw_user, 'ro member': w.ro_user, 'staff non-owner': w.staff,
                  'owner of another project': w.other_owner,
                  'staff superuser': make_user('boss', is_staff=True, is_superuser=True)}
    for who, user in non_owners.items():
        for name in ALL_ENDPOINTS + ('project_config_preview', 'project_config_remove'):
            client = w.client_for(user)
            url = w.curl(name)
            if name in GET_ENDPOINTS:
                response = client.get(url)
            elif name == 'project_config_upload':
                response = client.post(url, {'upload_file': SimpleUploadedFile('c.json', json.dumps(valid).encode())})
            elif name == 'project_config_remove':
                response = client.post(url, data=json.dumps({'config': valid, 'cat': 'Service'}),
                                       content_type='application/json')
            else:
                response = client.post(url, data=json.dumps(valid), content_type='application/json',
                                       headers={'X-Config-Token': token})
            assert refusal(response) == OWNER_ONLY, (who, name)
            assert b'csv_sep' not in response.content, (who, name)      # no configuration leaks
    anonymous = Client()
    for name in ALL_ENDPOINTS:
        response = (anonymous.get if name in GET_ENDPOINTS else anonymous.post)(w.curl(name))
        assert response.status_code == 302
        assert response['Location'].startswith(LOGIN_URL)
    assert w.stored() == stored
    # the owner is let in; state-changing endpoints are POST only and CSRF protected
    assert w.owner_client.get(w.curl('project_config')).status_code == 200
    assert w.owner_client.get(w.curl('project_config_save')).status_code == 405
    enforcing = w.client_for(w.owner, enforce_csrf_checks=True)
    response = enforcing.post(w.curl('project_config_save'), data=json.dumps(valid), content_type='application/json',
                              headers={'X-Config-Token': token})
    assert response.status_code == 403
    assert w.stored() == stored
    assert w.curl('project_config') in w.owner_client.get('/editor/').content.decode()
    assert w.curl('project_config') not in w.client_for(w.rw_user).get('/editor/').content.decode()


def test_criterion_10_forms_lists_references_import_export_and_history_use_the_projects_configuration(w):
    first, second = cfg(w.project), cfg(w.other_project)
    first['cats']['Service']['name'] = 'Alpha Service'
    first['general']['csv_sep'] = ';'
    second['cats']['Service']['name'] = 'Beta Service'
    save_ok(w, first)
    save_ok(w, second, w.other_project)
    a = make_item(w.project, 'Service', 'D', 'svc', title='Svc A', status='CNF')
    b = make_item(w.other_project, 'Service', 'D', 'svc', title='Svc B', status='CNF')
    make_item(w.project, 'Packet', 'P', 'pkt', title='Pkt', p_link=a, status='CNF')
    assert 'Alpha Service' in page_content(w.owner_client.get(w.list_url('Service')))
    assert 'Beta Service' in page_content(w.other_owner_client.get(
        w.list_url('Service', project=w.other_project, val_set=w.other_val_set)))
    history = w.url('list_spec_item_history', 'Service', w.project.id, 0, a.id, 'Sel_All')
    assert w.owner_client.get(history).context['config']['name'] == 'Alpha Service'
    assert 'D:svc' in page_content(w.owner_client.get(w.list_url('Packet')))
    # item CSV export: separator and labels of the project
    csv_url = w.url('export_spec_items', 'Service', w.project.id, 0, w.default_val_set.id, 'Sel_All', 0)
    other_csv = w.url('export_spec_items', 'Service', w.other_project.id, 0, w.other_val_set.id, 'Sel_All', 0)
    assert ';' in w.owner_client.get(csv_url).content.decode().splitlines()[0]
    assert '|' in w.other_owner_client.get(other_csv).content.decode().splitlines()[0]
    archive = export_bytes(w, w.project)
    members = {n: zipfile.ZipFile(io.BytesIO(archive)).read(n) for n in zipfile.ZipFile(io.BytesIO(archive)).namelist()}
    assert json.loads(members['config.json']) == cfg(w.project)
    assert json.loads(archived_config_text(w, w.other_project))['cats']['Service']['name'] == 'Beta Service'
    # import restores the archived configuration; the original is renamed to free the project name
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    messages = import_archive(w, archive)
    imported = Project.objects.filter(name='Proj').exclude(id=w.project.id).get()
    assert imported.config == cfg(w.project), messages
    assert SpecItem.objects.filter(project=imported).count() == SpecItem.objects.filter(project=w.project).count()
    # an archive without a configuration gets the template filtered to the imported data
    old = io.BytesIO()
    with zipfile.ZipFile(old, 'w') as z:
        for name, content in members.items():
            if name != 'config.json':
                z.writestr(name, content)
    Project.objects.filter(id=imported.id).update(name='Proj_imported')
    import_archive(w, old.getvalue())
    derived = Project.objects.filter(name='Proj').exclude(id__in=[w.project.id, imported.id]).get()
    assert config_validation.validate_config(derived.config, derived) == []
    assert set(derived.config['cats']) == set(w.project.cats.split(',')) | \
        set(SpecItem.objects.filter(project=derived).values_list('cat', flat=True))
    assert 'temp_dir' not in derived.config['general']
    assert b.title == 'Svc B'                           # the other project was never touched
    assert w.stored(w.other_project)['cats']['Service']['name'] == 'Beta Service'


def row_counts():
    return {m.__name__: m.objects.count() for m in (Project, SpecItem, Release, ValSet, ProjectUser, Application)}


def test_criterion_11_the_configuration_is_one_json_column_without_history_status_or_files(w, isolated_temp_dir):
    field = Project._meta.get_field('config')
    assert isinstance(field, dj_models.JSONField)
    assert field.default == dict
    model_names = [m.__name__ for m in apps.get_app_config('editor').get_models()]
    assert [n for n in model_names if 'config' in n.lower()] == []
    assert [f.name for f in Project._meta.get_fields() if 'config' in f.name or 'status' in f.name] == ['config']
    migration = __import__('editor.migrations.0014_project_config', fromlist=['Migration']).Migration
    assert [(type(op).__name__, op.model_name, op.name) for op in migration.operations] == \
        [('AddField', 'project', 'config')]

    before = row_counts()
    for n in range(3):
        config = cfg(w.project)
        config['cats']['Service']['page_size'] = 10 + n
        save_ok(w, config)
        w.post_json(w.owner_client, 'project_config_preview', config)
        w.owner_client.get(w.curl('project_config_download'))
    assert list(isolated_temp_dir.iterdir()) == []      # no server-side configuration file
    assert row_counts() == before                       # no new rows: no history, no statuses
    assert w.stored()['cats']['Service']['page_size'] == 12      # only the current value is kept
    with connection.cursor() as cursor:
        tables = {t for t in connection.introspection.table_names(cursor) if t.startswith('editor_')}
    assert [t for t in tables if 'config' in t] == []


def p_link_choices(w, cat):
    form = w.client.get(w.add_url(cat)).context['form']
    return [c[0] for c in form.fields['p_link'].choices if c[0]]


def test_criterion_12_existing_and_new_categories_use_the_same_relationship_rules_and_validators(w):
    service = make_item(w.project, 'Service', 'D', 'svc', title='Svc')
    enum_type = make_item(w.project, 'EnumType', 'D', 'et', title='ET')
    config = widget(cfg(w.project), source='Packet')    # a new category with Packet's rules
    config['cats']['Widget']['links'] = copy_config(config['cats']['Packet']['links'])
    save_ok(w, config)
    assert p_link_choices(w, 'Widget') == p_link_choices(w, 'Packet')
    assert p_link_choices(w, 'Packet') == [service.id]
    for cat in ('Packet', 'Widget'):
        url = w.add_url(cat)
        response = w.client.post(url, add_payload('Packet', {'p_link': service}, name=cat.lower() + '1'))
        assert response.status_code == 302, (cat, response.context['form'].errors if response.status_code == 200 else '')
        bad = w.client.post(url, add_payload('Packet', {'p_link': enum_type}, name=cat.lower() + '2'))
        assert bad.status_code == 200, cat
        assert 'p_link' in bad.context['form'].errors
        assert not SpecItem.objects.filter(cat=cat, name=cat.lower() + '2').exists()
    # configuration selects validators by name only; an unknown name is rejected, never imported or executed
    bad = cfg(w.project)
    bad['cats']['Widget']['validators'] = [{'name': 'os.system', 'params': {}}]
    response = w.save(w.owner_client, bad)
    assert response.status_code == 422
    assert 'cats.Widget.validators[0].name' in [e['path'] for e in response.json()['errors']]
    # no category name decides anything in production code or templates
    pattern = re.compile(r'''['"](%s)['"]''' % '|'.join(load_template()['cats']))
    offenders = []
    for path in list(PRODUCTION.rglob('*.py')) + list(PRODUCTION.glob('templates/**/*.html')) + \
            list(PRODUCTION.glob('static/*.js')):
        if 'migrations' in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line):
                offenders.append('%s:%d' % (path.relative_to(PRODUCTION), number))
    assert offenders == []


def test_criterion_13_removing_a_definition_asks_for_confirmation_naming_it_and_promising_the_data_is_kept(w):
    script = (PRODUCTION / 'static' / 'project_config.js').read_text(encoding='utf-8')
    text = re.sub(r"'\s*\+\s*'", '', script)            # the texts as the dialog shows them
    assert text.count('Its saved data will not be deleted') == 2
    assert ('will be deleted from the configuration: the category is no longer shown in the menus, lists and forms '
            'of this project') in text
    assert 'will be deleted from the configuration: it is no longer shown in its forms, lists and CSV exports' in text
    # tooltips on hover and focus; cancelling changes nothing: the request is sent and the state changed only by
    # the action which confirmDialog runs after the confirmation
    assert "'data-bs-trigger': 'hover focus'" in script
    assert re.search(r"confirmDialog\(title, body, 'Delete', 'bi-trash-fill', function \(\) \{\s*"
                     r"deleteDefinition\(catId, attrId\);\s*\}\);", script)
    assert re.search(r"async function deleteDefinition\(catId, attrId\) \{\s*"
                     r"const payload = \{config: state\.config, cat: catId\};", script)
    assert script.count('deleteDefinition(') == 2       # the definition and the confirmed action
    assert re.search(r"if \(window\.confirm\([^\n]*\)\) \{\s*action\(\);\s*\}", script)
    assert script.count('action();') == 2               # without Bootstrap: window.confirm; else the Confirm button
    # the page carries the remove endpoint and the confirmed action keeps the data: cleanup in the backend only
    assert w.curl('project_config_remove') in page_content(w.owner_client.get(w.curl('project_config')))
    item = make_item(w.project, 'Requirement', 'R', 'req', title='Req', rationale='kept')
    before = snapshot(w.project)
    cleaned = remove(w, cfg(w.project), 'Requirement', 'rationale')
    assert 'rationale' not in cleaned['cats']['Requirement']['attrs']
    assert snapshot(w.project) == before                # nothing stored and nothing deleted by the request
    assert refresh(item).rationale == 'kept'
    assert w.stored() == new_project_config()
