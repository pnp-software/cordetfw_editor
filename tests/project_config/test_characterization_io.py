import csv
import io
import tempfile
from django.test import override_settings
import zipfile
from unittest import mock

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile

from editor.convert import convert_db_to_edit
from editor.forms import identifier_error
from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.project_config import load_template
from tests.project_config.base import EditorTestCase, TEMPLATE

TEXT_ATTRS = ('desc', 'rationale', 'remarks', 'implementation', 'value', 't1', 't2', 't3', 't4', 't5')
PLAIN_ATTRS = ('domain', 'name', 'title', 'p_kind', 's_kind', 'n1', 'n2', 'n3', 'status', 'change_log')   # s_data and created_at are not restored by import


def parse_csv(text):
    return list(csv.DictReader(io.StringIO(text), delimiter='|'))


class SpecItemExportTests(EditorTestCase):
    def export(self, cat, query='', application_id=None, sel_val='Sel_All'):
        if application_id is None:
            application_id = self.app_id(cat)
        url = self.url('export_spec_items', cat, self.project.id, application_id, self.default_val_set.id, sel_val, 0)
        return self.client.get(url + query)

    def setUp(self):
        super().setUp()
        self.service = self.make_item(self.project, 'Service', 'S', 'svc', title='Svc title', value='Type 1')
        self.packet = self.make_item(self.project, 'Packet', 'P', 'pkt', title='a_b & c', p_link=self.service,
                                     p_kind='TC', value='sub', t1='x', t2='y', desc='refers #iref:%d' % self.service.id)

    def test_plain_export_uses_attribute_labels_as_header(self):
        response = self.export('Packet')
        self.assertEqual(response['Content-Type'], 'text/plain')
        self.assertEqual(response['Content-Disposition'], 'attachment; filename= "ProjPacket.csv"')
        rows = parse_csv(response.content.decode())
        labels = [spec['label'] for spec in TEMPLATE['cats']['Packet']['attrs'].values()]
        self.assertEqual(list(rows[0].keys()), labels)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['Domain'], row['Name'], row['Title']), ('P', 'pkt', 'a_b & c'))
        self.assertEqual(row['Description'], 'refers #Service:S:svc')            # references exported in edit notation
        self.assertEqual(row['Type'], 'S:svc')                                   # spec_item_ref exported as domain:name
        self.assertEqual(row['Sub-Type'], 'sub')
        self.assertEqual(row['Owner'], 'owner')
        self.assertEqual(row['Val Set'] if 'Val Set' in row else row[TEMPLATE['cats']['Packet']['attrs']['val_set']['label']], 'Default')
        self.assertEqual(row[TEMPLATE['cats']['Packet']['attrs']['s_link']['label']], 'None')

    def test_export_file_name_depends_on_the_category_level_and_application(self):
        self.make_item(self.project, 'Requirement', 'R', 'req', value='v')
        self.assertEqual(self.export('Requirement')['Content-Disposition'], 'attachment; filename= "AppRequirement.csv"')
        self.assertEqual(self.export('Requirement', application_id=0)['Content-Disposition'],
                         'attachment; filename= "ProjRequirement.csv"')

    def test_export_of_an_empty_list_is_empty(self):
        self.assertEqual(self.export('InfoItem').content, b'')

    def test_export_honours_domain_filter_and_excludes_deleted_items(self):
        self.make_item(self.project, 'Service', 'T', 'other')
        self.make_item(self.project, 'Service', 'S', 'gone', status='DEL')
        rows = parse_csv(self.export('Service', sel_val='S').content.decode())
        self.assertEqual([r['Name'] for r in rows], ['svc'])

    def test_latex_export_escapes_text_and_adds_traceability_columns(self):
        ver_item = self.make_item(self.project, 'VerItem', 'V', 'ver', title='Verifier')
        self.make_item(self.project, 'VerLink', 'L', 'link', p_link=ver_item, s_link=self.packet, title='l')
        rows = parse_csv(self.export('Packet', '?export=latex_format').content.decode())
        row = rows[0]
        self.assertEqual(row['Title'], 'a\\_b \\& c')
        self.assertEqual(row['Description'], 'refers S:svc')
        self.assertEqual(row['Type'], 'S:svc')
        self.assertEqual(row['Owner'], 'owner')
        self.assertEqual(row['Status'], 'NEW')
        self.assertEqual(row['Project'], 'Proj')
        self.assertEqual(row['Application'], 'None')
        self.assertEqual(row['VerLink'], 'V:ver (Verifier)')               # from tracs: trac_cat VerLink via s_link
        for key in ('UpdatedAt', 'CreatedAt'):
            self.assertRegex(row[key], r'^\d\d-\d\d-\d{4} \d\d:\d\d$')

    def test_export_requires_read_access(self):
        self.login(self.make_user('stranger'))
        response = self.export('Service')
        self.assertEqual((response.status_code, response.url), (302, '/editor'))


class SpecItemImportTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.cfg = TEMPLATE['cats']['Service']['attrs']
        self.import_url = self.url_for()

    def url_for(self, cat='Service', val_set=None, sel_val='Sel_All'):
        val_set = val_set or self.default_val_set
        return self.url('import_spec_items', cat, self.project.id, self.app_id(cat), val_set.id, sel_val)

    def row(self, **values):
        """A complete CSV row for category Service keyed by column label."""
        base = {'domain': 'D', 'name': 'n1', 'title': 'Imported', 'desc': 'd', 'value': 'Type', 'rationale': 'r',
                'remarks': 'm', 'implementation': 'i', 'val_set': 'Default', 'change_log': '', 'owner': 'rw_user'}
        base.update(values)
        return {self.cfg[attr]['label']: base.get(attr, '') for attr in self.cfg}

    def upload(self, rows, url=None, fieldnames=None):
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=fieldnames or [s['label'] for s in self.cfg.values()], delimiter='|')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        upload = SimpleUploadedFile('items.csv', out.getvalue().encode('utf-8'), content_type='text/csv')
        response = self.client.post(url or self.import_url, {'upload_file': upload})
        return response, [str(m) for m in get_messages(response.wsgi_request)]

    def test_upload_form_is_offered(self):
        response = self.client.get(self.import_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload CSV File')

    def test_new_rows_create_new_items(self):
        response, messages = self.upload([self.row(), self.row(name='n2', title='Second')])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/editor/Service/%d/0/%d/Sel_All/0/list_spec_items' % (self.project.id, self.default_val_set.id))
        self.assertEqual(messages, ['2 imported, 0 rejected'])
        items = SpecItem.objects.filter(cat='Service').order_by('name')
        self.assertEqual([(i.domain, i.name, i.title, i.status, i.owner_id, i.project_id, i.val_set_id) for i in items],
                         [('D', 'n1', 'Imported', 'NEW', self.rw_user.id, self.project.id, self.default_val_set.id),
                          ('D', 'n2', 'Second', 'NEW', self.rw_user.id, self.project.id, self.default_val_set.id)])
        self.assertEqual((items[0].desc, items[0].value, items[0].rationale), ('d', 'Type', 'r'))

    def test_references_are_converted_to_database_notation(self):
        target = self.make_item(self.project, 'Service', 'S', 'target')
        self.upload([self.row(desc='see #Service:S:target')])
        self.assertEqual(SpecItem.objects.get(name='n1').desc, 'see #iref:%d' % target.id)

    def test_existing_new_item_is_updated_in_place(self):
        item = self.make_item(self.project, 'Service', 'D', 'n1', title='old', value='v')
        _, messages = self.upload([self.row(title='updated')])
        self.assertEqual(messages, ['1 imported, 0 rejected'])
        self.assertEqual(self.refresh(item).title, 'updated')
        self.assertEqual(SpecItem.objects.filter(cat='Service').count(), 1)

    def test_existing_confirmed_item_gets_an_obsolete_copy(self):
        item = self.make_item(self.project, 'Service', 'D', 'n1', title='old', value='v', status='CNF')
        self.upload([self.row(title='updated')])
        item = self.refresh(item)
        self.assertEqual((item.title, item.status), ('updated', 'MOD'))
        self.assertEqual((item.previous.title, item.previous.status), ('old', 'OBS'))

    def test_header_must_match_the_category(self):
        labels = [s['label'] for s in self.cfg.values()]
        response, messages = self.upload([], fieldnames=labels[1:] + ['Bogus'])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0], 'Uploaded CSV does not match the selected Service category: missing column(s): %s; '
                                      'unexpected column(s): Bogus' % labels[0])
        self.assertFalse(SpecItem.objects.exists())

    def test_rejected_rows_are_summarised_by_reason(self):
        self.make_item(self.project, 'Packet', 'D', 'taken')
        rows = [self.row(name='ok'), self.row(name='', title='x'), self.row(name='bad name'), self.row(name='taken'),
                self.row(name='wrongvs', val_set='Other')]
        _, messages = self.upload(rows)
        bad_identifier = "['%s']" % identifier_error
        self.assertEqual(messages, [
            '1 imported, 4 rejected. Rejected: line 3: %s; line 4: %s; line 5: identifier already in use outside '
            'selected category; line 6: incorrect ValSet' % (bad_identifier, bad_identifier)])
        self.assertEqual(list(SpecItem.objects.filter(cat='Service').values_list('name', flat=True)), ['ok'])

    def test_domain_must_match_the_selected_domain(self):
        _, messages = self.upload([self.row(domain='D'), self.row(domain='E', name='n2')], url=self.url_for(sel_val='D'))
        self.assertEqual(messages, ['1 imported, 1 rejected. Rejected: line 3: incorrect Domain'])

    def test_import_into_another_val_set_requires_the_item_in_the_default_val_set(self):
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        self.make_item(self.project, 'Service', 'D', 'n1')
        rows = [self.row(val_set='Alt'), self.row(val_set='Alt', name='n2')]
        _, messages = self.upload(rows, url=self.url_for(val_set=alt))
        self.assertEqual(messages, ['1 imported, 1 rejected. Rejected: line 3: missing from Default ValSet'])
        self.assertEqual(SpecItem.objects.filter(cat='Service', val_set=alt).count(), 1)

    def test_import_requires_write_access(self):
        self.login(self.make_user('stranger'))
        response, _ = self.upload([self.row()])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/editor')
        self.assertFalse(SpecItem.objects.exists())


