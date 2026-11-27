import pytest

from editor.configs import get_p_link_choices, get_s_link_choices
from editor.forms import identifier_error
from editor.models import ProjectUser, SpecItem, ValSet
from editor.project_config import get_project_config
from editor.utilities import get_p_kind_choices, get_s_kind_choices
from tests.project_config.base import (ALL_CATS, TEMPLATE, World, add_payload, make_application, make_item,
                                       make_project, make_user, refresh)

pytestmark = pytest.mark.django_db

# Rules editor/configs.py hardcoded before the project configuration (now the `links` settings of the template)
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
ENUM_ERROR = 'Data item value must be a reference to an enumerated value of the item type'


@pytest.fixture
def w(client):
    return World(client)


@pytest.fixture
def linked(w):
    """Items of every category in project Proj (incl. a deleted and an obsolete one) and in project Other."""
    w.other, _ = make_project('Other', cats=ALL_CATS)
    w.other_app = make_application(w.other, 'OtherApp')
    for cat in ALL_CATS:
        make_item(w.project, cat, 'D2', 'b_' + cat)
        make_item(w.project, cat, 'D1', 'z_' + cat)
        make_item(w.project, cat, 'D1', 'del_' + cat, status='DEL')
        make_item(w.project, cat, 'D1', 'obs_' + cat, status='OBS')
        make_item(w.other, cat, 'D1', 'other_' + cat)
    return w


@pytest.fixture
def typed(w):
    """EnumTypes color (value red) and shape (value square) and DataItemType int32."""
    w.enum = make_item(w.project, 'EnumType', 'E', 'color', n1=1)
    w.enum_other = make_item(w.project, 'EnumType', 'E', 'shape', n1=1)
    w.red = make_item(w.project, 'EnumValue', 'E', 'red', s_link=w.enum, value='1')
    w.square = make_item(w.project, 'EnumValue', 'E', 'square', s_link=w.enum_other, value='1')
    w.data_item_type = make_item(w.project, 'DataItemType', 'T', 'int32', n1=4)
    return w


@pytest.fixture
def service(w):
    return make_item(w.project, 'Service', 'S', 'svc')


@pytest.fixture
def members(w, service):
    """An RO user, a user without access, a staff user without access and Service svc."""
    w.ro_user = make_user('ro_user')
    ProjectUser.objects.create(project=w.project, user=w.ro_user, role='RO')
    w.stranger = make_user('stranger')
    w.staff = make_user('staff', is_staff=True)
    w.service = service
    return w


def names(queryset):
    return [(i.domain, i.name) for i in queryset]


def active_sorted(project, *cats):
    items = SpecItem.objects.filter(project=project, cat__in=cats, status__in=('NEW', 'CNF', 'MOD'))
    return sorted((i.domain, i.name) for i in items)


def post_data_item(w, p_link, value):
    payload = add_payload('DataItem', {'p_link': p_link}, value=value)
    return w.client.post(w.add_url('DataItem'), payload)


def add_packet(w, service, **overrides):
    payload = add_payload('Packet', {'p_link': service}, **overrides)
    return w.client.post(w.add_url('Packet'), payload)


def status_of(w, user, url, method='get', data=None):
    w.login(user)
    response = getattr(w.client, method)(url, data or {})
    return response.status_code


# ------------------------------------------------------------------ link choices

@pytest.mark.parametrize('cat', ALL_CATS)
def test_p_link_choices_per_category(linked, cat):
    result = get_p_link_choices(cat, linked.project, linked.application, None, None, get_project_config(linked.project))
    if cat in P_LINK_TARGETS:
        assert names(result) == active_sorted(linked.project, *P_LINK_TARGETS[cat])
    elif cat == 'AdaptPoint':
        assert names(result) == [('D1', 'z_Requirement'), ('D2', 'b_Requirement')]
        assert all(i.application_id == linked.application.id for i in result)
    else:
        assert list(result) == []


