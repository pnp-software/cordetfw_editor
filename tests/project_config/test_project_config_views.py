"""Every read of the configuration is the configuration of the project of the request."""
import csv
import io
import json
import re
import zipfile
from pathlib import Path
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from editor import configs, convert, markdown
from editor.config_cleanup import copy_config, remove_attribute, remove_category
from editor.config_validation import validate_config
from editor.convert import get_tooltip
from editor.fields import OrderedJSONField
from editor.forms import ProjectForm
from editor.models import Application, Project, Release, SpecItem, ValSet
from editor.project_config import (get_project_config, get_request_config, load_template, new_project_config,
                                   resolve_config)
from editor.templatetags.ref_filters import get_short_desc
from editor.utilities import HIDDEN_VALUE_FIELDS, get_hidden_fields, make_temp_dir
from tests.factories import template_config
from tests.project_config.base import ALL_CATS, World, make_application, make_item, make_project, messages_of, refresh
from tests.project_config.test_project_config_access import project_config_queries

pytestmark = pytest.mark.django_db

PRODUCTION_DIR = Path(__file__).resolve().parents[2] / 'editor'
HIDDEN = ('rationale', 'remarks')


@pytest.fixture
def w(client):
    return World(client)


def configure(project, transform=None):
    """Store the template, changed by transform(config) (which mutates or returns a new configuration)."""
    config = template_config()
    if transform is not None:
        config = transform(config) or config
    assert validate_config(config, project) == []
    Project.objects.filter(id=project.id).update(config=config)     # update(): updated_at is not touched
    project.refresh_from_db()
    return config


def other_project(w, name='Other'):
    project, val_set = make_project(name, owner=w.owner, rw_users=[w.rw_user])
    make_application(project, name + 'App')
    return project, val_set


def service_list(w, project, val_set, **query):
    return w.client.get(w.list_url('Service', project=project, val_set=val_set), query)


def content(response):
    assert response.status_code == 200
    return response.content.decode()


def snapshot(project):
    """Everything of a project which hiding a field or category must leave unchanged."""
    return {
        'items': list(SpecItem.objects.filter(project=project).order_by('id').values()),
        'releases': list(Release.objects.order_by('id').values()),
        'applications': list(Application.objects.filter(project=project).order_by('id').values('id', 'name',
                                                                                                'cats', 'release_id')),
        'project_cats': Project.objects.get(id=project.id).cats,
    }


def exported_archive(w):
    w.login(w.owner)
    response = w.client.get(w.url('export_project', w.project.id))
    return zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))


# ---------------------------------------------------------------------------
# Acceptance criteria 1 and 10: the same category, different settings, in two projects
# ---------------------------------------------------------------------------

@pytest.fixture
def alpha_beta(w):
    """Service is 'Alpha Service' (page size 2, separator ';') in Proj and 'Beta Service' (page size 3) in project
    w.other; both have three Service items."""
    w.other, w.other_vs = other_project(w)

    def alpha(config):
        service = config['cats']['Service']
        service.update(name='Alpha Service', page_size=2)
        service['attrs']['title']['label'] = 'Alpha Title'
        config['general']['csv_sep'] = ';'

    def beta(config):
        service = config['cats']['Service']
        service.update(name='Beta Service', page_size=3)
        service['attrs']['title']['label'] = 'Beta Title'

    configure(w.project, alpha)
    configure(w.other, beta)
    for project in (w.project, w.other):
        for n in range(1, 4):
            make_item(project, 'Service', 'D', 'svc%d' % n, title='Title %d' % n, status='CNF')


def test_list_pages_use_the_settings_of_their_own_project(w, alpha_beta):
    first = service_list(w, w.project, w.default_val_set)
    second = service_list(w, w.other, w.other_vs)
    assert first.context['config']['name'] == 'Alpha Service'
    assert second.context['config']['name'] == 'Beta Service'
    assert len(first.context['page_items']) == 2       # page_size 2
    assert len(second.context['page_items']) == 3      # page_size 3
    assert first.context['pagination']['has_next']
    assert not second.context['pagination']['has_next']
    assert 'Alpha Service' in content(first)
    assert 'Beta Service' not in content(first)
    assert 'Beta Service' in content(second)
    assert 'Alpha Service' not in content(second)


def test_forms_use_the_labels_of_their_own_project(w, alpha_beta):
    first = w.client.get(w.add_url('Service')).context['form']
    second = w.client.get(w.url('add_spec_item', 'Service', w.other.id, 0, 'Sel_All', 0)).context['form']
    assert first.fields['title'].label == 'Alpha Title'
    assert second.fields['title'].label == 'Beta Title'
    assert w.client.get(w.add_url('Service')).context['title'] == 'Add Alpha Service'


