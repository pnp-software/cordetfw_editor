"""Phase 6: owner-only configuration endpoints (editor/config_views.py) and the conflict-safe save
(editor/config_store.py)."""
import copy
import json
import threading
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection, connections
from django.db.models import QuerySet
from django.test import Client, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from editor import config_validation, config_views
from editor.config_cleanup import remove_category
from editor.config_store import StaleConfigError, config_token, save_project_config
from editor.config_validation import MAX_JSON_BYTES
from editor.models import Project, ProjectUser, SpecItem
from editor.project_config import get_project_config, load_template
from tests.backend import is_mysql
from tests.project_config.base import BACKEND, EditorTestCase

GET_ENDPOINTS = ('project_config', 'project_config_download', 'project_config_reload')
POST_ENDPOINTS = ('project_config_validate', 'project_config_upload', 'project_config_save')
ALL_ENDPOINTS = GET_ENDPOINTS + POST_ENDPOINTS
LOGIN_URL = '/editor/login/'


def writes(queries):
    return [q['sql'] for q in queries if q['sql'].split(None, 1)[0].upper() in ('INSERT', 'UPDATE', 'DELETE')]


class EndpointCase(EditorTestCase):
    """The project belongs to `owner`; rw_user is RW (logged in on self.client by the base class)."""

    def setUp(self):
        super().setUp()
        self.ro_user = self.make_user('ro_user')
        ProjectUser.objects.create(project=self.project, user=self.ro_user, role='RO')
        self.staff = self.make_user('staff_user', is_staff=True)
        self.other_owner = self.make_user('other_owner')
        self.other_project, _ = self.make_project('Other', owner=self.other_owner)
        self.owner_client = self.client_for(self.owner)

    def client_for(self, user, **kwargs):
        client = Client(**kwargs)
        if user is not None:
            client.force_login(user, backend=BACKEND)
        return client

    def curl(self, name, project=None):
        return reverse(name, args=[(project or self.project).id])

    def valid_config(self):
        return get_project_config(self.project)

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

    def upload(self, client, content, name='config.json', project=None):
        return client.post(self.curl('project_config_upload', project),
                           {'upload_file': SimpleUploadedFile(name, content)})

    def call(self, client, name, project=None):
        """A request which would succeed for the owner (current token, valid configuration)."""
        if name in GET_ENDPOINTS:
            return client.get(self.curl(name, project))
        if name == 'project_config_upload':
            return self.upload(client, json.dumps(self.valid_config()).encode(), project=project)
        return self.post_json(client, name, self.valid_config(), self.token(project), project)

    def changed_config(self):
        config = self.valid_config()
        config['cats']['Packet']['page_size'] = 7
        return config