def test_p_link_choices_are_project_scoped_and_exclude_deleted_and_obsolete(linked):
    result = get_p_link_choices('Packet', linked.project, None, None, None, get_project_config(linked.project))
    assert names(result) == [('D1', 'z_Service'), ('D2', 'b_Service')]
    assert {i.project_id for i in result} == {linked.project.id}


def test_adapt_point_p_link_requires_an_application_and_is_application_scoped(linked):
    assert list(get_p_link_choices('AdaptPoint', linked.project, None, None, None,
                                   get_project_config(linked.project))) == []
    other_req = make_item(linked.other, 'Requirement', 'D1', 'o_req', application=linked.other_app)
    result = get_p_link_choices('AdaptPoint', linked.other, linked.other_app, None, None,
                                get_project_config(linked.other))
    assert {i.id for i in result} == {other_req.id, SpecItem.objects.get(name='other_Requirement').id}


@pytest.mark.parametrize('cat', ALL_CATS)
def test_s_link_choices_per_category(linked, cat):
    result = get_s_link_choices(cat, linked.project, linked.application, None, None, get_project_config(linked.project))
    if cat in S_LINK_TARGETS:
        assert names(result) == active_sorted(linked.project, *S_LINK_TARGETS[cat])
    elif cat == 'VerLink':
        other_cats = [c for c in ALL_CATS if c not in ('VerItem', 'VerLink')]
        expected = sorted(((i.cat, i.domain, i.name) for i in SpecItem.objects.filter(
            project=linked.project, cat__in=other_cats, status__in=('NEW', 'CNF', 'MOD'))))
        assert [(i.cat, i.domain, i.name) for i in result] == expected
    else:
        assert list(result) == []


@pytest.mark.parametrize('cat', ALL_CATS)
def test_parent_id_overrides_the_choices(linked, cat):
    target = SpecItem.objects.get(project=linked.project, name='b_Service')
    elsewhere = SpecItem.objects.get(project=linked.other, name='other_Service')
    config = get_project_config(linked.project)
    assert [i.id for i in get_p_link_choices(cat, linked.project, None, str(target.id), None, config)] == [target.id]
    # A parent of another project is never offered (parent ids are scoped to the project)
    assert list(get_s_link_choices(cat, linked.project, None, str(elsewhere.id), None, config)) == []
    assert list(get_p_link_choices(cat, linked.project, None, str(elsewhere.id), None, config)) == []


def test_der_packet_p_link_is_limited_to_enum_values_of_the_s_parent_enum_type(linked):
    enum1 = make_item(linked.project, 'EnumType', 'E', 'enum1')
    enum2 = make_item(linked.project, 'EnumType', 'E', 'enum2')
    packet = make_item(linked.project, 'Packet', 'P', 'pkt', s_link=enum1)
    val1 = make_item(linked.project, 'EnumValue', 'E', 'val1', s_link=enum1)
    make_item(linked.project, 'EnumValue', 'E', 'val2', s_link=enum2)
    result = get_p_link_choices('DerPacket', linked.project, None, None, str(packet.id),
                                get_project_config(linked.project))
    assert [i.id for i in result] == [val1.id]


def test_form_querysets_follow_the_choice_functions(linked):
    response = linked.client.get(linked.add_url('PacketPar'))
    form = response.context['form']
    assert names(form.fields['p_link'].queryset) == active_sorted(linked.project, 'Packet', 'DerPacket')
    assert names(form.fields['s_link'].queryset) == active_sorted(linked.project, 'DataItem')


def test_form_rejects_a_link_to_the_wrong_category(linked):
    parents = linked.parent_items('PacketPar')
    service = SpecItem.objects.get(project=linked.project, name='b_Service')
    payload = add_payload('PacketPar', parents, p_link=service.id)
    before = SpecItem.objects.count()
    response = linked.client.post(linked.add_url('PacketPar'), payload)
    assert response.status_code == 200
    assert 'p_link' in response.context['form'].errors
    assert SpecItem.objects.count() == before


