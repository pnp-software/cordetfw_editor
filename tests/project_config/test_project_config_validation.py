"""Every rule has an invalid case (asserting the exact JSON path of the error) and a valid case. Validation through
the HTTP endpoints, the UI and the archive import is tested in test_project_config_{endpoints,ui,archive}.py."""
import json
import re
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext

from editor import config_validation, project_config
from editor.config_cleanup import (copy_config, has_hidden_attributes, remove_attribute, remove_category,
                                   remove_dangling_references)
from editor.config_validation import (ALLOWED_KINDS, MAX_ERRORS, MAX_JSON_BYTES, config_error, error_text, key_path,
                                      validate_config, validate_config_file, validate_config_json)
from editor.models import Project, SpecItem
from editor.project_config import DATA_COLUMNS, filter_template_for_data, load_template, new_project_config
from tests.project_config.base import ALL_CATS, TEMPLATE, make_item, make_project, refresh

pytestmark = pytest.mark.django_db

REFERENCING = ('expand', 'tracs', 'links', 'validators', 'disp_trac')
BAD_VALUES = (None, True, 0, -1, 1.5, '', 'x' * 300, 'None', [], {}, [1], ['a', None], {'a': 1}, [[]], [{}])


def base_config():
    return new_project_config()


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


def with_setting(cat, key, value):
    config = base_config()
    config['cats'][cat][key] = value
    return config


def hide(config, cat, *attrs):
    """`config` with the attributes `attrs` of `cat` marked hidden (changed in place and returned)."""
    for attr in attrs:
        config['cats'][cat]['attrs'][attr]['hidden'] = True
    return config


def errors_of(config, project=None):
    return [(error['path'], error['message']) for error in validate_config(config, project)]


def assert_valid(config, project=None):
    assert errors_of(config, project) == []


def assert_error(config, path, fragment, project=None):
    errors = errors_of(config, project)
    assert any(p == path and fragment in m for p, m in errors), \
        'no error at %r containing %r in %r' % (path, fragment, errors)


def assert_no_error_at(config, path, project=None):
    errors = errors_of(config, project)
    assert [e for e in errors if e[0] == path] == [], errors


@pytest.fixture
def project():
    return make_project('Proj')[0]


# ------------------------------------------------------------------ structure

def test_the_template_without_server_settings_is_valid():
    assert_valid(base_config())


def test_the_raw_template_only_differs_by_the_server_setting():
    assert [e['path'] for e in validate_config(load_template())] == ['general.temp_dir']


def test_a_new_category_is_valid():
    assert_valid(with_new_cat())


@pytest.mark.parametrize('value', [None, [], 'x', 1, True, 1.5])
def test_root_must_be_an_object(value):
    assert validate_config(value) == [config_error('', 'the configuration must be a JSON object')]


def test_top_level_keys():
    config = base_config()
    config['extra'] = 1
    assert_error(config, 'extra', 'unknown setting')
    for key in ('general', 'cats'):
        config = base_config()
        del config[key]
        assert_error(config, key, 'is required')
    for key, value in (('general', []), ('general', None), ('cats', []), ('cats', 'x')):
        config = base_config()
        config[key] = value
        assert_error(config, key, 'must be an object')


def test_the_error_contract():
    error = config_error('cats.A.b', 'bad')
    assert error == {'path': 'cats.A.b', 'message': 'bad'}
    assert error_text(error) == 'cats.A.b: bad'
    assert error_text(config_error('', 'bad')) == '(root): bad'
    assert key_path('cats', 'Packet') == 'cats.Packet'
    assert key_path('', 'cats') == 'cats'
    assert key_path('cats.A', 'a.b') == 'cats.A["a.b"]'
    assert key_path('', 5) == '[5]'


# ------------------------------------------------------------------ general settings

def test_server_settings_are_rejected():
    config = base_config()
    config['general']['temp_dir'] = '/tmp'
    assert_error(config, 'general.temp_dir', 'server setting')


def test_unknown_and_missing_settings():
    config = base_config()
    config['general']['colour'] = 'red'
    assert_error(config, 'general.colour', 'unknown setting')
    for key in ('csv_sep', 'eol_sep', 'short_desc_len', 'max_depth'):
        config = base_config()
        del config['general'][key]
        assert_error(config, 'general.' + key, 'is required')


GENERAL_VALUES = {
    'csv_sep': (['', 'ab', 'a', '1', ' ', '"', '\n', '\r', 5, None, ['|']], ['|', ';', ',', '\t', '#']),
    'eol_sep': (['', 'x', '\r', None, 1, ['\n']], ['\n', '\r\n']),
    'short_desc_len': ([9, 1001, 0, True, '100', 100.0, None, -5], [10, 100, 1000]),
    'max_depth': ([0, 501, True, -1, '200', 2.5, None], [1, 200, 500]),
}


@pytest.mark.parametrize('key,value', [(key, value) for key, (bad, _) in GENERAL_VALUES.items() for value in bad])
def test_general_setting_bad_values(key, value):
    config = base_config()
    config['general'][key] = value
    assert_error(config, 'general.' + key, '')


@pytest.mark.parametrize('key,value', [(key, value) for key, (_, good) in GENERAL_VALUES.items() for value in good])
def test_general_setting_good_values(key, value):
    config = base_config()
    config['general'][key] = value
    assert_valid(config)


# ------------------------------------------------------------------ category identifiers and settings

@pytest.mark.parametrize('name', ['1Cat', 'a b', 'a-b', 'x' * 25, '', 'Pa.cket', 'Café', 'Cat/x', 'a,b', 'a|b',
                                  '_x'])
def test_invalid_identifiers(name):
    assert_error(with_new_cat(name), key_path('cats', name), 'category identifier')


@pytest.mark.parametrize('name', ['x' * 24, 'My_Cat2', 'A', 'Packet2'])
def test_valid_identifiers(name):
    config = with_new_cat(name)
    config['cats'][name]['name'] = 'Name of ' + name
    config['cats'][name]['abbr'] = name[:24]
    assert_valid(config)


@pytest.mark.parametrize('name', ['None', 'none', 'NONE'])
def test_none_is_reserved(name):
    assert_error(with_new_cat(name), 'cats.' + name, 'reserved')


def test_identifiers_must_be_unique_ignoring_case():
    assert_error(with_new_cat('packet'), 'cats.packet', 'differs only in case from "Packet"')


def test_category_must_be_an_object():
    config = base_config()
    config['cats']['Packet'] = []
    assert_error(config, 'cats.Packet', 'must be an object')
    config = base_config()
    config['cats']['Packet']['colour'] = 'red'
    assert_error(config, 'cats.Packet.colour', 'unknown setting')


@pytest.mark.parametrize('key', config_validation.CAT_KEYS)
def test_category_must_have_every_setting(key):
    config = base_config()
    del config['cats']['Packet'][key]
    assert_error(config, 'cats.Packet.' + key, 'is required')


