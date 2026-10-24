"""
Task 6.4: every object id taken from the URL, GET or POST is looked up inside the project whose
access was checked. A foreign id gives 404 (or a form error for a form field) and changes nothing;
legitimate ids behave as before. Complements the flipped pins in test_security_audit.py,
test_access.py and test_views.py.
"""
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client

from editor.configs import get_p_link_choices, get_s_link_choices
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.utilities import get_domains, get_redirect_url, get_spec_item_query
from tests.backend import is_mysql
from tests.factories import (default_val_set, make_application, make_project, make_project_user,
                             make_release, make_spec_item, make_user, make_val_set)

pytestmark = pytest.mark.django_db
CATS = 'DataItem,EnumType,EnumValue,DataItemType,Requirement,Model,InfoItem'


def snapshot():
    return [list(m.objects.order_by('id').values())
            for m in (SpecItem, ValSet, Application, ProjectUser, Release, Project, User)]


def msgs(resp):
    return [m.message for m in get_messages(resp.wsgi_request)]


class W:
    def __init__(self):
        self.owner_a = make_user('owner_a')
        self.owner_b = make_user('owner_b')
        self.rw = make_user('rw')
        self.staff = make_user('staff', is_staff=True)
        self.a = make_project(self.owner_a, 'ProjA', cats=CATS)
        self.b = make_project(self.owner_b, 'ProjB', cats=CATS)
        make_project_user(self.a, self.rw, 'RW')
        self.dvs_a = default_val_set(self.a)
        self.dvs_b = default_val_set(self.b)
        self.app_a = make_application(self.a, 'AppA', cats='Requirement,Model')
        self.app_b = make_application(self.b, 'AppB', cats='Requirement,Model')
        self.a_type = make_spec_item(self.a, cat='DataItemType', domain='AT', name='AInt', n1=4, status='CNF')
        self.a_item = make_spec_item(self.a, cat='DataItem', domain='AD', name='AItem', title='A item', value='1',
                                     p_link=self.a_type, p_kind='CNS', s_kind='INV', status='NEW')
        self.b_type = make_spec_item(self.b, cat='DataItemType', domain='BT', name='BInt', title='B secret', n1=4,
                                     status='CNF')
        self.b_enum = make_spec_item(self.b, cat='EnumType', domain='BE', name='BEnum', title='B enum', n1=1,
                                     status='NEW')
        self.a_enum = make_spec_item(self.a, cat='EnumType', domain='AE', name='AEnum', title='A enum', n1=1,
                                     status='NEW')

    def client(self, user):
        c = Client()
        c.force_login(user)
        return c


@pytest.fixture
def w():
    return W()


