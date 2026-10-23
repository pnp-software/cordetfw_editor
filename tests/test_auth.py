"""
Characterization tests for authentication: login/logout, password reset,
django-axes lockout, the real admin (/pnpAdmin/), the admin honeypot (/admin/)
and CSRF enforcement.
"""

import logging
import re
from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from tests.factories import PASSWORD, make_user
from tests.golden import assert_golden, normalize_html

from axes.models import AccessAttempt, AccessLog
from admin_honeypot.models import LoginAttempt

pytestmark = pytest.mark.django_db

LOGIN_URL = '/editor/login/'


def post_login(client, username, password, **extra):
    return client.post(LOGIN_URL, {'username': username, 'password': password}, **extra)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_page_renders_login_template(client):
    response = client.get(LOGIN_URL)
    assert response.status_code == 200
    assert 'registration/login.html' in [t.name for t in response.templates]
    assert b'<h2 class="my-3">Login</h2>' in response.content


def test_login_success_redirects_to_login_redirect_url(client):
    make_user('alice')
    response = post_login(client, 'alice', PASSWORD)
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert client.session['_auth_user_id'] == str(User.objects.get(username='alice').pk)


def test_login_success_honours_next(client):
    make_user('alice')
    response = client.post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD,
                                       'next': '/editor/help/'})
    assert response.status_code == 302
    assert response['Location'] == '/editor/help/'


def test_login_failure_rerenders_form(client):
    make_user('alice')
    response = post_login(client, 'alice', 'wrong-password')
    assert response.status_code == 200
    assert '_auth_user_id' not in client.session
    assert "Your username and password didn't match. Please try again." in response.content.decode()
    assert response.context['form'].errors


def test_login_unknown_user_rerenders_form(client):
    response = post_login(client, 'nobody', 'whatever')
    assert response.status_code == 200
    assert "Your username and password didn't match. Please try again." in response.content.decode()


def test_login_missing_password_rerenders_form(client):
    make_user('alice')
    response = client.post(LOGIN_URL, {'username': 'alice'})
    assert response.status_code == 200
    assert response.context['form'].errors


def test_login_required_redirects_to_default_login_url_which_does_not_exist(client):
    # KNOWN-ISSUE: login-url-default
    # settings.LOGIN_URL is not set, so @login_required redirects to Django's default
    # /accounts/login/, which is not routed (the login view lives at /editor/login/).
    response = client.get('/editor/add_project')
    assert response.status_code == 302
    assert response['Location'] == '/accounts/login/?next=/editor/add_project'
    assert client.get('/accounts/login/').status_code == 404


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

# Changed in Task 3.5 (Django 5.2, operator-approved): Django 5 removed GET logout, so the
# navbar link became a POST form with a CSRF token (Django 3.2: <a class="nav-link"
# href="/editor/logout/">Logout</a>).
def test_logout_control_in_base_template_is_a_post_form(client):
    owner = make_user('alice')
    client.force_login(owner)
    content = client.get('/editor/').content.decode()
    assert re.search(r'<form method="post" action="/editor/logout/">\s*'
                     r'<input type="hidden" name="csrfmiddlewaretoken" value="[^"]+">\s*'
                     r'<button type="submit" class="nav-link btn btn-link">Logout</button>\s*</form>',
                     content)
    assert 'href="/editor/logout/"' not in content


def test_logout_via_post_logs_out_and_redirects(client):
    owner = make_user('alice')
    client.force_login(owner)
    assert '_auth_user_id' in client.session
    response = client.post('/editor/logout/')
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert '_auth_user_id' not in client.session


def test_logout_via_get_is_rejected_and_keeps_session(client):
    # Changed in Task 3.5 (Django 5.2): GET used to log out (302 to /editor).
    owner = make_user('alice')
    client.force_login(owner)
    response = client.get('/editor/logout/')
    assert response.status_code == 405
    assert '_auth_user_id' in client.session


def test_logout_post_without_csrf_token_is_rejected():
    client = Client(enforce_csrf_checks=True)
    client.force_login(make_user('alice'))
    assert client.post('/editor/logout/').status_code == 403
    assert '_auth_user_id' in client.session


