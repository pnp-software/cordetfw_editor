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


# =============================================================================================
# Step B: refresh_spec_item and edit_project's member add/role change (user_id / role)
# =============================================================================================
from datetime import datetime, timezone
from unittest import mock

from tests.factories import make_application, make_spec_item


def model_setup():
    s = Setup()
    app = make_application(s.w.project, 'ModApp', cats='Model')
    item = make_spec_item(s.w.project, cat='Model', domain='OldDom', name='OldName', application=app,
                          n3=77, value='<svg>old</svg>', p_kind='SM', status='NEW')
    url = f'/editor/Model/{s.pid}/{app.id}/{item.id}/Sel_All/0/refresh_spec_item'
    return s, app, item, url


def fake_connect(rows):
    cursor = mock.Mock()
    cursor.fetchall.return_value = rows
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    return mock.patch('editor.ext_cats.mdb.connect', return_value=conn)


ROW = (77, 1, 'NewName', 3, 'Procedure', datetime(2024, 5, 5, tzinfo=timezone.utc),
       '{"globals": {"fwprop": {"smTags": "NewDom"}}}', '<svg>new</svg>', 11, 22)


@pytest.mark.parametrize('role', ['owner', 'ro', 'rw', 'unrelated', 'staff'])
def test_refresh_get_is_405_and_never_touches_the_fw_profile_db(client, role):
    s, app, item, url = model_setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    with fake_connect([ROW]) as connect:
        assert client.get(url).status_code == 405
    connect.assert_not_called()
    assert db_snapshot() == before


def test_refresh_get_anonymous_redirects_to_login(client):
    s, app, item, url = model_setup()
    before = db_snapshot()
    login_redirect(client.get(url), url)
    assert db_snapshot() == before


@pytest.mark.parametrize('role', ['owner', 'rw'])
def test_refresh_post_by_writer_refreshes(client, role):
    s, app, item, url = model_setup()
    client.force_login(s.w.user(role))
    with fake_connect([ROW]):
        response = client.post(url)
    assert response.status_code == 302
    item.refresh_from_db()
    assert (item.domain, item.name, item.value) == ('NewDom', 'NewName', '<svg>new</svg>')


@pytest.mark.parametrize('role', ['ro', 'unrelated', 'staff'])
def test_refresh_post_refused_for_non_writers(client, role):
    s, app, item, url = model_setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    with fake_connect([ROW]) as connect:
        response = client.post(url)
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_WRITE]
    connect.assert_not_called()
    assert db_snapshot() == before


def test_refresh_post_anonymous_and_csrf(client):
    s, app, item, url = model_setup()
    before = db_snapshot()
    with fake_connect([ROW]) as connect:
        login_redirect(client.post(url), url)
        assert csrf_client(s.w.owner).post(url).status_code == 403
    connect.assert_not_called()
    assert db_snapshot() == before


def test_refresh_control_is_a_post_form_with_csrf_token(client):
    s, app, item, url = model_setup()
    client.force_login(s.w.owner)
    vs = s.vs
    html = client.get(f'/editor/Model/{s.pid}/{app.id}/{vs}/Sel_All/0/list_spec_items').content.decode()
    assert f'href="{url}"' not in html
    form = html[:html.index('title="Refresh')].rsplit('<form', 1)[1]
    assert f'action="{url}"' in form and 'method="post"' in form and 'csrfmiddlewaretoken' in form


# ------------------------------------------------------------------ edit_project: add member / change role

def add_member_setup():
    s = Setup()
    newbie = make_user('newbie')
    return s, newbie


def test_add_member_via_get_changes_nothing(client):
    s, newbie = add_member_setup()
    client.force_login(s.w.staff)
    before = db_snapshot()
    response = client.get(s.url('edit_project'), {'user_id': newbie.id, 'role': 'RW'})
    assert response.status_code == 200
    assert db_snapshot() == before