def iurl(view, cat, project_id, item_id, app_id=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/%s' % (cat, project_id, app_id, item_id, sel_val, rel, view)


def aurl(cat, project_id, app_id=0):
    return '/editor/%s/%d/%d/Sel_All/0/add_spec_item' % (cat, project_id, app_id)


EV = {'domain': 'AE', 'name': 'v1', 'title': 't', 'desc': '', 'value': '1', 'rationale': '', 'remarks': '',
      'implementation': '', 'change_log': ''}
REQ = {'domain': 'AR', 'name': 'r1', 'title': 't', 'value': 'v', 'rationale': '', 'remarks': '',
       'implementation': '', 't1': '', 't2': '', 'p_kind': 'STD', 's_kind': 'TST', 'change_log': ''}


# ---- parent ids (idor-parent-link-cross-project) ----------------------------------------------

@pytest.mark.parametrize('view', ['add_spec_item', 'edit_spec_item', 'copy_spec_item', 'del_spec_item', 'split_spec_item'])
@pytest.mark.parametrize('param', ['s_parent_id', 'p_parent_id'])
def test_foreign_parent_id_is_404(w, view, param):
    c = w.client(w.rw)
    before = snapshot()
    if view == 'add_spec_item':
        url = aurl('EnumValue', w.a.id)
    else:
        url = iurl(view, 'EnumType', w.a.id, w.a_enum.id)
    url += '?%s=%d' % (param, w.b_enum.id)
    assert c.get(url).status_code == 404
    assert c.post(url, dict(EV, s_link=w.b_enum.id)).status_code == 404
    assert snapshot() == before


@pytest.mark.parametrize('view', ['add_spec_item', 'edit_spec_item'])
def test_non_integer_parent_id_is_404(w, view):
    c = w.client(w.rw)
    url = aurl('EnumValue', w.a.id) if view == 'add_spec_item' else iurl(view, 'EnumType', w.a.id, w.a_enum.id)
    assert c.get(url + '?s_parent_id=abc').status_code == 404


def test_own_parent_id_still_works(w):
    c = w.client(w.rw)
    url = aurl('EnumValue', w.a.id) + '?s_parent_id=%d' % w.a_enum.id
    get = c.get(url)
    assert get.status_code == 200
    assert 'AE:AEnum (A enum)' in get.context['sub_title']
    assert list(get.context['form'].fields['s_link'].queryset) == [w.a_enum]
    resp = c.post(url, dict(EV, s_link=w.a_enum.id))
    assert resp.status_code == 302
    assert resp.url.startswith('/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d'
                               % (w.a.id, w.dvs_a.id, w.a_enum.id))
    assert SpecItem.objects.get(project=w.a, name='v1').s_link == w.a_enum


def test_choice_builders_scoped_by_project(w):
    # defence in depth: a foreign parent id yields an empty choice list / no redirect target
    assert list(get_p_link_choices('DataItem', w.a, None, str(w.b_type.id), None)) == []
    assert list(get_s_link_choices('EnumValue', w.a, None, str(w.b_enum.id), None)) == []
    assert list(get_p_link_choices('DataItem', w.a, None, str(w.a_type.id), None)) == [w.a_type]
    assert list(get_s_link_choices('EnumValue', w.a, None, str(w.a_enum.id), None)) == [w.a_enum]
    assert list(get_s_link_choices('EnumValue', w.a, None, None, None)) == [w.a_enum]
    with pytest.raises(SpecItem.DoesNotExist):
        get_redirect_url('EnumType', w.a.id, 0, w.dvs_a.id, 'Sel_All', 0, str(w.b_enum.id), None, None)
    with pytest.raises(SpecItem.DoesNotExist):
        get_redirect_url('EnumType', w.a.id, 0, w.dvs_a.id, 'Sel_All', 0, None, str(w.b_enum.id), None)
    assert get_redirect_url('EnumType', w.a.id, 0, w.dvs_a.id, 'Sel_All', 0, str(w.a_enum.id), None, None) == \
        '/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d&expand_link=s_link#AE:AEnum' % (
            w.a.id, w.dvs_a.id, w.a_enum.id)


def test_adapt_point_choices_scoped_by_project(w):
    req_a = make_spec_item(w.a, cat='Requirement', domain='R', name='ra', application=w.app_a)
    make_spec_item(w.b, cat='Requirement', domain='R', name='rb', application=w.app_b)
    assert list(get_p_link_choices('AdaptPoint', w.a, w.app_a, None, None)) == [req_a]
    assert list(get_p_link_choices('AdaptPoint', w.a, w.app_b, None, None)) == []


# ---- foreign item ids (idor-item-project) ------------------------------------------------------

@pytest.mark.parametrize('view', ['edit_spec_item', 'copy_spec_item', 'split_spec_item', 'del_spec_item',
                                  'refresh_spec_item'])
def test_foreign_item_is_404_and_changes_nothing(w, view):
    c = w.client(w.rw)
    before = snapshot()
    url = iurl(view, 'DataItemType', w.a.id, w.b_type.id)
    if view != 'refresh_spec_item':
        assert c.get(url).status_code == 404
    assert c.post(url, {'title': 'x', 'change_log': 'x', 'n1': '4'}).status_code == 404
    assert snapshot() == before


def test_history_foreign_item_and_application(w):
    c = w.client(w.rw)
    assert c.get('/editor/DataItemType/%d/0/%d/Sel_All/list_spec_item_history' % (w.a.id, w.b_type.id)).status_code == 404
    assert c.get('/editor/DataItem/%d/%d/%d/Sel_All/list_spec_item_history' % (w.a.id, w.app_b.id, w.a_item.id)).status_code == 404
    ok = c.get('/editor/DataItem/%d/0/%d/Sel_All/list_spec_item_history' % (w.a.id, w.a_item.id))
    assert ok.status_code == 200 and ok.context['page_items'] == [w.a_item]


def test_nonexistent_item_is_404(w):
    c = w.client(w.rw)
    assert c.get(iurl('edit_spec_item', 'DataItem', w.a.id, 99999)).status_code == 404


def test_own_item_edit_unchanged(w):
    c = w.client(w.rw)
    assert c.get(iurl('edit_spec_item', 'DataItem', w.a.id, w.a_item.id)).status_code == 200
    resp = c.post(iurl('edit_spec_item', 'DataItem', w.a.id, w.a_item.id),
                  {'domain': 'AD', 'name': 'AItem', 'title': 'new title', 'desc': 'x', 'value': '1', 'rationale': '',
                   'remarks': '', 'implementation': '', 'p_kind': 'CNS', 't1': '', 't2': '', 'change_log': 'c',
                   'n1': '0', 'n2': '0', 'n3': '0', 's_kind': 'INV', 's_data': '{}', 'p_link': w.a_type.id})
    assert resp.status_code == 302
    w.a_item.refresh_from_db()
    assert (w.a_item.title, w.a_item.owner) == ('new title', w.rw)


def test_own_item_edit_foreign_p_link_is_form_error(w):
    c = w.client(w.rw)
    before = snapshot()
    resp = c.post(iurl('edit_spec_item', 'DataItem', w.a.id, w.a_item.id),
                  {'domain': 'AD', 'name': 'AItem', 'title': 'new title', 'desc': 'x', 'value': '1', 'rationale': '',
                   'remarks': '', 'implementation': '', 'p_kind': 'CNS', 't1': '', 't2': '', 'change_log': 'c',
                   'n1': '0', 'n2': '0', 'n3': '0', 's_kind': 'INV', 's_data': '{}', 'p_link': w.b_type.id})
    assert resp.status_code == 200
    assert 'Select a valid choice' in str(resp.context['form'].errors['p_link'])
    assert snapshot() == before


def test_split_foreign_val_set_is_form_error(w):
    c = w.client(w.rw)
    before = snapshot()
    resp = c.post(iurl('split_spec_item', 'DataItem', w.a.id, w.a_item.id),
                  {'domain': 'AD', 'name': 'AItem', 'title': 't', 'desc': 'x', 'value': '2', 'rationale': '',
                   'remarks': '', 'implementation': '', 'p_kind': 'CNS', 't1': '', 't2': '', 'change_log': 'c',
                   'n1': '0', 'n2': '0', 'n3': '0', 's_kind': 'INV', 's_data': '{}', 'p_link': w.a_type.id,
                   'val_set': w.dvs_b.id})
    assert resp.status_code == 200
    assert 'Select a valid choice' in str(resp.context['form'].errors['val_set'])
    assert snapshot() == before


def test_find_replace_read_only_member_foreign_ids_refused_by_write_check(w):
    ro = make_user('ro')
    make_project_user(w.a, ro, 'RO')
    c = w.client(ro)
    before = snapshot()
    url = '/editor/Requirement/%d/%d/%d/Sel_All/0/list_spec_items' % (w.a.id, w.app_b.id, w.dvs_b.id)
    data = {'field': 'title', 'find': 'secret', 'replace': 'PWNED'}
    # XHR: 403 JSON with the write-access error (the write check comes before any id lookup)
    resp = c.post(url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert resp.status_code == 403
    assert list(resp.json()['errors']) == ['__all__']
    # no XHR: redirect with the access message
    resp = c.post(url, data)
    assert resp.status_code == 302
    assert msgs(resp) == ['This operation requires read/write access to project ProjA']
    assert snapshot() == before


def test_no_access_still_redirects_not_404(w):
    # access is checked first: an outsider learns nothing about ids
    outsider = make_user('outsider')
    c = w.client(outsider)
    resp = c.get(iurl('edit_spec_item', 'DataItem', w.a.id, 99999))
    assert resp.status_code == 302 and resp.url == '/editor'


# ---- foreign application / ValSet / release ----------------------------------------------------

@pytest.mark.parametrize('view', ['add_spec_item', 'copy_spec_item', 'split_spec_item', 'edit_spec_item', 'del_spec_item'])
def test_foreign_application_on_write_is_404(w, view):
    c = w.client(w.rw)
    req_a = make_spec_item(w.a, cat='Requirement', domain='AR', name='ra', application=w.app_a, status='NEW',
                           p_kind='STD', s_kind='TST')
    before = snapshot()
    if view == 'add_spec_item':
        url = aurl('Requirement', w.a.id, w.app_b.id)
    else:
        url = iurl(view, 'Requirement', w.a.id, req_a.id, app_id=w.app_b.id)
    assert c.get(url).status_code == 404
    assert c.post(url, REQ).status_code == 404
    assert snapshot() == before


def test_own_application_add_unchanged(w):
    c = w.client(w.rw)
    resp = c.post(aurl('Requirement', w.a.id, w.app_a.id), REQ)
    assert resp.status_code == 302
    item = SpecItem.objects.get(name='r1')
    assert (item.project, item.application, item.val_set) == (w.a, w.app_a, w.dvs_a)


def test_import_foreign_application_and_valset_is_404(w):
    from django.core.files.uploadedfile import SimpleUploadedFile
    c = w.client(w.rw)
    before = snapshot()
    f = SimpleUploadedFile('x.csv', b'a')
    url = '/editor/Requirement/%d/%d/%d/Sel_All/import_spec_items' % (w.a.id, w.app_b.id, w.dvs_a.id)
    assert c.get(url).status_code == 404
    assert c.post(url, {'upload_file': f}).status_code == 404
    url = '/editor/Requirement/%d/%d/%d/Sel_All/import_spec_items' % (w.a.id, w.app_a.id, w.dvs_b.id)
    assert c.get(url).status_code == 404
    url = '/editor/Requirement/%d/%d/%d/Sel_All/import_spec_items' % (w.a.id, w.app_a.id, w.dvs_a.id)
    assert c.get(url).status_code == 200
    assert snapshot() == before


def test_export_and_list_foreign_release_is_404(w):
    c = w.client(w.rw)
    rel_b = w.b.release.id
    assert c.get('/editor/DataItemType/%d/0/%d/Sel_All/%d/export_spec_items' % (w.a.id, w.dvs_a.id, rel_b)).status_code == 404
    assert c.get('/editor/DataItemType/%d/0/%d/Sel_All/%d/list_spec_items' % (w.a.id, w.dvs_a.id, rel_b)).status_code == 404
    assert c.get('/editor/DataItemType/%d/0/%d/Sel_All/%d/export_spec_items' % (w.a.id, w.dvs_a.id, w.a.release.id)).status_code == 200


def test_release_chain_and_application_release_accepted(w):
    older = w.a.release
    newer = make_release(w.owner_a, project_version=1, previous=older)
    w.a.release = newer
    w.a.save()
    app_rel = make_release(w.owner_a, application_version=1, previous=w.app_a.release)
    w.app_a.release = app_rel
    w.app_a.save()
    c = w.client(w.rw)
    for rel in (older.id, newer.id):
        assert c.get('/editor/DataItemType/%d/0/%d/Sel_All/%d/list_spec_items' % (w.a.id, w.dvs_a.id, rel)).status_code == 200
    # an application release is accepted for that application only
    url = '/editor/Requirement/%d/%d/%d/Sel_All/%d/list_spec_items'
    assert c.get(url % (w.a.id, w.app_a.id, w.dvs_a.id, app_rel.id)).status_code == 200
    assert c.get(url % (w.a.id, 0, w.dvs_a.id, app_rel.id)).status_code == 404
    assert c.get(url % (w.a.id, w.app_a.id, w.dvs_a.id, 999999)).status_code == 404


def test_query_helpers_scoped_by_project(w):
    req_b = make_spec_item(w.b, cat='Requirement', domain='BR', name='rb', application=w.app_b)
    assert list(get_spec_item_query(w.a.id, w.app_b.id, w.dvs_b.id, 'Requirement', None, 'Sel_All', None)) == []
    assert list(get_spec_item_query(w.b.id, w.app_b.id, w.dvs_b.id, 'Requirement', None, 'Sel_All', None)) == [req_b]
    assert get_domains('Requirement', w.app_b.id, w.a.id) == ['Sel_All']
    assert get_domains('Requirement', w.app_b.id, w.b.id) == ['Sel_All', 'BR']


# ---- find/replace needs write access -----------------------------------------------------------

def test_find_replace_by_rw_member_still_works(w):
    c = w.client(w.rw)
    resp = c.post('/editor/DataItemType/%d/0/%d/Sel_All/0/list_spec_items' % (w.a.id, w.dvs_a.id),
                  {'field': 'name', 'find': 'AInt', 'replace': 'AInt2'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert resp.json() == {'updated_count': 1}


def test_find_replace_by_outsider_is_refused(w):
    c = w.client(make_user('outsider'))
    before = snapshot()
    resp = c.post('/editor/DataItemType/%d/0/%d/Sel_All/0/list_spec_items' % (w.a.id, w.dvs_a.id),
                  {'field': 'name', 'find': 'AInt', 'replace': 'AInt2'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert resp.status_code == 302
    assert snapshot() == before


# ---- ValSets ----------------------------------------------------------------------------------

def test_edit_val_set_foreign_is_404_own_works(w):
    c = w.client(w.staff)
    vs = make_val_set(w.a, 'Mine')
    assert c.post('/editor/%d/%d/edit_val_set' % (w.a.id, w.dvs_b.id), {'name': 'x', 'description': 'd'}).status_code == 404
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, vs.id), {'name': 'Renamed', 'description': 'd2'})
    assert r.status_code == 302
    vs.refresh_from_db()
    assert (vs.name, vs.desc) == ('Renamed', 'd2')


@pytest.mark.parametrize('name', ['Default', 'default', ' DEFAULT '])
def test_add_val_set_named_default_is_form_error(w, name):
    c = w.client(w.staff)
    r = c.post('/editor/%d/add_val_set' % w.a.id, {'name': name, 'description': 'dup'})
    assert r.status_code == 200 and r.context['form'].errors.get('name')
    assert ValSet.objects.filter(project=w.a).count() == 1


def test_default_val_set_cannot_be_renamed_but_description_can(w):
    c = w.client(w.staff)
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, w.dvs_a.id), {'name': 'Other', 'description': 'd'})
    assert r.status_code == 200 and r.context['form'].errors.get('name')
    w.dvs_a.refresh_from_db()
    assert w.dvs_a.name == 'Default'
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, w.dvs_a.id), {'name': 'Default', 'description': 'new desc'})
    assert r.status_code == 302
    w.dvs_a.refresh_from_db()
    assert (w.dvs_a.name, w.dvs_a.desc) == ('Default', 'new desc')


