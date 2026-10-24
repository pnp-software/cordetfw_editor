"""Characterization tests for editor/access.py and the access matrix at HTTP level."""
from unittest import mock

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from editor import access
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from tests.factories import (default_val_set, make_application, make_project, make_project_user,
                             make_spec_item, make_user)

pytestmark = pytest.mark.django_db

MSG_OWNER = 'This operation is only accessible to the owner of project Proj'
MSG_READ = 'This operation requires read access to project Proj'
MSG_WRITE = 'This operation requires read/write access to project Proj'
MSG_STAFF = 'This operation is only accessible to a staff user'

ROLES = ['anonymous', 'owner', 'ro', 'rw', 'unrelated', 'staff', 'superuser']


class World:
    """Project 'Proj' (owner) with an RO and an RW user, plus unrelated/staff/superuser users."""

    def __init__(self):
        self.owner = make_user('owner')
        self.ro = make_user('ro')
        self.rw = make_user('rw')
        self.unrelated = make_user('unrelated')
        self.staff = make_user('staff', is_staff=True)
        self.superuser = make_user('superuser', is_staff=True, is_superuser=True)
        self.project = make_project(self.owner, name='Proj')
        make_project_user(self.project, self.ro, 'RO')
        make_project_user(self.project, self.rw, 'RW')

    def user(self, role):
        return AnonymousUser() if role == 'anonymous' else getattr(self, role)


@pytest.fixture
def world():
    return World()


def make_request(user):
    request = RequestFactory().get('/')
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def msgs(request):
    return [m.message for m in get_messages(request)]


# ------------------------------------------------------------------ unit tests of helpers

@pytest.mark.parametrize('role,allowed', [
    ('anonymous', False), ('owner', True), ('ro', False), ('rw', False),
    ('unrelated', False), ('staff', False), ('superuser', False)])
def test_is_project_owner(world, role, allowed):
    request = make_request(world.user(role))
    assert access.is_project_owner(request, world.project) is allowed
    assert msgs(request) == ([] if allowed else [MSG_OWNER])


@pytest.mark.parametrize('role,allowed', [
    ('anonymous', False), ('owner', True), ('ro', True), ('rw', True),
    ('unrelated', False), ('staff', False), ('superuser', False)])
def test_has_read_access_to_project(world, role, allowed):
    request = make_request(world.user(role))
    assert access.has_read_access_to_project(request, world.project) is allowed
    assert msgs(request) == ([] if allowed else [MSG_READ])


@pytest.mark.parametrize('role,allowed', [
    ('anonymous', False), ('owner', True), ('ro', False), ('rw', True),
    ('unrelated', False), ('staff', False), ('superuser', False)])
def test_has_write_access_to_project(world, role, allowed):
    request = make_request(world.user(role))
    assert access.has_write_access_to_project(request, world.project) is allowed
    assert msgs(request) == ([] if allowed else [MSG_WRITE])


@pytest.mark.parametrize('func', [access.can_create_project, access.can_repair, access.can_add_val_set])
@pytest.mark.parametrize('role,allowed', [
    ('anonymous', False), ('owner', False), ('ro', False), ('rw', False),
    ('unrelated', False), ('staff', True), ('superuser', True)])
def test_staff_only_helpers(world, func, role, allowed):
    request = make_request(world.user(role))
    assert func(request) is allowed
    assert msgs(request) == ([] if allowed else [MSG_STAFF])


def test_staff_flag_alone_grants_no_project_access(world):
    """Staff/superuser who are neither owner nor ProjectUser get no project access at all."""
    for role in ('staff', 'superuser'):
        request = make_request(world.user(role))
        assert access.has_read_access_to_project(request, world.project) is False
        assert access.has_write_access_to_project(request, world.project) is False
        assert msgs(request) == [MSG_READ, MSG_WRITE]


def test_staff_who_is_project_user_follows_role(world):
    make_project_user(world.project, world.staff, 'RW')
    request = make_request(world.staff)
    assert access.has_read_access_to_project(request, world.project) is True
    assert access.has_write_access_to_project(request, world.project) is True
    assert msgs(request) == []