def test_expansion_add_restricts_the_choices_to_the_parent(linked):
    enum = make_item(linked.project, 'EnumType', 'E', 'enum1')
    response = linked.client.get(linked.add_url('EnumValue', '?s_parent_id=%d' % enum.id))
    assert [i.id for i in response.context['form'].fields['s_link'].queryset] == [enum.id]


# ------------------------------------------------------------------ kind choices

@pytest.mark.parametrize('cat', ALL_CATS)
def test_kind_choices_come_from_the_category_definition(w, cat):
    assert get_p_kind_choices(TEMPLATE, cat) == list(TEMPLATE['cats'][cat]['p_kind_choices'].items())
    assert get_s_kind_choices(TEMPLATE, cat) == list(TEMPLATE['cats'][cat]['s_kind_choices'].items())
    form = w.client.get(w.add_url(cat)).context['form']
    assert list(form.fields['p_kind'].choices) == get_p_kind_choices(TEMPLATE, cat)
    assert list(form.fields['s_kind'].choices) == get_s_kind_choices(TEMPLATE, cat)


@pytest.mark.parametrize('cat,which,expected', [(cat, which, expected)
                                                 for (cat, which), expected in KIND_LITERALS.items()])
def test_literal_kind_choices(cat, which, expected):
    func = get_p_kind_choices if which == 'p' else get_s_kind_choices
    assert func(TEMPLATE, cat) == expected


def test_invalid_kind_is_rejected(w):
    parents = w.parent_items('Packet')
    payload = add_payload('Packet', parents, p_kind='XX')
    response = w.client.post(w.add_url('Packet'), payload)
    assert response.status_code == 200
    assert 'p_kind' in response.context['form'].errors
    assert not SpecItem.objects.filter(cat='Packet').exists()


def test_stored_kind_is_preselected_when_editing(w):
    service = make_item(w.project, 'Service', 'S', 'svc')
    packet = make_item(w.project, 'Packet', 'P', 'pkt', p_link=service, p_kind='TM', s_kind='INV')
    form = w.client.get(w.item_url('edit_spec_item', packet)).context['form']
    assert form['p_kind'].value() == 'TM'
    assert form['s_kind'].value() == 'INV'


def test_every_kind_choice_is_accepted_when_adding(w):
    parents = w.parent_items('Packet')
    for index, kind in enumerate(TEMPLATE['cats']['Packet']['p_kind_choices']):
        payload = add_payload('Packet', parents, p_kind=kind, name='Item%d' % index)
        assert w.client.post(w.add_url('Packet'), payload).status_code == 302
    assert sorted(SpecItem.objects.filter(cat='Packet').values_list('p_kind', flat=True)) == ['TC', 'TM']


# ------------------------------------------------------------------ do_cat_specific_checks, eval_ref rule of the form

def test_enum_typed_data_item_accepts_a_reference_to_an_enum_value_of_its_type(typed):
    response = post_data_item(typed, typed.enum, '#EnumValue:E:red')
    assert response.status_code == 302
    item = SpecItem.objects.get(cat='DataItem')
    assert item.value == '#iref:%d' % typed.red.id
    assert item.p_link_id == typed.enum.id


@pytest.mark.parametrize('value', ['5', '#EnumValue:E:red + 1', 'x #EnumValue:E:red', '#EnumValue:E:missing'])
def test_enum_typed_data_item_rejects_values_which_are_not_a_single_enum_reference(typed, value):
    response = post_data_item(typed, typed.enum, value)
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [ENUM_ERROR]
    assert not SpecItem.objects.filter(cat='DataItem').exists()


def test_data_item_value_is_required(typed):
    response = post_data_item(typed, typed.enum, '')
    assert response.status_code == 200
    assert 'value' in response.context['form'].errors


def test_enum_typed_data_item_rejects_a_value_of_another_enum_type(typed):
    response = post_data_item(typed, typed.enum, '#EnumValue:E:square')
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == [ENUM_ERROR]


