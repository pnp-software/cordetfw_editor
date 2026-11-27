import copy
import csv
import io
import tempfile
from django.test import override_settings
import zipfile
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from editor.cat_validators import check_validator_specs
from editor.link_rules import check_link_rules, check_trac_settings
from editor.models import Application, Project, SpecItem
from editor.project_config import (SERVER_ONLY_GENERAL_KEYS, filter_template_for_data, get_data_usage,
                                   get_unknown_cats, load_template, split_cats)
from tests.project_config.base import ALL_CATS, EditorTestCase, TEMPLATE


def assert_consistent(test, config):
    """Every reference in the configuration points to a definition that is in the configuration."""
    cats = config['cats']
    for cat, definition in cats.items():
        attrs = definition['attrs']
        with test.subTest(cat=cat):
            test.assertTrue(set(definition['ext_attrs']) <= set(attrs))
            for link in ('s_link', 'p_link'):
                test.assertIn(definition['expand'][link], ('None', *cats))
            for trac in definition['tracs']:
                test.assertIn(trac['trac_cat'], cats)
            test.assertEqual(check_link_rules(definition['links'], 'links', set(cats)), [])
            test.assertEqual(check_trac_settings(definition['tracs'], 'tracs', set(cats)), [])
            test.assertEqual(check_validator_specs(definition['validators'], 'validators', config, cat), [])
            for key, names in definition['short_desc'].items():
                test.assertTrue(set(names) <= set(attrs), key)
            for layout in ('disp_def', 'disp_short', 'disp_trac'):
                for column in definition[layout]:
                    if 'attrs' in column:
                        test.assertTrue(column['attrs'] and set(column['attrs']) <= set(attrs), (layout, column))
                        if 'order_by' in column:
                            test.assertIn(column['order_by'], attrs)
                    else:
                        test.assertIn(column['trac_cat'], cats)


class TemplateLoadingTests(EditorTestCase):
    def test_load_template_reads_the_shared_file_without_caching(self):
        first, second = load_template(), load_template()
        self.assertEqual(first, TEMPLATE)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        first['cats'].clear()
        self.assertEqual(len(load_template()['cats']), 30)

    def test_split_cats(self):
        self.assertEqual(split_cats(' A, B ,,C'), ['A', 'B', 'C'])
        self.assertEqual(split_cats(''), [])


