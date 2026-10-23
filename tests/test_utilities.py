"""Characterization tests for editor/utilities.py and the link-choice helpers of editor/configs.py."""
import os

import pytest
from django.contrib.messages import get_messages
from django.contrib.messages.storage.cookie import CookieStorage
from django.contrib.auth.models import User
from django.test import RequestFactory

from editor.configs import configs, get_p_link_choices, get_s_link_choices
from editor.models import SpecItem, ValSet, Project
from editor.utilities import (spec_item_to_edit, spec_item_to_latex, spec_item_to_export,
                              export_to_spec_item, get_user_choices, get_redirect_url,
                              make_temp_dir, get_default_val_set_id, create_and_init_spec_item,
                              get_p_kind_choices, get_s_kind_choices, get_csv_line, snake_to_camel,
                              get_previous_list)
from tests.factories import (make_user, make_project, make_spec_item, make_val_set, make_release,
                             make_application, default_val_set, FIXED_TIME)

pytestmark = pytest.mark.django_db

CATS = 'DataItem,EnumType,EnumValue,DataItemType'


@pytest.fixture
def world():
    owner = make_user()
    project = make_project(owner, cats=CATS)
    etype = make_spec_item(project, 'EnumType', 'D', 'T1', status='CNF', title='t', desc='d')
    item = make_spec_item(project, 'DataItem', 'D', 'x', status='NEW', p_link=etype,
                          value='#iref:%d*2' % etype.id, desc='x_y #iref:%d\nl2' % etype.id)
    return dict(owner=owner, project=project, etype=etype, item=item)


def _request():
    request = RequestFactory().get('/')
    request._messages = CookieStorage(request)
    return request


# ------------------------------------------------------------------ small helpers
def test_snake_to_camel():
    assert snake_to_camel('abc_def') == 'AbcDef'
    assert snake_to_camel('a__b') == 'A_B'
    assert snake_to_camel('') == '_'      # empty string yields '_'


def test_get_csv_line():
    assert get_csv_line([]) == '\n'
    assert get_csv_line(['a', None, 'b%']) == 'a||b\\%\n'
    assert get_csv_line(['only']) == 'only\n'


def test_get_previous_list(world):
    a = world['item']
    b = make_spec_item(world['project'], 'DataItem', 'D', 'prev', p_link=world['etype'])
    a.previous = b
    a.save()
    assert get_previous_list(a) == [a, b]
    assert get_previous_list(b) == [b]


# ---------------------------------------------------------------- spec_item_to_edit
def test_spec_item_to_edit(world):
    d = spec_item_to_edit(world['item'])
    assert d['desc'] == 'x_y #EnumType:D:T1\nl2'
    assert d['value'] == '#EnumType:D:T1*2'
    assert d['domain'] == 'D' and d['name'] == 'x'
    assert d['p_link'] == world['etype'].id
    assert d['val_set'] == world['item'].val_set_id
    assert d['owner'] == world['owner'].id
    assert d['s_data'] == {}
    assert list(d.keys()) == [
        'id', 'cat', 'name', 'domain', 'project', 'application', 'title', 'desc', 'owner', 'status',
        'updated_at', 'created_at', 'previous', 'rationale', 'remarks', 'implementation', 'val_set',
        'p_link', 's_link', 'p_kind', 's_kind', 'value', 's_data', 't1', 't2', 't3', 't4', 't5',
        'n1', 'n2', 'n3', 'change_log']


def test_spec_item_to_edit_dangling_reference(world):
    world['item'].desc = 'see #iref:9999'
    assert spec_item_to_edit(world['item'])['desc'] == 'see ERROR:9999'


# ---------------------------------------------------------------- spec_item_to_latex
def test_spec_item_to_latex_datait(world):
    d = spec_item_to_latex(world['item'])
    assert d == {
        'Domain': 'D', 'Name': 'x', 'Title': 'Title of x',
        'Description': 'x\\_y D:T1 \\newline l2',
        'Value': 'D:T1*2',
        # NVal is computed from the raw db value; the referenced item has an empty value -> '*2' invalid
        'NVal': '#iref:%d*2' % world['etype'].id,
        'Rationale': '', 'Remarks': '', 'Implementation': '',
        'Type': 'D:T1', 'Kind': '', 'Multiplicity': '', 'Unit': '',
        'Owner': 'alice', 'ChangeLog': '', 'ValSet': 'Default',
        'UpdatedAt': '15-01-2024 10:30', 'CreatedAt': '15-01-2024 10:30',
        'Status': 'NEW', 'Project': 'Proj', 'Application': 'None'}


