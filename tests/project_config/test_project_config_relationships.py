"""The expected values below (the inventory) are the rules which editor/configs.py hardcoded before the project
configuration, not values read from the template, so that the template is checked against the previous behavior."""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from editor.cat_validators import VALIDATORS, check_validator_specs, run_validators
from editor.config_cleanup import copy_config
from editor.configs import do_cat_specific_checks, get_p_link_choices, get_s_link_choices
from editor.forms import SpecItemForm
from editor.link_rules import check_link_rule, check_link_rules, check_trac_settings, get_link_choices
from editor.models import SpecItem, ValSet
from editor.project_config import filter_template_for_data, get_project_config, load_template
from tests.project_config.base import ALL_CATS, TEMPLATE, World, make_application, make_project, now

pytestmark = pytest.mark.django_db

# A category not listed offers no choices.
P_LINK_TARGETS = {
    'DataItem': {'DataItemType', 'EnumType'}, 'RiskScenario': {'OpContext'}, 'VerLink': {'VerItem'},
    'Packet': {'Service'}, 'InCommand': {'Packet', 'DerPacket'}, 'OutComponent': {'Packet', 'DerPacket'},
    'PacketPar': {'Packet', 'DerPacket'}, 'DerPacket': {'EnumValue'}, 'AdaptPoint': {'Requirement'},
}
S_LINK_TARGETS = {
    'RiskScenario': {'DisrEvt'}, 'EnumValue': {'EnumType'}, 'PacketPar': {'DataItem'}, 'DerPacket': {'Packet'},
    'Packet': {'EnumType'}, 'VerStep': {'VerItem'}, 'VerLink': set(ALL_CATS) - {'VerItem', 'VerLink'},
}
TRACS = {
    'ParReq': [('TracLink', 's_link'), ('VerLink', 's_link')], 'DerReq': [('TracLink', 'p_link'), ('VerLink', 's_link')],
    'VerItem': [('VerLink', 'p_link')], 'OpContext': [('RiskScenario', 'p_link')], 'DisrEvt': [('RiskScenario', 's_link')],
    **{cat: [('VerLink', 's_link')] for cat in ('Requirement', 'SysReq', 'Service', 'Packet', 'DerPacket', 'PacketPar',
                                                'InCommand', 'OutComponent', 'DataItem')},
}
ENUM_MSG = 'Data item value must be a reference to an enumerated value of the item type'
REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_FILES = {name: REPO_ROOT / 'editor' / name for name in (
    'configs.py', 'link_rules.py', 'cat_validators.py', 'config_validation.py', 'config_cleanup.py')}
GOOD_SPEC = {'name': 'link_conditional_reference',
             'params': {'field': 'value', 'link': 'p_link', 'when_link_cat': 'EnumType', 'ref_cat': 'EnumValue',
                        'ref_link': 's_link', 'message': 'm'}}


def schema_errors(config):
    """All relationship schema errors of a complete configuration."""
    cats, errors = set(config['cats']), []
    for cat, definition in config['cats'].items():
        errors += check_link_rules(definition['links'], 'cats.%s.links' % cat, cats)
        errors += check_trac_settings(definition['tracs'], 'cats.%s.tracs' % cat, cats)
        errors += check_validator_specs(definition['validators'], 'cats.%s.validators' % cat, config, cat)
    return errors


def make(project, cat, name, application=None, status='CNF', **fields):
    """A SpecItem created directly; works for categories the template does not know."""
    return SpecItem.objects.create(cat=cat, domain='D', name=name, project=project, application=application,
                                   val_set=ValSet.objects.get(project=project, name='Default'), status=status,
                                   owner=project.owner, updated_at=now(), created_at=now(), **fields)


def configure(project, mutate=None, new_cats=()):
    """Store a copy of the template (plus new categories copied from InfoItem) as the project's configuration."""
    config = copy_config(TEMPLATE)
    for cat in new_cats:
        config['cats'][cat] = copy_config(TEMPLATE['cats']['InfoItem'])
        config['cats'][cat]['name'] = cat
    if mutate:
        mutate(config['cats'])
    project.config = config
    project.save(update_fields=['config'])
    return get_project_config(project)