def test_logout_post_with_csrf_token_from_page_works():
    client = Client(enforce_csrf_checks=True)
    client.force_login(make_user('alice'))
    page = client.get('/editor/').content.decode()
    token = re.search(r'action="/editor/logout/">\s*<input type="hidden" name="csrfmiddlewaretoken" '
                      r'value="([^"]+)"', page).group(1)
    response = client.post('/editor/logout/', {'csrfmiddlewaretoken': token})
    assert response.status_code == 302 and response['Location'] == '/editor'
    assert '_auth_user_id' not in client.session


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def test_password_reset_full_flow(client, mailoutbox):
    user = make_user('alice')

    response = client.get('/editor/password_reset/')
    assert response.status_code == 200
    assert 'registration/password_reset_form.html' in [t.name for t in response.templates]

    response = client.post('/editor/password_reset/', {'email': 'alice@example.com'})
    assert response.status_code == 302
    assert response['Location'] == '/editor/password_reset/done/'

    response = client.get('/editor/password_reset/done/')
    assert response.status_code == 200
    assert "We've emailed you instructions for setting your password." in response.content.decode()

    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ['alice@example.com']
    assert message.subject == 'Password reset on testserver'
    match = re.search(r'http://testserver(/editor/reset/[^/]+/[^/]+/)\n', message.body)
    assert match, message.body
    assert message.body.startswith(
        'Someone asked for password reset for email alice@example.com. Follow the link below:\n')

    # The token link redirects to the set-password form
    confirm_url = match.group(1)
    response = client.get(confirm_url)
    assert response.status_code == 302
    set_url = response['Location']
    assert set_url.endswith('/set-password/')
    response = client.get(set_url)
    assert response.status_code == 200
    assert response.context['validlink'] is True
    assert 'Please enter (and confirm) your new password.' in response.content.decode()

    response = client.post(set_url, {'new_password1': 'N3w-Passw0rd-xyz', 'new_password2': 'N3w-Passw0rd-xyz'})
    assert response.status_code == 302
    assert response['Location'] == '/editor/reset/done/'
    response = client.get('/editor/reset/done/')
    assert response.status_code == 200
    assert 'The password has been changed!' in response.content.decode()

    user.refresh_from_db()
    assert user.check_password('N3w-Passw0rd-xyz')

    # The token is single-use
    response = client.get(confirm_url, follow=True)
    assert response.status_code == 200
    assert 'Password reset failed' in response.content.decode()


def test_password_reset_unknown_email_sends_nothing(client, mailoutbox):
    response = client.post('/editor/password_reset/', {'email': 'nobody@example.com'})
    assert response.status_code == 302
    assert response['Location'] == '/editor/password_reset/done/'
    assert mailoutbox == []


def test_password_reset_invalid_token(client):
    response = client.get('/editor/reset/MQ/set-password/', follow=False)
    assert response.status_code == 200
    assert 'Password reset failed' in response.content.decode()


# ---------------------------------------------------------------------------
# django-axes
# ---------------------------------------------------------------------------

def test_axes_effective_settings():
    from django.conf import settings
    assert settings.AXES_FAILURE_LIMIT == 3
    assert settings.AXES_COOLOFF_TIME == timedelta(minutes=3)
    assert settings.AXES_LOCKOUT_PARAMETERS == ['ip_address']
    assert settings.AXES_LOCKOUT_TEMPLATE == '../templates/lockout.html'
    assert settings.AXES_RESET_ON_SUCCESS is False


def test_axes_lockout_after_three_failures(client):
    make_user('alice')
    statuses = [post_login(client, 'alice', 'bad').status_code for _ in range(3)]
    # failures 1 and 2 re-render the form; the third failure reaches AXES_FAILURE_LIMIT
    assert statuses == [200, 200, 429]

    response = post_login(client, 'alice', 'bad')
    assert response.status_code == 429
    content = response.content.decode()
    assert '<h1 class="display-4 fw-bold lh-1 mb-3">Account Locked</h1>' in content
    assert 'Too many failed login attempts. Please try again later.' in content
    assert 'Your username and password didn' not in content


def test_axes_correct_password_refused_while_locked(client):
    make_user('alice')
    for _ in range(3):
        post_login(client, 'alice', 'bad')
    response = post_login(client, 'alice', PASSWORD)
    assert response.status_code == 429
    assert 'Account Locked' in response.content.decode()
    assert '_auth_user_id' not in client.session


def test_axes_lockout_is_by_ip_not_username(client):
    make_user('alice')
    make_user('bob')
    for _ in range(3):
        post_login(client, 'alice', 'bad')
    # another user from the same IP is locked too
    assert post_login(client, 'bob', PASSWORD).status_code == 429
    # another IP is not
    other = Client(REMOTE_ADDR='10.9.8.7')
    response = post_login(other, 'bob', PASSWORD)
    assert response.status_code == 302
    assert response['Location'] == '/editor'


