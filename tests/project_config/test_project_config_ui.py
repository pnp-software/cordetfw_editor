"""The script's behaviour (dialogs, tooltips, reload, conflicts, layouts) is not automated here; it is checked manually
in a browser. The guards at the end check its source."""
import json
import re
from pathlib import Path
from unittest import mock

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from editor import config_validation
from editor.config_cleanup import copy_config, remove_attribute, remove_category
from editor.config_store import config_token
from editor.config_validation import validate_config
from editor.models import Project, SpecItem
from editor.project_config import load_template, new_project_config
from tests.project_config.base import make_item
from tests.project_config.test_project_config_endpoints import (LOGIN_URL, NON_OWNERS, OWNER_ONLY, EndpointWorld,
                                                                changed_config, refusal, writes)

pytestmark = pytest.mark.django_db

STATIC_DIR = Path(__file__).resolve().parents[2] / 'editor' / 'static'
SCRIPT = STATIC_DIR / 'project_config.js'
UI_POST_ENDPOINTS = ('project_config_preview', 'project_config_remove')
HOSTILE = '<script>alert(1)</script>'
HOSTILE_ESCAPED = '&lt;script&gt;alert(1)&lt;/script&gt;'


@pytest.fixture
def w(client):
    return EndpointWorld(client)


@pytest.fixture
def script():
    return SCRIPT.read_text(encoding='utf-8')


def preview(w, client, body, **headers):
    return w.post_json(client, 'project_config_preview', body, **headers)


def remove(w, client, config, cat, attr=None):
    payload = {'config': config, 'cat': cat}
    if attr is not None:
        payload['attr'] = attr
    return w.post_json(client, 'project_config_remove', payload)


def call_ui(w, client, name):
    """A request which would succeed for the owner."""
    if name == 'project_config_preview':
        return preview(w, client, new_project_config())
    return remove(w, client, new_project_config(), 'Packet')


def page_content(response):
    assert response.status_code == 200
    return response.content.decode()


# ------------------------------------------------------------------ the tab and the page

def index_links(w, user):
    return w.curl('project_config') in w.client_for(user).get(w.url('index')).content.decode()


def test_only_the_owner_sees_the_configuration_tab(w):
    assert index_links(w, w.owner)
    for who in NON_OWNERS:
        assert not index_links(w, getattr(w, who)), who


def test_the_page_is_the_editor_with_the_owner_only_endpoints(w):
    content = page_content(w.owner_client.get(w.curl('project_config')))
    for name in ('project_config_reload', 'project_config_validate', 'project_config_save',
                 'project_config_upload', 'project_config_preview', 'project_config_remove',
                 'project_config_download'):
        assert w.curl(name) in content
    for element in ('id="tab-forms"', 'id="tab-json"', 'id="tab-preview"', 'id="config-json"',
                    'id="configConfirmModal"', 'id="config-save"', 'id="config-reload"',
                    'id="config-upload-file"', 'name="csrfmiddlewaretoken"', 'project_config.js'):
        assert element in content
    assert 'Configuration of ' + w.project.name in content


def test_the_page_embeds_the_token_the_configuration_and_the_supported_settings(w):
    response = w.owner_client.get(w.curl('project_config'))
    content = page_content(response)
    assert 'data-token="%s"' % config_token(new_project_config()) in content
    # data-config and data-meta are the JSON texts of the context, autoescaped
    assert 'data-config="{&quot;' in content
    assert 'data-meta="{&quot;' in content
    assert json.loads(response.context['initial_config']) == new_project_config()
    meta = json.loads(response.context['editor_meta'])
    assert meta['validators']['link_conditional_reference']['link'] == 'link'
    assert meta['allowed_kinds']['p_link'] == ['spec_item_ref']
    assert meta['external_cats'] == ['FCP', 'Model']               # the template categories with ext_attrs


def test_the_breadcrumb_is_not_confused_by_the_configuration(w):
    # base_generic.html reads `config.name`: the page must not define a context variable called `config`
    response = w.owner_client.get(w.curl('project_config'))
    assert 'config' not in response.context
    assert 'aria-current="page"' in page_content(response)