def p_choices(cat, project, application=None, parent_id=None, other_parent_id=None):
    return list(get_p_link_choices(cat, project, application, parent_id, other_parent_id, get_project_config(project)))


def s_choices(cat, project, application=None, parent_id=None, other_parent_id=None):
    return list(get_s_link_choices(cat, project, application, parent_id, other_parent_id, get_project_config(project)))


def cat_checks(project, cat, **cleaned_data):
    form = SimpleNamespace(cat=cat, project=project, cleaned_data=cleaned_data)
    return do_cat_specific_checks(form, get_project_config(project))


@pytest.fixture
def w(client):
    return World(client)


# ------------------------------------------------------------------ the rules of the template

@pytest.mark.parametrize('cat', ALL_CATS)
def test_every_category_has_both_settings(cat):
    assert isinstance(TEMPLATE['cats'][cat]['links'], dict)
    assert isinstance(TEMPLATE['cats'][cat]['validators'], list)


@pytest.mark.parametrize('cat', ALL_CATS)
@pytest.mark.parametrize('link,expected', [('p_link', P_LINK_TARGETS), ('s_link', S_LINK_TARGETS)], ids=['p', 's'])
def test_link_targets_equal_the_inventory(cat, link, expected):
    rule = TEMPLATE['cats'][cat]['links'].get(link)
    if cat not in expected:
        assert rule is None
    elif cat == 'VerLink' and link == 's_link':
        assert (set(rule['all_except']), 'targets' in rule) == ({'VerItem', 'VerLink'}, False)
    else:
        assert set(rule['targets']) == expected[cat]


def test_specification_confirmed_pairs_are_present():
    links = {cat: TEMPLATE['cats'][cat]['links'] for cat in ALL_CATS}
    for cat, link, target in [('DataItem', 'p_link', 'DataItemType'), ('DataItem', 'p_link', 'EnumType'),
                              ('DerPacket', 'p_link', 'EnumValue'), ('Packet', 'p_link', 'Service'),
                              ('PacketPar', 'p_link', 'Packet'), ('PacketPar', 'p_link', 'DerPacket'),
                              ('InCommand', 'p_link', 'Packet'), ('OutComponent', 'p_link', 'Packet'),
                              ('DerPacket', 's_link', 'Packet'), ('EnumValue', 's_link', 'EnumType'),
                              ('Packet', 's_link', 'EnumType'), ('PacketPar', 's_link', 'DataItem')]:
        assert target in links[cat][link]['targets'], (cat, link)


def test_scope_order_and_dependency_settings():
    links = {cat: TEMPLATE['cats'][cat]['links'] for cat in ALL_CATS}
    assert links['AdaptPoint']['p_link']['scope'] == 'application'
    assert links['VerLink']['s_link']['order_by'] == ['cat', 'domain', 'name']
    assert links['DerPacket']['p_link']['narrow_by_other_parent'] == \
        {'target_field': 's_link', 'parent_field': 's_link'}
    explicit = {(cat, link, key) for cat in ALL_CATS for link, rule in links[cat].items()
                for key in ('scope', 'order_by', 'narrow_by_other_parent') if key in rule}
    assert explicit == {('AdaptPoint', 'p_link', 'scope'), ('VerLink', 's_link', 'order_by'),
                        ('DerPacket', 'p_link', 'narrow_by_other_parent')}


@pytest.mark.parametrize('cat', ALL_CATS)
def test_traceability_settings_equal_the_inventory(cat):
    assert [(t['trac_cat'], t['trac_link']) for t in TEMPLATE['cats'][cat]['tracs']] == TRACS.get(cat, [])


def test_only_the_data_item_rule_is_a_validator():
    for cat in ALL_CATS:
        assert len(TEMPLATE['cats'][cat]['validators']) == (1 if cat == 'DataItem' else 0), cat
    assert TEMPLATE['cats']['DataItem']['validators'] == [{
        'name': 'link_conditional_reference',
        'params': {'field': 'value', 'link': 'p_link', 'when_link_cat': 'EnumType', 'ref_cat': 'EnumValue',
                   'ref_link': 's_link', 'message': ENUM_MSG}}]


def test_the_template_satisfies_the_schema():
    assert schema_errors(TEMPLATE) == []
    assert schema_errors(load_template()) == []


