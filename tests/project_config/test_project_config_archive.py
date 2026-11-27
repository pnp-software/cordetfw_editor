"""Phase 7: the project archive carries the project configuration (config.json) and import restores it."""
import copy
import csv
import io
import json
import tempfile
from django.test import override_settings
import zipfile
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile

from editor import imports
from editor.config_cleanup import remove_attribute, remove_category
from editor.config_store import config_token
from editor.config_validation import MAX_JSON_BYTES, validate_config
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.project_config import filter_template_for_data, load_template, resolve_config
from tests.project_config.base import EditorTestCase, TEMPLATE

CSV_MEMBERS = ['project.csv', 'applications.csv', 'val_sets.csv', 'project_users.csv', 'releases.csv', 'spec_items.csv']
UNSAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


class ArchiveTestCase(EditorTestCase):
    """Helpers: export, archive surgery, import as staff user, row counts."""

    def setUp(self):
        super().setUp()
        self.boss = self.make_user('boss', is_staff=True)

    def export_bytes(self, project):
        self.login(project.owner)
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.get(self.url('export_project', project.id))
            self.assertEqual(response.status_code, 200)
            return b''.join(response.streaming_content)

    def members(self, data):
        archive = zipfile.ZipFile(io.BytesIO(data))
        return {name: archive.read(name) for name in archive.namelist()}

    def archive(self, members):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return out.getvalue()

    def with_config(self, data, config):
        """The archive `data` with config.json replaced by `config` (a dict or the text; None removes it)."""
        members = self.members(data)
        members.pop('config.json', None)
        if config is not None:
            members['config.json'] = config if isinstance(config, (str, bytes)) else json.dumps(config)
        return self.archive(members)

    def import_zip(self, data):
        self.login(self.boss)
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.post(self.url('import_project'), {'upload_file': SimpleUploadedFile('p.zip', data)})
        return response, [str(m) for m in get_messages(response.wsgi_request)]

    def counts(self):
        return {model.__name__: model.objects.count()
                for model in (Project, Release, ValSet, ProjectUser, Application, SpecItem, User)}

    def stored(self, project):
        return Project.objects.get(id=project.id).config

    def import_as_copy(self, project, data=None):
        """Import an archive of `project` under its own name (the original is renamed)."""
        data = data if data is not None else self.export_bytes(project)
        name = project.name
        Project.objects.filter(id=project.id).update(name=name + '_original')
        response, messages = self.import_zip(data)
        return Project.objects.filter(name=name).exclude(id=project.id).first(), messages


class ConfiguredProjectTestCase(ArchiveTestCase):
    """A configured project with hidden data: a hidden field, a hidden category and a category of its own."""

    def setUp(self):
        super().setUp()
        p = self.project
        self.svc = self.make_item(p, 'Service', 'S', 'svc', title='Svc title', value='Type')
        self.req = self.make_item(p, 'Requirement', 'R', 'req', title='Req title', value='v', p_kind='STD', s_kind='TST')
        self.pkt = self.make_item(p, 'Packet', 'P', 'pkt', title='Pkt', p_link=self.svc, p_kind='TC', t1='x')
        self.info = self.make_item(p, 'InfoItem', 'I', 'info', title='hidden category data', value='iv')
        widget = self.make_item(p, 'InfoItem', 'W', 'w1', title='custom category data', value='wv')
        SpecItem.objects.filter(id=widget.id).update(cat='Widget')
        self.widget_id = widget.id

        config = resolve_config({})
        config = remove_category(config, 'InfoItem')                    # hidden category (items stay)
        config = remove_attribute(config, 'Service', 'title')           # hidden field (values stay)
        config = remove_attribute(config, 'Requirement', 'p_kind')      # hidden kind (values stay)
        config['cats']['Requirement']['page_size'] = 7
        widget_definition = copy.deepcopy(TEMPLATE['cats']['InfoItem'])
        widget_definition.update(name='Widget', abbr='Wdg')
        config['cats']['Widget'] = widget_definition
        self.config = config
        Project.objects.filter(id=p.id).update(config=config)
        self.project = Project.objects.get(id=p.id)
        self.assertEqual(validate_config(self.config, self.project), [])


