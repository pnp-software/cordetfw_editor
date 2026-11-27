"""The `hidden` setting of an attribute, as opposed to deleting its definition (trash icon, config/remove).

A hidden attribute stays in the stored configuration with its settings and the references to it. The item pages use
the configuration without it (`shown_config`), so for them it is a removed field whose values are kept. The
configuration editor, the download and the project archive keep the setting.
"""
import copy
import json

from django.test import RequestFactory, SimpleTestCase

from editor.config_cleanup import has_hidden_attributes, hidden_attributes, remove_attribute, \
    remove_hidden_attributes, shown_columns
from editor.config_store import config_token
from editor.convert import get_tooltip
from editor.models import Project, SpecItem
from editor.project_config import get_project_config, get_request_config, resolve_config, shown_config
from editor.templatetags.ref_filters import get_short_desc
from tests.factories import template_config
from tests.project_config import test_project_config_archive as archive_tests
from tests.project_config import test_project_config_views as views_tests
from tests.project_config.test_project_config_endpoints import EndpointCase
from tests.project_config.test_project_config_validation import Assertions, base_config


def hide(config, cat, *attrs):
    """`config` with the attributes `attrs` of `cat` marked hidden (changed in place and returned)."""
    for attr in attrs:
        config['cats'][cat]['attrs'][attr]['hidden'] = True
    return config


class HiddenSettingValidationTests(Assertions, SimpleTestCase):
    def test_a_configuration_with_hidden_attributes_and_references_to_them_is_valid(self):
        config = hide(base_config(), 'Service', 'rationale', 'remarks', 'value')
        self.assertIn('value', json.dumps(config['cats']['Service']['disp_def']))     # references are kept
        self.assert_valid(config)

    def test_hidden_is_true_or_false(self):
        config = base_config()
        config['cats']['Packet']['attrs']['t1']['hidden'] = False
        self.assert_valid(config)
        for bad in ('yes', 1, 0, None, [], {}):
            with self.subTest(value=bad):
                config['cats']['Packet']['attrs']['t1']['hidden'] = bad
                self.assert_error(config, 'cats.Packet.attrs.t1.hidden', 'must be true or false')

    def test_hidden_is_optional_and_other_unknown_settings_are_still_refused(self):
        config = base_config()
        self.assertNotIn('hidden', config['cats']['Packet']['attrs']['t1'])
        self.assert_valid(config)
        config['cats']['Packet']['attrs']['t1']['hide'] = True
        self.assert_error(config, 'cats.Packet.attrs.t1.hide', 'unknown')

    def test_domain_and_name_cannot_be_hidden(self):
        for attr in ('domain', 'name'):
            with self.subTest(attr=attr):
                config = hide(base_config(), 'Packet', attr)
                self.assert_error(config, 'cats.Packet.attrs.%s.hidden' % attr,
                                  'must be false: the item is identified by it')
                config['cats']['Packet']['attrs'][attr]['hidden'] = False
                self.assert_valid(config)

    def test_the_default_list_keeps_a_column_with_a_shown_attribute(self):
        config = base_config()
        packet = config['cats']['Packet']
        packet['disp_def'] = [{'header': 'Text', 'attrs': ['title', 'value']}]
        packet['short_desc'] = {'expand_text': [], 'href_tip': [], 'expand_tip': []}
        hide(config, 'Packet', 'title')
        self.assert_valid(config)
        hide(config, 'Packet', 'value')
        self.assert_error(config, 'cats.Packet.disp_def', 'must have at least one column with an attribute which is '
                                                          'not hidden')
        del packet['attrs']['title']['hidden']
        self.assert_valid(config)

    def test_a_hidden_required_choice_attribute_needs_no_choices(self):
        config = base_config()
        definition = config['cats']['Requirement']
        definition['attrs']['p_kind']['req_in_form'] = True
        definition['p_kind_choices'] = {}
        self.assert_error(config, 'cats.Requirement.p_kind_choices', 'must have at least one choice')
        hide(config, 'Requirement', 'p_kind')
        self.assert_no_error_at(config, 'cats.Requirement.p_kind_choices')

    def test_the_template_has_no_hidden_attribute(self):
        self.assertFalse(has_hidden_attributes(base_config()))