@pytest.mark.parametrize('value', ['', ' x', 'x ', 5, None, 'x' * 101, 'a\nb', ['x']])
def test_display_name(value):
    assert_error(with_setting('Packet', 'name', value), 'cats.Packet.name', '')


def test_long_display_name():
    assert_valid(with_setting('Packet', 'name', 'x' * 100))


def test_display_names_are_unique_ignoring_case():
    assert_error(with_setting('Service', 'name', 'packet'), 'cats.Service.name', 'already used by category "Packet"')


@pytest.mark.parametrize('value', ['', 'a b', 'x' * 25, 5, None, 'a.b', 'a\n'])
def test_abbreviation(value):
    assert_error(with_setting('Packet', 'abbr', value), 'cats.Packet.abbr', '')


def test_abbreviation_characters():
    assert_valid(with_setting('Packet', 'abbr', 'Pck_1-'))


def test_abbreviations_are_unique_ignoring_case():
    assert_error(with_setting('Service', 'abbr', 'pckt'), 'cats.Service.abbr', 'already used by category "Packet"')


@pytest.mark.parametrize('value', ['Project', 'x', None, 1, ['project']])
def test_level(value):
    assert_error(with_setting('Packet', 'level', value), 'cats.Packet.level', 'must be one of')


@pytest.mark.parametrize('value', [0, 1001, True, '100', 1.5, None, -1])
def test_page_size(value):
    assert_error(with_setting('Packet', 'page_size', value), 'cats.Packet.page_size', 'integer from 1 to 1000')


@pytest.mark.parametrize('value', [1, 100, 1000])
def test_valid_page_size(value):
    assert_valid(with_setting('Packet', 'page_size', value))


def test_access_from_index():
    path = 'cats.Packet.access_from_index'
    assert_error(with_setting('Packet', 'access_from_index', []), path, 'must be an object')
    assert_error(with_setting('Packet', 'access_from_index', {}), path + '.level', 'is required')
    assert_error(with_setting('Packet', 'access_from_index', {'level': 'project'}), path + '.level', 'must be one of')
    assert_error(with_setting('Packet', 'access_from_index', {'level': 'Project', 'x': 1}), path + '.x', 'unknown')


def test_access_from_index_must_fit_the_level():
    assert_error(with_setting('Packet', 'access_from_index', {'level': 'Application'}),
                 'cats.Packet.access_from_index.level', 'level "project"')
    assert_error(with_setting('Requirement', 'access_from_index', {'level': 'Project'}),
                 'cats.Requirement.access_from_index.level', 'level "application"')
    assert_valid(with_setting('Packet', 'access_from_index', {'level': 'None'}))
    assert_valid(with_setting('Requirement', 'access_from_index', {'level': 'None'}))


def test_a_category_which_is_not_reachable_from_the_index_is_valid():
    assert base_config()['cats']['EnumValue']['access_from_index'] == {'level': 'None'}
    assert_valid(base_config())


# ------------------------------------------------------------------ attributes

def test_allowed_fields_are_the_item_model_fields_with_data():
    assert set(ALLOWED_KINDS) == set(DATA_COLUMNS)


def test_attrs_must_be_an_object():
    assert_error(with_setting('Packet', 'attrs', []), 'cats.Packet.attrs', 'must be an object')


@pytest.mark.parametrize('name', ['domain', 'name'])
def test_domain_and_name_are_mandatory(name):
    config = base_config()
    del config['cats']['Packet']['attrs'][name]
    assert_error(config, 'cats.Packet.attrs.' + name, 'is required')
    config = base_config()
    config['cats']['Packet']['attrs'][name]['req_in_form'] = False
    assert_error(config, 'cats.Packet.attrs.%s.req_in_form' % name, 'must be true')


@pytest.mark.parametrize('field', ['status', 's_data', 'project', 'application', 'previous', 'created_at',
                                   'updated_at', 'id', 'foo', 'n4', 'cat', 'Title', ''])
def test_only_fields_of_the_item_model(field):
    config = base_config()
    config['cats']['Packet']['attrs'][field] = {'label': 'Extra', 'req_in_form': False, 'kind': 'plain_text'}
    assert_error(config, key_path('cats.Packet.attrs', field), 'not a field of the item model')


@pytest.mark.parametrize('field', list(ALLOWED_KINDS))
@pytest.mark.parametrize('kind', ['plain_text', 'ref_text', 'plain_ref', 'spec_item_ref', 'eval_ref', 'int', 'image',
                                  'date', 'table', 'foo', '', 5, None, ['int']])