def test_item_csv_uses_the_labels_and_separator_of_the_project(w, alpha_beta):
    first = w.client.get(w.url('export_spec_items', 'Service', w.project.id, 0, w.default_val_set.id, 'Sel_All', 0))
    second = w.client.get(w.url('export_spec_items', 'Service', w.other.id, 0, w.other_vs.id, 'Sel_All', 0))
    first_header = first.content.decode().splitlines()[0]
    second_header = second.content.decode().splitlines()[0]
    assert 'Alpha Title;' in first_header
    assert 'Beta Title' not in first_header
    assert 'Beta Title|' in second_header             # the template separator
    assert 'Alpha Title' not in second_header


def test_item_csv_import_expects_the_columns_of_the_project(w, alpha_beta):
    csv_text = w.client.get(w.url('export_spec_items', 'Service', w.project.id, 0, w.default_val_set.id,
                                  'Sel_All', 0)).content.decode()
    url = w.url('import_spec_items', 'Service', w.other.id, 0, w.other_vs.id, 'Sel_All')
    response = w.client.post(url, {'upload_file': SimpleUploadedFile('s.csv', csv_text.encode())})
    assert response.status_code == 302
    assert any('does not match the selected Service category' in m for m in messages_of(response))


def test_menus_come_from_the_configuration_of_each_project(w, alpha_beta):
    response = w.client.get(w.url('index'))
    names = {entry['project'].name: entry['project_configs']['Service']['name']
             for entry in response.context['list_of_projects']}
    assert names == {'Proj': 'Alpha Service', 'Other': 'Beta Service'}


def test_saving_one_configuration_does_not_change_the_other_project(w, alpha_beta):
    def shown():
        response = service_list(w, w.other, w.other_vs)
        return response.context['config'], [item.name for item in response.context['page_items']]
    before = shown()
    configure(w.project, lambda config: config['cats']['Service'].update(name='Gamma Service'))
    assert shown() == before
    assert 'Gamma Service' in content(service_list(w, w.project, w.default_val_set))


def test_a_new_project_uses_the_configuration_of_a_new_project(w, alpha_beta):
    fresh, val_set = other_project(w, 'Fresh')
    assert Project.objects.get(id=fresh.id).config == new_project_config()
    response = service_list(w, fresh, val_set)
    assert response.context['config']['name'] == load_template()['cats']['Service']['name']
    assert response.context['project_config'] == get_project_config(fresh)


def test_history_uses_the_configuration_of_the_project(w, alpha_beta):
    first = make_item(w.project, 'Service', 'H', 'hist')
    second = make_item(w.other, 'Service', 'H', 'hist')
    names = []
    for item in (first, second):
        url = w.url('list_spec_item_history', 'Service', item.project_id, 0, item.id, 'Sel_All')
        names.append(w.client.get(url).context['config']['name'])
    assert names == ['Alpha Service', 'Beta Service']


def test_a_new_request_sees_a_saved_change_at_once(w, alpha_beta):
    assert 'Alpha Service' in content(service_list(w, w.project, w.default_val_set))
    configure(w.project, lambda config: config['cats']['Service'].update(name='Renamed Service'))
    assert 'Renamed Service' in content(service_list(w, w.project, w.default_val_set))


def test_item_views_read_the_configuration_once_per_request(w, alpha_beta):
    item = SpecItem.objects.filter(project=w.project, cat='Service').first()
    urls = [w.list_url('Service', val_set=w.default_val_set), w.add_url('Service'),
            w.item_url('edit_spec_item', item), w.item_url('copy_spec_item', item),
            w.item_url('del_spec_item', item),
            w.url('list_spec_item_history', 'Service', w.project.id, 0, item.id, 'Sel_All'),
            w.url('export_spec_items', 'Service', w.project.id, 0, w.default_val_set.id, 'Sel_All', 0)]
    for url in urls:
        with CaptureQueriesContext(connection) as queries:
            assert w.client.get(url).status_code in (200, 302), url
            assert len(project_config_queries(queries)) == 1, url


def test_the_index_reads_each_project_once(w, alpha_beta):
    with CaptureQueriesContext(connection) as queries:
        w.client.get(w.url('index'))
    assert len(project_config_queries(queries)) == 2


# ---------------------------------------------------------------------------
# Acceptance criterion 2: a category which is not in the template needs no code
# ---------------------------------------------------------------------------

def add_widget(config):
    widget = copy_config(config['cats']['Service'])
    widget.update(name='Widget', abbr='Wdg', expand={'s_link': 'None', 'p_link': 'None'}, tracs=[])
    widget['page_size'] = 7
    config['cats']['Widget'] = widget


