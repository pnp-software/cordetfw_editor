"""Every read of the configuration is the configuration of the project of the request."""
import copy
import csv
import io
import json
import pathlib
import re
import tempfile
import zipfile
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from editor import convert
from editor.config_cleanup import remove_attribute, remove_category
from editor.config_validation import validate_config
from editor.fields import OrderedJSONField
from editor.forms import ProjectForm
from editor.models import Application, Project, Release, SpecItem
from editor.project_config import get_project_config, load_template
from editor.utilities import HIDDEN_VALUE_FIELDS, get_hidden_fields
from tests.factories import template_config
from tests.project_config.base import ALL_CATS, EditorTestCase
from tests.project_config.test_project_config_access import project_config_queries

PRODUCTION_DIR = pathlib.Path(__file__).resolve().parents[2] / 'editor'


class ConfiguredTestCase(EditorTestCase):
    def configure(self, project, transform=None):
        """Store the template, changed by transform(config) (which mutates or returns a new configuration)."""
        config = template_config()
        if transform is not None:
            config = transform(config) or config
        self.assertEqual(validate_config(config, project), [])
        Project.objects.filter(id=project.id).update(config=config)     # update(): updated_at is not touched
        project.refresh_from_db()
        return config

    def other_project(self, name='Other'):
        project, val_set = self.make_project(name, owner=self.owner, rw_users=[self.rw_user])
        self.make_application(project, name + 'App')
        return project, val_set

    def service_list(self, project, val_set, **query):
        return self.client.get(self.list_url('Service', project=project, val_set=val_set), query)

    def snapshot(self, project):
        """Everything of a project which hiding a field or category must leave unchanged."""
        return {
            'items': list(SpecItem.objects.filter(project=project).order_by('id').values()),
            'releases': list(Release.objects.order_by('id').values()),
            'applications': list(Application.objects.filter(project=project).order_by('id').values('id', 'name',
                                                                                                    'cats', 'release_id')),
            'project_cats': Project.objects.get(id=project.id).cats,
        }


