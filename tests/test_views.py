"""
Characterization tests for the functional behaviour of the editor views for an
authorized user (permission matrix, forms, import/export and auth live in other
test modules).  Current behaviour is pinned exactly, including bugs; see
docs/migration/known-issues/views.md for the KNOWN-ISSUE ids used below.
"""
from datetime import datetime, timezone
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.db.models import ProtectedError

from editor.models import Application, ProjectUser, Release, SpecItem, ValSet, Project
from tests.factories import (FIXED_TIME, default_val_set, make_application, make_project,
                             make_project_user, make_release, make_spec_item, make_user,
                             make_val_set)

pytestmark = pytest.mark.django_db

ALL_CATS = 'DataItem,EnumType,EnumValue,DataItemType,InfoItem,Model'


def msgs(response):
    return [(m.level_tag, m.message) for m in get_messages(response.wsgi_request)]


def template_names(response):
    return [t.name for t in response.templates]


@pytest.fixture
def owner(client):
    user = make_user('owner', is_staff=True)
    client.force_login(user)
    return user


@pytest.fixture
def project(owner):
    return make_project(owner, 'Proj', cats=ALL_CATS)


@pytest.fixture
def dvs(project):
    return default_val_set(project)


def lurl(cat, project, dvs, app=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/list_spec_items' % (cat, project.id, app, dvs.id, sel_val, rel)


def item_url(view, cat, project, item, app=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/%s' % (cat, project.id, app, item.id, sel_val, rel, view)


def add_url(cat, project, app=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%s/%d/add_spec_item' % (cat, project.id, app, sel_val, rel)


def post_data(**over):
    """POST data for a DataItem-like SpecItemForm; hidden/unused fields are omitted."""
    data = {'domain': 'Dom', 'name': 'New', 'title': 'A title', 'desc': 'A desc', 'value': '5',
            'rationale': '', 'remarks': '', 'implementation': '', 'p_kind': 'CNS',
            't1': '', 't2': '', 'change_log': 'log text',
            # hidden inputs which the browser posts back with their initial values
            'n1': '0', 'n2': '0', 'n3': '0', 's_kind': 'INV', 's_data': '{}'}
    data.update(over)
    return data


@pytest.fixture
def dtype(project):
    return make_spec_item(project, cat='DataItemType', domain='Types', name='Int32')


# ----------------------------------------------------------------------------
# index / help / repair
# ----------------------------------------------------------------------------

def test_index_anonymous(client):
    owner = make_user('owner', is_staff=True)
    make_project(owner, 'Proj')
    resp = client.get('/editor/')
    assert resp.status_code == 200
    assert 'index.html' in template_names(resp)
    ctx = resp.context['list_of_projects']
    assert len(ctx) == 1
    assert ctx[0]['user_has_access'] is False
    assert b'Sign-In' in resp.content
    assert b'Proj' not in resp.content


def test_index_logged_in_context(client, owner, project, dvs):
    app = make_application(project, 'App', cats='InfoItem')
    make_application(project, 'Alpha', cats='Model')
    resp = client.get('/editor/')
    assert resp.status_code == 200
    assert 'index.html' in template_names(resp)
    entry = resp.context['list_of_projects'][0]
    assert entry['project'] == project
    assert [a.name for a in entry['applications']] == ['Alpha', 'App']
    assert entry['default_val_set_id'] == dvs.id
    assert list(entry['project_configs'].keys()) == [
        k for k in __import__('editor.configs', fromlist=['configs']).configs['cats'] if k in ALL_CATS.split(',')]
    assert entry['user_has_access'] is False
    assert b'add project' in resp.content
    assert b'Proj' in resp.content
    assert app.name.encode() in resp.content


def test_index_orders_projects_by_name(client, owner):
    make_project(owner, 'Zed')
    make_project(owner, 'Abc')
    resp = client.get('/editor/')
    assert [p['project'].name for p in resp.context['list_of_projects']] == ['Abc', 'Zed']


def test_index_user_has_access_substring_bug(client, owner, project):
    bobby = make_user('bobby')
    bob = make_user('bob')
    make_project_user(project, bobby, 'RO')
    client.force_login(bob)
    resp = client.get('/editor/')
    # KNOWN-ISSUE: index-username-substring
    assert resp.context['list_of_projects'][0]['user_has_access'] is True
    client.force_login(make_user('carol'))
    assert client.get('/editor/').context['list_of_projects'][0]['user_has_access'] is False


def test_help(client):
    resp = client.get('/editor/help/')
    assert resp.status_code == 200
    assert 'help.html' in template_names(resp)
    assert resp.context['project_name'] == 'n.a.'


def test_repair_staff(client, owner):
    resp = client.get('/editor/repair/')
    assert resp.status_code == 302
    assert resp.url == '/editor'
    assert msgs(resp) == [('alert-warning', 'Nothing to repair')]


# ----------------------------------------------------------------------------
# change_password
# ----------------------------------------------------------------------------

def test_change_password_valid_post(client, owner):
    resp = client.post('/editor/change_password', {
        'old_password': 'test-password-123', 'new_password1': 'Zx9-brand-new-pw', 'new_password2': 'Zx9-brand-new-pw'})
    assert resp.status_code == 302
    assert resp.url == '/editor/change_password'
    assert msgs(resp) == [('alert-success', 'Your password was successfully updated!')]
    owner.refresh_from_db()
    assert owner.check_password('Zx9-brand-new-pw')
    # session kept (update_session_auth_hash)
    assert client.get('/editor/').context['user'].is_authenticated


def test_change_password_get_raises(client, owner):
    # KNOWN-ISSUE: change-password-no-response
    with pytest.raises(ValueError):
        client.get('/editor/change_password')


def test_change_password_invalid_post_raises(client, owner):
    # KNOWN-ISSUE: change-password-no-response
    with pytest.raises(ValueError):
        client.post('/editor/change_password', {
            'old_password': 'wrong', 'new_password1': 'Zx9-brand-new-pw', 'new_password2': 'Zx9-brand-new-pw'})
    owner.refresh_from_db()
    assert owner.check_password('test-password-123')


# ----------------------------------------------------------------------------
# projects
# ----------------------------------------------------------------------------

def test_add_project_get(client, owner):
    resp = client.get('/editor/add_project')
    assert resp.status_code == 200
    assert 'generic_form.html' in template_names(resp)
    assert resp.context['title'] == 'Add New Project'


def test_add_project_post_creates_release_project_valset(client, owner):
    other = make_user('other')
    resp = client.post('/editor/add_project', {
        'name': 'NewP', 'description': 'Desc', 'cats': 'InfoItem, Model', 'owner': other.id})
    assert resp.status_code == 302
    assert resp.url == '/editor'
    p = Project.objects.get(name='NewP')
    assert p.owner == other
    assert p.desc == 'Desc'
    assert p.cats == 'InfoItem,Model'
    assert str(p.release) == '0.0'
    assert p.release.desc == 'Initial release for project NewP'
    assert p.release.release_author == owner
    assert p.release.previous is None
    vs = ValSet.objects.get(project=p)
    assert (vs.name, vs.desc) == ('Default', 'Default ValSet')


def test_add_project_invalid_cats(client, owner):
    resp = client.post('/editor/add_project', {
        'name': 'NewP', 'description': 'Desc', 'cats': 'Bogus', 'owner': owner.id})
    assert resp.status_code == 200
    assert 'cats' in resp.context['form'].errors
    assert not Project.objects.filter(name='NewP').exists()


def test_edit_project_get(client, owner, project, dvs):
    u2 = make_user('u2')
    pu = make_project_user(project, u2, 'RW')
    resp = client.get('/editor/%d/edit_project' % project.id)
    assert resp.status_code == 200
    assert 'edit_project.html' in template_names(resp)
    assert resp.context['project'] == project
    assert resp.context['form'].initial == {'name': 'Proj', 'description': 'Project description',
                                            'cats': ALL_CATS, 'owner': owner}
    assert [u['username'] for u in resp.context['users']] == ['u2']
    assert resp.context['project_users'] == [pu]
    assert resp.context['val_sets'] == [dvs]


def test_edit_project_post_updates(client, owner, project):
    u2 = make_user('u2')
    resp = client.post('/editor/%d/edit_project' % project.id, {
        'name': 'Renamed', 'description': 'New desc', 'cats': 'InfoItem', 'owner': u2.id})
    assert resp.status_code == 302
    assert resp.url == '/editor'
    project.refresh_from_db()
    assert (project.name, project.desc, project.cats, project.owner) == ('Renamed', 'New desc', 'InfoItem', u2)


def test_edit_project_post_invalid(client, owner, project):
    resp = client.post('/editor/%d/edit_project' % project.id, {
        'name': '', 'description': 'x', 'cats': 'InfoItem', 'owner': owner.id})
    assert resp.status_code == 200
    assert 'name' in resp.context['form'].errors
    project.refresh_from_db()
    assert project.name == 'Proj'


def test_edit_project_post_adds_and_updates_user(client, owner, project):
    # FIXED: mutation-via-get (was: GET ?user_id=&role= added/changed the member and rendered 200)
    u2 = make_user('u2')
    url = '/editor/%d/edit_project' % project.id
    resp = client.post(url, {'user_id': u2.id, 'role': 'RW'})
    assert resp.status_code == 302 and resp.url == url
    pu = ProjectUser.objects.get(project=project, user=u2)
    assert pu.role == 'RW'
    resp = client.post(url, {'user_id': u2.id, 'role': 'RO'})
    assert ProjectUser.objects.get(project=project, user=u2).role == 'RO'
    assert ProjectUser.objects.filter(project=project).count() == 1
    resp = client.get(url)
    assert resp.context['project_users'][0].role == 'RO'


def test_edit_project_del_user_id_is_unscoped(client, owner, project):
    other_project = make_project(owner, 'Other')
    u2 = make_user('u2')
    pu_other = make_project_user(other_project, u2, 'RO')
    resp = client.post('/editor/%d/edit_project' % project.id, {'del_user_id': pu_other.id})
    assert resp.status_code == 302
    # FIXED: edit-project-del-user-unscoped (was: the other project's ProjectUser was deleted) — upstream #86
    assert ProjectUser.objects.filter(id=pu_other.id).exists()


def test_edit_project_del_user(client, owner, project):
    u2 = make_user('u2')
    pu = make_project_user(project, u2, 'RO')
    # FIXED: mutation-via-get (was: GET ?del_user_id=) — upstream #86
    resp = client.post('/editor/%d/edit_project' % project.id, {'del_user_id': pu.id})
    assert resp.status_code == 302
    assert resp.url == '/editor/%d/edit_project' % project.id
    assert not ProjectUser.objects.filter(id=pu.id).exists()


def test_edit_project_del_val_set(client, owner, project):
    vs = make_val_set(project, 'VS1')
    # FIXED: mutation-via-get (was: GET ?del_val_set_id=) — upstream #86
    resp = client.post('/editor/%d/edit_project' % project.id, {'del_val_set_id': vs.id})
    assert resp.status_code == 302
    assert resp.url == '/editor/%d/edit_project' % project.id
    assert not ValSet.objects.filter(id=vs.id).exists()
    assert msgs(resp) == []


def test_edit_project_del_val_set_protected(client, owner, project, dvs):
    # Task 6.4 (edit-project-valset-unscoped): was the Default ValSet; the Default ValSet can no longer
    # be deleted at all (see test_edit_project_del_default_val_set_refused), so a ValSet in use is used.
    vs1 = make_val_set(project, 'VS1')
    make_spec_item(project, cat='InfoItem', name='X', val_set=vs1)
    # FIXED: mutation-via-get (was: GET ?del_val_set_id=) — upstream #86
    resp = client.post('/editor/%d/edit_project' % project.id, {'del_val_set_id': vs1.id})
    assert resp.status_code == 302
    assert ValSet.objects.filter(id=vs1.id).exists()
    [(level, text)] = msgs(resp)
    assert level == 'alert-danger'
    assert text.startswith('Failure to delete ValSet with id %d, possibly because it is still in use: ProtectedError(' % vs1.id)


def test_edit_project_del_default_val_set_refused(client, owner, project, dvs):
    resp = client.post('/editor/%d/edit_project' % project.id, {'del_val_set_id': dvs.id})
    assert resp.status_code == 302
    assert ValSet.objects.filter(id=dvs.id).exists()
    assert [t for _, t in msgs(resp)] == ['The Default ValSet cannot be deleted']


def test_del_project_full_cascade(client, owner, project, dvs, dtype):
    # FIXED: mutation-via-get (was: GET /del_project deleted the project) — upstream #86
    app = make_application(project, 'App', cats='InfoItem')
    app_rel2 = make_release(owner, previous=app.release, application_version=1)
    app.release = app_rel2
    app.save()
    # project release chain of length 2
    new_rel = make_release(owner, project_version=1, previous=project.release)
    project.release = new_rel
    project.save()
    vs1 = make_val_set(project, 'VS1')
    parent = make_spec_item(project, cat='EnumType', domain='D', name='E')
    child = make_spec_item(project, cat='EnumValue', domain='D', name='V', s_link=parent)
    alias = make_spec_item(project, cat='EnumValue', domain='D', name='V', val_set=vs1, p_link=child)
    old = make_spec_item(project, cat='InfoItem', domain='D', name='I', application=app, status='OBS')
    cur = make_spec_item(project, cat='InfoItem', domain='D', name='I', application=app, previous=old)
    make_project_user(project, make_user('u2'), 'RW')
    other = make_project(owner, 'Keep')
    keep_item = make_spec_item(other, cat='InfoItem', name='K')
    n_releases_before = Release.objects.count()

    resp = client.post('/editor/%d/del_project' % project.id)
    assert resp.status_code == 302
    assert resp.url == '/editor'
    assert not Project.objects.filter(id=project.id).exists()
    assert not SpecItem.objects.filter(project_id=project.id).exists()
    assert not ValSet.objects.filter(project_id=project.id).exists()
    assert not Application.objects.filter(project_id=project.id).exists()
    assert not ProjectUser.objects.filter(project_id=project.id).exists()
    # 2 project releases + 2 application releases deleted
    assert Release.objects.count() == n_releases_before - 4
    assert Project.objects.filter(id=other.id).exists()
    assert SpecItem.objects.filter(id=keep_item.id).exists()
    assert msgs(resp) == []


# ----------------------------------------------------------------------------
# val sets / applications
# ----------------------------------------------------------------------------

def test_add_val_set(client, owner, project):
    url = '/editor/%d/add_val_set' % project.id
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'generic_form.html' in template_names(resp)
    assert resp.context['title'] == 'Add ValSet to Project Proj'
    resp = client.post(url, {'name': 'VS9', 'description': 'nine'})
    assert resp.status_code == 302
    assert resp.url == '/editor/%d/edit_project' % project.id
    vs = ValSet.objects.get(project=project, name='VS9')
    assert vs.desc == 'nine'


def test_add_val_set_invalid(client, owner, project):
    resp = client.post('/editor/%d/add_val_set' % project.id, {'name': '', 'description': 'x'})
    assert resp.status_code == 200
    assert 'name' in resp.context['form'].errors


def test_edit_val_set(client, owner, project):
    vs = make_val_set(project, 'VS1', 'old')
    url = '/editor/%d/%d/edit_val_set' % (project.id, vs.id)
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context['title'] == 'Edit ValSet VS1'
    assert resp.context['form'].initial == {'name': 'VS1', 'description': 'old'}
    resp = client.post(url, {'name': 'VS2', 'description': 'new'})
    assert resp.status_code == 302
    assert resp.url == '/editor/%d/edit_project' % project.id
    vs.refresh_from_db()
    assert (vs.name, vs.desc) == ('VS2', 'new')


def test_add_application(client, owner, project):
    url = '/editor/%d/add_application' % project.id
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'generic_form.html' in template_names(resp)
    assert resp.context['title'] == 'Add Application to Project Proj'
    resp = client.post(url, {'name': 'NewApp', 'description': 'D', 'cats': 'InfoItem, Model'})
    assert resp.status_code == 302
    assert resp.url == '/editor'
    app = Application.objects.get(name='NewApp')
    assert (app.desc, app.cats, app.project) == ('D', 'InfoItem,Model', project)
    assert str(app.release) == '0.0'
    assert app.release.desc == 'Initial release for application NewApp'
    assert app.release.release_author == owner
    assert app.release.previous is None


def test_add_application_invalid_cats(client, owner, project):
    resp = client.post('/editor/%d/add_application' % project.id,
                       {'name': 'NewApp', 'description': 'D', 'cats': 'Requirement'})
    assert resp.status_code == 200
    assert 'cats' in resp.context['form'].errors
    assert not Application.objects.exists()


def test_edit_application(client, owner, project):
    app = make_application(project, 'App', cats='InfoItem')
    url = '/editor/%d/edit_application' % app.id
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context['title'] == 'Edit Application App'
    assert resp.context['form'].initial == {'name': 'App', 'description': 'Application description', 'cats': 'InfoItem'}
    resp = client.post(url, {'name': 'App2', 'description': 'D2', 'cats': 'Model'})
    assert resp.status_code == 302
    assert resp.url == '/editor'
    app.refresh_from_db()
    assert (app.name, app.desc, app.cats) == ('App2', 'D2', 'Model')


# ----------------------------------------------------------------------------
# list_spec_items
# ----------------------------------------------------------------------------

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@pytest.fixture
def items(project, dtype):
    a_a = make_spec_item(project, domain='A', name='a', title='foo bar', p_kind='VAR', p_link=dtype)
    a_b = make_spec_item(project, domain='A', name='b', title='foo baz', p_kind='CNS', p_link=dtype)
    b_c = make_spec_item(project, domain='B', name='c', title='other', p_kind='PAR', p_link=dtype)
    return a_a, a_b, b_c


def listed(resp):
    return [(i.domain, i.name) for i in resp.context['page_items']]


def test_list_defaults(client, owner, project, dvs, items):
    resp = client.get(lurl('DataItem', project, dvs))
    assert resp.status_code == 200
    assert template_names(resp)[:2] == ['list_spec_items.html', 'base_generic.html']
    assert listed(resp) == [('A', 'a'), ('A', 'b'), ('B', 'c')]
    ctx = resp.context
    assert ctx['disp'] == 'disp_def'
    assert ctx['cat'] == 'DataItem'
    assert ctx['project'] == project
    assert ctx['application_id'] == 0
    assert ctx['sel_val'] == 'Sel_All'
    assert ctx['val_set'] == dvs
    assert list(ctx['val_sets']) == [dvs]
    assert ctx['default_val_set_id'] == dvs.id
    assert ctx['domains'] == ['Sel_All', 'A', 'B']
    assert ctx['history'] is False
    assert ctx['expand_id'] is None and ctx['expand_items'] is None and ctx['expand_link'] is None
    assert ctx['order_by'] is None
    assert ctx['sel_rel'] is None and ctx['sel_rel_id'] == 0
    assert ctx['n_pad_fields'] == range(len(ctx['config']['disp_def']) - 3)
    assert ctx['get_parameter_sting'] == '?disp=disp_def&'
    assert [r.id for r in ctx['releases']] == [project.release.id]
    assert ctx['pagination']['page_number'] == 1
    assert ctx['pagination']['has_previous'] is False and ctx['pagination']['has_next'] is False
    assert ctx['pagination']['previous_page'] is None and ctx['pagination']['next_page'] is None
    # (pagination['page_list'] is a generator consumed by the template)
    assert ctx['find_replace_fields'] == ctx['config']['attrs']
    assert not ctx['find_replace_form'].is_bound
    bc = ctx['breadcrumb']
    assert bc['rest'] == []
    assert [d['spec_item'] for d in bc['active']] == ['EnumType', 'DataItemType']  # excludes current + EnumValue ('None' level)
    assert b'foo bar' in resp.content


def test_list_hides_del_and_obs_items(client, owner, project, dvs, items):
    make_spec_item(project, domain='Z', name='del', status='DEL')
    make_spec_item(project, domain='Z', name='obs', status='OBS')
    resp = client.get(lurl('DataItem', project, dvs))
    assert listed(resp) == [('A', 'a'), ('A', 'b'), ('B', 'c')]
    assert resp.context['domains'] == ['Sel_All', 'A', 'B']


@pytest.mark.parametrize('disp', ['disp_def', 'disp_short', 'disp_trac'])
def test_list_disp_variants(client, owner, project, dvs, items, disp):
    resp = client.get(lurl('DataItem', project, dvs), {'disp': disp})
    assert resp.status_code == 200
    assert resp.context['disp'] == disp
    assert resp.context['disp_list'] == resp.context['config'][disp]
    assert resp.context['get_parameter_sting'] == '?disp=%s&' % disp


def test_list_unknown_disp_raises(client, owner, project, dvs, items):
    # KNOWN-ISSUE: list-500s
    with pytest.raises(KeyError):
        client.get(lurl('DataItem', project, dvs), {'disp': 'bogus'})


def test_list_unknown_cat_raises(client, owner, project, dvs, items):
    # KNOWN-ISSUE: list-500s
    with pytest.raises(KeyError):
        client.get(lurl('Bogus', project, dvs))


@pytest.mark.parametrize('order_by,expected', [
    ('title', [('A', 'a'), ('A', 'b'), ('B', 'c')]),
    ('p_kind', [('A', 'b'), ('B', 'c'), ('A', 'a')]),
    ('name', [('A', 'a'), ('A', 'b'), ('B', 'c')]),
])
def test_list_order_by(client, owner, project, dvs, items, order_by, expected):
    resp = client.get(lurl('DataItem', project, dvs), {'order_by': order_by})
    assert resp.status_code == 200
    assert resp.context['order_by'] == order_by
    assert resp.context['get_parameter_sting'] == '?disp=disp_def&order_by=%s&' % order_by
    assert listed(resp) == expected


def test_list_order_by_p_link_distinct_targets(client, owner, project, dvs, items):
    # order_by=p_link sorts by the link target's (domain, name); targets are distinct here so the
    # order is fully determined
    a_a, a_b, b_c = items
    t_z = make_spec_item(project, cat='DataItemType', domain='Z', name='z')
    t_a = make_spec_item(project, cat='DataItemType', domain='A', name='a')
    t_m = make_spec_item(project, cat='DataItemType', domain='M', name='m')
    for item, target in ((a_a, t_z), (a_b, t_a), (b_c, t_m)):
        SpecItem.objects.filter(id=item.id).update(p_link=target)
    resp = client.get(lurl('DataItem', project, dvs), {'order_by': 'p_link'})
    assert resp.status_code == 200
    assert resp.context['order_by'] == 'p_link'
    assert resp.context['get_parameter_sting'] == '?disp=disp_def&order_by=p_link&'
    assert listed(resp) == [('A', 'b'), ('B', 'c'), ('A', 'a')]


def test_list_order_by_owner_distinct_usernames(client, owner, project, dvs, items):
    a_a, a_b, b_c = items
    for item, uname in ((a_a, 'cara'), (a_b, 'abe'), (b_c, 'bob')):
        SpecItem.objects.filter(id=item.id).update(owner=make_user(uname))
    resp = client.get(lurl('DataItem', project, dvs), {'order_by': 'owner'})
    assert resp.status_code == 200
    assert resp.context['get_parameter_sting'] == '?disp=disp_def&order_by=owner&'
    assert listed(resp) == [('A', 'b'), ('B', 'c'), ('A', 'a')]


@pytest.mark.parametrize('order_by', ['p_link', 'owner'])
def test_list_order_by_ties_are_compared_as_set(client, owner, project, dvs, items, order_by):
    # All items share the same p_link target / owner: the order among them is undefined (the
    # sort key has no tie-breaker for p_link), so only the set of items is asserted.
    resp = client.get(lurl('DataItem', project, dvs), {'order_by': order_by})
    assert resp.status_code == 200
    assert len(listed(resp)) == 3
    assert set(listed(resp)) == {('A', 'a'), ('A', 'b'), ('B', 'c')}


def test_list_order_by_unknown_field_raises(client, owner, project, dvs, items):
    # KNOWN-ISSUE: list-500s
    from django.core.exceptions import FieldError
    with pytest.raises(FieldError):
        client.get(lurl('DataItem', project, dvs), {'order_by': 'bogus'})


def test_list_sel_val_filters_domain(client, owner, project, dvs, items):
    resp = client.get(lurl('DataItem', project, dvs, sel_val='B'))
    assert listed(resp) == [('B', 'c')]
    assert resp.context['sel_val'] == 'B'
    assert resp.context['domains'] == ['Sel_All', 'A', 'B']


def test_list_other_val_set(client, owner, project, dvs, items):
    vs1 = make_val_set(project, 'VS1')
    alias = make_spec_item(project, domain='A', name='a', val_set=vs1, p_link=items[0])
    resp = client.get(lurl('DataItem', project, vs1))
    assert listed(resp) == [('A', 'a')]
    assert resp.context['val_set'] == vs1
    assert resp.context['default_val_set_id'] == dvs.id
    assert [v.name for v in resp.context['val_sets']] == ['Default', 'VS1']


def test_list_pagination(client, owner, project, dvs, items, monkeypatch):
    from editor.configs import configs
    monkeypatch.setitem(configs['cats']['DataItem'], 'page_size', 2)
    resp = client.get(lurl('DataItem', project, dvs))
    assert listed(resp) == [('A', 'a'), ('A', 'b')]
    pg = resp.context['pagination']
    assert (pg['page_number'], pg['has_previous'], pg['has_next'], pg['next_page']) == (1, False, True, 2)
    resp = client.get(lurl('DataItem', project, dvs), {'page': '2'})
    assert listed(resp) == [('B', 'c')]
    pg = resp.context['pagination']
    assert (pg['page_number'], pg['has_previous'], pg['previous_page'], pg['has_next']) == (2, True, 1, False)


def test_list_pagination_non_integer_page_raises(client, owner, project, dvs, items):
    # KNOWN-ISSUE: list-500s
    with pytest.raises(ValueError):
        client.get(lurl('DataItem', project, dvs), {'page': 'abc'})


def test_list_pagination_out_of_range_raises(client, owner, project, dvs, items):
    # KNOWN-ISSUE: list-500s
    from django.core.paginator import EmptyPage
    with pytest.raises(EmptyPage):
        client.get(lurl('DataItem', project, dvs), {'page': '9'})


def test_list_expand_s_link(client, owner, project, dvs):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    v1 = make_spec_item(project, cat='EnumValue', domain='E', name='v1', s_link=et)
    v2 = make_spec_item(project, cat='EnumValue', domain='E', name='v2', s_link=et)
    make_spec_item(project, cat='EnumValue', domain='E', name='gone', s_link=et, status='DEL')
    resp = client.get(lurl('EnumType', project, dvs), {'expand_id': et.id, 'expand_link': 's_link'})
    assert resp.status_code == 200
    assert resp.context['expand_id'] == et.id            # cast to int
    assert resp.context['expand_link'] == 's_link'
    assert list(resp.context['expand_items']) == [v1, v2]
    assert resp.context['get_parameter_sting'] == '?expand_id=%d&expand_link=s_link&disp=disp_def&' % et.id


def test_list_expand_p_link(client, owner, project, dvs, dtype):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    di = make_spec_item(project, domain='D', name='i', p_link=et)
    resp = client.get(lurl('EnumType', project, dvs), {'expand_id': et.id, 'expand_link': 'p_link'})
    assert list(resp.context['expand_items']) == [di]


def test_list_expand_link_none_string(client, owner, project, dvs, items):
    resp = client.get(lurl('DataItem', project, dvs), {'expand_id': '7', 'expand_link': 'None'})
    assert resp.context['expand_items'] is None
    assert resp.context['expand_id'] == '7'              # not cast


def test_list_expand_without_link_raises(client, owner, project, dvs, items):
    # KNOWN-ISSUE: list-500s
    with pytest.raises(KeyError):
        client.get(lurl('DataItem', project, dvs), {'expand_id': items[0].id})


def test_list_expand_link_unused_for_cat(client, owner, project, dvs, items):
    resp = client.get(lurl('DataItem', project, dvs), {'expand_id': items[0].id, 'expand_link': 's_link'})
    assert resp.context['expand_items'] is None


def test_list_release_view(client, owner, project, dvs, dtype):
    rel_time = datetime(2024, 2, 1, 0, 0, tzinfo=timezone.utc)
    before = datetime(2024, 1, 20, tzinfo=timezone.utc)
    after = datetime(2024, 3, 1, tzinfo=timezone.utc)
    rel = make_release(owner, project_version=1, previous=project.release, updated_at=rel_time, desc='R1')
    project.release = rel
    project.save()
    make_spec_item(project, domain='R', name='conf', status='CNF', created_at=before, updated_at=before)
    make_spec_item(project, domain='R', name='new', status='NEW', created_at=before, updated_at=before)
    make_spec_item(project, domain='R', name='confafter', status='CNF', created_at=before, updated_at=after)
    make_spec_item(project, domain='R', name='createdafter', status='CNF', created_at=after, updated_at=after)
    make_spec_item(project, domain='R', name='deleted', status='DEL', created_at=before, updated_at=after)
    resp = client.get(lurl('DataItem', project, dvs, rel=rel.id))
    assert resp.status_code == 200
    assert resp.context['sel_rel'] == rel
    assert resp.context['sel_rel_id'] == rel.id
    assert listed(resp) == [('R', 'conf'), ('R', 'deleted')]
    assert [r.id for r in resp.context['releases']] == [rel.id, rel.previous.id]
    assert b'Release: 1.0' in resp.content


# ---- find & replace ----------------------------------------------------------

def test_find_replace_form_post(client, owner, project, dvs, items):
    other = make_user('other')
    client.force_login(other)
    make_project_user(project, other, 'RW')
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': 'foo', 'replace': 'qux'})
    assert resp.status_code == 200
    assert 'list_spec_items.html' in template_names(resp)
    assert resp.context['find_replace_form'].is_valid()
    a, b, c = [SpecItem.objects.get(id=i.id) for i in items]
    assert (a.title, b.title, c.title) == ('qux bar', 'qux baz', 'other')
    assert a.owner == other and b.owner == other and c.owner == owner
    assert a.updated_at > FIXED_TIME and b.updated_at > FIXED_TIME and c.updated_at == FIXED_TIME
    assert a.status == 'NEW'     # status and history untouched


def test_find_replace_xhr_success(client, owner, project, dvs, items):
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': 'foo', 'replace': 'qux'}, **XHR)
    assert resp.status_code == 200
    assert resp['Content-Type'] == 'application/json'
    assert resp.json() == {'updated_count': 2}


def test_find_replace_xhr_no_match(client, owner, project, dvs, items):
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': 'nomatch', 'replace': 'x'}, **XHR)
    assert resp.json() == {'updated_count': 0}
    assert SpecItem.objects.get(id=items[0].id).updated_at == FIXED_TIME


@pytest.mark.parametrize('data,errors', [
    ({'field': 'title', 'find': 'foo', 'replace': 'foo'},
     {'__all__': [{'message': 'Error: Find and replace values must be different', 'code': ''}]}),
    ({'field': 'zzz', 'find': 'a', 'replace': 'b'},
     {'field': [{'message': 'Select a valid field', 'code': ''}]}),
    ({'field': 'n1', 'find': 'a', 'replace': 'b'},
     {'field': [{'message': 'Select a valid field', 'code': ''}]}),
    ({'field': 'name', 'find': 'a', 'replace': 'b'},
     {'__all__': [{'message': "Error: Name 'b' already exists in domain 'A'", 'code': ''}]}),
    ({'field': 'domain', 'find': 'A', 'replace': 'x y'},
     {'__all__': [{'message': 'Error: Only alphanumeric characters, underscores and dashes allowed; '
                              'dots must be internal', 'code': ''}]}),
])
def test_find_replace_xhr_errors(client, owner, project, dvs, items, data, errors):
    resp = client.post(lurl('DataItem', project, dvs), data, **XHR)
    assert resp.status_code == 400
    assert resp.json() == {'errors': errors}
    assert all(SpecItem.objects.get(id=i.id).updated_at == FIXED_TIME for i in items)


def test_find_replace_xhr_missing_find(client, owner, project, dvs, items):
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': '', 'replace': 'x'}, **XHR)
    assert resp.status_code == 400
    # Django's own message wording is not asserted (harness rule 3); only the error key and code
    errors = resp.json()['errors']
    assert list(errors) == ['find']
    assert [e['code'] for e in errors['find']] == ['required']


def test_find_replace_non_ajax_error_renders_form_errors(client, owner, project, dvs, items):
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': 'foo', 'replace': 'foo'})
    assert resp.status_code == 200
    assert resp.context['find_replace_form'].non_field_errors() == ['Error: Find and replace values must be different']


def test_find_replace_domain_rename_no_conflict(client, owner, project, dvs, items):
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'domain', 'find': 'B', 'replace': 'A2'}, **XHR)
    assert resp.json() == {'updated_count': 1}
    assert SpecItem.objects.get(id=items[2].id).domain == 'A2'


def test_find_replace_read_only_user_is_refused(client, owner, project, dvs, items):
    ro = make_user('ro')
    make_project_user(project, ro, 'RO')
    client.force_login(ro)
    # FIXED: find-replace-no-write-check (was: {'updated_count': 2}, items changed by a RO member)
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': 'foo', 'replace': 'qux'}, **XHR)
    assert resp.status_code == 403
    assert list(resp.json()['errors']) == ['__all__']
    assert SpecItem.objects.get(id=items[0].id).title == 'foo bar'
    assert SpecItem.objects.get(id=items[0].id).owner == owner
    # without XHR: redirect with the access message
    resp = client.post(lurl('DataItem', project, dvs), {'field': 'title', 'find': 'foo', 'replace': 'qux'})
    assert resp.status_code == 302
    assert msgs(resp) == [('alert-danger', 'This operation requires read/write access to project Proj')]
    assert SpecItem.objects.get(id=items[0].id).title == 'foo bar'
    # a RO member can still list
    assert client.get(lurl('DataItem', project, dvs)).status_code == 200


def test_find_replace_applies_to_current_domain_filter_only(client, owner, project, dvs, items):
    resp = client.post(lurl('DataItem', project, dvs, sel_val='B'), {'field': 'title', 'find': 'o', 'replace': '0'}, **XHR)
    assert resp.json() == {'updated_count': 1}
    assert SpecItem.objects.get(id=items[0].id).title == 'foo bar'


# ---- application-level list --------------------------------------------------

def test_list_application_items(client, owner, project, dvs):
    app = make_application(project, 'App', cats='InfoItem')
    other_app = make_application(project, 'Other', cats='InfoItem')
    make_spec_item(project, cat='InfoItem', domain='I', name='one', application=app)
    make_spec_item(project, cat='InfoItem', domain='I', name='two', application=other_app)
    resp = client.get(lurl('InfoItem', project, dvs, app=app.id))
    assert resp.status_code == 200
    assert listed(resp) == [('I', 'one')]
    assert resp.context['application_id'] == app.id
    assert resp.context['domains'] == ['Sel_All', 'I']
    bc = resp.context['breadcrumb']
    assert bc['application_name_active'] == 'App'
    assert [d['list_as'] for d in bc['rest']] == ['Proj / Data Item', 'Proj / Enumerated Type', 'Proj / Data Item Type',
                                                   'Proj / Other / Info Item']
    assert bc['active'] == []


# ----------------------------------------------------------------------------
# list_spec_item_history
# ----------------------------------------------------------------------------

def test_history(client, owner, project, dvs, dtype):
    v1 = make_spec_item(project, domain='H', name='x', status='OBS', title='v1')
    v2 = make_spec_item(project, domain='H', name='x', status='OBS', title='v2', previous=v1)
    cur = make_spec_item(project, domain='H', name='x', status='MOD', title='v3', previous=v2)
    resp = client.get('/editor/DataItem/%d/0/%d/Sel_All/list_spec_item_history' % (project.id, cur.id))
    assert resp.status_code == 200
    assert template_names(resp)[:2] == ['list_spec_items.html', 'base_generic.html']
    ctx = resp.context
    assert ctx['page_items'] == [cur, v2, v1]
    assert ctx['history'] is True
    assert ctx['disp'] == 'disp_def'
    assert ctx['expand_id'] == 0
    assert ctx['val_set'] == dvs and ctx['val_set_id'] == dvs.id
    assert ctx['sel_rel'] is None and ctx['sel_rel_id'] == 0
    assert b'History of H:x' in resp.content


# ----------------------------------------------------------------------------
# add_spec_item
# ----------------------------------------------------------------------------

def test_add_spec_item_get(client, owner, project, dvs, dtype):
    resp = client.get(add_url('DataItem', project))
    assert resp.status_code == 200
    assert 'spec_item_form.html' in template_names(resp)
    ctx = resp.context
    assert ctx['title'] == 'Add Data Item'
    assert ctx['sub_title'] == ''
    assert ctx['sel_val'] == 'Sel_All'
    assert ctx['cat'] == 'DataItem'
    assert list(ctx['spec_items']) == [dtype]
    assert [p.id for p in ctx['form'].fields['p_link'].queryset] == [dtype.id]


def test_add_spec_item_get_in_application(client, owner, project, dvs):
    app = make_application(project, 'App', cats='InfoItem')
    resp = client.get(add_url('InfoItem', project, app=app.id))
    assert resp.context['title'] == 'Add Info Item to Application App'


def test_add_spec_item_post(client, owner, project, dvs, dtype):
    resp = client.post(add_url('DataItem', project, sel_val='Dom'),
                       post_data(p_link=dtype.id, p_kind='VAR', t2='m', t1='1'))
    assert resp.status_code == 302
    item = SpecItem.objects.get(name='New')
    assert resp.url == '/editor/DataItem/%d/0/%d/Dom/0/list_spec_items#Dom:New' % (project.id, dvs.id)
    assert item.cat == 'DataItem'
    assert item.val_set == dvs
    assert item.status == 'NEW'
    assert item.owner == owner
    assert item.project == project
    assert item.application is None
    assert item.p_link == dtype
    assert (item.domain, item.title, item.desc, item.p_kind, item.t1, item.t2) == ('Dom', 'A title', 'A desc', 'VAR', '1', 'm')
    assert item.created_at > FIXED_TIME and item.updated_at > FIXED_TIME
    assert item.previous is None


def test_add_spec_item_post_in_application(client, owner, project, dvs):
    app = make_application(project, 'App', cats='InfoItem')
    resp = client.post(add_url('InfoItem', project, app=app.id),
                       {'domain': 'I', 'name': 'one', 'title': 't', 'value': 'v', 'rationale': '', 'remarks': '',
                        'implementation': '', 'change_log': 'cl'})
    assert resp.status_code == 302
    assert resp.url == '/editor/InfoItem/%d/%d/%d/Sel_All/0/list_spec_items#I:one' % (project.id, app.id, dvs.id)
    item = SpecItem.objects.get(name='one')
    assert item.application == app and item.project == project and item.status == 'NEW'


def test_add_spec_item_post_invalid_identifier(client, owner, project, dvs, dtype):
    resp = client.post(add_url('DataItem', project), post_data(p_link=dtype.id, name='bad name'))
    assert resp.status_code == 200
    assert 'name' in resp.context['form'].errors
    assert not SpecItem.objects.filter(domain='Dom').exists()


def test_add_spec_item_post_duplicate(client, owner, project, dvs, dtype):
    make_spec_item(project, domain='Dom', name='New')
    resp = client.post(add_url('DataItem', project), post_data(p_link=dtype.id))
    assert resp.status_code == 200
    assert resp.context['form'].errors['name'] == ["Error: Name 'New' already exists in domain 'Dom'"]
    assert SpecItem.objects.filter(name='New').count() == 1


def test_add_spec_item_with_s_parent(client, owner, project, dvs):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    url = add_url('EnumValue', project) + '?s_parent_id=%d' % et.id
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context['sub_title'] == 'Type ' + str(et)    # label of the s_link attr of EnumValue
    assert [p.id for p in resp.context['form'].fields['s_link'].queryset] == [et.id]
    resp = client.post(url, post_data(domain='E', name='v1', title='one', value='1', s_link=et.id, p_kind=''))
    assert resp.status_code == 302
    assert resp.url == ('/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d&expand_link=s_link#E:T'
                        % (project.id, dvs.id, et.id))
    assert SpecItem.objects.get(name='v1').s_link == et


def test_add_spec_item_with_p_parent_on_cat_without_s_link_raises(client, owner, project, dvs, dtype):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    # KNOWN-ISSUE: add-p-parent-label-keyerror
    with pytest.raises(KeyError):
        client.get(add_url('DataItem', project) + '?p_parent_id=%d' % et.id)


def test_add_spec_item_with_p_parent(client, owner, project, dvs):
    pk = make_spec_item(project, cat='Packet', domain='P', name='pk')
    di = make_spec_item(project, domain='D', name='di')
    url = add_url('PacketPar', project) + '?p_parent_id=%d' % pk.id
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context['sub_title'] == 'Data Item ' + str(pk)   # label of the s_link attr is used (sic)
    data = post_data(domain='P', name='par', p_link=pk.id, s_link=di.id, p_kind='HK')
    resp = client.post(url, data)
    assert resp.status_code == 302, resp.context['form'].errors
    assert resp.url == ('/editor/Packet/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d&expand_link=p_link#P:pk'
                        % (project.id, dvs.id, pk.id))
    item = SpecItem.objects.get(name='par')
    assert item.p_link == pk and item.s_link == di


def test_add_enum_data_item_converts_value_reference(client, owner, project, dvs):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    ev = make_spec_item(project, cat='EnumValue', domain='E', name='v1', s_link=et)
    resp = client.post(add_url('DataItem', project), post_data(p_link=et.id, value='#EnumValue:E:v1', p_kind='VAR'))
    assert resp.status_code == 302
    item = SpecItem.objects.get(name='New')
    assert item.p_link == et
    assert item.value == '#iref:%d' % ev.id          # edit representation converted to db representation


# ----------------------------------------------------------------------------
# edit_spec_item
# ----------------------------------------------------------------------------

def edit_post(item, dtype, **over):
    data = dict(domain=item.domain, name=item.name, p_link=dtype.id, p_kind=item.p_kind or 'CNS')
    data.update(over)
    return post_data(**data)


@pytest.mark.parametrize('status', ['NEW', 'MOD'])
def test_edit_in_place(client, owner, project, dvs, dtype, status):
    editor = make_user('editor')
    make_project_user(project, editor, 'RW')
    client.force_login(editor)
    item = make_spec_item(project, domain='Dom', name='It', status=status, p_link=dtype, p_kind='CNS', value='1')
    url = item_url('edit_spec_item', 'DataItem', project, item, sel_val='Dom')
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'spec_item_form.html' in template_names(resp)
    assert resp.context['title'] == 'Edit Data Item in Project Proj'
    assert resp.context['form'].initial['name'] == 'It'
    resp = client.post(url, edit_post(item, dtype, title='Changed', value='42'))
    assert resp.status_code == 302
    assert resp.url == '/editor/DataItem/%d/0/%d/Dom/0/list_spec_items#Dom:It' % (project.id, dvs.id)
    assert SpecItem.objects.count() == 2        # no copy made
    item.refresh_from_db()
    assert (item.title, item.value, item.status, item.owner) == ('Changed', '42', status, editor)
    assert item.updated_at > FIXED_TIME
    assert item.previous is None
    assert item.change_log == 'log text'


def test_edit_cnf_creates_obs_copy(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', status='CNF', p_link=dtype, p_kind='CNS', value='1',
                          title='Old title')
    url = item_url('edit_spec_item', 'DataItem', project, item)
    resp = client.get(url)
    assert resp.context['form'].initial['change_log'] == ''
    resp = client.post(url, edit_post(item, dtype, title='New title', value='2'))
    assert resp.status_code == 302
    assert SpecItem.objects.count() == 3
    item.refresh_from_db()
    assert item.id == item.id and item.status == 'MOD'
    assert item.title == 'New title' and item.value == '2'
    obs = item.previous
    assert obs is not None and obs.id != item.id
    assert obs.status == 'OBS'
    assert obs.title == 'Old title' and obs.value == '1'
    assert obs.previous is None
    assert obs.updated_at > FIXED_TIME            # OBS copy stamped with current time
    assert obs.owner == owner


def test_edit_cnf_twice_chains_history(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', status='CNF', p_link=dtype, p_kind='CNS', value='1')
    url = item_url('edit_spec_item', 'DataItem', project, item)
    client.post(url, edit_post(item, dtype, value='2'))
    item.refresh_from_db()
    first_obs = item.previous
    SpecItem.objects.filter(id=item.id).update(status='CNF')
    client.post(url, edit_post(item, dtype, value='3'))
    item.refresh_from_db()
    assert item.value == '3' and item.status == 'MOD'
    assert item.previous.value == '2'
    assert item.previous.previous == first_obs
    assert first_obs.value == '1'


@pytest.mark.parametrize('status', ['DEL', 'OBS'])
def test_edit_not_editable_status(client, owner, project, dvs, dtype, status):
    item = make_spec_item(project, status=status, p_link=dtype)
    url = item_url('edit_spec_item', 'DataItem', project, item)
    for do in (lambda: client.get(url), lambda: client.post(url, edit_post(item, dtype))):
        client.logout()
        client.force_login(owner)
        resp = do()
        assert resp.status_code == 302
        assert resp.url == '/editor'
        assert msgs(resp) == [('alert-danger', 'Only SpecItems in state CNF, MOD or NEW can be edited ')]
    item.refresh_from_db()
    assert item.status == status and item.title == 'Title of Item'


def test_edit_invalid_post_rerenders(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='CNS', value='1')
    resp = client.post(item_url('edit_spec_item', 'DataItem', project, item), edit_post(item, dtype, value=''))
    assert resp.status_code == 200
    assert 'value' in resp.context['form'].errors
    item.refresh_from_db()
    assert item.value == '1'


def test_edit_rename_duplicate_rejected(client, owner, project, dvs, dtype):
    make_spec_item(project, domain='Dom', name='Other', p_link=dtype)
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='CNS', value='1')
    resp = client.post(item_url('edit_spec_item', 'DataItem', project, item),
                       edit_post(item, dtype, name='Other'))
    assert resp.status_code == 200
    assert resp.context['form'].errors['name'] == ["Error: Name 'Other' already exists in domain 'Dom'"]


def test_edit_rename_propagates_to_aliases(client, owner, project, dvs, dtype):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='CNS', value='1')
    alias = make_spec_item(project, domain='Dom', name='It', val_set=vs1, p_link=item, title='alias title')
    resp = client.post(item_url('edit_spec_item', 'DataItem', project, item),
                       edit_post(item, dtype, domain='Dom2', name='Renamed'))
    assert resp.status_code == 302
    assert resp.url.endswith('list_spec_items#Dom2:Renamed')
    alias.refresh_from_db()
    assert (alias.domain, alias.name) == ('Dom2', 'Renamed')
    assert alias.title == 'alias title'            # other fields untouched
    assert alias.updated_at == FIXED_TIME         # propagation does not touch updated_at