def test_write_access_any_rw_project_user_row_wins(world):
    """access-first-row (operator decision 2026-10-24): a user with duplicate ProjectUser rows
    has write access if ANY row is RW, whatever the row order."""
    dup = make_user('dup')
    make_project_user(world.project, dup, 'RO')   # lower id
    make_project_user(world.project, dup, 'RW')
    request = make_request(dup)
    # FIXED: access-first-row (was: False with MSG_WRITE, the first row (RO) decided)
    assert access.has_write_access_to_project(request, world.project) is True
    assert msgs(request) == []
    assert access.has_read_access_to_project(make_request(dup), world.project) is True


def test_write_access_duplicate_ro_rows_denied(world):
    dup = make_user('dup2')
    make_project_user(world.project, dup, 'RO')
    make_project_user(world.project, dup, 'RO')
    request = make_request(dup)
    assert access.has_write_access_to_project(request, world.project) is False
    assert msgs(request) == [MSG_WRITE]


def test_write_access_rw_first_then_ro_still_allowed(world):
    dup = make_user('dup3')
    make_project_user(world.project, dup, 'RW')
    make_project_user(world.project, dup, 'RO')
    assert access.has_write_access_to_project(make_request(dup), world.project) is True


def test_access_is_per_project(world):
    other = make_project(world.unrelated, name='Other')
    request = make_request(world.rw)
    assert access.has_write_access_to_project(request, other) is False
    assert access.has_read_access_to_project(request, other) is False
    assert msgs(request) == ['This operation requires read/write access to project Other',
                             'This operation requires read access to project Other']


def test_owner_has_access_without_project_user_row(world):
    assert not ProjectUser.objects.filter(user=world.owner).exists()
    request = make_request(world.owner)
    assert access.has_write_access_to_project(request, world.project) is True
    assert access.has_read_access_to_project(request, world.project) is True
    assert msgs(request) == []


# ------------------------------------------------------------------ HTTP matrix

class Setup:
    def __init__(self):
        self.w = World()
        p = self.w.project
        self.pid = p.id
        self.vs = default_val_set(p).id
        self.app = make_application(p, name='App', cats='Model')
        self.item = make_spec_item(p, name='Cnf', status='CNF')
        self.new_item = make_spec_item(p, name='NewOne', status='NEW')

    def url(self, key):
        p, i = self.pid, self.item.id
        return {
            'edit_project': f'/editor/{p}/edit_project',
            'del_project': f'/editor/{p}/del_project',
            'export_project': f'/editor/{p}/export_project',
            'make_project_release': f'/editor/{p}/make_project_release',
            'add_val_set': f'/editor/{p}/add_val_set',
            'add_application': f'/editor/{p}/add_application',
            'edit_application': f'/editor/{self.app.id}/edit_application',
            'make_application_release': f'/editor/{self.app.id}/make_application_release',
            'list_spec_items': f'/editor/DataItem/{p}/0/{self.vs}/Sel_All/0/list_spec_items',
            'list_spec_item_history': f'/editor/DataItem/{p}/0/{i}/Sel_All/list_spec_item_history',
            'add_spec_item': f'/editor/DataItem/{p}/0/Sel_All/0/add_spec_item',
            'edit_spec_item': f'/editor/DataItem/{p}/0/{i}/Sel_All/0/edit_spec_item',
            'copy_spec_item': f'/editor/DataItem/{p}/0/{i}/Sel_All/0/copy_spec_item',
            'split_spec_item': f'/editor/DataItem/{p}/0/{i}/Sel_All/0/split_spec_item',
            'del_spec_item': f'/editor/DataItem/{p}/0/{i}/Sel_All/0/del_spec_item',
            'refresh_spec_item': f'/editor/DataItem/{p}/0/{i}/Sel_All/0/refresh_spec_item',
            'export_spec_items': f'/editor/DataItem/{p}/0/{self.vs}/Sel_All/0/export_spec_items',
            'import_spec_items': f'/editor/DataItem/{p}/0/{self.vs}/Sel_All/import_spec_items',
        }[key]


OWNER = {'owner'}
STAFF = {'staff', 'superuser'}
READERS = {'owner', 'ro', 'rw'}
WRITERS = {'owner', 'rw'}

