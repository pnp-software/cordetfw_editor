"""Every rule has an invalid case (asserting the exact JSON path of the error) and a valid case. Validation through
the HTTP endpoints, the UI and the archive import is tested in test_project_config_{endpoints,ui,archive}.py."""
import copy
import json
import random
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from editor import config_validation, project_config
from editor.config_cleanup import remove_attribute, remove_category, remove_dangling_references
from editor.config_validation import (ALLOWED_KINDS, MAX_ERRORS, MAX_JSON_BYTES, ConfigError, key_path,
                                      validate_config, validate_config_file, validate_config_json)
from editor.models import Project, SpecItem
from editor.project_config import DATA_COLUMNS, filter_template_for_data, load_template, resolve_config
from tests.project_config.base import ALL_CATS, EditorTestCase


def base_config():
    """What every reader of a project's configuration gets for an unconfigured project (no server settings)."""
    return resolve_config(None)


def minimal_cat(attrs=None, **overrides):
    """A small valid category definition which does not depend on any other category."""
    definition = {
        'name': 'Widget', 'level': 'project', 'abbr': 'Wdg', 'page_size': 100, 'ext_attrs': [],
        'expand': {'s_link': 'None', 'p_link': 'None'},
        'short_desc': {'expand_text': ['title'], 'href_tip': ['title'], 'expand_tip': ['title']},
        'tracs': [], 'links': {}, 'validators': [], 'access_from_index': {'level': 'Project'},
        'attrs': attrs or {
            'domain': {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
            'name': {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
            'title': {'label': 'Title', 'req_in_form': False, 'kind': 'plain_text'}},
        'p_kind_choices': {}, 's_kind_choices': {},
        'disp_def': [{'header': 'Name', 'attrs': ['name'], 'order_by': 'name'}], 'disp_short': [], 'disp_trac': [],
    }
    definition.update(overrides)
    return definition


def with_new_cat(name='Widget', **overrides):
    config = base_config()
    config['cats'][name] = minimal_cat(**overrides)
    return config


class Assertions:
    def errors_of(self, config, project=None):
        return [(error.path, error.message) for error in validate_config(config, project)]

    def assert_valid(self, config, project=None):
        self.assertEqual(self.errors_of(config, project), [])

    def assert_error(self, config, path, fragment, project=None):
        errors = self.errors_of(config, project)
        self.assertTrue(any(p == path and fragment in m for p, m in errors),
                        'no error at %r containing %r in %r' % (path, fragment, errors))

    def assert_no_error_at(self, config, path, project=None):
        errors = self.errors_of(config, project)
        self.assertFalse([e for e in errors if e[0] == path], errors)


class StructureTests(Assertions, SimpleTestCase):
    def test_the_template_without_server_settings_is_valid(self):
        self.assert_valid(base_config())

    def test_the_raw_template_only_differs_by_the_server_setting(self):
        self.assertEqual([e.path for e in validate_config(load_template())], ['general.temp_dir'])

    def test_a_new_category_is_valid(self):
        self.assert_valid(with_new_cat())

    def test_root_must_be_an_object(self):
        for value in (None, [], 'x', 1, True, 1.5):
            with self.subTest(value=value):
                self.assertEqual(validate_config(value), [ConfigError('', 'the configuration must be a JSON object')])

    def test_top_level_keys(self):
        config = base_config()
        config['extra'] = 1
        self.assert_error(config, 'extra', 'unknown setting')
        for key in ('general', 'cats'):
            config = base_config()
            del config[key]
            self.assert_error(config, key, 'is required')
        for key, value in (('general', []), ('general', None), ('cats', []), ('cats', 'x')):
            config = base_config()
            config[key] = value
            self.assert_error(config, key, 'must be an object')

    def test_the_error_contract(self):
        error = ConfigError('cats.A.b', 'bad')
        self.assertEqual(error.as_dict(), {'path': 'cats.A.b', 'message': 'bad'})
        self.assertEqual(str(error), 'cats.A.b: bad')
        self.assertEqual(str(ConfigError('', 'bad')), '(root): bad')
        self.assertEqual(key_path('cats', 'Packet'), 'cats.Packet')
        self.assertEqual(key_path('', 'cats'), 'cats')
        self.assertEqual(key_path('cats.A', 'a.b'), 'cats.A["a.b"]')
        self.assertEqual(key_path('', 5), '[5]')


class GeneralSettingsTests(Assertions, SimpleTestCase):
    def check(self, key, bad, good):
        for value in bad:
            with self.subTest(key=key, bad=value):
                config = base_config()
                config['general'][key] = value
                self.assert_error(config, 'general.' + key, '')
        for value in good:
            with self.subTest(key=key, good=value):
                config = base_config()
                config['general'][key] = value
                self.assert_valid(config)

    def test_server_settings_are_rejected(self):
        config = base_config()
        config['general']['temp_dir'] = '/tmp'
        self.assert_error(config, 'general.temp_dir', 'server setting')

    def test_unknown_and_missing_settings(self):
        config = base_config()
        config['general']['colour'] = 'red'
        self.assert_error(config, 'general.colour', 'unknown setting')
        for key in ('csv_sep', 'eol_sep', 'short_desc_len', 'max_depth'):
            config = base_config()
            del config['general'][key]
            self.assert_error(config, 'general.' + key, 'is required')

    def test_csv_sep(self):
        self.check('csv_sep', ['', 'ab', 'a', '1', ' ', '"', '\n', '\r', 5, None, ['|']], ['|', ';', ',', '\t', '#'])

    def test_eol_sep(self):
        self.check('eol_sep', ['', 'x', '\r', None, 1, ['\n']], ['\n', '\r\n'])

    def test_short_desc_len(self):
        self.check('short_desc_len', [9, 1001, 0, True, '100', 100.0, None, -5], [10, 100, 1000])

    def test_max_depth(self):
        self.check('max_depth', [0, 501, True, -1, '200', 2.5, None], [1, 200, 500])


class CategoryIdentifierTests(Assertions, SimpleTestCase):
    def add(self, name):
        config = base_config()
        config['cats'][name] = minimal_cat()
        return config

    def test_invalid_identifiers(self):
        for name in ('1Cat', 'a b', 'a-b', 'x' * 25, '', 'Pa.cket', 'Caf\u00e9', 'Cat/x', 'a,b', 'a|b', '_x'):
            with self.subTest(name=name):
                self.assert_error(self.add(name), key_path('cats', name), 'category identifier')

    def test_valid_identifiers(self):
        for name in ('x' * 24, 'My_Cat2', 'A', 'Packet2'):
            with self.subTest(name=name):
                config = self.add(name)
                config['cats'][name]['name'] = 'Name of ' + name
                config['cats'][name]['abbr'] = name[:24]
                self.assert_valid(config)

    def test_none_is_reserved(self):
        for name in ('None', 'none', 'NONE'):
            with self.subTest(name=name):
                self.assert_error(self.add(name), 'cats.' + name, 'reserved')

    def test_identifiers_must_be_unique_ignoring_case(self):
        config = self.add('packet')
        self.assert_error(config, 'cats.packet', 'differs only in case from "Packet"')

    def test_category_must_be_an_object_and_have_every_setting(self):
        config = base_config()
        config['cats']['Packet'] = []
        self.assert_error(config, 'cats.Packet', 'must be an object')
        for key in config_validation.CAT_KEYS:
            with self.subTest(missing=key):
                config = base_config()
                del config['cats']['Packet'][key]
                self.assert_error(config, 'cats.Packet.' + key, 'is required')
        config = base_config()
        config['cats']['Packet']['colour'] = 'red'
        self.assert_error(config, 'cats.Packet.colour', 'unknown setting')


class CategorySettingTests(Assertions, SimpleTestCase):
    def mutate(self, cat, key, value):
        config = base_config()
        config['cats'][cat][key] = value
        return config

    def test_display_name(self):
        for value in ('', ' x', 'x ', 5, None, 'x' * 101, 'a\nb', ['x']):
            with self.subTest(value=value):
                self.assert_error(self.mutate('Packet', 'name', value), 'cats.Packet.name', '')
        self.assert_valid(self.mutate('Packet', 'name', 'x' * 100))

    def test_display_names_are_unique_ignoring_case(self):
        self.assert_error(self.mutate('Service', 'name', 'packet'), 'cats.Service.name',
                          'already used by category "Packet"')

    def test_abbreviation(self):
        for value in ('', 'a b', 'x' * 25, 5, None, 'a.b', 'a\n'):
            with self.subTest(value=value):
                self.assert_error(self.mutate('Packet', 'abbr', value), 'cats.Packet.abbr', '')
        self.assert_valid(self.mutate('Packet', 'abbr', 'Pck_1-'))

    def test_abbreviations_are_unique_ignoring_case(self):
        self.assert_error(self.mutate('Service', 'abbr', 'pckt'), 'cats.Service.abbr', 'already used by category "Packet"')

    def test_level(self):
        for value in ('Project', 'x', None, 1, ['project']):
            with self.subTest(value=value):
                self.assert_error(self.mutate('Packet', 'level', value), 'cats.Packet.level', 'must be one of')

    def test_page_size(self):
        for value in (0, 1001, True, '100', 1.5, None, -1):
            with self.subTest(value=value):
                self.assert_error(self.mutate('Packet', 'page_size', value), 'cats.Packet.page_size', 'integer from 1 to 1000')
        for value in (1, 100, 1000):
            self.assert_valid(self.mutate('Packet', 'page_size', value))

    def test_access_from_index(self):
        path = 'cats.Packet.access_from_index'
        self.assert_error(self.mutate('Packet', 'access_from_index', []), path, 'must be an object')
        self.assert_error(self.mutate('Packet', 'access_from_index', {}), path + '.level', 'is required')
        self.assert_error(self.mutate('Packet', 'access_from_index', {'level': 'project'}), path + '.level', 'must be one of')
        self.assert_error(self.mutate('Packet', 'access_from_index', {'level': 'Project', 'x': 1}), path + '.x', 'unknown')

    def test_access_from_index_must_fit_the_level(self):
        self.assert_error(self.mutate('Packet', 'access_from_index', {'level': 'Application'}),
                          'cats.Packet.access_from_index.level', 'level "project"')
        self.assert_error(self.mutate('Requirement', 'access_from_index', {'level': 'Project'}),
                          'cats.Requirement.access_from_index.level', 'level "application"')
        self.assert_valid(self.mutate('Packet', 'access_from_index', {'level': 'None'}))
        self.assert_valid(self.mutate('Requirement', 'access_from_index', {'level': 'None'}))

    def test_a_category_which_is_not_reachable_from_the_index_is_valid(self):
        self.assertEqual(base_config()['cats']['EnumValue']['access_from_index'], {'level': 'None'})
        self.assert_valid(base_config())


class AttributeTests(Assertions, SimpleTestCase):
    def attrs_of(self, cat='Packet'):
        config = base_config()
        return config, config['cats'][cat]['attrs']

    def test_allowed_fields_are_the_item_model_fields_with_data(self):
        self.assertEqual(set(ALLOWED_KINDS), set(DATA_COLUMNS))

    def test_attrs_must_be_an_object(self):
        config = base_config()
        config['cats']['Packet']['attrs'] = []
        self.assert_error(config, 'cats.Packet.attrs', 'must be an object')

    def test_domain_and_name_are_mandatory(self):
        for name in ('domain', 'name'):
            config, attrs = self.attrs_of()
            del attrs[name]
            self.assert_error(config, 'cats.Packet.attrs.' + name, 'is required')
            config, attrs = self.attrs_of()
            attrs[name]['req_in_form'] = False
            self.assert_error(config, 'cats.Packet.attrs.%s.req_in_form' % name, 'must be true')

    def test_only_fields_of_the_item_model(self):
        for field in ('status', 's_data', 'project', 'application', 'previous', 'created_at', 'updated_at', 'id',
                      'foo', 'n4', 'cat', 'Title', ''):
            with self.subTest(field=field):
                config, attrs = self.attrs_of()
                attrs[field] = {'label': 'Extra', 'req_in_form': False, 'kind': 'plain_text'}
                self.assert_error(config, key_path('cats.Packet.attrs', field), 'not a field of the item model')

    def test_every_field_with_each_kind(self):
        kinds = ['plain_text', 'ref_text', 'plain_ref', 'spec_item_ref', 'eval_ref', 'int', 'image', 'date', 'table',
                 'foo', '', 5, None, ['int']]
        for field, allowed in ALLOWED_KINDS.items():
            for kind in kinds:
                with self.subTest(field=field, kind=kind):
                    attrs = {'domain': {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                             'name': {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'}}
                    attrs[field] = {'label': 'Other ' + field, 'req_in_form': field in ('domain', 'name'), 'kind': kind}
                    config = with_new_cat(attrs=attrs, short_desc={'expand_text': [], 'href_tip': [], 'expand_tip': []})
                    errors = [e for e in self.errors_of(config) if e[0].startswith('cats.Widget.attrs')]
                    if kind in allowed:
                        self.assertEqual(errors, [])
                    else:
                        self.assertEqual([e[0] for e in errors], ['cats.Widget.attrs.%s.kind' % field])

    def test_label(self):
        for value in ('', ' x', 'x ', 5, None, 'x' * 101, 'a\tb', ['x']):
            with self.subTest(value=value):
                config, attrs = self.attrs_of()
                attrs['title']['label'] = value
                self.assert_error(config, 'cats.Packet.attrs.title.label', '')

    def test_labels_are_unique_ignoring_blanks_and_case(self):
        for label in ('Domain', 'domain', 'D o m a i n'):
            with self.subTest(label=label):
                config, attrs = self.attrs_of()
                attrs['title']['label'] = label
                self.assert_error(config, 'cats.Packet.attrs.title.label', 'already used by attribute "domain"')

    def test_req_in_form_is_a_boolean(self):
        for value in ('yes', 1, None, 'true', []):
            with self.subTest(value=value):
                config, attrs = self.attrs_of()
                attrs['title']['req_in_form'] = value
                self.assert_error(config, 'cats.Packet.attrs.title.req_in_form', 'true or false')
        config, attrs = self.attrs_of()
        attrs['title']['req_in_form'] = False
        self.assert_valid(config)

    def test_attribute_structure(self):
        config, attrs = self.attrs_of()
        attrs['title'] = 'x'
        self.assert_error(config, 'cats.Packet.attrs.title', 'must be an object')
        config, attrs = self.attrs_of()
        attrs['title']['colour'] = 1
        self.assert_error(config, 'cats.Packet.attrs.title.colour', 'unknown setting')
        for key in ('label', 'req_in_form', 'kind'):
            config, attrs = self.attrs_of()
            del attrs['title'][key]
            self.assert_error(config, 'cats.Packet.attrs.title.' + key, 'is required')


class ExternalAttributeTests(Assertions, SimpleTestCase):
    def test_external_categories_of_the_template_are_valid(self):
        config = base_config()
        self.assertTrue(config['cats']['FCP']['ext_attrs'] and config['cats']['Model']['ext_attrs'])
        self.assert_valid(config)

    def test_ext_attrs_must_name_attributes_of_the_category(self):
        config = base_config()
        config['cats']['FCP']['ext_attrs'].append('nope')
        self.assert_error(config, 'cats.FCP.ext_attrs[8]', 'unknown attribute "nope"')

    def test_ext_attrs_must_be_a_list_of_names_without_duplicates(self):
        for value, fragment in (('title', 'must be a list'), ([5], 'must be an attribute name'),
                                (['domain', 'domain'], 'twice')):
            with self.subTest(value=value):
                config = base_config()
                config['cats']['FCP']['ext_attrs'] = value
                self.assert_error(config, 'cats.FCP.ext_attrs' + ('[0]' if value == [5] else ''), fragment)

    def test_a_category_without_external_support_cannot_load_attributes_from_outside(self):
        config = base_config()
        config['cats']['Packet']['ext_attrs'] = ['title']
        self.assert_error(config, 'cats.Packet.ext_attrs', 'external repository')
        config = with_new_cat(ext_attrs=['title'])
        self.assert_error(config, 'cats.Widget.ext_attrs', 'external repository')


class ReferenceTests(Assertions, SimpleTestCase):
    def test_expand(self):
        path = 'cats.Packet.expand'
        for value, error_path, fragment in (([], path, 'must be an object'),
                                            ({'s_link': 'DerPacket', 's_label': 'x'}, path + '.p_link', 'is required'),
                                            ({'p_link': 'PacketPar', 'p_label': 'x'}, path + '.s_link', 'is required'),
                                            ({'s_link': 'Nope', 'p_link': 'None'}, path + '.s_link', 'identifier of a category'),
                                            ({'s_link': 5, 'p_link': 'None'}, path + '.s_link', 'identifier of a category'),
                                            ({'s_link': 'None', 'p_link': 'None', 'x': 1}, path + '.x', 'unknown setting'),
                                            ({'s_link': 'DerPacket', 'p_link': 'None'}, path + '.s_label', 'is required'),
                                            ({'s_link': 'None', 'p_link': 'PacketPar'}, path + '.p_label', 'is required'),
                                            ({'s_link': 'None', 'p_link': 'None', 'p_label': ''}, path + '.p_label', '')):
            with self.subTest(value=value):
                config = base_config()
                config['cats']['Packet']['expand'] = value
                self.assert_error(config, error_path, fragment)

    def test_expand_with_none_and_without_labels_is_valid(self):
        config = base_config()
        config['cats']['Packet']['expand'] = {'s_link': 'None', 'p_link': 'None'}
        self.assert_valid(config)

    def test_short_desc(self):
        path = 'cats.Packet.short_desc'
        config = base_config()
        config['cats']['Packet']['short_desc'] = []
        self.assert_error(config, path, 'must be an object')
        for key in ('expand_text', 'href_tip', 'expand_tip'):
            config = base_config()
            del config['cats']['Packet']['short_desc'][key]
            self.assert_error(config, path + '.' + key, 'is required')
            config = base_config()
            config['cats']['Packet']['short_desc'][key] = ['title', 'nope']
            self.assert_error(config, '%s.%s[1]' % (path, key), 'unknown attribute "nope"')
            config['cats']['Packet']['short_desc'][key] = 'title'
            self.assert_error(config, path + '.' + key, 'must be a list')
            config['cats']['Packet']['short_desc'][key] = [3]
            self.assert_error(config, path + '.' + key + '[0]', 'attribute name')
            config['cats']['Packet']['short_desc'][key] = []
            self.assert_valid(config)
        config = base_config()
        config['cats']['Packet']['short_desc']['colour'] = []
        self.assert_error(config, path + '.colour', 'unknown setting')

    def test_tracs(self):
        path = 'cats.Requirement.tracs'
        for value, error_path, fragment in (
                ('x', path, 'must be a list'), (['x'], path + '[0]', 'must be an object'),
                ([{'trac_cat': 'Nope', 'trac_link': 'p_link'}], path + '[0].trac_cat', 'unknown category "Nope"'),
                ([{'trac_cat': 5, 'trac_link': 'p_link'}], path + '[0].trac_cat', 'category name'),
                ([{'trac_cat': 'VerLink', 'trac_link': 'x'}], path + '[0].trac_link', 'must be one of'),
                ([{'trac_cat': 'VerLink', 'trac_link': 'p_link', 'x': 1}], path + '[0].x', 'unknown setting')):
            with self.subTest(value=value):
                config = base_config()
                config['cats']['Requirement']['tracs'] = value
                self.assert_error(config, error_path, fragment)

    def test_links(self):
        path = 'cats.Packet.links'
        for value, error_path, fragment in (
                ([], path, 'must be an object'),
                ({'q_link': {'targets': ['Service']}}, path + '.q_link', 'unknown link'),
                ({'p_link': {'targets': ['Nope']}}, path + '.p_link.targets[0]', 'unknown category "Nope"'),
                ({'p_link': {'targets': []}}, path + '.p_link.targets', 'non-empty'),
                ({'p_link': {'targets': ['Service'], 'all_except': []}}, path + '.p_link', 'exactly one'),
                ({'p_link': {}}, path + '.p_link', 'exactly one'),
                ({'p_link': {'targets': ['Service'], 'scope': 'x'}}, path + '.p_link.scope', 'must be one of'),
                ({'p_link': {'targets': ['Service'], 'order_by': ['x']}}, path + '.p_link.order_by', 'must be a non-empty list'),
                ({'p_link': {'targets': ['Service'], 'colour': 1}}, path + '.p_link.colour', 'unknown setting'),
                ({'p_link': {'targets': ['Service'], 'narrow_by_other_parent': {'target_field': 'x', 'parent_field': 's_link'}}},
                 path + '.p_link.narrow_by_other_parent.target_field', 'must be one of'),
                ({'p_link': 'Service'}, path + '.p_link', 'must be an object')):
            with self.subTest(value=value):
                config = base_config()
                config['cats']['Packet']['links'] = value
                self.assert_error(config, error_path, fragment)

    def test_all_except_may_be_empty_and_rules_with_every_setting_are_valid(self):
        config = base_config()
        config['cats']['Packet']['links'] = {
            'p_link': {'all_except': []},
            's_link': {'targets': ['EnumType'], 'scope': 'application', 'order_by': ['cat', 'name'],
                       'narrow_by_other_parent': {'target_field': 's_link', 'parent_field': 'p_link'}}}
        self.assert_valid(config)

    def test_validators(self):
        path = 'cats.DataItem.validators'
        good = copy.deepcopy(base_config()['cats']['DataItem']['validators'][0])
        for mutate, error_path, fragment in (
                (lambda s: s.update(name='os.system'), path + '[0].name', 'unknown validator'),
                (lambda s: s.update(name='__import__'), path + '[0].name', 'unknown validator'),
                (lambda s: s.update(name=5), path + '[0].name', 'unknown validator'),
                (lambda s: s['params'].update(ref_cat='Nope'), path + '[0].params.ref_cat', 'unknown category'),
                (lambda s: s['params'].update(field='nope'), path + '[0].params.field', 'unknown attribute'),
                (lambda s: s['params'].update(link='x_link'), path + '[0].params.link', 'must be one of'),
                (lambda s: s['params'].update(extra='x'), path + '[0].params.extra', 'unknown parameter'),
                (lambda s: s['params'].pop('message'), path + '[0].params.message', 'is required'),
                (lambda s: s['params'].update(message='x' * 301), path + '[0].params.message', 'at most'),
                (lambda s: s.update(params=[]), path + '[0].params', 'must be an object'),
                (lambda s: s.update(colour=1), path + '[0].colour', 'unknown setting')):
            with self.subTest(fragment=fragment, path=error_path):
                spec = copy.deepcopy(good)
                mutate(spec)
                config = base_config()
                config['cats']['DataItem']['validators'] = [spec]
                self.assert_error(config, error_path, fragment)
        config = base_config()
        config['cats']['DataItem']['validators'] = 'x'
        self.assert_error(config, path, 'must be a list')
        config['cats']['DataItem']['validators'] = ['x']
        self.assert_error(config, path + '[0]', 'must be an object')

    def test_validators_must_name_attributes_of_their_own_category(self):
        config = base_config()
        config['cats']['EnumValue']['validators'] = copy.deepcopy(config['cats']['DataItem']['validators'])
        del config['cats']['EnumValue']['attrs']['value']
        self.assert_error(config, 'cats.EnumValue.validators[0].params.field', 'unknown attribute "value" of category "EnumValue"')


class ChoiceListTests(Assertions, SimpleTestCase):
    def mutate(self, cat, key, value):
        config = base_config()
        config['cats'][cat][key] = value
        return config

    def test_choice_lists(self):
        for kind in ('p_kind', 's_kind'):
            path = 'cats.Requirement.%s_choices' % kind
            self.assert_error(self.mutate('Requirement', kind + '_choices', []), path, 'must be an object')
            for value in ('', 'a b', 'x' * 25, 'a\tb', 5, None):
                with self.subTest(kind=kind, value=value):
                    self.assert_error(self.mutate('Requirement', kind + '_choices', {value: 'Label', 'OK': 'Fine'}),
                                      key_path(path, value), '')
            for label in ('', ' x', 5, None, 'x' * 101):
                with self.subTest(kind=kind, label=label):
                    self.assert_error(self.mutate('Requirement', kind + '_choices', {'TST': label}), path + '.TST', '')
            self.assert_valid(self.mutate('Requirement', kind + '_choices', {'n.a.': 'Not applicable', 'x' * 24: 'Long'}))

    def test_choice_values_with_dots_use_the_bracket_notation(self):
        errors = self.errors_of(self.mutate('Requirement', 'p_kind_choices', {'n.a.': ''}))
        self.assertEqual(errors[0][0], 'cats.Requirement.p_kind_choices["n.a."]')

    def test_a_shown_and_required_kind_needs_choices(self):
        self.assertTrue(base_config()['cats']['Requirement']['attrs']['p_kind']['req_in_form'])
        self.assert_error(self.mutate('Requirement', 'p_kind_choices', {}), 'cats.Requirement.p_kind_choices',
                          'at least one choice')
        self.assert_error(self.mutate('Requirement', 's_kind_choices', {}), 'cats.Requirement.s_kind_choices',
                          'at least one choice')

    def test_empty_choices_are_valid_when_the_attribute_is_optional_or_absent(self):
        config = self.mutate('Requirement', 'p_kind_choices', {})
        config['cats']['Requirement']['attrs']['p_kind']['req_in_form'] = False
        self.assert_valid(config)
        config = self.mutate('Requirement', 'p_kind_choices', {})
        config = remove_attribute(config, 'Requirement', 'p_kind')
        self.assertNotIn('p_kind', config['cats']['Requirement']['attrs'])
        self.assert_valid(config)


class LayoutTests(Assertions, SimpleTestCase):
    def mutate(self, layout, value):
        config = base_config()
        config['cats']['Packet'][layout] = value
        return config

    def test_layout_must_be_a_list_of_columns(self):
        for layout in ('disp_def', 'disp_short', 'disp_trac'):
            with self.subTest(layout=layout):
                self.assert_error(self.mutate(layout, {}), 'cats.Packet.' + layout, 'must be a list')
                self.assert_error(self.mutate(layout, ['x']), 'cats.Packet.%s[0]' % layout, 'must be an object')

    def test_the_default_display_needs_a_column_the_others_may_be_empty(self):
        self.assert_error(self.mutate('disp_def', []), 'cats.Packet.disp_def', 'at least one column')
        self.assert_valid(self.mutate('disp_short', []))
        self.assert_valid(self.mutate('disp_trac', []))

    def column(self, **column):
        config = base_config()
        config['cats']['Packet']['disp_short'] = [column]
        return config

    def test_columns(self):
        path = 'cats.Packet.disp_short[0]'
        for column, error_path, fragment in (
                ({'attrs': ['title']}, path + '.header', 'is required'),
                ({'header': '', 'attrs': ['title']}, path + '.header', ''),
                ({'header': 5, 'attrs': ['title']}, path + '.header', 'must be a text'),
                ({'header': 'T'}, path, 'exactly one of "attrs" and "trac_cat"'),
                ({'header': 'T', 'attrs': ['title'], 'trac_cat': 'VerLink', 'trac_link': 's_link'}, path, 'exactly one'),
                ({'header': 'T', 'attrs': []}, path + '.attrs', 'must not be empty'),
                ({'header': 'T', 'attrs': 'title'}, path + '.attrs', 'must be a list'),
                ({'header': 'T', 'attrs': ['title', 'nope']}, path + '.attrs[1]', 'unknown attribute "nope"'),
                ({'header': 'T', 'attrs': [3]}, path + '.attrs[0]', 'attribute name'),
                ({'header': 'T', 'attrs': ['title'], 'order_by': 'nope'}, path + '.order_by', 'attribute of the category'),
                ({'header': 'T', 'attrs': ['title'], 'order_by': 5}, path + '.order_by', 'attribute of the category'),
                ({'header': 'T', 'attrs': ['title'], 'trac_link': 's_link'}, path + '.trac_link', 'traceability column'),
                ({'header': 'T', 'attrs': ['title'], 'colour': 1}, path + '.colour', 'unknown setting')):
            with self.subTest(column=column):
                self.assert_error(self.column(**column), error_path, fragment)

    def test_order_by_may_name_an_attribute_outside_the_column(self):
        config = base_config()
        self.assertIn({'header': 'Title', 'attrs': ['title'], 'order_by': 'value'}, config['cats']['Packet']['disp_short'])
        self.assert_valid(config)

    def test_traceability_columns(self):
        path = 'cats.Packet.disp_trac[0]'
        def trac(**column):
            config = base_config()
            config['cats']['Packet']['disp_trac'] = [dict({'header': 'V', 'trac_cat': 'VerLink', 'trac_link': 's_link'}, **column)]
            return config
        self.assert_valid(trac())
        self.assert_error(trac(trac_cat='Nope'), path + '.trac_cat', 'identifier of a category')
        self.assert_error(trac(trac_cat=5), path + '.trac_cat', 'identifier of a category')
        self.assert_error(trac(trac_link='x'), path + '.trac_link', 'must be one of')
        self.assert_error(trac(order_by='title'), path + '.order_by', 'cannot be sorted')
        config = self.column(header='V', trac_cat='VerLink', trac_link='s_link')
        self.assert_error(config, 'cats.Packet.disp_short[0].trac_cat', 'only used in disp_trac')


class DeterminismTests(Assertions, SimpleTestCase):
    def broken(self):
        config = base_config()
        config['cats']['Service']['abbr'] = config['cats']['Packet']['abbr']
        config['cats']['Service']['attrs']['title']['label'] = 'Domain'
        config['cats']['packet'] = minimal_cat()
        config['cats']['Requirement']['page_size'] = 0
        return config

    def test_the_result_does_not_depend_on_the_key_order(self):
        config = self.broken()
        expected = validate_config(config)
        self.assertGreaterEqual(len(expected), 4)
        keys = list(config['cats'])
        rng = random.Random(1)
        for _ in range(10):
            rng.shuffle(keys)
            shuffled = dict(config, cats={key: config['cats'][key] for key in keys})
            self.assertEqual(validate_config(shuffled), expected)

    def test_the_error_list_is_cut(self):
        config = base_config()
        for i in range(2 * MAX_ERRORS):
            config['cats']['bad cat %d' % i] = 1
        errors = validate_config(config)
        self.assertEqual(len(errors), MAX_ERRORS + 1)
        self.assertRegex(errors[-1].message, r'^[1-9][0-9]* more error\(s\) not shown$')
        self.assertEqual(errors[-1].path, '')


class ValidationIsPureTests(Assertions, SimpleTestCase):
    def test_the_argument_is_not_modified(self):
        for config in (base_config(), self.invalid_config()):
            before = copy.deepcopy(config)
            validate_config(config)
            self.assertEqual(config, before)

    def invalid_config(self):
        config = base_config()
        config['cats']['Packet']['links'] = {'p_link': {'targets': ['Nope']}}
        config['cats']['Packet']['disp_def'] = 5
        return config


class MalformedInputTests(Assertions, SimpleTestCase):
    """A malformed configuration yields errors, never an exception (an exception would be an HTTP 500)."""
    BAD_VALUES = (None, True, 0, -1, 1.5, '', 'x' * 300, 'None', [], {}, [1], ['a', None], {'a': 1}, [[]], [{}])

    def small_config(self):
        config = base_config()
        config['cats'] = {cat: config['cats'][cat] for cat in ('Packet', 'Service', 'DataItem', 'Requirement', 'FCP')}
        return config

    def paths(self, node, prefix=()):
        yield prefix
        if isinstance(node, dict):
            for key, value in node.items():
                yield from self.paths(value, prefix + (key,))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                yield from self.paths(value, prefix + (i,))

    def set_path(self, config, path, value):
        node = config
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    def test_every_setting_replaced_by_every_bad_value(self):
        template = self.small_config()
        count = 0
        for path in self.paths(template):
            if not path:
                continue
            for value in self.BAD_VALUES:
                config = copy.deepcopy(template)
                self.set_path(config, path, copy.deepcopy(value))
                with self.subTest(path=path, value=value):
                    errors = validate_config(config)
                    self.assertIsInstance(errors, list)
                    for error in errors:
                        self.assertIsInstance(error, ConfigError)
                        self.assertIsInstance(error.path, str)
                        self.assertIsInstance(error.message, str)
                    if config != template and path[-1] not in ('None',):
                        count += 1
        self.assertGreater(count, 1000)

    def test_most_bad_values_are_reported(self):
        template = self.small_config()
        for path in (('general', 'max_depth'), ('cats', 'Packet', 'page_size'), ('cats', 'Packet', 'attrs'),
                     ('cats', 'Packet', 'links'), ('cats', 'Packet', 'disp_def', 0, 'attrs'), ('cats', 'Packet', 'expand', 's_link')):
            for value in (None, [], 'x', {}, 1.5, True):
                config = copy.deepcopy(template)
                self.set_path(config, path, value)
                with self.subTest(path=path, value=value):
                    self.assertTrue(validate_config(config))

    def test_weird_root_members(self):
        for config in ({1: 2}, {'general': {}, 'cats': {1: {}, None: [], ('a',): 'x'}}, {'general': {5: 1}, 'cats': {}},
                       {'cats': {'A': {'attrs': {3: {}, None: None}, 'disp_def': [{1: 2}], 'links': {5: {}}}}},
                       {'cats': {'A': {'attrs': {'domain': {'kind': ['x'], 'label': {}, 'req_in_form': []}}}}}):
            with self.subTest(config=config):
                self.assertTrue(validate_config(config))

    def test_unhashable_and_odd_values_where_names_are_expected(self):
        config = base_config()
        config['cats']['Packet']['level'] = []
        config['cats']['Packet']['access_from_index'] = {'level': []}
        config['cats']['Packet']['expand'] = {'s_link': [], 'p_link': {}}
        config['cats']['Packet']['tracs'] = [{'trac_cat': [], 'trac_link': {}}]
        config['cats']['Packet']['attrs']['title']['kind'] = {}
        config['cats']['Packet']['disp_def'] = [{'header': 'x', 'attrs': [[]], 'order_by': []}]
        config['cats']['Packet']['p_kind_choices'] = {'A': []}
        self.assertTrue(validate_config(config))


class StoredDataTests(Assertions, EditorTestCase):
    def setUp(self):
        super().setUp()
        self.project, _ = self.make_project('Data', owner=self.owner, cats=ALL_CATS)

    def make(self, cat, name, **fields):
        return self.make_item(self.project, cat, 'D', name, **fields)

    def test_stored_values_which_are_choices_are_valid(self):
        self.make('Packet', 'p', p_kind='TC')
        self.make('Packet', 'q', p_kind='')
        self.make('Requirement', 'r', p_kind='STD', s_kind='TST')
        self.assert_valid(base_config(), self.project)

    def test_a_stored_kind_which_is_not_a_choice_is_reported_with_its_count(self):
        self.make('Packet', 'p', p_kind='TC')
        self.make('Packet', 'q', p_kind='TC', status='OBS')
        config = base_config()
        del config['cats']['Packet']['p_kind_choices']['TC']
        self.assertEqual(self.errors_of(config, self.project),
                         [('cats.Packet.p_kind_choices', 'the stored p_kind value "TC" of 2 item(s) is not a choice')])
        self.assert_valid(config)             # without a project nothing is compared with stored data

    def test_s_kind_is_checked_too(self):
        self.make('Requirement', 'r', s_kind='TST')
        config = base_config()
        del config['cats']['Requirement']['s_kind_choices']['TST']
        self.assert_error(config, 'cats.Requirement.s_kind_choices', 'stored s_kind value "TST" of 1 item(s)', self.project)

    def test_a_hidden_kind_attribute_is_still_checked(self):
        self.make('Packet', 'p', p_kind='TC')
        config = remove_attribute(base_config(), 'Packet', 'p_kind')
        del config['cats']['Packet']['p_kind_choices']['TC']
        self.assert_error(config, 'cats.Packet.p_kind_choices', 'stored p_kind value "TC"', self.project)

    def test_stored_values_of_a_category_which_is_not_in_the_configuration_are_ignored(self):
        self.make('Packet', 'p', p_kind='GONE')
        self.assert_valid(remove_category(base_config(), 'Packet'), self.project)

    def test_other_projects_do_not_matter(self):
        other, _ = self.make_project('Other', owner=self.owner, cats=ALL_CATS)
        self.make_item(other, 'Packet', 'D', 'p', p_kind='GONE')
        self.assert_valid(base_config(), self.project)
        self.assert_error(base_config(), 'cats.Packet.p_kind_choices', '"GONE"', other)

    def test_stored_link_pairs_must_be_allowed(self):
        service = self.make('Service', 's')
        self.make('Packet', 'p', p_link=service)
        self.assert_valid(base_config(), self.project)
        config = base_config()
        config['cats']['Packet']['links']['p_link']['targets'] = ['EnumType']
        self.assert_error(config, 'cats.Packet.links.p_link',
                          'stored p_link of 1 item(s) of category "Packet" point to items of category "Service", '
                          'which this rule does not allow', self.project)
        del config['cats']['Packet']['links']['p_link']
        self.assert_error(config, 'cats.Packet.links.p_link', 'category has no rule for', self.project)
        config['cats']['Packet']['links']['p_link'] = {'all_except': ['Service']}
        self.assert_error(config, 'cats.Packet.links.p_link', 'does not allow', self.project)
        config['cats']['Packet']['links']['p_link'] = {'all_except': []}
        self.assert_valid(config, self.project)

    def test_s_link_pairs_are_checked_too(self):
        enum_type = self.make('EnumType', 'e')
        self.make('Packet', 'p', s_link=enum_type)
        config = base_config()
        config['cats']['Packet']['links']['s_link']['targets'] = ['DataItem']
        self.assert_error(config, 'cats.Packet.links.s_link', 'stored s_link of 1 item(s)', self.project)

    def test_a_link_to_a_hidden_category_is_not_checked_and_restoring_it_is(self):
        service = self.make('Service', 's')
        self.make('Packet', 'p', p_link=service)
        hidden = remove_category(base_config(), 'Service')
        self.assertNotIn('p_link', hidden['cats']['Packet']['links'])        # the reference was cleaned
        self.assert_valid(hidden, self.project)
        restored = copy.deepcopy(hidden)
        restored['cats']['Service'] = copy.deepcopy(base_config()['cats']['Service'])
        self.assert_error(restored, 'cats.Packet.links.p_link', 'category has no rule for', self.project)
        restored['cats']['Packet']['links']['p_link'] = {'targets': ['Service']}
        self.assert_valid(restored, self.project)

    def test_a_malformed_rule_is_reported_once_not_as_a_data_problem(self):
        service = self.make('Service', 's')
        self.make('Packet', 'p', p_link=service)
        config = base_config()
        config['cats']['Packet']['links']['p_link'] = {'targets': 'Service'}
        errors = self.errors_of(config, self.project)
        self.assertEqual([e[0] for e in errors], ['cats.Packet.links.p_link.targets'])

    def test_removing_any_category_with_stored_data_is_allowed(self):
        for cat in ALL_CATS:
            self.make(cat, 'item_' + cat, p_kind='', title='t', value='v', t1='x')
        before = self.snapshot()
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                self.assert_valid(remove_category(base_config(), cat), self.project)
        self.assertEqual(self.snapshot(), before)

    def test_removing_an_attribute_with_stored_data_is_allowed_and_keeps_the_data(self):
        item = self.make('Packet', 'p', title='Title', desc='Desc', value='7', t1='t1', t2='t2', p_kind='TC')
        before = self.snapshot()
        for attr in base_config()['cats']['Packet']['attrs']:
            if attr in ('domain', 'name'):
                continue
            with self.subTest(attr=attr):
                self.assert_valid(remove_attribute(base_config(), 'Packet', attr), self.project)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.refresh(item).title, 'Title')

    def snapshot(self):
        return list(SpecItem.objects.order_by('id').values_list(
            'id', 'cat', 'domain', 'name', 'title', 'desc', 'value', 't1', 'p_kind', 's_kind', 'p_link_id',
            's_link_id', 'status', 'updated_at', 'application_id', 'val_set_id'))

    def test_validation_only_reads(self):
        service = self.make('Service', 's')
        self.make('Packet', 'p', p_link=service, p_kind='GONE')
        self.project.config = base_config()
        self.project.save(update_fields=['config'])
        before = (self.snapshot(), Project.objects.get(id=self.project.id).config)
        config = base_config()
        config['cats']['Packet']['links']['p_link']['targets'] = ['EnumType']
        with CaptureQueriesContext(connection) as queries:
            errors = validate_config(config, self.project)
            remove_category(config, 'Service')
            remove_attribute(config, 'Packet', 'title')
            remove_dangling_references(config)
        self.assertTrue(errors)
        self.assertEqual(len(queries), 1)
        self.assertTrue(queries[0]['sql'].lstrip().upper().startswith('SELECT'))
        self.assertEqual((self.snapshot(), Project.objects.get(id=self.project.id).config), before)


class InitializedConfigurationTests(Assertions, EditorTestCase):
    def test_every_single_category_filter_output_is_valid(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                project, _ = self.make_project('P_' + cat, owner=self.owner, cats=[cat])
                self.assert_valid(filter_template_for_data(load_template(), project), project)

    def test_filter_output_for_data_only_categories_is_valid(self):
        project, _ = self.make_project('Only data', owner=self.owner, cats=[])
        service = self.make_item(project, 'Service', 'D', 's')
        enum_type = self.make_item(project, 'EnumType', 'D', 'e', p_kind='')
        self.make_item(project, 'Packet', 'D', 'p', p_link=service, s_link=enum_type, p_kind='TC', title='T')
        self.make_item(project, 'DataItem', 'D', 'd', value='1', p_kind='CNS')
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(sorted(config['cats']), ['DataItem', 'EnumType', 'Packet', 'Service'])
        self.assert_valid(config, project)

    def test_the_init_command_output_is_valid(self):
        for cats, name in ((ALL_CATS, 'All'), (['Packet', 'Service'], 'Some'), ([], 'None')):
            with self.subTest(name=name):
                project, _ = self.make_project('I_' + name, owner=self.owner, cats=cats)
                stderr = StringIO()
                call_command('init_project_configs', stdout=StringIO(), stderr=stderr)
                project.refresh_from_db()
                self.assertTrue(project.config)
                self.assert_valid(project.config, project)
                self.assertNotIn('configuration problem', stderr.getvalue())

    def test_the_command_reports_problems_of_the_proposal_but_stores_it(self):
        project, _ = self.make_project('Odd data', owner=self.owner, cats=['Packet'])
        self.make_item(project, 'Packet', 'D', 'p', p_kind='LEGACY')
        stderr = StringIO()
        call_command('init_project_configs', stdout=StringIO(), stderr=stderr)
        project.refresh_from_db()
        self.assertIn('Project %d (Odd data): configuration problem at cats.Packet.p_kind_choices: the stored p_kind '
                      'value "LEGACY" of 1 item(s) is not a choice' % project.id, stderr.getvalue())
        self.assertTrue(project.config)

    def test_a_filtered_configuration_uses_the_shared_cleanup(self):
        project, _ = self.make_project('Shared', owner=self.owner, cats=['Packet'])
        with mock.patch.object(project_config, 'remove_dangling_references', wraps=remove_dangling_references) as spy:
            filter_template_for_data(load_template(), project)
        spy.assert_called_once()


class CleanupTests(Assertions, SimpleTestCase):
    REFERENCING = ('expand', 'tracs', 'links', 'validators', 'disp_trac')

    def test_removing_a_category_removes_the_references_to_it(self):
        config = remove_category(base_config(), 'Packet')
        cats = config['cats']
        self.assertNotIn('Packet', cats)
        self.assertEqual(cats['Service']['expand'], {'p_link': 'None', 'p_label': 'Packet', 's_link': 'None'})
        self.assertNotIn({'trac_cat': 'Packet', 'trac_link': 'p_link'}, cats['DerPacket']['tracs'])
        self.assertEqual(cats['PacketPar']['links'].get('p_link'), {'targets': ['DerPacket']})
        self.assertEqual(cats['InCommand']['links']['p_link'], {'targets': ['DerPacket']})
        self.assert_valid(config)

    def test_removing_a_link_category_removes_the_traceability_references(self):
        config = remove_category(base_config(), 'VerLink')
        for cat, definition in config['cats'].items():
            with self.subTest(cat=cat):
                self.assertNotIn('VerLink', [t['trac_cat'] for t in definition['tracs']])
                self.assertNotIn('VerLink', [c.get('trac_cat') for c in definition['disp_trac']])
                self.assertNotIn('VerLink', json.dumps(definition['links']))
        self.assertEqual(config['cats']['Requirement']['tracs'], [])
        self.assertEqual(config['cats']['ParReq']['tracs'], [{'trac_cat': 'TracLink', 'trac_link': 's_link'}])
        self.assert_valid(config)

    def test_removing_the_enumerated_value_category_removes_the_validator_and_nothing_else(self):
        config = remove_category(base_config(), 'EnumValue')
        self.assertEqual(config['cats']['DataItem']['validators'], [])
        self.assertEqual(config['cats']['EnumType']['expand']['s_link'], 'None')
        self.assertEqual(config['cats']['DataItem']['links'], base_config()['cats']['DataItem']['links'])
        self.assert_valid(config)

    def test_every_category_can_be_removed_without_touching_unrelated_ones(self):
        original = base_config()
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                before = copy.deepcopy(original)
                config = remove_category(original, cat)
                self.assertEqual(original, before)              # the argument is not modified
                self.assert_valid(config)
                self.assertEqual(config['general'], original['general'])
                self.assertEqual(list(config['cats']), [c for c in original['cats'] if c != cat])
                for other in config['cats']:
                    for key, value in original['cats'][other].items():
                        if config['cats'][other][key] != value:
                            self.assertIn(key, self.REFERENCING, '%s.%s changed without referencing %s' % (other, key, cat))
                            self.assertIn(cat, json.dumps(value), '%s.%s did not refer to %s' % (other, key, cat))

    def test_removing_an_attribute_removes_the_references_to_it(self):
        original = base_config()
        config = remove_attribute(original, 'DataItem', 'value')
        definition = config['cats']['DataItem']
        self.assertNotIn('value', definition['attrs'])
        self.assertEqual(definition['validators'], [])
        for names in definition['short_desc'].values():
            self.assertNotIn('value', names)
        for layout in ('disp_def', 'disp_short', 'disp_trac'):
            for column in definition[layout]:
                self.assertNotIn('value', column.get('attrs', []))
                self.assertNotEqual(column.get('order_by'), 'value')
        self.assertEqual(config['cats']['Packet'], original['cats']['Packet'])
        self.assert_valid(config)

    def test_a_column_left_without_attributes_is_removed_and_an_order_by_on_a_removed_attribute_too(self):
        original = base_config()
        packet = remove_attribute(original, 'Packet', 'title')['cats']['Packet']
        self.assertNotIn({'header': 'Title', 'attrs': ['title'], 'order_by': 'value'}, packet['disp_short'])
        self.assertEqual(len(packet['disp_short']), len(original['cats']['Packet']['disp_short']) - 1)
        packet = remove_attribute(original, 'Packet', 'value')['cats']['Packet']
        self.assertIn({'header': 'Title', 'attrs': ['title']}, packet['disp_short'])       # order_by dropped, column kept
        self.assert_valid(remove_attribute(original, 'Packet', 'value'))

    def test_ext_attrs_are_cleaned(self):
        config = remove_attribute(base_config(), 'FCP', 'n3')
        self.assertNotIn('n3', config['cats']['FCP']['ext_attrs'])
        self.assert_valid(config)

    def test_every_attribute_can_be_removed_without_touching_anything_else(self):
        original = base_config()
        for cat, definition in original['cats'].items():
            for attr in definition['attrs']:
                with self.subTest(cat=cat, attr=attr):
                    config = remove_attribute(original, cat, attr)
                    errors = self.errors_of(config)
                    if attr in ('domain', 'name'):
                        self.assertEqual(errors, [('cats.%s.attrs.%s' % (cat, attr), 'is required')])
                    else:
                        self.assertEqual(errors, [])
                    self.assertEqual({c: d for c, d in config['cats'].items() if c != cat},
                                     {c: d for c, d in original['cats'].items() if c != cat})
                    self.assertEqual({k: v for k, v in config['cats'][cat].items() if k not in self.REFERENCING + ('attrs', 'ext_attrs', 'short_desc', 'disp_def', 'disp_short')},
                                     {k: v for k, v in original['cats'][cat].items() if k not in self.REFERENCING + ('attrs', 'ext_attrs', 'short_desc', 'disp_def', 'disp_short')})

    def test_removing_what_does_not_exist_changes_nothing(self):
        original = base_config()
        self.assertEqual(remove_category(original, 'Nope'), original)
        self.assertEqual(remove_attribute(original, 'Nope', 'title'), original)
        self.assertEqual(remove_attribute(original, 'Packet', 'nope'), original)

    def test_a_removed_attribute_can_be_defined_again_with_the_same_identifier(self):
        original = base_config()
        removed = remove_attribute(original, 'Packet', 't1')
        removed['cats']['Packet']['attrs']['t1'] = copy.deepcopy(original['cats']['Packet']['attrs']['t1'])
        self.assert_valid(removed)

    def test_dangling_references_of_a_hand_edited_configuration_are_removed(self):
        config = base_config()
        del config['cats']['Service']
        del config['cats']['Packet']['attrs']['t2']
        self.assertTrue(self.errors_of(config))
        cleaned = remove_dangling_references(config)
        self.assert_valid(cleaned)
        self.assertEqual(cleaned['cats']['Packet']['links'].get('p_link'), None)
        self.assertEqual(remove_dangling_references(cleaned), cleaned)           # idempotent

    def test_a_valid_configuration_is_unchanged_by_the_cleanup(self):
        config = base_config()
        self.assertEqual(remove_dangling_references(config), config)
        self.assertIsNot(remove_dangling_references(config), config)

    def test_malformed_parts_are_left_alone(self):
        config = base_config()
        config['cats']['Packet']['links'] = {'p_link': 'x', 's_link': {'targets': 'x'}}
        config['cats']['Packet']['validators'] = 'x'
        config['cats']['Packet']['disp_def'] = [1, {'attrs': 'x'}, {'attrs': [5]}]
        config['cats']['Packet']['tracs'] = ['x', {'trac_cat': 5}]
        config['cats']['Packet']['expand'] = {'s_link': 5, 'p_link': []}
        config['cats']['Packet']['short_desc'] = {'expand_text': 'x'}
        config['cats']['Service'] = 'x'
        config['cats']['PacketPar']['attrs'] = []
        for result in (remove_dangling_references(config), remove_category(config, 'Packet'),
                       remove_attribute(config, 'Packet', 'title')):
            self.assertIsInstance(result, dict)
        for bad in (None, [], 'x', {'cats': []}, {'cats': {'A': []}}):
            self.assertEqual(remove_dangling_references(bad), bad)
            self.assertEqual(remove_attribute(bad, 'A', 'title'), bad)
        for bad in (None, [], 'x', {'cats': []}):
            self.assertEqual(remove_category(bad, 'A'), bad)
        self.assertEqual(remove_category({'cats': {'A': []}}, 'A'), {'cats': {}})


class SharedEntryPointTests(Assertions, EditorTestCase):
    """The form (payload), raw JSON and file entry points all go through validate_config."""

    def invalid_config(self):
        config = base_config()
        config['cats']['Packet']['page_size'] = 0
        config['cats']['Packet']['links']['p_link']['targets'] = ['Nope']
        return config

    def test_all_three_entry_points_give_the_same_errors(self):
        config = self.invalid_config()
        expected = validate_config(config)
        self.assertEqual([e.path for e in expected], ['cats.Packet.page_size', 'cats.Packet.links.p_link.targets[0]'])
        text = json.dumps(config)
        for result in (validate_config_json(text), validate_config_json(text.encode()),
                       validate_config_file(SimpleUploadedFile('c.json', text.encode()))):
            parsed, errors = result
            self.assertEqual(parsed, config)
            self.assertEqual(errors, expected)

    def test_all_three_entry_points_call_the_one_validator(self):
        config = base_config()
        text = json.dumps(config)
        with mock.patch.object(config_validation, 'validate_config', wraps=validate_config) as spy:
            validate_config_json(text, self.project)
            validate_config_file(SimpleUploadedFile('c.json', text.encode()), self.project)
        self.assertEqual(spy.call_count, 2)
        self.assertTrue(all(call.args[1] is self.project for call in spy.call_args_list))

    def test_valid_input_through_every_entry_point(self):
        config = base_config()
        text = json.dumps(config, indent=2)
        self.assertEqual(validate_config_json(text, self.project), (config, []))
        self.assertEqual(validate_config_file(SimpleUploadedFile('c.json', text.encode()), self.project), (config, []))

    def test_the_stored_data_is_checked_for_json_and_file_input_too(self):
        self.make_item(self.project, 'Packet', 'D', 'p', p_kind='TC')
        config = base_config()
        del config['cats']['Packet']['p_kind_choices']['TC']
        text = json.dumps(config)
        for _, errors in (validate_config_json(text, self.project),
                          validate_config_file(SimpleUploadedFile('c.json', text.encode()), self.project)):
            self.assertEqual([e.path for e in errors], ['cats.Packet.p_kind_choices'])

    def test_a_project_configuration_can_be_downloaded_and_uploaded_again(self):
        self.project.config = base_config()
        self.project.save(update_fields=['config'])
        stored = Project.objects.get(id=self.project.id).config
        text = json.dumps(stored, indent=2, sort_keys=True)
        self.assertEqual(validate_config_json(text, self.project), (stored, []))

    def test_json_syntax_errors_have_a_position(self):
        config, errors = validate_config_json('{\n "general": {,}\n}')
        self.assertIsNone(config)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].path, '')
        self.assertIn('invalid JSON at line 2, column 14', errors[0].message)

    def test_json_which_is_not_an_object_is_reported_by_the_validator(self):
        for text in ('[]', '5', 'null', '"x"', 'true'):
            with self.subTest(text=text):
                config, errors = validate_config_json(text)
                self.assertEqual(errors, [ConfigError('', 'the configuration must be a JSON object')])

    def test_constants_which_are_not_json_are_rejected(self):
        for text in ('{"general": NaN}', '{"general": Infinity}', '{"general": -Infinity}'):
            with self.subTest(text=text):
                config, errors = validate_config_json(text)
                self.assertIsNone(config)
                self.assertIn('is not allowed', errors[0].message)

    def test_duplicate_keys_are_reported_with_their_path(self):
        text = json.dumps(base_config()).replace('"page_size": 100', '"page_size": 100, "page_size": 5', 1)
        config, errors = validate_config_json(text)
        self.assertTrue(any(e.path.endswith('.page_size') and 'more than once' in e.message for e in errors))
        text = '{"general": {"csv_sep": "|", "csv_sep": ";"}, "cats": {"A": {}, "A": {}}}'
        _, errors = validate_config_json(text)
        self.assertIn(ConfigError('general.csv_sep', 'the key occurs more than once in the object'), errors)
        self.assertIn(ConfigError('cats.A', 'the key occurs more than once in the object'), errors)

    def test_input_limits(self):
        big = '{"x": "%s"}' % ('a' * MAX_JSON_BYTES)
        for data in (big, big.encode()):
            config, errors = validate_config_json(data)
            self.assertIsNone(config)
            self.assertIn('larger than', errors[0].message)
        config, errors = validate_config_file(SimpleUploadedFile('c.json', big.encode()))
        self.assertIsNone(config)
        self.assertIn('larger than', errors[0].message)

    def test_encoding_and_input_types(self):
        config, errors = validate_config_json(b'\xff\xfe{')
        self.assertIsNone(config)
        self.assertIn('UTF-8', errors[0].message)
        bom = b'\xef\xbb\xbf' + json.dumps(base_config()).encode()
        self.assertEqual(validate_config_json(bom)[1], [])
        for value in (None, 5, [], {}):
            self.assertEqual(validate_config_json(value)[0], None)

    def test_deeply_nested_json_is_an_error_not_a_crash(self):
        for text in ('[' * 100000, '{"a":' * 100000, '[' * 100000 + ']' * 100000):
            with self.subTest(text=text[:5]):
                config, errors = validate_config_json(text)
                self.assertIsNone(config)
                self.assertEqual(len(errors), 1)

    def test_unreadable_files(self):
        class Broken:
            def read(self, size):
                raise OSError('boom')
        config, errors = validate_config_file(Broken())
        self.assertIsNone(config)
        self.assertEqual(errors, [ConfigError('', 'the file cannot be read')])

    def test_a_server_setting_in_an_uploaded_file_is_rejected(self):
        text = json.dumps(load_template())
        _, errors = validate_config_file(SimpleUploadedFile('c.json', text.encode()))
        self.assertEqual([e.path for e in errors], ['general.temp_dir'])
