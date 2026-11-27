from django.contrib.messages import get_messages

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from tests.project_config.base import ALL_CATS, EditorTestCase, TEMPLATE

CATS_HELP = 'Must contain a comma-separated list of categories from: ' + ', '.join(ALL_CATS)


class ProjectFormTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.staff = self.make_user('staff', is_staff=True)
        self.login(self.staff)

    def add_project(self, cats, name='NewProj'):
        return self.client.post(self.url('add_project'), {'name': name, 'owner': self.owner.id, 'cats': cats,
                                                          'description': 'A new project'})

    def test_add_project_creates_project_release_and_default_val_set(self):
        response = self.add_project(' Service , Packet,DerPacket,PacketPar,VerLink , EnumType,EnumValue,DataItem,'
                                    'DataItemType,Requirement')
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        project = Project.objects.get(name='NewProj')
        self.assertEqual(project.cats, 'Service,Packet,DerPacket,PacketPar,VerLink,EnumType,EnumValue,DataItem,'
                                       'DataItemType,Requirement')
        self.assertEqual((project.owner_id, project.desc), (self.owner.id, 'A new project'))
        self.assertEqual((project.release.project_version, project.release.application_version, project.release.previous),
                         (0, 0, None))
        self.assertEqual(project.release.desc, 'Initial release for project NewProj')
        self.assertEqual(project.release.release_author_id, self.staff.id)
        self.assertEqual(list(ValSet.objects.filter(project=project).values_list('name', 'desc')), [('Default', 'Default ValSet')])

    def test_unknown_categories_are_rejected(self):
        response = self.add_project('Service,Bogus')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].errors['cats'], [CATS_HELP])
        self.assertFalse(Project.objects.filter(name='NewProj').exists())

    def test_categories_require_their_expand_and_traceability_dependencies(self):
        cases = [('Packet', 'Category Packet requires dependent category DerPacket'),
                 ('Packet,DerPacket', 'Category Packet requires dependent category PacketPar'),
                 ('Service', 'Category Service requires dependent category Packet'),
                 ('ParReq', 'Category ParReq requires dependent category TracLink'),
                 ('Requirement', 'Category Requirement requires dependent category VerLink'),
                 ('DerReq,VerLink', 'Category DerReq requires dependent category TracLink')]
        for cats, message in cases:
            with self.subTest(cats=cats):
                response = self.add_project(cats)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['form'].errors['cats'], [message])
        self.assertFalse(Project.objects.filter(name='NewProj').exists())

    def test_categories_without_dependencies_are_accepted_alone(self):
        for cat in ('InfoItem', 'VerLink', 'TracLink', 'EnumValue', 'AdaptPoint', 'FCP', 'Model', 'ComIntEvt'):
            with self.subTest(cat=cat):
                self.assertEqual(self.add_project(cat, name='P_' + cat).status_code, 302)

    def test_only_staff_can_add_projects(self):
        self.login(self.owner)
        response = self.add_project('InfoItem')
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        self.assertFalse(Project.objects.filter(name='NewProj').exists())

    def test_edit_project_requires_staff_even_for_the_owner(self):
        self.login(self.owner)
        url = self.url('edit_project', self.project.id)
        response = self.client.post(url, {'name': 'Hijacked', 'owner': self.owner.id, 'cats': 'InfoItem', 'description': 'x'})
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        self.assertEqual(Project.objects.get(id=self.project.id).name, 'Proj')

    def test_staff_can_edit_project_name_owner_and_categories(self):
        url = self.url('edit_project', self.project.id)
        response = self.client.post(url, {'name': 'Renamed', 'owner': self.rw_user.id, 'cats': 'InfoItem, VerLink',
                                          'description': 'new desc'})
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        project = Project.objects.get(id=self.project.id)
        self.assertEqual((project.name, project.desc, project.owner_id, project.cats),
                         ('Renamed', 'new desc', self.rw_user.id, 'InfoItem,VerLink'))
        bad = self.client.post(url, {'name': 'Renamed', 'owner': self.rw_user.id, 'cats': 'Requirement', 'description': 'd'})
        self.assertEqual(bad.context['form'].errors['cats'], ['Category Requirement requires dependent category VerLink'])

    def test_edit_project_form_is_prefilled(self):
        response = self.client.get(self.url('edit_project', self.project.id))
        form = response.context['form']
        self.assertEqual((form['name'].value(), form['cats'].value()), ('Proj', self.project.cats))
        self.assertEqual([u.user.username for u in response.context['project_users']], ['rw_user'])
        self.assertEqual([v.name for v in response.context['val_sets']], ['Default'])

    def test_project_users_are_managed_through_posts(self):
        newcomer = self.make_user('newcomer')
        url = self.url('edit_project', self.project.id)
        self.client.post(url, {'user_id': newcomer.id, 'role': 'RO'})
        self.assertEqual(ProjectUser.objects.get(project=self.project, user=newcomer).role, 'RO')
        self.client.post(url, {'user_id': newcomer.id, 'role': 'RW'})
        self.assertEqual(ProjectUser.objects.get(project=self.project, user=newcomer).role, 'RW')
        self.assertEqual(ProjectUser.objects.filter(project=self.project, user=newcomer).count(), 1)
        self.client.post(url, {'del_user_id': ProjectUser.objects.get(project=self.project, user=newcomer).id})
        self.assertFalse(ProjectUser.objects.filter(project=self.project, user=newcomer).exists())

    def test_old_get_links_no_longer_change_the_project(self):
        newcomer = self.make_user('newcomer')
        response = self.client.get(self.url('edit_project', self.project.id) + '?user_id=%d&role=RW' % newcomer.id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ProjectUser.objects.filter(project=self.project, user=newcomer).exists())

    def test_val_sets_are_managed_by_staff_only(self):
        add_url = self.url('add_val_set', self.project.id)
        response = self.client.post(add_url, {'name': 'Extra', 'description': 'Extra set'})
        self.assertEqual(response.url, '/editor/%d/edit_project' % self.project.id)
        extra = ValSet.objects.get(project=self.project, name='Extra')
        self.client.post(self.url('edit_val_set', self.project.id, extra.id), {'name': 'Extra2', 'description': 'd2'})
        self.assertEqual(ValSet.objects.get(id=extra.id).name, 'Extra2')
        self.client.post(self.url('edit_project', self.project.id), {'del_val_set_id': extra.id})
        self.assertFalse(ValSet.objects.filter(id=extra.id).exists())
        self.login(self.owner)
        self.assertEqual(self.client.post(add_url, {'name': 'Nope', 'description': 'd'}).url, '/editor')
        self.assertFalse(ValSet.objects.filter(name='Nope').exists())

    def test_val_set_in_use_cannot_be_deleted(self):
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        self.make_item(self.project, 'Service', 'S', 'x', val_set=alt)
        response = self.client.post(self.url('edit_project', self.project.id), {'del_val_set_id': alt.id}, follow=True)
        self.assertTrue(ValSet.objects.filter(id=alt.id).exists())
        self.assertTrue(any('Failure to delete ValSet' in str(m) for m in get_messages(response.wsgi_request)))

    def test_delete_project_removes_its_data_only(self):
        other, other_vs = self.make_project('Other', owner=self.owner)
        other_item = self.make_item(other, 'Service', 'S', 'keep')
        service = self.make_item(self.project, 'Service', 'S', 'svc')
        self.make_item(self.project, 'Packet', 'P', 'pkt', p_link=service)
        self.make_item(self.project, 'Requirement', 'R', 'req')
        releases_before = Release.objects.count()
        self.assertEqual(self.client.get(self.url('del_project', self.project.id)).status_code, 405)
        self.assertTrue(Project.objects.filter(id=self.project.id).exists())
        response = self.client.post(self.url('del_project', self.project.id))
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        self.assertFalse(Project.objects.filter(id=self.project.id).exists())
        self.assertFalse(SpecItem.objects.filter(project_id=self.project.id).exists())
        self.assertFalse(ValSet.objects.filter(project_id=self.project.id).exists())
        self.assertFalse(Application.objects.filter(project_id=self.project.id).exists())
        self.assertFalse(ProjectUser.objects.filter(project_id=self.project.id).exists())
        self.assertEqual(Release.objects.count(), releases_before - 2)       # project release + application release
        self.assertTrue(SpecItem.objects.filter(id=other_item.id).exists())
        self.assertTrue(Project.objects.filter(id=other.id).exists())


class ApplicationFormTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.login(self.owner)

    def test_owner_adds_an_application_with_categories_of_the_project(self):
        response = self.client.post(self.url('add_application', self.project.id),
                                    {'name': 'Second', 'description': 'desc', 'cats': 'Requirement, ParReq'})
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        application = Application.objects.get(name='Second')
        self.assertEqual((application.project_id, application.desc, application.cats), (self.project.id, 'desc', 'Requirement,ParReq'))
        self.assertEqual((application.release.project_version, application.release.application_version, application.release.previous),
                         (0, 0, None))
        self.assertEqual(application.release.desc, 'Initial release for application Second')

    def test_application_categories_must_belong_to_the_project(self):
        project, _ = self.make_project('Small', owner=self.owner, cats=['Requirement', 'VerLink'])
        response = self.client.post(self.url('add_application', project.id),
                                    {'name': 'A', 'description': 'd', 'cats': 'Requirement,ParReq'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].errors['cats'],
                         ['Must contain a comma-separated list of categories from: Requirement,VerLink'])
        self.assertFalse(Application.objects.filter(project=project).exists())

    def test_edit_application(self):
        response = self.client.post(self.url('edit_application', self.application.id),
                                    {'name': 'Renamed', 'description': 'new', 'cats': 'Requirement'})
        self.assertEqual((response.status_code, response.url), (302, '/editor'))
        application = Application.objects.get(id=self.application.id)
        self.assertEqual((application.name, application.desc, application.cats), ('Renamed', 'new', 'Requirement'))

    def test_only_the_owner_manages_applications(self):
        for user in (self.rw_user, self.make_user('staff', is_staff=True)):
            self.login(user)
            response = self.client.post(self.url('add_application', self.project.id),
                                        {'name': 'Sneaky', 'description': 'd', 'cats': 'Requirement'})
            self.assertEqual((response.status_code, response.url), (302, '/editor'))
            response = self.client.post(self.url('edit_application', self.application.id),
                                        {'name': 'Sneaky', 'description': 'd', 'cats': 'Requirement'})
            self.assertEqual(response.url, '/editor')
        self.assertFalse(Application.objects.filter(name='Sneaky').exists())
        self.assertEqual(Application.objects.get(id=self.application.id).name, 'App')