class AccessTests(EndpointCase):
    def test_the_owner_may_use_every_endpoint(self):
        for name in ALL_ENDPOINTS:
            with self.subTest(endpoint=name):
                self.assertEqual(self.call(self.owner_client, name).status_code, 200)

    def test_anonymous_users_are_redirected_to_the_login_page(self):
        anonymous = Client()
        self.store(load_template())
        before = self.stored()
        for name in ALL_ENDPOINTS:
            with self.subTest(endpoint=name):
                response = self.call(anonymous, name)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(LOGIN_URL), response['Location'])
        self.assertEqual(self.stored(), before)

    def test_nobody_but_the_owner_has_access(self):
        users = {'RO member': self.ro_user, 'RW member': self.rw_user, 'staff, not the owner': self.staff,
                 'owner of another project': self.other_owner}
        for who, user in users.items():
            client = self.client_for(user)
            for name in ALL_ENDPOINTS:
                with self.subTest(user=who, endpoint=name):
                    before = self.stored()
                    with CaptureQueriesContext(connection) as queries:
                        response = self.call(client, name)
                    self.assertEqual(response.status_code, 403)
                    self.assertEqual(self.stored(), before)
                    self.assertEqual(writes(queries.captured_queries), [])
                    self.assertNotIn(b'"config"', response.content)       # nothing of the configuration leaks

    def test_a_staff_owner_is_the_owner_like_any_other(self):
        self.owner.is_staff = True
        self.owner.save()
        self.assertEqual(self.call(self.client_for(self.owner), 'project_config_reload').status_code, 200)

    def test_ownership_decides_before_the_http_method(self):
        for user in (self.rw_user, self.staff, self.other_owner):
            for name in ALL_ENDPOINTS:
                client = self.client_for(user)
                response = client.post(self.curl(name)) if name in GET_ENDPOINTS else client.get(self.curl(name))
                with self.subTest(user=user.username, endpoint=name):
                    self.assertEqual(response.status_code, 403)

    def test_an_unknown_project_is_forbidden_not_not_found(self):
        missing = Project.objects.order_by('-id').first().id + 100
        for name in ALL_ENDPOINTS:
            with self.subTest(endpoint=name):
                response = self.owner_client.get(reverse(name, args=[missing]))
                self.assertEqual(response.status_code, 403)

    def test_each_project_has_its_own_owner(self):
        self.assertEqual(self.call(self.client_for(self.other_owner), 'project_config_reload',
                                   self.other_project).status_code, 200)
        self.assertEqual(self.call(self.owner_client, 'project_config_reload', self.other_project).status_code, 403)

    def test_methods_are_restricted(self):
        for name in POST_ENDPOINTS:
            with self.subTest(endpoint=name, method='GET'):
                response = self.owner_client.get(self.curl(name))
                self.assertEqual(response.status_code, 405)
                self.assertEqual(response['Allow'], 'POST')
        for name in GET_ENDPOINTS:
            for method in ('post', 'put', 'delete'):
                with self.subTest(endpoint=name, method=method):
                    response = getattr(self.owner_client, method)(self.curl(name))
                    self.assertEqual(response.status_code, 405)
        for name in POST_ENDPOINTS:
            for method in ('put', 'delete', 'patch'):
                with self.subTest(endpoint=name, method=method):
                    self.assertEqual(getattr(self.owner_client, method)(self.curl(name)).status_code, 405)
        self.assertEqual(self.stored(), {})

    def test_a_get_cannot_change_the_configuration(self):
        for name in POST_ENDPOINTS:
            self.owner_client.get(self.curl(name) + '?config=%7B%7D')
        self.assertEqual(self.stored(), {})


class CsrfTests(EndpointCase):
    """Clients which enforce CSRF checks like a browser does (the default test client does not)."""

    def setUp(self):
        super().setUp()
        self.csrf_client = self.client_for(self.owner, enforce_csrf_checks=True)

    def csrf_token(self):
        self.assertEqual(self.csrf_client.get(self.curl('project_config')).status_code, 200)    # sets the cookie
        return self.csrf_client.cookies['csrftoken'].value

    def test_posts_without_a_csrf_token_are_rejected_and_change_nothing(self):
        for name in POST_ENDPOINTS:
            with self.subTest(endpoint=name):
                before = self.stored()
                response = self.call(self.csrf_client, name)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(self.stored(), before)

    def test_a_wrong_csrf_token_is_rejected(self):
        self.csrf_token()
        response = self.save(self.csrf_client, self.changed_config(), **{'X-CSRFToken': 'x' * 64})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.stored(), {})

    def test_with_the_csrf_token_the_posts_work(self):
        token = self.csrf_token()
        self.assertEqual(self.post_json(self.csrf_client, 'project_config_validate', self.valid_config(),
                                        **{'X-CSRFToken': token}).status_code, 200)
        self.assertEqual(self.save(self.csrf_client, self.changed_config(), **{'X-CSRFToken': token}).status_code, 200)
        self.assertEqual(self.stored()['cats']['Packet']['page_size'], 7)
        upload = self.csrf_client.post(self.curl('project_config_upload'),
                                       {'upload_file': SimpleUploadedFile('c.json', json.dumps(self.valid_config()).encode())},
                                       headers={'X-CSRFToken': token})
        self.assertEqual(upload.status_code, 200)

    def test_the_csrf_check_is_not_bypassed_for_a_non_owner(self):
        client = self.client_for(self.rw_user, enforce_csrf_checks=True)
        self.assertEqual(self.call(client, 'project_config_save').status_code, 403)


