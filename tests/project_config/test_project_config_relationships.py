"""Phase 3: declarative relationship rules (`links`), traceability settings (`tracs`) and category validators.

The expected values below come from the Phase 0 inventory (project_config_phase0_inventory.md, section B), not
from the template, so that the template is checked against the behavior that existed before the migration.
"""
import copy
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

import editor
from editor.cat_validators import VALIDATORS, check_validator_specs, run_validators
from editor.configs import do_cat_specific_checks, get_p_link_choices, get_s_link_choices
from editor.forms import SpecItemForm
from editor.link_rules import check_link_rule, check_link_rules, check_trac_settings, get_link_choices
from editor.models import Project, SpecItem, ValSet
from editor.project_config import (add_missing_relationship_settings, filter_template_for_data, get_project_config,
                                   load_template, resolve_config)
from tests.project_config.base import ALL_CATS, EditorTestCase, TEMPLATE, now

# Inventory B1: link target categories per category (a category not listed offers no choices).
P_LINK_TARGETS = {
    'DataItem': {'DataItemType', 'EnumType'}, 'RiskScenario': {'OpContext'}, 'VerLink': {'VerItem'},
    'Packet': {'Service'}, 'InCommand': {'Packet', 'DerPacket'}, 'OutComponent': {'Packet', 'DerPacket'},
    'PacketPar': {'Packet', 'DerPacket'}, 'DerPacket': {'EnumValue'}, 'AdaptPoint': {'Requirement'},
}
S_LINK_TARGETS = {
    'RiskScenario': {'DisrEvt'}, 'EnumValue': {'EnumType'}, 'PacketPar': {'DataItem'}, 'DerPacket': {'Packet'},
    'Packet': {'EnumType'}, 'VerStep': {'VerItem'}, 'VerLink': set(ALL_CATS) - {'VerItem', 'VerLink'},
}
# Inventory B3: traceability settings per category.
TRACS = {
    'ParReq': [('TracLink', 's_link'), ('VerLink', 's_link')], 'DerReq': [('TracLink', 'p_link'), ('VerLink', 's_link')],
    'VerItem': [('VerLink', 'p_link')], 'OpContext': [('RiskScenario', 'p_link')], 'DisrEvt': [('RiskScenario', 's_link')],
    **{cat: [('VerLink', 's_link')] for cat in ('Requirement', 'SysReq', 'Service', 'Packet', 'DerPacket', 'PacketPar',
                                                'InCommand', 'OutComponent', 'DataItem')},
}
ENUM_MSG = 'Data item value must be a reference to an enumerated value of the item type'
SOURCE_FILES = {name: Path(editor.__file__).parent / name for name in (
    'configs.py', 'link_rules.py', 'cat_validators.py', 'config_validation.py', 'config_cleanup.py')}


def schema_errors(config):
    """All Phase 3 schema errors of a complete configuration."""
    cats, errors = set(config['cats']), []
    for cat, definition in config['cats'].items():
        errors += check_link_rules(definition['links'], 'cats.%s.links' % cat, cats)
        errors += check_trac_settings(definition['tracs'], 'cats.%s.tracs' % cat, cats)
        errors += check_validator_specs(definition['validators'], 'cats.%s.validators' % cat, config, cat)
    return errors


class RelationshipTestCase(EditorTestCase):
    def make(self, project, cat, name, application=None, status='CNF', **fields):
        """A SpecItem created directly; works for categories the template does not know."""
        return SpecItem.objects.create(cat=cat, domain='D', name=name, project=project, application=application,
                                       val_set=ValSet.objects.get(project=project, name='Default'), status=status,
                                       owner=project.owner, updated_at=now(), created_at=now(), **fields)

    def configure(self, project, mutate=None, new_cats=()):
        """Store a copy of the template (plus new categories copied from InfoItem) as the project's configuration."""
        config = copy.deepcopy(TEMPLATE)
        for cat in new_cats:
            config['cats'][cat] = copy.deepcopy(TEMPLATE['cats']['InfoItem'])
            config['cats'][cat]['name'] = cat
        if mutate:
            mutate(config['cats'])
        project.config = config
        project.save(update_fields=['config'])
        return get_project_config(project)