class HiddenCleanupTests(SimpleTestCase):
    def test_the_shown_configuration_equals_removing_each_hidden_attribute(self):
        config = hide(base_config(), 'Service', 'rationale', 'value')
        hide(config, 'DataItem', 'value')
        original = copy.deepcopy(config)
        expected = base_config()
        for cat, attr in (('Service', 'rationale'), ('Service', 'value'), ('DataItem', 'value')):
            expected = remove_attribute(expected, cat, attr)
        self.assertEqual(remove_hidden_attributes(config), expected)
        self.assertEqual(config, original)                       # the argument is not changed

    def test_validators_of_a_hidden_field_are_not_applied(self):
        self.assertTrue(base_config()['cats']['DataItem']['validators'])
        shown = remove_hidden_attributes(hide(base_config(), 'DataItem', 'value'))
        self.assertEqual(shown['cats']['DataItem']['validators'], [])

    def test_hidden_false_and_malformed_definitions_are_not_hidden(self):
        config = base_config()
        config['cats']['Packet']['attrs']['t1']['hidden'] = False
        config['cats']['Packet']['attrs']['t2']['hidden'] = 'yes'
        self.assertEqual(hidden_attributes(config['cats']['Packet']), [])
        self.assertEqual(hidden_attributes('not a definition'), [])
        self.assertEqual(hidden_attributes({'attrs': []}), [])
        self.assertFalse(has_hidden_attributes(config))
        self.assertIs(shown_config(config), config)              # nothing to remove: no copy

    def test_a_layout_without_the_hidden_attributes(self):
        columns = [{'header': 'A', 'attrs': ['title', 'value'], 'order_by': 'value'}, {'header': 'B', 'attrs': ['value']},
                   {'header': 'Links', 'trac_cat': 'Packet', 'trac_link': 'p_link'}]
        self.assertEqual(shown_columns(columns, ['value']), [{'header': 'A', 'attrs': ['title']},
                                                             {'header': 'Links', 'trac_cat': 'Packet', 'trac_link': 'p_link'}])
        self.assertEqual(columns[0], {'header': 'A', 'attrs': ['title', 'value'], 'order_by': 'value'})


class HiddenSettingFieldTests(views_tests.HiddenFieldTests):
    """Reruns HiddenFieldTests (fields removed from the configuration) with fields hidden by `"hidden": true`."""

    def hide_attrs(self, config, cat, attrs):
        return hide(config, cat, *attrs)

    def assert_archived_definitions(self, config):
        # the archive keeps the hidden definitions and their columns, so the import restores them
        for attr in self.HIDDEN:
            self.assertIs(config['cats']['Service']['attrs'][attr]['hidden'], True)
        self.assertEqual(config['cats']['Service']['disp_def'], template_config()['cats']['Service']['disp_def'])

    def stored(self):
        return Project.objects.get(id=self.project.id).config

    def test_the_stored_configuration_keeps_the_definitions_and_the_references(self):
        stored, template = self.stored(), template_config()
        for attr in self.HIDDEN:
            self.assertEqual({k: v for k, v in stored['cats']['Service']['attrs'][attr].items() if k != 'hidden'},
                             template['cats']['Service']['attrs'][attr])
        for key in ('disp_def', 'disp_short', 'disp_trac', 'short_desc', 'validators', 'ext_attrs'):
            self.assertEqual(stored['cats']['Service'][key], template['cats']['Service'][key])
        self.assertNotIn('rationale', get_project_config(self.project)['cats']['Service']['attrs'])
        self.assertIs(resolve_config(stored)['cats']['Service']['attrs']['rationale']['hidden'], True)

    def test_showing_the_field_again_restores_its_column_and_values(self):
        stored = self.stored()
        for attr in self.HIDDEN:
            del stored['cats']['Service']['attrs'][attr]['hidden']
        self.assertEqual(stored, template_config())               # nothing of the definition was lost
        Project.objects.filter(id=self.project.id).update(config=stored)
        response = self.client.get(self.list_url('Service'))
        self.assertContains(response, 'keep me')
        self.assertIn(['title', 'desc', 'rationale', 'remarks', 'implementation'],
                      [column.get('attrs') for column in response.context['disp_list']])
        form = self.client.get(self.item_url('edit_spec_item', self.item)).context['form']
        self.assertEqual(form['rationale'].value(), 'keep me')
        self.assertEqual(type(form.fields['rationale'].widget).__name__, 'Textarea')

    def test_the_list_leaves_out_a_column_of_hidden_attributes_only(self):
        self.configure(self.project, lambda config: hide(config, 'Service', 'value', 'rationale', 'remarks'))
        response = self.client.get(self.list_url('Service'))
        self.assertNotIn('Type', [column['header'] for column in response.context['disp_list']])
        self.assertIn(['title', 'desc', 'implementation'], [column.get('attrs') for column in response.context['disp_list']])
        self.assertNotContains(response, 'Val</td>')
        self.assertNotIn('value', response.context['find_replace_fields'])

    def test_find_and_replace_does_not_change_a_hidden_field(self):
        self.assertNotIn('rationale', self.client.get(self.list_url('Service')).context['find_replace_fields'])
        response = self.client.post(self.list_url('Service'), {'field': 'rationale', 'find': 'keep', 'replace': 'lost'},
                                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.refresh(self.item).rationale, 'keep me')

    def test_short_descriptions_and_tooltips_leave_out_hidden_attributes(self):
        self.configure(self.project, lambda config: hide(config, 'Service', 'title'))
        config = get_project_config(self.project)
        self.assertEqual(get_short_desc(self.item, config), 'Val')
        self.assertNotIn('Title', get_tooltip(config, self.item, 'href_tip'))
        self.assertIn('Val', get_tooltip(config, self.item, 'href_tip'))

    def test_one_request_reads_the_shown_configuration(self):
        request = RequestFactory().get('/')
        config = get_request_config(request, self.project)
        self.assertNotIn('rationale', config['cats']['Service']['attrs'])
        self.assertIs(get_request_config(request, self.project), config)