def test_kind_choices_are_still_category_specific_maps():
    for cat in ALL_CATS:
        for key in ('p_kind_choices', 's_kind_choices'):
            assert isinstance(TEMPLATE['cats'][cat][key], dict), (cat, key)
    assert list(TEMPLATE['cats']['Requirement']['p_kind_choices']) == ['STD', 'CNS', 'DEF', 'PRP', 'AP']


# ------------------------------------------------------------------ the rules taken over from editor/configs.py

@pytest.fixture
def items(w):
    """One confirmed item of every category in project 'Proj' (application 'App' for application categories)."""
    return {cat: make(w.project, cat, 'i_' + cat,
                      application=w.application if TEMPLATE['cats'][cat]['level'] == 'application' else None)
            for cat in ALL_CATS}


@pytest.mark.parametrize('cat', ALL_CATS)
def test_choices_of_every_category_and_link(w, items, cat):
    application = w.application if cat == 'AdaptPoint' else None
    assert {item.cat for item in p_choices(cat, w.project, application)} == P_LINK_TARGETS.get(cat, set())
    assert {item.cat for item in s_choices(cat, w.project, application)} == S_LINK_TARGETS.get(cat, set())


def test_adapt_point_choices_need_an_application(w, items):
    assert p_choices('AdaptPoint', w.project) == []
    assert p_choices('AdaptPoint', w.project, w.application) == [items['Requirement']]
    other = make_application(w.project, 'Other')
    assert p_choices('AdaptPoint', w.project, other) == []


def test_ordering(w, items):
    make(w.project, 'Packet', 'a_first')
    make(w.project, 'DerPacket', 'b_second')
    names = [(i.domain, i.name) for i in p_choices('PacketPar', w.project)]
    assert names == sorted(names)
    ordered = [(i.cat, i.domain, i.name) for i in s_choices('VerLink', w.project)]
    assert ordered == sorted(ordered)


def test_deleted_and_obsolete_items_are_not_offered(w, items):
    for status in ('DEL', 'OBS'):
        make(w.project, 'Service', 'gone_' + status, status=status)
    assert p_choices('Packet', w.project) == [items['Service']]
    assert 'DEL' not in {i.status for i in s_choices('VerLink', w.project)}


def test_items_of_other_projects_are_not_offered(w, items):
    other, _ = make_project('Other', owner=w.owner)
    make(other, 'Service', 'foreign')
    assert p_choices('Packet', w.project) == [items['Service']]


def test_parent_override_applies_to_every_rule(w, items):
    parent = items['DataItem']
    assert p_choices('Packet', w.project, parent_id=str(parent.id)) == [parent]
    assert s_choices('ParReq', w.project, parent_id=parent.id) == [parent]      # no rule at all
    other, _ = make_project('Other', owner=w.owner)
    foreign = make(other, 'Service', 'foreign')
    assert p_choices('Packet', w.project, parent_id=foreign.id) == []


def test_der_packet_enum_values_follow_the_expanded_packet(w, items):
    type_a, type_b = items['EnumType'], make(w.project, 'EnumType', 'T2')
    value_a = make(w.project, 'EnumValue', 'va', s_link=type_a)
    value_b = make(w.project, 'EnumValue', 'vb', s_link=type_b)
    packet = make(w.project, 'Packet', 'pk', s_link=type_b)
    untyped = items['EnumValue']
    assert p_choices('DerPacket', w.project) == [untyped, value_a, value_b]
    assert p_choices('DerPacket', w.project, other_parent_id=packet.id) == [value_b]
    # The dependency is part of the p_link rule only: s_link of DerPacket ignores the other parent
    assert s_choices('DerPacket', w.project, other_parent_id=value_a.id) == [items['Packet'], packet]


def test_der_packet_dependency_on_a_parent_without_type(w, items):
    value_typed = make(w.project, 'EnumValue', 'va', s_link=items['EnumType'])
    value_untyped = make(w.project, 'EnumValue', 'vu')
    packet = make(w.project, 'Packet', 'pk')
    # Same as the original code: a parent without type selects the targets without type
    assert p_choices('DerPacket', w.project, other_parent_id=packet.id) == [items['EnumValue'], value_untyped]
    assert value_typed not in p_choices('DerPacket', w.project, other_parent_id=packet.id)