def test_other_val_set_cannot_be_renamed_to_default(w):
    c = w.client(w.staff)
    vs = make_val_set(w.a, 'Mine')
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, vs.id), {'name': 'Default', 'description': 'd'})
    assert r.status_code == 200 and r.context['form'].errors.get('name')
    vs.refresh_from_db()
    assert vs.name == 'Mine'


def test_default_val_set_cannot_be_deleted(w):
    c = w.client(w.staff)
    r = c.post('/editor/%d/edit_project' % w.a.id, {'del_val_set_id': w.dvs_a.id})
    assert r.status_code == 302
    assert ValSet.objects.filter(id=w.dvs_a.id).exists()
    assert msgs(r) == ['The Default ValSet cannot be deleted']


def test_add_val_set_db_collation_variant_of_default(w):
    # 'Défault' differs from 'Default' in Python; utf8mb4_unicode_ci (MySQL) treats them as equal,
    # which would give the project two Default ValSets.
    c = w.client(w.staff)
    r = c.post('/editor/%d/add_val_set' % w.a.id, {'name': 'D\u00e9fault', 'description': 'dup'})
    if is_mysql():
        assert r.status_code == 200 and r.context['form'].errors.get('name')
        assert ValSet.objects.filter(project=w.a).count() == 1
    else:
        assert r.status_code == 302
        assert ValSet.objects.filter(project=w.a).count() == 2