def test_spec_item_to_latex_key_order(world):
    assert list(spec_item_to_latex(world['item']).keys()) == [
        'Domain', 'Name', 'Title', 'Description', 'Value', 'NVal', 'Rationale', 'Remarks',
        'Implementation', 'Type', 'Kind', 'Multiplicity', 'Unit', 'Owner', 'ChangeLog', 'ValSet',
        'UpdatedAt', 'CreatedAt', 'Status', 'Project', 'Application']
    # 'Owner' is set by the attrs loop and overwritten in place (position kept)


def test_spec_item_to_latex_nval_evaluated(world):
    world['item'].value = '2*(3+4)'
    d = spec_item_to_latex(world['item'])
    assert d['Value'] == '2*(3+4)'
    assert d['NVal'] == '14.0'


def test_spec_item_to_latex_int_and_spec_item_ref(world):
    d = spec_item_to_latex(world['etype'])
    assert d['Size'] == '0'                      # int field -> frmt_string(str(n1))
    d2 = spec_item_to_latex(world['item'])
    assert d2['Type'] == 'D:T1'                 # 'spec_item_ref': str(item).split(' ')[0]


def test_spec_item_to_latex_application_and_escaping(world):
    app = make_application(world['project'], name='My_App', cats='Requirement')
    req = make_spec_item(world['project'], 'Requirement', 'R', 'r', application=app, value='v',
                         title='5% & #1')
    d = spec_item_to_latex(req)
    assert d['Application'] == 'My\\_App'
    assert d['Title'] == '5\\% \\& \\#1'
    assert d['Project'] == 'Proj'


def test_spec_item_to_latex_image_kind():
    # no category in configs.json uses a populated 'image' attribute here; check that the kind exists
    kinds = {a['kind'] for c in configs['cats'].values() for a in c['attrs'].values()}
    assert 'image' in kinds


def test_spec_item_to_latex_date_format(world):
    from datetime import datetime, timezone
    world['item'].updated_at = datetime(2023, 12, 31, 23, 59, tzinfo=timezone.utc)
    world['item'].created_at = datetime(2020, 2, 3, 4, 5, tzinfo=timezone.utc)
    d = spec_item_to_latex(world['item'])
    assert d['UpdatedAt'] == '31-12-2023 23:59'
    assert d['CreatedAt'] == '03-02-2020 04:05'


# --------------------------------------------------------- export / import round trip
def test_spec_item_to_export(world):
    assert spec_item_to_export(world['item']) == {
        'Domain': 'D', 'Name': 'x', 'Title': 'Title of x',
        'Description': 'x_y #EnumType:D:T1\nl2', 'Value': '#iref:%d*2' % world['etype'].id,
        'Rationale': '', 'Remarks': '', 'Implementation': '', 'Type': 'D:T1', 'Kind': '',
        'Multiplicity': '', 'Unit': '', 'Owner': 'alice', 'Change Log': '', 'ValSet': 'Default'}
    # KNOWN-ISSUE: export-eval-ref-raw  (eval_ref 'Value' is exported in db form '#iref:N', not edit form)


def test_spec_item_to_export_empty_spec_item_ref_is_None_string(world):
    assert spec_item_to_export(world['etype'])['Size'] == '0'
    root = make_spec_item(world['project'], 'DataItem', 'D', 'nolink')
    # KNOWN-ISSUE: export-none-string  (empty link is exported as the string 'None')
    assert spec_item_to_export(root)['Type'] == 'None'


def test_export_to_spec_item_round_trip(world):
    exported = spec_item_to_export(world['item'])
    new = SpecItem(cat='DataItem')
    export_to_spec_item(None, world['project'], exported, new)
    assert new.domain == 'D' and new.name == 'x' and new.title == 'Title of x'
    assert new.p_link == world['etype']
    assert new.val_set == default_val_set(world['project'])
    # 'Value' is an eval_ref (not ref_text) so it is copied verbatim
    assert new.value == '#iref:%d*2' % world['etype'].id
    # ref_text with edit refs converted back to db refs
    assert new.desc == 'x_y #iref:%d\nl2' % world['etype'].id
    # owner is not copied
    assert new.owner_id is None


