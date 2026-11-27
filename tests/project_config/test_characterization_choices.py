"""Phase 0 characterization: link/kind choices, category-specific checks and validation rules."""
from editor.configs import get_p_link_choices, get_s_link_choices
from editor.forms import identifier_error
from editor.models import SpecItem, ValSet
from tests.project_config.base import ALL_CATS, EditorTestCase, TEMPLATE
from editor.utilities import get_p_kind_choices, get_s_kind_choices
from editor.project_config import get_project_config

# Rules currently hardcoded in editor/configs.py (see project_config_phase0_inventory.md)
P_LINK_TARGETS = {
    'DataItem': ['DataItemType', 'EnumType'],
    'RiskScenario': ['OpContext'],
    'VerLink': ['VerItem'],
    'Packet': ['Service'],
    'InCommand': ['Packet', 'DerPacket'],
    'OutComponent': ['Packet', 'DerPacket'],
    'PacketPar': ['Packet', 'DerPacket'],
    'DerPacket': ['EnumValue'],
}
S_LINK_TARGETS = {
    'RiskScenario': ['DisrEvt'],
    'EnumValue': ['EnumType'],
    'PacketPar': ['DataItem'],
    'DerPacket': ['Packet'],
    'Packet': ['EnumType'],
    'VerStep': ['VerItem'],
}
KIND_LITERALS = {
    ('Packet', 'p'): [('TC', 'Telecommand'), ('TM', 'Telemetry')],
    ('Packet', 's'): [('INV', 'Invalid')],
    ('DataItem', 'p'): [('CNS', 'Constant'), ('PAR', 'Configuration Parameter'), ('VAR', 'Global Variable'),
                        ('CTX', 'Context Variable'), ('PCK', 'Packet Parameter')],
    ('Model', 'p'): [('SM', 'State Machine'), ('PR', 'Procedure')],
    ('ComIntEvt', 'p'): [('1', 'Normal'), ('2', 'Warning'), ('3', 'Error'), ('4', 'Critical')],
    ('VerItem', 's'): [('OPEN', 'Verification Still Open'), ('CLOSED', 'Verification Closed')],
}