class TemplateRulesTests(RelationshipTestCase):
    def test_every_category_has_both_settings(self):
        for cat, definition in TEMPLATE['cats'].items():
            with self.subTest(cat=cat):
                self.assertIsInstance(definition['links'], dict)
                self.assertIsInstance(definition['validators'], list)

    def test_link_targets_equal_the_inventory(self):
        for cat in ALL_CATS:
            for link, expected in (('p_link', P_LINK_TARGETS), ('s_link', S_LINK_TARGETS)):
                with self.subTest(cat=cat, link=link):
                    rule = TEMPLATE['cats'][cat]['links'].get(link)
                    if cat not in expected:
                        self.assertIsNone(rule)
                    elif cat == 'VerLink' and link == 's_link':
                        self.assertEqual((set(rule['all_except']), 'targets' in rule), ({'VerItem', 'VerLink'}, False))
                    else:
                        self.assertEqual(set(rule['targets']), expected[cat])

    def test_specification_confirmed_pairs_are_present(self):
        links = {cat: TEMPLATE['cats'][cat]['links'] for cat in ALL_CATS}
        for cat, link, target in [('DataItem', 'p_link', 'DataItemType'), ('DataItem', 'p_link', 'EnumType'),
                                  ('DerPacket', 'p_link', 'EnumValue'), ('Packet', 'p_link', 'Service'),
                                  ('PacketPar', 'p_link', 'Packet'), ('PacketPar', 'p_link', 'DerPacket'),
                                  ('InCommand', 'p_link', 'Packet'), ('OutComponent', 'p_link', 'Packet'),
                                  ('DerPacket', 's_link', 'Packet'), ('EnumValue', 's_link', 'EnumType'),
                                  ('Packet', 's_link', 'EnumType'), ('PacketPar', 's_link', 'DataItem')]:
            self.assertIn(target, links[cat][link]['targets'], (cat, link))

    def test_scope_order_and_dependency_settings(self):
        links = {cat: TEMPLATE['cats'][cat]['links'] for cat in ALL_CATS}
        self.assertEqual(links['AdaptPoint']['p_link']['scope'], 'application')
        self.assertEqual(links['VerLink']['s_link']['order_by'], ['cat', 'domain', 'name'])
        self.assertEqual(links['DerPacket']['p_link']['narrow_by_other_parent'],
                         {'target_field': 's_link', 'parent_field': 's_link'})
        explicit = {(cat, link, key) for cat in ALL_CATS for link, rule in links[cat].items()
                    for key in ('scope', 'order_by', 'narrow_by_other_parent') if key in rule}
        self.assertEqual(explicit, {('AdaptPoint', 'p_link', 'scope'), ('VerLink', 's_link', 'order_by'),
                                    ('DerPacket', 'p_link', 'narrow_by_other_parent')})

    def test_traceability_settings_equal_the_inventory(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                self.assertEqual([(t['trac_cat'], t['trac_link']) for t in TEMPLATE['cats'][cat]['tracs']],
                                 TRACS.get(cat, []))

    def test_only_the_data_item_rule_is_a_validator(self):
        for cat in ALL_CATS:
            self.assertEqual(len(TEMPLATE['cats'][cat]['validators']), 1 if cat == 'DataItem' else 0, cat)
        self.assertEqual(TEMPLATE['cats']['DataItem']['validators'], [{
            'name': 'link_conditional_reference',
            'params': {'field': 'value', 'link': 'p_link', 'when_link_cat': 'EnumType', 'ref_cat': 'EnumValue',
                       'ref_link': 's_link', 'message': ENUM_MSG}}])

    def test_the_template_satisfies_the_schema(self):
        self.assertEqual(schema_errors(TEMPLATE), [])
        self.assertEqual(schema_errors(load_template()), [])

    def test_kind_choices_are_still_category_specific_maps(self):
        for cat in ALL_CATS:
            for key in ('p_kind_choices', 's_kind_choices'):
                self.assertIsInstance(TEMPLATE['cats'][cat][key], dict, (cat, key))
        self.assertEqual(list(TEMPLATE['cats']['Requirement']['p_kind_choices']), ['STD', 'CNS', 'DEF', 'PRP', 'AP'])


class MigratedRuleTests(RelationshipTestCase):
    """Every inventoried rule, evaluated against one item of every template category."""

    def setUp(self):
        super().setUp()
        self.items = {}
        for cat in ALL_CATS:
            application = self.application if TEMPLATE['cats'][cat]['level'] == 'application' else None
            self.items[cat] = self.make(self.project, cat, 'i_' + cat, application=application)

    def choices(self, link, cat, application=None, parent_id=None, other_parent_id=None):
        function = get_p_link_choices if link == 'p_link' else get_s_link_choices
        return function(cat, self.project, application, parent_id, other_parent_id, get_project_config(self.project))

    def test_choices_of_every_category_and_link(self):
        for cat in ALL_CATS:
            for link, expected in (('p_link', P_LINK_TARGETS), ('s_link', S_LINK_TARGETS)):
                with self.subTest(cat=cat, link=link):
                    application = self.application if cat == 'AdaptPoint' else None
                    got = {item.cat for item in self.choices(link, cat, application)}
                    self.assertEqual(got, expected.get(cat, set()))

    def test_adapt_point_choices_need_an_application(self):
        self.assertEqual(list(self.choices('p_link', 'AdaptPoint')), [])
        self.assertEqual(list(self.choices('p_link', 'AdaptPoint', self.application)), [self.items['Requirement']])
        other = self.make_application(self.project, 'Other')
        self.assertEqual(list(self.choices('p_link', 'AdaptPoint', other)), [])

    def test_ordering(self):
        self.make(self.project, 'Packet', 'a_first')
        self.make(self.project, 'DerPacket', 'b_second')
        names = [(i.domain, i.name) for i in self.choices('p_link', 'PacketPar')]
        self.assertEqual(names, sorted(names))
        ordered = [(i.cat, i.domain, i.name) for i in self.choices('s_link', 'VerLink')]
        self.assertEqual(ordered, sorted(ordered))

    def test_deleted_and_obsolete_items_are_not_offered(self):
        for status in ('DEL', 'OBS'):
            self.make(self.project, 'Service', 'gone_' + status, status=status)
        self.assertEqual(list(self.choices('p_link', 'Packet')), [self.items['Service']])
        self.assertNotIn('DEL', {i.status for i in self.choices('s_link', 'VerLink')})

    def test_items_of_other_projects_are_not_offered(self):
        other, _ = self.make_project('Other', owner=self.owner)
        self.make(other, 'Service', 'foreign')
        self.assertEqual(list(self.choices('p_link', 'Packet')), [self.items['Service']])

    def test_parent_override_applies_to_every_rule(self):
        parent = self.items['DataItem']
        self.assertEqual(list(self.choices('p_link', 'Packet', parent_id=str(parent.id))), [parent])
        self.assertEqual(list(self.choices('s_link', 'ParReq', parent_id=parent.id)), [parent])      # no rule at all
        other, _ = self.make_project('Other', owner=self.owner)
        foreign = self.make(other, 'Service', 'foreign')
        self.assertEqual(list(self.choices('p_link', 'Packet', parent_id=foreign.id)), [])

    def test_der_packet_enum_values_follow_the_expanded_packet(self):
        type_a, type_b = self.items['EnumType'], self.make(self.project, 'EnumType', 'T2')
        value_a = self.make(self.project, 'EnumValue', 'va', s_link=type_a)
        value_b = self.make(self.project, 'EnumValue', 'vb', s_link=type_b)
        packet = self.make(self.project, 'Packet', 'pk', s_link=type_b)
        untyped = self.items['EnumValue']
        self.assertEqual(list(self.choices('p_link', 'DerPacket')), [untyped, value_a, value_b])
        self.assertEqual(list(self.choices('p_link', 'DerPacket', other_parent_id=packet.id)), [value_b])
        # The dependency is part of the p_link rule only: s_link of DerPacket ignores the other parent
        self.assertEqual(list(self.choices('s_link', 'DerPacket', other_parent_id=value_a.id)),
                         [self.items['Packet'], packet])

    def test_der_packet_dependency_on_a_parent_without_type(self):
        value_typed = self.make(self.project, 'EnumValue', 'va', s_link=self.items['EnumType'])
        value_untyped = self.make(self.project, 'EnumValue', 'vu')
        packet = self.make(self.project, 'Packet', 'pk')
        # Same as the original code: a parent without type selects the targets without type
        self.assertEqual(list(self.choices('p_link', 'DerPacket', other_parent_id=packet.id)),
                         [self.items['EnumValue'], value_untyped])
        self.assertNotIn(value_typed, self.choices('p_link', 'DerPacket', other_parent_id=packet.id))

    def test_dependency_parent_of_another_project_is_rejected(self):
        other, _ = self.make_project('Other', owner=self.owner)
        foreign = self.make(other, 'Packet', 'pk')
        with self.assertRaises(SpecItem.DoesNotExist):
            list(self.choices('p_link', 'DerPacket', other_parent_id=foreign.id))

    def test_enum_typed_data_item_value_check(self):
        enum_type = self.items['EnumType']
        value = self.make(self.project, 'EnumValue', 'v1', s_link=enum_type)
        other_value = self.make(self.project, 'EnumValue', 'v2', s_link=self.make(self.project, 'EnumType', 'T2'))

        def check(p_link, text):
            form = SimpleNamespace(cat='DataItem', project=self.project, cleaned_data={'p_link': p_link, 'value': text})
            return do_cat_specific_checks(form, get_project_config(form.project))

        self.assertEqual(check(enum_type, '#iref:%d' % value.id), '')
        self.assertEqual(check(enum_type, ' #iref:%d ' % value.id), '')
        for text in ('5', '', '#iref:%d x' % value.id, 'x #iref:%d' % value.id, '#iref:1 #iref:2'):
            self.assertEqual(check(enum_type, text), ENUM_MSG, text)
        self.assertEqual(check(enum_type, '#iref:%d' % other_value.id), ENUM_MSG)
        self.assertEqual(check(enum_type, '#iref:%d' % self.items['DataItemType'].id), ENUM_MSG + ': The reference is invalid')
        self.assertEqual(check(enum_type, '#iref:999999'), ENUM_MSG + ': The reference is invalid')
        self.assertEqual(check(self.items['DataItemType'], 'anything'), '')          # not an enumerated type
        self.assertEqual(check(None, 'anything'), '')

    def test_categories_without_validators_pass(self):
        for cat in ALL_CATS:
            if cat != 'DataItem':
                form = SimpleNamespace(cat=cat, project=self.project, cleaned_data={'p_link': self.items['EnumType']})
                self.assertEqual(do_cat_specific_checks(form, get_project_config(form.project)), '', cat)


class ProjectSpecificRulesTests(RelationshipTestCase):
    """Rules come from the project's configuration: other settings give other choices, no code change."""

    def test_two_projects_have_different_rules_for_the_same_category(self):
        other, _ = self.make_project('Other', owner=self.owner)
        for project in (self.project, other):
            self.make(project, 'Service', 'svc')
            self.make(project, 'EnumType', 'enum')
        self.configure(other, lambda cats: cats['Packet']['links']['p_link'].update(targets=['EnumType']))
        self.assertEqual([i.cat for i in get_p_link_choices('Packet', self.project, None, None, None, get_project_config(self.project))], ['Service'])
        self.assertEqual([i.cat for i in get_p_link_choices('Packet', other, None, None, None, get_project_config(other))], ['EnumType'])

    def test_a_new_category_with_declarative_relationships_behaves_like_an_existing_one(self):
        def add_rules(cats):
            cats['Widget']['links'] = {
                'p_link': {'targets': ['Gadget', 'Part'], 'narrow_by_other_parent': {'target_field': 'p_link',
                                                                                     'parent_field': 'p_link'}},
                's_link': {'all_except': ['Widget'], 'scope': 'application', 'order_by': ['name', 'domain']}}
        config = self.configure(self.project, add_rules, new_cats=('Widget', 'Gadget', 'Part'))
        self.assertEqual(schema_errors(config), [])
        gadget, part = self.make(self.project, 'Gadget', 'g'), self.make(self.project, 'Part', 'p')
        self.make(self.project, 'ParReq', 'r', application=self.application)
        self.make(self.project, 'Gadget', 'deleted', status='DEL')
        self.assertEqual(list(get_p_link_choices('Widget', self.project, None, None, None, get_project_config(self.project))), [gadget, part])
        # scope "application": nothing without an application, only that application's items with one
        self.assertEqual(list(get_s_link_choices('Widget', self.project, None, None, None, get_project_config(self.project))), [])
        app_item = SpecItem.objects.get(name='r')
        self.assertEqual(list(get_s_link_choices('Widget', self.project, self.application, None, None, get_project_config(self.project))), [app_item])
        # dependency on the other parent (compares p_link of the targets with p_link of the parent)
        parent = self.make(self.project, 'Gadget', 'parent_of', p_link=part)
        child_a = self.make(self.project, 'Part', 'child_a', p_link=part)
        self.make(self.project, 'Part', 'child_b', p_link=gadget)
        self.assertEqual(list(get_p_link_choices('Widget', self.project, None, None, parent.id, get_project_config(self.project))), [child_a, parent])

    def test_a_category_without_a_rule_offers_nothing(self):
        self.configure(self.project, new_cats=('Widget',))
        self.make(self.project, 'Gadget', 'g')
        for function in (get_p_link_choices, get_s_link_choices):
            self.assertEqual(list(function('Widget', self.project, None, None, None, get_project_config(self.project))), [])
            self.assertEqual(list(function('NotConfigured', self.project, None, None, None, get_project_config(self.project))), [])

    def test_a_removed_rule_offers_nothing(self):
        self.make(self.project, 'Service', 'svc')
        self.configure(self.project, lambda cats: cats['Packet']['links'].pop('p_link'))
        self.assertEqual(list(get_p_link_choices('Packet', self.project, None, None, None, get_project_config(self.project))), [])

    def test_malformed_rules_offer_nothing_and_do_not_raise(self):
        self.make(self.project, 'Service', 'svc')
        for rule in ('Service', ['Service'], {}, {'targets': 'Service'}, {'targets': [1]}, {'targets': []},
                     {'targets': ['Service'], 'all_except': []}, {'targets': ['Service'], 'scope': 'x'},
                     {'targets': ['Service'], 'order_by': ['title']}, {'targets': ['Service'], 'bogus': 1},
                     {'targets': ['Service'], 'narrow_by_other_parent': {'target_field': 'cat', 'parent_field': 's_link'}}):
            with self.subTest(rule=rule):
                self.configure(self.project, lambda cats: cats['Packet']['links'].update(p_link=rule))
                self.assertEqual(list(get_p_link_choices('Packet', self.project, None, None, None, get_project_config(self.project))), [])

    def test_an_explicit_configuration_overrides_the_project(self):
        service = self.make(self.project, 'Service', 'svc')
        config = copy.deepcopy(TEMPLATE)
        config['cats']['Packet']['links']['p_link']['targets'] = ['EnumType']
        self.assertEqual(list(get_p_link_choices('Packet', self.project, None, None, None, config)), [])
        self.assertEqual(list(get_p_link_choices('Packet', self.project, None, None, None, get_project_config(self.project))), [service])
        self.assertEqual(list(get_link_choices(config, 'p_link', 'Packet', self.project, None, None, None)), [])

    def test_the_form_offers_the_choices_of_the_project_configuration(self):
        self.configure(self.project, lambda cats: cats['DataItem']['links']['p_link'].update(targets=['EnumType']))
        enum_type, item_type = self.make(self.project, 'EnumType', 'e'), self.make(self.project, 'DataItemType', 't')
        other, _ = self.make_project('Other', owner=self.owner)
        other_type = self.make(other, 'DataItemType', 't')
        self.assertEqual(list(self.data_item_form().fields['p_link'].queryset), [enum_type])
        self.assertEqual(list(self.data_item_form(project=other).fields['p_link'].queryset), [other_type])   # default rule
        self.assertNotIn(item_type, self.data_item_form().fields['p_link'].queryset)

    def data_item_form(self, project=None, data=None):
        project = project or self.project
        return SpecItemForm('add', None, 'DataItem', project, None, get_project_config(project), None, None,
                            **({'data': data} if data is not None else {}))

    def post(self, enum_type, **overrides):
        data = {'domain': 'D', 'name': 'new', 'title': 'T', 'desc': '', 'value': 'plain text', 'rationale': '',
                'implementation': '', 'remarks': '', 'change_log': '', 'p_kind': 'CNS', 'p_link': str(enum_type.id),
                't1': '', 't2': ''}
        data.update(overrides)
        return data

    def test_the_form_applies_the_validators_of_the_project_configuration(self):
        enum_type = self.make(self.project, 'EnumType', 'e')
        other, _ = self.make_project('Other', owner=self.owner)
        other_enum_type = self.make(other, 'EnumType', 'e')
        self.configure(other, lambda cats: cats['DataItem'].update(validators=[]))
        default_form = self.data_item_form(data=self.post(enum_type))
        self.assertFalse(default_form.is_valid())
        self.assertEqual(default_form.non_field_errors(), [ENUM_MSG])
        form = self.data_item_form(project=other, data=self.post(other_enum_type))
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_new_category_validator_behaves_like_the_data_item_one(self):
        def add_validator(cats):
            cats['Widget']['validators'] = [{'name': 'link_conditional_reference', 'params': {
                'field': 'value', 'link': 's_link', 'when_link_cat': 'Gadget', 'ref_cat': 'Part',
                'ref_link': 'p_link', 'message': 'Widget value must reference a part of the gadget'}}]
        config = self.configure(self.project, add_validator, new_cats=('Widget', 'Gadget', 'Part'))
        self.assertEqual(schema_errors(config), [])
        gadget, other_gadget = self.make(self.project, 'Gadget', 'g'), self.make(self.project, 'Gadget', 'g2')
        part = self.make(self.project, 'Part', 'p', p_link=gadget)
        message = 'Widget value must reference a part of the gadget'

        def check(s_link, text):
            return do_cat_specific_checks(SimpleNamespace(cat='Widget', project=self.project,
                                                          cleaned_data={'s_link': s_link, 'value': text}), get_project_config(self.project))
        self.assertEqual(check(gadget, '#iref:%d' % part.id), '')
        self.assertEqual(check(other_gadget, '#iref:%d' % part.id), message)
        self.assertEqual(check(gadget, 'text'), message)
        self.assertEqual(check(gadget, '#iref:%d' % gadget.id), message + ': The reference is invalid')
        self.assertEqual(check(self.make(self.project, 'Part', 'q'), 'text'), '')
        self.assertEqual(check(None, 'text'), '')


class RuleSchemaTests(EditorTestCase):
    def paths(self, errors):
        return [path for path, _ in errors]

    def test_valid_rules(self):
        for rule in ({'targets': ['A']}, {'all_except': []}, {'all_except': ['A', 'B'], 'scope': 'project'},
                     {'targets': ['A'], 'scope': 'application', 'order_by': ['cat', 'name']},
                     {'targets': ['A'], 'narrow_by_other_parent': {'target_field': 'p_link', 'parent_field': 's_link'}}):
            self.assertEqual(check_link_rule(rule, 'r'), [], rule)

    def test_invalid_rules_report_precise_paths(self):
        cases = [
            ('x', ['r']), ({}, ['r']), ({'targets': ['A'], 'all_except': []}, ['r']),
            ({'targets': []}, ['r.targets']), ({'targets': 'A'}, ['r.targets']), ({'targets': [3]}, ['r.targets']),
            ({'all_except': 'A'}, ['r.all_except']), ({'targets': ['A'], 'scope': 'global'}, ['r.scope']),
            ({'targets': ['A'], 'order_by': []}, ['r.order_by']), ({'targets': ['A'], 'order_by': ['title']}, ['r.order_by']),
            ({'targets': ['A'], 'extra': 1}, ['r.extra']),
            ({'targets': ['A'], 'narrow_by_other_parent': 'x'}, ['r.narrow_by_other_parent']),
            ({'targets': ['A'], 'narrow_by_other_parent': {'target_field': 'cat', 'parent_field': 'p_link', 'z': 1}},
             ['r.narrow_by_other_parent.z', 'r.narrow_by_other_parent.target_field']),
            ({'targets': ['A'], 'narrow_by_other_parent': {}},
             ['r.narrow_by_other_parent.target_field', 'r.narrow_by_other_parent.parent_field']),
        ]
        for rule, expected in cases:
            with self.subTest(rule=rule):
                self.assertEqual(self.paths(check_link_rule(rule, 'r')), expected)

    def test_category_references_are_checked_when_categories_are_given(self):
        self.assertEqual(self.paths(check_link_rule({'targets': ['A', 'Nope']}, 'r', {'A'})), ['r.targets[1]'])
        self.assertEqual(self.paths(check_link_rule({'all_except': ['Nope']}, 'r', {'A'})), ['r.all_except[0]'])
        self.assertEqual(check_link_rule({'targets': ['A', 'Nope']}, 'r'), [])

    def test_links_object(self):
        self.assertEqual(check_link_rules({'p_link': {'targets': ['A']}, 's_link': {'all_except': []}}, 'l'), [])
        self.assertEqual(self.paths(check_link_rules({'t1': {'targets': ['A']}}, 'l')), ['l.t1'])
        self.assertEqual(self.paths(check_link_rules({'p_link': {'targets': []}}, 'l')), ['l.p_link.targets'])
        self.assertEqual(self.paths(check_link_rules([], 'l')), ['l'])

    def test_traceability_settings(self):
        self.assertEqual(check_trac_settings([{'trac_cat': 'A', 'trac_link': 's_link'}], 't', {'A'}), [])
        self.assertEqual(self.paths(check_trac_settings({}, 't')), ['t'])
        self.assertEqual(self.paths(check_trac_settings(['x'], 't')), ['t[0]'])
        self.assertEqual(self.paths(check_trac_settings([{'trac_cat': 1, 'trac_link': 'title', 'z': 0}], 't')),
                         ['t[0].z', 't[0].trac_cat', 't[0].trac_link'])
        self.assertEqual(self.paths(check_trac_settings([{'trac_cat': 'B', 'trac_link': 'p_link'}], 't', {'A'})),
                         ['t[0].trac_cat'])


class ValidatorRegistryTests(RelationshipTestCase):
    GOOD = {'name': 'link_conditional_reference',
            'params': {'field': 'value', 'link': 'p_link', 'when_link_cat': 'EnumType', 'ref_cat': 'EnumValue',
                       'ref_link': 's_link', 'message': 'm'}}

    def spec(self, **params):
        spec = copy.deepcopy(self.GOOD)
        spec['params'].update(params)
        return spec

    def errors(self, specs, config=TEMPLATE, cat='DataItem'):
        return check_validator_specs(specs, 'cats.%s.validators' % cat, config, cat)

    def test_registry_contains_only_explicitly_supported_validators(self):
        self.assertEqual(sorted(VALIDATORS), ['link_conditional_reference'])
        for function, params in VALIDATORS.values():
            self.assertTrue(callable(function))
            self.assertTrue(set(params.values()) <= {'str', 'link', 'cat', 'attr'})

    def test_a_valid_spec_passes(self):
        self.assertEqual(self.errors([]), [])
        self.assertEqual(self.errors([self.GOOD]), [])
        self.assertEqual(check_validator_specs([self.GOOD], 'v'), [])

    def test_unknown_validator_name_is_an_error_at_the_name_path(self):
        for name in ('does_not_exist', 'os.system', '__import__', 'editor.cat_validators._link_conditional_reference',
                     '', 'LINK_CONDITIONAL_REFERENCE', 5, None, ['x']):
            with self.subTest(name=name):
                errors = self.errors([{'name': name, 'params': {}}])
                self.assertEqual([path for path, _ in errors], ['cats.DataItem.validators[0].name'])
                self.assertIn('unknown validator', errors[0][1])

    def test_nothing_is_imported_or_executed_for_an_unknown_name(self):
        with mock.patch('importlib.import_module') as import_module, mock.patch('builtins.eval') as evaluate, \
                mock.patch('builtins.exec') as execute:
            errors = check_validator_specs([{'name': 'os.system', 'params': {'command': 'true'}}], 'v')
        self.assertEqual([path for path, _ in errors], ['v[0].name'])
        # (mock itself resolves 'builtins' through import_module; nothing else may be imported)
        self.assertEqual([c for c in import_module.call_args_list if c.args != ('builtins',)], [])
        evaluate.assert_not_called()
        execute.assert_not_called()

    def test_structure_errors(self):
        self.assertEqual([p for p, _ in self.errors({})], ['cats.DataItem.validators'])
        self.assertEqual([p for p, _ in self.errors(['x'])], ['cats.DataItem.validators[0]'])
        self.assertEqual([p for p, _ in self.errors([{}])], ['cats.DataItem.validators[0].name'])
        self.assertEqual([p for p, _ in self.errors([{'name': self.GOOD['name']}])], ['cats.DataItem.validators[0].params'])
        self.assertEqual([p for p, _ in self.errors([dict(self.GOOD, code='1+1')])], ['cats.DataItem.validators[0].code'])

    def test_parameter_errors(self):
        base = 'cats.DataItem.validators[0].params.'
        cases = [({'extra': 'x'}, base + 'extra'), ({'link': 'p_kind'}, base + 'link'), ({'ref_link': 'x'}, base + 'ref_link'),
                 ({'message': ''}, base + 'message'), ({'message': 7}, base + 'message'),
                 ({'message': 'x' * 301}, base + 'message'), ({'when_link_cat': 'Nope'}, base + 'when_link_cat'),
                 ({'ref_cat': 'Nope'}, base + 'ref_cat'), ({'field': 'nope'}, base + 'field')]
        for params, path in cases:
            with self.subTest(params=params):
                self.assertEqual([p for p, _ in self.errors([self.spec(**params)])], [path])
        missing = copy.deepcopy(self.GOOD)
        del missing['params']['ref_cat']
        self.assertEqual([p for p, _ in self.errors([missing])], [base + 'ref_cat'])

    def test_references_are_only_checked_with_a_configuration(self):
        self.assertEqual(check_validator_specs([self.spec(ref_cat='Nope')], 'v'), [])

    def test_unknown_validator_in_a_stored_configuration_rejects_the_item(self):
        self.configure(self.project, lambda cats: cats['DataItem'].update(validators=[{'name': 'os.system', 'params': {}}]))
        enum_type = self.make(self.project, 'EnumType', 'e')
        form = SimpleNamespace(cat='DataItem', project=self.project, cleaned_data={'p_link': enum_type, 'value': 'x'})
        message = do_cat_specific_checks(form, get_project_config(form.project))
        self.assertTrue(message.startswith('Configuration error at cats.DataItem.validators[0].name'), message)
        # the item is rejected even though its value would be accepted by a data item without enum type
        form.cleaned_data['p_link'] = self.make(self.project, 'DataItemType', 't')
        self.assertTrue(do_cat_specific_checks(form, get_project_config(form.project)).startswith('Configuration error'))

    def test_unknown_validator_makes_the_form_invalid(self):
        self.configure(self.project, lambda cats: cats['DataItem'].update(validators=[{'name': 'nope', 'params': {}}]))
        enum_type = self.make(self.project, 'EnumType', 'e')
        form = SpecItemForm('add', None, 'DataItem', self.project, None, get_project_config(self.project), None, None,
                            data={'domain': 'D', 'name': 'n', 'title': 'T', 'value': '#iref:1', 'p_kind': 'CNS',
                                  'p_link': str(enum_type.id)})
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors()[0].startswith('Configuration error at'))

    def test_malformed_validator_list_in_a_stored_configuration(self):
        self.configure(self.project, lambda cats: cats['DataItem'].update(validators='oops'))
        form = SimpleNamespace(cat='DataItem', project=self.project, cleaned_data={})
        self.assertTrue(do_cat_specific_checks(form, get_project_config(form.project)).startswith('Configuration error at cats.DataItem.validators'))
        self.assertTrue(run_validators(form, {}, [self.spec(link='x')], 'v').startswith('Configuration error at v[0]'))

    def test_registered_functions_are_used_by_name_only(self):
        called = []
        with mock.patch.dict(VALIDATORS, {'probe': (lambda form, cd, params: called.append(params) or 'probe says no',
                                                    {'text': 'str'})}):
            self.assertEqual(run_validators(None, {}, [{'name': 'probe', 'params': {'text': 'x'}}], 'v'), 'probe says no')
        self.assertEqual(called, [{'text': 'x'}])
        self.assertNotIn('probe', VALIDATORS)