def test_axes_records(client):
    make_user('alice')
    for _ in range(3):
        post_login(client, 'alice', 'bad')
    attempts = list(AccessAttempt.objects.all())
    assert len(attempts) == 1
    attempt = attempts[0]
    assert attempt.username == 'alice'
    assert attempt.ip_address == '127.0.0.1'
    assert attempt.failures_since_start == 3
    assert attempt.path_info == '/editor/login/'
    assert AccessLog.objects.count() == 0

    post_login(client, 'alice', 'bad')   # locked: counter keeps increasing
    attempt.refresh_from_db()
    assert attempt.failures_since_start == 4


def test_axes_cooloff_allows_login_again(client):
    make_user('alice')
    for _ in range(3):
        post_login(client, 'alice', 'bad')
    assert post_login(client, 'alice', PASSWORD).status_code == 429

    # Still locked 2 minutes later
    AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=2))
    assert post_login(client, 'alice', PASSWORD).status_code == 429

    # Cooloff (3 minutes) has elapsed
    AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(minutes=4))
    response = post_login(client, 'alice', PASSWORD)
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert AccessAttempt.objects.count() == 0     # expired attempts are cleaned
    log = AccessLog.objects.get()
    assert log.username == 'alice'
    assert log.ip_address == '127.0.0.1'
    assert log.logout_time is None


def test_axes_successful_login_creates_access_log(client):
    make_user('alice')
    post_login(client, 'alice', PASSWORD)
    log = AccessLog.objects.get()
    assert (log.username, log.ip_address) == ('alice', '127.0.0.1')
    assert AccessAttempt.objects.count() == 0


def test_axes_successful_login_does_not_reset_failures(client):
    # AXES_RESET_ON_SUCCESS is False: two failures then a success leave the counter at 2
    make_user('alice')
    post_login(client, 'alice', 'bad')
    post_login(client, 'alice', 'bad')
    assert post_login(client, 'alice', PASSWORD).status_code == 302
    assert AccessAttempt.objects.get().failures_since_start == 2


# ---------------------------------------------------------------------------
# Real admin /pnpAdmin/
# ---------------------------------------------------------------------------

def test_pnpadmin_anonymous_redirects_to_admin_login(client):
    response = client.get('/pnpAdmin/')
    assert response.status_code == 302
    assert response['Location'] == '/pnpAdmin/login/?next=/pnpAdmin/'


def test_pnpadmin_superuser_login_and_index(client):
    make_user('root', is_staff=True, is_superuser=True)
    response = client.post('/pnpAdmin/login/?next=/pnpAdmin/',
                           {'username': 'root', 'password': PASSWORD, 'next': '/pnpAdmin/'})
    assert response.status_code == 302
    assert response['Location'] == '/pnpAdmin/'
    response = client.get('/pnpAdmin/')
    assert response.status_code == 200
    content = response.content.decode()
    assert 'Django administration' in content
    for text in ('Users', 'Access attempts', 'Access logs', 'Login attempts'):
        assert text in content
    assert client.get('/pnpAdmin/auth/user/').status_code == 200
    assert client.get('/pnpAdmin/axes/accessattempt/').status_code == 200


def test_pnpadmin_staff_non_superuser_sees_index_without_models(client):
    make_user('staffer', is_staff=True)
    response = client.post('/pnpAdmin/login/?next=/pnpAdmin/',
                           {'username': 'staffer', 'password': PASSWORD, 'next': '/pnpAdmin/'})
    assert response.status_code == 302
    response = client.get('/pnpAdmin/')
    assert response.status_code == 200
    assert 'Django administration' in response.content.decode()
    assert 'Users' not in response.content.decode()
    assert client.get('/pnpAdmin/auth/user/').status_code == 403


def test_pnpadmin_non_staff_cannot_log_in(client):
    make_user('plain')
    response = client.post('/pnpAdmin/login/?next=/pnpAdmin/',
                           {'username': 'plain', 'password': PASSWORD, 'next': '/pnpAdmin/'})
    assert response.status_code == 200
    assert response.context['form'].errors
    assert client.get('/pnpAdmin/').status_code == 302


def test_pnpadmin_login_is_protected_by_axes(client):
    make_user('root', is_staff=True, is_superuser=True)
    for _ in range(3):
        client.post('/pnpAdmin/login/', {'username': 'root', 'password': 'bad', 'next': '/pnpAdmin/'})
    response = client.post('/pnpAdmin/login/', {'username': 'root', 'password': PASSWORD, 'next': '/pnpAdmin/'})
    assert response.status_code == 429
    assert 'Account Locked' in response.content.decode()


# ---------------------------------------------------------------------------
# Honeypot /admin/
# ---------------------------------------------------------------------------

