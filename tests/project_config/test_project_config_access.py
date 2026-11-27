"""Phase 2: access layer (get_project_config, get_request_config) and the explicit-configuration accessors."""
import copy
import io
import re

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import path

from editor import configs as configs_module
from editor import convert as convert_module
from editor import markdown as markdown_module
from editor.configs import (get_attr_config, get_cat_config, get_general_setting, has_cat)
from editor.models import Project
from editor.project_config import (SERVER_ONLY_GENERAL_KEYS, filter_template_for_data, get_project_config,
                                   get_request_config, load_template, resolve_config)
from tests.project_config.base import EditorTestCase, TEMPLATE


CONFIG_ONLY_QUERY = re.compile(r'^SELECT [`"]editor_project[`"]\.[`"]config[`"](?: AS [`"]config[`"])? FROM')


def project_config_queries(queries):
    """Single-column reads of Project.config (what get_request_config issues)."""
    return [q['sql'] for q in queries if CONFIG_ONLY_QUERY.match(q['sql'])]


def probe_view(request, first_id, second_id):
    """Reads the configuration of two projects twice each, as a view with several helpers would."""
    first, second = Project.objects.get(id=first_id), Project.objects.get(id=second_id)
    result = {}
    for _ in range(2):
        result['first'] = get_request_config(request, first)['cats']['Packet']['name']
        result['second'] = get_request_config(request, second)['cats']['Packet']['name']
    result['same_object'] = get_request_config(request, first) is get_request_config(request, first)
    return JsonResponse(result)


urlpatterns = [path('probe/<int:first_id>/<int:second_id>/', probe_view, name='probe')]


