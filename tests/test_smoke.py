import pytest
from django.conf import settings

from tests.factories import make_project, make_spec_item, make_user


def test_settings_use_synthetic_config():
    assert settings.SECRET_KEY == 'test-only-key-never-use-in-production'
    assert settings.DATABASES['default']['ENGINE'] in ('django.db.backends.sqlite3',
                                                       'django.db.backends.mysql')


@pytest.mark.django_db
def test_factories_and_index(client):
    owner = make_user()
    project = make_project(owner)
    make_spec_item(project)
    client.force_login(owner)
    response = client.get('/editor/')
    assert response.status_code == 200
    assert b'Proj' in response.content