class FilterTemplateTests(EditorTestCase):
    def make_cats_project(self, cats, name='P', app_cats=None):
        project, _ = self.make_project(name, owner=self.owner, cats=cats)
        if app_cats is not None:
            self.make_application(project, name + 'App', cats=app_cats)
        return project

    def test_template_is_not_modified(self):
        template = load_template()
        snapshot = copy.deepcopy(template)
        project = self.make_cats_project(['Packet'])
        config = filter_template_for_data(template, project)
        self.assertEqual(template, snapshot)
        config['cats']['Packet']['attrs']['title']['label'] = 'Changed'
        self.assertEqual(template, snapshot)

    def test_all_categories_listed_gives_the_template_without_server_settings(self):
        project = self.make_cats_project(ALL_CATS)
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(config['cats'], TEMPLATE['cats'])
        self.assertEqual(list(config['cats']), list(TEMPLATE['cats']))              # template order
        self.assertEqual(config['general'], {k: v for k, v in TEMPLATE['general'].items() if k != 'temp_dir'})
        self.assertNotIn('temp_dir', config['general'])
        self.assertEqual(SERVER_ONLY_GENERAL_KEYS, ('temp_dir',))
        self.assertEqual(set(config), {'general', 'cats'})
        assert_consistent(self, config)

    def test_only_listed_categories_are_kept_when_there_is_no_data(self):
        project = self.make_cats_project(['InfoItem', 'Requirement', 'VerLink'])
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(list(config['cats']), ['VerLink', 'Requirement', 'InfoItem'])
        for cat in config['cats']:                      # listed categories keep every definition
            # Except that relationship targets which are not in the configuration are removed
            self.assertEqual({k: v for k, v in config['cats'][cat].items() if k != 'links'},
                             {k: v for k, v in TEMPLATE['cats'][cat].items() if k != 'links'})
        self.assertEqual(config['cats']['VerLink']['links'],
                         {'s_link': {'all_except': ['VerLink'], 'order_by': ['cat', 'domain', 'name']}})
        assert_consistent(self, config)

    def test_application_categories_are_kept(self):
        project = self.make_cats_project(['InfoItem'], app_cats=['Requirement', 'SysReq'])
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(sorted(config['cats']), ['InfoItem', 'Requirement', 'SysReq'])

    def test_listed_category_without_data_keeps_all_its_fields(self):
        project = self.make_cats_project(['InfoItem'])
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(list(config['cats']['InfoItem']['attrs']), list(TEMPLATE['cats']['InfoItem']['attrs']))

    def test_category_with_data_is_kept_with_the_definitions_that_hold_data(self):
        project = self.make_cats_project(['InfoItem'])
        self.make_item(project, 'Requirement', 'D', 'r1', title='T', value='v', t1='x', p_kind='STD', status='CNF')
        self.make_item(project, 'Requirement', 'D', 'r2', status='DEL', rationale='why')       # statuses are all data
        self.make_item(project, 'DataItemType', 'D', 'n', n1=4)
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(sorted(config['cats']), ['DataItemType', 'InfoItem', 'Requirement'])
        requirement = config['cats']['Requirement']
        self.assertEqual(set(requirement['attrs']), {'domain', 'name', 'title', 'value', 'rationale', 't1', 'p_kind',
                                                     'val_set', 'owner'})
        for name, definition in requirement['attrs'].items():                          # definitions are unchanged
            self.assertEqual(definition, TEMPLATE['cats']['Requirement']['attrs'][name])
        self.assertEqual(set(config['cats']['DataItemType']['attrs']), {'domain', 'name', 'n1', 'val_set', 'owner'})
        names = {a for layout in ('disp_def', 'disp_short', 'disp_trac') for c in requirement[layout] for a in c.get('attrs', [])}
        self.assertTrue(names <= set(requirement['attrs']))
        self.assertTrue(set(requirement['short_desc']['expand_text']) <= set(requirement['attrs']))
        assert_consistent(self, config)

    def test_data_of_other_projects_is_ignored(self):
        project = self.make_cats_project(['InfoItem'])
        other = self.make_cats_project(['InfoItem', 'Requirement', 'VerLink'], name='Other')
        self.make_item(other, 'Requirement', 'D', 'r1', title='T')
        self.make_item(other, 'EnumType', 'D', 'e1', n1=2)
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(list(config['cats']), ['InfoItem'])

    def test_references_to_removed_categories_and_fields_are_removed(self):
        project = self.make_cats_project(['Packet'])
        config = filter_template_for_data(load_template(), project)
        packet = config['cats']['Packet']
        self.assertEqual(packet['expand']['s_link'], 'None')              # DerPacket removed
        self.assertEqual(packet['expand']['p_link'], 'None')              # PacketPar removed
        self.assertEqual((packet['expand']['s_label'], packet['expand']['p_label']),
                         (TEMPLATE['cats']['Packet']['expand']['s_label'], TEMPLATE['cats']['Packet']['expand']['p_label']))
        self.assertEqual(packet['tracs'], [])                              # VerLink removed
        for layout in ('disp_def', 'disp_short', 'disp_trac'):
            self.assertFalse([c for c in packet[layout] if 'trac_cat' in c], layout)
        self.assertEqual(len(packet['disp_trac']), len(TEMPLATE['cats']['Packet']['disp_trac']) - 1)
        assert_consistent(self, config)

    def test_references_between_kept_categories_are_preserved(self):
        project = self.make_cats_project(['Packet', 'DerPacket', 'PacketPar', 'VerLink'])
        config = filter_template_for_data(load_template(), project)
        packet = config['cats']['Packet']
        self.assertEqual((packet['expand']['s_link'], packet['expand']['p_link']), ('DerPacket', 'PacketPar'))
        self.assertEqual(packet['tracs'], [{'trac_cat': 'VerLink', 'trac_link': 's_link'}])
        assert_consistent(self, config)

    def test_every_single_category_gives_a_consistent_configuration(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                project = self.make_cats_project([cat], name='P_' + cat)
                config = filter_template_for_data(load_template(), project)
                self.assertEqual(list(config['cats']), [cat])
                assert_consistent(self, config)

    def test_data_only_category_with_the_fewest_fields_is_consistent(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                project = self.make_cats_project([], name='D_' + cat)
                self.make_item(project, cat, 'D', 'only')
                config = filter_template_for_data(load_template(), project)
                self.assertEqual(list(config['cats']), [cat])
                self.assertEqual(set(config['cats'][cat]['attrs']), {'domain', 'name', 'val_set', 'owner'} & set(TEMPLATE['cats'][cat]['attrs']))
                assert_consistent(self, config)

    def test_unknown_categories_are_reported_and_not_copied(self):
        project = self.make_cats_project(['InfoItem', 'Bogus'])
        SpecItem.objects.create(cat='Ghost', domain='D', name='g', project=project, val_set=project.val_sets.first(),
                                owner=self.owner, status='NEW', updated_at=project.updated_at, created_at=project.updated_at)
        config = filter_template_for_data(load_template(), project)
        self.assertEqual(list(config['cats']), ['InfoItem'])
        self.assertEqual(get_unknown_cats(load_template(), project), ['Bogus', 'Ghost'])

    def test_data_usage(self):
        project = self.make_cats_project(['InfoItem'])
        self.make_item(project, 'Requirement', 'D', 'a', title='T', n1=0, t3='x')
        self.make_item(project, 'Requirement', 'D', 'b', desc='d')
        parent = self.make_item(project, 'Service', 'D', 'p')
        self.make_item(project, 'Packet', 'D', 'c', p_link=parent)
        usage = get_data_usage(project)
        self.assertEqual(usage['Requirement'], {'domain', 'name', 'val_set', 'owner', 'title', 't3', 'desc'})
        self.assertEqual(usage['Packet'], {'domain', 'name', 'val_set', 'owner', 'p_link'})
        self.assertEqual(usage['Service'], {'domain', 'name', 'val_set', 'owner'})


class InitProjectConfigsTests(EditorTestCase):
    def run_command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        call_command('init_project_configs', *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def snapshot_data(self):
        items = list(SpecItem.objects.order_by('id').values())
        projects = [{k: v for k, v in p.items() if k not in ('config',)} for p in Project.objects.order_by('id').values()]
        apps = list(Application.objects.order_by('id').values())
        return items, projects, apps

    def setUp(self):
        super().setUp()
        self.p2, _ = self.make_project('Second', owner=self.owner, cats=['InfoItem'])
        self.p3, _ = self.make_project('Third', owner=self.owner, cats=['Service', 'Packet', 'DerPacket', 'PacketPar', 'VerLink'])
        self.make_item(self.project, 'Service', 'S', 'svc', title='T')
        self.make_item(self.p2, 'Requirement', 'R', 'r', value='v')       # data in a category which is not listed
        self.make_item(self.p3, 'Service', 'S', 'other')

    def test_new_projects_start_with_an_empty_configuration(self):
        for project in Project.objects.all():
            self.assertEqual(project.config, {})

    def test_every_project_gets_its_own_filtered_configuration(self):
        before = self.snapshot_data()
        out, err = self.run_command()
        self.assertEqual(err, '')
        self.assertIn('3 project(s) initialized, 0 skipped', out)
        for project in Project.objects.all():
            project.refresh_from_db()
            self.assertEqual(project.config, filter_template_for_data(load_template(), project))
            assert_consistent(self, project.config)
        self.assertEqual(len(Project.objects.get(id=self.project.id).config['cats']), 30)
        self.assertEqual(sorted(Project.objects.get(id=self.p2.id).config['cats']), ['InfoItem', 'Requirement'])
        self.assertEqual(sorted(Project.objects.get(id=self.p3.id).config['cats']),
                         ['DerPacket', 'Packet', 'PacketPar', 'Service', 'VerLink'])
        self.assertEqual(self.snapshot_data(), before)                     # no project data changed, not even updated_at

    def test_configurations_are_isolated_from_each_other_and_from_the_template(self):
        self.run_command()
        first = Project.objects.get(id=self.project.id)
        first.config['cats']['Service']['name'] = 'Renamed Service'
        first.config['cats'].pop('Packet')
        first.save()
        self.assertEqual(Project.objects.get(id=self.p3.id).config['cats']['Service']['name'], TEMPLATE['cats']['Service']['name'])
        self.assertIn('Packet', Project.objects.get(id=self.p3.id).config['cats'])
        self.assertEqual(load_template(), TEMPLATE)

    def test_a_second_run_changes_nothing(self):
        self.run_command()
        configs = {p.id: p.config for p in Project.objects.all()}
        stamps = {p.id: p.updated_at for p in Project.objects.all()}
        before = self.snapshot_data()
        with CaptureQueriesContext(connection) as queries:
            out, _ = self.run_command()
        self.assertIn('0 project(s) initialized, 3 skipped', out)
        self.assertEqual({p.id: p.config for p in Project.objects.all()}, configs)
        self.assertEqual({p.id: p.updated_at for p in Project.objects.all()}, stamps)
        self.assertEqual(self.snapshot_data(), before)
        self.assertFalse([q['sql'] for q in queries.captured_queries if q['sql'].lstrip().upper().startswith(('UPDATE', 'INSERT', 'DELETE'))])

    def test_projects_which_are_already_configured_are_skipped(self):
        custom = {'general': {}, 'cats': {'Custom': {'name': 'My own category'}}}
        Project.objects.filter(id=self.p2.id).update(config=custom)
        out, _ = self.run_command()
        self.assertIn('2 project(s) initialized, 1 skipped', out)
        self.assertEqual(Project.objects.get(id=self.p2.id).config, custom)
        self.assertIn('Second): already configured, skipped', out)

    def test_dry_run_writes_nothing(self):
        before = self.snapshot_data()
        out, _ = self.run_command('--dry-run')
        self.assertIn('Dry run: 3 project(s) to initialize, 0 skipped', out)
        self.assertEqual([p.config for p in Project.objects.all()], [{}, {}, {}])
        self.assertEqual(self.snapshot_data(), before)

    def test_categories_without_a_template_definition_are_reported(self):
        Project.objects.filter(id=self.p2.id).update(cats='InfoItem,Bogus')
        out, err = self.run_command()
        self.assertIn('category Bogus is not defined in the template', err)
        self.assertEqual(sorted(Project.objects.get(id=self.p2.id).config['cats']), ['InfoItem', 'Requirement'])

    def test_the_global_configs_dictionary_no_longer_exists(self):
        # The command (like everything else) works from the template file and the projects' data
        import editor.configs
        self.assertFalse(hasattr(editor.configs, 'configs'))
        self.run_command()
        self.assertEqual(len(Project.objects.get(id=self.project.id).config['cats']), 30)

    def test_archive_project_csv_keeps_its_columns(self):
        # The configuration travels in config.json, so project.csv is unchanged
        self.run_command()
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.get(self.url('export_project', self.project.id))
            archive = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
        header = next(csv.reader(io.StringIO(archive.read('project.csv').decode('utf-8'))))
        self.assertEqual(header, ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release'])