def test_edit_without_rename_leaves_aliases(client, owner, project, dvs, dtype):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='CNS', value='1')
    alias = make_spec_item(project, domain='Other', name='Alias', val_set=vs1, p_link=item)
    client.post(item_url('edit_spec_item', 'DataItem', project, item), edit_post(item, dtype, title='T2'))
    alias.refresh_from_db()
    assert (alias.domain, alias.name) == ('Other', 'Alias')


def test_edit_with_s_parent_redirects_to_expansion(client, owner, project, dvs):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    ev = make_spec_item(project, cat='EnumValue', domain='E', name='v1', s_link=et, title='t', value='1')
    resp = client.post(item_url('edit_spec_item', 'EnumValue', project, ev) + '?s_parent_id=%d' % et.id,
                       post_data(domain='E', name='v1', title='new', value='2', s_link=et.id, p_kind=''))
    assert resp.status_code == 302
    assert resp.url == ('/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d&expand_link=s_link#E:T'
                        % (project.id, dvs.id, et.id))
    ev.refresh_from_db()
    assert ev.title == 'new'


def test_edit_application_item_title(client, owner, project, dvs):
    app = make_application(project, 'App', cats='InfoItem')
    item = make_spec_item(project, cat='InfoItem', application=app)
    resp = client.get(item_url('edit_spec_item', 'InfoItem', project, item, app=app.id))
    assert resp.context['title'] == 'Edit Info Item in Application App'


