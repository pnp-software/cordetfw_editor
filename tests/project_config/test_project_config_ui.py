"""Server side of the configuration editor page and static guards for its script. The script's behaviour (dialogs,
tooltips, reload, conflicts, layouts) is not automated here; it is checked manually in a browser."""
import copy
import json
import re
from pathlib import Path
from unittest import mock

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from editor import config_validation, config_views
from editor.config_cleanup import remove_attribute, remove_category
from editor.config_store import config_token
from editor.config_validation import validate_config
from editor.models import SpecItem
from editor.project_config import load_template
from tests.project_config.test_project_config_endpoints import EndpointCase, writes

SCRIPT = Path(config_views.__file__).resolve().parent / 'static' / 'project_config.js'
UI_POST_ENDPOINTS = ('project_config_preview', 'project_config_remove')
HOSTILE = '<script>alert(1)</script>'
HOSTILE_ESCAPED = '&lt;script&gt;alert(1)&lt;/script&gt;'


class UiCase(EndpointCase):
    def preview(self, client, body, **kwargs):
        return self.post_json(client, 'project_config_preview', body, **kwargs)

    def remove(self, client, config, cat, attr=None, **kwargs):
        payload = {'config': config, 'cat': cat}
        if attr is not None:
            payload['attr'] = attr
        return self.post_json(client, 'project_config_remove', payload, **kwargs)

    def valid_body(self):
        return self.valid_config()

    def call_ui(self, client, name):
        """A request which would succeed for the owner."""
        if name == 'project_config_preview':
            return self.preview(client, self.valid_config())
        return self.remove(client, self.valid_config(), 'Packet')