def test_rename_to_db_collation_variant_of_default(w):
    c = w.client(w.staff)
    vs = make_val_set(w.a, 'Mine')
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, vs.id), {'name': 'D\u00e9fault', 'description': 'd'})
    vs.refresh_from_db()
    if is_mysql():
        assert r.status_code == 200 and r.context['form'].errors.get('name')
        assert vs.name == 'Mine'
    else:
        assert r.status_code == 302 and vs.name == 'D\u00e9fault'


def test_default_val_set_description_edit_still_allowed_with_db_check(w):
    c = w.client(w.staff)
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, w.dvs_a.id), {'name': 'Default', 'description': 'd2'})
    assert r.status_code == 302
    w.dvs_a.refresh_from_db()
    assert (w.dvs_a.name, w.dvs_a.desc) == ('Default', 'd2')


def test_default_val_set_cannot_be_renamed_to_variant(w):
    c = w.client(w.staff)
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, w.dvs_a.id), {'name': 'D\u00e9fault', 'description': 'd'})
    assert r.status_code == 200 and r.context['form'].errors.get('name')
    w.dvs_a.refresh_from_db()
    assert w.dvs_a.name == 'Default'


def test_legacy_lowercase_default_val_set_saved_unchanged_is_allowed(w):
    # a legacy ValSet named 'default' (other project, no Default clash there) keeps its name
    c = w.client(w.staff)
    project = make_project(w.owner_a, 'ProjLegacy', cats=CATS)
    legacy = ValSet.objects.create(name='default', desc='old', project=project,
                                   updated_at=w.dvs_a.updated_at)
    r = c.post('/editor/%d/%d/edit_val_set' % (project.id, legacy.id), {'name': 'default', 'description': 'new'})
    assert r.status_code == 302
    legacy.refresh_from_db()
    assert (legacy.name, legacy.desc) == ('default', 'new')