# ----------------------------------------------------------------------------
# copy / split
# ----------------------------------------------------------------------------

def test_copy_spec_item(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='VAR', value='1',
                          title='Orig', change_log='old log', status='CNF')
    url = item_url('copy_spec_item', 'DataItem', project, item)
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'spec_item_form.html' in template_names(resp)
    assert resp.context['title'] == 'Copy Data Item in Project Proj'
    resp = client.post(url, post_data(domain='Dom', name='Copy', p_link=dtype.id, p_kind='VAR', value='1'))
    assert resp.status_code == 302
    assert resp.url == '/editor/DataItem/%d/0/%d/Sel_All/0/list_spec_items#Dom:Copy' % (project.id, dvs.id)
    new = SpecItem.objects.get(name='Copy')
    assert new.id != item.id and new.status == 'NEW' and new.owner == owner
    assert new.p_link == dtype and new.val_set == dvs
    item.refresh_from_db()
    assert item.status == 'CNF' and item.name == 'It'


def test_copy_spec_item_duplicate_name(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype)
    resp = client.post(item_url('copy_spec_item', 'DataItem', project, item),
                       post_data(domain='Dom', name='It', p_link=dtype.id))
    assert resp.status_code == 200
    assert resp.context['form'].errors['name'] == ["Error: Name 'It' already exists in domain 'Dom'"]