def test_honeypot_admin_redirects_to_fake_login(client):
    response = client.get('/admin/')
    assert response.status_code == 302
    assert response['Location'] == '/admin/login/?next=/admin/'


def test_honeypot_login_page_golden(client):
    response = client.get('/admin/login/')
    assert response.status_code == 200
    assert 'admin_honeypot/login.html' in [t.name for t in response.templates]
    assert_golden('auth/honeypot_login.html', normalize_html(response.content))


@pytest.mark.parametrize('path,expected', [
    ('/admin/anything/', '/admin/login/?next=/admin/anything/'),
    ('/admin/auth/user/', '/admin/login/?next=/admin/auth/user/'),
    ('/admin/a/b/c/?x=1', '/admin/login/?next=/admin/a/b/c/%3Fx%3D1'),
])
def test_honeypot_any_subpath_redirects_to_fake_login(client, path, expected):
    response = client.get(path)
    assert response.status_code == 302
    assert response['Location'] == expected


def test_honeypot_path_without_trailing_slash_gets_permanent_redirect(client):
    response = client.get('/admin/anything')
    assert response.status_code == 301
    assert response['Location'] == '/admin/anything/'


def test_honeypot_post_records_attempt_and_never_authenticates(client, caplog):
    make_user('root', is_staff=True, is_superuser=True)
    with caplog.at_level(logging.DEBUG):
        response = client.post('/admin/login/', {'username': 'root', 'password': PASSWORD},
                               HTTP_USER_AGENT='Agent/1.0', REMOTE_ADDR='10.1.2.3')
    # Even with valid credentials of a real superuser the page is re-rendered
    assert response.status_code == 200
    assert 'Please enter the correct username and password for a staff account.' in response.content.decode()
    assert '_auth_user_id' not in client.session
    assert client.get('/pnpAdmin/').status_code == 302

    attempt = LoginAttempt.objects.get()
    assert attempt.username == 'root'
    assert attempt.ip_address == '10.1.2.3'
    assert attempt.user_agent == 'Agent/1.0'
    assert attempt.path == '/admin/login/'
    assert attempt.session_key is None

    # KNOWN-ISSUE: honeypot-logger-not-connected
    # editor/signals/handlers.py defines a receiver that logs honeypot attempts,
    # but nothing imports it (EditorConfig has no ready()), so no log record is emitted.
    assert [r for r in caplog.records if r.name == 'admin.honeypot'] == []


def test_honeypot_signal_has_no_receivers(client):
    # KNOWN-ISSUE: honeypot-logger-not-connected
    from admin_honeypot.signals import honeypot
    assert not honeypot.has_listeners(LoginAttempt)


def test_honeypot_records_each_attempt_with_path_and_next(client):
    client.post('/admin/login/', {'username': 'a', 'password': 'x'})
    client.post('/admin/login/?next=/admin/foo/', {'username': 'b', 'password': 'y'})
    rows = list(LoginAttempt.objects.order_by('id').values_list('username', 'path'))
    assert rows == [('a', '/admin/login/'), ('b', '/admin/login/?next=/admin/foo/')]


def test_honeypot_post_to_other_path_redirects_without_recording(client):
    response = client.post('/admin/something/', {'username': 'a', 'password': 'x'})
    assert response.status_code == 302
    assert LoginAttempt.objects.count() == 0


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def test_login_post_without_csrf_token_is_forbidden():
    make_user('alice')
    client = Client(enforce_csrf_checks=True)
    response = client.post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD})
    assert response.status_code == 403
    assert AccessAttempt.objects.count() == 0


def test_login_post_with_csrf_token_succeeds():
    make_user('alice')
    client = Client(enforce_csrf_checks=True)
    page = client.get(LOGIN_URL)
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
    response = client.post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD,
                                       'csrfmiddlewaretoken': token})
    assert response.status_code == 302
    assert response['Location'] == '/editor'


# ===========================================================================
# Extended characterization (pre-upgrade gaps)
# ===========================================================================

from django.core import mail  # noqa: E402
from django.db import connection  # noqa: E402
from django.template import Context, Template  # noqa: E402

from tests.factories import FIXED_TIME  # noqa: E402

FIXED_TIME_2 = FIXED_TIME + timedelta(days=1, hours=2, minutes=3, seconds=4)


# ---------------------------------------------------------------------------
# Bare datetime / number rendering (USE_L10N=False, strftime-style DATETIME_FORMAT)
# ---------------------------------------------------------------------------