def test_reference_to_a_non_enum_value_item_is_rejected(typed):
    response = post_data_item(typed, typed.enum, '#DataItemType:T:int32')
    assert response.status_code == 200
    assert response.context['form'].errors
    assert not SpecItem.objects.filter(cat='DataItem').exists()


def test_data_item_of_data_item_type_accepts_any_value(typed):
    response = post_data_item(typed, typed.data_item_type, '3.14 * 2')
    assert response.status_code == 302
    assert SpecItem.objects.get(cat='DataItem').value == '3.14 * 2'


def test_eval_ref_field_only_accepts_references_to_eval_ref_fields(typed):
    other = make_item(typed.project, 'DataItem', 'D', 'other', p_link=typed.data_item_type, value='2')
    ok = post_data_item(typed, typed.data_item_type, '#DataItem:D:other * 2')
    assert ok.status_code == 302
    assert SpecItem.objects.get(cat='DataItem', name='Item1').value == '#iref:%d * 2' % other.id
    for ref, text in (('#Packet:P:x', 'is not of kind eval_ref'), ('#OpContext:O:x', 'does not support field')):
        payload = add_payload('DataItem', {'p_link': typed.data_item_type}, value=ref, name='Item2')
        response = typed.client.post(typed.add_url('DataItem'), payload)
        assert response.status_code == 200, ref
        assert text in response.context['form'].non_field_errors()[0]
        assert 'The field "value" of kind eval_ref' in response.context['form'].non_field_errors()[0]


# ------------------------------------------------------------------ validation rules

@pytest.mark.parametrize('value,valid', [('bad name', False), ('a..b', False), ('.a', False), ('a.', False),
                                         ('a/b', False), ('é', False), ('a.b', True), ('a-b_c.d9', True)])
def test_domain_and_name_must_be_identifiers(w, service, value, valid):
    response = add_packet(w, service, name=value)
    if valid:
        assert response.status_code == 302
    else:
        assert response.status_code == 200
        assert response.context['form'].errors['name'] == [identifier_error]


def test_domain_name_pair_must_be_unique_among_active_items(w, service):
    assert add_packet(w, service).status_code == 302
    response = add_packet(w, service)
    assert response.status_code == 200
    assert response.context['form'].errors['name'] == ["Error: Name 'Item1' already exists in domain 'Dom1'"]
    assert SpecItem.objects.filter(cat='Packet').count() == 1
    SpecItem.objects.filter(cat='Packet').update(status='DEL')
    assert add_packet(w, service).status_code == 302         # deleted items do not block the identifier


def test_uniqueness_spans_categories_of_the_project_only(w, service):
    make_item(w.project, 'Service', 'Dom1', 'Item1')
    assert add_packet(w, service).status_code == 200
    other, _ = make_project('Other', owner=w.owner)
    make_item(other, 'Service', 'Dom2', 'Item2')
    assert add_packet(w, service, domain='Dom2', name='Item2').status_code == 302


def test_edit_rename_to_existing_identifier_is_rejected_but_unchanged_name_is_fine(w, service):
    a = make_item(w.project, 'Packet', 'D', 'a', p_link=service, p_kind='TC')
    make_item(w.project, 'Packet', 'D', 'b', p_link=service, p_kind='TC')
    url = w.item_url('edit_spec_item', a)
    assert w.client.post(url, w.form_payload(url, title='x', value='v', t1='a', t2='b')).status_code == 302
    response = w.client.post(url, w.form_payload(url, name='b'))
    assert response.status_code == 200
    assert response.context['form'].errors['name'] == ["Error: Name 'b' already exists in domain 'D'"]
    assert refresh(a).name == 'a'