class TabAndPageTests(UiCase):
    def index_links(self, user):
        content = self.client_for(user).get(reverse('index')).content.decode()
        return reverse('project_config', args=[self.project.id]) in content

    def test_only_the_owner_sees_the_configuration_tab(self):
        self.assertTrue(self.index_links(self.owner))
        for who, user in {'RW member': self.rw_user, 'RO member': self.ro_user, 'staff, not the owner': self.staff,
                          'owner of another project': self.other_owner}.items():
            with self.subTest(user=who):
                self.assertFalse(self.index_links(user))

    def test_the_page_is_the_editor_with_the_owner_only_endpoints(self):
        response = self.owner_client.get(self.curl('project_config'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        for name in ('project_config_reload', 'project_config_validate', 'project_config_save',
                     'project_config_upload', 'project_config_preview', 'project_config_remove',
                     'project_config_download'):
            self.assertIn(self.curl(name), content)
        for element in ('id="tab-forms"', 'id="tab-json"', 'id="tab-preview"', 'id="config-json"',
                        'id="configConfirmModal"', 'id="config-save"', 'id="config-reload"',
                        'id="config-upload-file"', 'name="csrfmiddlewaretoken"', 'project_config.js'):
            self.assertIn(element, content)
        self.assertIn('Configuration of ' + self.project.name, content)

    def test_the_page_embeds_the_token_the_configuration_and_the_supported_settings(self):
        content = self.owner_client.get(self.curl('project_config')).content.decode()
        self.assertIn('data-token="%s"' % config_token({}), content)
        embedded = json.loads(re.search(r'<script id="project-config-initial"[^>]*>(.*?)</script>', content, re.S).group(1))
        self.assertEqual(embedded, self.valid_config())
        meta = json.loads(re.search(r'<script id="project-config-meta"[^>]*>(.*?)</script>', content, re.S).group(1))
        self.assertEqual(meta['validators']['link_conditional_reference']['link'], 'link')
        self.assertEqual(meta['allowed_kinds']['p_link'], ['spec_item_ref'])
        self.assertEqual(sorted(meta['external_cats']), ['fcp', 'model'])      # lower case, as in editor.ext_cats

    def test_the_breadcrumb_is_not_confused_by_the_configuration(self):
        # base_generic.html reads `config.name`: the page must not define a context variable called `config`
        response = self.owner_client.get(self.curl('project_config'))
        self.assertNotIn('config', response.context)
        self.assertContains(response, 'aria-current="page"')

    def test_hostile_names_never_become_markup_in_the_page(self):
        config = self.valid_config()
        config['cats']['Packet']['name'] = HOSTILE
        config['cats']['Packet']['attrs']['title']['label'] = '"><img src=x onerror=alert(1)>'
        self.store(config)
        content = self.owner_client.get(self.curl('project_config')).content.decode()
        self.assertNotIn(HOSTILE, content)
        self.assertNotIn('<img src=x', content)
        self.assertIn('\\u003Cscript\\u003Ealert(1)\\u003C/script\\u003E', content)

    def test_the_page_needs_the_owner(self):
        for user in (self.rw_user, self.ro_user, self.staff, self.other_owner):
            self.assertEqual(self.client_for(user).get(self.curl('project_config')).status_code, 403)
        self.assertEqual(Client().get(self.curl('project_config')).status_code, 302)


class UiEndpointAccessTests(UiCase):
    def test_the_owner_may_use_the_new_endpoints(self):
        for name in UI_POST_ENDPOINTS:
            with self.subTest(endpoint=name):
                self.assertEqual(self.call_ui(self.owner_client, name).status_code, 200)

    def test_anonymous_users_are_redirected(self):
        for name in UI_POST_ENDPOINTS:
            with self.subTest(endpoint=name):
                response = self.call_ui(Client(), name)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith('/editor/login/'))

    def test_nobody_but_the_owner_has_access(self):
        users = {'RO member': self.ro_user, 'RW member': self.rw_user, 'staff, not the owner': self.staff,
                 'owner of another project': self.other_owner}
        for who, user in users.items():
            client = self.client_for(user)
            for name in UI_POST_ENDPOINTS:
                with self.subTest(user=who, endpoint=name):
                    before = self.stored()
                    with CaptureQueriesContext(connection) as queries:
                        response = self.call_ui(client, name)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(self.stored(), before)
                    self.assertEqual(writes(queries.captured_queries), [])
                    self.assertNotIn(b'"config"', response.content)
                    self.assertNotIn(b'"html"', response.content)

    def test_get_is_not_allowed_and_ownership_decides_first(self):
        for name in UI_POST_ENDPOINTS:
            self.assertEqual(self.owner_client.get(self.curl(name)).status_code, 405)
            self.assertEqual(self.client_for(self.rw_user).get(self.curl(name)).status_code, 403)

    def test_csrf_is_enforced(self):
        client = self.client_for(self.owner, enforce_csrf_checks=True)
        for name in UI_POST_ENDPOINTS:
            with self.subTest(endpoint=name):
                self.assertEqual(self.call_ui(client, name).status_code, 403)
        token_client = self.client_for(self.owner, enforce_csrf_checks=True)
        token_client.get(self.curl('project_config'))                  # sets the cookie
        cookie = token_client.cookies['csrftoken'].value
        response = self.preview(token_client, self.valid_config(), **{'X-CSRFToken': cookie})
        self.assertEqual(response.status_code, 200)

    def test_unknown_project_is_refused_like_a_foreign_one(self):
        url = reverse('project_config_preview', args=[self.project.id + 1000])
        self.assertEqual(self.owner_client.post(url, '{}', content_type='application/json').status_code, 403)


class PreviewTests(UiCase):
    def test_preview_renders_the_unsaved_configuration_and_stores_nothing(self):
        config = self.changed_config()
        config['cats']['Packet']['name'] = 'Unsaved Packet Name'
        config['cats']['Packet']['attrs']['title']['label'] = 'Unsaved title label'
        before = self.stored()
        with CaptureQueriesContext(connection) as queries:
            response = self.preview(self.owner_client, config)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['valid'])
        self.assertEqual(body['errors'], [])
        self.assertIn('Unsaved Packet Name', body['html'])
        self.assertIn('Unsaved title label', body['html'])
        self.assertIn('7 items per page', body['html'])
        self.assertEqual(writes(queries.captured_queries), [])
        self.assertEqual(self.stored(), before)

    def test_preview_shows_menus_forms_layouts_and_relationships_of_the_configuration(self):
        config = self.valid_config()
        config['cats']['Packet']['p_kind_choices'] = {'TC': 'Telecommand label', 'TM': 'Telemetry label'}
        html = self.preview(self.owner_client, config).json()['html']
        for text in ('Project menu', 'Application menu', 'Telecommand label (TC)', 'Default list', 'Short list',
                     'Traceability list', 'Short description', 'Relationships', 'items of Service',
                     'Verification Link'):
            self.assertIn(text, html)

    def test_preview_categories_are_collapsible_and_the_menus_are_not(self):
        config = self.valid_config()
        html = self.preview(self.owner_client, config).json()['html']
        self.assertIn('<details class="card mb-3 config-section config-preview-category" data-cat="Packet">', html)
        self.assertEqual(html.count('<details '), len(config['cats']))          # one per category, nothing else
        menus = html[:html.index('<details ')]
        self.assertIn('Project menu: manage item', menus)
        self.assertIn('Application menu: manage item', menus)
        script = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('setupPreviewCategories(target);', script)
        self.assertIn("details.open = previewOpen.has(cat) ? previewOpen.get(cat) : cat === state.selected;", script)

    def test_preview_of_a_new_category_needs_no_code(self):
        config = self.valid_config()
        config['cats']['Widget'] = copy.deepcopy(config['cats']['InfoItem'])
        config['cats']['Widget'].update(name='Widget Thing', abbr='Wdgt')
        response = self.preview(self.owner_client, config)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Widget Thing', response.json()['html'])

    def test_a_hidden_category_with_data_is_reported_not_hidden_from_the_data(self):
        self.make_item(self.project, 'InfoItem', 'D', 'I1', title='t')
        self.make_item(self.project, 'InfoItem', 'D', 'I2', title='t')
        config = remove_category(self.valid_config(), 'InfoItem')
        html = self.preview(self.owner_client, config).json()['html']
        self.assertIn('InfoItem (2 items)', html)
        self.assertEqual(SpecItem.objects.filter(project=self.project, cat='InfoItem').count(), 2)

    def test_invalid_configurations_get_the_errors_with_their_paths_and_no_preview(self):
        config = self.valid_config()
        config['cats']['Packet']['page_size'] = 0
        config['cats']['Service']['level'] = 'nowhere'
        response = self.preview(self.owner_client, config)
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertFalse(body['valid'])
        self.assertEqual({e['path'] for e in body['errors']}, {'cats.Packet.page_size', 'cats.Service.level'})
        self.assertNotIn('html', body)

    def test_stored_data_problems_surface_in_the_preview(self):
        self.make_item(self.project, 'Requirement', 'D', 'R1', value='t', p_kind='STD', s_kind='TST')
        config = self.valid_config()
        del config['cats']['Requirement']['p_kind_choices']['STD']
        body = self.preview(self.owner_client, config).json()
        self.assertEqual([e['path'] for e in body['errors']], ['cats.Requirement.p_kind_choices'])

    def test_preview_uses_the_shared_validator_with_the_project(self):
        with mock.patch.object(config_validation, 'validate_config', wraps=validate_config) as spy:
            self.preview(self.owner_client, self.valid_config())
        self.assertEqual(spy.call_args.args[1].id, self.project.id)

    def test_malformed_bodies_never_cause_a_server_error(self):
        bodies = ['   ', '[]', 'null', '1', '"x"', '{', '{"general": 1, "cats": []}', '{"cats": {"A": 5}}',
                  '{"general": {}, "cats": {"A": {"attrs": []}}}', b'\xff\xfe', '{"a": NaN}']
        for body in bodies:
            with self.subTest(body=body):
                response = self.preview(self.owner_client, body)
                self.assertIn(response.status_code, (422,))
                self.assertTrue(response.json()['errors'])

    def test_wrong_content_type_and_oversize(self):
        response = self.owner_client.post(self.curl('project_config_preview'), 'x=1',
                                          content_type='application/x-www-form-urlencoded')
        self.assertEqual(response.status_code, 415)
        huge = '{"x": "%s"}' % ('a' * (config_validation.MAX_JSON_BYTES + 10))
        self.assertEqual(self.preview(self.owner_client, huge).status_code, 413)

    def test_hostile_text_is_escaped_in_the_preview(self):
        config = self.valid_config()
        packet = config['cats']['Packet']
        packet['name'] = HOSTILE
        packet['abbr'] = 'Pk'
        packet['attrs']['title']['label'] = '"><img src=x onerror=alert(1)>'
        packet['p_kind_choices'] = {'TC': '<b>bold</b>', 'TM': "' onmouseover='alert(2)"}
        packet['disp_def'][0]['header'] = '<svg onload=alert(3)>'
        packet['expand']['s_label'] = '<i>label</i>'
        body = self.preview(self.owner_client, config).json()
        self.assertTrue(body['valid'], body)
        html = body['html']
        for raw in (HOSTILE, '<img src=x', '<b>bold</b>', '<svg onload', '<i>label</i>', "' onmouseover='alert(2)"):
            self.assertNotIn(raw, html)
        self.assertIn(HOSTILE_ESCAPED, html)
        self.assertIn('&lt;b&gt;bold&lt;/b&gt;', html)

    def test_errors_with_submitted_text_stay_plain_text_in_json(self):
        config = self.valid_config()
        config['cats'][HOSTILE] = config['cats']['Packet']
        body = self.preview(self.owner_client, config).json()
        self.assertFalse(body['valid'])
        self.assertTrue(any(HOSTILE in e['path'] or HOSTILE in e['message'] for e in body['errors']))
        self.assertEqual(self.preview(self.owner_client, config)['Content-Type'], 'application/json')