class ExportTests(ConfiguredProjectTestCase):
    def test_the_archive_has_the_configuration_as_a_last_extra_member(self):
        names = zipfile.ZipFile(io.BytesIO(self.export_bytes(self.project))).namelist()
        self.assertEqual(names, CSV_MEMBERS + ['config.json'])

    def test_project_csv_keeps_its_columns(self):
        text = self.members(self.export_bytes(self.project))['project.csv'].decode()
        self.assertEqual(next(csv.reader(io.StringIO(text))),
                         ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release'])

    def test_config_json_is_the_stored_configuration(self):
        exported = json.loads(self.members(self.export_bytes(self.project))['config.json'])
        self.assertEqual(exported, self.config)
        self.assertNotIn('temp_dir', exported['general'])

    def test_an_unconfigured_project_exports_the_template_fallback(self):
        other, _ = self.make_project('Plain', owner=self.owner)
        exported = json.loads(self.members(self.export_bytes(other))['config.json'])
        self.assertEqual(exported, resolve_config({}))
        self.assertEqual(self.stored(other), {})                 # exporting does not store anything

    def test_a_server_setting_injected_into_the_stored_value_is_not_exported(self):
        stored = copy.deepcopy(self.config)
        stored['general']['temp_dir'] = '/somewhere/else'
        Project.objects.filter(id=self.project.id).update(config=stored)
        text = self.members(self.export_bytes(self.project))['config.json'].decode()
        self.assertNotIn('temp_dir', text)
        self.assertNotIn('/somewhere/else', text)

    def test_hidden_fields_and_categories_are_exported(self):
        rows = list(csv.DictReader(io.StringIO(self.members(self.export_bytes(self.project))['spec_items.csv'].decode())))
        by_name = {(r['cat'], r['name']): r for r in rows}
        self.assertEqual(by_name[('Service', 'svc')]['title'], 'Svc title')            # field hidden in the configuration
        self.assertEqual(by_name[('Requirement', 'req')]['p_kind'], 'STD')             # kind hidden
        self.assertEqual(by_name[('InfoItem', 'info')]['title'], 'hidden category data')   # category hidden
        self.assertEqual(by_name[('Widget', 'w1')]['value'], 'wv')

    def test_the_configuration_of_another_project_is_not_exported(self):
        other, _ = self.make_project('Other', owner=self.owner)
        other_config = resolve_config({})
        other_config['cats']['Service']['name'] = 'Different'
        Project.objects.filter(id=other.id).update(config=other_config)
        exported = json.loads(self.members(self.export_bytes(self.project))['config.json'])
        self.assertEqual(exported['cats']['Service']['name'], self.config['cats']['Service']['name'])
        self.assertNotEqual(exported['cats']['Service']['name'], 'Different')

    def test_export_still_requires_read_access(self):
        self.login(self.make_user('stranger'))
        response = self.client.get(self.url('export_project', self.project.id))
        self.assertEqual((response.status_code, response.url), (302, '/editor'))


class RoundTripTests(ConfiguredProjectTestCase):
    def test_the_configuration_is_restored_identically(self):
        imported, messages = self.import_as_copy(self.project)
        self.assertEqual(messages, [])
        self.assertEqual(self.stored(imported), self.config)
        self.assertEqual(json.dumps(self.stored(imported), sort_keys=True), json.dumps(self.config, sort_keys=True))
        self.assertEqual(validate_config(self.stored(imported), imported), [])

    def test_the_original_project_is_untouched(self):
        before = (self.stored(self.project), list(SpecItem.objects.filter(project=self.project).values_list('id', 'title')))
        imported, _ = self.import_as_copy(self.project)
        self.assertEqual((self.stored(self.project), list(SpecItem.objects.filter(project=self.project).values_list('id', 'title'))),
                         before)
        self.assertNotEqual(imported.id, self.project.id)

    def test_exporting_the_imported_project_gives_the_same_configuration(self):
        imported, _ = self.import_as_copy(self.project)
        again = json.loads(self.members(self.export_bytes(imported))['config.json'])
        self.assertEqual(again, self.config)

    def test_hidden_data_round_trips(self):
        imported, _ = self.import_as_copy(self.project)
        items = {(i.cat, i.name): i for i in SpecItem.objects.filter(project=imported)}
        self.assertEqual(items[('Service', 'svc')].title, 'Svc title')
        self.assertEqual((items[('Requirement', 'req')].p_kind, items[('Requirement', 'req')].s_kind), ('STD', 'TST'))
        self.assertEqual((items[('InfoItem', 'info')].title, items[('InfoItem', 'info')].value), ('hidden category data', 'iv'))
        self.assertEqual((items[('Widget', 'w1')].title, items[('Widget', 'w1')].value), ('custom category data', 'wv'))
        self.assertEqual(len(items), SpecItem.objects.filter(project=self.project).count())

    def test_relationships_point_into_the_new_project(self):
        imported, _ = self.import_as_copy(self.project)
        pkt = SpecItem.objects.get(project=imported, cat='Packet')
        self.assertEqual(pkt.p_link.name, 'svc')
        self.assertEqual(pkt.p_link.project_id, imported.id)
        self.assertNotEqual(pkt.p_link_id, self.svc.id)

    def test_the_import_creates_one_project_and_leaves_other_projects_alone(self):
        other, _ = self.make_project('Other', owner=self.owner)
        other_config = resolve_config({})
        other_config['cats']['Service']['name'] = 'Different'
        Project.objects.filter(id=other.id).update(config=other_config)
        other_item = self.make_item(other, 'Service', 'X', 'other', title='o')
        imported, _ = self.import_as_copy(self.project)
        self.assertEqual(self.stored(other), other_config)
        self.assertEqual(list(SpecItem.objects.filter(project=other).values_list('id', 'title')), [(other_item.id, 'o')])
        self.assertEqual(self.stored(imported)['cats']['Service']['name'], self.config['cats']['Service']['name'])

    def test_the_project_timestamp_of_the_archive_is_kept(self):
        original = Project.objects.get(id=self.project.id).updated_at
        imported, _ = self.import_as_copy(self.project)
        self.assertLess(abs((imported.updated_at - original).total_seconds()), 1)

    def test_the_archive_configuration_is_stored_by_the_shared_save_and_validated_after_the_links_exist(self):
        data = self.export_bytes(self.project)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        seen = []
        real = imports.save_project_config

        def spy(project_id, body, token):
            project = Project.objects.get(id=project_id)
            seen.append((project.name, token, SpecItem.objects.get(project=project, cat='Packet').p_link.project_id,
                         json.loads(body) == self.config))
            return real(project_id, body, token)

        with mock.patch('editor.imports.save_project_config', side_effect=spy):
            response, messages = self.import_zip(data)
        imported = Project.objects.get(name='Proj')
        self.assertEqual(messages, [])
        self.assertEqual(seen, [('Proj', config_token({}), imported.id, True)])

    def test_the_configuration_is_validated_against_the_imported_data(self):
        data = self.export_bytes(self.project)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        calls = []
        real = __import__('editor.config_validation', fromlist=['validate_config']).validate_config

        def spy(config, project=None):
            calls.append((project.id if project else None, SpecItem.objects.filter(project=project).count() if project else None))
            return real(config, project)

        with mock.patch('editor.config_validation.validate_config', side_effect=spy):
            self.import_zip(data)
        imported = Project.objects.get(name='Proj')
        self.assertIn((None, None), calls)                                    # structure, before any data exists
        self.assertIn((imported.id, SpecItem.objects.filter(project=imported).count()), calls)   # then the stored data


class ProtectionTests(ConfiguredProjectTestCase):
    def test_import_never_overwrites_the_configuration_of_an_existing_project(self):
        data = self.with_config(self.export_bytes(self.project), resolve_config({}))     # a different configuration
        before = (self.stored(self.project), self.counts())
        response, messages = self.import_zip(data)
        self.assertEqual(messages, ['A project called Proj already exists'])
        self.assertEqual((self.stored(self.project), self.counts()), before)

    def test_import_still_requires_a_staff_user(self):
        data = self.export_bytes(self.project)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        self.login(self.make_user('plain'))
        before = self.counts()
        response = self.client.post(self.url('import_project'), {'upload_file': SimpleUploadedFile('p.zip', data)})
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        self.assertEqual(self.counts(), before)

    def test_a_server_setting_in_the_archive_configuration_is_rejected(self):
        bad = copy.deepcopy(self.config)
        bad['general']['temp_dir'] = '/tmp/elsewhere'
        imported, messages = self.import_as_copy(self.project, self.with_config(self.export_bytes(self.project), bad))
        self.assertIsNone(imported)
        self.assertEqual(len(messages), 1)
        self.assertIn('general.temp_dir', messages[0])

    def import_unsafe_model(self, config):
        model = self.make_item(self.project, 'Model', 'M', 'm1', title='m', value=UNSAFE_SVG)
        imported, messages = self.import_as_copy(self.project, self.with_config(self.export_bytes(self.project), config))
        self.assertIsNotNone(imported)
        self.assertFalse(SpecItem.objects.filter(project=imported, cat='Model').exists())
        self.assertTrue(any('Model:M:m1' in m for m in messages), messages)
        self.assertTrue(SpecItem.objects.filter(id=model.id).exists())

    def test_hiding_the_category_in_the_archive_does_not_skip_the_svg_check(self):
        self.import_unsafe_model(remove_category(copy.deepcopy(self.config), 'Model'))

    def test_changing_the_value_kind_in_the_archive_does_not_skip_the_svg_check(self):
        config = copy.deepcopy(self.config)
        config['cats']['Model']['attrs']['value']['kind'] = 'plain_text'
        self.import_unsafe_model(config)

    def test_a_category_defined_nowhere_is_still_rejected(self):
        members = self.members(self.export_bytes(self.project))
        text = members['spec_items.csv'].decode().replace('Widget', 'Nowhere')
        members['spec_items.csv'] = text.encode()
        imported, messages = self.import_as_copy(self.project, self.archive(members))
        self.assertFalse(SpecItem.objects.filter(project=imported, cat='Nowhere').exists())
        self.assertTrue(any('the category Nowhere is not defined in configs.json' in m for m in messages), messages)


class InvalidConfigurationTests(ConfiguredProjectTestCase):
    """A rejected import leaves nothing behind: no project, releases, applications, ValSets, items, users."""

    def rejected(self, config):
        data = self.with_config(self.export_bytes(self.project), config)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        before = self.counts()
        response, messages = self.import_zip(data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.counts(), before)
        self.assertFalse(Project.objects.filter(name='Proj').exists())
        self.assertEqual(len(messages), 1, messages)
        self.assertIn('nothing was imported', messages[0])
        return messages[0]

    def test_malformed_json(self):
        self.assertIn('invalid JSON', self.rejected('{"general": '))

    def test_empty_file(self):
        self.assertIn('invalid JSON', self.rejected(''))

    def test_not_an_object(self):
        self.assertIn('the configuration must be a JSON object', self.rejected('[]'))

    def test_not_utf8(self):
        self.assertIn('config.json', self.rejected(b'\xff\xfe\x00{'))

    def test_unknown_setting_is_reported_with_its_path(self):
        bad = copy.deepcopy(self.config)
        bad['cats']['Service']['bogus'] = 1
        self.assertIn('cats.Service.bogus: unknown setting', self.rejected(bad))

    def test_wrong_type_is_reported_with_its_path(self):
        bad = copy.deepcopy(self.config)
        bad['cats']['Requirement']['page_size'] = 'seven'
        self.assertIn('cats.Requirement.page_size', self.rejected(bad))

    def test_duplicate_keys_are_reported(self):
        text = '{"general": %s, "general": {}, "cats": %s}' % (json.dumps(self.config['general']), json.dumps(self.config['cats']))
        message = self.rejected(text)
        self.assertIn('general', message)
        self.assertIn('more than once', message)

    def test_missing_relationship_settings_are_reported(self):
        bad = copy.deepcopy(self.config)
        del bad['cats']['Packet']['links']
        self.assertIn('cats.Packet.links: is required', self.rejected(bad))

    def test_several_problems_are_listed_and_counted(self):
        bad = copy.deepcopy(self.config)
        for cat in list(bad['cats'])[:15]:
            bad['cats'][cat]['page_size'] = 0
        message = self.rejected(bad)
        self.assertIn('and 5 more problem(s)', message)
        self.assertEqual(message.count('page_size'), imports.IMPORT_MAX_CONFIG_ERRORS_SHOWN)

    def test_data_that_conflicts_with_the_configuration_rolls_everything_back(self):
        bad = copy.deepcopy(self.config)
        del bad['cats']['Requirement']['p_kind_choices']['STD']
        message = self.rejected(bad)                         # items, releases and the project exist when this is found
        self.assertIn('cats.Requirement.p_kind_choices', message)
        self.assertIn('STD', message)

    def test_a_stored_link_the_configuration_does_not_allow_rolls_everything_back(self):
        bad = copy.deepcopy(self.config)
        bad['cats']['Packet']['links']['p_link']['targets'] = ['Packet']
        self.assertIn('cats.Packet.links.p_link', self.rejected(bad))

    def test_the_stored_configuration_of_other_projects_is_untouched_by_a_rejection(self):
        other, _ = self.make_project('Other', owner=self.owner)
        other_config = resolve_config({})
        Project.objects.filter(id=other.id).update(config=other_config)
        bad = copy.deepcopy(self.config)
        del bad['cats']['Requirement']['p_kind_choices']['STD']
        self.rejected(bad)
        self.assertEqual(self.stored(other), other_config)
        self.assertEqual(self.stored(Project.objects.get(name='Proj_original')), self.config)

    def test_an_oversized_configuration_is_refused_when_the_archive_is_read(self):
        data = self.with_config(self.export_bytes(self.project), ' ' * (MAX_JSON_BYTES + 1))
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        before = self.counts()
        response, messages = self.import_zip(data)
        self.assertEqual(self.counts(), before)
        self.assertEqual(len(messages), 1)
        self.assertIn('config.json is larger than', messages[0])

    def test_an_unexpected_failure_while_storing_the_configuration_rolls_everything_back(self):
        data = self.export_bytes(self.project)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        before = self.counts()
        with mock.patch('editor.imports.save_project_config', side_effect=RuntimeError('boom')):
            response, messages = self.import_zip(data)
        self.assertEqual(self.counts(), before)
        self.assertEqual(messages, ['Unable to import project; nothing was imported (details in the server log)'])

    def test_a_failure_after_the_configuration_is_stored_rolls_it_back_too(self):
        data = self.export_bytes(self.project)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        before = self.counts()
        real = imports.save_project_config

        def store_then_fail(project_id, body, token):
            real(project_id, body, token)
            raise RuntimeError('after the write')

        with mock.patch('editor.imports.save_project_config', side_effect=store_then_fail):
            self.import_zip(data)
        self.assertEqual(self.counts(), before)
        self.assertFalse(Project.objects.filter(name='Proj').exists())


class OldArchiveTests(ArchiveTestCase):
    """Archives written before the configuration existed (no config.json)."""

    def setUp(self):
        super().setUp()
        self.project, _ = self.make_project('Old', owner=self.owner, cats=['Requirement', 'Service'])
        app = self.make_application(self.project, 'OldApp', cats=['Requirement'])
        self.make_item(self.project, 'Requirement', 'R', 'req', application=app, value='v', p_kind='STD')
        svc = self.make_item(self.project, 'Service', 'S', 'svc', title='Svc', value='Type')
        # Not listed in the project's cats: kept with the definitions which have data
        self.make_item(self.project, 'Packet', 'P', 'pkt', title='Pkt', p_link=svc, p_kind='TC')
        # A row which the import rejects: its category must not be part of the filtered configuration
        self.make_item(self.project, 'ComIntCmd', 'C', 'cmd', title='rejected', status='XXX')
        self.old_archive = self.with_config(self.export_bytes(self.project), None)

    def test_the_old_archive_has_no_configuration_member(self):
        self.assertEqual(list(self.members(self.old_archive)), CSV_MEMBERS)

    def test_the_configuration_is_the_template_filtered_for_the_imported_data(self):
        imported, messages = self.import_as_copy(self.project, self.old_archive)
        self.assertEqual(len(messages), 1)
        self.assertIn('ComIntCmd:C:cmd', messages[0])                  # the rejected row, as before
        expected = filter_template_for_data(load_template(), imported)
        self.assertEqual(self.stored(imported), expected)
        cats = self.stored(imported)['cats']
        self.assertEqual(sorted(cats), ['Packet', 'Requirement', 'Service'])
        self.assertNotIn('ComIntCmd', cats)                            # based on the data actually imported
        self.assertEqual(sorted(cats['Packet']['attrs']), ['domain', 'name', 'owner', 'p_kind', 'p_link', 'title', 'val_set'])
        self.assertEqual(cats['Requirement']['attrs'], TEMPLATE['cats']['Requirement']['attrs'])   # listed: all definitions

    def test_the_derived_configuration_is_valid_for_the_imported_data(self):
        imported, _ = self.import_as_copy(self.project, self.old_archive)
        self.assertEqual(validate_config(self.stored(imported), imported), [])
        self.assertNotIn('temp_dir', self.stored(imported)['general'])

    def test_the_shared_filter_is_called_after_the_items_exist(self):
        Project.objects.filter(id=self.project.id).update(name='Old_original')
        calls = []
        real = imports.filter_template_for_data

        def spy(template, project):
            calls.append((project.name, SpecItem.objects.filter(project=project).count()))
            return real(template, project)

        with mock.patch('editor.imports.filter_template_for_data', side_effect=spy):
            self.import_zip(self.old_archive)
        self.assertEqual(calls, [('Old', 3)])

    def test_the_derived_configuration_is_not_shared_with_the_template_or_other_projects(self):
        other, _ = self.make_project('Other', owner=self.owner)
        Project.objects.filter(id=other.id).update(config=resolve_config({}))
        imported, _ = self.import_as_copy(self.project, self.old_archive)
        self.assertEqual(self.stored(other), resolve_config({}))
        self.stored(imported)['cats']['Service']['name'] = 'changed in memory'
        self.assertNotEqual(load_template()['cats']['Service']['name'], 'changed in memory')

    def test_problems_of_the_derived_configuration_do_not_reject_the_archive(self):
        # A stored kind the template does not offer (data from before this check existed)
        SpecItem.objects.filter(project=self.project, cat='Requirement').update(p_kind='NOPE')
        data = self.with_config(self.export_bytes(self.project), None)
        with self.assertLogs('editor.imports', level='WARNING') as logs:
            imported, messages = self.import_as_copy(self.project, data)
        self.assertEqual(SpecItem.objects.get(project=imported, cat='Requirement').p_kind, 'NOPE')
        self.assertNotEqual(self.stored(imported), {})
        self.assertIn('cats.Requirement.p_kind_choices', logs.output[0])

    def test_an_empty_archive_configuration_member_is_not_an_old_archive(self):
        data = self.with_config(self.old_archive, '{}')
        Project.objects.filter(id=self.project.id).update(name='Old_original')
        response, messages = self.import_zip(data)
        self.assertEqual(len(messages), 1)
        self.assertIn('nothing was imported', messages[0])
        self.assertFalse(Project.objects.filter(name='Old').exists())

    def test_extra_members_of_the_archive_are_still_ignored(self):
        members = self.members(self.old_archive)
        members['notes.txt'] = b'ignored'
        members['../evil.json'] = b'{}'
        imported, _ = self.import_as_copy(self.project, self.archive(members))
        self.assertIsNotNone(imported)