def test_hostile_names_never_become_markup_in_the_page(w):
    config = new_project_config()
    config['cats']['Packet']['name'] = HOSTILE
    config['cats']['Packet']['attrs']['title']['label'] = '"><img src=x onerror=alert(1)>'
    w.store(config)
    content = page_content(w.owner_client.get(w.curl('project_config')))
    assert HOSTILE not in content
    assert '<img src=x' not in content
    assert HOSTILE_ESCAPED in content


def test_the_page_needs_the_owner(w):
    for who in NON_OWNERS:
        assert refusal(w.client_for(getattr(w, who)).get(w.curl('project_config'))) == OWNER_ONLY, who
    assert Client().get(w.curl('project_config')).status_code == 302


# ------------------------------------------------------------------ access to preview and remove

@pytest.mark.parametrize('name', UI_POST_ENDPOINTS)
def test_the_owner_may_use_the_new_endpoints(w, name):
    assert call_ui(w, w.owner_client, name).status_code == 200


@pytest.mark.parametrize('name', UI_POST_ENDPOINTS)
def test_anonymous_users_are_redirected(w, name):
    response = call_ui(w, Client(), name)
    assert response.status_code == 302
    assert response['Location'].startswith(LOGIN_URL)


@pytest.mark.parametrize('name', UI_POST_ENDPOINTS)
@pytest.mark.parametrize('who', NON_OWNERS)
def test_nobody_but_the_owner_has_access(w, who, name):
    client = w.client_for(getattr(w, who))
    before = w.stored()
    with CaptureQueriesContext(connection) as queries:
        response = call_ui(w, client, name)
    assert refusal(response) == OWNER_ONLY
    assert w.stored() == before
    assert writes(queries.captured_queries) == []
    assert b'"config"' not in response.content
    assert b'"html"' not in response.content


@pytest.mark.parametrize('name', UI_POST_ENDPOINTS)
def test_get_is_not_allowed_for_any_logged_in_user(w, name):
    assert w.owner_client.get(w.curl(name)).status_code == 405
    assert w.client_for(w.rw_user).get(w.curl(name)).status_code == 405


def test_csrf_is_enforced(w):
    client = w.client_for(w.owner, enforce_csrf_checks=True)
    for name in UI_POST_ENDPOINTS:
        assert call_ui(w, client, name).status_code == 403, name
    token_client = w.client_for(w.owner, enforce_csrf_checks=True)
    token_client.get(w.curl('project_config'))                      # sets the cookie
    cookie = token_client.cookies['csrftoken'].value
    response = preview(w, token_client, new_project_config(), **{'X-CSRFToken': cookie})
    assert response.status_code == 200


def test_an_unknown_project_is_an_error(w):
    url = w.url('project_config_preview', w.project.id + 1000)
    with pytest.raises(Project.DoesNotExist):
        w.owner_client.post(url, '{}', content_type='application/json')


# ------------------------------------------------------------------ preview

def test_preview_renders_the_unsaved_configuration_and_stores_nothing(w):
    config = changed_config()
    config['cats']['Packet']['name'] = 'Unsaved Packet Name'
    config['cats']['Packet']['attrs']['title']['label'] = 'Unsaved title label'
    before = w.stored()
    with CaptureQueriesContext(connection) as queries:
        response = preview(w, w.owner_client, config)
    assert response.status_code == 200
    body = response.json()
    assert body['valid']
    assert body['errors'] == []
    assert 'Unsaved Packet Name' in body['html']
    assert 'Unsaved title label' in body['html']
    assert '7 items per page' in body['html']
    assert writes(queries.captured_queries) == []
    assert w.stored() == before


def test_preview_shows_menus_forms_layouts_and_relationships_of_the_configuration(w):
    config = new_project_config()
    config['cats']['Packet']['p_kind_choices'] = {'TC': 'Telecommand label', 'TM': 'Telemetry label'}
    html = preview(w, w.owner_client, config).json()['html']
    for text in ('Project menu', 'Application menu', 'Telecommand label (TC)', 'Default list', 'Short list',
                 'Traceability list', 'Short description', 'Relationships', 'items of Service',
                 'Verification Link'):
        assert text in html