class TwoProjectIsolationTests(ConfiguredTestCase):
    """Acceptance criteria 1 and 10: the same category, different settings, in two projects."""

    def setUp(self):
        super().setUp()
        self.other, self.other_vs = self.other_project()

        def alpha(config):
            service = config['cats']['Service']
            service.update(name='Alpha Service', page_size=2)
            service['attrs']['title']['label'] = 'Alpha Title'
            config['general']['csv_sep'] = ';'

        def beta(config):
            service = config['cats']['Service']
            service.update(name='Beta Service', page_size=3)
            service['attrs']['title']['label'] = 'Beta Title'

        self.configure(self.project, alpha)
        self.configure(self.other, beta)
        for project in (self.project, self.other):
            for n in range(1, 4):
                self.make_item(project, 'Service', 'D', 'svc%d' % n, title='Title %d' % n, status='CNF')

    def test_list_pages_use_the_settings_of_their_own_project(self):
        first = self.service_list(self.project, self.default_val_set)
        second = self.service_list(self.other, self.other_vs)
        self.assertEqual(first.context['config']['name'], 'Alpha Service')
        self.assertEqual(second.context['config']['name'], 'Beta Service')
        self.assertEqual(len(first.context['page_items']), 2)       # page_size 2
        self.assertEqual(len(second.context['page_items']), 3)      # page_size 3
        self.assertTrue(first.context['pagination']['has_next'])
        self.assertFalse(second.context['pagination']['has_next'])
        self.assertContains(first, 'Alpha Service')
        self.assertNotContains(first, 'Beta Service')
        self.assertContains(second, 'Beta Service')
        self.assertNotContains(second, 'Alpha Service')

    def test_forms_use_the_labels_of_their_own_project(self):
        first = self.client.get(self.add_url('Service')).context['form']
        second = self.client.get(self.url('add_spec_item', 'Service', self.other.id, 0, 'Sel_All', 0)).context['form']
        self.assertEqual(first.fields['title'].label, 'Alpha Title')
        self.assertEqual(second.fields['title'].label, 'Beta Title')
        self.assertEqual(self.client.get(self.add_url('Service')).context['title'], 'Add Alpha Service')

    def test_item_csv_uses_the_labels_and_separator_of_the_project(self):
        first = self.client.get(self.url('export_spec_items', 'Service', self.project.id, 0,
                                         self.default_val_set.id, 'Sel_All', 0))
        second = self.client.get(self.url('export_spec_items', 'Service', self.other.id, 0,
                                          self.other_vs.id, 'Sel_All', 0))
        first_header = first.content.decode().splitlines()[0]
        second_header = second.content.decode().splitlines()[0]
        self.assertIn('Alpha Title;', first_header)
        self.assertNotIn('Beta Title', first_header)
        self.assertIn('Beta Title|', second_header)             # the template separator
        self.assertNotIn('Alpha Title', second_header)

    def test_item_csv_import_expects_the_columns_of_the_project(self):
        csv_text = self.client.get(self.url('export_spec_items', 'Service', self.project.id, 0,
                                            self.default_val_set.id, 'Sel_All', 0)).content.decode()
        url = self.url('import_spec_items', 'Service', self.other.id, 0, self.other_vs.id, 'Sel_All')
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.client.post(url, {'upload_file': SimpleUploadedFile('s.csv', csv_text.encode())})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(any('does not match the selected Service category' in m for m in self.messages_of(response)))

    def test_menus_come_from_the_configuration_of_each_project(self):
        response = self.client.get(self.url('index'))
        names = {entry['project'].name: entry['project_configs']['Service']['name']
                 for entry in response.context['list_of_projects']}
        self.assertEqual(names, {'Proj': 'Alpha Service', 'Other': 'Beta Service'})

    def test_saving_one_configuration_does_not_change_the_other_project(self):
        def shown():
            response = self.service_list(self.other, self.other_vs)
            return response.context['config'], [item.name for item in response.context['page_items']]
        before = shown()
        self.configure(self.project, lambda config: config['cats']['Service'].update(name='Gamma Service'))
        self.assertEqual(shown(), before)
        self.assertContains(self.service_list(self.project, self.default_val_set), 'Gamma Service')

    def test_a_project_without_a_configuration_uses_the_template(self):
        fresh, val_set = self.other_project('Fresh')
        self.assertEqual(Project.objects.get(id=fresh.id).config, {})
        response = self.service_list(fresh, val_set)
        self.assertEqual(response.context['config']['name'], load_template()['cats']['Service']['name'])
        self.assertEqual(response.context['project_config'], get_project_config(fresh))

    def test_history_uses_the_configuration_of_the_project(self):
        first = self.make_item(self.project, 'Service', 'H', 'hist')
        second = self.make_item(self.other, 'Service', 'H', 'hist')
        names = []
        for item in (first, second):
            url = self.url('list_spec_item_history', 'Service', item.project_id, 0, item.id, 'Sel_All')
            names.append(self.client.get(url).context['config']['name'])
        self.assertEqual(names, ['Alpha Service', 'Beta Service'])

    def test_a_new_request_sees_a_saved_change_at_once(self):
        self.assertContains(self.service_list(self.project, self.default_val_set), 'Alpha Service')
        self.configure(self.project, lambda config: config['cats']['Service'].update(name='Renamed Service'))
        self.assertContains(self.service_list(self.project, self.default_val_set), 'Renamed Service')

    def test_item_views_read_the_configuration_once_per_request(self):
        item = SpecItem.objects.filter(project=self.project, cat='Service').first()
        urls = [self.list_url('Service', val_set=self.default_val_set), self.add_url('Service'),
                self.item_url('edit_spec_item', item), self.item_url('copy_spec_item', item),
                self.item_url('del_spec_item', item),
                self.url('list_spec_item_history', 'Service', self.project.id, 0, item.id, 'Sel_All'),
                self.url('export_spec_items', 'Service', self.project.id, 0, self.default_val_set.id, 'Sel_All', 0)]
        for url in urls:
            with self.subTest(url=url), CaptureQueriesContext(connection) as queries:
                self.assertIn(self.client.get(url).status_code, (200, 302))
                self.assertEqual(len(project_config_queries(queries)), 1)

    def test_the_index_reads_each_project_once(self):
        with CaptureQueriesContext(connection) as queries:
            self.client.get(self.url('index'))
        self.assertEqual(len(project_config_queries(queries)), 2)


