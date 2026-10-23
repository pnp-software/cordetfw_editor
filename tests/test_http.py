"""
Characterization tests for the raw HTTP surface: full response header sets,
cookie attributes and the CSRF cookie. Pinned on Django 3.2; the Django 4.0+
differences are marked EXPECTED-CHANGE.
"""

import re

import pytest
from django.test import Client

from tests.factories import PASSWORD, default_val_set, make_project, make_spec_item, make_user

pytestmark = pytest.mark.django_db

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
NO_CACHE = 'max-age=0, no-cache, no-store, must-revalidate, private'

# Headers that are identical on every response of the stack (SecurityMiddleware,
# XFrameOptionsMiddleware, SessionMiddleware).
COMMON = [
    # EXPECTED-CHANGE: Django 4.0 SecurityMiddleware adds Cross-Origin-Opener-Policy: same-origin
    ('Referrer-Policy', 'same-origin'),
    ('Vary', 'Cookie'),
    ('X-Content-Type-Options', 'nosniff'),
    ('X-Frame-Options', 'DENY'),
]


def headers(response, length=True):
    """Sorted (name, value) pairs without Date/Expires; Content-Length is optionally dropped
    after verifying it against the body (variable-size bodies)."""
    pairs = sorted((k, v) for k, v in response.items() if k not in ('Date', 'Expires'))
    if not length:
        pairs = [(k, v) for k, v in pairs if k != 'Content-Length']
    return pairs


def body(response):
    if response.streaming:
        return b''.join(response.streaming_content)
    return response.content


def cookie_attrs(morsel):
    return {k: morsel[k] for k in ('path', 'max-age', 'secure', 'httponly', 'samesite', 'domain')}


# ---------------------------------------------------------------------------
# Header sets
# ---------------------------------------------------------------------------

def test_headers_login_page_get(client):
    response = client.get('/editor/login/')
    assert response.status_code == 200
    assert 'Expires' in response   # Date is added by the WSGI server, not present here
    assert headers(response) == sorted([
        ('Cache-Control', NO_CACHE),
        ('Content-Length', '4046'),
        ('Content-Type', 'text/html; charset=utf-8'),
    ] + COMMON)


def test_headers_logged_in_index(client):
    client.force_login(make_user('alice'))
    response = client.get('/editor/')
    assert response.status_code == 200
    assert 'Expires' not in response
    assert headers(response) == sorted([
        ('Content-Length', '3350'),
        ('Content-Type', 'text/html; charset=utf-8'),
    ] + COMMON)


def test_headers_anonymous_index(client):
    response = client.get('/editor/')
    assert response.status_code == 200
    assert headers(response) == sorted([
        ('Content-Length', '4184'),
        ('Content-Type', 'text/html; charset=utf-8'),
    ] + COMMON)


def test_headers_redirect(client):
    client.force_login(make_user('alice'))
    # EXPECTED-CHANGE: Django 5 requires POST for logout, GET returns 405
    response = client.get('/editor/logout/')
    assert response.status_code == 302
    assert headers(response) == sorted([
        ('Cache-Control', NO_CACHE),
        ('Content-Length', '0'),
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Location', '/editor'),
    ] + COMMON)


def test_headers_login_redirect_after_post(client):
    make_user('alice')
    response = client.post('/editor/login/', {'username': 'alice', 'password': PASSWORD})
    assert response.status_code == 302
    assert headers(response) == sorted([
        ('Cache-Control', NO_CACHE),
        ('Content-Length', '0'),
        ('Content-Type', 'text/html; charset=utf-8'),
        ('Location', '/editor'),
    ] + COMMON)


@pytest.fixture
def world(client):
    user = make_user('alice')
    project = make_project(user, 'Proj')
    make_spec_item(project, name='a', title='foo')
    client.force_login(user)
    return project, default_val_set(project)