def test_preview_categories_are_collapsible_and_the_menus_are_not(w, script):
    config = new_project_config()
    html = preview(w, w.owner_client, config).json()['html']
    assert re.search(r'<div id="preview-cat-(\d+)" class="accordion-collapse collapse"\s+'
                     r'aria-labelledby="preview-heading-\1" data-cat="Packet">', html)
    # one collapsible section per category, nothing else
    assert html.count('class="accordion-collapse collapse"') == len(config['cats'])
    assert html.count('data-bs-toggle="collapse"') == len(config['cats'])
    menus = html[:html.index('<div class="accordion">')]
    assert 'Project menu: manage item' in menus
    assert 'Application menu: manage item' in menus
    assert 'setupPreviewCategories(target);' in script
    assert "const open = typeof previewOpen[cat] === 'boolean' ? previewOpen[cat] : cat === state.selected;" in script
    assert 'setSectionOpen(body, open || !hasBootstrap);' in script


def test_preview_of_a_new_category_needs_no_code(w):
    config = new_project_config()
    config['cats']['Widget'] = copy_config(config['cats']['InfoItem'])
    config['cats']['Widget'].update(name='Widget Thing', abbr='Wdgt')
    response = preview(w, w.owner_client, config)
    assert response.status_code == 200
    assert 'Widget Thing' in response.json()['html']


def test_a_hidden_category_with_data_is_reported_not_hidden_from_the_data(w):
    make_item(w.project, 'InfoItem', 'D', 'I1', title='t')
    make_item(w.project, 'InfoItem', 'D', 'I2', title='t')
    config = remove_category(new_project_config(), 'InfoItem')
    html = preview(w, w.owner_client, config).json()['html']
    assert 'InfoItem (2 items)' in html
    assert SpecItem.objects.filter(project=w.project, cat='InfoItem').count() == 2


def test_invalid_configurations_get_the_errors_with_their_paths_and_no_preview(w):
    config = new_project_config()
    config['cats']['Packet']['page_size'] = 0
    config['cats']['Service']['level'] = 'nowhere'
    response = preview(w, w.owner_client, config)
    assert response.status_code == 422
    body = response.json()
    assert not body['valid']
    assert {e['path'] for e in body['errors']} == {'cats.Packet.page_size', 'cats.Service.level'}
    assert 'html' not in body


def test_stored_data_problems_surface_in_the_preview(w):
    make_item(w.project, 'Requirement', 'D', 'R1', value='t', p_kind='STD', s_kind='TST')
    config = new_project_config()
    del config['cats']['Requirement']['p_kind_choices']['STD']
    body = preview(w, w.owner_client, config).json()
    assert [e['path'] for e in body['errors']] == ['cats.Requirement.p_kind_choices']


def test_preview_uses_the_shared_validator_with_the_project(w):
    with mock.patch.object(config_validation, 'validate_config', wraps=validate_config) as spy:
        preview(w, w.owner_client, new_project_config())
    assert spy.call_args.args[1].id == w.project.id


@pytest.mark.parametrize('body', ['   ', '[]', 'null', '1', '"x"', '{', '{"general": 1, "cats": []}',
                                  '{"cats": {"A": 5}}', '{"general": {}, "cats": {"A": {"attrs": []}}}', b'\xff\xfe',
                                  '{"a": NaN}'])
def test_malformed_bodies_never_cause_a_server_error(w, body):
    response = preview(w, w.owner_client, body)
    assert response.status_code == 422
    assert response.json()['errors']


def test_wrong_content_type_and_oversize(w):
    response = w.owner_client.post(w.curl('project_config_preview'), 'x=1',
                                   content_type='application/x-www-form-urlencoded')
    assert response.status_code == 415
    huge = '{"x": "%s"}' % ('a' * (config_validation.MAX_JSON_BYTES + 10))
    assert preview(w, w.owner_client, huge).status_code == 413


def test_hostile_text_is_escaped_in_the_preview(w):
    config = new_project_config()
    packet = config['cats']['Packet']
    packet['name'] = HOSTILE
    packet['abbr'] = 'Pk'
    packet['attrs']['title']['label'] = '"><img src=x onerror=alert(1)>'
    packet['p_kind_choices'] = {'TC': '<b>bold</b>', 'TM': "' onmouseover='alert(2)"}
    packet['disp_def'][0]['header'] = '<svg onload=alert(3)>'
    packet['expand']['s_label'] = '<i>label</i>'
    body = preview(w, w.owner_client, config).json()
    assert body['valid'], body
    html = body['html']
    for raw in (HOSTILE, '<img src=x', '<b>bold</b>', '<svg onload', '<i>label</i>', "' onmouseover='alert(2)"):
        assert raw not in html
    assert HOSTILE_ESCAPED in html
    assert '&lt;b&gt;bold&lt;/b&gt;' in html