def test_export_to_spec_item_unknown_link_is_none(world):
    exported = spec_item_to_export(world['item'])
    exported['Type'] = 'Zz:nope'
    new = SpecItem(cat='DataItem')
    export_to_spec_item(None, world['project'], exported, new)
    assert new.p_link is None


def test_export_to_spec_item_missing_column_raises(world):
    exported = spec_item_to_export(world['item'])
    del exported['Title']
    with pytest.raises(KeyError):
        export_to_spec_item(None, world['project'], exported, SpecItem(cat='DataItem'))


def test_export_to_spec_item_unknown_valset_raises(world):
    exported = spec_item_to_export(world['item'])
    exported['ValSet'] = 'Nope'
    with pytest.raises(ValSet.DoesNotExist):
        export_to_spec_item(None, world['project'], exported, SpecItem(cat='DataItem'))


def test_export_to_spec_item_int_not_converted(world):
    exported = spec_item_to_export(world['etype'])
    exported['Size'] = '7'
    new = SpecItem(cat='EnumType')
    export_to_spec_item(None, world['project'], exported, new)
    assert new.n1 == '7'          # string, no int conversion


def test_export_unicode_round_trip(world):
    world['item'].title = 'café € <b>&</b>'
    exported = spec_item_to_export(world['item'])
    new = SpecItem(cat='DataItem')
    export_to_spec_item(None, world['project'], exported, new)
    assert new.title == 'café € <b>&</b>'


# ------------------------------------------------------------------- user choices
def test_get_user_choices_owner_first(world):
    make_user('zed')
    make_user('bob')
    u = User.objects.get(username='bob')
    u.first_name, u.last_name = 'Bob', 'Builder'
    u.save()
    ids = {x.username: x.id for x in User.objects.all()}
    # owner 'alice' (no names) first, then the others ordered by username
    # KNOWN-ISSUE: owner-empty-names  (owner entry always shows ' ( )' parentheses; others do not)
    assert get_user_choices(world['project']) == [
        (ids['alice'], 'alice ( )'), (ids['bob'], 'bob (Bob Builder)'), (ids['zed'], 'zed')]


def test_get_user_choices_no_project():
    make_user('zed')
    make_user('alice')
    ids = {x.username: x.id for x in User.objects.all()}
    assert get_user_choices(None) == [(ids['alice'], 'alice'), (ids['zed'], 'zed')]


def test_get_user_choices_owner_with_names():
    owner = make_user('carol')
    owner.first_name, owner.last_name = 'Carol', 'C'
    owner.save()
    project = make_project(owner)
    assert get_user_choices(project) == [(owner.id, 'carol (Carol C)')]


def test_get_user_choices_only_first_name():
    u = make_user('dave')
    u.first_name = 'Dave'
    u.save()
    assert get_user_choices(None) == [(u.id, 'dave (Dave )')]


# ------------------------------------------------------------------ kind choices
def test_kind_choices():
    assert get_p_kind_choices('DataItem') == [('CNS', 'Constant'), ('PAR', 'Configuration Parameter'),
                                              ('VAR', 'Global Variable'), ('CTX', 'Context Variable'),
                                              ('PCK', 'Packet Parameter')]
    assert get_s_kind_choices('Packet') == [('INV', 'Invalid')]
    with pytest.raises(KeyError):
        get_p_kind_choices('Nope')


# ----------------------------------------------------------------- get_redirect_url
def test_get_redirect_url_plain(world):
    it = world['item']
    assert get_redirect_url('DataItem', 1, 0, 1, 'Sel_All', 0, None, None, it) == \
        '/editor/DataItem/1/0/1/Sel_All/0/list_spec_items#D:x'
    assert get_redirect_url('DataItem', 1, 0, 1, 'Sel_All', 0, None, None, None) == \
        '/editor/DataItem/1/0/1/Sel_All/0/list_spec_items'


def test_get_redirect_url_s_parent(world):
    e = world['etype']
    assert get_redirect_url('DataItem', 1, 0, 1, 'Sel_All', 3, str(e.id), None, world['item']) == \
        '/editor/EnumType/1/0/1/Sel_All/3/list_spec_items?expand_id=%d&expand_link=s_link#D:T1' % e.id


def test_get_redirect_url_p_parent(world):
    e = world['etype']
    assert get_redirect_url('DataItem', 1, 0, 1, 'Sel_All', 0, None, str(e.id), None) == \
        '/editor/EnumType/1/0/1/Sel_All/0/list_spec_items?expand_id=%d&expand_link=p_link#D:T1' % e.id