class LegacyConfigurationTests(RelationshipTestCase):
    """A configuration stored before Phase 3 has no `links`/`validators`: it is completed, never overwritten."""

    def legacy(self, cats=None):
        """What Phase 1 stored: the template (or its filtered form for some categories) without the new keys."""
        if cats is None:
            config = copy.deepcopy(TEMPLATE)
        else:
            project, _ = self.make_project('Legacy_' + '_'.join(cats), owner=self.owner, cats=cats)
            config = filter_template_for_data(load_template(), project)
        for definition in config['cats'].values():
            del definition['links'], definition['validators']
        return config

    def test_missing_settings_are_added_in_memory_only(self):
        stored = self.legacy()
        snapshot = copy.deepcopy(stored)
        self.project.config = stored
        self.project.save(update_fields=['config'])
        config = get_project_config(Project.objects.get(id=self.project.id))
        for cat in ALL_CATS:
            self.assertEqual(config['cats'][cat]['links'], TEMPLATE['cats'][cat]['links'], cat)
            self.assertEqual(config['cats'][cat]['validators'], TEMPLATE['cats'][cat]['validators'], cat)
        self.assertEqual(schema_errors(config), [])
        self.assertEqual(Project.objects.get(id=self.project.id).config, snapshot)
        self.assertEqual(stored, snapshot)

    def test_legacy_projects_keep_their_choices(self):
        self.project.config = self.legacy()
        self.project.save(update_fields=['config'])
        service = self.make(self.project, 'Service', 'svc')
        self.assertEqual(list(get_p_link_choices('Packet', self.project, None, None, None, get_project_config(self.project))), [service])

    def test_owner_managed_settings_are_never_overwritten(self):
        stored = self.legacy(['Packet', 'Service', 'EnumType', 'DataItem'])
        stored['cats']['Packet']['links'] = {}                                        # the owner removed the rules
        stored['cats']['DataItem']['validators'] = []                                 # ... and a validator
        stored['cats']['Service']['links'] = {'s_link': {'targets': ['EnumType']}}
        config = resolve_config(stored)
        self.assertEqual(config['cats']['Packet']['links'], {})
        self.assertEqual(config['cats']['DataItem']['validators'], [])
        self.assertEqual(config['cats']['Service']['links'], {'s_link': {'targets': ['EnumType']}})
        self.assertEqual(config['cats']['DataItem']['links'], {'p_link': {'targets': ['EnumType']}})     # missing: added
        self.assertEqual(config['cats']['Service']['validators'], [])

    def test_added_settings_refer_only_to_categories_of_the_configuration(self):
        config = resolve_config(self.legacy(['Packet', 'DataItem']))
        self.assertEqual(config['cats']['Packet']['links'], {})                       # Service, EnumType not configured
        self.assertEqual(config['cats']['DataItem']['links'], {})
        self.assertEqual(config['cats']['DataItem']['validators'], [])               # EnumType, EnumValue not configured
        self.assertEqual(schema_errors(config), [])

    def test_categories_unknown_to_the_template_are_left_alone(self):
        stored = self.legacy(['Packet'])
        stored['cats']['Widget'] = {'name': 'Widget', 'attrs': {}}
        config = resolve_config(stored)
        self.assertEqual(config['cats']['Widget'], {'name': 'Widget', 'attrs': {}})

    def test_current_configurations_are_not_touched_and_the_template_is_not_read(self):
        stored = copy.deepcopy(TEMPLATE)
        with mock.patch('editor.project_config.load_template', side_effect=AssertionError):
            self.assertFalse(add_missing_relationship_settings(stored))
            resolve_config(stored)
        self.assertEqual(stored, TEMPLATE)

    def test_malformed_configurations_do_not_raise(self):
        for stored in ({'cats': []}, {'cats': {'A': 'x'}}, {'general': {}}, {'cats': None}):
            self.assertFalse(add_missing_relationship_settings(copy.deepcopy(stored)))
            resolve_config(stored)
        self.assertFalse(add_missing_relationship_settings([]))

    def run_command(self, *args):
        call_command('init_project_configs', *args, stdout=mock.MagicMock(), stderr=mock.MagicMock())

    def test_the_command_persists_the_upgrade_only_when_asked(self):
        stored = self.legacy(['Packet', 'Service', 'EnumType', 'DataItem', 'EnumValue'])
        stored['cats']['Packet']['links'] = {}
        self.project.config = stored
        self.project.save(update_fields=['config'])
        updated_at = Project.objects.get(id=self.project.id).updated_at
        item = self.make(self.project, 'Service', 'svc')

        self.run_command()
        self.assertEqual(Project.objects.get(id=self.project.id).config, stored)       # skipped as before
        self.run_command('--upgrade-format', '--dry-run')
        self.assertEqual(Project.objects.get(id=self.project.id).config, stored)
        self.run_command('--upgrade-format')

        project = Project.objects.get(id=self.project.id)
        self.assertEqual(project.updated_at, updated_at)
        self.assertEqual(project.config['cats']['Packet']['links'], {})               # owner's choice kept
        self.assertEqual(project.config['cats']['DataItem']['validators'], TEMPLATE['cats']['DataItem']['validators'])
        self.assertEqual(project.config['cats']['EnumValue']['links'], TEMPLATE['cats']['EnumValue']['links'])
        self.assertEqual(schema_errors(project.config), [])
        for cat, definition in stored['cats'].items():                                  # nothing else changed
            self.assertEqual({k: v for k, v in project.config['cats'][cat].items() if k not in ('links', 'validators')},
                             {k: v for k, v in definition.items() if k not in ('links', 'validators')})
        self.assertEqual(SpecItem.objects.get(id=item.id).name, 'svc')

        with CaptureQueriesContext(connection) as queries:
            self.run_command('--upgrade-format')
        self.assertEqual([q['sql'] for q in queries.captured_queries if re.match(r'\s*(UPDATE|INSERT|DELETE)', q['sql'])], [])