def test_errors_with_submitted_text_stay_plain_text_in_json(w):
    config = new_project_config()
    config['cats'][HOSTILE] = config['cats']['Packet']
    response = preview(w, w.owner_client, config)
    body = response.json()
    assert not body['valid']
    assert any(HOSTILE in e['path'] or HOSTILE in e['message'] for e in body['errors'])
    assert response['Content-Type'] == 'application/json'


# ------------------------------------------------------------------ remove

def test_removing_a_category_equals_the_shared_cleanup(w):
    config = new_project_config()
    response = remove(w, w.owner_client, config, 'VerLink')
    assert response.status_code == 200
    body = response.json()
    assert body['config'] == remove_category(config, 'VerLink')
    assert body['errors'] == []
    assert 'VerLink' not in body['config']['cats']
    for cat, definition in body['config']['cats'].items():
        assert 'VerLink' not in [t['trac_cat'] for t in definition['tracs']], cat


def test_removing_a_field_equals_the_shared_cleanup_and_updates_the_references(w):
    config = new_project_config()
    assert 'remarks' in json.dumps(config['cats']['Requirement']['disp_def'])
    body = remove(w, w.owner_client, config, 'Requirement', 'remarks').json()
    assert body['config'] == remove_attribute(config, 'Requirement', 'remarks')
    assert body['errors'] == []
    cleaned = body['config']['cats']['Requirement']
    assert 'remarks' not in cleaned['attrs']
    assert 'remarks' not in json.dumps({k: v for k, v in cleaned.items() if k != 'attrs'})
    assert body['config']['cats']['Packet'] == config['cats']['Packet']      # others untouched


def test_every_category_of_the_template_can_be_removed_with_a_valid_result(w):
    config = new_project_config()
    for cat in config['cats']:
        assert remove(w, w.owner_client, config, cat).json()['errors'] == [], cat


def test_the_result_is_checked_by_the_validator_and_reported_with_paths(w):
    body = remove(w, w.owner_client, new_project_config(), 'Requirement', 'domain').json()
    assert [e['path'] for e in body['errors']] == ['cats.Requirement.attrs.domain']


def test_removing_stores_nothing_and_never_touches_data(w):
    w.store(changed_config())
    item = make_item(w.project, 'Requirement', 'D', 'R1', value='text', remarks='keep me', p_kind='STD', s_kind='TST')
    before = (w.stored(), list(SpecItem.objects.values()))
    with CaptureQueriesContext(connection) as queries:
        remove(w, w.owner_client, new_project_config(), 'Requirement')
        remove(w, w.owner_client, new_project_config(), 'Requirement', 'remarks')
    assert writes(queries.captured_queries) == []
    assert (w.stored(), list(SpecItem.objects.values())) == before
    item.refresh_from_db()
    assert item.remarks == 'keep me'


def test_the_cleaned_result_can_be_saved_and_data_stays_exported(w):
    # The flow of the dialog: delete, then Save the result with the token the editor was based on.
    make_item(w.project, 'InfoItem', 'D', 'I1', title='kept')
    config = remove(w, w.owner_client, new_project_config(), 'InfoItem').json()['config']
    response = w.save(w.owner_client, config)
    assert response.status_code == 200, response.content
    assert 'InfoItem' not in w.stored()['cats']
    assert SpecItem.objects.get(project=w.project, cat='InfoItem').title == 'kept'
    assert w.owner_client.get(w.url('export_project', w.project.id)).status_code == 200


def test_manual_json_and_uploads_cannot_bypass_the_removal_rules(w):
    # Deleting VerLink by hand leaves dangling references, which every entry point refuses
    config = new_project_config()
    del config['cats']['VerLink']
    errors = {
        'json': w.post_json(w.owner_client, 'project_config_validate', config).json()['errors'],
        'upload': w.upload(w.owner_client, json.dumps(config).encode()).json()['errors'],
        'save': w.save(w.owner_client, config).json()['errors'],
        'preview': preview(w, w.owner_client, config).json()['errors'],
    }
    assert errors['json']
    for entry, found in errors.items():
        assert found == errors['json'], entry
    assert 'unknown category "VerLink"' in [e['message'] for e in errors['json']]
    assert w.stored() == new_project_config()