def test_dependency_parent_of_another_project_is_rejected(w, items):
    other, _ = make_project('Other', owner=w.owner)
    foreign = make(other, 'Packet', 'pk')
    with pytest.raises(SpecItem.DoesNotExist):
        p_choices('DerPacket', w.project, other_parent_id=foreign.id)


def test_enum_typed_data_item_value_check(w, items):
    enum_type = items['EnumType']
    value = make(w.project, 'EnumValue', 'v1', s_link=enum_type)
    other_value = make(w.project, 'EnumValue', 'v2', s_link=make(w.project, 'EnumType', 'T2'))
    assert cat_checks(w.project, 'DataItem', p_link=enum_type, value='#iref:%d' % value.id) == ''
    assert cat_checks(w.project, 'DataItem', p_link=enum_type, value=' #iref:%d ' % value.id) == ''
    for text in ('5', '', '#iref:%d x' % value.id, 'x #iref:%d' % value.id, '#iref:1 #iref:2'):
        assert cat_checks(w.project, 'DataItem', p_link=enum_type, value=text) == ENUM_MSG, text
    assert cat_checks(w.project, 'DataItem', p_link=enum_type, value='#iref:%d' % other_value.id) == ENUM_MSG
    assert cat_checks(w.project, 'DataItem', p_link=enum_type, value='#iref:%d' % items['DataItemType'].id) == \
        ENUM_MSG + ': The reference is invalid'
    assert cat_checks(w.project, 'DataItem', p_link=enum_type, value='#iref:999999') == \
        ENUM_MSG + ': The reference is invalid'
    # not an enumerated type
    assert cat_checks(w.project, 'DataItem', p_link=items['DataItemType'], value='anything') == ''
    assert cat_checks(w.project, 'DataItem', p_link=None, value='anything') == ''


def test_categories_without_validators_pass(w, items):
    for cat in ALL_CATS:
        if cat != 'DataItem':
            assert cat_checks(w.project, cat, p_link=items['EnumType']) == '', cat


# ------------------------------------------------------------------ rules of the project configuration

def data_item_form(project, data=None):
    return SpecItemForm('add', None, 'DataItem', project, None, get_project_config(project), None, None,
                        **({'data': data} if data is not None else {}))


def data_item_post(enum_type, **overrides):
    data = {'domain': 'D', 'name': 'new', 'title': 'T', 'desc': '', 'value': 'plain text', 'rationale': '',
            'implementation': '', 'remarks': '', 'change_log': '', 'p_kind': 'CNS', 'p_link': str(enum_type.id),
            't1': '', 't2': ''}
    data.update(overrides)
    return data


def test_two_projects_have_different_rules_for_the_same_category(w):
    other, _ = make_project('Other', owner=w.owner)
    for project in (w.project, other):
        make(project, 'Service', 'svc')
        make(project, 'EnumType', 'enum')
    configure(other, lambda cats: cats['Packet']['links']['p_link'].update(targets=['EnumType']))
    assert [i.cat for i in p_choices('Packet', w.project)] == ['Service']
    assert [i.cat for i in p_choices('Packet', other)] == ['EnumType']


def test_a_new_category_with_declarative_relationships_behaves_like_an_existing_one(w):
    def add_rules(cats):
        cats['Widget']['links'] = {
            'p_link': {'targets': ['Gadget', 'Part'], 'narrow_by_other_parent': {'target_field': 'p_link',
                                                                                 'parent_field': 'p_link'}},
            's_link': {'all_except': ['Widget'], 'scope': 'application', 'order_by': ['name', 'domain']}}
    config = configure(w.project, add_rules, new_cats=('Widget', 'Gadget', 'Part'))
    assert schema_errors(config) == []
    gadget, part = make(w.project, 'Gadget', 'g'), make(w.project, 'Part', 'p')
    make(w.project, 'ParReq', 'r', application=w.application)
    make(w.project, 'Gadget', 'deleted', status='DEL')
    assert p_choices('Widget', w.project) == [gadget, part]
    # scope "application": nothing without an application, only that application's items with one
    assert s_choices('Widget', w.project) == []
    app_item = SpecItem.objects.get(name='r')
    assert s_choices('Widget', w.project, w.application) == [app_item]
    # dependency on the other parent (compares p_link of the targets with p_link of the parent)
    parent = make(w.project, 'Gadget', 'parent_of', p_link=part)
    child_a = make(w.project, 'Part', 'child_a', p_link=part)
    make(w.project, 'Part', 'child_b', p_link=gadget)
    assert p_choices('Widget', w.project, other_parent_id=parent.id) == [child_a, parent]