# Changed in Task 3.5 (Django 5.2, operator-approved): DATETIME_FORMAT is now the Django
# format 'd-m-Y H:i:s' (settings + cordetfw_editor/formats/en). Django 3.2 rendered the
# strftime-style '%d-%m-%Y %H:%M:%S' literally as '%15-%01-%2024 %10:%Jan:%th'.
# |date (DATE_FORMAT), integers and floats are unchanged.
def test_bare_datetime_and_number_rendering():
    out = Template('{{ d }}|{{ d|date }}|{{ n }}|{{ f }}').render(
        Context({'d': FIXED_TIME, 'n': 1234567, 'f': 1234.5}))
    assert out == '15-01-2024 10:30:00|Jan. 15, 2024|1234567|1234.5'


def changelist_table(html):
    """Return (column css classes, normalized <tbody> text) of the admin result list."""
    table = re.search(r'<table id="result_list">.*?</table>', html, re.S).group(0)
    columns = re.findall(r'<th scope="col" class="([^"]*)"', table)
    tbody = re.search(r'<tbody>(.*)</tbody>', table, re.S).group(1)
    tbody = re.sub(r'/(\d+)/change/', '/ID/change/', tbody)
    tbody = re.sub(r'name="_selected_action" value="\d+"', 'name="_selected_action" value="ID"', tbody)
    tbody = re.sub(r'[a-z0-9]{32}', 'SESSION', tbody)  # random session key
    return columns, '\n'.join(line for line in tbody.splitlines() if line.strip()) + '\n'


@pytest.fixture
def superuser_client():
    make_user('root', is_staff=True, is_superuser=True)
    client = Client()
    response = client.post('/pnpAdmin/login/?next=/pnpAdmin/',
                           {'username': 'root', 'password': PASSWORD, 'next': '/pnpAdmin/'})
    assert response.status_code == 302
    return client


# Changed in Task 3.5: admin timestamp cells show '15-01-2024 10:30:00' (see
# test_bare_datetime_and_number_rendering); Django 5.2 also adds an aria-label to row checkboxes.
def test_admin_honeypot_loginattempt_changelist(superuser_client):
    for username, stamp in (('first', FIXED_TIME), ('second', FIXED_TIME_2)):
        superuser_client.post('/admin/login/', {'username': username, 'password': 'x'},
                              REMOTE_ADDR='10.1.1.1', HTTP_USER_AGENT='Agent/1.0')
        LoginAttempt.objects.filter(username=username).update(timestamp=stamp)
    response = superuser_client.get('/pnpAdmin/admin_honeypot/loginattempt/')
    assert response.status_code == 200
    columns, rows = changelist_table(response.content.decode())
    assert [c.split()[-1] if 'sorted' not in c else c.split()[1] for c in columns] == [
        'column-username', 'column-get_ip_address', 'column-get_session_key',
        'column-timestamp', 'column-get_path']
    assert_golden('auth/admin_honeypot_loginattempt_rows.html', rows)


# Changed in Task 3.5: see test_bare_datetime_and_number_rendering.
def test_admin_axes_accessattempt_and_accesslog_changelists(superuser_client):
    # one failure from another user name (AccessAttempt) ...
    Client().post(LOGIN_URL, {'username': 'ghost', 'password': 'bad'})
    AccessAttempt.objects.update(attempt_time=FIXED_TIME)
    # ... and the superuser login itself created exactly one AccessLog row
    AccessLog.objects.update(attempt_time=FIXED_TIME_2)

    response = superuser_client.get('/pnpAdmin/axes/accessattempt/')
    assert response.status_code == 200
    columns, rows = changelist_table(response.content.decode())
    assert [c.split()[-1] for c in columns] == [
        'action-checkbox-column', 'column-attempt_time', 'column-ip_address', 'column-user_agent',
        'column-username', 'column-path_info', 'column-failures_since_start',
        'column-status']   # Task 3.7: django-axes 8 adds a read-only 'status' column
    assert_golden('auth/admin_axes_accessattempt_rows.html', rows)

    response = superuser_client.get('/pnpAdmin/axes/accesslog/')
    assert response.status_code == 200
    columns, rows = changelist_table(response.content.decode())
    assert [c.split()[-1] for c in columns] == [
        'action-checkbox-column', 'column-attempt_time', 'column-logout_time', 'column-ip_address',
        'column-username', 'column-user_agent', 'column-path_info']
    assert_golden('auth/admin_axes_accesslog_rows.html', rows)


# ---------------------------------------------------------------------------
# CSRF Origin / Referer checking matrix
# ---------------------------------------------------------------------------

GOOD_REFERER = 'https://testserver/editor/login/'

