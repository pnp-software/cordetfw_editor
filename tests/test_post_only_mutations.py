"""Task 6.3, mutation-via-get: no state change on a GET request.

Upstream #86 plus the follow-ups: delete, refresh and member/ValSet actions are POST-only
(del_project, edit_project's user_id / del_user_id / del_val_set_id, del_spec_item for NEW items,
refresh_spec_item).
GET behaviour as implemented:
  * del_project                      -> 405 (require_POST), nothing changes
  * edit_project?del_*=...           -> 200 edit page, the parameter is ignored
  * del_spec_item (any status)       -> 200 confirmation form, nothing changes
"""
import tempfile

import pytest
from django.core.signals import request_finished
from django.db import close_old_connections
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
    form = html[html.index(f'<form id="del-project-{s.pid}"'):]
    form = form[:form.index('</form>')]
    assert f'action="/editor/{s.pid}/del_project"' in form
    assert 'method="post"' in form and 'csrfmiddlewaretoken' in form

    client.force_login(s.w.owner)
    html = client.get(f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item').content.decode()
    assert 'data-confirm-message=' in html
    form = html[:html.index('</form>', html.index('data-confirm-message='))]
    form = form.rsplit('<form', 1)[1]
    assert 'data-confirm-message=' in form
    assert 'method="post"' in form and 'csrfmiddlewaretoken' in form


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
                          n3=77, value='<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>', p_kind='SM', status='NEW')
    url = f'/editor/Model/{s.pid}/{app.id}/{item.id}/Sel_All/0/refresh_spec_item'
    return s, app, item, url


def fake_connect(rows):
    cursor = mock.Mock()
    cursor.fetchall.return_value = rows
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    return mock.patch('editor.ext_cats.mdb.connect', return_value=conn)


ROW = (77, 1, 'NewName', 3, 'Procedure', datetime(2024, 5, 5, tzinfo=timezone.utc),
       '{"globals": {"fwprop": {"smTags": "NewDom"}}}', '<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>', 11, 22)


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
    assert (item.domain, item.name, item.value) == ('NewDom', 'NewName', '<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>')


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

def test_edit_project_old_member_links_warn_and_change_nothing(client):
    s, pu, vs = project_with_member_and_valset()
    client.force_login(s.w.staff)
    before = db_snapshot()
    for params in ({'user_id': pu.user_id, 'role': 'RW'}, {'del_user_id': pu.id},
                   {'del_val_set_id': vs.id}):
        response = client.get(s.url('edit_project'), params)
        assert response.status_code == 200
        assert response.context['messages'] and \
            [m.message for m in response.context['messages']] == \
            ['This link no longer changes the project. Use the buttons on this page.']
        assert db_snapshot() == before
    # a plain visit shows no warning
    response = client.get(s.url('edit_project'))
    assert not [m.message for m in response.context['messages']]


def test_confirm_delete_script_is_served_and_does_not_fail_open():
    from django.contrib.staticfiles import finders
    path = finders.find('confirm-delete.js')
    assert path
    with open(path, encoding='utf-8') as f:
        js = f.read()
    assert "typeof bootstrap === 'undefined'" in js or "typeof bootstrap !== 'undefined'" in js
    assert 'window.confirm(form.dataset.confirmMessage)' in js
    assert 'HTMLFormElement.prototype.submit.call(form)' in js
    assert "typeof form.requestSubmit === 'function'" in js


def test_project_delete_button_sits_directly_in_the_button_group(client):
    s = Setup()
    client.force_login(s.w.staff)
    html = client.get('/editor/').content.decode()
    group = html[html.index('aria-label="project controls"'):]
    group = group[:group.index('</div>')]
    assert f'form="del-project-{s.pid}"' in group and '<form' not in group
    form = html[html.index(f'<form id="del-project-{s.pid}"'):]
    form = form[:form.index('</form>')]
    assert f'action="/editor/{s.pid}/del_project"' in form
    assert 'method="post"' in form and 'csrfmiddlewaretoken' in form
    assert 'data-confirm-message="Are you sure you want to delete this project?"' in form


def test_no_get_request_changes_the_database(client):
    """Every project/application/item URL, with every mutating query parameter that used to work.

    Run as roles that get PAST the access check (owner = writer; a staff user who is also an RW
    member), with a NEW item for del_spec_item and a Model item for refresh_spec_item, and the FW
    Profile DB mocked so that a mutation would happen if GET were allowed.
    """
    from tests.test_access import ENDPOINTS
    s, app, model_item, refresh_url = model_setup()
    member = make_user('member')
    pu = make_project_user(s.w.project, member, 'RO')
    vs = make_val_set(s.w.project, 'VS1')
    staff_member = make_user('staffmember', is_staff=True)
    make_project_user(s.w.project, staff_member, 'RW')
    params = {'user_id': member.id, 'role': 'RW', 'del_user_id': pu.id, 'del_val_set_id': vs.id,
              'export': 'csv'}
    urls = {e: s.url(e) for e in ENDPOINTS}
    urls['del_spec_item'] = f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item'
    urls['refresh_spec_item'] = refresh_url
    reached = set()
    for user in (s.w.owner, staff_member):
        client.force_login(user)
        before = db_snapshot()
        with fake_connect([ROW]) as connect, mock.patch(
                'editor.views.make_temp_dir',
                side_effect=lambda d, n, request=None: tempfile.mkdtemp(prefix=n, dir=d)):    # request param added by temp-dir-collision fix
            for endpoint in sorted(urls):
                response = client.get(urls[endpoint], params)
                assert response.status_code in (200, 302, 405), endpoint
                if response.status_code == 200:
                    reached.add(endpoint)
                if response.streaming:
                    # like Django's test client: closing must not close the test's DB connection
                    request_finished.disconnect(close_old_connections)
                    try:
                        response.close()
                    finally:
                        request_finished.connect(close_old_connections)
                assert db_snapshot() == before, (user.username, endpoint)
        connect.assert_not_called()
    # the sweep really got past the access checks of the mutating endpoints
    assert {'del_spec_item', 'edit_project', 'export_project', 'export_spec_items'} <= reached