@pytest.fixture
def widget(w):
    """Category Widget, which the template does not have, in the configuration and the categories of Proj."""
    configure(w.project, add_widget)
    Project.objects.filter(id=w.project.id).update(cats=w.project.cats + ',Widget')
    w.project.refresh_from_db()


def test_the_menu_offers_the_new_category(w, widget):
    response = w.client.get(w.url('index'))
    menu = response.context['list_of_projects'][0]['project_configs']
    assert menu['Widget']['name'] == 'Widget'
    assert 'Manage Widgets' in content(response)


def test_an_item_can_be_added_listed_edited_copied_and_deleted(w, widget):
    add_url = w.add_url('Widget')
    payload = w.form_payload(add_url, domain='W', name='w1', title='First widget', value='v')
    response = w.client.post(add_url, payload)
    assert response.status_code == 302, getattr(response, 'context', None) and response.context['form'].errors
    item = SpecItem.objects.get(cat='Widget', name='w1')
    assert (item.project_id, item.status, item.title) == (w.project.id, 'NEW', 'First widget')

    listed = w.client.get(w.list_url('Widget'))
    assert listed.status_code == 200
    assert listed.context['config']['name'] == 'Widget'
    assert 'First widget' in content(listed)

    edit_url = w.item_url('edit_spec_item', item)
    response = w.client.post(edit_url, w.form_payload(edit_url, title='Edited widget'))
    assert response.status_code == 302
    assert refresh(item).title == 'Edited widget'

    copy_url = w.item_url('copy_spec_item', item)
    response = w.client.post(copy_url, w.form_payload(copy_url, name='w2'))
    assert response.status_code == 302
    assert SpecItem.objects.filter(cat='Widget').count() == 2

    delete_url = w.item_url('del_spec_item', item)
    assert w.client.post(delete_url).status_code == 302
    assert SpecItem.objects.filter(cat='Widget').count() == 1


def test_the_pages_of_the_new_category_use_its_settings(w, widget):
    for n in range(9):
        make_item(w.project, 'Widget', 'W', 'w%d' % n, title='t', status='CNF')
    listed = w.client.get(w.list_url('Widget'))
    assert len(listed.context['page_items']) == 7             # page_size of Widget
    assert w.client.get(w.list_url('Widget'), {'disp': 'disp_trac'}).status_code == 200
    csv_response = w.client.get(w.url('export_spec_items', 'Widget', w.project.id, 0, w.default_val_set.id,
                                      'Sel_All', 0))
    assert csv_response.status_code == 200
    assert 'Widget.csv' in csv_response['Content-Disposition']


def test_references_to_the_new_category_are_displayed_and_stored(w, widget):
    target = make_item(w.project, 'Widget', 'W', 'ref_target', title='Target')
    add_url = w.add_url('Service')
    payload = w.form_payload(add_url, domain='S', name='s1', title='Svc', value='v', desc='see #Widget:W:ref_target')
    response = w.client.post(add_url, payload)
    assert response.status_code == 302, response.context['form'].errors if response.status_code == 200 else ''
    service = SpecItem.objects.get(cat='Service', name='s1')
    assert service.desc == 'see #iref:%d' % target.id
    listed = content(w.client.get(w.list_url('Service')))
    assert 'W:ref_target' in listed
    assert 'Title: Target' in listed                      # the tooltip of the new category


def test_the_project_form_accepts_the_category_only_for_this_project(w, widget):
    other, _ = other_project(w)
    data = {'name': 'N', 'owner': str(w.owner.id), 'cats': 'Widget', 'description': 'd'}
    form = ProjectForm(w.project, data=data)
    assert form.is_valid(), form.errors
    assert 'Widget' in form.predefined_cats
    form = ProjectForm(other, data=data)
    assert not form.is_valid()
    assert 'cats' in form.errors


def test_the_new_category_is_not_visible_in_another_project(w, widget):
    other, other_vs = other_project(w)
    response = w.client.get(w.list_url('Widget', project=other, val_set=other_vs, application_id=0))
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Acceptance criterion 6: hidden fields, removed from the configuration or hidden by `"hidden": true`
# ---------------------------------------------------------------------------

def remove_attrs(config, cat, attrs):
    """The configuration without the definitions of the attributes `attrs` of `cat` (trash icon, config/remove)."""
    for attr in attrs:
        config = remove_attribute(config, cat, attr)
    return config


def mark_hidden(config, cat, attrs):
    """`config` with the attributes `attrs` of `cat` marked hidden (changed in place and returned)."""
    for attr in attrs:
        config['cats'][cat]['attrs'][attr]['hidden'] = True
    return config