def test_headers_find_replace_xhr_json(client, world):
    project, dvs = world
    response = client.post('/editor/DataItem/%d/0/%d/Sel_All/0/list_spec_items' % (project.id, dvs.id),
                           {'field': 'title', 'find': 'foo', 'replace': 'qux'}, **XHR)
    assert response.json() == {'updated_count': 1}
    assert headers(response) == sorted([
        ('Content-Length', '20'),
        ('Content-Type', 'application/json'),
    ] + COMMON)


def test_headers_export_project_file_response(client, world):
    project, _ = world
    response = client.get('/editor/%d/export_project' % project.id)
    assert response.streaming is True
    data = body(response)
    assert response['Content-Length'] == str(len(data))
    assert headers(response, length=False) == sorted([
        ('Content-Disposition', 'inline; filename="cordetfw_editor_Proj.zip"'),
        ('Content-Type', 'application/zip'),
    ] + COMMON)


def test_headers_export_spec_items(client, world):
    project, dvs = world
    response = client.get('/editor/DataItem/%d/0/%d/Sel_All/0/export_spec_items' % (project.id, dvs.id))
    assert response['Content-Length'] == str(len(response.content))
    assert headers(response, length=False) == sorted([
        ('Content-Disposition', 'attachment; filename= "ProjDataItem.csv"'),
        ('Content-Type', 'text/plain'),
    ] + COMMON)


def test_headers_axes_lockout_429(client):
    make_user('alice')
    for _ in range(3):
        client.post('/editor/login/', {'username': 'alice', 'password': 'bad'})
    response = client.post('/editor/login/', {'username': 'alice', 'password': 'bad'})
    assert response.status_code == 429
    assert headers(response) == sorted([
        ('Content-Length', '2535'),
        ('Content-Type', 'text/html; charset=utf-8'),
    ] + COMMON)


# ---------------------------------------------------------------------------
# Cookies (production values restored)
# ---------------------------------------------------------------------------

@pytest.fixture
def prod_cookies(settings):
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True


def test_csrf_cookie_attributes_and_length(client, prod_cookies):
    response = client.get('/editor/login/', secure=True)
    morsel = response.cookies['csrftoken']
    assert cookie_attrs(morsel) == {'path': '/', 'max-age': 31449600, 'secure': True,
                                    'httponly': '', 'samesite': 'Lax', 'domain': ''}
    # EXPECTED-CHANGE: Django 4.1+ stores a 32 character secret in the cookie (64 before)
    assert len(morsel.value) == 64
    assert re.fullmatch(r'[A-Za-z0-9]{64}', morsel.value)
    # the token embedded in the form is masked and differs from the cookie value
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()).group(1)
    assert len(token) == 64
    assert token != morsel.value


def test_session_cookie_attributes(client, prod_cookies):
    make_user('alice')
    response = client.post('/editor/login/', {'username': 'alice', 'password': PASSWORD}, secure=True)
    assert response.status_code == 302
    assert 'sessionid' in response.cookies
    morsel = response.cookies['sessionid']
    assert cookie_attrs(morsel) == {'path': '/', 'max-age': 1209600, 'secure': True,
                                    'httponly': True, 'samesite': 'Lax', 'domain': ''}
    assert re.fullmatch(r'[a-z0-9]{32}', morsel.value)


def test_session_cookie_not_secure_with_test_settings(client):
    # The global test settings disable the secure flags (so the plain HTTP test client works).
    make_user('alice')
    response = client.post('/editor/login/', {'username': 'alice', 'password': PASSWORD})
    assert response.cookies['sessionid']['secure'] == ''


def test_logout_clears_session_cookie(client, prod_cookies):
    client.force_login(make_user('alice'))
    # EXPECTED-CHANGE: Django 5 requires POST for logout
    response = client.get('/editor/logout/', secure=True)
    morsel = response.cookies['sessionid']
    assert morsel.value == ''
    assert morsel['max-age'] == 0
    assert morsel['expires'] == 'Thu, 01 Jan 1970 00:00:00 GMT'
    assert morsel['samesite'] == 'Lax'
    # EXPECTED-CHANGE: Django 3.2 does not set secure/httponly on the deletion cookie
    assert morsel['secure'] == ''
    assert morsel['httponly'] == ''