def test_get_redirect_url_s_parent_wins_over_p_parent(world):
    it, e = world['item'], world['etype']
    url = get_redirect_url('DataItem', 1, 0, 1, 'Sel_All', 0, str(e.id), str(it.id), None)
    assert url.endswith('expand_link=s_link#D:T1')


def test_get_redirect_url_int_parent_id_crashes(world):
    # KNOWN-ISSUE: redirect-int-parent  (parent id must be str: concatenation with int raises)
    with pytest.raises(TypeError):
        get_redirect_url('DataItem', 1, 0, 1, 'Sel_All', 0, world['etype'].id, None, None)


# ----------------------------------------------------------------- make_temp_dir
def test_make_temp_dir_success(tmp_path):
    out = make_temp_dir(str(tmp_path), 'exp_')
    assert os.path.isdir(out)
    assert os.path.dirname(out) == str(tmp_path)
    base = os.path.basename(out)
    assert base.startswith('exp_')
    stamp = base[len('exp_'):]
    assert len(stamp) == len('2024_01_15_10_30_00')
    assert stamp.replace('_', '').isdigit()


def test_make_temp_dir_failure_nameerror(tmp_path):
    # KNOWN-ISSUE: make-temp-dir-nameerror  (error path references undefined 'request' and 'exp_dir')
    with pytest.raises(NameError):
        make_temp_dir(str(tmp_path / 'does-not-exist'), 'exp_')


def test_make_temp_dir_already_exists_nameerror(tmp_path, monkeypatch):
    # same failure path through FileExistsError (OSError subclass)
    import editor.utilities as u
    from datetime import datetime as real_dt

    class FixedDT:
        @staticmethod
        def now(tz=None):
            return real_dt(2024, 1, 15, 10, 30, 0)

    monkeypatch.setattr(u, 'datetime', FixedDT)
    first = make_temp_dir(str(tmp_path), 'd_')
    assert os.path.basename(first) == 'd_2024_01_15_10_30_00'
    with pytest.raises(NameError):
        make_temp_dir(str(tmp_path), 'd_')


# ---------------------------------------------------------- get_default_val_set_id
def test_get_default_val_set_id(world):
    assert get_default_val_set_id(None, world['project']) == default_val_set(world['project']).id


def test_get_default_val_set_id_with_other_valsets(world):
    make_val_set(world['project'], 'VS1')
    assert get_default_val_set_id(None, world['project']) == default_val_set(world['project']).id


def test_get_default_val_set_id_missing_returns_zero_and_message(world):
    p2 = Project.objects.create(name='NoVS', desc='', cats='', owner=world['owner'],
                                release=world['project'].release)
    request = _request()
    assert get_default_val_set_id(request, p2) == 0
    msgs = [str(m) for m in get_messages(request)]
    assert len(msgs) == 1
    assert msgs[0].startswith('Failure to retrieve the ValSet for project NoVS. This probably meanns '
                              'that the data for the projects are corrupted. Error message was: ')


# ---------------------------------------------------- create_and_init_spec_item
def test_create_and_init_spec_item():
    item = create_and_init_spec_item(None, 'DataItem', {
        'domain': 'D', 'name': 'n', 'title': 'T', 'value': '1', 'n1': 5, 'unknown': 'zzz',
        'status': 'CNF', 'p_kind': 'CNS'})
    assert isinstance(item, SpecItem) and item.pk is None
    assert (item.domain, item.name, item.title, item.value, item.p_kind) == ('D', 'n', 'T', '1', 'CNS')
    # attributes not in the category config are not copied (DataItem has no n1 nor status)
    assert item.n1 == 0
    assert item.status == 'NEW'
    assert not hasattr(item, 'unknown')
    # 'cat' is not initialised either
    assert item.cat == ''


def test_create_and_init_spec_item_unknown_cat():
    with pytest.raises(KeyError):
        create_and_init_spec_item(None, 'Nope', {})


# ------------------------------------------------------ configs link choices
def _pairs(qs):
    return [(i.cat, i.domain, i.name) for i in qs]


def test_p_link_choices_parent_id(world):
    qs = get_p_link_choices('DataItem', world['project'], None, str(world['etype'].id), None)
    assert list(qs) == [world['etype']]