class RemoveTests(UiCase):
    def test_removing_a_category_equals_the_shared_cleanup(self):
        config = self.valid_config()
        response = self.remove(self.owner_client, config, 'VerLink')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['config'], remove_category(config, 'VerLink'))
        self.assertEqual(body['errors'], [])
        self.assertNotIn('VerLink', body['config']['cats'])
        for cat, definition in body['config']['cats'].items():
            self.assertNotIn('VerLink', [t['trac_cat'] for t in definition['tracs']], cat)

    def test_removing_a_field_equals_the_shared_cleanup_and_updates_the_references(self):
        config = self.valid_config()
        self.assertIn('remarks', json.dumps(config['cats']['Requirement']['disp_def']))
        body = self.remove(self.owner_client, config, 'Requirement', 'remarks').json()
        self.assertEqual(body['config'], remove_attribute(config, 'Requirement', 'remarks'))
        self.assertEqual(body['errors'], [])
        cleaned = body['config']['cats']['Requirement']
        self.assertNotIn('remarks', cleaned['attrs'])
        self.assertNotIn('remarks', json.dumps({k: v for k, v in cleaned.items() if k != 'attrs'}))
        self.assertEqual(body['config']['cats']['Packet'], config['cats']['Packet'])      # others untouched

    def test_every_category_of_the_template_can_be_removed_with_a_valid_result(self):
        config = self.valid_config()
        for cat in config['cats']:
            with self.subTest(cat=cat):
                body = self.remove(self.owner_client, config, cat).json()
                self.assertEqual(body['errors'], [])

    def test_the_result_is_checked_by_the_validator_and_reported_with_paths(self):
        config = self.valid_config()
        body = self.remove(self.owner_client, config, 'Requirement', 'domain').json()
        self.assertEqual([e['path'] for e in body['errors']], ['cats.Requirement.attrs.domain'])

    def test_removing_stores_nothing_and_never_touches_data(self):
        self.store(self.changed_config())
        item = self.make_item(self.project, 'Requirement', 'D', 'R1', value='text', remarks='keep me',
                              p_kind='STD', s_kind='TST')
        before = (self.stored(), list(SpecItem.objects.values()))
        with CaptureQueriesContext(connection) as queries:
            self.remove(self.owner_client, self.valid_config(), 'Requirement')
            self.remove(self.owner_client, self.valid_config(), 'Requirement', 'remarks')
        self.assertEqual(writes(queries.captured_queries), [])
        self.assertEqual((self.stored(), list(SpecItem.objects.values())), before)
        item.refresh_from_db()
        self.assertEqual(item.remarks, 'keep me')

    def test_the_cleaned_result_can_be_saved_and_data_stays_exported(self):
        # The flow of the dialog: delete, then Save the result with the token the editor was based on.
        self.make_item(self.project, 'InfoItem', 'D', 'I1', title='kept')
        config = self.remove(self.owner_client, self.valid_config(), 'InfoItem').json()['config']
        response = self.save(self.owner_client, config)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('InfoItem', self.stored()['cats'])
        self.assertEqual(SpecItem.objects.get(project=self.project, cat='InfoItem').title, 'kept')
        export = self.owner_client.get(reverse('export_project', args=[self.project.id]))
        self.assertEqual(export.status_code, 200)

    def test_manual_json_and_uploads_cannot_bypass_the_removal_rules(self):
        # Deleting VerLink by hand leaves dangling references, which every entry point refuses
        config = self.valid_config()
        del config['cats']['VerLink']
        errors = {}
        errors['json'] = self.post_json(self.owner_client, 'project_config_validate', config).json()['errors']
        errors['upload'] = self.upload(self.owner_client, json.dumps(config).encode()).json()['errors']
        errors['save'] = self.save(self.owner_client, config).json()['errors']
        errors['preview'] = self.preview(self.owner_client, config).json()['errors']
        self.assertTrue(errors['json'])
        for entry, found in errors.items():
            with self.subTest(entry=entry):
                self.assertEqual(found, errors['json'])
        self.assertIn('unknown category "VerLink"', [e['message'] for e in errors['json']])
        self.assertEqual(self.stored(), {})

    def test_malformed_requests_are_refused_without_a_server_error(self):
        config = self.valid_config()
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
            with self.subTest(case=label):
                response = self.post_json(self.owner_client, 'project_config_remove', body)
                self.assertEqual(response.status_code, status)
                self.assertTrue(response.json()['errors'])
        self.assertEqual(self.post_json(self.owner_client, 'project_config_remove', {'config': {'cats': {'A': 1}},
                                                                                 'cat': 'A'}).status_code, 200)

    def test_wrong_content_type(self):
        response = self.owner_client.post(self.curl('project_config_remove'), 'x', content_type='text/plain')
        self.assertEqual(response.status_code, 415)

    def test_the_template_and_the_stored_configuration_are_not_modified(self):
        template = copy.deepcopy(load_template())
        self.remove(self.owner_client, self.valid_config(), 'Packet', 'remarks')
        self.assertEqual(load_template(), template)