def test_split_into_a_val_set_already_in_use_is_rejected(w, service):
    a = make_item(w.project, 'Packet', 'D', 'a', p_link=service, p_kind='TC', t1='a', t2='b', value='v', title='t')
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    url = w.item_url('split_spec_item', a)
    assert w.client.post(url, w.form_payload(url, val_set=alt.id)).status_code == 302
    response = w.client.post(url, w.form_payload(url, val_set=alt.id))
    assert response.status_code == 200
    assert response.context['form'].non_field_errors() == ['Split Error: ValSet is already in use for this domain:name']
    assert SpecItem.objects.filter(cat='Packet', val_set=alt).count() == 1


def test_renaming_an_item_propagates_to_its_aliases_in_other_val_sets(w, service):
    a = make_item(w.project, 'Packet', 'D', 'a', p_link=service, p_kind='TC', t1='a', t2='b', value='v', title='t')
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    alias = make_item(w.project, 'Packet', 'D', 'a', p_link=a, val_set=alt, p_kind='TC')
    url = w.item_url('edit_spec_item', a)
    assert w.client.post(url, w.form_payload(url, name='renamed', domain='NewD')).status_code == 302
    alias = refresh(alias)
    assert (alias.domain, alias.name) == ('NewD', 'renamed')


def test_deleting_an_item_removes_or_marks_its_aliases(w, service):
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    new_item = make_item(w.project, 'Packet', 'D', 'n', p_link=service, p_kind='TC')
    new_alias = make_item(w.project, 'Packet', 'D', 'n', p_link=new_item, val_set=alt)
    w.client.post(w.item_url('del_spec_item', new_item))
    assert not SpecItem.objects.filter(id__in=[new_item.id, new_alias.id]).exists()
    cnf_item = make_item(w.project, 'Packet', 'D', 'c', p_link=service, p_kind='TC', status='CNF',
                         t1='a', t2='b', value='v', title='t')
    cnf_alias = make_item(w.project, 'Packet', 'D', 'c', p_link=cnf_item, val_set=alt, status='CNF')
    url = w.item_url('del_spec_item', cnf_item)
    assert w.client.post(url, w.form_payload(url, change_log='gone')).status_code == 302
    assert refresh(cnf_item).status == 'DEL'
    alias = refresh(cnf_alias)
    assert (alias.status, alias.owner_id) == ('DEL', w.rw_user.id)


@pytest.mark.parametrize('view', ['edit_spec_item', 'split_spec_item', 'del_spec_item'])
@pytest.mark.parametrize('status', ['DEL', 'OBS'])
def test_only_new_mod_and_cnf_items_can_be_edited_split_or_deleted(w, status, view):
    item = make_item(w.project, 'Service', 'D', 'x_' + status, status=status)
    response = w.client.get(w.item_url(view, item))
    assert response.status_code == 302
    assert response.url == '/editor'


def test_copy_and_split_only_apply_to_the_default_val_set(w):
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    alias = make_item(w.project, 'Service', 'D', 'x', val_set=alt)
    for view in ('copy_spec_item', 'split_spec_item'):
        assert w.client.get(w.item_url(view, alias)).status_code == 302


# ------------------------------------------------------------------ access to items
# Existing behaviour, not to be extended by the configuration feature.

def test_read_access_is_for_owner_and_project_users(members):
    url = members.list_url('Service')
    assert [status_of(members, u, url) for u in (members.owner, members.rw_user, members.ro_user)] == [200, 200, 200]
    for user in (members.stranger, members.staff):
        assert status_of(members, user, url) == 302


def test_write_access_is_for_owner_and_rw_users(members):
    url = members.add_url('Service')
    assert [status_of(members, u, url) for u in (members.owner, members.rw_user)] == [200, 200]
    for user in (members.ro_user, members.stranger, members.staff):
        assert status_of(members, user, url) == 302
    payload = add_payload('Service', {})
    members.login(members.ro_user)
    assert members.client.post(url, payload).status_code == 302
    assert not SpecItem.objects.filter(cat='Service', name='Item1').exists()


def test_anonymous_users_are_sent_to_login(members):
    members.client.logout()
    response = members.client.get(members.list_url('Service'))
    assert response.status_code == 302
    assert 'login' in response.url