def test_a_category_without_a_rule_offers_nothing(w):
    configure(w.project, new_cats=('Widget',))
    make(w.project, 'Gadget', 'g')
    for choices in (p_choices, s_choices):
        assert choices('Widget', w.project) == []
        assert choices('NotConfigured', w.project) == []


def test_a_removed_rule_offers_nothing(w):
    make(w.project, 'Service', 'svc')
    configure(w.project, lambda cats: cats['Packet']['links'].pop('p_link'))
    assert p_choices('Packet', w.project) == []


@pytest.mark.parametrize('rule', [
    'Service', ['Service'], {}, {'targets': 'Service'}, {'targets': [1]}, {'targets': []},
    {'targets': ['Service'], 'all_except': []}, {'targets': ['Service'], 'scope': 'x'},
    {'targets': ['Service'], 'order_by': ['title']}, {'targets': ['Service'], 'bogus': 1},
    {'targets': ['Service'], 'narrow_by_other_parent': {'target_field': 'cat', 'parent_field': 's_link'}}])
def test_malformed_rules_offer_nothing_and_do_not_raise(w, rule):
    make(w.project, 'Service', 'svc')
    configure(w.project, lambda cats: cats['Packet']['links'].update(p_link=rule))
    assert p_choices('Packet', w.project) == []


def test_an_explicit_configuration_overrides_the_project(w):
    service = make(w.project, 'Service', 'svc')
    config = copy_config(TEMPLATE)
    config['cats']['Packet']['links']['p_link']['targets'] = ['EnumType']
    assert list(get_p_link_choices('Packet', w.project, None, None, None, config)) == []
    assert p_choices('Packet', w.project) == [service]
    assert list(get_link_choices(config, 'p_link', 'Packet', w.project, None, None, None)) == []


def test_the_form_offers_the_choices_of_the_project_configuration(w):
    configure(w.project, lambda cats: cats['DataItem']['links']['p_link'].update(targets=['EnumType']))
    enum_type, item_type = make(w.project, 'EnumType', 'e'), make(w.project, 'DataItemType', 't')
    other, _ = make_project('Other', owner=w.owner)
    other_type = make(other, 'DataItemType', 't')
    assert list(data_item_form(w.project).fields['p_link'].queryset) == [enum_type]
    assert list(data_item_form(other).fields['p_link'].queryset) == [other_type]          # default rule
    assert item_type not in data_item_form(w.project).fields['p_link'].queryset


def test_the_form_applies_the_validators_of_the_project_configuration(w):
    enum_type = make(w.project, 'EnumType', 'e')
    other, _ = make_project('Other', owner=w.owner)
    other_enum_type = make(other, 'EnumType', 'e')
    configure(other, lambda cats: cats['DataItem'].update(validators=[]))
    default_form = data_item_form(w.project, data=data_item_post(enum_type))
    assert not default_form.is_valid()
    assert default_form.non_field_errors() == [ENUM_MSG]
    form = data_item_form(other, data=data_item_post(other_enum_type))
    assert form.is_valid(), form.errors


def test_a_new_category_validator_behaves_like_the_data_item_one(w):
    message = 'Widget value must reference a part of the gadget'

    def add_validator(cats):
        cats['Widget']['validators'] = [{'name': 'link_conditional_reference', 'params': {
            'field': 'value', 'link': 's_link', 'when_link_cat': 'Gadget', 'ref_cat': 'Part',
            'ref_link': 'p_link', 'message': message}}]
    config = configure(w.project, add_validator, new_cats=('Widget', 'Gadget', 'Part'))
    assert schema_errors(config) == []
    gadget, other_gadget = make(w.project, 'Gadget', 'g'), make(w.project, 'Gadget', 'g2')
    part = make(w.project, 'Part', 'p', p_link=gadget)
    assert cat_checks(w.project, 'Widget', s_link=gadget, value='#iref:%d' % part.id) == ''
    assert cat_checks(w.project, 'Widget', s_link=other_gadget, value='#iref:%d' % part.id) == message
    assert cat_checks(w.project, 'Widget', s_link=gadget, value='text') == message
    assert cat_checks(w.project, 'Widget', s_link=gadget, value='#iref:%d' % gadget.id) == \
        message + ': The reference is invalid'
    assert cat_checks(w.project, 'Widget', s_link=make(w.project, 'Part', 'q'), value='text') == ''
    assert cat_checks(w.project, 'Widget', s_link=None, value='text') == ''