class ProjectArchiveTests(EditorTestCase):
    CSV_NAMES = ['project.csv', 'applications.csv', 'val_sets.csv', 'project_users.csv', 'releases.csv', 'spec_items.csv']

    def setUp(self):
        super().setUp()
        self.build_project()

    def build_project(self):
        p = self.project
        self.alt = ValSet.objects.create(project=p, name='Alt', desc='Alternative')
        self.svc = self.make_item(p, 'Service', 'S', 'svc', title='Svc', value='Type', owner=self.owner)
        self.pkt = self.make_item(p, 'Packet', 'P', 'pkt', title='Pkt', p_link=self.svc, p_kind='TC', t1='a', t2='b',
                                  desc='uses #iref:%d' % self.svc.id, owner=self.rw_user, status='CNF')
        self.enum = self.make_item(p, 'EnumType', 'E', 'color', n1=1)
        self.val = self.make_item(p, 'EnumValue', 'E', 'red', s_link=self.enum, value='1', title='Red')
        self.der = self.make_item(p, 'DerPacket', 'P', 'der', p_link=self.val, s_link=self.pkt, t1='x')
        obsolete = self.make_item(p, 'Service', 'S', 'old', title='before', status='OBS')
        self.make_item(p, 'Service', 'S', 'old', title='after', status='MOD', previous=obsolete)
        self.make_item(p, 'Service', 'S', 'removed', status='DEL')
        self.alias = self.make_item(p, 'Service', 'S', 'svc', val_set=self.alt, p_link=self.svc, title='Svc alias', value='T2')
        self.req = self.make_item(p, 'Requirement', 'R', 'req', value='r #iref:%d' % self.svc.id, p_kind='STD', s_kind='TST')
        self.ver = self.make_item(p, 'VerItem', 'V', 'ver', title='Ver', p_kind='TST', s_kind='OPEN')
        self.make_item(p, 'VerLink', 'L', 'link', p_link=self.ver, s_link=self.req, title='l')
        self.hidden_app = self.make_application(p, 'Second', cats=['Requirement'])
        self.make_item(p, 'Requirement', 'R', 'req2', application=self.hidden_app, value='v2')

    def export_bytes(self, project=None):
        project = project or self.project
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.get(self.url('export_project', project.id))
            return b''.join(response.streaming_content)

    def export_zip(self, project=None):
        return zipfile.ZipFile(io.BytesIO(self.export_bytes(project)))

    def import_zip(self, archive_bytes, user=None):
        self.login(user or self.make_user('boss', is_staff=True))
        with tempfile.TemporaryDirectory() as tmp, override_settings(TEMP_DIR=tmp):
            response = self.client.post(self.url('import_project'),
                                        {'upload_file': SimpleUploadedFile('p.zip', archive_bytes)})
        return response, [str(m) for m in get_messages(response.wsgi_request)]

    def zip_bytes(self, files):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            for name, text in files.items():
                archive.writestr(name, text)
        return out.getvalue()

    def read_csv(self, archive, name):
        text = archive.read(name).decode('utf-8')
        return list(csv.DictReader(io.StringIO(text)))

    # ---------------------------------------------------------------- export
    def test_export_contains_the_six_tables(self):
        archive = self.export_zip()
        # The configuration is a seventh member (see test_project_config_archive.py); the tables are unchanged
        self.assertEqual(sorted(archive.namelist()), sorted(self.CSV_NAMES + ['config.json']))
        project = self.read_csv(archive, 'project.csv')
        self.assertEqual(len(project), 1)
        self.assertEqual(list(project[0].keys()), ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release'])
        self.assertEqual((project[0]['name'], project[0]['owner'], project[0]['cats']), ('Proj', 'owner', self.project.cats))
        self.assertEqual(project[0]['release'], str(self.project.release_id))

    def test_export_tables_hold_the_project_data(self):
        archive = self.export_zip()
        items = self.read_csv(archive, 'spec_items.csv')
        self.assertEqual(len(items), SpecItem.objects.filter(project=self.project).count())
        packet = [i for i in items if i['cat'] == 'Packet'][0]
        self.assertEqual(packet['desc'], 'uses #Service:S:svc')                     # edit notation
        self.assertEqual((packet['owner'], packet['p_link'], packet['status']), ('rw_user', str(self.svc.id), 'CNF'))
        self.assertEqual(sorted(v['name'] for v in self.read_csv(archive, 'val_sets.csv')), ['Alt', 'Default'])
        self.assertEqual([(u['user'], u['role']) for u in self.read_csv(archive, 'project_users.csv')], [('rw_user', 'RW')])
        self.assertEqual(sorted(a['name'] for a in self.read_csv(archive, 'applications.csv')), ['App', 'Second'])
        self.assertEqual(len(self.read_csv(archive, 'releases.csv')), 3)

    def test_export_excludes_other_projects(self):
        other, _ = self.make_project('Other', owner=self.owner)
        self.make_item(other, 'Service', 'X', 'foreign')
        archive = self.export_zip()
        self.assertNotIn('foreign', archive.read('spec_items.csv').decode())

    def test_export_requires_read_access(self):
        self.login(self.make_user('stranger'))
        response = self.client.get(self.url('export_project', self.project.id))
        self.assertEqual((response.status_code, response.url), (302, '/editor'))

    # ---------------------------------------------------------------- import
    def describe(self, project):
        """Content of a project independent of database ids."""
        def key(item):
            if item is None:
                return None
            return (item.cat, item.domain, item.name, item.val_set.name, item.status)
        items = {}
        for item in SpecItem.objects.filter(project=project):
            text = {a: convert_db_to_edit(getattr(item, a)) for a in TEXT_ATTRS}
            plain = {a: getattr(item, a) for a in PLAIN_ATTRS}
            items[key(item)] = dict(text, **plain, owner=item.owner.username, p_link=key(item.p_link), s_link=key(item.s_link),
                                    previous=key(item.previous), application=item.application.name if item.application else None)
        releases = []
        release = project.release
        while release is not None:
            releases.append((release.desc, release.project_version, release.release_author.username))
            release = release.previous
        applications = {a.name: (a.cats, a.desc) for a in Application.objects.filter(project=project)}
        return {'name_independent': (project.cats, project.desc, project.owner.username),
                'items': items, 'releases': releases, 'applications': applications,
                'val_sets': sorted(v.name for v in ValSet.objects.filter(project=project)),
                'users': sorted(u.user.username for u in ProjectUser.objects.filter(project=project))}

    def test_round_trip_recreates_the_project(self):
        # The archive carries the configuration, which must allow the stored Service -> Service link of
        # the alias item (the template has no such rule); the owner would have added it.
        config = load_template()
        config['general'].pop('temp_dir')
        config['cats']['Service']['links']['p_link'] = {'targets': ['Service']}
        Project.objects.filter(id=self.project.id).update(config=config)
        data = self.export_bytes()
        original = self.describe(self.project)
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        response, messages = self.import_zip(data)
        self.assertEqual((response.status_code, messages), (302, []))
        imported = Project.objects.get(name='Proj')
        self.assertNotEqual(imported.id, self.project.id)
        copy = self.describe(imported)
        self.assertEqual(copy['name_independent'], original['name_independent'])
        self.assertEqual(copy['val_sets'], original['val_sets'])
        self.assertEqual(copy['users'], original['users'])
        self.assertEqual(copy['applications'], original['applications'])
        self.assertEqual(copy['releases'], original['releases'])
        self.assertEqual(copy['items'], original['items'])
        self.assertEqual(len(copy['items']), 13)
        self.assertEqual(SpecItem.objects.filter(project=imported).count(), 13)
        self.assertFalse(set(SpecItem.objects.filter(project=imported).values_list('id', flat=True)) &
                         set(SpecItem.objects.filter(project=self.project).values_list('id', flat=True)))

    def test_import_is_refused_for_existing_project_names(self):
        response, messages = self.import_zip(self.export_bytes())
        self.assertEqual(messages, ['A project called Proj already exists'])
        self.assertEqual(Project.objects.filter(name='Proj').count(), 1)

    def test_import_requires_a_staff_user(self):
        data = self.export_bytes()
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        response, messages = self.import_zip(data, user=self.owner)
        self.assertEqual(messages, ['This operation is only accessible to a staff user'])
        self.assertFalse(Project.objects.filter(name='Proj').exists())

    def test_import_rejects_categories_missing_from_the_template(self):
        data = self.export_bytes()
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        archive = zipfile.ZipFile(io.BytesIO(data))
        files = {n: archive.read(n).decode('utf-8') for n in archive.namelist()}
        reader = list(csv.DictReader(io.StringIO(files['project.csv'])))
        reader[0]['cats'] = reader[0]['cats'] + ',Bogus'
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=list(reader[0].keys()))
        writer.writeheader()
        writer.writerows(reader)
        files['project.csv'] = out.getvalue()
        response, messages = self.import_zip(self.zip_bytes(files))
        self.assertEqual(messages, ['The project category Bogus is not defined in configs.json'])
        self.assertFalse(Project.objects.filter(name='Proj').exists())

    def test_import_of_an_application_category_missing_from_the_template_is_rejected(self):
        data = self.export_bytes()
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        archive = zipfile.ZipFile(io.BytesIO(data))
        files = {n: archive.read(n).decode('utf-8') for n in archive.namelist()}
        files['applications.csv'] = files['applications.csv'].replace('Requirement', 'Nothing', 1)
        response, messages = self.import_zip(self.zip_bytes(files))
        self.assertEqual(len(messages), 1)
        self.assertRegex(messages[0], r'The category .*Nothing.* in application .* is not defined in configs.json')
        self.assertFalse(Project.objects.filter(name='Proj').exists())

    def test_import_rejects_unknown_owner(self):
        data = self.export_bytes()
        Project.objects.filter(id=self.project.id).update(name='Proj_original')
        archive = zipfile.ZipFile(io.BytesIO(data))
        files = {n: archive.read(n).decode('utf-8') for n in archive.namelist()}
        lines = files['project.csv'].splitlines()
        files['project.csv'] = '\n'.join([lines[0], lines[1].replace(',owner,', ',nobody,')]) + '\n'
        response, messages = self.import_zip(self.zip_bytes(files))
        self.assertTrue(messages[0].startswith('The project owner nobody does not exist'))
        self.assertFalse(Project.objects.filter(name='Proj').exists())