CSRF_MATRIX = [
    pytest.param({}, {}, 302, id='http-no-origin'),
    pytest.param({}, {'HTTP_ORIGIN': 'http://testserver'}, 302, id='http-origin-same'),
    # Changed in Task 3.4 (Django 4.2, was 302): the Origin header of every unsafe request is
    # checked; an Origin not matching the host (or CSRF_TRUSTED_ORIGINS) is rejected with 403.
    pytest.param({}, {'HTTP_ORIGIN': 'http://evil.example'}, 403, id='http-origin-evil'),
    # Changed in Task 3.4 (Django 4.2, was 302): scheme and host of Origin are compared with the
    # request. Behind the Apache TLS proxy Django sees plain HTTP while the browser sends
    # 'Origin: https://host', so production needs CSRF_TRUSTED_ORIGINS = ['https://<host>']
    # (or SECURE_PROXY_SSL_HEADER). Deployment item, see docs/migration/tasks.md Task 4.4.
    pytest.param({}, {'HTTP_ORIGIN': 'https://testserver'}, 403, id='http-origin-https-scheme'),
    # Changed in Task 3.4 (Django 4.2, was 403): a matching Origin on a secure request is
    # accepted without a Referer (3.2 always required a Referer on HTTPS).
    pytest.param({'secure': True}, {'HTTP_ORIGIN': 'https://testserver'}, 302,
                 id='https-origin-good-no-referer'),
    # Changed in Task 3.4 (Django 4.2, was 302): an untrusted Origin is rejected without falling
    # back to the Referer.
    pytest.param({'secure': True}, {'HTTP_ORIGIN': 'https://evil.example', 'HTTP_REFERER': GOOD_REFERER},
                 403, id='https-origin-evil-referer-good'),
    pytest.param({'secure': True}, {'HTTP_REFERER': GOOD_REFERER}, 302, id='https-referer-good'),
    pytest.param({'secure': True}, {'HTTP_REFERER': 'https://evil.example/'}, 403,
                 id='https-referer-evil'),
    pytest.param({'secure': True}, {}, 403, id='https-no-origin-no-referer'),
]


@pytest.mark.parametrize('request_kwargs,extra,status', CSRF_MATRIX)
def test_csrf_origin_referer_matrix(settings, request_kwargs, extra, status):
    # Production cookie settings (CSRF_TRUSTED_ORIGINS is not configured)
    settings.CSRF_COOKIE_SECURE = True
    settings.SESSION_COOKIE_SECURE = True
    assert not getattr(settings, 'CSRF_TRUSTED_ORIGINS', [])
    make_user('alice')
    client = Client(enforce_csrf_checks=True)
    page = client.get(LOGIN_URL, **request_kwargs)
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
    response = client.post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD,
                                       'csrfmiddlewaretoken': token}, **request_kwargs, **extra)
    assert response.status_code == status
    if status == 302:
        assert response['Location'] == '/editor'
        assert '_auth_user_id' in client.session
    else:
        assert '_auth_user_id' not in client.session
        assert AccessAttempt.objects.count() == 0


# ---------------------------------------------------------------------------
# django-axes: proxies, locked clients, real 429 response
# ---------------------------------------------------------------------------

def test_axes_ignores_x_forwarded_for():
    make_user('alice')
    client = Client(REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='1.2.3.4')
    post_login(client, 'alice', 'bad')
    attempt = AccessAttempt.objects.get()
    assert attempt.ip_address == '10.0.0.1'      # REMOTE_ADDR wins; XFF is not trusted
    # a different X-Forwarded-For does not escape the lock (nor create a second record)
    assert post_login(client, 'alice', 'bad').status_code == 200
    assert post_login(client, 'alice', 'bad').status_code == 429
    spoof = Client(REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='5.6.7.8')
    assert post_login(spoof, 'alice', PASSWORD).status_code == 429
    assert list(AccessAttempt.objects.values_list('ip_address', flat=True)) == ['10.0.0.1']


def test_axes_locked_ip_can_still_get_pages(client):
    make_user('alice')
    for _ in range(3):
        post_login(client, 'alice', 'bad')
    assert post_login(client, 'alice', PASSWORD).status_code == 429
    assert client.get(LOGIN_URL).status_code == 200
    assert client.get('/editor/').status_code == 200
    assert client.get('/editor/help/').status_code == 200


def test_axes_lockout_response_golden(client):
    make_user('alice')
    for _ in range(3):
        post_login(client, 'alice', 'bad')
    response = post_login(client, 'alice', 'bad')
    assert response.status_code == 429
    assert response['Content-Type'] == 'text/html; charset=utf-8'
    assert_golden('auth/lockout_429.html', normalize_html(response.content))