class ReadEndpointTests(EndpointCase):
    def test_reload_returns_the_stored_configuration_and_its_token(self):
        config = self.changed_config()
        self.store(config)
        body = self.owner_client.get(self.curl('project_config_reload')).json()
        self.assertEqual(body['config'], config)
        self.assertEqual(body['token'], config_token(config))
        self.assertTrue(body['token'].startswith('sha256:'))

    def test_an_unconfigured_project_shows_the_template_without_server_settings(self):
        body = self.owner_client.get(self.curl('project_config_reload')).json()
        self.assertEqual(body['config'], get_project_config(self.project))
        self.assertNotIn('temp_dir', body['config']['general'])
        self.assertEqual(body['token'], config_token({}))

    def test_reload_changes_nothing(self):
        self.store(self.changed_config())
        updated = self.project.updated_at
        with CaptureQueriesContext(connection) as queries:
            self.owner_client.get(self.curl('project_config_reload'))
        self.assertEqual(writes(queries.captured_queries), [])
        self.assertEqual(Project.objects.get(id=self.project.id).updated_at, updated)

    def test_reload_does_not_touch_stored_items(self):
        self.make_item(self.project, 'Requirement', 'D', 'r1', p_kind='STD')
        rows = list(SpecItem.objects.values())
        self.owner_client.get(self.curl('project_config_reload'))
        self.assertEqual(list(SpecItem.objects.values()), rows)

    def test_reload_after_a_change_by_somebody_else_shows_it(self):
        old = self.owner_client.get(self.curl('project_config_reload')).json()
        newer = self.changed_config()
        self.store(newer)
        body = self.owner_client.get(self.curl('project_config_reload')).json()
        self.assertEqual(body['config'], newer)
        self.assertNotEqual(body['token'], old['token'])

    def test_download_is_a_json_file_which_can_be_uploaded_again(self):
        self.store(self.changed_config())
        response = self.owner_client.get(self.curl('project_config_download'))
        self.assertEqual(response['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(response['Content-Disposition'],
                         'attachment; filename="cordetfw_project_%d_config.json"' % self.project.id)
        self.assertEqual(json.loads(response.content), self.changed_config())
        uploaded = self.upload(self.owner_client, response.content)
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()['config'], self.changed_config())

    def test_download_of_an_unconfigured_project_is_the_valid_template(self):
        response = self.owner_client.get(self.curl('project_config_download'))
        self.assertEqual(self.post_json(self.owner_client, 'project_config_validate', response.content).status_code, 200)

    def test_the_page_shows_the_configuration_and_token_escaped(self):
        config = self.changed_config()
        config['cats']['Packet']['name'] = '<script>alert(1)</script>'
        self.store(config)
        response = self.owner_client.get(self.curl('project_config'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn('<script>alert(1)', content)
        # Phase 8: the configuration is embedded with json_script (escaped for a <script> element)
        self.assertIn('\\u003Cscript\\u003Ealert(1)\\u003C/script\\u003E', content)
        self.assertIn('data-token="%s"' % config_token(config), content)
        self.assertIn(self.curl('project_config_save'), content)

    def test_responses_are_not_cached(self):
        for name in GET_ENDPOINTS:
            self.assertIn('no-store', self.owner_client.get(self.curl(name))['Cache-Control'])

    def test_server_settings_in_a_stored_configuration_are_never_served(self):
        config = self.valid_config()
        config['general']['temp_dir'] = '/somewhere/else'
        self.store(config)
        for name in ('project_config_reload', 'project_config_download', 'project_config'):
            with self.subTest(endpoint=name):
                self.assertNotIn('/somewhere/else', self.owner_client.get(self.curl(name)).content.decode())


class ValidateAndUploadTests(EndpointCase):
    def test_a_valid_configuration_is_reported_valid_without_a_write(self):
        config = self.changed_config()
        with CaptureQueriesContext(connection) as queries:
            response = self.post_json(self.owner_client, 'project_config_validate', config)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'valid': True, 'errors': [], 'config': config})
        self.assertEqual(writes(queries.captured_queries), [])
        self.assertEqual(self.stored(), {})

    def test_an_invalid_configuration_gets_errors_with_paths(self):
        config = self.valid_config()
        config['cats']['Packet']['page_size'] = 0
        config['cats']['Service']['level'] = 'galaxy'
        response = self.post_json(self.owner_client, 'project_config_validate', config)
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertFalse(body['valid'])
        self.assertEqual({e['path'] for e in body['errors']}, {'cats.Packet.page_size', 'cats.Service.level'})
        self.assertTrue(all(e['message'] for e in body['errors']))
        self.assertEqual(self.stored(), {})

    def test_stored_data_errors_surface_through_the_endpoint(self):
        self.make_item(self.project, 'Requirement', 'D', 'r1', p_kind='STD')
        config = self.valid_config()
        del config['cats']['Requirement']['p_kind_choices']['STD']
        response = self.post_json(self.owner_client, 'project_config_validate', config)
        self.assertEqual(response.status_code, 422)
        self.assertEqual([e['path'] for e in response.json()['errors']], ['cats.Requirement.p_kind_choices'])

    def test_a_server_setting_in_the_payload_is_rejected(self):
        config = self.valid_config()
        config['general']['temp_dir'] = '/tmp/elsewhere'
        for name in ('validate', 'save'):
            with self.subTest(endpoint=name):
                if name == 'validate':
                    response = self.post_json(self.owner_client, 'project_config_validate', config)
                else:
                    response = self.save(self.owner_client, config)
                self.assertEqual(response.status_code, 422)
                self.assertEqual([e['path'] for e in response.json()['errors']], ['general.temp_dir'])
        self.assertEqual(self.stored(), {})
        upload = self.upload(self.owner_client, json.dumps(config).encode())
        self.assertEqual([e['path'] for e in upload.json()['errors']], ['general.temp_dir'])

    def test_malformed_bodies_are_errors_not_server_errors(self):
        bodies = {'not json': b'{', 'blank': b'  ', 'list': b'[]', 'null': b'null', 'number': b'1', 'string': b'"x"',
                  'not utf-8': b'\xff\xfe{}', 'nan': b'{"general": NaN}',
                  'duplicate key': b'{"general": {}, "general": {}, "cats": {}}',
                  'too deep': b'[' * 20000 + b']' * 20000, 'wrong shape': b'{"cats": 5, "general": []}'}
        for what, body in bodies.items():
            for name in ('project_config_validate', 'project_config_save'):
                with self.subTest(body=what, endpoint=name):
                    response = self.post_json(self.owner_client, name, body, token=self.token()) \
                        if name == 'project_config_save' else self.post_json(self.owner_client, name, body)
                    self.assertEqual(response.status_code, 422)
                    self.assertTrue(response.json()['errors'])
            with self.subTest(body=what, endpoint='upload'):
                response = self.upload(self.owner_client, body)
                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.json()['errors'])
        self.assertEqual(self.stored(), {})

    def test_the_duplicate_key_is_reported_with_its_path(self):
        response = self.post_json(self.owner_client, 'project_config_validate',
                                  b'{"general": {}, "general": {}, "cats": {}}')
        self.assertIn('general', [e['path'] for e in response.json()['errors']])

    def test_the_content_type_must_be_json(self):
        for name in ('project_config_validate', 'project_config_save'):
            with self.subTest(endpoint=name):
                response = self.owner_client.post(self.curl(name), data=json.dumps(self.valid_config()),
                                                  content_type='text/plain', headers={'X-Config-Token': self.token()})
                self.assertEqual(response.status_code, 415)
        self.assertEqual(self.stored(), {})

    def test_an_oversized_body_is_refused_before_it_is_read(self):
        too_big = b' ' * (MAX_JSON_BYTES + 1)
        for name in ('project_config_validate', 'project_config_save'):
            with self.subTest(endpoint=name):
                response = self.post_json(self.owner_client, name, too_big, token=self.token())
                self.assertEqual(response.status_code, 413)
        self.assertEqual(self.upload(self.owner_client, too_big).status_code, 413)
        self.assertEqual(self.stored(), {})

    def test_upload_returns_the_content_and_stores_nothing(self):
        config = self.changed_config()
        with CaptureQueriesContext(connection) as queries:
            response = self.upload(self.owner_client, json.dumps(config).encode())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'valid': True, 'errors': [], 'config': config})
        self.assertEqual(writes(queries.captured_queries), [])
        self.assertEqual(self.stored(), {})

    def test_an_invalid_upload_is_reported_and_stores_nothing(self):
        config = self.valid_config()
        config['cats']['Packet']['page_size'] = 'many'
        response = self.upload(self.owner_client, json.dumps(config).encode())
        self.assertEqual(response.status_code, 422)
        self.assertEqual([e['path'] for e in response.json()['errors']], ['cats.Packet.page_size'])
        self.assertEqual(response.json()['config'], config)              # the editor can show it with the errors
        self.assertEqual(self.stored(), {})

    def test_an_upload_needs_a_file(self):
        response = self.owner_client.post(self.curl('project_config_upload'), {'other': 'x'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stored(), {})

    def test_preview_and_upload_leave_no_server_side_draft(self):
        before = {model.objects.count() for model in (Project, SpecItem)}
        rows = list(Project.objects.values())
        files_before = self.temp_files()
        self.post_json(self.owner_client, 'project_config_validate', self.changed_config())
        self.upload(self.owner_client, json.dumps(self.changed_config()).encode())
        self.assertEqual(list(Project.objects.values()), rows)
        self.assertEqual({model.objects.count() for model in (Project, SpecItem)}, before)
        self.assertEqual(self.temp_files(), files_before)
        self.assertEqual(self.owner_client.get(self.curl('project_config_reload')).json()['config'],
                         get_project_config(self.project))

    def temp_files(self):
        import os
        from django.conf import settings
        return sorted(os.listdir(settings.TEST_ROOT))

    def test_validation_is_the_shared_validator(self):
        with mock.patch.object(config_validation, 'validate_config', wraps=config_validation.validate_config) as validate:
            self.upload(self.owner_client, json.dumps(self.valid_config()).encode())
            self.post_json(self.owner_client, 'project_config_validate', self.valid_config())
            self.save(self.owner_client, self.valid_config())
        self.assertEqual(validate.call_count, 3)
        for call in validate.call_args_list:
            self.assertEqual(call.args[1].id, self.project.id)            # always against the project's data


class SaveTests(EndpointCase):
    def test_a_valid_save_stores_the_configuration_and_returns_the_new_token(self):
        config = self.changed_config()
        token = self.token()
        response = self.save(self.owner_client, config)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['saved'])
        self.assertEqual(self.stored(), config)
        self.assertEqual(body['token'], config_token(config))
        self.assertNotEqual(body['token'], token)
        self.assertEqual(self.owner_client.get(self.curl('project_config_reload')).json(),
                         {'config': config, 'token': body['token']})

    def test_the_new_token_allows_the_next_save(self):
        first = self.save(self.owner_client, self.changed_config()).json()['token']
        second = self.changed_config()
        second['cats']['Packet']['page_size'] = 8
        self.assertEqual(self.save(self.owner_client, second, token=first).status_code, 200)
        self.assertEqual(self.stored()['cats']['Packet']['page_size'], 8)

    def test_an_invalid_save_leaves_the_stored_configuration_unchanged(self):
        stored = self.changed_config()
        self.store(stored)
        invalid = copy.deepcopy(stored)
        invalid['cats']['Packet']['page_size'] = -1
        updated = Project.objects.get(id=self.project.id).updated_at
        response = self.save(self.owner_client, invalid)
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertFalse(body['saved'])
        self.assertEqual([e['path'] for e in body['errors']], ['cats.Packet.page_size'])
        self.assertEqual(self.stored(), stored)
        self.assertEqual(Project.objects.get(id=self.project.id).updated_at, updated)

    def test_a_save_without_a_token_is_refused(self):
        response = self.post_json(self.owner_client, 'project_config_save', self.changed_config())
        self.assertEqual(response.status_code, 428)
        self.assertEqual(self.stored(), {})

    def test_a_save_with_a_wrong_token_is_a_conflict(self):
        for token in ('', 'sha256:' + '0' * 64, 'garbage', config_token({'x': 1})):
            with self.subTest(token=token):
                response = self.save(self.owner_client, self.changed_config(), token=token or 'x')
                self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored(), {})

    def test_a_stale_save_is_a_conflict_and_does_not_overwrite_newer_data(self):
        editor_a, editor_b = self.token(), self.token()               # both loaded the same state
        newer = self.changed_config()
        self.assertEqual(self.save(self.owner_client, newer, token=editor_a).status_code, 200)
        mine = self.valid_config()
        mine['cats']['Packet']['page_size'] = 9
        response = self.save(self.owner_client, mine, token=editor_b)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['errors'][0]['path'], '')
        self.assertIn('reload', response.json()['errors'][0]['message'])
        self.assertNotIn('token', response.json())                     # no token which would allow overwriting
        self.assertEqual(self.stored(), newer)

    def test_a_conflict_is_reported_before_the_validation_errors(self):
        self.store(self.changed_config())
        invalid = self.valid_config()
        invalid['cats']['Packet']['page_size'] = 0
        self.assertEqual(self.save(self.owner_client, invalid, token=config_token({})).status_code, 409)

    def test_the_token_does_not_depend_on_the_key_order(self):
        config = self.changed_config()
        reordered = {'cats': dict(reversed(list(config['cats'].items()))), 'general': config['general']}
        self.assertEqual(config_token(config), config_token(reordered))
        self.store(reordered)
        self.assertEqual(self.save(self.owner_client, config, token=config_token(config)).status_code, 200)

    def test_saving_a_configuration_which_hides_a_category_with_data_keeps_the_data(self):
        service = self.make_item(self.project, 'Service', 'D', 's1', title='kept')
        self.make_item(self.project, 'Packet', 'D', 'p1', p_link=service, p_kind='')
        rows = list(SpecItem.objects.order_by('id').values())
        config = remove_category(self.valid_config(), 'Packet')      # the cleanup the editor applies first
        response = self.save(self.owner_client, config)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('Packet', self.stored()['cats'])
        self.assertEqual(list(SpecItem.objects.order_by('id').values()), rows)

    def test_a_save_changes_no_other_project(self):
        other_config = load_template()
        self.store(other_config, self.other_project)
        self.save(self.owner_client, self.changed_config())
        self.assertEqual(self.stored(self.other_project), other_config)

    def test_a_non_owner_cannot_save_even_with_the_right_token(self):
        for user in (self.rw_user, self.ro_user, self.staff, self.other_owner):
            with self.subTest(user=user.username):
                self.assertEqual(self.save(self.client_for(user), self.changed_config()).status_code, 403)
        self.assertEqual(self.stored(), {})

    def test_an_unconfigured_project_can_be_saved_from_the_template(self):
        self.assertEqual(self.stored(), {})
        self.assertEqual(self.save(self.owner_client, self.valid_config()).status_code, 200)
        self.assertEqual(self.stored(), self.valid_config())