class LinkChoicesTests(EditorTestCase):
    """get_p_link_choices / get_s_link_choices for every category."""

    def setUp(self):
        super().setUp()
        self.other, _ = self.make_project('Other', cats=ALL_CATS)
        self.other_app = self.make_application(self.other, 'OtherApp')
        for cat in ALL_CATS:
            self.make_item(self.project, cat, 'D2', 'b_' + cat)
            self.make_item(self.project, cat, 'D1', 'z_' + cat)
            self.make_item(self.project, cat, 'D1', 'del_' + cat, status='DEL')
            self.make_item(self.project, cat, 'D1', 'obs_' + cat, status='OBS')
            self.make_item(self.other, cat, 'D1', 'other_' + cat)

    def names(self, queryset):
        return [(i.domain, i.name) for i in queryset]

    def active_sorted(self, *cats):
        items = SpecItem.objects.filter(project=self.project, cat__in=cats, status__in=('NEW', 'CNF', 'MOD'))
        return sorted((i.domain, i.name) for i in items)

    def test_p_link_choices_per_category(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                result = get_p_link_choices(cat, self.project, self.application, None, None, get_project_config(self.project))
                if cat in P_LINK_TARGETS:
                    self.assertEqual(self.names(result), self.active_sorted(*P_LINK_TARGETS[cat]))
                elif cat == 'AdaptPoint':
                    self.assertEqual(self.names(result), [('D1', 'z_Requirement'), ('D2', 'b_Requirement')])
                    self.assertTrue(all(i.application_id == self.application.id for i in result))
                else:
                    self.assertEqual(list(result), [])

    def test_p_link_choices_are_project_scoped_and_exclude_deleted_and_obsolete(self):
        result = get_p_link_choices('Packet', self.project, None, None, None, get_project_config(self.project))
        self.assertEqual(self.names(result), [('D1', 'z_Service'), ('D2', 'b_Service')])
        self.assertEqual({i.project_id for i in result}, {self.project.id})

    def test_adapt_point_p_link_requires_an_application_and_is_application_scoped(self):
        self.assertEqual(list(get_p_link_choices('AdaptPoint', self.project, None, None, None, get_project_config(self.project))), [])
        other_req = self.make_item(self.other, 'Requirement', 'D1', 'o_req', application=self.other_app)
        result = get_p_link_choices('AdaptPoint', self.other, self.other_app, None, None, get_project_config(self.other))
        self.assertEqual({i.id for i in result}, {other_req.id, SpecItem.objects.get(name='other_Requirement').id})

    def test_s_link_choices_per_category(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                result = get_s_link_choices(cat, self.project, self.application, None, None, get_project_config(self.project))
                if cat in S_LINK_TARGETS:
                    self.assertEqual(self.names(result), self.active_sorted(*S_LINK_TARGETS[cat]))
                elif cat == 'VerLink':
                    other_cats = [c for c in ALL_CATS if c not in ('VerItem', 'VerLink')]
                    expected = sorted(((i.cat, i.domain, i.name) for i in SpecItem.objects.filter(
                        project=self.project, cat__in=other_cats, status__in=('NEW', 'CNF', 'MOD'))))
                    self.assertEqual([(i.cat, i.domain, i.name) for i in result], expected)
                else:
                    self.assertEqual(list(result), [])

    def test_parent_id_overrides_the_choices(self):
        target = SpecItem.objects.get(project=self.project, name='b_Service')
        elsewhere = SpecItem.objects.get(project=self.other, name='other_Service')
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                self.assertEqual([i.id for i in get_p_link_choices(cat, self.project, None, str(target.id), None, get_project_config(self.project))], [target.id])
                # A parent of another project is never offered (parent ids are scoped to the project)
                self.assertEqual(list(get_s_link_choices(cat, self.project, None, str(elsewhere.id), None, get_project_config(self.project))), [])
                self.assertEqual(list(get_p_link_choices(cat, self.project, None, str(elsewhere.id), None, get_project_config(self.project))), [])

    def test_der_packet_p_link_is_limited_to_enum_values_of_the_s_parent_enum_type(self):
        enum1 = self.make_item(self.project, 'EnumType', 'E', 'enum1')
        enum2 = self.make_item(self.project, 'EnumType', 'E', 'enum2')
        packet = self.make_item(self.project, 'Packet', 'P', 'pkt', s_link=enum1)
        val1 = self.make_item(self.project, 'EnumValue', 'E', 'val1', s_link=enum1)
        self.make_item(self.project, 'EnumValue', 'E', 'val2', s_link=enum2)
        result = get_p_link_choices('DerPacket', self.project, None, None, str(packet.id), get_project_config(self.project))
        self.assertEqual([i.id for i in result], [val1.id])

    def test_form_querysets_follow_the_choice_functions(self):
        response = self.client.get(self.add_url('PacketPar'))
        form = response.context['form']
        self.assertEqual(self.names(form.fields['p_link'].queryset), self.active_sorted('Packet', 'DerPacket'))
        self.assertEqual(self.names(form.fields['s_link'].queryset), self.active_sorted('DataItem'))

    def test_form_rejects_a_link_to_the_wrong_category(self):
        parents = self.parent_items('PacketPar')
        service = SpecItem.objects.get(project=self.project, name='b_Service')
        payload = self.add_payload('PacketPar', parents, p_link=service.id)
        before = SpecItem.objects.count()
        response = self.client.post(self.add_url('PacketPar'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn('p_link', response.context['form'].errors)
        self.assertEqual(SpecItem.objects.count(), before)

    def test_expansion_add_restricts_the_choices_to_the_parent(self):
        enum = self.make_item(self.project, 'EnumType', 'E', 'enum1')
        response = self.client.get(self.add_url('EnumValue', '?s_parent_id=%d' % enum.id))
        self.assertEqual([i.id for i in response.context['form'].fields['s_link'].queryset], [enum.id])


class KindChoicesTests(EditorTestCase):
    def test_kind_choices_come_from_the_category_definition(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                self.assertEqual(get_p_kind_choices(TEMPLATE, cat), list(TEMPLATE['cats'][cat]['p_kind_choices'].items()))
                self.assertEqual(get_s_kind_choices(TEMPLATE, cat), list(TEMPLATE['cats'][cat]['s_kind_choices'].items()))
                form = self.client.get(self.add_url(cat)).context['form']
                self.assertEqual(list(form.fields['p_kind'].choices), get_p_kind_choices(TEMPLATE, cat))
                self.assertEqual(list(form.fields['s_kind'].choices), get_s_kind_choices(TEMPLATE, cat))

    def test_literal_kind_choices(self):
        for (cat, which), expected in KIND_LITERALS.items():
            with self.subTest(cat=cat, which=which):
                func = get_p_kind_choices if which == 'p' else get_s_kind_choices
                self.assertEqual(func(TEMPLATE, cat), expected)

    def test_invalid_kind_is_rejected(self):
        parents = self.parent_items('Packet')
        payload = self.add_payload('Packet', parents, p_kind='XX')
        response = self.client.post(self.add_url('Packet'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn('p_kind', response.context['form'].errors)
        self.assertFalse(SpecItem.objects.filter(cat='Packet').exists())

    def test_stored_kind_is_preselected_when_editing(self):
        service = self.make_item(self.project, 'Service', 'S', 'svc')
        packet = self.make_item(self.project, 'Packet', 'P', 'pkt', p_link=service, p_kind='TM', s_kind='INV')
        form = self.client.get(self.item_url('edit_spec_item', packet)).context['form']
        self.assertEqual(form['p_kind'].value(), 'TM')
        self.assertEqual(form['s_kind'].value(), 'INV')

    def test_every_kind_choice_is_accepted_when_adding(self):
        parents = self.parent_items('Packet')
        for index, kind in enumerate(TEMPLATE['cats']['Packet']['p_kind_choices']):
            payload = self.add_payload('Packet', parents, p_kind=kind, name='Item%d' % index)
            self.assertEqual(self.client.post(self.add_url('Packet'), payload).status_code, 302)
        self.assertEqual(sorted(SpecItem.objects.filter(cat='Packet').values_list('p_kind', flat=True)), ['TC', 'TM'])


class CategorySpecificCheckTests(EditorTestCase):
    """do_cat_specific_checks and the eval_ref rule of SpecItemForm.clean."""

    ENUM_ERROR = 'Data item value must be a reference to an enumerated value of the item type'

    def setUp(self):
        super().setUp()
        self.enum = self.make_item(self.project, 'EnumType', 'E', 'color', n1=1)
        self.enum_other = self.make_item(self.project, 'EnumType', 'E', 'shape', n1=1)
        self.red = self.make_item(self.project, 'EnumValue', 'E', 'red', s_link=self.enum, value='1')
        self.square = self.make_item(self.project, 'EnumValue', 'E', 'square', s_link=self.enum_other, value='1')
        self.data_item_type = self.make_item(self.project, 'DataItemType', 'T', 'int32', n1=4)

    def post_data_item(self, p_link, value):
        payload = self.add_payload('DataItem', {'p_link': p_link}, value=value)
        return self.client.post(self.add_url('DataItem'), payload)

    def test_enum_typed_data_item_accepts_a_reference_to_an_enum_value_of_its_type(self):
        response = self.post_data_item(self.enum, '#EnumValue:E:red')
        self.assertEqual(response.status_code, 302)
        item = SpecItem.objects.get(cat='DataItem')
        self.assertEqual(item.value, '#iref:%d' % self.red.id)
        self.assertEqual(item.p_link_id, self.enum.id)

    def test_enum_typed_data_item_rejects_values_which_are_not_a_single_enum_reference(self):
        for value in ('5', '#EnumValue:E:red + 1', 'x #EnumValue:E:red', '#EnumValue:E:missing'):
            with self.subTest(value=value):
                response = self.post_data_item(self.enum, value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['form'].non_field_errors(), [self.ENUM_ERROR])
                self.assertFalse(SpecItem.objects.filter(cat='DataItem').exists())

    def test_data_item_value_is_required(self):
        response = self.post_data_item(self.enum, '')
        self.assertEqual(response.status_code, 200)
        self.assertIn('value', response.context['form'].errors)

    def test_enum_typed_data_item_rejects_a_value_of_another_enum_type(self):
        response = self.post_data_item(self.enum, '#EnumValue:E:square')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].non_field_errors(), [self.ENUM_ERROR])

    def test_reference_to_a_non_enum_value_item_is_rejected(self):
        response = self.post_data_item(self.enum, '#DataItemType:T:int32')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(SpecItem.objects.filter(cat='DataItem').exists())

    def test_data_item_of_data_item_type_accepts_any_value(self):
        response = self.post_data_item(self.data_item_type, '3.14 * 2')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SpecItem.objects.get(cat='DataItem').value, '3.14 * 2')

    def test_eval_ref_field_only_accepts_references_to_eval_ref_fields(self):
        other = self.make_item(self.project, 'DataItem', 'D', 'other', p_link=self.data_item_type, value='2')
        ok = self.post_data_item(self.data_item_type, '#DataItem:D:other * 2')
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(SpecItem.objects.get(cat='DataItem', name='Item1').value, '#iref:%d * 2' % other.id)
        for ref, text in (('#Packet:P:x', 'is not of kind eval_ref'), ('#OpContext:O:x', 'does not support field')):
            with self.subTest(ref=ref):
                payload = self.add_payload('DataItem', {'p_link': self.data_item_type}, value=ref, name='Item2')
                response = self.client.post(self.add_url('DataItem'), payload)
                self.assertEqual(response.status_code, 200)
                self.assertIn(text, response.context['form'].non_field_errors()[0])
                self.assertIn('The field "value" of kind eval_ref', response.context['form'].non_field_errors()[0])


class ValidationRuleTests(EditorTestCase):
    """Identifier, uniqueness and alias (ValSet) rules of the item forms."""

    def setUp(self):
        super().setUp()
        self.service = self.make_item(self.project, 'Service', 'S', 'svc')

    def add_packet(self, **overrides):
        payload = self.add_payload('Packet', {'p_link': self.service}, **overrides)
        return self.client.post(self.add_url('Packet'), payload)

    def test_domain_and_name_must_be_identifiers(self):
        for value in ('bad name', 'a..b', '.a', 'a.', 'a/b', 'é'):
            with self.subTest(value=value):
                response = self.add_packet(name=value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['form'].errors['name'], [identifier_error])
        for value in ('a.b', 'a-b_c.d9'):
            with self.subTest(value=value):
                self.assertEqual(self.add_packet(name=value).status_code, 302)

    def test_domain_name_pair_must_be_unique_among_active_items(self):
        self.assertEqual(self.add_packet().status_code, 302)
        response = self.add_packet()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].errors['name'], ["Error: Name 'Item1' already exists in domain 'Dom1'"])
        self.assertEqual(SpecItem.objects.filter(cat='Packet').count(), 1)
        SpecItem.objects.filter(cat='Packet').update(status='DEL')
        self.assertEqual(self.add_packet().status_code, 302)         # deleted items do not block the identifier

    def test_uniqueness_spans_categories_of_the_project_only(self):
        self.make_item(self.project, 'Service', 'Dom1', 'Item1')
        self.assertEqual(self.add_packet().status_code, 200)
        other, _ = self.make_project('Other', owner=self.owner)
        self.make_item(other, 'Service', 'Dom2', 'Item2')
        self.assertEqual(self.add_packet(domain='Dom2', name='Item2').status_code, 302)

    def test_edit_rename_to_existing_identifier_is_rejected_but_unchanged_name_is_fine(self):
        a = self.make_item(self.project, 'Packet', 'D', 'a', p_link=self.service, p_kind='TC')
        self.make_item(self.project, 'Packet', 'D', 'b', p_link=self.service, p_kind='TC')
        url = self.item_url('edit_spec_item', a)
        self.assertEqual(self.client.post(url, self.form_payload(url, title='x', value='v', t1='a', t2='b')).status_code, 302)
        response = self.client.post(url, self.form_payload(url, name='b'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].errors['name'], ["Error: Name 'b' already exists in domain 'D'"])
        self.assertEqual(self.refresh(a).name, 'a')

    def test_split_into_a_val_set_already_in_use_is_rejected(self):
        a = self.make_item(self.project, 'Packet', 'D', 'a', p_link=self.service, p_kind='TC', t1='a', t2='b', value='v', title='t')
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        url = self.item_url('split_spec_item', a)
        self.assertEqual(self.client.post(url, self.form_payload(url, val_set=alt.id)).status_code, 302)
        response = self.client.post(url, self.form_payload(url, val_set=alt.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].non_field_errors(), ['Split Error: ValSet is already in use for this domain:name'])
        self.assertEqual(SpecItem.objects.filter(cat='Packet', val_set=alt).count(), 1)

    def test_renaming_an_item_propagates_to_its_aliases_in_other_val_sets(self):
        a = self.make_item(self.project, 'Packet', 'D', 'a', p_link=self.service, p_kind='TC', t1='a', t2='b', value='v', title='t')
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        alias = self.make_item(self.project, 'Packet', 'D', 'a', p_link=a, val_set=alt, p_kind='TC')
        url = self.item_url('edit_spec_item', a)
        self.assertEqual(self.client.post(url, self.form_payload(url, name='renamed', domain='NewD')).status_code, 302)
        alias = self.refresh(alias)
        self.assertEqual((alias.domain, alias.name), ('NewD', 'renamed'))

    def test_deleting_an_item_removes_or_marks_its_aliases(self):
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        new_item = self.make_item(self.project, 'Packet', 'D', 'n', p_link=self.service, p_kind='TC')
        new_alias = self.make_item(self.project, 'Packet', 'D', 'n', p_link=new_item, val_set=alt)
        self.client.post(self.item_url('del_spec_item', new_item))
        self.assertFalse(SpecItem.objects.filter(id__in=[new_item.id, new_alias.id]).exists())
        cnf_item = self.make_item(self.project, 'Packet', 'D', 'c', p_link=self.service, p_kind='TC', status='CNF',
                                  t1='a', t2='b', value='v', title='t')
        cnf_alias = self.make_item(self.project, 'Packet', 'D', 'c', p_link=cnf_item, val_set=alt, status='CNF')
        url = self.item_url('del_spec_item', cnf_item)
        self.assertEqual(self.client.post(url, self.form_payload(url, change_log='gone')).status_code, 302)
        self.assertEqual(self.refresh(cnf_item).status, 'DEL')
        alias = self.refresh(cnf_alias)
        self.assertEqual((alias.status, alias.owner_id), ('DEL', self.rw_user.id))

    def test_only_new_mod_and_cnf_items_can_be_edited_split_or_deleted(self):
        for status in ('DEL', 'OBS'):
            item = self.make_item(self.project, 'Service', 'D', 'x_' + status, status=status)
            for view in ('edit_spec_item', 'split_spec_item', 'del_spec_item'):
                with self.subTest(status=status, view=view):
                    response = self.client.get(self.item_url(view, item))
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.url, '/editor')

    def test_copy_and_split_only_apply_to_the_default_val_set(self):
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        alias = self.make_item(self.project, 'Service', 'D', 'x', val_set=alt)
        for view in ('copy_spec_item', 'split_spec_item'):
            self.assertEqual(self.client.get(self.item_url(view, alias)).status_code, 302)


class AccessTests(EditorTestCase):
    """Who may read/write items (existing behavior; not to be extended by the configuration feature)."""

    def setUp(self):
        super().setUp()
        self.ro_user = self.make_user('ro_user')
        from editor.models import ProjectUser
        ProjectUser.objects.create(project=self.project, user=self.ro_user, role='RO')
        self.stranger = self.make_user('stranger')
        self.staff = self.make_user('staff', is_staff=True)
        self.service = self.make_item(self.project, 'Service', 'S', 'svc')

    def status_of(self, user, url, method='get', data=None):
        self.login(user)
        response = getattr(self.client, method)(url, data or {})
        return response.status_code

    def test_read_access_is_for_owner_and_project_users(self):
        url = self.list_url('Service')
        self.assertEqual([self.status_of(u, url) for u in (self.owner, self.rw_user, self.ro_user)], [200, 200, 200])
        for user in (self.stranger, self.staff):
            self.assertEqual(self.status_of(user, url), 302)

    def test_write_access_is_for_owner_and_rw_users(self):
        url = self.add_url('Service')
        self.assertEqual([self.status_of(u, url) for u in (self.owner, self.rw_user)], [200, 200])
        for user in (self.ro_user, self.stranger, self.staff):
            self.assertEqual(self.status_of(user, url), 302)
        payload = self.add_payload('Service', {})
        self.login(self.ro_user)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertFalse(SpecItem.objects.filter(cat='Service', name='Item1').exists())

    def test_anonymous_users_are_sent_to_login(self):
        self.client.logout()
        response = self.client.get(self.list_url('Service'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