# ---------------------------------------------------------------------------
# Honeypot: schema, migrations and isolation from the real login
# ---------------------------------------------------------------------------

def test_honeypot_model_table_and_app_label():
    assert LoginAttempt._meta.db_table == 'admin_honeypot_loginattempt'
    assert LoginAttempt._meta.app_label == 'admin_honeypot'
    assert LoginAttempt._meta.label == 'admin_honeypot.LoginAttempt'
    assert connection.introspection.table_names().count('admin_honeypot_loginattempt') == 1


def test_honeypot_migrations_recorded():
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM django_migrations WHERE app = 'admin_honeypot' ORDER BY name")
        names = [row[0] for row in cursor.fetchall()]
    assert names == ['0001_initial', '0002_auto_20160208_0854']


def test_honeypot_attempts_do_not_lock_the_real_login_nor_send_mail(client):
    make_user('alice')
    for i in range(3):
        response = client.post('/admin/login/', {'username': 'alice', 'password': 'bad%d' % i})
        assert response.status_code == 200
    assert LoginAttempt.objects.count() == 3
    assert AccessAttempt.objects.count() == 0
    assert AccessLog.objects.count() == 0
    assert mail.outbox == []
    # the real login is not locked
    assert client.get(LOGIN_URL).status_code == 200
    assert post_login(client, 'alice', 'bad').status_code == 200
    assert post_login(client, 'alice', PASSWORD).status_code == 302


# ---------------------------------------------------------------------------
# Password reset e-mail
# ---------------------------------------------------------------------------

def test_password_reset_email_exact(client, mailoutbox):
    make_user('alice')
    client.post('/editor/password_reset/', {'email': 'alice@example.com'})
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.subject == 'Password reset on testserver'
    assert message.from_email == 'webmaster@localhost'
    assert message.to == ['alice@example.com']
    assert message.alternatives == []
    assert message.extra_headers == {}
    mime = message.message()
    assert mime['Content-Type'] == 'text/plain; charset="utf-8"'
    assert mime['Content-Transfer-Encoding'] == '7bit'
    body = re.sub(r'/editor/reset/([^/]+)/([^/]+)/\n$',
                  lambda m: '/editor/reset/<UID>/<TOKEN>/\n', message.body)
    assert body == ('Someone asked for password reset for email alice@example.com. '
                    'Follow the link below:\n'
                    'http://testserver/editor/reset/<UID>/<TOKEN>/\n')
    uid, token = re.search(r'/editor/reset/([^/]+)/([^/]+)/', message.body).groups()
    assert re.fullmatch(r'[A-Za-z0-9_-]+', uid)
    assert re.fullmatch(r'[a-z0-9]+-[0-9a-f]{32}', token)


# ---------------------------------------------------------------------------
# Redirect safety
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('next_url', ['//evil.example/', 'https://evil.example/x', '/\\evil.example'])
def test_login_unsafe_next_is_ignored(client, next_url):
    make_user('alice')
    response = client.post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD, 'next': next_url})
    assert response.status_code == 302
    assert response['Location'] == '/editor'


def test_logout_safe_next_is_honoured(client):
    client.force_login(make_user('alice'))
    response = client.post('/editor/logout/?next=/editor/help/')   # POST since Task 3.5
    assert response.status_code == 302
    assert response['Location'] == '/editor/help/'


@pytest.mark.parametrize('next_url', ['//evil.example/', 'https://evil.example/'])
def test_logout_unsafe_next_falls_back_to_logout_redirect_url(client, next_url):
    # Changed in Task 3.4 (Django 4.2): an unsafe ?next= now falls back to LOGOUT_REDIRECT_URL.
    # Django 3.2 redirected to request.path (/editor/logout/), a redirect loop
    # (KNOWN-ISSUE logout-unsafe-next-self-redirect, fixed upstream).
    # POST since Task 3.5 (Django 5 removed GET logout).
    client.force_login(make_user('alice'))
    response = client.post('/editor/logout/', {'next': next_url})
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert '_auth_user_id' not in client.session



def test_axes_resolves_client_ip_through_ipware():
    # Task 3.7: django-axes 8 no longer depends on django-ipware; production had it installed
    # (axes 7 dependency), so it is kept via the 'django-axes[ipware]' extra. axes uses ipware
    # when it is importable; with the default precedence ('REMOTE_ADDR',) both paths agree.
    from axes import helpers
    assert helpers.IPWARE_INSTALLED