# endpoint -> (roles that pass the access check, message shown to the others)
ENDPOINTS = {
    'edit_project': (STAFF, MSG_STAFF),
    'del_project': (STAFF, MSG_STAFF),
    'export_project': (READERS, MSG_READ),
    'make_project_release': (OWNER, MSG_OWNER),
    'add_val_set': (STAFF, MSG_STAFF),
    'add_application': (OWNER, MSG_OWNER),
    'edit_application': (OWNER, MSG_OWNER),
    'make_application_release': (OWNER, MSG_OWNER),
    'list_spec_items': (READERS, MSG_READ),
    'list_spec_item_history': (READERS, MSG_READ),
    'add_spec_item': (WRITERS, MSG_WRITE),
    'edit_spec_item': (WRITERS, MSG_WRITE),
    'copy_spec_item': (WRITERS, MSG_WRITE),
    'split_spec_item': (WRITERS, MSG_WRITE),
    'del_spec_item': (WRITERS, MSG_WRITE),
    'refresh_spec_item': (WRITERS, MSG_WRITE),
    'export_spec_items': (READERS, MSG_READ),
    'import_spec_items': (WRITERS, MSG_WRITE),
}

def db_snapshot():
    return {m.__name__: sorted(m.objects.values_list(*[f.attname for f in m._meta.concrete_fields]),
                               key=repr)
            for m in (Project, ProjectUser, Application, Release, ValSet, SpecItem)}


def do_get(client, url):
    with mock.patch('editor.ext_cats.mdb.connect', side_effect=RuntimeError('no network in tests')):
        return client.get(url)


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('endpoint', sorted(ENDPOINTS))
def test_access_matrix_get(client, endpoint, role):
    s = Setup()
    allowed_roles, deny_msg = ENDPOINTS[endpoint]
    if role != 'anonymous':
        client.force_login(s.w.user(role))
    before = db_snapshot()
    response = do_get(client, s.url(endpoint))
    url = s.url(endpoint)

    if role == 'anonymous':
        # @login_required: redirected to the login page
        assert response.status_code == 302
        assert response['Location'] == '/editor/login/?next=' + url
        assert db_snapshot() == before
        return

    if endpoint in ('del_project', 'refresh_spec_item'):
        # FIXED: mutation-via-get (was: GET deleted the project for staff / refreshed the item
        # from the FW Profile DB) — upstream #86 / Task 6.3. Only POST is accepted; every
        # logged-in role gets 405 and nothing changes.
        assert response.status_code == 405
        assert db_snapshot() == before
        return

    if role in allowed_roles:
        if endpoint == 'export_project':
            assert response.status_code == 200
            assert response.streaming
            assert response['Content-Type'] == 'application/zip'
            response.close()
        elif endpoint == 'export_spec_items':
            assert response.status_code == 200
            assert response['Content-Disposition'] == 'attachment; filename= "ProjDataItem.csv"'
            assert db_snapshot() == before
        else:
            assert response.status_code == 200
            assert db_snapshot() == before
    else:
        assert response.status_code == 302
        assert response['Location'] == '/editor'
        assert msgs(response.wsgi_request) == [deny_msg]
        assert db_snapshot() == before


@pytest.mark.parametrize('role', ROLES)
def test_access_matrix_post_refresh_spec_item(client, role):
    s = Setup()
    if role != 'anonymous':
        client.force_login(s.w.user(role))
    before = db_snapshot()
    url = s.url('refresh_spec_item')
    with mock.patch('editor.ext_cats.mdb.connect', side_effect=RuntimeError('no network in tests')):
        response = client.post(url)
    if role == 'anonymous':
        assert response.status_code == 302
        assert response['Location'] == '/editor/login/?next=' + url
    elif role in WRITERS:
        # FW Profile DB unreachable -> NOT_FOUND outcome -> redirect to the item in the list
        assert response.status_code == 302
        assert response['Location'] == (f'/editor/DataItem/{s.pid}/0/{s.vs}/Sel_All/0/'
                                        'list_spec_items#Dom:Cnf')
        assert msgs(response.wsgi_request)[0].startswith('Unable to connect to the FW Profile database')
    else:
        assert response.status_code == 302
        assert response['Location'] == '/editor'
        assert msgs(response.wsgi_request) == [MSG_WRITE]
    assert db_snapshot() == before