# ------------------------------------------------------------------ the rule schema

def paths(errors):
    return [path for path, _ in errors]


@pytest.mark.parametrize('rule', [
    {'targets': ['A']}, {'all_except': []}, {'all_except': ['A', 'B'], 'scope': 'project'},
    {'targets': ['A'], 'scope': 'application', 'order_by': ['cat', 'name']},
    {'targets': ['A'], 'narrow_by_other_parent': {'target_field': 'p_link', 'parent_field': 's_link'}}])
def test_valid_rules(rule):
    assert check_link_rule(rule, 'r') == []


@pytest.mark.parametrize('rule,expected', [
    ('x', ['r']), ({}, ['r']), ({'targets': ['A'], 'all_except': []}, ['r']),
    ({'targets': []}, ['r.targets']), ({'targets': 'A'}, ['r.targets']), ({'targets': [3]}, ['r.targets']),
    ({'all_except': 'A'}, ['r.all_except']), ({'targets': ['A'], 'scope': 'global'}, ['r.scope']),
    ({'targets': ['A'], 'order_by': []}, ['r.order_by']), ({'targets': ['A'], 'order_by': ['title']}, ['r.order_by']),
    ({'targets': ['A'], 'extra': 1}, ['r.extra']),
    ({'targets': ['A'], 'narrow_by_other_parent': 'x'}, ['r.narrow_by_other_parent']),
    ({'targets': ['A'], 'narrow_by_other_parent': {'target_field': 'cat', 'parent_field': 'p_link', 'z': 1}},
     ['r.narrow_by_other_parent.z', 'r.narrow_by_other_parent.target_field']),
    ({'targets': ['A'], 'narrow_by_other_parent': {}},
     ['r.narrow_by_other_parent.target_field', 'r.narrow_by_other_parent.parent_field'])])
def test_invalid_rules_report_precise_paths(rule, expected):
    assert paths(check_link_rule(rule, 'r')) == expected


def test_category_references_are_checked_when_categories_are_given():
    assert paths(check_link_rule({'targets': ['A', 'Nope']}, 'r', {'A'})) == ['r.targets[1]']
    assert paths(check_link_rule({'all_except': ['Nope']}, 'r', {'A'})) == ['r.all_except[0]']
    assert check_link_rule({'targets': ['A', 'Nope']}, 'r') == []


def test_links_object():
    assert check_link_rules({'p_link': {'targets': ['A']}, 's_link': {'all_except': []}}, 'l') == []
    assert paths(check_link_rules({'t1': {'targets': ['A']}}, 'l')) == ['l.t1']
    assert paths(check_link_rules({'p_link': {'targets': []}}, 'l')) == ['l.p_link.targets']
    assert paths(check_link_rules([], 'l')) == ['l']


def test_traceability_settings():
    assert check_trac_settings([{'trac_cat': 'A', 'trac_link': 's_link'}], 't', {'A'}) == []
    assert paths(check_trac_settings({}, 't')) == ['t']
    assert paths(check_trac_settings(['x'], 't')) == ['t[0]']
    assert paths(check_trac_settings([{'trac_cat': 1, 'trac_link': 'title', 'z': 0}], 't')) == \
        ['t[0].z', 't[0].trac_cat', 't[0].trac_link']
    assert paths(check_trac_settings([{'trac_cat': 'B', 'trac_link': 'p_link'}], 't', {'A'})) == ['t[0].trac_cat']


# ------------------------------------------------------------------ the validator registry

def good_spec(**params):
    spec = copy_config(GOOD_SPEC)
    spec['params'].update(params)
    return spec