def test_csrf_trusted_origins_config_key_allows_proxy_https_origin(settings):
    # Optional config key CSRF_TRUSTED_ORIGINS (default [] = unchanged behaviour) fixes the
    # 'http-origin-https-scheme' case of the CSRF matrix for a TLS-terminating proxy.
    settings.CSRF_TRUSTED_ORIGINS = ['https://testserver']
    make_user('alice')
    client = Client(enforce_csrf_checks=True)
    page = client.get(LOGIN_URL)
    token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
    response = client.post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD,
                                       'csrfmiddlewaretoken': token}, HTTP_ORIGIN='https://testserver')
    assert response.status_code == 302


def test_csrf_trusted_origins_defaults_to_empty():
    from django.conf import settings
    assert settings.CSRF_TRUSTED_ORIGINS == []


def test_logout_from_stale_tab_with_rotated_csrf_token_is_rejected():
    # Known limitation since Task 3.5 (documented in RELEASE_NOTES.md): a tab rendered before a
    # re-login carries an outdated CSRF token, so its logout button gets Django's CSRF 403 page;
    # reloading the page fixes it. LogoutView enforces CSRF itself (csrf_protect on dispatch).
    client = Client(enforce_csrf_checks=True)
    user = make_user('alice')
    client.force_login(user)
    stale = re.search(r'action="/editor/logout/">\s*<input type="hidden" name="csrfmiddlewaretoken" '
                      r'value="([^"]+)"', client.get('/editor/').content.decode()).group(1)
    client.logout()
    client.force_login(user)          # login rotates the CSRF secret
    response = client.post('/editor/logout/', {'csrfmiddlewaretoken': stale})
    assert response.status_code == 403
    assert '_auth_user_id' in client.session


# ---------------------------------------------------------------------------------------------
# Task 6.7: optional config key AXES_LOCKOUT_PARAMETERS
# ---------------------------------------------------------------------------------------------

def test_axes_lockout_parameters_absent_key_leaves_default():
    from django.conf import settings
    from cordetfw_editor.config_helpers import parse_axes_lockout_parameters
    assert parse_axes_lockout_parameters({}) is None
    assert settings.AXES_LOCKOUT_PARAMETERS == ['ip_address']      # same as before Task 6.7


@pytest.mark.parametrize('value', [
    ['ip_address'], ['ip_address', 'username'], [['ip_address', 'username']],
    ['username', ['ip_address', 'user_agent']],
])
def test_axes_lockout_parameters_valid_shapes_pass_through(value):
    from cordetfw_editor.config_helpers import parse_axes_lockout_parameters
    assert parse_axes_lockout_parameters({'AXES_LOCKOUT_PARAMETERS': value}) == value


@pytest.mark.parametrize('value', [
    None, 'ip_address', [], ['ip'], [[]], [['ip_address', 'nope']], [1], [['username', 1]],
    {'a': 1}, [['ip_address', ['username']]], ['IP_ADDRESS'],
])
def test_axes_lockout_parameters_invalid_shapes_are_rejected(value):
    from django.core.exceptions import ImproperlyConfigured
    from cordetfw_editor.config_helpers import parse_axes_lockout_parameters
    with pytest.raises(ImproperlyConfigured, match='AXES_LOCKOUT_PARAMETERS'):
        parse_axes_lockout_parameters({'AXES_LOCKOUT_PARAMETERS': value})


def _fail_login(ip, n, password='bad'):
    c = Client(REMOTE_ADDR=ip)
    for _ in range(n):
        c.post(LOGIN_URL, {'username': 'alice', 'password': password})
    return c


def test_axes_lockout_by_ip_or_username_stops_distributed_guessing(settings):
    # Recommended value: any IP reaching 3 failures is locked, and so is a username that reaches 3
    # failures in total, whatever the source IPs.
    settings.AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']
    make_user('alice')
    for ip in ('10.0.0.1', '10.0.0.2', '10.0.0.3'):
        _fail_login(ip, 1)
    r = Client(REMOTE_ADDR='10.0.0.4').post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD})
    assert r.status_code == 429
    # trade-off: the legitimate user is locked too, from any IP, until the cool-off ends
    r = Client(REMOTE_ADDR='10.0.0.99').post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD})
    assert r.status_code == 429


def test_axes_lockout_by_combination_does_not_stop_distributed_guessing(settings):
    # [["ip_address", "username"]] counts per (IP, username) pair: no better than IP only here.
    settings.AXES_LOCKOUT_PARAMETERS = [['ip_address', 'username']]
    make_user('alice')
    for ip in ('10.0.0.1', '10.0.0.2', '10.0.0.3'):
        _fail_login(ip, 2)
    r = Client(REMOTE_ADDR='10.0.0.4').post(LOGIN_URL, {'username': 'alice', 'password': PASSWORD})
    assert r.status_code == 302