class InitializedConfigurationTests(RelationshipTestCase):
    """Configurations initialized in Phase 1 satisfy the Phase 3 schema without any format change."""

    def test_every_single_category_filter_output_satisfies_the_schema(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                project, _ = self.make_project('P_' + cat, owner=self.owner, cats=[cat])
                self.assertEqual(schema_errors(filter_template_for_data(load_template(), project)), [])

    def test_data_only_categories_satisfy_the_schema(self):
        for cat in ('DataItem', 'Packet', 'VerLink', 'DerPacket'):
            with self.subTest(cat=cat):
                project, _ = self.make_project('D_' + cat, owner=self.owner, cats=[])
                self.make(project, cat, 'only')
                self.assertEqual(schema_errors(filter_template_for_data(load_template(), project)), [])

    def test_relationship_settings_follow_the_categories_kept(self):
        counter = iter(range(100))

        def config_for(cats, **data):
            project, _ = self.make_project('Q%d' % next(counter), owner=self.owner, cats=cats)
            for cat, fields in data.items():
                self.make(project, cat, 'x', **fields)
            return filter_template_for_data(load_template(), project)

        packet = config_for(['Packet'])['cats']['Packet']
        self.assertEqual(packet['links'], {})                                           # Service, EnumType removed
        packet = config_for(['Packet', 'Service'])['cats']['Packet']
        self.assertEqual(packet['links'], {'p_link': {'targets': ['Service']}})
        self.assertEqual(config_for(['DataItem'])['cats']['DataItem']['validators'], [])
        self.assertEqual(config_for(['DataItem', 'EnumType'])['cats']['DataItem']['validators'], [])
        full = config_for(['DataItem', 'EnumType', 'EnumValue'])['cats']['DataItem']
        self.assertEqual(full['validators'], TEMPLATE['cats']['DataItem']['validators'])
        self.assertEqual(full['links'], {'p_link': {'targets': ['EnumType']}})
        # A data item category kept only through its data loses the validator when its `value` is not stored
        self.assertEqual(config_for(['EnumType', 'EnumValue'], DataItem={'title': 'T'})['cats']['DataItem']['validators'], [])
        self.assertEqual(config_for(['EnumType', 'EnumValue'], DataItem={'value': 'v'})['cats']['DataItem']['validators'],
                         TEMPLATE['cats']['DataItem']['validators'])

    def test_the_init_command_output_satisfies_the_schema(self):
        for cats, name in ((ALL_CATS, 'All'), (['Packet', 'Service'], 'Some')):
            self.make_project(name, owner=self.owner, cats=cats)
        call_command('init_project_configs', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        for project in Project.objects.filter(name__in=('All', 'Some')):
            self.assertEqual(schema_errors(project.config), [], project.name)
        self.assertEqual(Project.objects.get(name='All').config['cats'], TEMPLATE['cats'])

    def test_pruning_does_not_modify_the_template(self):
        template = load_template()
        snapshot = copy.deepcopy(template)
        project, _ = self.make_project('Pr', owner=self.owner, cats=['Packet'])
        config = filter_template_for_data(template, project)
        config['cats']['Packet']['links']['x'] = 1
        self.assertEqual(template, snapshot)


class NoCategoryLiteralsTests(RelationshipTestCase):
    """Phase 3: no category name is hardcoded in the relationship and validation code."""

    def test_no_category_name_literals_in_the_code(self):
        for name, path in SOURCE_FILES.items():
            source = path.read_text()
            for cat in ALL_CATS:
                with self.subTest(file=name, cat=cat):
                    self.assertIsNone(re.search(r'''["']%s["']''' % cat, source))

    def test_no_category_comparisons_on_the_item_category_attribute(self):
        for name, path in SOURCE_FILES.items():
            with self.subTest(file=name):
                self.assertIsNone(re.search(r'\bcat\s*(==|!=|in)\s*[\[\(\'"]', path.read_text()))
                self.assertNotIn('.cat ==', path.read_text())