def test_copy_spec_item_non_default_val_set_redirects_silently(client, owner, project, dvs, dtype):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, val_set=vs1, p_link=dtype)
    resp = client.get(item_url('copy_spec_item', 'DataItem', project, item))
    assert resp.status_code == 302
    assert resp.url == '/editor'
    # KNOWN-ISSUE: copy-unreachable-valset-message
    assert msgs(resp) == []


def test_split_spec_item(client, owner, project, dvs, dtype):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='VAR', value='1', status='CNF')
    url = item_url('split_spec_item', 'DataItem', project, item)
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context['title'] == 'Split Data Item in Project Proj'
    form = resp.context['form']
    assert form.fields['domain'].disabled and form.fields['name'].disabled
    assert [v.name for v in form.fields['val_set'].queryset] == ['Default', 'VS1']
    resp = client.post(url, post_data(domain='Dom', name='It', p_link=dtype.id, p_kind='VAR', value='7',
                                      val_set=vs1.id))
    assert resp.status_code == 302
    assert resp.url == '/editor/DataItem/%d/0/%d/Sel_All/0/list_spec_items#Dom:It' % (project.id, dvs.id)
    new = SpecItem.objects.get(val_set=vs1)
    assert new.p_link == item          # new alias points to the original
    assert new.status == 'NEW' and new.owner == owner
    assert (new.domain, new.name, new.value) == ('Dom', 'It', '7')
    item.refresh_from_db()
    assert item.status == 'CNF' and item.value == '1'