class AccessTestCase(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.other, _ = self.make_project('Other', owner=self.owner)

    def store(self, project, mutate=None):
        config = load_template()
        if mutate:
            mutate(config)
        Project.objects.filter(id=project.id).update(config=config)
        project.refresh_from_db()
        return config


class GetProjectConfigTests(AccessTestCase):
    def test_empty_configuration_falls_back_to_the_template(self):
        self.assertEqual(self.project.config, {})
        config = get_project_config(self.project)
        expected = copy.deepcopy(TEMPLATE)
        for key in SERVER_ONLY_GENERAL_KEYS:
            del expected['general'][key]
        self.assertEqual(config, expected)

    def test_fallback_is_a_new_object_each_time(self):
        first, second = get_project_config(self.project), get_project_config(self.project)
        self.assertIsNot(first, second)
        first['cats']['Packet']['name'] = 'Changed'
        self.assertEqual(get_project_config(self.project)['cats']['Packet']['name'], TEMPLATE['cats']['Packet']['name'])
        self.assertEqual(load_template(), TEMPLATE)

    def test_stored_configuration_is_returned(self):
        self.store(self.project, lambda c: c['cats']['Packet'].update(name='Telemetry Packet'))
        config = get_project_config(self.project)
        self.assertEqual(config['cats']['Packet']['name'], 'Telemetry Packet')
        self.assertEqual(config['cats']['Service'], TEMPLATE['cats']['Service'])

    def test_stored_configuration_is_not_replaced_by_the_template(self):
        stored = {'general': {'csv_sep': ';'}, 'cats': {'Custom': {'name': 'Custom'}}}
        Project.objects.filter(id=self.project.id).update(config=stored)
        self.project.refresh_from_db()
        self.assertEqual(get_project_config(self.project), stored)

    def test_none_is_treated_as_empty(self):
        self.assertEqual(resolve_config(None), resolve_config({}))

    def test_server_settings_are_never_part_of_the_result(self):
        self.assertNotIn('temp_dir', get_project_config(self.project)['general'])
        Project.objects.filter(id=self.project.id).update(config=load_template())
        self.project.refresh_from_db()
        self.assertIn('temp_dir', self.project.config['general'])
        self.assertNotIn('temp_dir', get_project_config(self.project)['general'])
        self.assertIn('temp_dir', Project.objects.get(id=self.project.id).config['general'])

    def test_two_projects_with_different_settings_for_the_same_category(self):
        self.store(self.project, lambda c: c['cats']['Packet'].update(name='Packet A', page_size=5))
        self.store(self.other, lambda c: c['cats']['Packet']['attrs']['t1'].update(label='Other label'))
        first, second = get_project_config(self.project), get_project_config(self.other)
        self.assertEqual(first['cats']['Packet']['name'], 'Packet A')
        self.assertEqual(first['cats']['Packet']['page_size'], 5)
        self.assertEqual(first['cats']['Packet']['attrs']['t1'], TEMPLATE['cats']['Packet']['attrs']['t1'])
        self.assertEqual(second['cats']['Packet']['name'], TEMPLATE['cats']['Packet']['name'])
        self.assertEqual(second['cats']['Packet']['page_size'], TEMPLATE['cats']['Packet']['page_size'])
        self.assertEqual(second['cats']['Packet']['attrs']['t1']['label'], 'Other label')

    def test_mutating_the_result_changes_neither_the_other_project_nor_the_stored_value(self):
        self.store(self.project)
        self.store(self.other)
        config = get_project_config(self.project)
        config['cats']['Packet']['name'] = 'Mutated'
        config['cats']['Packet']['attrs']['t1']['label'] = 'Mutated'
        config['general']['csv_sep'] = '|'
        del config['cats']['Service']
        self.assertEqual(self.project.config['cats']['Packet']['name'], TEMPLATE['cats']['Packet']['name'])
        for project in (self.project, self.other):
            project = Project.objects.get(id=project.id)
            fresh = get_project_config(project)
            self.assertEqual(fresh['cats']['Packet'], TEMPLATE['cats']['Packet'])
            self.assertIn('Service', fresh['cats'])
            self.assertEqual(fresh['general']['csv_sep'], TEMPLATE['general']['csv_sep'])
        self.assertEqual(load_template(), TEMPLATE)

    def test_the_template_is_not_touched(self):
        config = get_project_config(self.project)
        config['cats'].clear()
        resolve_config(self.project.config)['general'].clear()
        self.assertEqual(load_template(), TEMPLATE)

    def test_filter_for_data_is_the_function_used_by_initialization(self):
        # Shared function: its output for a project is what init_project_configs stores.
        from django.core.management import call_command
        call_command('init_project_configs', stdout=io.StringIO())
        self.project.refresh_from_db()
        self.assertEqual(resolve_config(self.project.config),
                         resolve_config(filter_template_for_data(load_template(), self.project)))


class RequestConfigTests(AccessTestCase):
    def setUp(self):
        super().setUp()
        self.store(self.project, lambda c: c['cats']['Packet'].update(name='Packet A'))
        self.store(self.other, lambda c: c['cats']['Packet'].update(name='Packet B'))

    def test_one_read_per_project_and_request(self):
        request = HttpRequest()
        with CaptureQueriesContext(connection) as queries:
            for _ in range(5):
                get_request_config(request, self.project)
        self.assertEqual(len(project_config_queries(queries)), 1)

    def test_all_calls_in_a_request_see_the_same_configuration_even_if_it_changes_meanwhile(self):
        request = HttpRequest()
        first = get_request_config(request, self.project)
        Project.objects.filter(id=self.project.id).update(config={'general': {}, 'cats': {}})
        self.assertIs(get_request_config(request, self.project), first)
        self.assertEqual(first['cats']['Packet']['name'], 'Packet A')

    def test_a_stale_instance_does_not_provide_the_value(self):
        stale = Project.objects.get(id=self.project.id)
        self.store(self.project, lambda c: c['cats']['Packet'].update(name='Newer'))
        self.assertEqual(stale.config['cats']['Packet']['name'], 'Packet A')
        self.assertEqual(get_request_config(HttpRequest(), stale)['cats']['Packet']['name'], 'Newer')

    def test_two_projects_in_one_request_are_isolated(self):
        request = HttpRequest()
        with CaptureQueriesContext(connection) as queries:
            first = get_request_config(request, self.project)
            second = get_request_config(request, self.other)
            get_request_config(request, self.project)
            get_request_config(request, self.other)
        self.assertEqual(len(project_config_queries(queries)), 2)
        self.assertEqual(first['cats']['Packet']['name'], 'Packet A')
        self.assertEqual(second['cats']['Packet']['name'], 'Packet B')
        self.assertIsNot(first, second)
        first['cats']['Packet']['name'] = 'Mutated in the request'
        self.assertEqual(second['cats']['Packet']['name'], 'Packet B')
        self.assertEqual(Project.objects.get(id=self.other.id).config['cats']['Packet']['name'], 'Packet B')

    def test_requests_do_not_share_state(self):
        first_request, second_request = HttpRequest(), HttpRequest()
        first = get_request_config(first_request, self.project)
        first['cats']['Packet']['name'] = 'Mutated'
        self.assertEqual(get_request_config(second_request, self.project)['cats']['Packet']['name'], 'Packet A')

    def test_empty_configuration_falls_back_in_a_request(self):
        project, _ = self.make_project('Fresh', owner=self.owner)
        config = get_request_config(HttpRequest(), project)
        self.assertEqual(config['cats']['Packet'], TEMPLATE['cats']['Packet'])

    def test_missing_project_falls_back_to_the_template(self):
        self.assertEqual(get_request_config(HttpRequest(), Project(id=999999))['cats'], TEMPLATE['cats'])

    @override_settings(ROOT_URLCONF=__name__)
    def test_a_view_reads_each_project_once_and_a_new_request_sees_saved_changes(self):
        url = '/probe/%d/%d/' % (self.project.id, self.other.id)
        with CaptureQueriesContext(connection) as queries:
            first = self.client.get(url).json()
        self.assertEqual(len(project_config_queries(queries)), 2)
        self.assertEqual(first, {'first': 'Packet A', 'second': 'Packet B', 'same_object': True})
        self.store(self.project, lambda c: c['cats']['Packet'].update(name='Saved'))
        second = self.client.get(url).json()
        self.assertEqual(second['first'], 'Saved')
        self.assertEqual(second['second'], 'Packet B')


class ExplicitAccessorTests(AccessTestCase):
    def test_accessors_use_only_the_given_configuration(self):
        first = get_project_config(self.project)
        second = get_project_config(self.other)
        first['cats']['Packet']['name'] = 'Packet A'
        first['cats']['Packet']['attrs']['t1']['label'] = 'Label A'
        first['general']['csv_sep'] = '|'
        del second['cats']['Service']
        self.assertEqual(get_cat_config(first, 'Packet')['name'], 'Packet A')
        self.assertEqual(get_cat_config(second, 'Packet')['name'], TEMPLATE['cats']['Packet']['name'])
        self.assertEqual(get_attr_config(first, 'Packet', 't1')['label'], 'Label A')
        self.assertEqual(get_attr_config(second, 'Packet', 't1'), TEMPLATE['cats']['Packet']['attrs']['t1'])
        self.assertEqual(get_general_setting(first, 'csv_sep'), '|')
        self.assertEqual(get_general_setting(second, 'csv_sep'), TEMPLATE['general']['csv_sep'])
        self.assertTrue(has_cat(first, 'Service'))
        self.assertFalse(has_cat(second, 'Service'))
        with self.assertRaises(KeyError):
            get_cat_config(second, 'Service')
        with self.assertRaises(KeyError):
            get_attr_config(first, 'Packet', 'nope')
        with self.assertRaises(KeyError):
            get_general_setting(first, 'temp_dir')

    def test_there_is_no_global_dictionary_any_more(self):
        self.assertFalse(hasattr(configs_module, 'configs'))
        self.assertFalse(hasattr(convert_module, 'configs'))
        self.assertFalse(hasattr(markdown_module, 'configs'))