def test_malformed_requests_are_refused_without_a_server_error(w):
    config = new_project_config()
    cases = {
        'not json': ('{', 400),
        'list': ('[]', 422),
        'no config': ({'cat': 'Packet'}, 422),
        'config not an object': ({'config': [], 'cat': 'Packet'}, 422),
        'cats not an object': ({'config': {'cats': 1}, 'cat': 'Packet'}, 422),
        'no cat': ({'config': config}, 422),
        'cat not a text': ({'config': config, 'cat': 5}, 422),
        'unknown cat': ({'config': config, 'cat': 'Nope'}, 422),
        'unknown attr': ({'config': config, 'cat': 'Packet', 'attr': 'zzz'}, 422),
        'attr not a text': ({'config': config, 'cat': 'Packet', 'attr': ['t1']}, 422),
        'definition not an object': ({'config': {'cats': {'A': 1}}, 'cat': 'A', 'attr': 't1'}, 422),
    }
    for label, (body, status) in cases.items():
        response = w.post_json(w.owner_client, 'project_config_remove', body)
        assert response.status_code == status, label
        assert response.json()['errors'], label
    assert w.post_json(w.owner_client, 'project_config_remove',
                       {'config': {'cats': {'A': 1}}, 'cat': 'A'}).status_code == 200


def test_wrong_content_type(w):
    response = w.owner_client.post(w.curl('project_config_remove'), 'x', content_type='text/plain')
    assert response.status_code == 415


def test_the_template_and_the_stored_configuration_are_not_modified(w):
    template = load_template()
    remove(w, w.owner_client, new_project_config(), 'Packet', 'remarks')
    assert load_template() == template
    assert w.stored() == new_project_config()


# ------------------------------------------------------------------ one validator for forms, JSON editor and uploads

def validator_calls(action):
    with mock.patch.object(config_validation, 'validate_config', wraps=validate_config) as spy, \
            mock.patch('editor.views.validate_config', wraps=validate_config) as view_spy:
        action()
    return spy.call_args_list + view_spy.call_args_list


def test_every_ui_entry_point_validates_with_the_project(w):
    config = new_project_config()
    actions = {
        'forms: remove': lambda: remove(w, w.owner_client, config, 'Packet'),
        'forms: preview': lambda: preview(w, w.owner_client, config),
        'json: validate': lambda: w.post_json(w.owner_client, 'project_config_validate', config),
        'json: save': lambda: w.save(w.owner_client, config),
        'upload': lambda: w.upload(w.owner_client, json.dumps(config).encode()),
    }
    for entry, action in actions.items():
        calls = validator_calls(action)
        assert calls, entry
        assert all(call.args[1].id == w.project.id for call in calls), entry


def test_the_same_invalid_configuration_gives_the_same_errors_everywhere(w):
    config = new_project_config()
    config['cats']['Packet']['attrs']['t1']['kind'] = 'nonsense'
    config['cats']['Service']['links'] = {'p_link': {'targets': ['Nope']}}
    expected = validate_config(config, w.project)
    assert len(expected) == 2
    found = {
        'validate': w.post_json(w.owner_client, 'project_config_validate', config).json()['errors'],
        'preview': preview(w, w.owner_client, config).json()['errors'],
        'upload': w.upload(w.owner_client, json.dumps(config).encode()).json()['errors'],
        'save': w.save(w.owner_client, config).json()['errors'],
    }
    for entry, errors in found.items():
        assert errors == expected, entry
    assert w.stored() == new_project_config()


# ------------------------------------------------------------------ guards for the script

def test_the_script_is_served_with_the_site_static_files(w):
    assert SCRIPT.exists()
    assert '/static/project_config.js' in page_content(w.owner_client.get(w.curl('project_config')))


def test_texts_reach_the_page_as_text_not_as_markup(script):
    assert script.count('.innerHTML') == 1                # the server-escaped preview fragment
    assert 'target.innerHTML = result.data.html' in script
    for forbidden in ('document.write', 'insertAdjacentHTML', 'outerHTML', 'eval(', 'new Function', '.html('):
        assert forbidden not in script


