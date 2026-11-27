"""One end-to-end test per acceptance criterion (1-14), through the real endpoints and views; finer grained tests
live in the other modules of this package."""
import copy
import csv
import io
import json
import pathlib
import re
import tempfile
import zipfile

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, override_settings
from django.urls import reverse

from editor import config_validation
from editor.config_store import config_token
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.project_config import get_project_config, load_template
from tests.project_config.base import BACKEND
from tests.project_config.test_project_config_endpoints import ALL_ENDPOINTS, GET_ENDPOINTS, LOGIN_URL, EndpointCase

PRODUCTION = pathlib.Path(__file__).resolve().parents[2] / 'editor'


class AcceptanceTests(EndpointCase):

    def setUp(self):
        super().setUp()
        self.other_owner_client = self.client_for(self.other_owner)
        self.login(self.owner)                          # self.client acts as the owner of self.project
        self.other_val_set = ValSet.objects.get(project=self.other_project, name='Default')

    def cfg(self, project=None):
        return copy.deepcopy(get_project_config(Project.objects.get(id=(project or self.project).id)))

    def save_ok(self, config, project=None, client=None):
        project = project or self.project
        client = client or (self.owner_client if project == self.project else self.other_owner_client)
        response = self.save(client, config, project=project)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['token']

    def widget(self, config, source='Service', **changes):
        definition = copy.deepcopy(config['cats'][source])
        definition.update(name='Widget', abbr='Wdg', expand={'s_link': 'None', 'p_link': 'None'}, tracs=[])
        definition.update(changes)
        config['cats']['Widget'] = definition
        return config

    def add_to_project_cats(self, cat, project=None):
        project = project or self.project
        Project.objects.filter(id=project.id).update(cats=project.cats + ',' + cat)

    def snapshot(self, project=None):
        project = project or self.project
        return {
            'items': list(SpecItem.objects.filter(project=project).order_by('id').values()),
            'releases': list(Release.objects.order_by('id').values()),
            'applications': list(Application.objects.filter(project=project).order_by('id')
                                 .values('id', 'name', 'cats', 'release_id')),
            'project_cats': Project.objects.get(id=project.id).cats,
            'val_sets': list(ValSet.objects.filter(project=project).order_by('id').values()),
            'users': list(ProjectUser.objects.filter(project=project).order_by('id').values()),
        }

    def export_bytes(self, project, client=None):
        response = (client or self.owner_client).get(self.curl('export_project', project))
        self.assertEqual(response.status_code, 200)
        return b''.join(response.streaming_content)

    def spec_item_rows(self, archive):
        member = zipfile.ZipFile(io.BytesIO(archive)).read('spec_items.csv').decode()
        return list(csv.DictReader(io.StringIO(member, newline='')))

    def import_archive(self, data, user=None):
        client = self.client_for(user or self.staff)
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = client.post(reverse('import_project'), {'upload_file': SimpleUploadedFile('p.zip', data)})
        return [str(m) for m in get_messages(response.wsgi_request)]

    def remove(self, config, cat, attr=None, client=None):
        body = {'config': config, 'cat': cat}
        if attr:
            body['attr'] = attr
        response = self.post_json(client or self.owner_client, 'project_config_remove', body)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['config']

    def test_criterion_01_two_projects_have_the_same_category_with_different_settings(self):
        first, second = self.cfg(), self.cfg(self.other_project)
        first['cats']['Service'].update(name='Alpha Service', page_size=2)
        first['cats']['Service']['attrs']['title']['label'] = 'Alpha Title'
        second['cats']['Service'].update(name='Beta Service', page_size=3, abbr='BSvc')
        second['cats']['Service']['attrs']['title']['label'] = 'Beta Title'
        self.save_ok(first)
        self.save_ok(second, self.other_project)
        for project in (self.project, self.other_project):
            for n in range(1, 5):
                self.make_item(project, 'Service', 'D', 'svc%d' % n, title='T%d' % n, status='CNF')

        alpha = self.owner_client.get(self.list_url('Service', val_set=self.default_val_set))
        beta = self.other_owner_client.get(self.list_url('Service', project=self.other_project,
                                                         val_set=self.other_val_set))
        self.assertEqual((alpha.context['config']['name'], len(alpha.context['page_items'])), ('Alpha Service', 2))
        self.assertEqual((beta.context['config']['name'], len(beta.context['page_items'])), ('Beta Service', 3))
        self.assertNotContains(alpha, 'Beta Service')
        self.assertNotContains(beta, 'Alpha Service')
        form = self.owner_client.get(self.add_url('Service')).context['form']
        other_form = self.other_owner_client.get(
            self.url('add_spec_item', 'Service', self.other_project.id, 0, 'Sel_All', 0)).context['form']
        self.assertEqual((form.fields['title'].label, other_form.fields['title'].label), ('Alpha Title', 'Beta Title'))
        self.assertEqual(self.stored()['cats']['Service']['name'], 'Alpha Service')
        self.assertEqual(self.stored(self.other_project)['cats']['Service']['abbr'], 'BSvc')
        self.assertNotEqual(self.stored()['cats']['Service']['abbr'], 'BSvc')

    def test_criterion_02_the_owner_adds_a_category_saves_and_creates_an_item_without_code(self):
        self.assertFalse(self.owner.is_staff)               # the owner needs no staff status
        config = self.widget(self.cfg(), page_size=5)
        self.save_ok(config)
        self.assertIn('Widget', self.stored()['cats'])

        add_url = self.add_url('Widget')
        payload = self.form_payload(add_url, domain='W', name='w1', title='First widget', value='v')
        response = self.client.post(add_url, payload)
        self.assertEqual(response.status_code, 302,
                         response.context['form'].errors if response.status_code == 200 else '')
        item = SpecItem.objects.get(cat='Widget', name='w1')
        self.assertEqual((item.project_id, item.title, item.value), (self.project.id, 'First widget', 'v'))
        listed = self.client.get(self.list_url('Widget'))
        self.assertContains(listed, 'First widget')
        self.assertEqual(listed.context['config']['name'], 'Widget')

        # Menus also need the category in Project.cats (changed by staff through "edit project").
        self.assertNotContains(self.client.get('/editor/'), 'Manage Widgets')
        self.add_to_project_cats('Widget')
        self.assertContains(self.client.get('/editor/'), 'Manage Widgets')

    def test_criterion_03_validation_checks_structure_types_limits_references_and_data(self):
        self.make_item(self.project, 'Requirement', 'R', 'req', p_kind='STD', title='t')
        invalid = {}

        def case(name, mutate, expected_path):
            config = self.cfg()
            mutate(config)
            invalid[name] = (config, expected_path)

        case('structure: unknown top-level key', lambda c: c.update(extra={}), 'extra')
        case('structure: category setting missing', lambda c: c['cats']['Service'].pop('page_size'),
             'cats.Service.page_size')
        case('type: page size is not a number', lambda c: c['cats']['Service'].update(page_size='many'),
             'cats.Service.page_size')
        case('limit: page size out of range', lambda c: c['cats']['Service'].update(page_size=100000),
             'cats.Service.page_size')
        case('model limit: attribute is not a SpecItem field',
             lambda c: c['cats']['Service']['attrs'].update(bogus={'label': 'B', 'kind': 'plain_text',
                                                                   'req_in_form': False}),
             'cats.Service.attrs.bogus')
        case('field kind not allowed for the field', lambda c: c['cats']['Service']['attrs']['n1'].update(kind='image')
             if 'n1' in c['cats']['Service']['attrs'] else c['cats']['Service']['attrs']['title'].update(kind='image'),
             'cats.Service.attrs.')
        case('reference: layout names an unknown attribute',
             lambda c: c['cats']['Service']['disp_def'][0]['attrs'].append('nope'), 'cats.Service.disp_def[0].attrs')
        case('reference: relationship names an unknown category',
             lambda c: c['cats']['Packet']['links']['p_link'].update(targets=['NoSuchCat']), 'cats.Packet.links.p_link')
        case('server setting inside the project configuration', lambda c: c['general'].update(temp_dir='/etc'),
             'general.temp_dir')
        case('data: a stored kind is no longer offered',
             lambda c: c['cats']['Requirement']['p_kind_choices'].pop('STD'), 'cats.Requirement.p_kind_choices')
        stored = self.stored()
        for name, (config, path) in invalid.items():
            with self.subTest(name):
                response = self.save(self.owner_client, config)
                self.assertEqual(response.status_code, 422, name)
                self.assertTrue(any(e['path'].startswith(path) for e in response.json()['errors']),
                                (path, response.json()['errors']))
                self.assertEqual(self.stored(), stored)

        # Removing definitions is allowed with data when the remaining JSON is consistent; no data is deleted.
        before = self.snapshot()
        config = self.remove(self.cfg(), 'Requirement')
        self.assertEqual(config_validation.validate_config(config, self.project), [])
        self.save_ok(config)
        self.assertNotIn('Requirement', self.stored()['cats'])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(SpecItem.objects.filter(cat='Requirement', name='req', p_kind='STD').exists())

    def test_criterion_04_a_saved_configuration_applies_to_the_next_request_without_restart(self):
        self.make_item(self.project, 'Service', 'D', 'svc', title='T')
        url = self.list_url('Service')
        self.assertNotContains(self.client.get(url), 'Renamed Service')
        config = self.cfg()
        config['cats']['Service']['name'] = 'Renamed Service'
        self.save_ok(config)
        for client in (self.client, self.client_for(self.rw_user), Client()):       # other session, other user
            if client is not self.client and client.session.get('_auth_user_id') is None:
                client.force_login(self.rw_user, backend=BACKEND)
            self.assertContains(client.get(url), 'Renamed Service')
        # the same request path in a fresh Client: no per-process or shared state needed
        self.assertEqual(self.client_for(self.rw_user).get(url).context['config']['name'], 'Renamed Service')

    def test_criterion_05_preview_failed_saves_reload_and_stale_saves(self):
        stored = self.stored()
        draft = self.cfg()
        draft['cats']['Service']['name'] = 'Draft Service'
        response = self.post_json(self.owner_client, 'project_config_preview', draft)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Draft Service', response.json()['html'])
        self.assertEqual(self.stored(), stored)
        broken = copy.deepcopy(draft)
        broken['cats']['Service']['page_size'] = 0
        response = self.save(self.owner_client, broken)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.stored(), stored)
        self.assertNotIn('html', self.post_json(self.owner_client, 'project_config_preview', broken).json())
        reloaded = self.owner_client.get(self.curl('project_config_reload')).json()
        self.assertEqual(reloaded['config'], get_project_config(self.project))
        self.assertEqual(reloaded['token'], config_token(self.stored()))
        self.assertEqual(self.stored(), stored)
        # Two editors started from the same state: the second save is a conflict and does not overwrite
        editor_token = reloaded['token']
        first = self.cfg()
        first['cats']['Service']['name'] = 'First Writer'
        second = self.cfg()
        second['cats']['Service']['name'] = 'Second Writer'
        self.assertEqual(self.save(self.owner_client, first, editor_token).status_code, 200)
        conflict = self.save(self.owner_client, second, editor_token)
        self.assertEqual(conflict.status_code, 409)
        self.assertNotIn('token', conflict.json())              # a client cannot go on without reloading
        self.assertEqual(self.stored()['cats']['Service']['name'], 'First Writer')
        fresh = self.owner_client.get(self.curl('project_config_reload')).json()
        self.assertEqual(fresh['config']['cats']['Service']['name'], 'First Writer')
        self.assertEqual(self.save(self.owner_client, second, fresh['token']).status_code, 200)
        # The editor asks before discarding unsaved changes on reload (browser behavior, static guard + manual check)
        script = (PRODUCTION / 'static' / 'project_config.js').read_text(encoding='utf-8')
        self.assertIn('Discard unsaved changes?', script)
        self.assertIn('state.conflict = true', script)

    def test_criterion_06_removing_a_field_does_not_delete_its_values_also_after_editing(self):
        item = self.make_item(self.project, 'Requirement', 'R', 'req', title='Req', value='v', p_kind='STD',
                              s_kind='TST', rationale='keep this rationale', remarks='keep these remarks')
        config = self.remove(self.cfg(), 'Requirement', 'rationale')
        config = self.remove(config, 'Requirement', 'remarks')
        self.save_ok(config)
        self.assertNotIn('rationale', self.stored()['cats']['Requirement']['attrs'])
        edit_url = self.item_url('edit_spec_item', item)
        form = self.client.get(edit_url).context['form']
        self.assertEqual([f.name for f in form if f.name in ('rationale', 'remarks') and not f.is_hidden], [])
        payload = self.form_payload(edit_url, title='Edited')
        for hidden in ('rationale', 'remarks'):                 # a client may omit or forge the hidden values
            payload.pop(hidden, None)
        payload['rationale'] = 'forged'
        response = self.client.post(edit_url, payload)
        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.status_code == 200 else '')
        item = self.refresh(item)
        self.assertEqual((item.title, item.rationale, item.remarks, item.p_kind, item.s_kind),
                         ('Edited', 'keep this rationale', 'keep these remarks', 'STD', 'TST'))
        restored = self.cfg()
        restored['cats']['Requirement']['attrs']['rationale'] = load_template()['cats']['Requirement']['attrs']['rationale']
        self.save_ok(restored)
        self.assertContains(self.client.get(edit_url), 'keep this rationale')

    def test_criterion_07_a_category_can_be_hidden_without_touching_items_history_releases_or_assignments(self):
        project = self.project
        info = self.make_item(project, 'InfoItem', 'I', 'info', title='Info', value='iv')
        info2 = self.make_item(project, 'InfoItem', 'I', 'info2', title='Info 2', previous=info, status='MOD')
        svc = self.make_item(project, 'Service', 'S', 'svc', title='Svc')
        pkt = self.make_item(project, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc)
        Release.objects.create(release_author=self.owner, desc='R1', updated_at=info.updated_at, project_version=1,
                               application_version=0)
        before = self.snapshot()
        config = self.remove(self.cfg(), 'Service')                  # a category others link to
        config = self.remove(config, 'InfoItem')
        self.save_ok(config)
        self.assertNotIn('Service', self.stored()['cats'])
        self.assertEqual(self.snapshot(), before)               # items (previous, links), releases, apps, cats, users
        self.assertEqual(self.refresh(pkt).p_link_id, svc.id)
        self.assertEqual(self.refresh(info2).previous_id, info.id)
        self.assertEqual(self.client.get(self.list_url('Packet')).status_code, 200)

    def test_criterion_08_restoring_a_category_shows_its_items_hidden_ones_do_not_break_references_and_export_keeps_them(self):
        svc = self.make_item(self.project, 'Service', 'S', 'svc', title='Svc', status='CNF')
        pkt = self.make_item(self.project, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc, status='CNF')
        full = self.cfg()
        self.save_ok(self.remove(self.cfg(), 'Service'))
        self.assertEqual(self.client.get(self.list_url('Service')).status_code, 404)
        # references and other pages still render; the reference is the plain identifier
        listed = self.client.get(self.list_url('Packet'))
        self.assertEqual(listed.status_code, 200)
        self.assertContains(listed, 'S:svc')
        self.assertEqual(self.client.get('/editor/').status_code, 200)
        self.assertEqual(self.client.get(self.item_url('edit_spec_item', pkt)).status_code, 200)
        rows = self.spec_item_rows(self.export_bytes(self.project))
        self.assertIn(('Service', 'svc'), [(r['cat'], r['name']) for r in rows])
        self.save_ok(full)
        restored = self.client.get(self.list_url('Service'))
        self.assertEqual(restored.status_code, 200)
        self.assertEqual([i.name for i in restored.context['page_items']], ['svc'])

    def test_criterion_09_only_the_project_owner_can_access_or_modify_the_configuration(self):
        stored = self.stored()
        valid = self.cfg()
        valid['cats']['Service']['name'] = 'Hijacked'
        token = self.token()
        non_owners = {'rw member': self.client_for(self.rw_user), 'ro member': self.client_for(self.ro_user),
                      'staff non-owner': self.client_for(self.staff),
                      'owner of another project': self.client_for(self.other_owner),
                      'staff superuser': self.client_for(self.make_user('boss', is_staff=True, is_superuser=True))}
        extra = {'project_config_preview': 'POST', 'project_config_remove': 'POST'}
        for who, client in non_owners.items():
            for name in ALL_ENDPOINTS + tuple(extra):
                with self.subTest(who=who, endpoint=name):
                    url = self.curl(name)
                    if name in GET_ENDPOINTS:
                        response = client.get(url)
                    elif name == 'project_config_upload':
                        response = client.post(url, {'upload_file': SimpleUploadedFile('c.json', json.dumps(valid).encode())})
                    elif name == 'project_config_remove':
                        response = client.post(url, data=json.dumps({'config': valid, 'cat': 'Service'}),
                                               content_type='application/json')
                    else:
                        response = client.post(url, data=json.dumps(valid), content_type='application/json',
                                               headers={'X-Config-Token': token})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn(b'csv_sep', response.content)          # no configuration leaks
        anonymous = Client()
        for name in ALL_ENDPOINTS:
            response = (anonymous.get if name in GET_ENDPOINTS else anonymous.post)(self.curl(name))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response['Location'].startswith(LOGIN_URL))
        self.assertEqual(self.stored(), stored)
        # the owner is let in; state-changing endpoints are POST only and CSRF protected
        self.assertEqual(self.owner_client.get(self.curl('project_config')).status_code, 200)
        self.assertEqual(self.owner_client.get(self.curl('project_config_save')).status_code, 405)
        enforcing = self.client_for(self.owner, enforce_csrf_checks=True)
        response = enforcing.post(self.curl('project_config_save'), data=json.dumps(valid),
                                  content_type='application/json', headers={'X-Config-Token': token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.stored(), stored)
        self.assertIn(self.curl('project_config'), self.owner_client.get('/editor/').content.decode())
        self.assertNotIn(self.curl('project_config'), self.client_for(self.rw_user).get('/editor/').content.decode())

    def test_criterion_10_forms_lists_references_import_export_and_history_use_the_projects_configuration(self):
        first, second = self.cfg(), self.cfg(self.other_project)
        first['cats']['Service']['name'] = 'Alpha Service'
        first['general']['csv_sep'] = ';'
        second['cats']['Service']['name'] = 'Beta Service'
        self.save_ok(first)
        self.save_ok(second, self.other_project)
        a = self.make_item(self.project, 'Service', 'D', 'svc', title='Svc A', status='CNF')
        b = self.make_item(self.other_project, 'Service', 'D', 'svc', title='Svc B', status='CNF')
        self.make_item(self.project, 'Packet', 'P', 'pkt', title='Pkt', p_link=a, status='CNF')
        self.assertContains(self.owner_client.get(self.list_url('Service')), 'Alpha Service')
        self.assertContains(self.other_owner_client.get(
            self.list_url('Service', project=self.other_project, val_set=self.other_val_set)), 'Beta Service')
        history = self.url('list_spec_item_history', 'Service', self.project.id, 0, a.id, 'Sel_All')
        self.assertEqual(self.owner_client.get(history).context['config']['name'], 'Alpha Service')
        self.assertContains(self.owner_client.get(self.list_url('Packet')), 'D:svc')
        # item CSV export: separator and labels of the project
        csv_url = self.url('export_spec_items', 'Service', self.project.id, 0, self.default_val_set.id, 'Sel_All', 0)
        other_csv = self.url('export_spec_items', 'Service', self.other_project.id, 0, self.other_val_set.id,
                             'Sel_All', 0)
        self.assertIn(';', self.owner_client.get(csv_url).content.decode().splitlines()[0])
        self.assertIn('|', self.other_owner_client.get(other_csv).content.decode().splitlines()[0])
        archive = self.export_bytes(self.project)
        members = {n: zipfile.ZipFile(io.BytesIO(archive)).read(n) for n in zipfile.ZipFile(io.BytesIO(archive)).namelist()}
        self.assertEqual(json.loads(members['config.json']), self.cfg())
        self.assertEqual(json.loads(self.export_bytes_of(self.other_project))['cats']['Service']['name'], 'Beta Service')
        # import restores the archived configuration; the original is renamed to free the project name
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        messages = self.import_archive(archive)
        imported = Project.objects.filter(name='Proj').exclude(id=self.project.id).get()
        self.assertEqual(imported.config, self.cfg(), messages)
        self.assertEqual(SpecItem.objects.filter(project=imported).count(), SpecItem.objects.filter(
            project=self.project).count())
        # an archive without a configuration gets the template filtered to the imported data
        old = io.BytesIO()
        with zipfile.ZipFile(old, 'w') as z:
            for name, content in members.items():
                if name != 'config.json':
                    z.writestr(name, content)
        Project.objects.filter(id=imported.id).update(name='Proj_imported')
        self.import_archive(old.getvalue())
        derived = Project.objects.filter(name='Proj').exclude(id__in=[self.project.id, imported.id]).get()
        self.assertEqual(config_validation.validate_config(derived.config, derived), [])
        self.assertEqual(set(derived.config['cats']), {c for c in self.project.cats.split(',')} |
                         set(SpecItem.objects.filter(project=derived).values_list('cat', flat=True)))
        self.assertNotIn('temp_dir', derived.config['general'])
        self.assertEqual(b.title, 'Svc B')                      # the other project was never touched
        self.assertEqual(self.stored(self.other_project)['cats']['Service']['name'], 'Beta Service')

    def export_bytes_of(self, project):
        """config.json of the project archive, as text."""
        archive = self.export_bytes(project, self.other_owner_client if project == self.other_project else None)
        return zipfile.ZipFile(io.BytesIO(archive)).read('config.json').decode()

    def test_criterion_11_the_configuration_is_one_json_column_without_history_status_or_files(self):
        from django.apps import apps
        from django.db import models as dj_models, connection
        field = Project._meta.get_field('config')
        self.assertIsInstance(field, dj_models.JSONField)
        self.assertEqual(field.default, dict)
        model_names = [m.__name__ for m in apps.get_app_config('editor').get_models()]
        self.assertEqual([n for n in model_names if 'config' in n.lower()], [])
        self.assertEqual([f.name for f in Project._meta.get_fields() if 'config' in f.name or 'status' in f.name], ['config'])
        migration = __import__('editor.migrations.0014_project_config', fromlist=['Migration']).Migration
        self.assertEqual([(type(op).__name__, op.model_name, op.name) for op in migration.operations],
                         [('AddField', 'project', 'config')])

        def counts():
            return {m.__name__: m.objects.count() for m in (Project, SpecItem, Release, ValSet, ProjectUser,
                                                            Application)}
        before, files = counts(), sorted(p.name for p in pathlib.Path(tempfile.gettempdir()).iterdir())
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            for n in range(3):
                config = self.cfg()
                config['cats']['Service']['page_size'] = 10 + n
                self.save_ok(config)
                self.post_json(self.owner_client, 'project_config_preview', config)
                self.owner_client.get(self.curl('project_config_download'))
            self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])         # no server-side configuration file
        self.assertEqual(counts(), before)                      # no new rows: no history, no statuses
        self.assertEqual(self.stored()['cats']['Service']['page_size'], 12)       # only the current value is kept
        with connection.cursor() as cursor:
            tables = {t for t in connection.introspection.table_names(cursor) if t.startswith('editor_')}
        self.assertFalse([t for t in tables if 'config' in t])

    def test_criterion_12_existing_and_new_categories_use_the_same_relationship_rules_and_validators(self):
        service = self.make_item(self.project, 'Service', 'D', 'svc', title='Svc')
        enum_type = self.make_item(self.project, 'EnumType', 'D', 'et', title='ET')
        config = self.widget(self.cfg(), source='Packet')                  # a new category with Packet's rules
        config['cats']['Widget']['links'] = copy.deepcopy(config['cats']['Packet']['links'])
        self.save_ok(config)
        def p_link_choices(cat):
            form = self.client.get(self.add_url(cat)).context['form']
            return [c[0] for c in form.fields['p_link'].choices if c[0]]
        self.assertEqual(p_link_choices('Widget'), p_link_choices('Packet'))
        self.assertEqual(p_link_choices('Packet'), [service.id])
        for cat in ('Packet', 'Widget'):
            url = self.add_url(cat)
            payload = self.add_payload('Packet', {'p_link': service}, name=cat.lower() + '1')
            response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 302, (cat, response.context['form'].errors if response.status_code == 200 else ''))
            bad = self.client.post(url, self.add_payload('Packet', {'p_link': enum_type}, name=cat.lower() + '2'))
            self.assertEqual(bad.status_code, 200, cat)
            self.assertIn('p_link', bad.context['form'].errors)
            self.assertFalse(SpecItem.objects.filter(cat=cat, name=cat.lower() + '2').exists())
        # configuration selects validators by name only; an unknown name is rejected, never imported or executed
        bad = self.cfg()
        bad['cats']['Widget']['validators'] = [{'name': 'os.system', 'params': {}}]
        response = self.save(self.owner_client, bad)
        self.assertEqual(response.status_code, 422)
        self.assertIn('cats.Widget.validators[0].name', [e['path'] for e in response.json()['errors']])
        # no category name decides anything in production code or templates
        cats = list(load_template()['cats'])
        pattern = re.compile(r'''['"](%s)['"]''' % '|'.join(cats))
        offenders = []
        for path in list(PRODUCTION.rglob('*.py')) + list(PRODUCTION.glob('templates/**/*.html')) + \
                list(PRODUCTION.glob('static/*.js')):
            if 'migrations' in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if pattern.search(line):
                    offenders.append('%s:%d' % (path.relative_to(PRODUCTION), number))
        self.assertEqual(offenders, [])

    def test_criterion_13_removing_a_definition_asks_for_confirmation_naming_it_and_promising_the_data_is_kept(self):
        script = (PRODUCTION / 'static' / 'project_config.js').read_text(encoding='utf-8')
        text = re.sub(r"'\s*\+\s*'", '', script)                  # the texts as the dialog shows them
        self.assertEqual(text.count('Its saved data will not be deleted'), 2)
        self.assertIn('will be deleted from the configuration: the category is no longer shown in the menus, lists '
                      'and forms of this project', text)
        self.assertIn('will be deleted from the configuration: it is no longer shown in its forms, lists and CSV '
                      'exports', text)
        self.assertIn("confirmDialog(title, body, 'Delete', 'bi-trash-fill')", script)
        # tooltips on hover and focus; cancelling changes nothing (the state is only changed after the confirmation)
        self.assertIn("'data-bs-trigger': 'hover focus'", script)
        self.assertRegex(script, r"if \(!await confirmDialog\(title, body, 'Delete', 'bi-trash-fill'\)\) \{\s*"
                                 r"return;\s*\}\s*const payload = \{config: state\.config")
        # the page carries the remove endpoint and the confirmed action keeps the data: cleanup in the backend only
        page = self.owner_client.get(self.curl('project_config')).content.decode()
        self.assertIn(self.curl('project_config_remove'), page)
        item = self.make_item(self.project, 'Requirement', 'R', 'req', title='Req', rationale='kept')
        before = self.snapshot()
        cleaned = self.remove(self.cfg(), 'Requirement', 'rationale')
        self.assertNotIn('rationale', cleaned['cats']['Requirement']['attrs'])
        self.assertEqual(self.snapshot(), before)               # nothing stored and nothing deleted by the request
        self.assertEqual(self.refresh(item).rationale, 'kept')
        self.assertEqual(self.stored(), {})

    def test_criterion_14_existing_projects_are_initialized_from_the_template_filtered_to_their_data(self):
        legacy, _ = self.make_project('Legacy', owner=self.owner, cats=['Service', 'Packet'])
        app = self.make_application(legacy, 'LApp', cats=[])
        self.make_item(legacy, 'Service', 'D', 'svc', title='Svc')
        self.make_item(legacy, 'InfoItem', 'I', 'info', application=app, title='Info', value='v')   # not in cats
        self.assertEqual(Project.objects.get(id=legacy.id).config, {})
        before = self.snapshot(legacy)
        call_command('init_project_configs', stdout=io.StringIO(), stderr=io.StringIO())
        stored = self.stored(legacy)
        self.assertEqual(set(stored['cats']), {'Service', 'Packet', 'InfoItem'})   # cats + categories with data
        self.assertEqual(stored['cats']['Service']['attrs'], load_template()['cats']['Service']['attrs'])
        self.assertIn('title', stored['cats']['InfoItem']['attrs'])             # a field with data is kept
        self.assertNotIn('rationale', stored['cats']['InfoItem']['attrs'])      # an unused one is not
        self.assertNotIn('temp_dir', stored['general'])
        self.assertEqual(config_validation.validate_config(stored, legacy), [])
        self.assertEqual(self.snapshot(legacy), before)                         # data untouched
        # the other projects, which are also configured by the command, are independent of this one
        self.assertEqual(set(self.stored(self.project)['cats']), set(load_template()['cats']))
        call_command('init_project_configs', stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(self.stored(legacy), stored)
        # the owner reviews (download) and adjusts (save) the result
        client = self.client_for(self.owner)
        downloaded = json.loads(client.get(self.curl('project_config_download', legacy)).content)
        self.assertEqual(downloaded, stored)
        downloaded['cats']['Service']['page_size'] = 17
        self.assertEqual(self.save(client, downloaded, project=legacy).status_code, 200)
        self.assertEqual(self.stored(legacy)['cats']['Service']['page_size'], 17)
        call_command('init_project_configs', stdout=io.StringIO(), stderr=io.StringIO())
        self.assertEqual(self.stored(legacy)['cats']['Service']['page_size'], 17)   # the review survives re-runs