class HiddenSettingEditorTests(EndpointCase):
    """The configuration editor works on the stored configuration, not on the shown one."""

    def test_the_setting_is_saved_reloaded_and_downloaded(self):
        config = hide(self.valid_config(), 'Service', 'rationale')
        response = self.save(self.owner_client, config)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIs(self.stored()['cats']['Service']['attrs']['rationale']['hidden'], True)
        reloaded = self.owner_client.get(self.curl('project_config_reload')).json()
        self.assertIs(reloaded['config']['cats']['Service']['attrs']['rationale']['hidden'], True)
        self.assertEqual(reloaded['token'], config_token(self.stored()))
        download = json.loads(self.owner_client.get(self.curl('project_config_download')).content)
        self.assertIs(download['cats']['Service']['attrs']['rationale']['hidden'], True)
        page = self.owner_client.get(self.curl('project_config'))
        self.assertIs(page.context['initial_config']['cats']['Service']['attrs']['rationale']['hidden'], True)

    def test_an_invalid_setting_is_not_saved(self):
        config = hide(self.valid_config(), 'Service', 'name')
        response = self.save(self.owner_client, config)
        self.assertEqual(response.status_code, 422)
        self.assertEqual([e['path'] for e in response.json()['errors']], ['cats.Service.attrs.name.hidden'])
        self.assertEqual(self.stored(), {})

    def test_the_preview_shows_the_pages_without_the_hidden_field_and_lists_it(self):
        config = hide(self.valid_config(), 'Service', 'rationale')
        body = self.post_json(self.owner_client, 'project_config_preview', config).json()
        self.assertTrue(body['valid'], body)
        definition = config['cats']['Service']
        html = body['html']
        service = html[html.index('<strong class="fs-5">%s</strong>' % definition['name']):]
        service = service[:service.index('</details>')]
        self.assertIn('Hidden fields', service)
        self.assertIn('%s (rationale)' % definition['attrs']['rationale']['label'], service)
        self.assertNotIn('rationale, ', service)                 # not a field of the preview form
        label = definition['attrs']['rationale']['label']
        self.assertNotIn(label + ' /', service)                  # not in a column of the preview layouts
        self.assertNotIn('/ ' + label, service)


class HiddenSettingArchiveTests(archive_tests.ArchiveTestCase):
    def test_the_import_restores_the_hidden_setting(self):
        config = hide(template_config(), 'Service', 'rationale')
        Project.objects.filter(id=self.project.id).update(config=config)
        self.make_item(self.project, 'Service', 'D', 'svc', title='T', rationale='kept')
        data = self.export_bytes(self.project)
        self.assertEqual(json.loads(self.members(data)['config.json']), config)
        imported, messages = self.import_as_copy(self.project, data)
        self.assertEqual(messages, [])
        self.assertEqual(self.stored(imported), config)
        self.assertEqual(SpecItem.objects.get(project=imported, name='svc').rationale, 'kept')