def data_item_spec_errors(specs):
    return check_validator_specs(specs, 'cats.DataItem.validators', TEMPLATE, 'DataItem')


def test_registry_contains_only_explicitly_supported_validators():
    assert sorted(VALIDATORS) == ['link_conditional_reference']
    for function, params in VALIDATORS.values():
        assert set(params.values()) <= {'str', 'link', 'cat', 'attr'}


def test_a_valid_spec_passes():
    assert data_item_spec_errors([]) == []
    assert data_item_spec_errors([GOOD_SPEC]) == []
    assert check_validator_specs([GOOD_SPEC], 'v') == []


@pytest.mark.parametrize('name', ['does_not_exist', 'os.system', '__import__',
                                  'editor.cat_validators._link_conditional_reference', '',
                                  'LINK_CONDITIONAL_REFERENCE', 5, None, ['x']])
def test_unknown_validator_name_is_an_error_at_the_name_path(name):
    errors = data_item_spec_errors([{'name': name, 'params': {}}])
    assert paths(errors) == ['cats.DataItem.validators[0].name']
    assert 'unknown validator' in errors[0][1]


def test_nothing_is_imported_or_executed_for_an_unknown_name():
    with mock.patch('importlib.import_module') as import_module, mock.patch('builtins.eval') as evaluate, \
            mock.patch('builtins.exec') as execute:
        errors = check_validator_specs([{'name': 'os.system', 'params': {'command': 'true'}}], 'v')
    assert paths(errors) == ['v[0].name']
    # (mock itself resolves 'builtins' through import_module; nothing else may be imported)
    assert [c for c in import_module.call_args_list if c.args != ('builtins',)] == []
    evaluate.assert_not_called()
    execute.assert_not_called()


def test_structure_errors():
    assert paths(data_item_spec_errors({})) == ['cats.DataItem.validators']
    assert paths(data_item_spec_errors(['x'])) == ['cats.DataItem.validators[0]']
    assert paths(data_item_spec_errors([{}])) == ['cats.DataItem.validators[0].name']
    assert paths(data_item_spec_errors([{'name': GOOD_SPEC['name']}])) == ['cats.DataItem.validators[0].params']
    assert paths(data_item_spec_errors([dict(GOOD_SPEC, code='1+1')])) == ['cats.DataItem.validators[0].code']


@pytest.mark.parametrize('params,key', [
    ({'extra': 'x'}, 'extra'), ({'link': 'p_kind'}, 'link'), ({'ref_link': 'x'}, 'ref_link'),
    ({'message': ''}, 'message'), ({'message': 7}, 'message'), ({'message': 'x' * 301}, 'message'),
    ({'when_link_cat': 'Nope'}, 'when_link_cat'), ({'ref_cat': 'Nope'}, 'ref_cat'), ({'field': 'nope'}, 'field')])
def test_parameter_errors(params, key):
    assert paths(data_item_spec_errors([good_spec(**params)])) == ['cats.DataItem.validators[0].params.' + key]


def test_a_missing_parameter_is_an_error():
    missing = good_spec()
    del missing['params']['ref_cat']
    assert paths(data_item_spec_errors([missing])) == ['cats.DataItem.validators[0].params.ref_cat']


def test_references_are_only_checked_with_a_configuration():
    assert check_validator_specs([good_spec(ref_cat='Nope')], 'v') == []


def test_unknown_validator_in_a_stored_configuration_rejects_the_item(w):
    configure(w.project, lambda cats: cats['DataItem'].update(validators=[{'name': 'os.system', 'params': {}}]))
    enum_type = make(w.project, 'EnumType', 'e')
    message = cat_checks(w.project, 'DataItem', p_link=enum_type, value='x')
    assert message.startswith('Configuration error at cats.DataItem.validators[0].name'), message
    # the item is rejected even though its value would be accepted by a data item without enum type
    item_type = make(w.project, 'DataItemType', 't')
    assert cat_checks(w.project, 'DataItem', p_link=item_type, value='x').startswith('Configuration error')