def test_split_same_val_set_rejected(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, value='1')
    resp = client.post(item_url('split_spec_item', 'DataItem', project, item),
                       post_data(domain='Dom', name='It', p_link=dtype.id, val_set=dvs.id))
    assert resp.status_code == 200
    assert resp.context['form'].non_field_errors() == ['Split Error: ValSet is already in use for this domain:name']
    assert SpecItem.objects.filter(p_link=item).count() == 0


@pytest.mark.parametrize('view,text', [('split_spec_item', 'split'), ('del_spec_item', 'deleted')])
def test_split_del_not_allowed_status(client, owner, project, dvs, dtype, view, text):
    item = make_spec_item(project, status='DEL', p_link=dtype)
    resp = client.get(item_url(view, 'DataItem', project, item))
    assert resp.status_code == 302
    assert resp.url == '/editor'
    assert msgs(resp) == [('alert-danger', 'Only SpecItems in state CNF, MOD or NEW can be %s ' % text)]


# ----------------------------------------------------------------------------
# del_spec_item
# ----------------------------------------------------------------------------

def test_del_new_item_hard_deleted_on_post(client, owner, project, dvs, dtype):
    # FIXED: mutation-via-get (was: GET hard-deleted the NEW item) — upstream #86
    item = make_spec_item(project, domain='Dom', name='It', status='NEW', p_link=dtype)
    resp = client.get(item_url('del_spec_item', 'DataItem', project, item, sel_val='Dom'))
    assert resp.status_code == 200      # GET only renders the confirmation form
    assert SpecItem.objects.filter(id=item.id).exists()
    resp = client.post(item_url('del_spec_item', 'DataItem', project, item, sel_val='Dom'))
    assert resp.status_code == 302
    assert resp.url == '/editor/DataItem/%d/0/%d/Dom/0/list_spec_items' % (project.id, dvs.id)
    assert not SpecItem.objects.filter(id=item.id).exists()