class NextRequestTests(EndpointCase):
    def packet_choices(self, client):
        response = client.get(self.add_url('DataItem'))
        self.assertEqual(response.status_code, 200)
        return set(response.context['form'].fields['p_link'].queryset.values_list('id', flat=True))

    def test_a_saved_setting_applies_to_the_next_request_without_a_restart(self):
        item_type = self.make_item(self.project, 'DataItemType', 'D', 't')
        enum_type = self.make_item(self.project, 'EnumType', 'D', 'e')
        self.assertEqual(self.packet_choices(self.owner_client), {item_type.id, enum_type.id})
        config = self.valid_config()
        config['cats']['DataItem']['links']['p_link']['targets'] = ['EnumType']
        self.assertEqual(self.save(self.owner_client, config).status_code, 200)
        self.assertEqual(self.packet_choices(self.owner_client), {enum_type.id})
        self.assertEqual(self.packet_choices(self.client_for(self.rw_user)), {enum_type.id})   # every user, new client

    def test_a_failed_save_does_not_change_the_next_request(self):
        item_type = self.make_item(self.project, 'DataItemType', 'D', 't')
        config = self.valid_config()
        config['cats']['DataItem']['links']['p_link']['targets'] = ['EnumType']
        config['cats']['Packet']['page_size'] = 0
        self.assertEqual(self.save(self.owner_client, config).status_code, 422)
        self.assertIn(item_type.id, self.packet_choices(self.owner_client))

    def test_another_project_is_not_affected(self):
        other_type = self.make_item(self.other_project, 'DataItemType', 'D', 't')
        config = self.valid_config()
        config['cats']['DataItem']['links']['p_link']['targets'] = ['EnumType']
        self.save(self.owner_client, config)
        response = self.client_for(self.other_owner).get(
            reverse('add_spec_item', args=['DataItem', self.other_project.id, 0, 'Sel_All', 0]))
        self.assertIn(other_type.id, response.context['form'].fields['p_link'].queryset.values_list('id', flat=True))

    def test_server_settings_come_from_the_server_not_from_the_project(self):
        config = self.valid_config()
        config['general']['temp_dir'] = '/does/not/exist'
        self.store(config)                                             # bypasses the validator on purpose
        self.assertEqual(self.owner_client.get(reverse('export_project', args=[self.project.id])).status_code, 200)