def make_hidden_item(w, hide_attrs):
    item = make_item(w.project, 'Service', 'D', 'svc', title='Title', desc='Desc', value='Val',
                     rationale='keep me', remarks='keep me too', status='NEW')
    configure(w.project, lambda config: hide_attrs(config, 'Service', HIDDEN))
    return item


@pytest.fixture
def item(w, hide_attrs):
    """Service item with values in the fields HIDDEN, which the configuration of Proj then hides (hide_attrs: each
    way to hide attributes; the item pages treat a hidden attribute as a removed one whose values are kept)."""
    return make_hidden_item(w, hide_attrs)


@pytest.fixture
def marked_item(w):
    """Like item, with the fields hidden by `"hidden": true`, which keeps their definitions in the configuration."""
    return make_hidden_item(w, mark_hidden)


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_the_form_does_not_show_the_hidden_fields(w, item):
    form = w.client.get(w.item_url('edit_spec_item', item)).context['form']
    for attr in HIDDEN:
        assert type(form.fields[attr].widget).__name__ == 'HiddenInput'
    assert type(form.fields['title'].widget).__name__ == 'TextInput'
    hidden_fields = set(get_hidden_fields(get_project_config(w.project), 'Service'))
    assert set(HIDDEN) <= hidden_fields
    assert hidden_fields <= set(HIDDEN_VALUE_FIELDS)


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_the_list_does_not_show_the_hidden_values(w, item):
    listed = content(w.client.get(w.list_url('Service')))
    assert 'Title' in listed
    assert 'keep me' not in listed


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_editing_with_the_form_keeps_the_hidden_values(w, item):
    url = w.item_url('edit_spec_item', item)
    response = w.client.post(url, w.form_payload(url, title='Changed'))
    assert response.status_code == 302
    edited = refresh(item)
    assert (edited.title, edited.rationale, edited.remarks) == ('Changed', 'keep me', 'keep me too')


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_editing_with_a_post_which_lacks_the_hidden_fields_keeps_the_values(w, item):
    url = w.item_url('edit_spec_item', item)
    payload = {key: value for key, value in w.form_payload(url, title='Changed').items() if key not in HIDDEN}
    assert w.client.post(url, payload).status_code == 302
    edited = refresh(item)
    assert (edited.title, edited.rationale, edited.remarks) == ('Changed', 'keep me', 'keep me too')


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_a_posted_value_cannot_overwrite_a_hidden_value(w, item):
    url = w.item_url('edit_spec_item', item)
    payload = w.form_payload(url, title='Changed', rationale='forged', remarks='forged')
    assert w.client.post(url, payload).status_code == 302
    edited = refresh(item)
    assert (edited.rationale, edited.remarks) == ('keep me', 'keep me too')


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_editing_a_confirmed_item_keeps_the_hidden_values_in_both_versions(w, item):
    SpecItem.objects.filter(id=item.id).update(status='CNF')
    url = w.item_url('edit_spec_item', item)
    assert w.client.post(url, w.form_payload(url, title='New version')).status_code == 302
    current = refresh(item)
    assert (current.status, current.rationale) == ('MOD', 'keep me')
    assert (current.previous.status, current.previous.title, current.previous.rationale) == ('OBS', 'Title', 'keep me')


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_a_hidden_kind_and_numbers_survive_editing(w, item, hide_attrs):
    requirement = make_item(w.project, 'Requirement', 'R', 'req', title='T', value='v', p_kind='CNS', s_kind='TST',
                            n1=5, n2=6)
    configure(w.project, lambda config: hide_attrs(config, 'Requirement', ('p_kind', 's_kind')))
    url = w.item_url('edit_spec_item', requirement)
    payload = w.form_payload(url, title='Changed', p_kind='', s_kind='')
    assert w.client.post(url, payload).status_code == 302
    edited = refresh(requirement)
    assert (edited.title, edited.p_kind, edited.s_kind, edited.n1, edited.n2) == ('Changed', 'CNS', 'TST', 5, 6)


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_copy_and_split_carry_the_hidden_values_over(w, item):
    copy_url = w.item_url('copy_spec_item', item)
    assert w.client.post(copy_url, w.form_payload(copy_url, name='svc_copy')).status_code == 302
    copied = SpecItem.objects.get(cat='Service', name='svc_copy')
    assert (copied.rationale, copied.remarks) == ('keep me', 'keep me too')

    alternative = ValSet.objects.create(project=w.project, name='Alt', desc='alt')
    split_url = w.item_url('split_spec_item', item)
    payload = w.form_payload(split_url, val_set=alternative.id)
    response = w.client.post(split_url, payload)
    assert response.status_code == 302, getattr(response, 'context', None) and response.context['form'].errors
    split = SpecItem.objects.get(cat='Service', name='svc', val_set=alternative)
    assert (split.rationale, split.remarks) == ('keep me', 'keep me too')


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_a_new_item_gets_empty_values_for_the_hidden_fields(w, item):
    url = w.add_url('Service')
    payload = w.form_payload(url, domain='N', name='fresh', title='Fresh', value='v', rationale='forged')
    assert w.client.post(url, payload).status_code == 302
    assert SpecItem.objects.get(name='fresh').rationale == ''


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_item_csv_leaves_out_the_hidden_columns_and_import_keeps_the_values(w, item):
    export_url = w.url('export_spec_items', 'Service', w.project.id, 0, w.default_val_set.id, 'Sel_All', 0)
    text = w.client.get(export_url).content.decode()
    rows = list(csv.DictReader(io.StringIO(text), delimiter='|'))
    assert 'Rationale' not in rows[0]
    assert 'Remarks' not in rows[0]
    rows[0]['Title'] = 'Via CSV'
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), delimiter='|')
    writer.writeheader()
    writer.writerows(rows)
    url = w.url('import_spec_items', 'Service', w.project.id, 0, w.default_val_set.id, 'Sel_All')
    response = w.client.post(url, {'upload_file': SimpleUploadedFile('s.csv', out.getvalue().encode())})
    assert response.status_code == 302
    imported = refresh(item)
    assert (imported.title, imported.rationale, imported.remarks) == ('Via CSV', 'keep me', 'keep me too')


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_the_project_export_contains_the_hidden_values(w, item, hide_attrs):
    archive = exported_archive(w)
    rows = list(csv.DictReader(io.StringIO(archive.read('spec_items.csv').decode())))
    service = [row for row in rows if row['name'] == 'svc'][0]
    assert (service['rationale'], service['remarks']) == ('keep me', 'keep me too')
    archived = json.loads(archive.read('config.json'))['cats']['Service']
    if hide_attrs is mark_hidden:
        # the archive keeps the hidden definitions and their columns, so the import restores them
        for attr in HIDDEN:
            assert archived['attrs'][attr]['hidden'] is True
        assert archived['disp_def'] == template_config()['cats']['Service']['disp_def']
    else:
        assert 'rationale' not in archived['attrs']