@pytest.mark.parametrize('role', ['RO', 'RW'])
def test_add_member_via_post_and_change_role(client, role):
    s, newbie = add_member_setup()
    client.force_login(s.w.staff)
    response = client.post(s.url('edit_project'), {'user_id': newbie.id, 'role': role})
    assert response.status_code == 302 and response['Location'] == s.url('edit_project')
    assert ProjectUser.objects.get(project_id=s.pid, user=newbie).role == role
    other = 'RO' if role == 'RW' else 'RW'
    client.post(s.url('edit_project'), {'user_id': newbie.id, 'role': other})
    assert ProjectUser.objects.get(project_id=s.pid, user=newbie).role == other
    assert ProjectUser.objects.filter(project_id=s.pid, user=newbie).count() == 1


@pytest.mark.parametrize('bad', [{'role': 'ADMIN'}, {'role': ''}, {'role': 'rw'}, {}])
def test_add_member_invalid_role_is_an_error_without_write(client, bad):
    s, newbie = add_member_setup()
    client.force_login(s.w.staff)
    before = db_snapshot()
    response = client.post(s.url('edit_project'), {'user_id': newbie.id, **bad})
    assert response.status_code == 302 and response['Location'] == s.url('edit_project')
    [(level, text)] = [(m.level_tag, m.message) for m in response.wsgi_request._messages]
    assert level == 'alert-danger' and text.startswith('Invalid role ') and text.endswith(': it must be RO or RW')
    assert db_snapshot() == before


@pytest.mark.parametrize('bad_user', ['999999', 'abc', ''])
def test_add_member_invalid_user_is_an_error_without_write(client, bad_user):
    s, newbie = add_member_setup()
    client.force_login(s.w.staff)
    before = db_snapshot()
    response = client.post(s.url('edit_project'), {'user_id': bad_user, 'role': 'RW'})
    assert response.status_code == 302
    assert msgs(response.wsgi_request) == [f'Invalid user: {bad_user!r}']
    assert db_snapshot() == before


@pytest.mark.parametrize('role', NON_STAFF)
def test_add_member_post_refused_for_non_staff(client, role):
    s, newbie = add_member_setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    response = client.post(s.url('edit_project'), {'user_id': newbie.id, 'role': 'RW'})
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_STAFF]
    assert db_snapshot() == before


def test_add_member_post_anonymous_and_csrf(client):
    s, newbie = add_member_setup()
    before = db_snapshot()
    data = {'user_id': newbie.id, 'role': 'RW'}
    login_redirect(client.post(s.url('edit_project'), data), s.url('edit_project'))
    assert csrf_client(s.w.staff).post(s.url('edit_project'), data).status_code == 403
    assert db_snapshot() == before


def test_add_member_menu_items_are_post_forms_with_csrf_token(client):
    s, newbie = add_member_setup()
    client.force_login(s.w.staff)
    html = client.get(s.url('edit_project')).content.decode()
    assert '?user_id=' not in html
    for role in ('RW', 'RO'):
        marker = f'name="user_id" value="{newbie.id}">\n                                        <input type="hidden" name="role" value="{role}"'
        form = html[:html.index(marker)].rsplit('<form', 1)[1]
        assert 'method="post"' in form and 'csrfmiddlewaretoken' in form


# ------------------------------------------------------------------ nothing mutates on GET, anywhere

def test_no_get_request_changes_the_database(client):
    """Every project/application/item URL, with every mutating query parameter that used to work."""
    from tests.test_access import ENDPOINTS
    s = Setup()
    member = make_user('member')
    pu = make_project_user(s.w.project, member, 'RO')
    vs = make_val_set(s.w.project, 'VS1')
    client.force_login(s.w.superuser)
    before = db_snapshot()
    params = {'user_id': member.id, 'role': 'RW', 'del_user_id': pu.id, 'del_val_set_id': vs.id,
              'export': 'csv'}
    with fake_connect([ROW]) as connect:
        for endpoint in sorted(ENDPOINTS):
            if endpoint.startswith('export_'):
                continue            # streaming responses, covered by the access matrix
            response = client.get(s.url(endpoint), params)
            assert response.status_code in (200, 302, 405), endpoint
            assert db_snapshot() == before, endpoint
    connect.assert_not_called()