def test_add_ordinary_val_set_unchanged(w):
    c = w.client(w.staff)
    r = c.post('/editor/%d/add_val_set' % w.a.id, {'name': 'VS9', 'description': 'ok'})
    assert r.status_code == 302
    assert ValSet.objects.filter(project=w.a, name='VS9').exists()


# ---- non-integer ids in edit_project -----------------------------------------------------------

@pytest.mark.parametrize('field', ['del_user_id', 'del_val_set_id', 'user_id'])
def test_non_integer_ids_give_message_not_500(w, field):
    c = w.client(w.staff)
    before = snapshot()
    data = {field: 'abc'}
    if field == 'user_id':
        data['role'] = 'RO'
    r = c.post('/editor/%d/edit_project' % w.a.id, data)
    assert r.status_code == 302
    assert len(msgs(r)) == 1 and 'abc' in msgs(r)[0]
    assert snapshot() == before


# FIXED: find-replace-on-release-view (was: Find & Replace offered and accepted on release views, rewriting historical rows)

def _fr_url(w, rel):
    return '/editor/DataItemType/%d/0/%d/Sel_All/%d/list_spec_items' % (w.a.id, w.dvs_a.id, rel)


def test_find_replace_refused_on_release_view_xhr(w):
    c = w.client(w.rw)
    before = snapshot()
    resp = c.post(_fr_url(w, w.a.release.id), {'field': 'name', 'find': 'AInt', 'replace': 'AInt2'},
                  HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert resp.status_code == 400
    assert resp.json()['errors']['__all__'][0]['message'] == 'Find & Replace is not available on a release view'
    assert snapshot() == before


def test_find_replace_refused_on_release_view_plain_post(w):
    c = w.client(w.rw)
    before = snapshot()
    resp = c.post(_fr_url(w, w.a.release.id), {'field': 'name', 'find': 'AInt', 'replace': 'AInt2'})
    assert resp.status_code == 200
    assert [str(m) for m in get_messages(resp.wsgi_request)] == ['Find & Replace is not available on a release view']
    assert snapshot() == before


@pytest.mark.parametrize('who', ['ro', 'outsider'])
def test_find_replace_release_view_other_roles_still_refused(w, who):
    if who == 'ro':
        user = make_user('ro_fr')
        make_project_user(w.a, user, 'RO')
    else:
        user = w.owner_b
    c = w.client(user)
    before = snapshot()
    resp = c.post(_fr_url(w, w.a.release.id), {'field': 'name', 'find': 'AInt', 'replace': 'x'},
                  HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert resp.status_code in (302, 403)
    assert snapshot() == before


def test_find_replace_not_offered_on_release_view_but_on_current_view(w):
    c = w.client(w.rw)
    assert b'findReplaceModal' not in c.get(_fr_url(w, w.a.release.id)).content
    assert b'findReplaceModal' in c.get(_fr_url(w, 0)).content