@pytest.mark.parametrize('hide_attrs', [remove_attrs, mark_hidden], ids=['removed', 'hidden_setting'])
def test_restoring_the_field_shows_the_values_again(w, item):
    configure(w.project)
    form = w.client.get(w.item_url('edit_spec_item', item)).context['form']
    assert form['rationale'].value() == 'keep me'
    assert type(form.fields['rationale'].widget).__name__ == 'Textarea'
    assert 'keep me' in content(w.client.get(w.list_url('Service')))


def test_the_stored_configuration_keeps_the_definitions_and_the_references(w, marked_item):
    stored, template = Project.objects.get(id=w.project.id).config, template_config()
    for attr in HIDDEN:
        assert {k: v for k, v in stored['cats']['Service']['attrs'][attr].items() if k != 'hidden'} == \
               template['cats']['Service']['attrs'][attr]
    for key in ('disp_def', 'disp_short', 'disp_trac', 'short_desc', 'validators', 'ext_attrs'):
        assert stored['cats']['Service'][key] == template['cats']['Service'][key]
    assert 'rationale' not in get_project_config(w.project)['cats']['Service']['attrs']
    assert resolve_config(stored)['cats']['Service']['attrs']['rationale']['hidden'] is True


def test_showing_the_field_again_restores_its_column_and_values(w, marked_item):
    stored = Project.objects.get(id=w.project.id).config
    for attr in HIDDEN:
        del stored['cats']['Service']['attrs'][attr]['hidden']
    assert stored == template_config()               # nothing of the definition was lost
    Project.objects.filter(id=w.project.id).update(config=stored)
    response = w.client.get(w.list_url('Service'))
    assert 'keep me' in content(response)
    assert ['title', 'desc', 'rationale', 'remarks', 'implementation'] in \
           [column.get('attrs') for column in response.context['disp_list']]
    form = w.client.get(w.item_url('edit_spec_item', marked_item)).context['form']
    assert form['rationale'].value() == 'keep me'
    assert type(form.fields['rationale'].widget).__name__ == 'Textarea'


def test_the_list_leaves_out_a_column_of_hidden_attributes_only(w, marked_item):
    configure(w.project, lambda config: mark_hidden(config, 'Service', ('value', 'rationale', 'remarks')))
    response = w.client.get(w.list_url('Service'))
    assert 'Type' not in [column['header'] for column in response.context['disp_list']]
    assert ['title', 'desc', 'implementation'] in [column.get('attrs') for column in response.context['disp_list']]
    assert 'Val</td>' not in content(response)
    assert 'value' not in response.context['find_replace_fields']


