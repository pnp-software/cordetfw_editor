"""Task 6.3, mutation-via-get: no state change on a GET request.

Step A (upstream #86): the delete actions are POST-only (del_project, edit_project's
del_user_id / del_val_set_id, del_spec_item for NEW items).
GET behaviour as implemented:
  * del_project                      -> 405 (require_POST), nothing changes
  * edit_project?del_*=...           -> 200 edit page, the parameter is ignored
  * del_spec_item (any status)       -> 200 confirmation form, nothing changes
"""
import pytest
from django.test import Client

from editor.models import Project, ProjectUser, SpecItem, ValSet
from tests.factories import make_project_user, make_val_set, make_user
from tests.test_access import (MSG_STAFF, MSG_WRITE, Setup, db_snapshot, msgs)

pytestmark = pytest.mark.django_db

NON_STAFF = ['owner', 'ro', 'rw', 'unrelated']


def csrf_client(user=None):
    c = Client(enforce_csrf_checks=True)
    if user is not None:
        c.force_login(user)
    return c


def login_redirect(response, url):
    assert response.status_code == 302
    assert response['Location'] == '/accounts/login/?next=' + url


# ------------------------------------------------------------------ del_project

@pytest.mark.parametrize('role', ['owner', 'ro', 'rw', 'unrelated', 'staff', 'superuser'])
def test_del_project_get_is_405_and_changes_nothing(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    assert client.get(s.url('del_project')).status_code == 405
    assert db_snapshot() == before


def test_del_project_get_anonymous_redirects_to_login(client):
    s = Setup()
    before = db_snapshot()
    login_redirect(client.get(s.url('del_project')), s.url('del_project'))
    assert db_snapshot() == before


@pytest.mark.parametrize('role', ['staff', 'superuser'])
def test_del_project_post_by_staff_deletes(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    response = client.post(s.url('del_project'))
    assert response.status_code == 302 and response['Location'] == '/editor'
    assert not Project.objects.filter(id=s.pid).exists()


@pytest.mark.parametrize('role', NON_STAFF)
def test_del_project_post_refused_for_non_staff(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    response = client.post(s.url('del_project'))
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_STAFF]
    assert db_snapshot() == before


def test_del_project_post_anonymous_redirects_to_login(client):
    s = Setup()
    before = db_snapshot()
    login_redirect(client.post(s.url('del_project')), s.url('del_project'))
    assert db_snapshot() == before


def test_del_project_post_without_csrf_token_is_403(db):
    s = Setup()
    c = csrf_client(s.w.staff)
    before = db_snapshot()
    assert c.post(s.url('del_project')).status_code == 403
    assert db_snapshot() == before


# ------------------------------------------------------------------ edit_project deletes

def project_with_member_and_valset():
    s = Setup()
    member = make_user('member')
    pu = make_project_user(s.w.project, member, 'RO')
    vs = make_val_set(s.w.project, 'VS1')
    return s, pu, vs


@pytest.mark.parametrize('param', ['del_user_id', 'del_val_set_id'])
def test_edit_project_delete_params_on_get_change_nothing(client, param):
    s, pu, vs = project_with_member_and_valset()
    client.force_login(s.w.staff)
    before = db_snapshot()
    response = client.get(s.url('edit_project'), {param: pu.id if param == 'del_user_id' else vs.id})
    assert response.status_code == 200
    assert db_snapshot() == before


def test_edit_project_post_del_user_by_staff(client):
    s, pu, vs = project_with_member_and_valset()
    client.force_login(s.w.staff)
    response = client.post(s.url('edit_project'), {'del_user_id': pu.id})
    assert response.status_code == 302 and response['Location'] == s.url('edit_project')
    assert not ProjectUser.objects.filter(id=pu.id).exists()
    assert ValSet.objects.filter(id=vs.id).exists()


def test_edit_project_post_del_val_set_by_staff(client):
    s, pu, vs = project_with_member_and_valset()
    client.force_login(s.w.staff)
    response = client.post(s.url('edit_project'), {'del_val_set_id': vs.id})
    assert response.status_code == 302 and response['Location'] == s.url('edit_project')
    assert not ValSet.objects.filter(id=vs.id).exists()
    assert ProjectUser.objects.filter(id=pu.id).exists()


@pytest.mark.parametrize('role', NON_STAFF)
@pytest.mark.parametrize('param', ['del_user_id', 'del_val_set_id'])
def test_edit_project_post_delete_refused_for_non_staff(client, role, param):
    s, pu, vs = project_with_member_and_valset()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    response = client.post(s.url('edit_project'), {param: pu.id if param == 'del_user_id' else vs.id})
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_STAFF]
    assert db_snapshot() == before


@pytest.mark.parametrize('param', ['del_user_id', 'del_val_set_id'])
def test_edit_project_post_delete_anonymous_and_csrf(client, param):
    s, pu, vs = project_with_member_and_valset()
    value = pu.id if param == 'del_user_id' else vs.id
    before = db_snapshot()
    login_redirect(client.post(s.url('edit_project'), {param: value}), s.url('edit_project'))
    assert csrf_client(s.w.staff).post(s.url('edit_project'), {param: value}).status_code == 403
    assert db_snapshot() == before


# ------------------------------------------------------------------ del_spec_item (NEW items)

@pytest.mark.parametrize('role', ['owner', 'rw'])
def test_del_new_spec_item_post_by_writer_deletes(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    response = client.post(f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item')
    assert response.status_code == 302
    assert response['Location'] == f'/editor/DataItem/{s.pid}/0/{s.vs}/Sel_All/0/list_spec_items'
    assert not SpecItem.objects.filter(id=s.new_item.id).exists()
    assert SpecItem.objects.filter(id=s.item.id).exists()


@pytest.mark.parametrize('status_item', ['item', 'new_item'])
def test_del_spec_item_get_shows_confirmation_and_changes_nothing(client, status_item):
    s = Setup()
    client.force_login(s.w.owner)
    item = getattr(s, status_item)
    before = db_snapshot()
    response = client.get(f'/editor/DataItem/{s.pid}/0/{item.id}/Sel_All/0/del_spec_item')
    assert response.status_code == 200
    assert response.context['confirm_delete'] is True
    assert db_snapshot() == before


@pytest.mark.parametrize('role', ['ro', 'unrelated', 'staff'])
def test_del_new_spec_item_post_refused(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    response = client.post(f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item')
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_WRITE]
    assert db_snapshot() == before


def test_del_new_spec_item_post_anonymous_and_csrf(client):
    s = Setup()
    url = f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item'
    before = db_snapshot()
    login_redirect(client.post(url), url)
    assert csrf_client(s.w.owner).post(url).status_code == 403
    assert db_snapshot() == before


# ------------------------------------------------------------------ rendered forms carry a CSRF token

def test_delete_forms_render_csrf_token_and_post_method(client):
    s, pu, vs = project_with_member_and_valset()
    client.force_login(s.w.staff)

    html = client.get(s.url('edit_project')).content.decode()
    for name in ('del_user_id', 'del_val_set_id'):
        form = html[:html.index(f'name="{name}"')].rsplit('<form', 1)[1]
        assert 'method="post"' in form and 'csrfmiddlewaretoken' in form
    assert '?del_user_id=' not in html and '?del_val_set_id=' not in html

    html = client.get('/editor/').content.decode()
    form = html[:html.index('Delete Proj Project')].rsplit('<form', 1)[1]
    assert f'action="/editor/{s.pid}/del_project"' in form
    assert 'method="post"' in form and 'csrfmiddlewaretoken' in form

    client.force_login(s.w.owner)
    html = client.get(f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item').content.decode()
    assert 'data-confirm-message=' in html
    form = html[html.index('data-confirm-message=') - 40:]
    assert 'csrfmiddlewaretoken' in form