def test_export_spec_items_content(client):
    s = Setup()
    client.force_login(s.w.owner)
    response = client.get(s.url('export_spec_items'))
    assert response['Content-Type'] == 'text/plain'
    assert response['Content-Disposition'] == 'attachment; filename= "ProjDataItem.csv"'
    assert response.content.decode().startswith('Domain|Name|')


def test_import_spec_items_requires_login(client):
    s = Setup()
    before = db_snapshot()
    response = client.get(s.url('import_spec_items'))
    assert response.status_code == 302
    # FIXED: import-no-login-required (was: 302 to /editor with the write-access message)
    assert response['Location'] == '/editor/login/?next=' + s.url('import_spec_items')
    assert db_snapshot() == before


def test_import_spec_items_anonymous_post_does_not_import(client, tmp_path):
    from django.core.files.uploadedfile import SimpleUploadedFile
    s = Setup()
    before = db_snapshot()
    f = SimpleUploadedFile('x.csv', b'a|b\n1|2\n')
    response = client.post(s.url('import_spec_items'), {'upload_file': f})
    assert response.status_code == 302
    # FIXED: import-no-login-required (was: 302 to /editor)
    assert response['Location'] == '/editor/login/?next=' + s.url('import_spec_items')
    assert db_snapshot() == before


@pytest.mark.parametrize('role', ['owner', 'ro', 'rw', 'unrelated', 'staff', 'superuser'])
def test_add_val_set_post_denied_for_non_staff_and_allowed_for_staff(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    response = client.post(f'/editor/{s.pid}/add_val_set', {'name': 'NewVS', 'description': 'd'})
    assert response.status_code == 302
    if role in STAFF:
        assert response['Location'] == f'/editor/{s.pid}/edit_project'
        assert ValSet.objects.filter(project_id=s.pid, name='NewVS').count() == 1
    else:
        assert response['Location'] == '/editor'
        assert msgs(response.wsgi_request) == [MSG_STAFF]
        assert db_snapshot() == before


def test_del_project_denied_for_owner_non_staff(client):
    """The owner of a project cannot delete it unless also staff."""
    s = Setup()
    client.force_login(s.w.owner)
    before = db_snapshot()
    # FIXED: mutation-via-get (was: GET) — upstream #86
    assert client.get(s.url('del_project')).status_code == 405
    response = client.post(s.url('del_project'))
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_STAFF]
    assert db_snapshot() == before


@pytest.mark.parametrize('role', ['ro', 'unrelated', 'staff'])
def test_del_new_spec_item_get_denied_keeps_item(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    url = f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item'
    response = client.get(url)
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_WRITE]
    assert SpecItem.objects.filter(id=s.new_item.id).exists()


@pytest.mark.parametrize('role', ['owner', 'rw'])
def test_del_new_spec_item_by_writer_needs_post(client, role):
    """FIXED: mutation-via-get (was: a plain GET deleted a NEW item immediately) — upstream #86.
    GET renders the confirmation form (200) and deletes nothing; POST deletes."""
    s = Setup()
    client.force_login(s.w.user(role))
    url = f'/editor/DataItem/{s.pid}/0/{s.new_item.id}/Sel_All/0/del_spec_item'
    response = client.get(url)
    assert response.status_code == 200
    assert SpecItem.objects.filter(id=s.new_item.id).exists()
    response = client.post(url)
    assert response.status_code == 302
    assert response['Location'] == f'/editor/DataItem/{s.pid}/0/{s.vs}/Sel_All/0/list_spec_items'
    assert not SpecItem.objects.filter(id=s.new_item.id).exists()


@pytest.mark.parametrize('role', ['ro', 'unrelated', 'staff'])
def test_add_spec_item_post_denied_creates_nothing(client, role):
    s = Setup()
    client.force_login(s.w.user(role))
    before = db_snapshot()
    response = client.post(s.url('add_spec_item'), {'domain': 'D', 'name': 'Created', 'title': 't'})
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_WRITE]
    assert db_snapshot() == before


# ------------------------------------------------------------------ cross-project denial

@pytest.fixture
def two_projects():
    w = World()
    other_owner = make_user('other_owner')
    b = make_project(other_owner, name='ProjB')
    item_b = make_spec_item(b, name='ItemB', status='CNF')
    new_b = make_spec_item(b, name='NewB', status='NEW')
    return w, b, item_b, new_b