def test_find_and_replace_does_not_change_a_hidden_field(w, marked_item):
    assert 'rationale' not in w.client.get(w.list_url('Service')).context['find_replace_fields']
    response = w.client.post(w.list_url('Service'), {'field': 'rationale', 'find': 'keep', 'replace': 'lost'},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert response.status_code == 400
    assert refresh(marked_item).rationale == 'keep me'


def test_short_descriptions_and_tooltips_leave_out_hidden_attributes(w, marked_item):
    configure(w.project, lambda config: mark_hidden(config, 'Service', ('title',)))
    config = get_project_config(w.project)
    assert get_short_desc(marked_item, config) == 'Val'
    assert 'Title' not in get_tooltip(config, marked_item, 'href_tip')
    assert 'Val' in get_tooltip(config, marked_item, 'href_tip')


def test_one_request_reads_the_shown_configuration(w, marked_item):
    request = RequestFactory().get('/')
    config = get_request_config(request, w.project)
    assert 'rationale' not in config['cats']['Service']['attrs']
    assert get_request_config(request, w.project) is config


# ---------------------------------------------------------------------------
# Acceptance criteria 7 and 8: hide and restore a category
# ---------------------------------------------------------------------------

@pytest.fixture
def service(w):
    """Confirmed Service svc; a Packet (w.packet) which links to it and refers to it in its text, a VerLink to it
    (w.verlink) and a Service with two versions. The configuration is the template (w.full)."""
    service = make_item(w.project, 'Service', 'D', 'svc', title='Service title', value='Kind', status='CNF')
    w.packet = make_item(w.project, 'Packet', 'D', 'pkt', title='Packet title', p_link=service, p_kind='TM',
                         status='CNF', desc='refers to #iref:%d' % service.id, value='v', t1='a', t2='b')
    ver_item = make_item(w.project, 'VerItem', 'D', 'vi', status='CNF')
    w.verlink = make_item(w.project, 'VerLink', 'D', 'vl', p_link=ver_item, s_link=service, status='CNF')
    edited = make_item(w.project, 'Service', 'D', 'svc2', title='v1', status='OBS')
    make_item(w.project, 'Service', 'D', 'svc2', title='v2', status='MOD', previous=edited)
    w.full = configure(w.project)
    return service


def hide_service(w):
    return configure(w.project, lambda config: remove_category(config, 'Service'))


def test_hiding_changes_nothing_but_the_configuration(w, service):
    before = snapshot(w.project)
    hide_service(w)
    assert snapshot(w.project) == before


def test_a_hidden_category_has_no_menu_entry_and_no_pages(w, service):
    hide_service(w)
    menu = w.client.get(w.url('index')).context['list_of_projects'][0]['project_configs']
    assert 'Service' not in menu
    assert 'Packet' in menu
    assert w.client.get(w.list_url('Service')).status_code == 404
    assert w.client.get(w.add_url('Service')).status_code == 404
    assert w.client.get(w.item_url('edit_spec_item', service)).status_code == 404
    assert w.client.get(w.url('list_spec_item_history', 'Service', w.project.id, 0, service.id,
                              'Sel_All')).status_code == 404
    assert w.client.get(w.url('export_spec_items', 'Service', w.project.id, 0, w.default_val_set.id,
                              'Sel_All', 0)).status_code == 404


def test_references_to_the_hidden_category_show_the_plain_identifier(w, service):
    hide_service(w)
    listed = w.client.get(w.list_url('Packet'))
    assert listed.status_code == 200
    text = listed.content.decode()
    assert 'D:svc' in text
    assert '/editor/Service/' not in text           # no link to a page which does not exist
    assert 'ERROR:' not in text


def test_references_in_text_show_the_plain_identifier(w, service):
    hide_service(w)
    shown = convert.convert_db_to_display('see #iref:%d' % service.id, None, get_project_config(w.project),
                                          w.project.id)
    assert shown == 'see D:svc'


@pytest.mark.parametrize('disp', ['disp_def', 'disp_short', 'disp_trac'])
@pytest.mark.parametrize('cat', ['Packet', 'VerLink', 'DataItem'])
def test_a_hidden_category_does_not_break_other_pages(w, service, cat, disp):
    hide_service(w)
    assert w.client.get(w.list_url(cat), {'disp': disp}).status_code == 200


def test_an_item_which_links_to_a_hidden_category_can_still_be_edited(w, service):
    hide_service(w)
    url = w.item_url('edit_spec_item', w.packet)
    form = w.client.get(url).context['form']
    assert form['p_link'].value() == service.id
    response = w.client.post(url, w.form_payload(url, title='Edited packet'))
    assert response.status_code == 302, getattr(response, 'context', None) and response.context['form'].errors
    packet = refresh(w.packet)
    assert (packet.p_link_id, packet.title, packet.status) == (service.id, 'Edited packet', 'MOD')


def test_relationships_assignments_releases_and_history_work_while_hidden(w, service):
    hide_service(w)
    assert SpecItem.objects.get(id=w.verlink.id).s_link_id == service.id
    history = w.client.get(w.url('list_spec_item_history', 'Packet', w.project.id, 0, w.packet.id, 'Sel_All'))
    assert history.status_code == 200
    w.login(w.owner)
    releases_before = Release.objects.count()
    response = w.client.post(w.url('make_project_release', w.project.id), {'description': 'Release'})
    assert response.status_code == 302
    # the project release and one release for each application
    assert Release.objects.count() == releases_before + 1 + Application.objects.filter(project=w.project).count()
    assert SpecItem.objects.get(id=service.id).status == 'CNF'
    assert Application.objects.get(id=w.application.id).cats == w.application.cats
    assert Project.objects.get(id=w.project.id).cats == ','.join(ALL_CATS)


def test_the_project_export_contains_the_items_of_the_hidden_category(w, service):
    hide_service(w)
    archive = exported_archive(w)
    rows = list(csv.DictReader(io.StringIO(archive.read('spec_items.csv').decode())))
    assert sorted(row['name'] for row in rows if row['cat'] == 'Service') == ['svc', 'svc2', 'svc2']
    assert 'Service' not in json.loads(archive.read('config.json'))['cats']


def test_restoring_the_definition_shows_the_items_again(w, service):
    hide_service(w)
    configure(w.project, lambda config: config.update(cats=w.full['cats']))
    menu = w.client.get(w.url('index')).context['list_of_projects'][0]['project_configs']
    assert 'Service' in menu
    assert 'Service title' in content(w.client.get(w.list_url('Service')))
    packets = w.client.get(w.list_url('Packet')).content.decode()
    assert '/editor/Service/' in packets               # the link is back, with its tooltip
    assert 'Title: Service title' in packets


def test_hiding_a_category_in_one_project_leaves_the_other_one_alone(w, service):
    other, other_vs = other_project(w)
    make_item(other, 'Service', 'O', 'osvc', title='Other service')
    hide_service(w)
    assert 'Other service' in content(w.client.get(w.list_url('Service', project=other, val_set=other_vs)))


def test_a_category_in_the_project_cats_but_not_in_the_configuration_is_skipped_everywhere(w, service):
    hide_service(w)
    assert 'Service' in w.project.cats.split(',')
    breadcrumb = w.client.get(w.list_url('Packet')).context['breadcrumb']
    names = [entry['list_as'] for group in (breadcrumb['active'], breadcrumb['rest']) for entry in group]
    assert 'Service' not in names
    assert names


# ---------------------------------------------------------------------------
# A reference never needs the display settings of its target: without them it is the plain identifier
# ---------------------------------------------------------------------------

@pytest.fixture
def target(w):
    return make_item(w.project, 'Service', 'D', 'svc', title='T', value='v', status='CNF')


def display(w, target, config):
    return convert.convert_db_to_display('#iref:%d' % target.id, None, config, w.project.id)


def test_a_category_without_short_descriptions_is_a_link_without_tooltip(w, target):
    config = template_config()
    config['cats']['Service']['short_desc'] = {}
    shown = display(w, target, config)
    assert 'href="/editor/Service/' in shown
    assert 'title=""' in shown
    assert '>D:svc</a>' in shown


def test_a_tooltip_attribute_which_is_not_defined_is_skipped(w, target):
    config = template_config()
    del config['cats']['Service']['attrs']['value']
    assert 'Title: T&#13;' in display(w, target, config)
    assert 'Type' not in display(w, target, config)


def test_a_category_which_is_not_defined_is_the_plain_identifier(w, target):
    config = template_config()
    del config['cats']['Service']
    assert display(w, target, config) == 'D:svc'


def test_labels_in_tooltips_are_escaped(w, target):
    config = template_config()
    config['cats']['Service']['attrs']['title']['label'] = 'A<b>"x"'
    shown = display(w, target, config)
    assert '<b>' not in shown
    assert 'A&lt;b&gt;&quot;x&quot;' in shown


# ---------------------------------------------------------------------------
# The order of categories, attributes and choices is part of the configuration (menus, columns, defaults)
# ---------------------------------------------------------------------------

def first_key_last(mapping):
    keys = list(mapping)
    return {key: mapping[key] for key in keys[1:] + keys[:1]}


def test_the_stored_order_is_the_order_in_menus_and_choices(w):
    def reorder(config):
        config['cats'] = first_key_last(config['cats'])
        service = config['cats']['Service']
        service['attrs'] = first_key_last(service['attrs'])
        requirement = config['cats']['Requirement']
        requirement['p_kind_choices'] = first_key_last(requirement['p_kind_choices'])
    config = configure(w.project, reorder)
    stored = Project.objects.get(id=w.project.id).config
    assert list(stored['cats']) == list(config['cats'])
    assert list(stored['cats']['Service']['attrs']) == list(config['cats']['Service']['attrs'])
    menu = w.client.get(w.url('index')).context['list_of_projects'][0]['project_configs']
    assert list(menu) == [cat for cat in config['cats'] if cat in ALL_CATS]
    choices = w.client.get(w.add_url('Requirement')).context['form'].fields['p_kind'].choices
    assert [value for value, _ in choices] == list(config['cats']['Requirement']['p_kind_choices'])


def test_the_column_is_text_on_mysql_and_native_json_elsewhere():
    field = Project._meta.get_field('config')
    assert isinstance(field, OrderedJSONField)

    class Connection:
        data_types = {'JSONField': 'json'}
        data_type_check_constraints = {}

        class ops:
            quote_name = staticmethod(lambda name: '`%s`' % name)

        def __init__(self, vendor):
            self.vendor = vendor

    assert field.db_type(Connection('mysql')) == 'longtext'
    assert field.db_check(Connection('mysql')) == 'JSON_VALID(`config`)'
    assert field.db_type(Connection('sqlite')) == 'json'
    assert field.db_check(Connection('sqlite')) is None


def test_the_default_is_an_empty_object():
    assert Project._meta.get_field('config').get_default() == {}


# ---------------------------------------------------------------------------
# temp_dir is a server setting: it is read from the Django settings, never from a project configuration
# ---------------------------------------------------------------------------

def export_temp_dir(w):
    """The directory in which the export of the project creates its temporary directory."""
    w.login(w.project.owner)
    with mock.patch('editor.views.make_temp_dir', wraps=make_temp_dir) as spy:
        response = w.client.get(w.url('export_project', w.project.id))
        b''.join(response.streaming_content)
    return spy.call_args.args[0]


def test_the_temp_directory_comes_from_the_settings(w, isolated_temp_dir):
    assert export_temp_dir(w) == str(isolated_temp_dir)


def test_a_temp_dir_inside_a_stored_configuration_is_ignored(w, isolated_temp_dir):
    stored = template_config()
    stored['general']['temp_dir'] = '/somewhere/else'
    Project.objects.filter(id=w.project.id).update(config=stored)
    assert export_temp_dir(w) == str(isolated_temp_dir)


def test_the_default_is_tmp():
    from cordetfw_editor import settings as production_settings
    assert hasattr(production_settings, 'TEMP_DIR')


# ---------------------------------------------------------------------------
# Acceptance criterion 10: nothing global is left
# ---------------------------------------------------------------------------

def production_sources():
    for path in sorted(PRODUCTION_DIR.rglob('*.py')):
        if 'migrations' in path.parts:
            continue
        yield path, path.read_text()


def test_the_global_dictionaries_and_adapters_are_gone():
    for module in (configs, convert, markdown):
        assert not hasattr(module, 'configs'), module.__name__


def test_no_production_module_reads_the_template_except_project_config():
    readers = [path.name for path, text in production_sources() if re.search(r"open\([^)]*configs\.json", text)]
    assert readers == ['project_config.py']


def test_no_production_code_indexes_a_global_configs_dictionary():
    pattern = re.compile(r"(?<![A-Za-z_])configs\[|import configs\b|configs\.configs")
    offenders = [path.name for path, text in production_sources() if pattern.search(text)]
    assert offenders == []


def test_no_category_name_is_hard_coded_in_production_code_or_templates():
    names = '|'.join(load_template()['cats'])
    pattern = re.compile(r"""['"](%s)['"]""" % names)
    paths = [path for path, _ in production_sources()] + sorted((PRODUCTION_DIR / 'templates').glob('*.html'))
    offenders = []
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line) and not line.lstrip().startswith(('#', '*', '"""')):
                offenders.append('%s:%d' % (path.name, number))
    assert offenders == []


def test_every_view_which_needs_a_configuration_reads_the_request_configuration():
    text = (PRODUCTION_DIR / 'views.py').read_text()
    assert 'editor.configs import configs' not in text
    assert text.count('get_request_config(request, project)') >= 12