def test_del_new_item_removes_aliases(client, owner, project, dvs, dtype):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, status='NEW', p_link=dtype)
    alias = make_spec_item(project, val_set=vs1, p_link=item)
    client.post(item_url('del_spec_item', 'DataItem', project, item))   # FIXED: mutation-via-get (was: GET) — upstream #86
    assert not SpecItem.objects.filter(id__in=[item.id, alias.id]).exists()


def test_del_new_item_in_non_default_val_set_keeps_aliases_untouched(client, owner, project, dvs, dtype):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, val_set=vs1, status='NEW', p_link=dtype)
    client.post(item_url('del_spec_item', 'DataItem', project, item))   # FIXED: mutation-via-get (was: GET) — upstream #86
    assert not SpecItem.objects.filter(id=item.id).exists()


def test_del_new_item_referenced_keeps_item_and_reports_error(client, owner, project, dvs, dtype):
    item = make_spec_item(project, domain='Dom', name='It', status='NEW', p_link=dtype)
    resp = client.post(item_url('del_spec_item', 'DataItem', project, dtype))   # FIXED: mutation-via-get (was: GET) — upstream #86; dtype is referenced by item
    assert resp.status_code == 302
    assert SpecItem.objects.filter(id=dtype.id).exists()
    [(level, text)] = msgs(resp)
    assert level == 'alert-danger'
    assert text.startswith('Failure to delete Types:Int32 (Title of Int32), possibly because other spec_items reference it: ')