class NewCategoryTests(ConfiguredTestCase):
    """Acceptance criterion 2: a category which is not in the template needs no code."""

    def widget_config(self, config):
        widget = copy.deepcopy(config['cats']['Service'])
        widget.update(name='Widget', abbr='Wdg', expand={'s_link': 'None', 'p_link': 'None'}, tracs=[])
        widget['page_size'] = 7
        config['cats']['Widget'] = widget

    def setUp(self):
        super().setUp()
        self.configure(self.project, self.widget_config)
        Project.objects.filter(id=self.project.id).update(cats=self.project.cats + ',Widget')
        self.project.refresh_from_db()

    def test_the_menu_offers_the_new_category(self):
        response = self.client.get(self.url('index'))
        menu = response.context['list_of_projects'][0]['project_configs']
        self.assertEqual(menu['Widget']['name'], 'Widget')
        self.assertContains(response, 'Manage Widgets')

    def test_an_item_can_be_added_listed_edited_copied_and_deleted(self):
        add_url = self.add_url('Widget')
        payload = self.form_payload(add_url, domain='W', name='w1', title='First widget', value='v')
        response = self.client.post(add_url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        item = SpecItem.objects.get(cat='Widget', name='w1')
        self.assertEqual((item.project_id, item.status, item.title), (self.project.id, 'NEW', 'First widget'))

        listed = self.client.get(self.list_url('Widget'))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.context['config']['name'], 'Widget')
        self.assertContains(listed, 'First widget')

        edit_url = self.item_url('edit_spec_item', item)
        response = self.client.post(edit_url, self.form_payload(edit_url, title='Edited widget'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.refresh(item).title, 'Edited widget')

        copy_url = self.item_url('copy_spec_item', item)
        response = self.client.post(copy_url, self.form_payload(copy_url, name='w2'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SpecItem.objects.filter(cat='Widget').count(), 2)

        delete_url = self.item_url('del_spec_item', item)
        self.assertEqual(self.client.post(delete_url).status_code, 302)
        self.assertEqual(SpecItem.objects.filter(cat='Widget').count(), 1)

    def test_the_pages_of_the_new_category_use_its_settings(self):
        for n in range(9):
            self.make_item(self.project, 'Widget', 'W', 'w%d' % n, title='t', status='CNF')
        listed = self.client.get(self.list_url('Widget'))
        self.assertEqual(len(listed.context['page_items']), 7)             # page_size of Widget
        self.assertEqual(self.client.get(self.list_url('Widget'), {'disp': 'disp_trac'}).status_code, 200)
        csv_response = self.client.get(self.url('export_spec_items', 'Widget', self.project.id, 0,
                                                self.default_val_set.id, 'Sel_All', 0))
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn('Widget.csv', csv_response['Content-Disposition'])

    def test_references_to_the_new_category_are_displayed_and_stored(self):
        widget = self.make_item(self.project, 'Widget', 'W', 'ref_target', title='Target')
        edit_url = self.add_url('Service')
        payload = self.form_payload(edit_url, domain='S', name='s1', title='Svc', value='v', desc='see #Widget:W:ref_target')
        response = self.client.post(edit_url, payload)
        self.assertEqual(response.status_code, 302, response.context['form'].errors if response.status_code == 200 else '')
        service = SpecItem.objects.get(cat='Service', name='s1')
        self.assertEqual(service.desc, 'see #iref:%d' % widget.id)
        listed = self.client.get(self.list_url('Service'))
        self.assertContains(listed, 'W:ref_target')
        self.assertContains(listed, 'Title: Target')                      # the tooltip of the new category

    def test_the_project_form_accepts_the_category_only_for_this_project(self):
        other, _ = self.other_project()
        data = {'name': 'N', 'owner': str(self.owner.id), 'cats': 'Widget', 'description': 'd'}
        form = ProjectForm(self.project, data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn('Widget', form.predefined_cats)
        form = ProjectForm(other, data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('cats', form.errors)

    def test_the_new_category_is_not_visible_in_another_project(self):
        other, other_vs = self.other_project()
        response = self.client.get(self.list_url('Widget', project=other, val_set=other_vs, application_id=0))
        self.assertEqual(response.status_code, 404)


class HiddenFieldTests(ConfiguredTestCase):
    """Acceptance criterion 6, with the fields removed from the configuration. test_project_config_hidden.py reruns
    these tests with fields hidden by `"hidden": true` (hooks hide_attrs, assert_archived_definitions)."""

    HIDDEN = ('rationale', 'remarks')

    def hide_attrs(self, config, cat, attrs):
        """The configuration in which the attributes `attrs` of `cat` are not shown: here they are removed."""
        for attr in attrs:
            config = remove_attribute(config, cat, attr)
        return config

    def assert_archived_definitions(self, config):
        """The configuration of the project archive no longer has the removed definitions."""
        self.assertNotIn('rationale', config['cats']['Service']['attrs'])

    def setUp(self):
        super().setUp()
        self.item = self.make_item(self.project, 'Service', 'D', 'svc', title='Title', desc='Desc', value='Val',
                                   rationale='keep me', remarks='keep me too', status='NEW')
        self.configure(self.project, lambda config: self.hide_attrs(config, 'Service', self.HIDDEN))

    def test_the_form_does_not_show_the_hidden_fields(self):
        form = self.client.get(self.item_url('edit_spec_item', self.item)).context['form']
        for attr in self.HIDDEN:
            self.assertEqual(type(form.fields[attr].widget).__name__, 'HiddenInput')
        self.assertEqual(type(form.fields['title'].widget).__name__, 'TextInput')
        self.assertTrue(set(self.HIDDEN) <= set(get_hidden_fields(get_project_config(self.project), 'Service')))
        self.assertTrue(set(get_hidden_fields(get_project_config(self.project), 'Service')) <= set(HIDDEN_VALUE_FIELDS))

    def test_the_list_does_not_show_the_hidden_values(self):
        response = self.client.get(self.list_url('Service'))
        self.assertContains(response, 'Title')
        self.assertNotContains(response, 'keep me')

    def test_editing_with_the_form_keeps_the_hidden_values(self):
        url = self.item_url('edit_spec_item', self.item)
        response = self.client.post(url, self.form_payload(url, title='Changed'))
        self.assertEqual(response.status_code, 302)
        item = self.refresh(self.item)
        self.assertEqual((item.title, item.rationale, item.remarks), ('Changed', 'keep me', 'keep me too'))

    def test_editing_with_a_post_which_lacks_the_hidden_fields_keeps_the_values(self):
        url = self.item_url('edit_spec_item', self.item)
        payload = {key: value for key, value in self.form_payload(url, title='Changed').items()
                   if key not in self.HIDDEN}
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        item = self.refresh(self.item)
        self.assertEqual((item.title, item.rationale, item.remarks), ('Changed', 'keep me', 'keep me too'))

    def test_a_posted_value_cannot_overwrite_a_hidden_value(self):
        url = self.item_url('edit_spec_item', self.item)
        payload = self.form_payload(url, title='Changed', rationale='forged', remarks='forged')
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        item = self.refresh(self.item)
        self.assertEqual((item.rationale, item.remarks), ('keep me', 'keep me too'))

    def test_editing_a_confirmed_item_keeps_the_hidden_values_in_both_versions(self):
        SpecItem.objects.filter(id=self.item.id).update(status='CNF')
        url = self.item_url('edit_spec_item', self.item)
        self.assertEqual(self.client.post(url, self.form_payload(url, title='New version')).status_code, 302)
        current = self.refresh(self.item)
        self.assertEqual((current.status, current.rationale), ('MOD', 'keep me'))
        self.assertEqual((current.previous.status, current.previous.title, current.previous.rationale),
                         ('OBS', 'Title', 'keep me'))

    def test_a_hidden_kind_and_numbers_survive_editing(self):
        requirement = self.make_item(self.project, 'Requirement', 'R', 'req', title='T', value='v', p_kind='CNS',
                                     s_kind='TST', n1=5, n2=6)
        self.configure(self.project, lambda config: self.hide_attrs(config, 'Requirement', ('p_kind', 's_kind')))
        url = self.item_url('edit_spec_item', requirement)
        payload = self.form_payload(url, title='Changed', p_kind='', s_kind='')
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        item = self.refresh(requirement)
        self.assertEqual((item.title, item.p_kind, item.s_kind, item.n1, item.n2), ('Changed', 'CNS', 'TST', 5, 6))

    def test_copy_and_split_carry_the_hidden_values_over(self):
        copy_url = self.item_url('copy_spec_item', self.item)
        self.assertEqual(self.client.post(copy_url, self.form_payload(copy_url, name='svc_copy')).status_code, 302)
        copied = SpecItem.objects.get(cat='Service', name='svc_copy')
        self.assertEqual((copied.rationale, copied.remarks), ('keep me', 'keep me too'))

        from editor.models import ValSet
        alternative = ValSet.objects.create(project=self.project, name='Alt', desc='alt')
        split_url = self.item_url('split_spec_item', self.item)
        payload = self.form_payload(split_url, val_set=alternative.id)
        response = self.client.post(split_url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        split = SpecItem.objects.get(cat='Service', name='svc', val_set=alternative)
        self.assertEqual((split.rationale, split.remarks), ('keep me', 'keep me too'))

    def test_a_new_item_gets_empty_values_for_the_hidden_fields(self):
        url = self.add_url('Service')
        payload = self.form_payload(url, domain='N', name='fresh', title='Fresh', value='v', rationale='forged')
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(SpecItem.objects.get(name='fresh').rationale, '')

    def test_item_csv_leaves_out_the_hidden_columns_and_import_keeps_the_values(self):
        export_url = self.url('export_spec_items', 'Service', self.project.id, 0, self.default_val_set.id, 'Sel_All', 0)
        text = self.client.get(export_url).content.decode()
        rows = list(csv.DictReader(io.StringIO(text), delimiter='|'))
        self.assertNotIn('Rationale', rows[0])
        self.assertNotIn('Remarks', rows[0])
        rows[0]['Title'] = 'Via CSV'
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(rows[0]), delimiter='|')
        writer.writeheader()
        writer.writerows(rows)
        from django.core.files.uploadedfile import SimpleUploadedFile
        url = self.url('import_spec_items', 'Service', self.project.id, 0, self.default_val_set.id, 'Sel_All')
        response = self.client.post(url, {'upload_file': SimpleUploadedFile('s.csv', out.getvalue().encode())})
        self.assertEqual(response.status_code, 302)
        item = self.refresh(self.item)
        self.assertEqual((item.title, item.rationale, item.remarks), ('Via CSV', 'keep me', 'keep me too'))

    def test_the_project_export_contains_the_hidden_values(self):
        self.login(self.owner)
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.get(self.url('export_project', self.project.id))
            archive = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
        rows = list(csv.DictReader(io.StringIO(archive.read('spec_items.csv').decode())))
        service = [row for row in rows if row['name'] == 'svc'][0]
        self.assertEqual((service['rationale'], service['remarks']), ('keep me', 'keep me too'))
        self.assert_archived_definitions(json.loads(archive.read('config.json')))

    def test_restoring_the_field_shows_the_values_again(self):
        self.configure(self.project)
        form = self.client.get(self.item_url('edit_spec_item', self.item)).context['form']
        self.assertEqual(form['rationale'].value(), 'keep me')
        self.assertEqual(type(form.fields['rationale'].widget).__name__, 'Textarea')
        self.assertContains(self.client.get(self.list_url('Service')), 'keep me')


class HiddenCategoryTests(ConfiguredTestCase):
    """Acceptance criteria 7 and 8: hide and restore a category."""

    def setUp(self):
        super().setUp()
        self.service = self.make_item(self.project, 'Service', 'D', 'svc', title='Service title', value='Kind',
                                      status='CNF')
        self.packet = self.make_item(self.project, 'Packet', 'D', 'pkt', title='Packet title', p_link=self.service,
                                     p_kind='TM', status='CNF', desc='refers to #iref:%d' % self.service.id,
                                     value='v', t1='a', t2='b')
        self.verlink = self.make_item(self.project, 'VerLink', 'D', 'vl', p_link=self.make_item(
            self.project, 'VerItem', 'D', 'vi', status='CNF'), s_link=self.service, status='CNF')
        self.edited = self.make_item(self.project, 'Service', 'D', 'svc2', title='v1', status='OBS')
        self.make_item(self.project, 'Service', 'D', 'svc2', title='v2', status='MOD', previous=self.edited)
        self.full = self.configure(self.project)

    def hide_service(self):
        return self.configure(self.project, lambda config: remove_category(config, 'Service'))

    def test_hiding_changes_nothing_but_the_configuration(self):
        before = self.snapshot(self.project)
        self.hide_service()
        self.assertEqual(self.snapshot(self.project), before)

    def test_a_hidden_category_has_no_menu_entry_and_no_pages(self):
        self.hide_service()
        menu = self.client.get(self.url('index')).context['list_of_projects'][0]['project_configs']
        self.assertNotIn('Service', menu)
        self.assertIn('Packet', menu)
        self.assertEqual(self.client.get(self.list_url('Service')).status_code, 404)
        self.assertEqual(self.client.get(self.add_url('Service')).status_code, 404)
        self.assertEqual(self.client.get(self.item_url('edit_spec_item', self.service)).status_code, 404)
        self.assertEqual(self.client.get(self.url('list_spec_item_history', 'Service', self.project.id, 0,
                                                  self.service.id, 'Sel_All')).status_code, 404)
        self.assertEqual(self.client.get(self.url('export_spec_items', 'Service', self.project.id, 0,
                                                  self.default_val_set.id, 'Sel_All', 0)).status_code, 404)

    def test_references_to_the_hidden_category_show_the_plain_identifier(self):
        self.hide_service()
        listed = self.client.get(self.list_url('Packet'))
        self.assertEqual(listed.status_code, 200)
        content = listed.content.decode()
        self.assertIn('D:svc', content)
        self.assertNotIn('/editor/Service/', content)           # no link to a page which does not exist
        self.assertNotIn('ERROR:', content)

    def test_references_in_text_show_the_plain_identifier(self):
        self.hide_service()
        shown = convert.convert_db_to_display('see #iref:%d' % self.service.id, None,
                                              get_project_config(self.project), self.project.id)
        self.assertEqual(shown, 'see D:svc')

    def test_a_hidden_category_does_not_break_other_pages(self):
        self.hide_service()
        for cat in ('Packet', 'VerLink', 'DataItem'):
            for disp in ('disp_def', 'disp_short', 'disp_trac'):
                with self.subTest(cat=cat, disp=disp):
                    response = self.client.get(self.list_url(cat), {'disp': disp})
                    self.assertEqual(response.status_code, 200)

    def test_an_item_which_links_to_a_hidden_category_can_still_be_edited(self):
        self.hide_service()
        url = self.item_url('edit_spec_item', self.packet)
        form = self.client.get(url).context['form']
        self.assertEqual(form['p_link'].value(), self.service.id)
        response = self.client.post(url, self.form_payload(url, title='Edited packet'))
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        packet = self.refresh(self.packet)
        self.assertEqual((packet.p_link_id, packet.title, packet.status), (self.service.id, 'Edited packet', 'MOD'))

    def test_relationships_assignments_releases_and_history_work_while_hidden(self):
        self.hide_service()
        self.assertEqual(SpecItem.objects.get(id=self.verlink.id).s_link_id, self.service.id)
        history = self.client.get(self.url('list_spec_item_history', 'Packet', self.project.id, 0, self.packet.id,
                                           'Sel_All'))
        self.assertEqual(history.status_code, 200)
        self.login(self.owner)
        releases_before = Release.objects.count()
        response = self.client.post(self.url('make_project_release', self.project.id), {'description': 'Release'})
        self.assertEqual(response.status_code, 302)
        # the project release and one release for each application
        self.assertEqual(Release.objects.count(), releases_before + 1 + Application.objects.filter(project=self.project).count())
        self.assertEqual(SpecItem.objects.get(id=self.service.id).status, 'CNF')
        self.assertEqual(Application.objects.get(id=self.application.id).cats, self.application.cats)
        self.assertEqual(Project.objects.get(id=self.project.id).cats, ','.join(ALL_CATS))

    def test_the_project_export_contains_the_items_of_the_hidden_category(self):
        self.hide_service()
        self.login(self.owner)
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.get(self.url('export_project', self.project.id))
            archive = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
        rows = list(csv.DictReader(io.StringIO(archive.read('spec_items.csv').decode())))
        self.assertEqual(sorted(row['name'] for row in rows if row['cat'] == 'Service'), ['svc', 'svc2', 'svc2'])
        self.assertNotIn('Service', json.loads(archive.read('config.json'))['cats'])

    def test_restoring_the_definition_shows_the_items_again(self):
        self.hide_service()
        self.configure(self.project, lambda config: config.update(cats=self.full['cats']))
        menu = self.client.get(self.url('index')).context['list_of_projects'][0]['project_configs']
        self.assertIn('Service', menu)
        listed = self.client.get(self.list_url('Service'))
        self.assertEqual(listed.status_code, 200)
        self.assertContains(listed, 'Service title')
        packets = self.client.get(self.list_url('Packet')).content.decode()
        self.assertIn('/editor/Service/', packets)               # the link is back, with its tooltip
        self.assertIn('Title: Service title', packets)

    def test_hiding_a_category_in_one_project_leaves_the_other_one_alone(self):
        other, other_vs = self.other_project()
        self.make_item(other, 'Service', 'O', 'osvc', title='Other service')
        self.hide_service()
        response = self.client.get(self.list_url('Service', project=other, val_set=other_vs))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Other service')

    def test_a_category_in_the_project_cats_but_not_in_the_configuration_is_skipped_everywhere(self):
        self.hide_service()
        self.assertIn('Service', self.project.cats.split(','))
        response = self.client.get(self.list_url('Packet'))
        names = [entry['list_as'] for group in (response.context['breadcrumb']['active'], response.context['breadcrumb']['rest'])
                 for entry in group]
        self.assertNotIn('Service', names)
        self.assertTrue(names)


class MissingDisplaySettingsTests(ConfiguredTestCase):
    """A reference never needs the display settings of its target: without them it is the plain identifier."""

    def setUp(self):
        super().setUp()
        self.target = self.make_item(self.project, 'Service', 'D', 'svc', title='T', value='v', status='CNF')

    def display(self, config):
        return convert.convert_db_to_display('#iref:%d' % self.target.id, None, config, self.project.id)

    def test_a_category_without_short_descriptions_is_a_link_without_tooltip(self):
        config = template_config()
        config['cats']['Service']['short_desc'] = {}
        shown = self.display(config)
        self.assertIn('href="/editor/Service/', shown)
        self.assertIn('title=""', shown)
        self.assertIn('>D:svc</a>', shown)

    def test_a_tooltip_attribute_which_is_not_defined_is_skipped(self):
        config = template_config()
        del config['cats']['Service']['attrs']['value']
        self.assertIn('Title: T&#13;', self.display(config))
        self.assertNotIn('Type', self.display(config))

    def test_a_category_which_is_not_defined_is_the_plain_identifier(self):
        config = template_config()
        del config['cats']['Service']
        self.assertEqual(self.display(config), 'D:svc')

    def test_labels_in_tooltips_are_escaped(self):
        config = template_config()
        config['cats']['Service']['attrs']['title']['label'] = 'A<b>"x"'
        shown = self.display(config)
        self.assertNotIn('<b>', shown)
        self.assertIn('A&lt;b&gt;&quot;x&quot;', shown)


class ConfigurationOrderTests(ConfiguredTestCase):
    """The order of categories, attributes and choices is part of the configuration (menus, columns, defaults)."""

    def test_the_stored_order_is_the_order_in_menus_and_choices(self):
        def reorder(config):
            cats = config['cats']
            config['cats'] = {key: cats[key] for key in reversed(list(cats))}
            service = config['cats']['Service']
            service['attrs'] = {key: service['attrs'][key] for key in reversed(list(service['attrs']))}
            requirement = config['cats']['Requirement']
            requirement['p_kind_choices'] = {key: requirement['p_kind_choices'][key]
                                             for key in reversed(list(requirement['p_kind_choices']))}
        config = self.configure(self.project, reorder)
        stored = Project.objects.get(id=self.project.id).config
        self.assertEqual(list(stored['cats']), list(config['cats']))
        self.assertEqual(list(stored['cats']['Service']['attrs']), list(config['cats']['Service']['attrs']))
        menu = self.client.get(self.url('index')).context['list_of_projects'][0]['project_configs']
        self.assertEqual(list(menu), [cat for cat in config['cats'] if cat in ALL_CATS])
        choices = self.client.get(self.add_url('Requirement')).context['form'].fields['p_kind'].choices
        self.assertEqual([value for value, _ in choices], list(config['cats']['Requirement']['p_kind_choices']))

    def test_the_column_is_text_on_mysql_and_native_json_elsewhere(self):
        field = Project._meta.get_field('config')
        self.assertIsInstance(field, OrderedJSONField)

        class Connection:
            data_types = {'JSONField': 'json'}
            data_type_check_constraints = {}

            class ops:
                quote_name = staticmethod(lambda name: '`%s`' % name)

            def __init__(self, vendor):
                self.vendor = vendor

        self.assertEqual(field.db_type(Connection('mysql')), 'longtext')
        self.assertEqual(field.db_check(Connection('mysql')), 'JSON_VALID(`config`)')
        self.assertEqual(field.db_type(Connection('sqlite')), 'json')
        self.assertIsNone(field.db_check(Connection('sqlite')))

    def test_the_default_is_an_empty_object(self):
        self.assertEqual(Project._meta.get_field('config').get_default(), {})


class ServerSettingTests(ConfiguredTestCase):
    """temp_dir is a server setting: it is read from the Django settings, never from a project configuration."""

    def export(self, project, tmp):
        self.login(project.owner)
        with override_settings(TEMP_DIR=tmp), mock.patch('editor.views.make_temp_dir', wraps=__import__(
                'editor.utilities', fromlist=['make_temp_dir']).make_temp_dir) as spy:
            response = self.client.get(self.url('export_project', project.id))
            b''.join(response.streaming_content)
        return spy

    def test_the_temp_directory_comes_from_the_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            spy = self.export(self.project, tmp)
        self.assertEqual(spy.call_args.args[0], tmp)

    def test_a_temp_dir_inside_a_stored_configuration_is_ignored(self):
        stored = template_config()
        stored['general']['temp_dir'] = '/somewhere/else'
        Project.objects.filter(id=self.project.id).update(config=stored)
        with tempfile.TemporaryDirectory() as tmp:
            spy = self.export(self.project, tmp)
        self.assertEqual(spy.call_args.args[0], tmp)

    def test_the_default_is_tmp(self):
        from cordetfw_editor import settings as production_settings
        self.assertTrue(hasattr(production_settings, 'TEMP_DIR'))


class NoGlobalConfigurationTests(ConfiguredTestCase):
    """Acceptance criterion 10: nothing global is left."""

    def production_sources(self):
        for path in sorted(PRODUCTION_DIR.rglob('*.py')):
            if 'migrations' in path.parts:
                continue
            yield path, path.read_text()

    def test_the_global_dictionaries_and_adapters_are_gone(self):
        import editor.configs as configs_module
        import editor.markdown as markdown_module
        for module in (configs_module, convert, markdown_module):
            self.assertFalse(hasattr(module, 'configs'), module.__name__)

    def test_no_production_module_reads_the_template_except_project_config(self):
        readers = [path.name for path, text in self.production_sources() if re.search(r"open\([^)]*configs\.json", text)]
        self.assertEqual(readers, ['project_config.py'])

    def test_no_production_code_indexes_a_global_configs_dictionary(self):
        pattern = re.compile(r"(?<![A-Za-z_])configs\[|import configs\b|configs\.configs")
        offenders = [path.name for path, text in self.production_sources() if pattern.search(text)]
        self.assertEqual(offenders, [])

    def test_no_category_name_is_hard_coded_in_production_code_or_templates(self):
        names = '|'.join(load_template()['cats'])
        pattern = re.compile(r"""['"](%s)['"]""" % names)
        paths = [path for path, _ in self.production_sources()] + sorted((PRODUCTION_DIR / 'templates').glob('*.html'))
        offenders = []
        for path in paths:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith(('#', '*', '"""')):
                    offenders.append('%s:%d' % (path.name, number))
        self.assertEqual(offenders, [])

    def test_every_view_which_needs_a_configuration_reads_the_request_configuration(self):
        text = (PRODUCTION_DIR / 'views.py').read_text()
        self.assertNotIn('editor.configs import configs', text)
        self.assertGreaterEqual(text.count('get_request_config(request, project)'), 12)