def test_unknown_validator_makes_the_form_invalid(w):
    configure(w.project, lambda cats: cats['DataItem'].update(validators=[{'name': 'nope', 'params': {}}]))
    enum_type = make(w.project, 'EnumType', 'e')
    form = data_item_form(w.project, data={'domain': 'D', 'name': 'n', 'title': 'T', 'value': '#iref:1',
                                           'p_kind': 'CNS', 'p_link': str(enum_type.id)})
    assert not form.is_valid()
    assert form.non_field_errors()[0].startswith('Configuration error at')


def test_malformed_validator_list_in_a_stored_configuration(w):
    configure(w.project, lambda cats: cats['DataItem'].update(validators='oops'))
    assert cat_checks(w.project, 'DataItem').startswith('Configuration error at cats.DataItem.validators')
    assert run_validators(None, {}, [good_spec(link='x')], 'v').startswith('Configuration error at v[0]')


def test_registered_functions_are_used_by_name_only(monkeypatch):
    called = []
    monkeypatch.setitem(VALIDATORS, 'probe', (lambda form, cd, params: called.append(params) or 'probe says no',
                                              {'text': 'str'}))
    assert run_validators(None, {}, [{'name': 'probe', 'params': {'text': 'x'}}], 'v') == 'probe says no'
    assert called == [{'text': 'x'}]


# ------------------------------------------------------------------ configurations derived from the template for data
# They satisfy the relationship schema without any format change.

@pytest.mark.parametrize('cat', ALL_CATS)
def test_every_single_category_filter_output_satisfies_the_schema(cat):
    project, _ = make_project('P_' + cat, cats=[cat])
    assert schema_errors(filter_template_for_data(load_template(), project)) == []


@pytest.mark.parametrize('cat', ['DataItem', 'Packet', 'VerLink', 'DerPacket'])
def test_data_only_categories_satisfy_the_schema(cat):
    project, _ = make_project('D_' + cat, cats=[])
    make(project, cat, 'only')
    assert schema_errors(filter_template_for_data(load_template(), project)) == []


def config_for(name, cats, **data):
    project, _ = make_project(name, cats=cats)
    for cat, fields in data.items():
        make(project, cat, 'x', **fields)
    return filter_template_for_data(load_template(), project)


def test_relationship_settings_follow_the_categories_kept():
    packet = config_for('Q1', ['Packet'])['cats']['Packet']
    assert packet['links'] == {}                                           # Service, EnumType removed
    packet = config_for('Q2', ['Packet', 'Service'])['cats']['Packet']
    assert packet['links'] == {'p_link': {'targets': ['Service']}}
    assert config_for('Q3', ['DataItem'])['cats']['DataItem']['validators'] == []
    assert config_for('Q4', ['DataItem', 'EnumType'])['cats']['DataItem']['validators'] == []
    full = config_for('Q5', ['DataItem', 'EnumType', 'EnumValue'])['cats']['DataItem']
    assert full['validators'] == TEMPLATE['cats']['DataItem']['validators']
    assert full['links'] == {'p_link': {'targets': ['EnumType']}}
    # A data item category kept only through its data loses the validator when its `value` is not stored
    assert config_for('Q6', ['EnumType', 'EnumValue'], DataItem={'title': 'T'})['cats']['DataItem']['validators'] == []
    assert config_for('Q7', ['EnumType', 'EnumValue'], DataItem={'value': 'v'})['cats']['DataItem']['validators'] == \
        TEMPLATE['cats']['DataItem']['validators']


def test_pruning_does_not_modify_the_template():
    template = load_template()
    snapshot = copy_config(template)
    project, _ = make_project('Pr', cats=['Packet'])
    config = filter_template_for_data(template, project)
    config['cats']['Packet']['links']['x'] = 1
    assert template == snapshot


# ------------------------------------------------------------------ no category names in the code

@pytest.mark.parametrize('name', list(SOURCE_FILES))
def test_no_category_name_literals_in_the_code(name):
    source = SOURCE_FILES[name].read_text()
    assert [cat for cat in ALL_CATS if re.search(r'''["']%s["']''' % cat, source)] == []


@pytest.mark.parametrize('name', list(SOURCE_FILES))
def test_no_category_comparisons_on_the_item_category_attribute(name):
    source = SOURCE_FILES[name].read_text()
    assert re.search(r'\bcat\s*(==|!=|in)\s*[\[\(\'"]', source) is None
    assert '.cat ==' not in source