def test_hide_and_delete_icons_have_tooltips_for_hover_and_focus(script):
    assert "'data-bs-toggle': 'tooltip'" in script
    assert "'data-bs-trigger': 'hover focus'" in script
    assert "new bootstrap.Tooltip(el, {trigger: 'hover focus'})" in script


def test_the_confirmations_name_the_definition_and_promise_that_data_is_kept(script):
    text = re.sub(r"'\s*\+\s*'", '', script)            # the texts as the dialog shows them
    assert text.count('Its saved data will not be deleted') == 2      # category and field
    assert 'the category is no longer shown in the menus, lists and forms of this project' in text
    assert 'it is no longer shown in its forms, lists and CSV exports' in text
    assert "confirmDialog(title, body, 'Delete', 'bi-trash-fill', function () {" in script
    assert 'its settings and the references to it have to be set up again' in text
    assert 'its settings, table columns and short descriptions have to be set up again' in text
    assert 'To keep them, hide the field instead' in text


def test_hiding_a_field_only_sets_its_hidden_setting_without_a_request_or_a_confirmation(script):
    start = script.index('function toggleHidden(')
    toggle = script[start:script.index('// ----', start)]
    assert 'attr.hidden = true;' in toggle
    assert 'delete attr.hidden;' in toggle
    for absent in ('confirmDialog', 'postJson', 'urls.'):
        assert absent not in toggle
    assert "'Required: items are identified by ' + attrId + ', so it cannot be ' + what" in script


def test_general_settings_are_a_collapsed_section_and_the_category_list_is_shown_whole(w):
    page = page_content(w.owner_client.get(w.curl('project_config')))
    assert '<div class="accordion mb-3" id="general-section">' in page
    assert '<div id="general-body" class="accordion-collapse collapse" aria-labelledby="general-heading">' in page
    assert 'id="general-settings"' in page
    # no height limit: no scrolling inside the list
    assert '<ul class="list-group mb-2" id="category-list"></ul>' in page
    assert 'category-list' not in (STATIC_DIR / 'style.css').read_text(encoding='utf-8')


def test_layouts_are_tables_with_column_tools_and_ordered_attributes(script):
    assert "h('table', {class: 'table table-bordered table-sm align-top mb-0'}" in script
    for text in ("'Move column ' + name + ' left'", "'Move column ' + name + ' right'", "'Remove column ' + name",
                 "'Add column'", "'Add traceability column'",
                 "'Move ' + text + (vertical ? ' up' : ' left')", "'Move ' + text + (vertical ? ' down' : ' right')"):
        assert text in script
    # the attributes of a column are edited in the cell, in order (the JSON list)
    assert re.search(r"attrListEditor\(path \+ '\.attrs', column, function \(\) \{\s*return column;\s*\}, 'attrs', "
                     r"attrIds, def, true\)", script)


def test_reload_and_upload_warn_before_discarding_changes(script):
    assert 'Discard unsaved changes?' in script
    assert 'Replace the editor contents?' in script
    assert 'beforeunload' in script


def test_a_conflict_keeps_the_local_work_and_blocks_saving_until_reload(script):
    assert 'status === 409' in script
    assert 'state.conflict = true' in script
    assert 'Download my changes' in script
    assert "$('config-save').disabled = state.busy || state.conflict" in script


def test_the_script_uses_the_endpoints_of_the_page_and_the_csrf_token(script):
    for name in ('reloadUrl', 'validateUrl', 'saveUrl', 'uploadUrl', 'previewUrl', 'removeUrl'):
        assert 'app.dataset.' + name in script
    assert 'JSON.parse(app.dataset.config)' in script
    assert 'JSON.parse(app.dataset.meta)' in script
    assert "'X-CSRFToken': csrfToken()" in script
    assert 'document.cookie' in script
    assert "'X-Config-Token': state.token" in script


def test_a_redirect_is_reported_and_not_followed(script):
    # A logged out user and a user who is no longer the owner are redirected (to the login page, to the index)
    assert "redirect: 'manual'" in script
    assert "if (response.type === 'opaqueredirect' || response.redirected) {" in script
    assert 'You are no longer logged in, or no longer the owner of this project.' in script