class SharedValidatorIntegrationTests(UiCase):
    """The three ways the UI produces a configuration (forms, JSON editor, uploaded file) use the same validator."""

    def calls(self, action):
        with mock.patch.object(config_validation, 'validate_config', wraps=validate_config) as spy, \
                mock.patch.object(config_views, 'validate_config', wraps=validate_config) as view_spy:
            action()
        return spy.call_args_list + view_spy.call_args_list

    def test_every_ui_entry_point_validates_with_the_project(self):
        config = self.valid_config()
        actions = {
            'forms: remove': lambda: self.remove(self.owner_client, config, 'Packet'),
            'forms: preview': lambda: self.preview(self.owner_client, config),
            'json: validate': lambda: self.post_json(self.owner_client, 'project_config_validate', config),
            'json: save': lambda: self.save(self.owner_client, config),
            'upload': lambda: self.upload(self.owner_client, json.dumps(config).encode()),
        }
        for entry, action in actions.items():
            with self.subTest(entry=entry):
                calls = self.calls(action)
                self.assertTrue(calls)
                self.assertTrue(all(call.args[1].id == self.project.id for call in calls))

    def test_the_same_invalid_configuration_gives_the_same_errors_everywhere(self):
        config = self.valid_config()
        config['cats']['Packet']['attrs']['t1']['kind'] = 'nonsense'
        config['cats']['Service']['links'] = {'p_link': {'targets': ['Nope']}}
        expected = [e.as_dict() for e in validate_config(config, self.project)]
        self.assertEqual(len(expected), 2)
        found = {
            'validate': self.post_json(self.owner_client, 'project_config_validate', config).json()['errors'],
            'preview': self.preview(self.owner_client, config).json()['errors'],
            'upload': self.upload(self.owner_client, json.dumps(config).encode()).json()['errors'],
            'save': self.save(self.owner_client, config).json()['errors'],
        }
        for entry, errors in found.items():
            with self.subTest(entry=entry):
                self.assertEqual(errors, expected)
        self.assertEqual(self.stored(), {})