def test_every_field_with_each_kind(field, kind):
    attrs = {'domain': {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
             'name': {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'}}
    attrs[field] = {'label': 'Other ' + field, 'req_in_form': field in ('domain', 'name'), 'kind': kind}
    config = with_new_cat(attrs=attrs, short_desc={'expand_text': [], 'href_tip': [], 'expand_tip': []})
    errors = [e for e in errors_of(config) if e[0].startswith('cats.Widget.attrs')]
    if kind in ALLOWED_KINDS[field]:
        assert errors == []
    else:
        assert [e[0] for e in errors] == ['cats.Widget.attrs.%s.kind' % field]


@pytest.mark.parametrize('value', ['', ' x', 'x ', 5, None, 'x' * 101, 'a\tb', ['x']])
def test_label(value):
    config = base_config()
    config['cats']['Packet']['attrs']['title']['label'] = value
    assert_error(config, 'cats.Packet.attrs.title.label', '')


@pytest.mark.parametrize('label', ['Domain', 'domain', 'D o m a i n'])
def test_labels_are_unique_ignoring_blanks_and_case(label):
    config = base_config()
    config['cats']['Packet']['attrs']['title']['label'] = label
    assert_error(config, 'cats.Packet.attrs.title.label', 'already used by attribute "domain"')


@pytest.mark.parametrize('value', ['yes', 1, None, 'true', []])
def test_req_in_form_is_a_boolean(value):
    config = base_config()
    config['cats']['Packet']['attrs']['title']['req_in_form'] = value
    assert_error(config, 'cats.Packet.attrs.title.req_in_form', 'true or false')


def test_req_in_form_false():
    config = base_config()
    config['cats']['Packet']['attrs']['title']['req_in_form'] = False
    assert_valid(config)


def test_attribute_structure():
    config = base_config()
    config['cats']['Packet']['attrs']['title'] = 'x'
    assert_error(config, 'cats.Packet.attrs.title', 'must be an object')
    config = base_config()
    config['cats']['Packet']['attrs']['title']['colour'] = 1
    assert_error(config, 'cats.Packet.attrs.title.colour', 'unknown setting')
    for key in ('label', 'req_in_form', 'kind'):
        config = base_config()
        del config['cats']['Packet']['attrs']['title'][key]
        assert_error(config, 'cats.Packet.attrs.title.' + key, 'is required')


# ------------------------------------------------------------------ external attributes

def test_external_categories_of_the_template_are_valid():
    config = base_config()
    assert config['cats']['FCP']['ext_attrs'] and config['cats']['Model']['ext_attrs']
    assert_valid(config)


def test_ext_attrs_must_name_attributes_of_the_category():
    config = base_config()
    config['cats']['FCP']['ext_attrs'].append('nope')
    assert_error(config, 'cats.FCP.ext_attrs[8]', 'unknown attribute "nope"')


@pytest.mark.parametrize('value,path,fragment', [
    ('title', 'cats.FCP.ext_attrs', 'must be a list'),
    ([5], 'cats.FCP.ext_attrs[0]', 'must be an attribute name'),
    (['domain', 'domain'], 'cats.FCP.ext_attrs', 'twice')])
def test_ext_attrs_must_be_a_list_of_names_without_duplicates(value, path, fragment):
    assert_error(with_setting('FCP', 'ext_attrs', value), path, fragment)


def test_a_category_without_external_support_cannot_load_attributes_from_outside():
    assert_error(with_setting('Packet', 'ext_attrs', ['title']), 'cats.Packet.ext_attrs', 'external repository')
    assert_error(with_new_cat(ext_attrs=['title']), 'cats.Widget.ext_attrs', 'external repository')


# ------------------------------------------------------------------ references

@pytest.mark.parametrize('value,path,fragment', [
    ([], '', 'must be an object'),
    ({'s_link': 'DerPacket', 's_label': 'x'}, '.p_link', 'is required'),
    ({'p_link': 'PacketPar', 'p_label': 'x'}, '.s_link', 'is required'),
    ({'s_link': 'Nope', 'p_link': 'None'}, '.s_link', 'identifier of a category'),
    ({'s_link': 5, 'p_link': 'None'}, '.s_link', 'identifier of a category'),
    ({'s_link': 'None', 'p_link': 'None', 'x': 1}, '.x', 'unknown setting'),
    ({'s_link': 'DerPacket', 'p_link': 'None'}, '.s_label', 'is required'),
    ({'s_link': 'None', 'p_link': 'PacketPar'}, '.p_label', 'is required'),
    ({'s_link': 'None', 'p_link': 'None', 'p_label': ''}, '.p_label', '')])
def test_expand(value, path, fragment):
    assert_error(with_setting('Packet', 'expand', value), 'cats.Packet.expand' + path, fragment)


def test_expand_with_none_and_without_labels_is_valid():
    assert_valid(with_setting('Packet', 'expand', {'s_link': 'None', 'p_link': 'None'}))


def test_short_desc():
    path = 'cats.Packet.short_desc'
    assert_error(with_setting('Packet', 'short_desc', []), path, 'must be an object')
    for key in ('expand_text', 'href_tip', 'expand_tip'):
        config = base_config()
        del config['cats']['Packet']['short_desc'][key]
        assert_error(config, path + '.' + key, 'is required')
        config = base_config()
        config['cats']['Packet']['short_desc'][key] = ['title', 'nope']
        assert_error(config, '%s.%s[1]' % (path, key), 'unknown attribute "nope"')
        config['cats']['Packet']['short_desc'][key] = 'title'
        assert_error(config, path + '.' + key, 'must be a list')
        config['cats']['Packet']['short_desc'][key] = [3]
        assert_error(config, path + '.' + key + '[0]', 'attribute name')
        config['cats']['Packet']['short_desc'][key] = []
        assert_valid(config)
    config = base_config()
    config['cats']['Packet']['short_desc']['colour'] = []
    assert_error(config, path + '.colour', 'unknown setting')


@pytest.mark.parametrize('value,path,fragment', [
    ('x', '', 'must be a list'),
    (['x'], '[0]', 'must be an object'),
    ([{'trac_cat': 'Nope', 'trac_link': 'p_link'}], '[0].trac_cat', 'unknown category "Nope"'),
    ([{'trac_cat': 5, 'trac_link': 'p_link'}], '[0].trac_cat', 'category name'),
    ([{'trac_cat': 'VerLink', 'trac_link': 'x'}], '[0].trac_link', 'must be one of'),
    ([{'trac_cat': 'VerLink', 'trac_link': 'p_link', 'x': 1}], '[0].x', 'unknown setting')])
def test_tracs(value, path, fragment):
    assert_error(with_setting('Requirement', 'tracs', value), 'cats.Requirement.tracs' + path, fragment)


@pytest.mark.parametrize('value,path,fragment', [
    ([], '', 'must be an object'),
    ({'q_link': {'targets': ['Service']}}, '.q_link', 'unknown link'),
    ({'p_link': {'targets': ['Nope']}}, '.p_link.targets[0]', 'unknown category "Nope"'),
    ({'p_link': {'targets': []}}, '.p_link.targets', 'non-empty'),
    ({'p_link': {'targets': ['Service'], 'all_except': []}}, '.p_link', 'exactly one'),
    ({'p_link': {}}, '.p_link', 'exactly one'),
    ({'p_link': {'targets': ['Service'], 'scope': 'x'}}, '.p_link.scope', 'must be one of'),
    ({'p_link': {'targets': ['Service'], 'order_by': ['x']}}, '.p_link.order_by', 'must be a non-empty list'),
    ({'p_link': {'targets': ['Service'], 'colour': 1}}, '.p_link.colour', 'unknown setting'),
    ({'p_link': {'targets': ['Service'], 'narrow_by_other_parent': {'target_field': 'x', 'parent_field': 's_link'}}},
     '.p_link.narrow_by_other_parent.target_field', 'must be one of'),
    ({'p_link': 'Service'}, '.p_link', 'must be an object')])
def test_links(value, path, fragment):
    assert_error(with_setting('Packet', 'links', value), 'cats.Packet.links' + path, fragment)


def test_all_except_may_be_empty_and_rules_with_every_setting_are_valid():
    config = with_setting('Packet', 'links', {
        'p_link': {'all_except': []},
        's_link': {'targets': ['EnumType'], 'scope': 'application', 'order_by': ['cat', 'name'],
                   'narrow_by_other_parent': {'target_field': 's_link', 'parent_field': 'p_link'}}})
    assert_valid(config)


@pytest.mark.parametrize('mutate,path,fragment', [
    (lambda s: s.update(name='os.system'), '[0].name', 'unknown validator'),
    (lambda s: s.update(name='__import__'), '[0].name', 'unknown validator'),
    (lambda s: s.update(name=5), '[0].name', 'unknown validator'),
    (lambda s: s['params'].update(ref_cat='Nope'), '[0].params.ref_cat', 'unknown category'),
    (lambda s: s['params'].update(field='nope'), '[0].params.field', 'unknown attribute'),
    (lambda s: s['params'].update(link='x_link'), '[0].params.link', 'must be one of'),
    (lambda s: s['params'].update(extra='x'), '[0].params.extra', 'unknown parameter'),
    (lambda s: s['params'].pop('message'), '[0].params.message', 'is required'),
    (lambda s: s['params'].update(message='x' * 301), '[0].params.message', 'at most'),
    (lambda s: s.update(params=[]), '[0].params', 'must be an object'),
    (lambda s: s.update(colour=1), '[0].colour', 'unknown setting')])
def test_validators(mutate, path, fragment):
    config = base_config()
    mutate(config['cats']['DataItem']['validators'][0])
    assert_error(config, 'cats.DataItem.validators' + path, fragment)


def test_validators_must_be_a_list_of_objects():
    path = 'cats.DataItem.validators'
    config = with_setting('DataItem', 'validators', 'x')
    assert_error(config, path, 'must be a list')
    config['cats']['DataItem']['validators'] = ['x']
    assert_error(config, path + '[0]', 'must be an object')


def test_validators_must_name_attributes_of_their_own_category():
    config = base_config()
    config['cats']['EnumValue']['validators'] = copy_config(config['cats']['DataItem']['validators'])
    del config['cats']['EnumValue']['attrs']['value']
    assert_error(config, 'cats.EnumValue.validators[0].params.field',
                 'unknown attribute "value" of category "EnumValue"')


# ------------------------------------------------------------------ choice lists

@pytest.mark.parametrize('kind', ['p_kind', 's_kind'])
def test_choice_lists_must_be_objects(kind):
    path = 'cats.Requirement.%s_choices' % kind
    assert_error(with_setting('Requirement', kind + '_choices', []), path, 'must be an object')
    assert_valid(with_setting('Requirement', kind + '_choices', {'n.a.': 'Not applicable', 'x' * 24: 'Long'}))


@pytest.mark.parametrize('kind', ['p_kind', 's_kind'])
@pytest.mark.parametrize('value', ['', 'a b', 'x' * 25, 'a\tb', 5, None])
def test_choice_values(kind, value):
    path = 'cats.Requirement.%s_choices' % kind
    config = with_setting('Requirement', kind + '_choices', {value: 'Label', 'OK': 'Fine'})
    assert_error(config, key_path(path, value), '')


@pytest.mark.parametrize('kind', ['p_kind', 's_kind'])
@pytest.mark.parametrize('label', ['', ' x', 5, None, 'x' * 101])
def test_choice_labels(kind, label):
    path = 'cats.Requirement.%s_choices' % kind
    assert_error(with_setting('Requirement', kind + '_choices', {'TST': label}), path + '.TST', '')


def test_choice_values_with_dots_use_the_bracket_notation():
    errors = errors_of(with_setting('Requirement', 'p_kind_choices', {'n.a.': ''}))
    assert errors[0][0] == 'cats.Requirement.p_kind_choices["n.a."]'


def test_a_shown_and_required_kind_needs_choices():
    assert base_config()['cats']['Requirement']['attrs']['p_kind']['req_in_form']
    assert_error(with_setting('Requirement', 'p_kind_choices', {}), 'cats.Requirement.p_kind_choices',
                 'at least one choice')
    assert_error(with_setting('Requirement', 's_kind_choices', {}), 'cats.Requirement.s_kind_choices',
                 'at least one choice')


def test_empty_choices_are_valid_when_the_attribute_is_optional_or_absent():
    config = with_setting('Requirement', 'p_kind_choices', {})
    config['cats']['Requirement']['attrs']['p_kind']['req_in_form'] = False
    assert_valid(config)
    config = with_setting('Requirement', 'p_kind_choices', {})
    config = remove_attribute(config, 'Requirement', 'p_kind')
    assert 'p_kind' not in config['cats']['Requirement']['attrs']
    assert_valid(config)


# ------------------------------------------------------------------ layouts

def with_column(**column):
    return with_setting('Packet', 'disp_short', [column])


@pytest.mark.parametrize('layout', ['disp_def', 'disp_short', 'disp_trac'])
def test_layout_must_be_a_list_of_columns(layout):
    assert_error(with_setting('Packet', layout, {}), 'cats.Packet.' + layout, 'must be a list')
    assert_error(with_setting('Packet', layout, ['x']), 'cats.Packet.%s[0]' % layout, 'must be an object')


def test_the_default_display_needs_a_column_the_others_may_be_empty():
    assert_error(with_setting('Packet', 'disp_def', []), 'cats.Packet.disp_def', 'at least one column')
    assert_valid(with_setting('Packet', 'disp_short', []))
    assert_valid(with_setting('Packet', 'disp_trac', []))


@pytest.mark.parametrize('column,path,fragment', [
    ({'attrs': ['title']}, '.header', 'is required'),
    ({'header': '', 'attrs': ['title']}, '.header', ''),
    ({'header': 5, 'attrs': ['title']}, '.header', 'must be a text'),
    ({'header': 'T'}, '', 'exactly one of "attrs" and "trac_cat"'),
    ({'header': 'T', 'attrs': ['title'], 'trac_cat': 'VerLink', 'trac_link': 's_link'}, '', 'exactly one'),
    ({'header': 'T', 'attrs': []}, '.attrs', 'must not be empty'),
    ({'header': 'T', 'attrs': 'title'}, '.attrs', 'must be a list'),
    ({'header': 'T', 'attrs': ['title', 'nope']}, '.attrs[1]', 'unknown attribute "nope"'),
    ({'header': 'T', 'attrs': [3]}, '.attrs[0]', 'attribute name'),
    ({'header': 'T', 'attrs': ['title'], 'order_by': 'nope'}, '.order_by', 'attribute of the category'),
    ({'header': 'T', 'attrs': ['title'], 'order_by': 5}, '.order_by', 'attribute of the category'),
    ({'header': 'T', 'attrs': ['title'], 'trac_link': 's_link'}, '.trac_link', 'traceability column'),
    ({'header': 'T', 'attrs': ['title'], 'colour': 1}, '.colour', 'unknown setting')])
def test_columns(column, path, fragment):
    assert_error(with_column(**column), 'cats.Packet.disp_short[0]' + path, fragment)


def test_order_by_may_name_an_attribute_outside_the_column():
    config = base_config()
    assert {'header': 'Title', 'attrs': ['title'], 'order_by': 'value'} in config['cats']['Packet']['disp_short']
    assert_valid(config)


def with_trac_column(**column):
    return with_setting('Packet', 'disp_trac', [dict({'header': 'V', 'trac_cat': 'VerLink', 'trac_link': 's_link'},
                                                     **column)])


def test_traceability_columns():
    path = 'cats.Packet.disp_trac[0]'
    assert_valid(with_trac_column())
    assert_error(with_trac_column(trac_cat='Nope'), path + '.trac_cat', 'identifier of a category')
    assert_error(with_trac_column(trac_cat=5), path + '.trac_cat', 'identifier of a category')
    assert_error(with_trac_column(trac_link='x'), path + '.trac_link', 'must be one of')
    assert_error(with_trac_column(order_by='title'), path + '.order_by', 'cannot be sorted')
    config = with_column(header='V', trac_cat='VerLink', trac_link='s_link')
    assert_error(config, 'cats.Packet.disp_short[0].trac_cat', 'only used in disp_trac')


# ------------------------------------------------------------------ the hidden setting

def test_a_configuration_with_hidden_attributes_and_references_to_them_is_valid():
    config = hide(base_config(), 'Service', 'rationale', 'remarks', 'value')
    assert 'value' in json.dumps(config['cats']['Service']['disp_def'])          # references are kept
    assert_valid(config)


def test_hidden_false_is_valid():
    config = base_config()
    config['cats']['Packet']['attrs']['t1']['hidden'] = False
    assert_valid(config)


@pytest.mark.parametrize('value', ['yes', 1, 0, None, [], {}])
def test_hidden_is_true_or_false(value):
    config = base_config()
    config['cats']['Packet']['attrs']['t1']['hidden'] = value
    assert_error(config, 'cats.Packet.attrs.t1.hidden', 'must be true or false')


def test_hidden_is_optional_and_other_unknown_settings_are_still_refused():
    config = base_config()
    assert 'hidden' not in config['cats']['Packet']['attrs']['t1']
    assert_valid(config)
    config['cats']['Packet']['attrs']['t1']['hide'] = True
    assert_error(config, 'cats.Packet.attrs.t1.hide', 'unknown')


@pytest.mark.parametrize('attr', ['domain', 'name'])
def test_domain_and_name_cannot_be_hidden(attr):
    config = hide(base_config(), 'Packet', attr)
    assert_error(config, 'cats.Packet.attrs.%s.hidden' % attr, 'must be false: the item is identified by it')
    config['cats']['Packet']['attrs'][attr]['hidden'] = False
    assert_valid(config)


def test_the_default_list_keeps_a_column_with_a_shown_attribute():
    config = base_config()
    packet = config['cats']['Packet']
    packet['disp_def'] = [{'header': 'Text', 'attrs': ['title', 'value']}]
    packet['short_desc'] = {'expand_text': [], 'href_tip': [], 'expand_tip': []}
    hide(config, 'Packet', 'title')
    assert_valid(config)
    hide(config, 'Packet', 'value')
    assert_error(config, 'cats.Packet.disp_def', 'must have at least one column with an attribute which is not hidden')
    del packet['attrs']['title']['hidden']
    assert_valid(config)


def test_a_hidden_required_choice_attribute_needs_no_choices():
    config = base_config()
    definition = config['cats']['Requirement']
    definition['attrs']['p_kind']['req_in_form'] = True
    definition['p_kind_choices'] = {}
    assert_error(config, 'cats.Requirement.p_kind_choices', 'must have at least one choice')
    hide(config, 'Requirement', 'p_kind')
    assert_no_error_at(config, 'cats.Requirement.p_kind_choices')


def test_the_template_has_no_hidden_attribute():
    assert not has_hidden_attributes(base_config())


# ------------------------------------------------------------------ determinism and purity

def broken_config():
    config = base_config()
    config['cats']['Service']['abbr'] = config['cats']['Packet']['abbr']
    config['cats']['Service']['attrs']['title']['label'] = 'Domain'
    config['cats']['packet'] = minimal_cat()
    config['cats']['Requirement']['page_size'] = 0
    return config


def test_the_result_does_not_depend_on_the_key_order():
    config = broken_config()
    expected = validate_config(config)
    assert len(expected) >= 4
    keys = list(config['cats'])
    orders = [keys[::-1], sorted(keys), sorted(keys, reverse=True), keys[1::2] + keys[::2]]
    orders += [keys[shift:] + keys[:shift] for shift in range(1, len(keys), 5)]
    for order in orders:
        shuffled = dict(config, cats={key: config['cats'][key] for key in order})
        assert validate_config(shuffled) == expected


def test_the_error_list_is_cut():
    config = base_config()
    for i in range(2 * MAX_ERRORS):
        config['cats']['bad cat %d' % i] = 1
    errors = validate_config(config)
    assert len(errors) == MAX_ERRORS + 1
    assert re.match(r'^[1-9][0-9]* more error\(s\) not shown$', errors[-1]['message'])
    assert errors[-1]['path'] == ''


def test_the_argument_is_not_modified():
    invalid = base_config()
    invalid['cats']['Packet']['links'] = {'p_link': {'targets': ['Nope']}}
    invalid['cats']['Packet']['disp_def'] = 5
    for config in (base_config(), invalid):
        before = copy_config(config)
        validate_config(config)
        assert config == before


# ------------------------------------------------------------------ malformed input
# A malformed configuration yields errors, never an exception (an exception would be an HTTP 500).

def small_config():
    config = base_config()
    config['cats'] = {cat: config['cats'][cat] for cat in ('Packet', 'Service', 'DataItem', 'Requirement', 'FCP')}
    return config


def setting_paths(node, prefix=()):
    paths = [prefix]
    if isinstance(node, dict):
        for key, value in node.items():
            paths += setting_paths(value, prefix + (key,))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            paths += setting_paths(value, prefix + (i,))
    return paths


def set_path(config, path, value):
    node = config
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def test_every_setting_replaced_by_every_bad_value():
    template = small_config()
    count = 0
    for path in setting_paths(template)[1:]:
        for value in BAD_VALUES:
            config = copy_config(template)
            set_path(config, path, copy_config(value))
            errors = validate_config(config)
            assert isinstance(errors, list), (path, value)
            for error in errors:
                assert set(error) == {'path', 'message'}, (path, value)
                assert isinstance(error['path'], str), (path, value)
                assert isinstance(error['message'], str), (path, value)
            if config != template and path[-1] not in ('None',):
                count += 1
    assert count > 1000


@pytest.mark.parametrize('path', [('general', 'max_depth'), ('cats', 'Packet', 'page_size'),
                                  ('cats', 'Packet', 'attrs'), ('cats', 'Packet', 'links'),
                                  ('cats', 'Packet', 'disp_def', 0, 'attrs'), ('cats', 'Packet', 'expand', 's_link')])
@pytest.mark.parametrize('value', [None, [], 'x', {}, 1.5, True])
def test_most_bad_values_are_reported(path, value):
    config = small_config()
    set_path(config, path, value)
    assert validate_config(config)


@pytest.mark.parametrize('config', [
    {1: 2}, {'general': {}, 'cats': {1: {}, None: [], ('a',): 'x'}}, {'general': {5: 1}, 'cats': {}},
    {'cats': {'A': {'attrs': {3: {}, None: None}, 'disp_def': [{1: 2}], 'links': {5: {}}}}},
    {'cats': {'A': {'attrs': {'domain': {'kind': ['x'], 'label': {}, 'req_in_form': []}}}}}])
def test_weird_root_members(config):
    assert validate_config(config)


def test_unhashable_and_odd_values_where_names_are_expected():
    config = base_config()
    config['cats']['Packet']['level'] = []
    config['cats']['Packet']['access_from_index'] = {'level': []}
    config['cats']['Packet']['expand'] = {'s_link': [], 'p_link': {}}
    config['cats']['Packet']['tracs'] = [{'trac_cat': [], 'trac_link': {}}]
    config['cats']['Packet']['attrs']['title']['kind'] = {}
    config['cats']['Packet']['disp_def'] = [{'header': 'x', 'attrs': [[]], 'order_by': []}]
    config['cats']['Packet']['p_kind_choices'] = {'A': []}
    assert validate_config(config)


# ------------------------------------------------------------------ stored data

def item_snapshot():
    return list(SpecItem.objects.order_by('id').values_list(
        'id', 'cat', 'domain', 'name', 'title', 'desc', 'value', 't1', 'p_kind', 's_kind', 'p_link_id',
        's_link_id', 'status', 'updated_at', 'application_id', 'val_set_id'))


def test_stored_values_which_are_choices_are_valid(project):
    make_item(project, 'Packet', 'D', 'p', p_kind='TC')
    make_item(project, 'Packet', 'D', 'q', p_kind='')
    make_item(project, 'Requirement', 'D', 'r', p_kind='STD', s_kind='TST')
    assert_valid(base_config(), project)


def test_a_stored_kind_which_is_not_a_choice_is_reported_with_its_count(project):
    make_item(project, 'Packet', 'D', 'p', p_kind='TC')
    make_item(project, 'Packet', 'D', 'q', p_kind='TC', status='OBS')
    config = base_config()
    del config['cats']['Packet']['p_kind_choices']['TC']
    assert errors_of(config, project) == [
        ('cats.Packet.p_kind_choices', 'the stored p_kind value "TC" of 2 item(s) is not a choice')]
    assert_valid(config)             # without a project nothing is compared with stored data


def test_s_kind_is_checked_too(project):
    make_item(project, 'Requirement', 'D', 'r', s_kind='TST')
    config = base_config()
    del config['cats']['Requirement']['s_kind_choices']['TST']
    assert_error(config, 'cats.Requirement.s_kind_choices', 'stored s_kind value "TST" of 1 item(s)', project)


def test_a_hidden_kind_attribute_is_still_checked(project):
    make_item(project, 'Packet', 'D', 'p', p_kind='TC')
    config = remove_attribute(base_config(), 'Packet', 'p_kind')
    del config['cats']['Packet']['p_kind_choices']['TC']
    assert_error(config, 'cats.Packet.p_kind_choices', 'stored p_kind value "TC"', project)


def test_stored_values_of_a_category_which_is_not_in_the_configuration_are_ignored(project):
    make_item(project, 'Packet', 'D', 'p', p_kind='GONE')
    assert_valid(remove_category(base_config(), 'Packet'), project)


def test_other_projects_do_not_matter(project):
    other, _ = make_project('Other', owner=project.owner, cats=ALL_CATS)
    make_item(other, 'Packet', 'D', 'p', p_kind='GONE')
    assert_valid(base_config(), project)
    assert_error(base_config(), 'cats.Packet.p_kind_choices', '"GONE"', other)


def test_stored_link_pairs_must_be_allowed(project):
    service = make_item(project, 'Service', 'D', 's')
    make_item(project, 'Packet', 'D', 'p', p_link=service)
    assert_valid(base_config(), project)
    config = base_config()
    config['cats']['Packet']['links']['p_link']['targets'] = ['EnumType']
    assert_error(config, 'cats.Packet.links.p_link',
                 'stored p_link of 1 item(s) of category "Packet" point to items of category "Service", '
                 'which this rule does not allow', project)
    del config['cats']['Packet']['links']['p_link']
    assert_error(config, 'cats.Packet.links.p_link', 'category has no rule for', project)
    config['cats']['Packet']['links']['p_link'] = {'all_except': ['Service']}
    assert_error(config, 'cats.Packet.links.p_link', 'does not allow', project)
    config['cats']['Packet']['links']['p_link'] = {'all_except': []}
    assert_valid(config, project)


def test_s_link_pairs_are_checked_too(project):
    enum_type = make_item(project, 'EnumType', 'D', 'e')
    make_item(project, 'Packet', 'D', 'p', s_link=enum_type)
    config = base_config()
    config['cats']['Packet']['links']['s_link']['targets'] = ['DataItem']
    assert_error(config, 'cats.Packet.links.s_link', 'stored s_link of 1 item(s)', project)


def test_a_link_to_a_hidden_category_is_not_checked_and_restoring_it_is(project):
    service = make_item(project, 'Service', 'D', 's')
    make_item(project, 'Packet', 'D', 'p', p_link=service)
    hidden = remove_category(base_config(), 'Service')
    assert 'p_link' not in hidden['cats']['Packet']['links']        # the reference was cleaned
    assert_valid(hidden, project)
    restored = copy_config(hidden)
    restored['cats']['Service'] = base_config()['cats']['Service']
    assert_error(restored, 'cats.Packet.links.p_link', 'category has no rule for', project)
    restored['cats']['Packet']['links']['p_link'] = {'targets': ['Service']}
    assert_valid(restored, project)


def test_a_malformed_rule_is_reported_once_not_as_a_data_problem(project):
    service = make_item(project, 'Service', 'D', 's')
    make_item(project, 'Packet', 'D', 'p', p_link=service)
    config = base_config()
    config['cats']['Packet']['links']['p_link'] = {'targets': 'Service'}
    assert [e[0] for e in errors_of(config, project)] == ['cats.Packet.links.p_link.targets']


def test_removing_any_category_with_stored_data_is_allowed(project):
    for cat in ALL_CATS:
        make_item(project, cat, 'D', 'item_' + cat, p_kind='', title='t', value='v', t1='x')
    before = item_snapshot()
    for cat in ALL_CATS:
        assert errors_of(remove_category(base_config(), cat), project) == [], cat
    assert item_snapshot() == before


def test_removing_an_attribute_with_stored_data_is_allowed_and_keeps_the_data(project):
    item = make_item(project, 'Packet', 'D', 'p', title='Title', desc='Desc', value='7', t1='t1', t2='t2',
                     p_kind='TC')
    before = item_snapshot()
    for attr in base_config()['cats']['Packet']['attrs']:
        if attr in ('domain', 'name'):
            continue
        assert errors_of(remove_attribute(base_config(), 'Packet', attr), project) == [], attr
    assert item_snapshot() == before
    assert refresh(item).title == 'Title'


def test_validation_only_reads(project):
    service = make_item(project, 'Service', 'D', 's')
    make_item(project, 'Packet', 'D', 'p', p_link=service, p_kind='GONE')
    project.config = base_config()
    project.save(update_fields=['config'])
    before = (item_snapshot(), Project.objects.get(id=project.id).config)
    config = base_config()
    config['cats']['Packet']['links']['p_link']['targets'] = ['EnumType']
    with CaptureQueriesContext(connection) as queries:
        errors = validate_config(config, project)
        remove_category(config, 'Service')
        remove_attribute(config, 'Packet', 'title')
        remove_dangling_references(config)
    assert errors
    assert len(queries) == 1
    assert queries[0]['sql'].lstrip().upper().startswith('SELECT')
    assert (item_snapshot(), Project.objects.get(id=project.id).config) == before


# ------------------------------------------------------------------ configurations derived from the template for data

@pytest.mark.parametrize('cat', ALL_CATS)
def test_every_single_category_filter_output_is_valid(cat):
    project, _ = make_project('P_' + cat, cats=[cat])
    assert_valid(filter_template_for_data(load_template(), project), project)


def test_filter_output_for_data_only_categories_is_valid():
    project, _ = make_project('Only data', cats=[])
    service = make_item(project, 'Service', 'D', 's')
    enum_type = make_item(project, 'EnumType', 'D', 'e', p_kind='')
    make_item(project, 'Packet', 'D', 'p', p_link=service, s_link=enum_type, p_kind='TC', title='T')
    make_item(project, 'DataItem', 'D', 'd', value='1', p_kind='CNS')
    config = filter_template_for_data(load_template(), project)
    assert sorted(config['cats']) == ['DataItem', 'EnumType', 'Packet', 'Service']
    assert_valid(config, project)


def test_a_filtered_configuration_uses_the_shared_cleanup():
    project, _ = make_project('Shared', cats=['Packet'])
    with mock.patch.object(project_config, 'remove_dangling_references', wraps=remove_dangling_references) as spy:
        filter_template_for_data(load_template(), project)
    spy.assert_called_once()


# ------------------------------------------------------------------ cleanup

def test_removing_a_category_removes_the_references_to_it():
    config = remove_category(base_config(), 'Packet')
    cats = config['cats']
    assert 'Packet' not in cats
    assert cats['Service']['expand'] == {'p_link': 'None', 'p_label': 'Packet', 's_link': 'None'}
    assert {'trac_cat': 'Packet', 'trac_link': 'p_link'} not in cats['DerPacket']['tracs']
    assert cats['PacketPar']['links'].get('p_link') == {'targets': ['DerPacket']}
    assert cats['InCommand']['links']['p_link'] == {'targets': ['DerPacket']}
    assert_valid(config)


def test_removing_a_link_category_removes_the_traceability_references():
    config = remove_category(base_config(), 'VerLink')
    for cat, definition in config['cats'].items():
        assert 'VerLink' not in [t['trac_cat'] for t in definition['tracs']], cat
        assert 'VerLink' not in [c.get('trac_cat') for c in definition['disp_trac']], cat
        assert 'VerLink' not in json.dumps(definition['links']), cat
    assert config['cats']['Requirement']['tracs'] == []
    assert config['cats']['ParReq']['tracs'] == [{'trac_cat': 'TracLink', 'trac_link': 's_link'}]
    assert_valid(config)


def test_removing_the_enumerated_value_category_removes_the_validator_and_nothing_else():
    config = remove_category(base_config(), 'EnumValue')
    assert config['cats']['DataItem']['validators'] == []
    assert config['cats']['EnumType']['expand']['s_link'] == 'None'
    assert config['cats']['DataItem']['links'] == base_config()['cats']['DataItem']['links']
    assert_valid(config)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_every_category_can_be_removed_without_touching_unrelated_ones(cat):
    original = base_config()
    before = copy_config(original)
    config = remove_category(original, cat)
    assert original == before              # the argument is not modified
    assert_valid(config)
    assert config['general'] == original['general']
    assert list(config['cats']) == [c for c in original['cats'] if c != cat]
    for other in config['cats']:
        for key, value in original['cats'][other].items():
            if config['cats'][other][key] != value:
                assert key in REFERENCING, '%s.%s changed without referencing %s' % (other, key, cat)
                assert cat in json.dumps(value), '%s.%s did not refer to %s' % (other, key, cat)


def test_removing_an_attribute_removes_the_references_to_it():
    original = base_config()
    config = remove_attribute(original, 'DataItem', 'value')
    definition = config['cats']['DataItem']
    assert 'value' not in definition['attrs']
    assert definition['validators'] == []
    for names in definition['short_desc'].values():
        assert 'value' not in names
    for layout in ('disp_def', 'disp_short', 'disp_trac'):
        for column in definition[layout]:
            assert 'value' not in column.get('attrs', [])
            assert column.get('order_by') != 'value'
    assert config['cats']['Packet'] == original['cats']['Packet']
    assert_valid(config)


def test_a_column_left_without_attributes_is_removed_and_an_order_by_on_a_removed_attribute_too():
    original = base_config()
    packet = remove_attribute(original, 'Packet', 'title')['cats']['Packet']
    assert {'header': 'Title', 'attrs': ['title'], 'order_by': 'value'} not in packet['disp_short']
    assert len(packet['disp_short']) == len(original['cats']['Packet']['disp_short']) - 1
    packet = remove_attribute(original, 'Packet', 'value')['cats']['Packet']
    assert {'header': 'Title', 'attrs': ['title']} in packet['disp_short']       # order_by dropped, column kept
    assert_valid(remove_attribute(original, 'Packet', 'value'))


def test_ext_attrs_are_cleaned():
    config = remove_attribute(base_config(), 'FCP', 'n3')
    assert 'n3' not in config['cats']['FCP']['ext_attrs']
    assert_valid(config)


@pytest.mark.parametrize('cat,attr', [(cat, attr) for cat in ALL_CATS for attr in TEMPLATE['cats'][cat]['attrs']])
def test_every_attribute_can_be_removed_without_touching_anything_else(cat, attr):
    original = base_config()
    config = remove_attribute(original, cat, attr)
    errors = errors_of(config)
    if attr in ('domain', 'name'):
        assert errors == [('cats.%s.attrs.%s' % (cat, attr), 'is required')]
    else:
        assert errors == []
    assert {c: d for c, d in config['cats'].items() if c != cat} == \
        {c: d for c, d in original['cats'].items() if c != cat}
    changing = REFERENCING + ('attrs', 'ext_attrs', 'short_desc', 'disp_def', 'disp_short')
    assert {k: v for k, v in config['cats'][cat].items() if k not in changing} == \
        {k: v for k, v in original['cats'][cat].items() if k not in changing}


def test_removing_what_does_not_exist_changes_nothing():
    original = base_config()
    assert remove_category(original, 'Nope') == original
    assert remove_attribute(original, 'Nope', 'title') == original
    assert remove_attribute(original, 'Packet', 'nope') == original


def test_a_removed_attribute_can_be_defined_again_with_the_same_identifier():
    original = base_config()
    removed = remove_attribute(original, 'Packet', 't1')
    removed['cats']['Packet']['attrs']['t1'] = original['cats']['Packet']['attrs']['t1']
    assert_valid(removed)


def test_dangling_references_of_a_hand_edited_configuration_are_removed():
    config = base_config()
    del config['cats']['Service']
    del config['cats']['Packet']['attrs']['t2']
    assert errors_of(config)
    cleaned = remove_dangling_references(config)
    assert_valid(cleaned)
    assert cleaned['cats']['Packet']['links'].get('p_link') is None
    assert remove_dangling_references(cleaned) == cleaned           # idempotent


def test_a_valid_configuration_is_unchanged_by_the_cleanup():
    config = base_config()
    assert remove_dangling_references(config) == config
    assert remove_dangling_references(config) is not config


def test_malformed_parts_are_left_alone():
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
        assert isinstance(result, dict)
    for bad in (None, [], 'x', {'cats': []}, {'cats': {'A': []}}):
        assert remove_dangling_references(bad) == bad
        assert remove_attribute(bad, 'A', 'title') == bad
    for bad in (None, [], 'x', {'cats': []}):
        assert remove_category(bad, 'A') == bad
    assert remove_category({'cats': {'A': []}}, 'A') == {'cats': {}}


# ------------------------------------------------------------------ entry points
# The form (payload), raw JSON and file entry points all go through validate_config.

def upload(text):
    return SimpleUploadedFile('c.json', text.encode())


def test_all_three_entry_points_give_the_same_errors():
    config = base_config()
    config['cats']['Packet']['page_size'] = 0
    config['cats']['Packet']['links']['p_link']['targets'] = ['Nope']
    expected = validate_config(config)
    assert [e['path'] for e in expected] == ['cats.Packet.page_size', 'cats.Packet.links.p_link.targets[0]']
    text = json.dumps(config)
    for parsed, errors in (validate_config_json(text), validate_config_json(text.encode()),
                           validate_config_file(upload(text))):
        assert parsed == config
        assert errors == expected


def test_all_three_entry_points_call_the_one_validator(project):
    text = json.dumps(base_config())
    with mock.patch.object(config_validation, 'validate_config', wraps=validate_config) as spy:
        validate_config_json(text, project)
        validate_config_file(upload(text), project)
    assert spy.call_count == 2
    assert all(call.args[1] is project for call in spy.call_args_list)


def test_valid_input_through_every_entry_point(project):
    config = base_config()
    text = json.dumps(config, indent=2)
    assert validate_config_json(text, project) == (config, [])
    assert validate_config_file(upload(text), project) == (config, [])


def test_the_stored_data_is_checked_for_json_and_file_input_too(project):
    make_item(project, 'Packet', 'D', 'p', p_kind='TC')
    config = base_config()
    del config['cats']['Packet']['p_kind_choices']['TC']
    text = json.dumps(config)
    for _, errors in (validate_config_json(text, project), validate_config_file(upload(text), project)):
        assert [e['path'] for e in errors] == ['cats.Packet.p_kind_choices']


def test_a_project_configuration_can_be_downloaded_and_uploaded_again(project):
    project.config = base_config()
    project.save(update_fields=['config'])
    stored = Project.objects.get(id=project.id).config
    text = json.dumps(stored, indent=2, sort_keys=True)
    assert validate_config_json(text, project) == (stored, [])


def test_json_syntax_errors_have_a_position():
    config, errors = validate_config_json('{\n "general": {,}\n}')
    assert config is None
    assert len(errors) == 1
    assert errors[0]['path'] == ''
    assert 'invalid JSON at line 2, column 14' in errors[0]['message']


@pytest.mark.parametrize('text', ['[]', '5', 'null', '"x"', 'true'])
def test_json_which_is_not_an_object_is_reported_by_the_validator(text):
    config, errors = validate_config_json(text)
    assert errors == [config_error('', 'the configuration must be a JSON object')]


@pytest.mark.parametrize('text', ['{"general": NaN}', '{"general": Infinity}', '{"general": -Infinity}'])
def test_constants_which_are_not_json_are_rejected(text):
    config, errors = validate_config_json(text)
    assert config is None
    assert 'is not allowed' in errors[0]['message']


def test_duplicate_keys_are_reported_with_their_path():
    text = json.dumps(base_config()).replace('"page_size": 100', '"page_size": 100, "page_size": 5', 1)
    config, errors = validate_config_json(text)
    assert any(e['path'].endswith('.page_size') and 'more than once' in e['message'] for e in errors)
    text = '{"general": {"csv_sep": "|", "csv_sep": ";"}, "cats": {"A": {}, "A": {}}}'
    _, errors = validate_config_json(text)
    assert config_error('general.csv_sep', 'the key occurs more than once in the object') in errors
    assert config_error('cats.A', 'the key occurs more than once in the object') in errors


def test_input_limits():
    big = '{"x": "%s"}' % ('a' * MAX_JSON_BYTES)
    for data in (big, big.encode()):
        config, errors = validate_config_json(data)
        assert config is None
        assert 'larger than' in errors[0]['message']
    config, errors = validate_config_file(upload(big))
    assert config is None
    assert 'larger than' in errors[0]['message']


def test_encoding_and_input_types():
    config, errors = validate_config_json(b'\xff\xfe{')
    assert config is None
    assert 'UTF-8' in errors[0]['message']
    bom = b'\xef\xbb\xbf' + json.dumps(base_config()).encode()
    assert validate_config_json(bom)[1] == []
    for value in (None, 5, [], {}):
        assert validate_config_json(value)[0] is None


@pytest.mark.parametrize('text', ['[' * 100000, '{"a":' * 100000, '[' * 100000 + ']' * 100000],
                         ids=['open lists', 'open objects', 'closed lists'])
def test_deeply_nested_json_is_an_error_not_a_crash(text):
    config, errors = validate_config_json(text)
    assert config is None
    assert len(errors) == 1


def test_unreadable_files():
    broken = mock.Mock(read=mock.Mock(side_effect=OSError))
    config, errors = validate_config_file(broken)
    assert config is None
    assert errors == [config_error('', 'the file cannot be read')]


def test_a_server_setting_in_an_uploaded_file_is_rejected():
    _, errors = validate_config_file(upload(json.dumps(load_template())))
    assert [e['path'] for e in errors] == ['general.temp_dir']