class ConcurrencyTests(EndpointCase):
    def test_the_token_is_compared_with_the_value_read_under_the_lock(self):
        # The editor loaded the configuration; a competing save commits after this request has been
        # accepted but before it locks the project: the stale save must be refused.
        token = self.token()
        competing = self.changed_config()
        real = config_views.user_is_project_owner
        done = []

        def owner_check_then_competing_save(user, project):
            result = real(user, project)
            if not done:
                done.append(True)
                Project.objects.filter(id=project.id).update(config=competing)
            return result

        with mock.patch.object(config_views, 'user_is_project_owner', owner_check_then_competing_save):
            response = self.save(self.owner_client, self.valid_config(), token=token)
        self.assertEqual(done, [True])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored(), competing)

    def test_the_row_is_locked_before_the_token_is_checked_and_inside_the_transaction(self):
        calls = []
        original = QuerySet.select_for_update

        def spy(queryset, *args, **kwargs):
            calls.append((queryset.model, connection.in_atomic_block))
            return original(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, 'select_for_update', spy), CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.save(self.owner_client, self.changed_config()).status_code, 200)
        self.assertEqual(calls, [(Project, True)])
        locking = [q['sql'] for q in queries.captured_queries if 'FOR UPDATE' in q['sql']]
        self.assertEqual(bool(locking), connection.features.has_select_for_update)   # MySQL: SELECT ... FOR UPDATE
        if locking:
            self.assertIn('editor_project', locking[0])

    def test_a_save_which_fails_validation_does_not_hold_or_write(self):
        invalid = self.valid_config()
        invalid['cats']['Packet']['page_size'] = 0
        with self.assertRaises(Exception) as caught:
            save_project_config(self.project.id, json.dumps(invalid), self.token())
        self.assertEqual(type(caught.exception).__name__, 'InvalidConfigError')
        self.assertEqual(self.stored(), {})