def test_p_link_choices_dataitem_types_sorted(world):
    p = world['project']
    make_spec_item(p, 'DataItemType', 'B', 'dt', status='CNF')
    make_spec_item(p, 'DataItemType', 'A', 'dt2', status='DEL')
    make_spec_item(p, 'EnumType', 'A', 'et', status='CNF')
    make_spec_item(p, 'EnumType', 'A', 'obs', status='OBS')
    qs = get_p_link_choices('DataItem', p, None, None, None)
    # q1 | q2 combine: the combined queryset is ordered by (domain, name)
    assert _pairs(qs) == [('EnumType', 'A', 'et'), ('DataItemType', 'B', 'dt'), ('EnumType', 'D', 'T1')]


def test_p_link_choices_no_link_cats(world):
    assert list(get_p_link_choices('EnumType', world['project'], None, None, None)) == []
    assert list(get_p_link_choices('AdaptPoint', world['project'], None, None, None)) == []


def test_p_link_choices_adaptpoint_with_application(world):
    p = world['project']
    app = make_application(p, cats='Requirement,AdaptPoint')
    other = make_application(p, name='Other', cats='Requirement')
    r1 = make_spec_item(p, 'Requirement', 'R', 'b', application=app, status='CNF')
    r2 = make_spec_item(p, 'Requirement', 'R', 'a', application=app, status='CNF')
    make_spec_item(p, 'Requirement', 'R', 'c', application=other, status='CNF')
    make_spec_item(p, 'Requirement', 'R', 'd', application=app, status='DEL')
    assert list(get_p_link_choices('AdaptPoint', p, app, None, None)) == [r2, r1]


def test_p_link_choices_packet_cats(world):
    p = world['project']
    svc = make_spec_item(p, 'Service', 'S', 's', status='CNF')
    pkt = make_spec_item(p, 'Packet', 'P', 'p', status='CNF')
    dpk = make_spec_item(p, 'DerPacket', 'P', 'a', status='CNF')
    assert list(get_p_link_choices('Packet', p, None, None, None)) == [svc]
    assert list(get_p_link_choices('InCommand', p, None, None, None)) == [dpk, pkt]
    assert list(get_p_link_choices('PacketPar', p, None, None, None)) == [dpk, pkt]


def test_p_link_choices_derpacket(world):
    p = world['project']
    et1 = make_spec_item(p, 'EnumType', 'E', 'e1', status='CNF')
    et2 = make_spec_item(p, 'EnumType', 'E', 'e2', status='CNF')
    ev1 = make_spec_item(p, 'EnumValue', 'E', 'v1', status='CNF', s_link=et1)
    ev2 = make_spec_item(p, 'EnumValue', 'E', 'v2', status='CNF', s_link=et2)
    pkt = make_spec_item(p, 'Packet', 'P', 'p', status='CNF', s_link=et1)
    assert list(get_p_link_choices('DerPacket', p, None, None, None)) == [ev1, ev2]
    # with s_parent_id: only enum values of the same enum type as the parent's s_link
    assert list(get_p_link_choices('DerPacket', p, None, None, pkt.id)) == [ev1]


def test_s_link_choices(world):
    p = world['project']
    ev_type = make_spec_item(p, 'EnumType', 'A', 'first', status='CNF')
    make_spec_item(p, 'EnumType', 'Z', 'gone', status='DEL')
    assert list(get_s_link_choices('EnumValue', p, None, None, None)) == [ev_type, world['etype']]
    assert list(get_s_link_choices('DataItem', p, None, None, None)) == []
    assert list(get_s_link_choices('EnumValue', p, None, str(world['etype'].id), None)) == [world['etype']]


def test_s_link_choices_other_cats(world):
    p = world['project']
    di = world['item']
    pkt = make_spec_item(p, 'Packet', 'P', 'p', status='CNF')
    vi = make_spec_item(p, 'VerItem', 'V', 'vi', status='CNF')
    assert list(get_s_link_choices('PacketPar', p, None, None, None)) == [di]
    assert list(get_s_link_choices('DerPacket', p, None, None, None)) == [pkt]
    assert list(get_s_link_choices('Packet', p, None, None, None)) == [world['etype']]
    assert list(get_s_link_choices('VerStep', p, None, None, None)) == [vi]
    # VerLink: everything except VerItem and VerLink, ordered by cat, domain, name
    assert _pairs(get_s_link_choices('VerLink', p, None, None, None)) == [
        ('DataItem', 'D', 'x'), ('EnumType', 'D', 'T1'), ('Packet', 'P', 'p')]
