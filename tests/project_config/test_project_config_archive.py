import csv
import io
import json
import logging
import zipfile
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from editor import imports
from editor.config_cleanup import copy_config, remove_attribute, remove_category
from editor.config_store import config_token
from editor.config_validation import MAX_JSON_BYTES, validate_config
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.project_config import filter_template_for_data, load_template, new_project_config
from tests.factories import template_config
from tests.project_config.base import (TEMPLATE, World, make_application, make_item, make_project, make_user,
                                       messages_of)

pytestmark = pytest.mark.django_db

CSV_MEMBERS = ['project.csv', 'applications.csv', 'val_sets.csv', 'project_users.csv', 'releases.csv', 'spec_items.csv']
UNSAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture
def w(client):
    """World with a staff user (w.boss), who imports the archives."""
    w = World(client)
    w.boss = make_user('boss', is_staff=True)
    return w


def export_bytes(w, project):
    w.login(project.owner)
    response = w.client.get(w.url('export_project', project.id))
    assert response.status_code == 200
    return b''.join(response.streaming_content)


def zip_members(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    return {name: archive.read(name) for name in archive.namelist()}


def make_zip(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return out.getvalue()


def with_config(data, config):
    """The archive `data` with config.json replaced by `config` (a dict or the text; None removes it)."""
    members = zip_members(data)
    members.pop('config.json', None)
    if config is not None:
        members['config.json'] = config if isinstance(config, (str, bytes)) else json.dumps(config)
    return make_zip(members)


def import_zip(w, data):
    w.login(w.boss)
    response = w.client.post(w.url('import_project'), {'upload_file': SimpleUploadedFile('p.zip', data)})
    return response, messages_of(response)


def counts():
    return {model.__name__: model.objects.count()
            for model in (Project, Release, ValSet, ProjectUser, Application, SpecItem, User)}


def stored(project):
    return Project.objects.get(id=project.id).config


def import_as_copy(w, project, data=None):
    """Import an archive of `project` under its own name (the original is renamed)."""
    data = data if data is not None else export_bytes(w, project)
    name = project.name
    Project.objects.filter(id=project.id).update(name=name + '_original')
    response, messages = import_zip(w, data)
    return Project.objects.filter(name=name).exclude(id=project.id).first(), messages


@pytest.fixture
def config(w):
    """The stored configuration of Proj, which has hidden data: a hidden field, a hidden category and a category
    of its own."""
    p = w.project
    svc = make_item(p, 'Service', 'S', 'svc', title='Svc title', value='Type')
    make_item(p, 'Requirement', 'R', 'req', title='Req title', value='v', p_kind='STD', s_kind='TST')
    make_item(p, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc, p_kind='TC', t1='x')
    make_item(p, 'InfoItem', 'I', 'info', title='hidden category data', value='iv')
    widget = make_item(p, 'InfoItem', 'W', 'w1', title='custom category data', value='wv')
    SpecItem.objects.filter(id=widget.id).update(cat='Widget')

    config = template_config()
    config = remove_category(config, 'InfoItem')                    # hidden category (items stay)
    config = remove_attribute(config, 'Service', 'title')           # hidden field (values stay)
    config = remove_attribute(config, 'Requirement', 'p_kind')      # hidden kind (values stay)
    config['cats']['Requirement']['page_size'] = 7
    widget_definition = copy_config(TEMPLATE['cats']['InfoItem'])
    widget_definition.update(name='Widget', abbr='Wdg')
    config['cats']['Widget'] = widget_definition
    Project.objects.filter(id=p.id).update(config=config)
    p.refresh_from_db()
    assert validate_config(config, p) == []
    return config


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def test_the_archive_has_the_configuration_as_a_last_extra_member(w, config):
    names = zipfile.ZipFile(io.BytesIO(export_bytes(w, w.project))).namelist()
    assert names == CSV_MEMBERS + ['config.json']


def test_project_csv_keeps_its_columns(w, config):
    text = zip_members(export_bytes(w, w.project))['project.csv'].decode()
    header = csv.DictReader(io.StringIO(text)).fieldnames
    assert header == ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release']


def test_config_json_is_the_stored_configuration(w, config):
    exported = json.loads(zip_members(export_bytes(w, w.project))['config.json'])
    assert exported == config
    assert 'temp_dir' not in exported['general']


def test_a_new_project_exports_the_configuration_of_a_new_project(w, config):
    other, _ = make_project('Plain', owner=w.owner)
    exported = json.loads(zip_members(export_bytes(w, other))['config.json'])
    assert exported == new_project_config()
    assert stored(other) == new_project_config()             # exporting does not store anything


def test_a_server_setting_injected_into_the_stored_value_is_not_exported(w, config):
    injected = copy_config(config)
    injected['general']['temp_dir'] = '/somewhere/else'
    Project.objects.filter(id=w.project.id).update(config=injected)
    text = zip_members(export_bytes(w, w.project))['config.json'].decode()
    assert 'temp_dir' not in text
    assert '/somewhere/else' not in text


def test_hidden_fields_and_categories_are_exported(w, config):
    rows = list(csv.DictReader(io.StringIO(zip_members(export_bytes(w, w.project))['spec_items.csv'].decode())))
    by_name = {(r['cat'], r['name']): r for r in rows}
    assert by_name[('Service', 'svc')]['title'] == 'Svc title'                     # field hidden in the configuration
    assert by_name[('Requirement', 'req')]['p_kind'] == 'STD'                      # kind hidden
    assert by_name[('InfoItem', 'info')]['title'] == 'hidden category data'        # category hidden
    assert by_name[('Widget', 'w1')]['value'] == 'wv'


def test_the_configuration_of_another_project_is_not_exported(w, config):
    other, _ = make_project('Other', owner=w.owner)
    other_config = template_config()
    other_config['cats']['Service']['name'] = 'Different'
    Project.objects.filter(id=other.id).update(config=other_config)
    exported = json.loads(zip_members(export_bytes(w, w.project))['config.json'])
    assert exported['cats']['Service']['name'] == config['cats']['Service']['name']
    assert exported['cats']['Service']['name'] != 'Different'


def test_export_still_requires_read_access(w, config):
    w.login(make_user('stranger'))
    response = w.client.get(w.url('export_project', w.project.id))
    assert (response.status_code, response.url) == (302, '/editor')


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

def test_the_configuration_is_restored_identically(w, config):
    imported, messages = import_as_copy(w, w.project)
    assert messages == []
    assert stored(imported) == config
    assert json.dumps(stored(imported), sort_keys=True) == json.dumps(config, sort_keys=True)
    assert validate_config(stored(imported), imported) == []


def test_the_original_project_is_untouched(w, config):
    def state():
        return stored(w.project), list(SpecItem.objects.filter(project=w.project).values_list('id', 'title'))
    before = state()
    imported, _ = import_as_copy(w, w.project)
    assert state() == before
    assert imported.id != w.project.id


def test_exporting_the_imported_project_gives_the_same_configuration(w, config):
    imported, _ = import_as_copy(w, w.project)
    again = json.loads(zip_members(export_bytes(w, imported))['config.json'])
    assert again == config


def test_hidden_data_round_trips(w, config):
    imported, _ = import_as_copy(w, w.project)
    items = {(i.cat, i.name): i for i in SpecItem.objects.filter(project=imported)}
    assert items[('Service', 'svc')].title == 'Svc title'
    assert (items[('Requirement', 'req')].p_kind, items[('Requirement', 'req')].s_kind) == ('STD', 'TST')
    assert (items[('InfoItem', 'info')].title, items[('InfoItem', 'info')].value) == ('hidden category data', 'iv')
    assert (items[('Widget', 'w1')].title, items[('Widget', 'w1')].value) == ('custom category data', 'wv')
    assert len(items) == SpecItem.objects.filter(project=w.project).count()


def test_the_import_restores_the_hidden_setting(w):
    hidden = template_config()
    hidden['cats']['Service']['attrs']['rationale']['hidden'] = True
    Project.objects.filter(id=w.project.id).update(config=hidden)
    make_item(w.project, 'Service', 'D', 'svc', title='T', rationale='kept')
    data = export_bytes(w, w.project)
    assert json.loads(zip_members(data)['config.json']) == hidden
    imported, messages = import_as_copy(w, w.project, data)
    assert messages == []
    assert stored(imported) == hidden
    assert SpecItem.objects.get(project=imported, name='svc').rationale == 'kept'


def test_relationships_point_into_the_new_project(w, config):
    imported, _ = import_as_copy(w, w.project)
    pkt = SpecItem.objects.get(project=imported, cat='Packet')
    assert pkt.p_link.name == 'svc'
    assert pkt.p_link.project_id == imported.id
    assert pkt.p_link_id != SpecItem.objects.get(project=w.project, cat='Service').id


def test_the_import_creates_one_project_and_leaves_other_projects_alone(w, config):
    other, _ = make_project('Other', owner=w.owner)
    other_config = template_config()
    other_config['cats']['Service']['name'] = 'Different'
    Project.objects.filter(id=other.id).update(config=other_config)
    other_item = make_item(other, 'Service', 'X', 'other', title='o')
    imported, _ = import_as_copy(w, w.project)
    assert stored(other) == other_config
    assert list(SpecItem.objects.filter(project=other).values_list('id', 'title')) == [(other_item.id, 'o')]
    assert stored(imported)['cats']['Service']['name'] == config['cats']['Service']['name']


def test_the_project_timestamp_of_the_archive_is_kept(w, config):
    original = Project.objects.get(id=w.project.id).updated_at
    imported, _ = import_as_copy(w, w.project)
    assert abs((imported.updated_at - original).total_seconds()) < 1


def test_the_archive_configuration_is_stored_by_the_shared_save_and_validated_after_the_links_exist(w, config):
    data = export_bytes(w, w.project)
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    seen = []
    real = imports.save_project_config

    def spy(project_id, body, token):
        project = Project.objects.get(id=project_id)
        seen.append((project.name, token, SpecItem.objects.get(project=project, cat='Packet').p_link.project_id,
                     json.loads(body) == config))
        return real(project_id, body, token)

    with mock.patch('editor.imports.save_project_config', side_effect=spy):
        response, messages = import_zip(w, data)
    imported = Project.objects.get(name='Proj')
    assert messages == []
    assert seen == [('Proj', config_token({}), imported.id, True)]


def test_the_configuration_is_validated_against_the_imported_data(w, config):
    data = export_bytes(w, w.project)
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    calls = []

    def spy(checked, project=None):
        calls.append((project.id if project else None,
                      SpecItem.objects.filter(project=project).count() if project else None))
        return validate_config(checked, project)

    with mock.patch('editor.config_validation.validate_config', side_effect=spy):
        import_zip(w, data)
    imported = Project.objects.get(name='Proj')
    assert (None, None) in calls                                    # structure, before any data exists
    assert (imported.id, SpecItem.objects.filter(project=imported).count()) in calls     # then the stored data


# ---------------------------------------------------------------------------
# Protection
# ---------------------------------------------------------------------------

def test_import_never_overwrites_the_configuration_of_an_existing_project(w, config):
    data = with_config(export_bytes(w, w.project), template_config())      # a different configuration
    before = (stored(w.project), counts())
    response, messages = import_zip(w, data)
    assert messages == ['A project called Proj already exists']
    assert (stored(w.project), counts()) == before


def test_import_still_requires_a_staff_user(w, config):
    data = export_bytes(w, w.project)
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    w.login(make_user('plain'))
    before = counts()
    response = w.client.post(w.url('import_project'), {'upload_file': SimpleUploadedFile('p.zip', data)})
    assert (response.status_code, response.url) == (302, '/editor')
    assert counts() == before


def test_a_server_setting_in_the_archive_configuration_is_rejected(w, config):
    bad = copy_config(config)
    bad['general']['temp_dir'] = '/tmp/elsewhere'
    imported, messages = import_as_copy(w, w.project, with_config(export_bytes(w, w.project), bad))
    assert imported is None
    assert len(messages) == 1
    assert 'general.temp_dir' in messages[0]


def import_unsafe_model(w, archive_config):
    model = make_item(w.project, 'Model', 'M', 'm1', title='m', value=UNSAFE_SVG)
    imported, messages = import_as_copy(w, w.project, with_config(export_bytes(w, w.project), archive_config))
    assert imported is not None
    assert not SpecItem.objects.filter(project=imported, cat='Model').exists()
    assert any('Model:M:m1' in m for m in messages), messages
    assert SpecItem.objects.filter(id=model.id).exists()


def test_hiding_the_category_in_the_archive_does_not_skip_the_svg_check(w, config):
    import_unsafe_model(w, remove_category(copy_config(config), 'Model'))


def test_changing_the_value_kind_in_the_archive_does_not_skip_the_svg_check(w, config):
    changed = copy_config(config)
    changed['cats']['Model']['attrs']['value']['kind'] = 'plain_text'
    import_unsafe_model(w, changed)


def test_a_category_defined_nowhere_is_still_rejected(w, config):
    members = zip_members(export_bytes(w, w.project))
    text = members['spec_items.csv'].decode().replace('Widget', 'Nowhere')
    members['spec_items.csv'] = text.encode()
    imported, messages = import_as_copy(w, w.project, make_zip(members))
    assert not SpecItem.objects.filter(project=imported, cat='Nowhere').exists()
    assert any('the category Nowhere is not defined in configs.json' in m for m in messages), messages


# ---------------------------------------------------------------------------
# Invalid configuration: a rejected import leaves nothing behind (no project, releases, applications, ValSets,
# items, users)
# ---------------------------------------------------------------------------

def rejected(w, archive_config):
    data = with_config(export_bytes(w, w.project), archive_config)
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    before = counts()
    response, messages = import_zip(w, data)
    assert response.status_code == 302
    assert counts() == before
    assert not Project.objects.filter(name='Proj').exists()
    assert len(messages) == 1, messages
    assert 'nothing was imported' in messages[0]
    return messages[0]


def test_malformed_json(w, config):
    assert 'invalid JSON' in rejected(w, '{"general": ')


def test_empty_file(w, config):
    assert 'invalid JSON' in rejected(w, '')


def test_not_an_object(w, config):
    assert 'the configuration must be a JSON object' in rejected(w, '[]')


def test_not_utf8(w, config):
    assert 'config.json' in rejected(w, b'\xff\xfe\x00{')


def test_unknown_setting_is_reported_with_its_path(w, config):
    bad = copy_config(config)
    bad['cats']['Service']['bogus'] = 1
    assert 'cats.Service.bogus: unknown setting' in rejected(w, bad)


def test_wrong_type_is_reported_with_its_path(w, config):
    bad = copy_config(config)
    bad['cats']['Requirement']['page_size'] = 'seven'
    assert 'cats.Requirement.page_size' in rejected(w, bad)


def test_duplicate_keys_are_reported(w, config):
    text = '{"general": %s, "general": {}, "cats": %s}' % (json.dumps(config['general']), json.dumps(config['cats']))
    message = rejected(w, text)
    assert 'general' in message
    assert 'more than once' in message


def test_missing_relationship_settings_are_reported(w, config):
    bad = copy_config(config)
    del bad['cats']['Packet']['links']
    assert 'cats.Packet.links: is required' in rejected(w, bad)


def test_several_problems_are_listed_and_counted(w, config):
    bad = copy_config(config)
    for cat in list(bad['cats'])[:15]:
        bad['cats'][cat]['page_size'] = 0
    message = rejected(w, bad)
    assert 'and 5 more problem(s)' in message
    assert message.count('page_size') == imports.IMPORT_MAX_CONFIG_ERRORS_SHOWN


def test_data_that_conflicts_with_the_configuration_rolls_everything_back(w, config):
    bad = copy_config(config)
    del bad['cats']['Requirement']['p_kind_choices']['STD']
    message = rejected(w, bad)                         # items, releases and the project exist when this is found
    assert 'cats.Requirement.p_kind_choices' in message
    assert 'STD' in message


def test_a_stored_link_the_configuration_does_not_allow_rolls_everything_back(w, config):
    bad = copy_config(config)
    bad['cats']['Packet']['links']['p_link']['targets'] = ['Packet']
    assert 'cats.Packet.links.p_link' in rejected(w, bad)


def test_the_stored_configuration_of_other_projects_is_untouched_by_a_rejection(w, config):
    other, _ = make_project('Other', owner=w.owner)
    bad = copy_config(config)
    del bad['cats']['Requirement']['p_kind_choices']['STD']
    rejected(w, bad)
    assert stored(other) == template_config()
    assert stored(Project.objects.get(name='Proj_original')) == config


def test_an_oversized_configuration_is_refused_when_the_archive_is_read(w, config):
    data = with_config(export_bytes(w, w.project), ' ' * (MAX_JSON_BYTES + 1))
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    before = counts()
    response, messages = import_zip(w, data)
    assert counts() == before
    assert len(messages) == 1
    assert 'config.json is larger than' in messages[0]


def test_an_unexpected_failure_while_storing_the_configuration_rolls_everything_back(w, config):
    data = export_bytes(w, w.project)
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    before = counts()
    with mock.patch('editor.imports.save_project_config', side_effect=RuntimeError('boom')):
        response, messages = import_zip(w, data)
    assert counts() == before
    assert messages == ['Unable to import project; nothing was imported (details in the server log)']


def test_a_failure_after_the_configuration_is_stored_rolls_it_back_too(w, config):
    data = export_bytes(w, w.project)
    Project.objects.filter(id=w.project.id).update(name='Proj_original')
    before = counts()
    real = imports.save_project_config

    def store_then_fail(project_id, body, token):
        real(project_id, body, token)
        raise RuntimeError('after the write')

    with mock.patch('editor.imports.save_project_config', side_effect=store_then_fail):
        import_zip(w, data)
    assert counts() == before
    assert not Project.objects.filter(name='Proj').exists()


# ---------------------------------------------------------------------------
# Archives written before the configuration existed (no config.json)
# ---------------------------------------------------------------------------

@pytest.fixture
def old_archive(w):
    """Archive without config.json of project Old, which becomes w.project."""
    w.project, _ = make_project('Old', owner=w.owner, cats=['Requirement', 'Service'])
    app = make_application(w.project, 'OldApp', cats=['Requirement'])
    make_item(w.project, 'Requirement', 'R', 'req', application=app, value='v', p_kind='STD')
    svc = make_item(w.project, 'Service', 'S', 'svc', title='Svc', value='Type')
    # Not listed in the project's cats: kept with the definitions which have data
    make_item(w.project, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc, p_kind='TC')
    # A row which the import rejects: its category must not be part of the filtered configuration
    make_item(w.project, 'ComIntCmd', 'C', 'cmd', title='rejected', status='XXX')
    return with_config(export_bytes(w, w.project), None)


def test_the_old_archive_has_no_configuration_member(old_archive):
    assert list(zip_members(old_archive)) == CSV_MEMBERS


def test_the_configuration_is_the_template_filtered_for_the_imported_data(w, old_archive):
    imported, messages = import_as_copy(w, w.project, old_archive)
    assert len(messages) == 1
    assert 'ComIntCmd:C:cmd' in messages[0]                  # the rejected row, as before
    expected = filter_template_for_data(load_template(), imported)
    assert stored(imported) == expected
    cats = stored(imported)['cats']
    assert sorted(cats) == ['Packet', 'Requirement', 'Service']
    assert 'ComIntCmd' not in cats                           # based on the data actually imported
    assert sorted(cats['Packet']['attrs']) == ['domain', 'name', 'owner', 'p_kind', 'p_link', 'title', 'val_set']
    assert cats['Requirement']['attrs'] == TEMPLATE['cats']['Requirement']['attrs']     # listed: all definitions


def test_the_derived_configuration_is_valid_for_the_imported_data(w, old_archive):
    imported, _ = import_as_copy(w, w.project, old_archive)
    assert validate_config(stored(imported), imported) == []
    assert 'temp_dir' not in stored(imported)['general']


def test_the_shared_filter_is_called_after_the_items_exist(w, old_archive):
    Project.objects.filter(id=w.project.id).update(name='Old_original')
    calls = []
    real = imports.filter_template_for_data

    def spy(template, project):
        calls.append((project.name, SpecItem.objects.filter(project=project).count()))
        return real(template, project)

    with mock.patch('editor.imports.filter_template_for_data', side_effect=spy):
        import_zip(w, old_archive)
    assert calls == [('Old', 3)]


def test_the_derived_configuration_is_not_shared_with_the_template_or_other_projects(w, old_archive):
    other, _ = make_project('Other', owner=w.owner)
    imported, _ = import_as_copy(w, w.project, old_archive)
    assert stored(other) == template_config()
    stored(imported)['cats']['Service']['name'] = 'changed in memory'
    assert load_template()['cats']['Service']['name'] != 'changed in memory'


def test_problems_of_the_derived_configuration_do_not_reject_the_archive(w, old_archive, caplog):
    # A stored kind the template does not offer (data from before this check existed)
    SpecItem.objects.filter(project=w.project, cat='Requirement').update(p_kind='NOPE')
    data = with_config(export_bytes(w, w.project), None)
    with caplog.at_level(logging.WARNING, logger='editor.imports'):
        imported, messages = import_as_copy(w, w.project, data)
    assert SpecItem.objects.get(project=imported, cat='Requirement').p_kind == 'NOPE'
    assert stored(imported) != {}
    logged = [record.getMessage() for record in caplog.records if record.name == 'editor.imports']
    assert 'cats.Requirement.p_kind_choices' in logged[0]


def test_an_empty_archive_configuration_member_is_not_an_old_archive(w, old_archive):
    data = with_config(old_archive, '{}')
    Project.objects.filter(id=w.project.id).update(name='Old_original')
    response, messages = import_zip(w, data)
    assert len(messages) == 1
    assert 'nothing was imported' in messages[0]
    assert not Project.objects.filter(name='Old').exists()


def test_extra_members_of_the_archive_are_still_ignored(w, old_archive):
    members = zip_members(old_archive)
    members['notes.txt'] = b'ignored'
    members['../evil.json'] = b'{}'
    imported, _ = import_as_copy(w, w.project, make_zip(members))
    assert imported is not None
