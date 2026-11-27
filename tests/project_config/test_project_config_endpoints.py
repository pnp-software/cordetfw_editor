import json
import os
import threading
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection
from django.db.models import QuerySet
from django.test import Client
from django.test.utils import CaptureQueriesContext

from editor import config_validation, views
from editor.config_cleanup import remove_category
from editor.config_store import InvalidConfigError, StaleConfigError, config_token, save_project_config
from editor.config_validation import MAX_JSON_BYTES
from editor.models import Project, ProjectUser, SpecItem
from editor.project_config import load_template, new_project_config
from tests.backend import is_mysql
from tests.project_config.base import BACKEND, World, make_item, make_project, make_user, messages_of

pytestmark = pytest.mark.django_db

GET_ENDPOINTS = ('project_config', 'project_config_download', 'project_config_reload')
POST_ENDPOINTS = ('project_config_validate', 'project_config_upload', 'project_config_save')
ALL_ENDPOINTS = GET_ENDPOINTS + POST_ENDPOINTS
LOGIN_URL = '/editor/login/'
NON_OWNERS = ('ro_user', 'rw_user', 'staff', 'other_owner')
OWNER_ONLY = (302, '/editor', ['This operation is only accessible to the owner of project Proj'])


def writes(queries):
    return [q['sql'] for q in queries if q['sql'].split(None, 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE')]


def refusal(response):
    """(status, redirect target, messages) of a response, to compare with OWNER_ONLY."""
    return response.status_code, response.get('Location'), messages_of(response)


def changed_config():
    config = new_project_config()
    config['cats']['Packet']['page_size'] = 7
    return config


class EndpointWorld(World):
    """World with an RO member, a staff user who is not the owner and project 'Other' of another owner;
    owner_client is logged in as the owner of Proj."""

    def __init__(self, client):
        super().__init__(client)
        self.ro_user = make_user('ro_user')
        ProjectUser.objects.create(project=self.project, user=self.ro_user, role='RO')
        self.staff = make_user('staff_user', is_staff=True)
        self.other_owner = make_user('other_owner')
        self.other_project, self.other_val_set = make_project('Other', owner=self.other_owner)
        self.owner_client = self.client_for(self.owner)

    def client_for(self, user, **kwargs):
        client = Client(**kwargs)
        client.force_login(user, backend=BACKEND)
        return client

    def curl(self, name, project=None):
        return self.url(name, (project or self.project).id)

    def stored(self, project=None):
        return Project.objects.get(id=(project or self.project).id).config

    def token(self, project=None):
        return config_token(self.stored(project))

    def store(self, config, project=None):
        Project.objects.filter(id=(project or self.project).id).update(config=config)

    def post_json(self, client, name, body, token=None, project=None, **headers):
        if not isinstance(body, (str, bytes)):
            body = json.dumps(body)
        if token is not None:
            headers['X-Config-Token'] = token
        return client.post(self.curl(name, project), data=body, content_type='application/json', headers=headers)

    def save(self, client, config, token=None, project=None, **headers):
        token = self.token(project) if token is None else token
        return self.post_json(client, 'project_config_save', config, token, project, **headers)

    def upload(self, client, content, project=None):
        return client.post(self.curl('project_config_upload', project),
                           {'upload_file': SimpleUploadedFile('config.json', content)})

    def call(self, client, name, project=None):
        """A request which would succeed for the owner (current token, valid configuration)."""
        if name in GET_ENDPOINTS:
            return client.get(self.curl(name, project))
        if name == 'project_config_upload':
            return self.upload(client, json.dumps(new_project_config()).encode(), project)
        return self.post_json(client, name, new_project_config(), self.token(project), project)


@pytest.fixture
def w(client):
    return EndpointWorld(client)


# ------------------------------------------------------------------ access

@pytest.mark.parametrize('name', ALL_ENDPOINTS)
def test_the_owner_may_use_every_endpoint(w, name):
    assert w.call(w.owner_client, name).status_code == 200


@pytest.mark.parametrize('name', ALL_ENDPOINTS)
def test_anonymous_users_are_redirected_to_the_login_page(w, name):
    w.store(load_template())
    before = w.stored()
    response = w.call(Client(), name)
    assert response.status_code == 302
    assert response['Location'].startswith(LOGIN_URL), response['Location']
    assert w.stored() == before


@pytest.mark.parametrize('name', ALL_ENDPOINTS)
@pytest.mark.parametrize('who', NON_OWNERS)
def test_nobody_but_the_owner_has_access(w, who, name):
    client = w.client_for(getattr(w, who))
    before = w.stored()
    with CaptureQueriesContext(connection) as queries:
        response = w.call(client, name)
    assert refusal(response) == OWNER_ONLY
    assert w.stored() == before
    assert writes(queries.captured_queries) == []
    assert b'"config"' not in response.content       # nothing of the configuration leaks


def test_a_staff_owner_is_the_owner_like_any_other(w):
    w.owner.is_staff = True
    w.owner.save()
    assert w.call(w.client_for(w.owner), 'project_config_reload').status_code == 200


@pytest.mark.parametrize('who', ('rw_user', 'staff', 'other_owner'))
def test_the_method_of_a_post_endpoint_is_checked_before_the_owner(w, who):
    for name in POST_ENDPOINTS:
        assert w.client_for(getattr(w, who)).get(w.curl(name)).status_code == 405, name
    for name in GET_ENDPOINTS:
        assert refusal(w.client_for(getattr(w, who)).post(w.curl(name))) == OWNER_ONLY, name


@pytest.mark.parametrize('name', ALL_ENDPOINTS)
def test_an_unknown_project_is_an_error(w, name):
    url = w.url(name, Project.objects.order_by('-id').first().id + 100)
    send = w.owner_client.get if name in GET_ENDPOINTS else w.owner_client.post
    with pytest.raises(Project.DoesNotExist):
        send(url)


def test_each_project_has_its_own_owner(w):
    assert w.call(w.client_for(w.other_owner), 'project_config_reload', w.other_project).status_code == 200
    response = w.call(w.owner_client, 'project_config_reload', w.other_project)
    assert refusal(response) == (302, '/editor', ['This operation is only accessible to the owner of project Other'])


def test_post_endpoints_accept_only_post_and_get_endpoints_any_method(w):
    for name in POST_ENDPOINTS:
        response = w.owner_client.get(w.curl(name))
        assert response.status_code == 405
        assert response['Allow'] == 'POST'
        for method in ('put', 'delete', 'patch'):
            assert getattr(w.owner_client, method)(w.curl(name)).status_code == 405, (name, method)
    for name in GET_ENDPOINTS:
        for method in ('post', 'put', 'delete'):
            assert getattr(w.owner_client, method)(w.curl(name)).status_code == 200, (name, method)
    assert w.stored() == new_project_config()


def test_a_get_cannot_change_the_configuration(w):
    for name in POST_ENDPOINTS:
        w.owner_client.get(w.curl(name) + '?config=%7B%7D')
    assert w.stored() == new_project_config()


# ------------------------------------------------------------------ CSRF

@pytest.fixture
def csrf_client(w):
    """A client of the owner which enforces the CSRF checks like a browser does (the default test client does not)."""
    return w.client_for(w.owner, enforce_csrf_checks=True)


def csrf_cookie(w, client):
    assert client.get(w.curl('project_config')).status_code == 200       # sets the cookie
    return client.cookies['csrftoken'].value


@pytest.mark.parametrize('name', POST_ENDPOINTS)
def test_posts_without_a_csrf_token_are_rejected_and_change_nothing(w, csrf_client, name):
    before = w.stored()
    assert w.call(csrf_client, name).status_code == 403
    assert w.stored() == before


def test_a_wrong_csrf_token_is_rejected(w, csrf_client):
    csrf_cookie(w, csrf_client)
    response = w.save(csrf_client, changed_config(), **{'X-CSRFToken': 'x' * 64})
    assert response.status_code == 403
    assert w.stored() == new_project_config()


def test_with_the_csrf_token_the_posts_work(w, csrf_client):
    cookie = csrf_cookie(w, csrf_client)
    assert w.post_json(csrf_client, 'project_config_validate', new_project_config(),
                       **{'X-CSRFToken': cookie}).status_code == 200
    assert w.save(csrf_client, changed_config(), **{'X-CSRFToken': cookie}).status_code == 200
    assert w.stored()['cats']['Packet']['page_size'] == 7
    upload = csrf_client.post(w.curl('project_config_upload'),
                              {'upload_file': SimpleUploadedFile('c.json', json.dumps(new_project_config()).encode())},
                              headers={'X-CSRFToken': cookie})
    assert upload.status_code == 200


def test_the_csrf_check_is_not_bypassed_for_a_non_owner(w):
    client = w.client_for(w.rw_user, enforce_csrf_checks=True)
    assert w.call(client, 'project_config_save').status_code == 403


# ------------------------------------------------------------------ page, reload and download

def test_reload_returns_the_stored_configuration_and_its_token(w):
    config = changed_config()
    w.store(config)
    body = w.owner_client.get(w.curl('project_config_reload')).json()
    assert body['config'] == config
    assert body['token'] == config_token(config)
    assert body['token'].startswith('sha256:')


def test_a_new_project_shows_the_template_without_server_settings(w):
    body = w.owner_client.get(w.curl('project_config_reload')).json()
    assert body['config'] == new_project_config()
    assert 'temp_dir' not in body['config']['general']
    assert body['token'] == config_token(new_project_config())


def test_reload_changes_nothing(w):
    w.store(changed_config())
    updated = w.project.updated_at
    with CaptureQueriesContext(connection) as queries:
        w.owner_client.get(w.curl('project_config_reload'))
    assert writes(queries.captured_queries) == []
    assert Project.objects.get(id=w.project.id).updated_at == updated


def test_reload_does_not_touch_stored_items(w):
    make_item(w.project, 'Requirement', 'D', 'r1', p_kind='STD')
    rows = list(SpecItem.objects.values())
    w.owner_client.get(w.curl('project_config_reload'))
    assert list(SpecItem.objects.values()) == rows


def test_reload_after_a_change_by_somebody_else_shows_it(w):
    old = w.owner_client.get(w.curl('project_config_reload')).json()
    newer = changed_config()
    w.store(newer)
    body = w.owner_client.get(w.curl('project_config_reload')).json()
    assert body['config'] == newer
    assert body['token'] != old['token']


def test_download_is_a_json_file_which_can_be_uploaded_again(w):
    w.store(changed_config())
    response = w.owner_client.get(w.curl('project_config_download'))
    assert response['Content-Type'] == 'application/json; charset=utf-8'
    assert response['Content-Disposition'] == 'attachment; filename="cordetfw_project_%d_config.json"' % w.project.id
    assert json.loads(response.content) == changed_config()
    uploaded = w.upload(w.owner_client, response.content)
    assert uploaded.status_code == 200
    assert uploaded.json()['config'] == changed_config()


def test_the_download_of_a_new_project_is_valid(w):
    response = w.owner_client.get(w.curl('project_config_download'))
    assert w.post_json(w.owner_client, 'project_config_validate', response.content).status_code == 200


def test_the_page_shows_the_configuration_and_token_escaped(w):
    config = changed_config()
    config['cats']['Packet']['name'] = '<script>alert(1)</script>'
    w.store(config)
    response = w.owner_client.get(w.curl('project_config'))
    assert response.status_code == 200
    content = response.content.decode()
    assert '<script>alert(1)' not in content
    # The configuration is the attribute data-config, autoescaped
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in content
    assert 'data-token="%s"' % config_token(config) in content
    assert w.curl('project_config_save') in content


@pytest.mark.parametrize('name', GET_ENDPOINTS)
def test_responses_have_no_cache_headers(w, name):
    assert not w.owner_client.get(w.curl(name)).has_header('Cache-Control')


@pytest.mark.parametrize('name', ('project_config_reload', 'project_config_download', 'project_config'))
def test_server_settings_in_a_stored_configuration_are_never_served(w, name):
    config = new_project_config()
    config['general']['temp_dir'] = '/somewhere/else'
    w.store(config)
    assert '/somewhere/else' not in w.owner_client.get(w.curl(name)).content.decode()


# ------------------------------------------------------------------ validate and upload

def test_a_valid_configuration_is_reported_valid_without_a_write(w):
    config = changed_config()
    with CaptureQueriesContext(connection) as queries:
        response = w.post_json(w.owner_client, 'project_config_validate', config)
    assert response.status_code == 200
    assert response.json() == {'valid': True, 'errors': [], 'config': config}
    assert writes(queries.captured_queries) == []
    assert w.stored() == new_project_config()


def test_an_invalid_configuration_gets_errors_with_paths(w):
    config = new_project_config()
    config['cats']['Packet']['page_size'] = 0
    config['cats']['Service']['level'] = 'galaxy'
    response = w.post_json(w.owner_client, 'project_config_validate', config)
    assert response.status_code == 422
    body = response.json()
    assert not body['valid']
    assert {e['path'] for e in body['errors']} == {'cats.Packet.page_size', 'cats.Service.level'}
    assert all(e['message'] for e in body['errors'])
    assert w.stored() == new_project_config()


def test_stored_data_errors_surface_through_the_endpoint(w):
    make_item(w.project, 'Requirement', 'D', 'r1', p_kind='STD')
    config = new_project_config()
    del config['cats']['Requirement']['p_kind_choices']['STD']
    response = w.post_json(w.owner_client, 'project_config_validate', config)
    assert response.status_code == 422
    assert [e['path'] for e in response.json()['errors']] == ['cats.Requirement.p_kind_choices']


def test_a_server_setting_in_the_payload_is_rejected(w):
    config = new_project_config()
    config['general']['temp_dir'] = '/tmp/elsewhere'
    for response in (w.post_json(w.owner_client, 'project_config_validate', config), w.save(w.owner_client, config)):
        assert response.status_code == 422
        assert [e['path'] for e in response.json()['errors']] == ['general.temp_dir']
    assert w.stored() == new_project_config()
    upload = w.upload(w.owner_client, json.dumps(config).encode())
    assert [e['path'] for e in upload.json()['errors']] == ['general.temp_dir']


MALFORMED_BODIES = {
    'not json': b'{', 'blank': b'  ', 'list': b'[]', 'null': b'null', 'number': b'1', 'string': b'"x"',
    'not utf-8': b'\xff\xfe{}', 'nan': b'{"general": NaN}', 'duplicate key': b'{"general": {}, "general": {}, "cats": {}}',
    'too deep': b'[' * 20000 + b']' * 20000, 'wrong shape': b'{"cats": 5, "general": []}',
}


@pytest.mark.parametrize('body', list(MALFORMED_BODIES.values()), ids=list(MALFORMED_BODIES))
def test_malformed_bodies_are_errors_not_server_errors(w, body):
    for response in (w.post_json(w.owner_client, 'project_config_validate', body),
                     w.post_json(w.owner_client, 'project_config_save', body, token=w.token()),
                     w.upload(w.owner_client, body)):
        assert response.status_code == 422
        assert response.json()['errors']
    assert w.stored() == new_project_config()


def test_the_duplicate_key_is_reported_with_its_path(w):
    response = w.post_json(w.owner_client, 'project_config_validate', b'{"general": {}, "general": {}, "cats": {}}')
    assert 'general' in [e['path'] for e in response.json()['errors']]


@pytest.mark.parametrize('name', ('project_config_validate', 'project_config_save'))
def test_the_content_type_must_be_json(w, name):
    response = w.owner_client.post(w.curl(name), data=json.dumps(new_project_config()), content_type='text/plain',
                                   headers={'X-Config-Token': w.token()})
    assert response.status_code == 415
    assert w.stored() == new_project_config()


def test_an_oversized_body_is_refused_before_it_is_read(w):
    too_big = b' ' * (MAX_JSON_BYTES + 1)
    for name in ('project_config_validate', 'project_config_save'):
        assert w.post_json(w.owner_client, name, too_big, token=w.token()).status_code == 413, name
    assert w.upload(w.owner_client, too_big).status_code == 413
    assert w.stored() == new_project_config()


def test_upload_returns_the_content_and_stores_nothing(w):
    config = changed_config()
    with CaptureQueriesContext(connection) as queries:
        response = w.upload(w.owner_client, json.dumps(config).encode())
    assert response.status_code == 200
    assert response.json() == {'valid': True, 'errors': [], 'config': config}
    assert writes(queries.captured_queries) == []
    assert w.stored() == new_project_config()


def test_an_invalid_upload_is_reported_and_stores_nothing(w):
    config = new_project_config()
    config['cats']['Packet']['page_size'] = 'many'
    response = w.upload(w.owner_client, json.dumps(config).encode())
    assert response.status_code == 422
    assert [e['path'] for e in response.json()['errors']] == ['cats.Packet.page_size']
    assert response.json()['config'] == config              # the editor can show it with the errors
    assert w.stored() == new_project_config()


def test_an_upload_needs_a_file(w):
    response = w.owner_client.post(w.curl('project_config_upload'), {'other': 'x'})
    assert response.status_code == 400
    assert w.stored() == new_project_config()


def test_preview_and_upload_leave_no_server_side_draft(w, settings):
    before = [model.objects.count() for model in (Project, SpecItem)]
    rows = list(Project.objects.values())
    files_before = sorted(os.listdir(settings.TEST_ROOT))
    w.post_json(w.owner_client, 'project_config_validate', changed_config())
    w.upload(w.owner_client, json.dumps(changed_config()).encode())
    assert list(Project.objects.values()) == rows
    assert [model.objects.count() for model in (Project, SpecItem)] == before
    assert sorted(os.listdir(settings.TEST_ROOT)) == files_before
    assert w.owner_client.get(w.curl('project_config_reload')).json()['config'] == new_project_config()


def test_validation_is_the_shared_validator(w):
    with mock.patch.object(config_validation, 'validate_config', wraps=config_validation.validate_config) as validate:
        w.upload(w.owner_client, json.dumps(new_project_config()).encode())
        w.post_json(w.owner_client, 'project_config_validate', new_project_config())
        w.save(w.owner_client, new_project_config())
    assert validate.call_count == 3
    for call in validate.call_args_list:
        assert call.args[1].id == w.project.id             # always against the project's data


# ------------------------------------------------------------------ save

def test_a_valid_save_stores_the_configuration_and_returns_the_new_token(w):
    config = changed_config()
    token = w.token()
    response = w.save(w.owner_client, config)
    assert response.status_code == 200
    body = response.json()
    assert body['saved']
    assert w.stored() == config
    assert body['token'] == config_token(config)
    assert body['token'] != token
    assert w.owner_client.get(w.curl('project_config_reload')).json() == {'config': config, 'token': body['token']}


def test_the_new_token_allows_the_next_save(w):
    first = w.save(w.owner_client, changed_config()).json()['token']
    second = changed_config()
    second['cats']['Packet']['page_size'] = 8
    assert w.save(w.owner_client, second, token=first).status_code == 200
    assert w.stored()['cats']['Packet']['page_size'] == 8


def test_an_invalid_save_leaves_the_stored_configuration_unchanged(w):
    stored = changed_config()
    w.store(stored)
    invalid = changed_config()
    invalid['cats']['Packet']['page_size'] = -1
    updated = Project.objects.get(id=w.project.id).updated_at
    response = w.save(w.owner_client, invalid)
    assert response.status_code == 422
    body = response.json()
    assert not body['saved']
    assert [e['path'] for e in body['errors']] == ['cats.Packet.page_size']
    assert w.stored() == stored
    assert Project.objects.get(id=w.project.id).updated_at == updated


def test_a_save_without_a_token_is_refused(w):
    response = w.post_json(w.owner_client, 'project_config_save', changed_config())
    assert response.status_code == 428
    assert w.stored() == new_project_config()


@pytest.mark.parametrize('token', ['x', 'sha256:' + '0' * 64, 'garbage', config_token({'x': 1})])
def test_a_save_with_a_wrong_token_is_a_conflict(w, token):
    assert w.save(w.owner_client, changed_config(), token=token).status_code == 409
    assert w.stored() == new_project_config()


def test_a_stale_save_is_a_conflict_and_does_not_overwrite_newer_data(w):
    editor_a, editor_b = w.token(), w.token()                   # both loaded the same state
    newer = changed_config()
    assert w.save(w.owner_client, newer, token=editor_a).status_code == 200
    mine = new_project_config()
    mine['cats']['Packet']['page_size'] = 9
    response = w.save(w.owner_client, mine, token=editor_b)
    assert response.status_code == 409
    assert response.json()['errors'][0]['path'] == ''
    assert 'reload' in response.json()['errors'][0]['message']
    assert 'token' not in response.json()                       # no token which would allow overwriting
    assert w.stored() == newer


def test_a_conflict_is_reported_before_the_validation_errors(w):
    loaded = w.token()
    w.store(changed_config())
    invalid = new_project_config()
    invalid['cats']['Packet']['page_size'] = 0
    assert w.save(w.owner_client, invalid, token=loaded).status_code == 409


def test_the_token_does_not_depend_on_the_key_order(w):
    config = changed_config()
    reordered = {'cats': dict(list(config['cats'].items())[::-1]), 'general': config['general']}
    assert config_token(config) == config_token(reordered)
    w.store(reordered)
    assert w.save(w.owner_client, config, token=config_token(config)).status_code == 200


def test_saving_a_configuration_which_hides_a_category_with_data_keeps_the_data(w):
    service = make_item(w.project, 'Service', 'D', 's1', title='kept')
    make_item(w.project, 'Packet', 'D', 'p1', p_link=service, p_kind='')
    rows = list(SpecItem.objects.order_by('id').values())
    config = remove_category(new_project_config(), 'Packet')      # the cleanup the editor applies first
    response = w.save(w.owner_client, config)
    assert response.status_code == 200, response.content
    assert 'Packet' not in w.stored()['cats']
    assert list(SpecItem.objects.order_by('id').values()) == rows


def test_a_save_changes_no_other_project(w):
    other_config = load_template()
    w.store(other_config, w.other_project)
    w.save(w.owner_client, changed_config())
    assert w.stored(w.other_project) == other_config


@pytest.mark.parametrize('who', NON_OWNERS)
def test_a_non_owner_cannot_save_even_with_the_right_token(w, who):
    assert refusal(w.save(w.client_for(getattr(w, who)), changed_config())) == OWNER_ONLY
    assert w.stored() == new_project_config()


def test_saving_the_configuration_of_a_new_project_unchanged_keeps_its_token(w):
    token = w.token()
    response = w.save(w.owner_client, new_project_config())
    assert response.status_code == 200
    assert response.json()['token'] == token
    assert w.stored() == new_project_config()


# ------------------------------------------------------------------ the next request

def packet_choices(w, client):
    response = client.get(w.add_url('DataItem'))
    assert response.status_code == 200
    return set(response.context['form'].fields['p_link'].queryset.values_list('id', flat=True))


def test_a_saved_setting_applies_to_the_next_request_without_a_restart(w):
    item_type = make_item(w.project, 'DataItemType', 'D', 't')
    enum_type = make_item(w.project, 'EnumType', 'D', 'e')
    assert packet_choices(w, w.owner_client) == {item_type.id, enum_type.id}
    config = new_project_config()
    config['cats']['DataItem']['links']['p_link']['targets'] = ['EnumType']
    assert w.save(w.owner_client, config).status_code == 200
    assert packet_choices(w, w.owner_client) == {enum_type.id}
    assert packet_choices(w, w.client_for(w.rw_user)) == {enum_type.id}      # every user, new client


def test_a_failed_save_does_not_change_the_next_request(w):
    item_type = make_item(w.project, 'DataItemType', 'D', 't')
    config = new_project_config()
    config['cats']['DataItem']['links']['p_link']['targets'] = ['EnumType']
    config['cats']['Packet']['page_size'] = 0
    assert w.save(w.owner_client, config).status_code == 422
    assert item_type.id in packet_choices(w, w.owner_client)


def test_another_project_is_not_affected(w):
    other_type = make_item(w.other_project, 'DataItemType', 'D', 't')
    config = new_project_config()
    config['cats']['DataItem']['links']['p_link']['targets'] = ['EnumType']
    w.save(w.owner_client, config)
    response = w.client_for(w.other_owner).get(w.url('add_spec_item', 'DataItem', w.other_project.id, 0, 'Sel_All', 0))
    assert other_type.id in response.context['form'].fields['p_link'].queryset.values_list('id', flat=True)


def test_server_settings_come_from_the_server_not_from_the_project(w):
    config = new_project_config()
    config['general']['temp_dir'] = '/does/not/exist'
    w.store(config)                                             # bypasses the validator on purpose
    assert w.owner_client.get(w.url('export_project', w.project.id)).status_code == 200


# ------------------------------------------------------------------ concurrent saves

@pytest.mark.django_db(transaction=True)
def test_the_token_is_compared_with_the_value_read_under_the_lock(w):
    # The editor loaded the configuration; a competing save commits after this request has been
    # accepted but before it locks the project: the stale save must be refused.
    token = w.token()
    competing = changed_config()
    real = views.is_project_owner
    done = []

    def owner_check_then_competing_save(request, project):
        result = real(request, project)
        if not done:
            done.append(True)
            Project.objects.filter(id=project.id).update(config=competing)
        return result

    with mock.patch.object(views, 'is_project_owner', owner_check_then_competing_save):
        response = w.save(w.owner_client, new_project_config(), token=token)
    assert done == [True]
    assert response.status_code == 409
    assert w.stored() == competing


@pytest.mark.django_db(transaction=True)
def test_the_row_is_locked_before_the_token_is_checked_and_inside_the_transaction(w):
    calls = []
    original = QuerySet.select_for_update

    def spy(queryset, *args, **kwargs):
        calls.append((queryset.model, connection.in_atomic_block))
        return original(queryset, *args, **kwargs)

    with mock.patch.object(QuerySet, 'select_for_update', spy), CaptureQueriesContext(connection) as queries:
        assert w.save(w.owner_client, changed_config()).status_code == 200
    assert calls == [(Project, True)]
    locking = [q['sql'] for q in queries.captured_queries if 'FOR UPDATE' in q['sql']]
    assert bool(locking) == connection.features.has_select_for_update       # MySQL: SELECT ... FOR UPDATE
    if locking:
        assert 'editor_project' in locking[0]


def test_a_save_which_fails_validation_does_not_hold_or_write(w):
    invalid = new_project_config()
    invalid['cats']['Packet']['page_size'] = 0
    with pytest.raises(InvalidConfigError):
        save_project_config(w.project.id, json.dumps(invalid), w.token())
    assert w.stored() == new_project_config()


@pytest.mark.django_db(transaction=True)
def test_only_one_of_two_parallel_saves_with_the_same_token_wins():
    # Really in parallel: each save has its own connection, so its own thread.
    project, _ = make_project('Race', owner=make_user('owner'))
    token = config_token(Project.objects.get(id=project.id).config)
    bodies = []
    for size in (5, 6):
        config = new_project_config()
        config['cats']['Packet']['page_size'] = size
        bodies.append(json.dumps(config))
    barrier = threading.Barrier(2)
    results = [None, None]

    def attempt(i):
        try:
            barrier.wait(timeout=10)
            results[i] = save_project_config(project.id, bodies[i], token)
        except StaleConfigError:
            results[i] = 'stale'
        except OperationalError:
            results[i] = 'locked'                      # SQLite: single writer, the loser fails and writes nothing
        finally:
            connection.close()                         # the connection of this thread

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    winners = [r for r in results if r not in ('stale', 'locked')]
    stored = Project.objects.get(id=project.id).config
    if is_mysql():
        assert sorted(r if r == 'stale' else 'won' for r in results) == ['stale', 'won'], results
    assert len(winners) <= 1, results                  # SQLite (shared in-memory cache) may fail both
    if winners:
        assert stored['cats']['Packet']['page_size'] in (5, 6)
        assert winners[0] == config_token(stored)
    else:
        assert stored == new_project_config()


# ------------------------------------------------------------------ the hidden setting of an attribute
# The editor works on the stored configuration, which keeps the hidden attributes, not on the shown one.

def test_the_hidden_setting_is_saved_reloaded_and_downloaded(w):
    config = new_project_config()
    config['cats']['Service']['attrs']['rationale']['hidden'] = True
    response = w.save(w.owner_client, config)
    assert response.status_code == 200, response.content
    assert w.stored()['cats']['Service']['attrs']['rationale']['hidden'] is True
    reloaded = w.owner_client.get(w.curl('project_config_reload')).json()
    assert reloaded['config']['cats']['Service']['attrs']['rationale']['hidden'] is True
    assert reloaded['token'] == config_token(w.stored())
    download = json.loads(w.owner_client.get(w.curl('project_config_download')).content)
    assert download['cats']['Service']['attrs']['rationale']['hidden'] is True
    page = w.owner_client.get(w.curl('project_config'))
    assert json.loads(page.context['initial_config'])['cats']['Service']['attrs']['rationale']['hidden'] is True


def test_an_invalid_hidden_setting_is_not_saved(w):
    config = new_project_config()
    config['cats']['Service']['attrs']['name']['hidden'] = True
    response = w.save(w.owner_client, config)
    assert response.status_code == 422
    assert [e['path'] for e in response.json()['errors']] == ['cats.Service.attrs.name.hidden']
    assert w.stored() == new_project_config()


def test_the_preview_shows_the_pages_without_the_hidden_field_and_lists_it(w):
    config = new_project_config()
    definition = config['cats']['Service']
    definition['attrs']['rationale']['hidden'] = True
    body = w.post_json(w.owner_client, 'project_config_preview', config).json()
    assert body['valid'], body
    heading = '<strong class="fs-5 me-2">%s</strong>' % definition['name']
    service = next(part for part in body['html'].split('<div class="accordion-item">') if heading in part)
    label = definition['attrs']['rationale']['label']
    assert 'Hidden fields' in service
    assert '%s (rationale)' % label in service
    assert 'rationale, ' not in service                 # not a field of the preview form
    assert label + ' /' not in service                  # not in a column of the preview layouts
    assert '/ ' + label not in service