def test_del_split_item_alias_form_validates(client, owner, project, dvs, dtype):
    # upstream #99: the p_link of a split alias is the original DataItem, which is outside the normal
    # p_link choices (DataItemType/EnumType); the delete form used to reject it and nothing was deleted
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, domain='Dom', name='It', p_link=dtype, p_kind='CNS', value='1', status='CNF')
    alias = make_spec_item(project, domain='Dom', name='It', val_set=vs1, p_link=item, p_kind='CNS',
                           value='2', status='CNF')
    url = item_url('del_spec_item', 'DataItem', project, alias, sel_val='Dom')
    resp = client.post(url, {'change_log': 'drop alias'})
    assert resp.status_code == 302, resp.context['form'].errors if resp.context else None
    alias.refresh_from_db()
    assert alias.status == 'DEL' and alias.change_log == 'drop alias'
    item.refresh_from_db()
    assert item.status == 'CNF'


@pytest.mark.parametrize('status', ['CNF', 'MOD'])
def test_del_cnf_mod_via_post(client, owner, project, dvs, dtype, status):
    vs1 = make_val_set(project, 'VS1')
    item = make_spec_item(project, domain='Dom', name='It', status=status, p_link=dtype, p_kind='CNS', value='1')
    alias = make_spec_item(project, domain='Dom', name='It', val_set=vs1, p_link=item, status='CNF')
    url = item_url('del_spec_item', 'DataItem', project, item, sel_val='Dom')
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'spec_item_form.html' in template_names(resp)
    assert resp.context['title'] == 'Delete Data Item in Project Proj'
    assert SpecItem.objects.filter(id=item.id, status=status).exists()   # GET does not delete
    editor = make_user('ed')
    make_project_user(project, editor, 'RW')
    client.force_login(editor)
    resp = client.post(url, {'change_log': 'removed because'})
    assert resp.status_code == 302
    assert resp.url == '/editor/DataItem/%d/0/%d/Dom/0/list_spec_items' % (project.id, dvs.id)
    item.refresh_from_db()
    assert item.status == 'DEL' and item.change_log == 'removed because'
    assert item.owner == editor and item.updated_at > FIXED_TIME
    alias.refresh_from_db()
    assert alias.status == 'DEL' and alias.owner == editor and alias.updated_at > FIXED_TIME