class ConcurrentSaveTests(TransactionTestCase):
    """Two saves based on the same token, really in parallel (own connections): exactly one is applied."""

    def setUp(self):
        owner = EditorTestCase.make_user(self, 'owner')
        self.make_user = lambda name, **kw: EditorTestCase.make_user(self, name, **kw)
        self.project, _ = EditorTestCase.make_project(self, 'Race', owner=owner)

    def test_only_one_of_two_parallel_saves_with_the_same_token_wins(self):
        token = config_token(Project.objects.get(id=self.project.id).config)
        bodies = []
        for size in (5, 6):
            config = get_project_config(self.project)
            config['cats']['Packet']['page_size'] = size
            bodies.append(json.dumps(config))
        barrier = threading.Barrier(2)
        results = [None, None]

        def attempt(i):
            try:
                barrier.wait(timeout=10)
                results[i] = save_project_config(self.project.id, bodies[i], token)
            except StaleConfigError:
                results[i] = 'stale'
            except OperationalError:
                results[i] = 'locked'                      # SQLite: single writer, the loser fails and writes nothing
            finally:
                connections.close_all()

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        winners = [r for r in results if r not in ('stale', 'locked')]
        stored = Project.objects.get(id=self.project.id).config
        if is_mysql():
            self.assertEqual(sorted(r if r == 'stale' else 'won' for r in results), ['stale', 'won'], results)
        self.assertLessEqual(len(winners), 1, results)     # SQLite (shared in-memory cache) may fail both
        if winners:
            self.assertIn(stored['cats']['Packet']['page_size'], (5, 6))
            self.assertEqual(winners[0], config_token(stored))
        else:
            self.assertEqual(stored, {})