class ScriptGuardTests(UiCase):
    def setUp(self):
        super().setUp()
        self.script = SCRIPT.read_text(encoding='utf-8')

    def test_the_script_is_served_with_the_site_static_files(self):
        self.assertTrue(SCRIPT.exists())
        self.assertIn('/static/project_config.js', self.owner_client.get(self.curl('project_config')).content.decode())

    def test_texts_reach_the_page_as_text_not_as_markup(self):
        self.assertEqual(self.script.count('.innerHTML'), 1)        # the server-escaped preview fragment
        self.assertIn('target.innerHTML = result.data.html', self.script)
        for forbidden in ('document.write', 'insertAdjacentHTML', 'outerHTML', 'eval(', 'new Function', '.html('):
            self.assertNotIn(forbidden, self.script)

    def test_hide_and_delete_icons_have_tooltips_for_hover_and_focus(self):
        self.assertIn("'data-bs-toggle': 'tooltip'", self.script)
        self.assertIn("'data-bs-trigger': 'hover focus'", self.script)
        self.assertIn("new bootstrap.Tooltip(el, {trigger: 'hover focus'})", self.script)

    def test_the_confirmations_name_the_definition_and_promise_that_data_is_kept(self):
        text = re.sub(r"'\s*\+\s*'", '', self.script)            # the texts as the dialog shows them
        self.assertEqual(text.count('Its saved data will not be deleted'), 2)    # category and field
        self.assertIn('the category is no longer shown in the menus, lists and forms of this project', text)
        self.assertIn('it is no longer shown in its forms, lists and CSV exports', text)
        self.assertIn("confirmDialog(title, body, 'Delete', 'bi-trash-fill')", self.script)
        self.assertIn('its settings and the references to it have to be set up again', text)
        self.assertIn('its settings, table columns and short descriptions have to be set up again', text)
        self.assertIn('To keep them, hide the field instead', text)

    def test_hiding_a_field_only_sets_its_hidden_setting_without_a_request_or_a_confirmation(self):
        toggle = self.script[self.script.index('function toggleHidden('):self.script.index('// ----', self.script.index('function toggleHidden('))]
        self.assertIn('attr.hidden = true;', toggle)
        self.assertIn('delete attr.hidden;', toggle)
        for absent in ('confirmDialog', 'postJson', 'urls.'):
            self.assertNotIn(absent, toggle)
        self.assertIn("'Required: items are identified by ' + attrId + ', so it cannot be ' + what", self.script)

    def test_general_settings_are_a_collapsed_section_and_the_category_list_is_shown_whole(self):
        page = self.owner_client.get(self.curl('project_config')).content.decode()
        self.assertIn('<details class="config-section card mb-3" id="general-section" data-section="general">', page)
        self.assertIn('id="general-settings"', page)
        css = (SCRIPT.parent / 'style.css').read_text(encoding='utf-8')
        self.assertNotIn('.config-cat-list', css)                    # no height limit: no scrolling inside the list

    def test_layouts_are_tables_with_column_tools_and_ordered_attributes(self):
        self.assertIn("class: 'table table-bordered table-sm align-top mb-0 config-layout'", self.script)
        for text in ("'Move column ' + name + ' left'", "'Move column ' + name + ' right'", "'Remove column ' + name",
                     "'Add column'", "'Add traceability column'",
                     "'Move ' + text + (vertical ? ' up' : ' left')", "'Move ' + text + (vertical ? ' down' : ' right')"):
            self.assertIn(text, self.script)
        # the attributes of a column are edited in the cell, in order (the JSON list)
        self.assertIn("attrListEditor(path + '.attrs', column, () => column, 'attrs', attrIds, def, true)", self.script)

    def test_reload_and_upload_warn_before_discarding_changes(self):
        self.assertIn('Discard unsaved changes?', self.script)
        self.assertIn('Replace the editor contents?', self.script)
        self.assertIn('beforeunload', self.script)

    def test_a_conflict_keeps_the_local_work_and_blocks_saving_until_reload(self):
        self.assertIn('status === 409', self.script)
        self.assertIn('state.conflict = true', self.script)
        self.assertIn('Download my changes', self.script)
        self.assertIn('$(\'config-save\').disabled = state.busy || state.conflict', self.script)

    def test_the_script_uses_the_endpoints_of_the_page_and_the_csrf_token(self):
        for name in ('reloadUrl', 'validateUrl', 'saveUrl', 'uploadUrl', 'previewUrl', 'removeUrl'):
            self.assertIn('app.dataset.' + name, self.script)
        self.assertIn("'X-CSRFToken': csrfToken()", self.script)
        self.assertIn('document.cookie', self.script)
        self.assertIn("'X-Config-Token': state.token", self.script)