def test_del_cnf_post_with_parent_redirect(client, owner, project, dvs):
    et = make_spec_item(project, cat='EnumType', domain='E', name='T')
    ev = make_spec_item(project, cat='EnumValue', domain='E', name='v1', s_link=et, status='CNF', value='1')
    resp = client.post(item_url('del_spec_item', 'EnumValue', project, ev) + '?s_parent_id=%d' % et.id,
                       {'change_log': 'x'})
    assert resp.status_code == 302, resp.context['form'].errors
    assert resp.status_code == 302
    assert resp.url == ('/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d&expand_link=s_link#E:T'
                        % (project.id, dvs.id, et.id))
    ev.refresh_from_db()
    assert ev.status == 'DEL'


# ----------------------------------------------------------------------------
# refresh_spec_item (external FW Profile DB is mocked)
# ----------------------------------------------------------------------------

SVG_NEW = '<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>'


def fake_connect(rows):
    cursor = mock.Mock()
    cursor.fetchall.return_value = rows
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    return mock.patch('editor.ext_cats.mdb.connect', return_value=conn), cursor, conn


def diagram_row(svg=SVG_NEW, name='NewName', kind='Procedure', model_id=77):
    json_rep = '{"globals": {"fwprop": {"smTags": "NewDom"}}}'
    return (model_id, 1, name, 3, kind, datetime(2024, 5, 5, tzinfo=timezone.utc), json_rep, svg, 11, 22)


@pytest.fixture
def model_item(project, dvs):
    app = make_application(project, 'App', cats='Model')
    item = make_spec_item(project, cat='Model', domain='OldDom', name='OldName', application=app, n3=77,
                          value='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>', p_kind='SM', status='NEW')
    return app, item


def refresh_url(project, app, item):
    return item_url('refresh_spec_item', 'Model', project, item, app=app.id, sel_val='Sel_All')


# FIXED: mutation-via-get (was: GET refresh_spec_item overwrote the item from the FW Profile DB):
# all refresh tests below POST.
def test_refresh_changed(client, owner, project, dvs, model_item):
    app, item = model_item
    patcher, cursor, conn = fake_connect([diagram_row()])
    with patcher:
        resp = client.post(refresh_url(project, app, item))
    assert resp.status_code == 302
    assert resp.url == '/editor/Model/%d/%d/%d/Sel_All/0/list_spec_items#NewDom:NewName' % (project.id, app.id, dvs.id)
    cursor.execute.assert_called_once_with('SELECT * FROM diagrams WHERE ID = 77')
    conn.close.assert_called_once_with()
    item.refresh_from_db()
    assert (item.domain, item.name, item.value, item.p_kind) == ('NewDom', 'NewName', SVG_NEW, 'PR')
    assert (item.n1, item.n2, item.n3) == (11, 22, 77)
    assert item.status == 'NEW' and item.owner == owner
    # KNOWN-ISSUE: refresh-timestamp-overwritten
    assert item.updated_at > FIXED_TIME            # view overwrites the external timestamp
    assert msgs(resp) == []


def test_refresh_changed_cnf_creates_obs_copy(client, owner, project, dvs, model_item):
    app, item = model_item
    SpecItem.objects.filter(id=item.id).update(status='CNF')
    patcher, cursor, conn = fake_connect([diagram_row(kind='StateMachine')])
    with patcher:
        client.post(refresh_url(project, app, item))
    item.refresh_from_db()
    assert item.status == 'MOD'
    assert item.value == SVG_NEW and item.p_kind == 'SM'
    assert item.previous.status == 'OBS'


def test_refresh_not_found(client, owner, project, dvs, model_item):
    app, item = model_item
    patcher, cursor, conn = fake_connect([])
    with patcher:
        resp = client.post(refresh_url(project, app, item))
    assert resp.status_code == 302
    assert resp.url == '/editor/Model/%d/%d/%d/Sel_All/0/list_spec_items#OldDom:OldName' % (project.id, app.id, dvs.id)
    assert msgs(resp) == [
        ('alert-warning', 'Model not found in FW Profile Database (its ID is: 77)'),
        ('alert-warning', 'External spec_item no longer exists -- no refresh can be done')]
    item.refresh_from_db()
    assert item.value == '<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>'


def test_refresh_no_change(client, owner, project, dvs, model_item):
    app, item = model_item
    patcher, cursor, conn = fake_connect([diagram_row(svg='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>')])
    with patcher:
        resp = client.post(refresh_url(project, app, item))
    assert resp.status_code == 302
    assert msgs(resp) == [('alert-warning', 'External spec_item has not changed -- no refresh needed')]
    item.refresh_from_db()
    assert (item.domain, item.updated_at, item.owner) == ('OldDom', FIXED_TIME, owner)


def test_refresh_db_error_reports_not_found(client, owner, project, dvs, model_item):
    app, item = model_item
    patcher, cursor, conn = fake_connect([])
    cursor.execute.side_effect = RuntimeError('db down')
    with patcher:
        resp = client.post(refresh_url(project, app, item))
    assert resp.status_code == 302
    assert msgs(resp) == [
        ('alert-danger', 'Error while accessing model with ID "77: db down'),
        ('alert-warning', 'External spec_item no longer exists -- no refresh can be done')]


# ----------------------------------------------------------------------------
# make_project_release / make_application_release
# ----------------------------------------------------------------------------

def test_make_project_release_get(client, owner, project):
    resp = client.get('/editor/%d/make_project_release' % project.id)
    assert resp.status_code == 200
    assert 'make_release.html' in template_names(resp)
    assert resp.context['entity_being_released'] == project
    assert resp.context['releases'] == [project.release]


def test_make_project_release_post(client, owner, project, dvs, dtype):
    app = make_application(project, 'App', cats='InfoItem')
    p_item = make_spec_item(project, domain='D', name='p', status='MOD')
    a_item = make_spec_item(project, cat='InfoItem', domain='D', name='a', application=app, status='NEW')
    obs = make_spec_item(project, domain='D', name='o', status='OBS')
    old_release = project.release
    resp = client.post('/editor/%d/make_project_release' % project.id, {'description': 'First'})
    assert resp.status_code == 302
    assert resp.url == '/editor'
    project.refresh_from_db()
    app.refresh_from_db()
    assert str(project.release) == '1.0' and project.release.desc == 'First'
    assert project.release.previous == old_release
    assert project.release.release_author == owner
    assert str(app.release) == '1.0' and app.release.desc == 'First'
    assert app.release.previous.desc == 'Initial release for application App'
    for obj, status in ((p_item, 'CNF'), (a_item, 'CNF'), (obs, 'OBS'), (dtype, 'CNF')):
        obj.refresh_from_db()
        assert obj.status == status


def test_make_project_release_blank_description_rerenders(client, owner, project):
    resp = client.post('/editor/%d/make_project_release' % project.id, {'description': '   '})
    assert resp.status_code == 200
    assert 'make_release.html' in template_names(resp)
    project.refresh_from_db()
    assert str(project.release) == '0.0'


def test_make_application_release(client, owner, project):
    app = make_application(project, 'App', cats='InfoItem')
    item = make_spec_item(project, cat='InfoItem', application=app, status='NEW')
    url = '/editor/%d/make_application_release' % app.id
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context['entity_being_released'] == app
    resp = client.post(url, {'description': 'App rel'})
    assert resp.status_code == 302
    assert resp.url == '/editor'
    app.refresh_from_db()
    item.refresh_from_db()
    assert str(app.release) == '0.1' and app.release.desc == 'App rel'
    assert item.status == 'CNF'
    project.refresh_from_db()
    assert str(project.release) == '0.0'
