"""
Characterization tests for state persisted by the OLD version (Django 3.2) that must
keep working after the upgrade: password hashes, the session auth hash, password
reset tokens and stored session data. All literals below were generated on the
baseline (Django 3.2.0, SECRET_KEY from tests/settings_test.py's synthetic config).
If one of the "must stay equal" assertions fails after the upgrade, every user is
logged out / every outstanding reset link is invalidated: that is a regression.
"""

from datetime import datetime, timedelta
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from datetime import timezone as dt_timezone

from django.utils import timezone

from tests.factories import PASSWORD

pytestmark = pytest.mark.django_db

# make_password(PASSWORD, salt='fixedsalt0000000000000') with PBKDF2PasswordHasher on Django 3.2.0
PBKDF2_HASH = 'pbkdf2_sha256$260000$fixedsalt0000000000000$hqntudOg1bKtRn1zXteKKxADqZnHsoZrcBAMIyDcIRY='
# User(id=7, password=PBKDF2_HASH).get_session_auth_hash() under the test SECRET_KEY
SESSION_AUTH_HASH = 'ab71920265e0bdc8e1123121443c8b35ec635fc03f9a3f8f9264269261b7562d'
# PasswordResetTokenGenerator().make_token(user) for user(id=7, PBKDF2_HASH, email alice@example.com,
# last_login 2024-01-15 10:30:00) with _now() mocked to 2024-01-15 10:30:00
RESET_NOW = datetime(2024, 1, 15, 10, 30, 0)
RESET_TOKEN = 'c0uai0-4cc83face0af8a24a8f1969ef0f71674'
RESET_UID = 'Nw'            # urlsafe_base64_encode(b'7')
# SessionStore().encode({...}) of a session logged in as user 7 with SESSION_AUTH_HASH
SESSION_DATA = ('.eJxVjDsOwyAQRO9CHSFY_inT-wwIFghOIpCMXUW5e2zJRdJMMe_NvIkP21r9NvLi50SuxJDLbxcDPnM7QHqEdu8Ue1uXOdJDoScddOopv26n-3dQw6j7'
                'OkTDHTDQKrOY0GbOQXDgUgq0UaiMWqiCTBQXRLHFgZag9-TRKA2JfL7IDDbe:1xKFOX:7aVMv3fWLvFlRiWZT0Z21f_1FYDFs_0eNqEJRx4LboU')
SESSION_DECODED = {
    '_auth_user_id': '7',
    '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend',
    '_auth_user_hash': SESSION_AUTH_HASH,
}
# The pinned token/session literals only make sense with this key (see settings_test.py)
EXPECTED_SECRET_KEY = 'test-only-key-never-use-in-production'


@pytest.fixture
def default_hashers(settings):
    """Restore Django's default PASSWORD_HASHERS (the suite normally uses MD5)."""
    from django.conf import global_settings
    settings.PASSWORD_HASHERS = list(global_settings.PASSWORD_HASHERS)


@pytest.fixture
def old_user():
    return User.objects.create(
        id=7, username='alice', email='alice@example.com', password=PBKDF2_HASH,
        last_login=datetime(2024, 1, 15, 10, 30, 0, tzinfo=dt_timezone.utc))


def test_secret_key_is_the_one_used_to_generate_literals(settings):
    assert settings.SECRET_KEY == EXPECTED_SECRET_KEY


def test_default_hashers_first_is_pbkdf2(default_hashers, settings):
    assert settings.PASSWORD_HASHERS[0] == 'django.contrib.auth.hashers.PBKDF2PasswordHasher'


# (a) password hash --------------------------------------------------------

def test_old_pbkdf2_hash_checks_and_logs_in(client, default_hashers, old_user):
    assert old_user.check_password(PASSWORD)
    old_user.refresh_from_db()
    # Changed in Task 3.4 (Django 4.2): check_password() already upgrades the outdated
    # 260000-iteration hash (Django 3.2 left it unchanged).
    assert old_user.password.startswith('pbkdf2_sha256$600000$')
    response = client.post('/editor/login/', {'username': 'alice', 'password': PASSWORD})
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    assert client.session['_auth_user_id'] == '7'
    old_user.refresh_from_db()
    # Changed in Task 3.4 (Django 4.2, was 260000): the password is rehashed on login with the
    # current default iterations. Django 3.2 can still verify the new hash (iterations are
    # stored in it), so a rollback does not lock users out.
    # EXPECTED-CHANGE: Django 5.2 raises the default to 1,000,000 iterations.
    assert old_user.password.startswith('pbkdf2_sha256$600000$')


def test_old_pbkdf2_hash_wrong_password_rejected(client, default_hashers, old_user):
    response = client.post('/editor/login/', {'username': 'alice', 'password': 'wrong'})
    assert response.status_code == 200
    assert '_auth_user_id' not in client.session
    old_user.refresh_from_db()
    assert old_user.password == PBKDF2_HASH


# (b) session auth hash ------------------------------------------------------

def test_session_auth_hash_stays_equal(old_user):
    # Must stay equal across the upgrade, otherwise all users are logged out.
    assert old_user.get_session_auth_hash() == SESSION_AUTH_HASH


# (c) password reset token ---------------------------------------------------

def test_old_reset_token_still_checks(old_user):
    generator = PasswordResetTokenGenerator()
    with mock.patch.object(generator, '_now', return_value=RESET_NOW):
        assert generator.check_token(old_user, RESET_TOKEN) is True
        # and today's algorithm still produces the very same literal
        assert generator.make_token(old_user) == RESET_TOKEN
    with mock.patch.object(generator, '_now', return_value=RESET_NOW + timedelta(days=3, seconds=1)):
        assert generator.check_token(old_user, RESET_TOKEN) is False    # PASSWORD_RESET_TIMEOUT 3 days
    with mock.patch.object(generator, '_now', return_value=RESET_NOW):
        assert generator.check_token(old_user, RESET_TOKEN[:-1] + '0') is False


def test_old_reset_token_valid_through_the_view(client, old_user):
    with mock.patch.object(PasswordResetTokenGenerator, '_now', return_value=RESET_NOW):
        response = client.get('/editor/reset/%s/%s/' % (RESET_UID, RESET_TOKEN))
        assert response.status_code == 302
        assert response['Location'] == '/editor/reset/%s/set-password/' % RESET_UID
        response = client.get(response['Location'])
        assert response.status_code == 200
        assert response.context['validlink'] is True


# (d) stored session -----------------------------------------------------------

def test_old_session_data_decodes():
    assert SessionStore().decode(SESSION_DATA) == SESSION_DECODED


def test_old_session_row_authenticates_user(client, old_user):
    key = 'persistedsessionkey00000000000ab'
    Session.objects.create(session_key=key, session_data=SESSION_DATA,
                           expire_date=timezone.now() + timedelta(days=1))
    client.cookies['sessionid'] = key
    response = client.get('/editor/')
    assert response.status_code == 200
    assert response.context['user'].is_authenticated
    assert response.context['user'].pk == 7
    assert client.session['_auth_user_id'] == '7'


def test_old_session_row_rejected_when_password_changed(client, old_user):
    # The session auth hash binds the session to the password hash
    key = 'persistedsessionkey00000000000ab'
    Session.objects.create(session_key=key, session_data=SESSION_DATA,
                           expire_date=timezone.now() + timedelta(days=1))
    User.objects.filter(pk=7).update(password='pbkdf2_sha256$260000$other$' + 'x' * 44)
    client.cookies['sessionid'] = key
    response = client.get('/editor/')
    assert not response.context['user'].is_authenticated