@pytest.mark.parametrize('suffix,kind', [
    ('0/Sel_All/0/add_spec_item', 'write'),
    ('0/{item}/Sel_All/0/edit_spec_item', 'write'),
    ('0/{item}/Sel_All/0/copy_spec_item', 'write'),
    ('0/{item}/Sel_All/0/split_spec_item', 'write'),
    ('0/{item}/Sel_All/0/del_spec_item', 'write'),
    ('0/{item}/Sel_All/0/refresh_spec_item', 'write'),
    ('0/{vs}/Sel_All/import_spec_items', 'write'),
    ('0/{vs}/Sel_All/0/list_spec_items', 'read'),
    ('0/{item}/Sel_All/list_spec_item_history', 'read'),
    ('0/{vs}/Sel_All/0/export_spec_items', 'read'),
])
def test_rw_user_of_project_a_cannot_access_project_b(client, two_projects, suffix, kind):
    w, b, item_b, new_b = two_projects
    client.force_login(w.rw)
    before = db_snapshot()
    ep = suffix.split('/')[-1]
    path = suffix.format(item=new_b.id if ep == 'del_spec_item' else item_b.id,
                         vs=default_val_set(b).id)
    if ep == 'refresh_spec_item':     # POST-only since Task 6.3 (mutation-via-get)
        with mock.patch('editor.ext_cats.mdb.connect', side_effect=RuntimeError('no network in tests')):
            response = client.post(f'/editor/DataItem/{b.id}/{path}')
    else:
        response = do_get(client, f'/editor/DataItem/{b.id}/{path}')
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    expected = ('This operation requires read/write access to project ProjB' if kind == 'write'
                else 'This operation requires read access to project ProjB')
    assert msgs(response.wsgi_request) == [expected]
    assert db_snapshot() == before


@pytest.mark.parametrize('url_fmt', ['/editor/{b}/edit_project', '/editor/{b}/del_project',
                                     '/editor/{b}/add_val_set'])
def test_staff_actions_on_other_project_unaffected_for_non_staff(client, two_projects, url_fmt):
    w, b, _, _ = two_projects
    client.force_login(w.owner)   # owner of project A, not staff
    before = db_snapshot()
    # FIXED: mutation-via-get (was: GET for del_project) — upstream #86: del_project only takes POST
    send = client.post if url_fmt.endswith('del_project') else client.get
    response = send(url_fmt.format(b=b.id))
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == [MSG_STAFF]
    assert db_snapshot() == before


def test_owner_of_a_cannot_release_project_b(client, two_projects):
    w, b, _, _ = two_projects
    client.force_login(w.owner)
    before = db_snapshot()
    response = client.post(f'/editor/{b.id}/make_project_release', {'description': 'x'})
    assert response['Location'] == '/editor'
    assert msgs(response.wsgi_request) == ['This operation is only accessible to the owner of project ProjB']
    assert db_snapshot() == before


def test_item_of_project_b_editable_through_project_a_url(client, two_projects):
    """FIXED: idor-item-project (was: the item id was not checked against the project in the URL: a
    user with write access to project A could open the edit form of, and delete NEW, items that
    belong to project B by putting A's project id in the URL). Now 404, nothing changes."""
    w, b, item_b, new_b = two_projects
    client.force_login(w.rw)
    a = w.project.id
    before = db_snapshot()
    response = client.get(f'/editor/DataItem/{a}/0/{item_b.id}/Sel_All/0/edit_spec_item')
    assert response.status_code == 404
    # FIXED: mutation-via-get (was: GET deleted the NEW item) — upstream #86: GET only shows the form
    response = client.get(f'/editor/DataItem/{a}/0/{new_b.id}/Sel_All/0/del_spec_item')
    assert response.status_code == 404
    response = client.post(f'/editor/DataItem/{a}/0/{new_b.id}/Sel_All/0/del_spec_item')
    assert response.status_code == 404
    assert SpecItem.objects.filter(id=new_b.id).exists()
    assert SpecItem.objects.get(id=item_b.id).project_id == b.id
    assert db_snapshot() == before
