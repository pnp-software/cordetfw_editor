"""Phase 0 characterization: lists, pagination, navigation, references, search/replace, history, releases."""
from datetime import timedelta

from django.utils import timezone

from editor.forms import identifier_error
from editor.models import Release, SpecItem, ValSet
from tests.project_config.base import ALL_CATS, APP_CATS, EditorTestCase, PROJECT_CATS, TEMPLATE, now

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class ListTests(EditorTestCase):
    def test_every_category_lists_with_every_display_mode(self):
        for cat in ALL_CATS:
            cfg = TEMPLATE['cats'][cat]
            item = self.make_item(self.project, cat, 'Dom1', 'Item1', title='Title ' + cat)
            for disp in ('disp_def', 'disp_short', 'disp_trac'):
                with self.subTest(cat=cat, disp=disp):
                    response = self.client.get(self.list_url(cat) + '?disp=' + disp)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context['config'], cfg)
                    self.assertEqual(response.context['disp_list'], cfg[disp])
                    self.assertEqual(response.context['n_pad_fields'], range(len(cfg[disp]) - 3))
                    self.assertEqual(response.context['find_replace_fields'], cfg['attrs'])
                    self.assertEqual(response.context['page_items'].paginator.per_page, cfg['page_size'])
                    self.assertEqual([i.id for i in response.context['page_items']], [item.id])
                    for column in cfg[disp]:
                        self.assertContains(response, column['header'])
                    self.assertContains(response, 'id="Dom1:Item1"')
                    self.assertContains(response, 'Add ' + cfg['name'])

    def test_list_excludes_deleted_obsolete_other_val_set_other_cat_and_other_project(self):
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='')
        other, _ = self.make_project('Other', owner=self.owner)
        shown = [self.make_item(self.project, 'Service', 'B', 'b'), self.make_item(self.project, 'Service', 'A', 'z'),
                 self.make_item(self.project, 'Service', 'A', 'a', status='CNF'),
                 self.make_item(self.project, 'Service', 'A', 'm', status='MOD')]
        self.make_item(self.project, 'Service', 'A', 'del', status='DEL')
        self.make_item(self.project, 'Service', 'A', 'obs', status='OBS')
        self.make_item(self.project, 'Service', 'A', 'alias', val_set=alt)
        self.make_item(self.project, 'Packet', 'A', 'pkt')
        self.make_item(other, 'Service', 'A', 'foreign')
        response = self.client.get(self.list_url('Service'))
        self.assertEqual([(i.domain, i.name) for i in response.context['page_items']],
                         [('A', 'a'), ('A', 'm'), ('A', 'z'), ('B', 'b')])
        self.assertEqual(response.context['domains'], ['Sel_All', 'A', 'B'])
        self.assertEqual(len(shown), 4)
        alias_list = self.client.get(self.list_url('Service', val_set=alt))
        self.assertEqual([i.name for i in alias_list.context['page_items']], ['alias'])

    def test_domain_filter_and_ordering(self):
        for domain, name, title in (('A', 'x', 'c'), ('A', 'y', 'a'), ('B', 'z', 'b')):
            self.make_item(self.project, 'Service', domain, name, title=title)
        by_domain = self.client.get(self.list_url('Service', sel_val='B'))
        self.assertEqual([i.name for i in by_domain.context['page_items']], ['z'])
        by_title = self.client.get(self.list_url('Service') + '?order_by=title')
        self.assertEqual([i.name for i in by_title.context['page_items']], ['y', 'z', 'x'])
        self.assertEqual(by_title.context['order_by'], 'title')
        self.assertIn('order_by=title&', by_title.context['get_parameter_sting'])

    def test_order_by_link_and_owner(self):
        svc_b = self.make_item(self.project, 'Service', 'S', 'b')
        svc_a = self.make_item(self.project, 'Service', 'S', 'a')
        self.make_item(self.project, 'Packet', 'P', 'p1', p_link=svc_b, owner=self.rw_user)
        self.make_item(self.project, 'Packet', 'P', 'p2', p_link=svc_a, owner=self.owner)
        by_link = self.client.get(self.list_url('Packet') + '?order_by=p_link')
        self.assertEqual([i.name for i in by_link.context['page_items']], ['p2', 'p1'])
        by_owner = self.client.get(self.list_url('Packet') + '?order_by=owner')
        self.assertEqual([i.name for i in by_owner.context['page_items']], ['p2', 'p1'])

    def test_pagination(self):
        SpecItem.objects.bulk_create([
            SpecItem(cat='Service', domain='D', name='s%03d' % i, project=self.project, val_set=self.default_val_set,
                     owner=self.owner, status='NEW', updated_at=now(), created_at=now())
            for i in range(101)])
        self.assertEqual(TEMPLATE['cats']['Service']['page_size'], 100)
        first = self.client.get(self.list_url('Service'))
        self.assertEqual(len(first.context['page_items']), 100)
        self.assertEqual({k: first.context['pagination'][k] for k in ('page_number', 'has_previous', 'previous_page', 'has_next', 'next_page')},
                         {'page_number': 1, 'has_previous': False, 'previous_page': None, 'has_next': True, 'next_page': 2})
        second = self.client.get(self.list_url('Service') + '?page=2')
        self.assertEqual([i.name for i in second.context['page_items']], ['s100'])
        self.assertEqual({k: second.context['pagination'][k] for k in ('page_number', 'has_previous', 'previous_page', 'has_next', 'next_page')},
                         {'page_number': 2, 'has_previous': True, 'previous_page': 1, 'has_next': False, 'next_page': None})
        self.assertContains(second, 'page=1')

    def test_expand_lists_the_children_of_the_expanded_item(self):
        packet = self.make_item(self.project, 'Packet', 'P', 'pkt', title='Pkt')
        der = self.make_item(self.project, 'DerPacket', 'P', 'der', s_link=packet)
        par = self.make_item(self.project, 'PacketPar', 'P', 'par', p_link=packet)
        self.make_item(self.project, 'DerPacket', 'P', 'gone', s_link=packet, status='DEL')
        self.make_item(self.project, 'PacketPar', 'P', 'other', p_link=self.make_item(self.project, 'Packet', 'P', 'p2'))
        s_resp = self.client.get(self.list_url('Packet') + '?expand_id=%d&expand_link=s_link' % packet.id)
        self.assertEqual([i.id for i in s_resp.context['expand_items']], [der.id])
        self.assertEqual(s_resp.context['expand_id'], packet.id)
        self.assertContains(s_resp, 'Add Derived Packet Child')
        p_resp = self.client.get(self.list_url('Packet') + '?expand_id=%d&expand_link=p_link' % packet.id)
        self.assertEqual([i.id for i in p_resp.context['expand_items']], [par.id])
        self.assertContains(p_resp, 'Add Parameter Child')
        none_resp = self.client.get(self.list_url('Service') + '?expand_id=1&expand_link=s_link')
        self.assertIsNone(none_resp.context['expand_items'])

    def test_breadcrumb_lists_categories_by_access_level(self):
        project, vs = self.make_project('Small', owner=self.owner, cats=['Service', 'DataItem', 'Requirement'], rw_users=[self.rw_user])
        app = self.make_application(project, 'AppA', cats=['Requirement'])
        self.make_application(project, 'Empty', cats=[])
        response = self.client.get(self.list_url('Service', project=project, val_set=vs, application_id=0))
        crumb = response.context['breadcrumb']
        self.assertEqual([d['list_as'] for d in crumb['active']], ['Data Item'])
        self.assertEqual([d['list_as'] for d in crumb['rest']], ['Small / AppA / Requirement'])
        self.assertEqual(crumb['rest'][0]['application_id'], app.id)
        app_resp = self.client.get(self.list_url('Requirement', project=project, val_set=vs, application_id=app.id))
        crumb = app_resp.context['breadcrumb']
        self.assertEqual(crumb['application_name_active'], 'AppA')
        self.assertEqual([d['list_as'] for d in crumb['active']], [])
        self.assertEqual(sorted(d['list_as'] for d in crumb['rest']), ['Small / Data Item', 'Small / Service'])


class IndexTests(EditorTestCase):
    def test_index_offers_the_categories_of_the_project_by_access_level(self):
        project, vs = self.make_project('Small', owner=self.owner, cats=['Service', 'Requirement', 'EnumValue', 'DataItem'])
        app = self.make_application(project, 'AppA', cats=['Requirement'])
        self.login(self.owner)
        response = self.client.get('/editor/')
        entry = [e for e in response.context['list_of_projects'] if e['project'].id == project.id][0]
        self.assertEqual(list(entry['project_configs']), [c for c in ALL_CATS if c in ('Service', 'Requirement', 'EnumValue', 'DataItem')])
        self.assertEqual(entry['default_val_set_id'], vs.id)
        self.assertEqual(entry['applications'], [app])
        prefix = '/editor/%s/' + str(project.id) + '/%d/' + str(vs.id) + '/Sel_All/0/list_spec_items?disp=disp_def'
        self.assertContains(response, prefix % ('Service', 0))
        self.assertContains(response, prefix % ('DataItem', 0))
        self.assertContains(response, prefix % ('Requirement', app.id))
        self.assertNotContains(response, prefix % ('Requirement', 0))
        self.assertNotContains(response, prefix % ('EnumValue', 0))      # access_from_index level 'None'

    def test_index_hides_manage_menu_from_users_without_access(self):
        project, vs = self.make_project('Secret', owner=self.make_user('boss'), cats=['Service'])
        self.login(self.rw_user)
        response = self.client.get('/editor/')
        self.assertNotContains(response, '/editor/Service/%d/0/' % project.id)


class ReferenceDisplayTests(EditorTestCase):
    def test_references_are_stored_as_item_ids_and_displayed_as_links(self):
        target = self.make_item(self.project, 'Service', 'S', 'svc', title='Svc title', value='Svc value')
        payload = self.add_payload('Packet', {'p_link': target}, desc='see #Service:S:svc and #Service:S:nope')
        self.assertEqual(self.client.post(self.add_url('Packet'), payload).status_code, 302)
        packet = SpecItem.objects.get(cat='Packet')
        self.assertEqual(packet.desc, 'see #iref:%d and #Service:S:nope' % target.id)
        edit = self.client.get(self.item_url('edit_spec_item', packet)).context['form']
        self.assertEqual(edit['desc'].value(), 'see #Service:S:svc and #Service:S:nope')
        html = self.client.get(self.list_url('Packet')).content.decode()
        self.assertIn('>S:svc</a>', html)
        self.assertIn('class="link-danger"', html)                        # NEW target is shown in red
        self.assertIn('Title: Svc title&#13;', html)                      # tooltip built from short_desc.href_tip
        self.assertIn('Type: Svc value&#13;', html)

    def test_dangling_references_and_markdown(self):
        item = self.make_item(self.project, 'Service', 'S', 'svc', desc='**bold** and #iref:99999', title='t')
        html = self.client.get(self.list_url('Service')).content.decode()
        self.assertIn('<b>bold</b> and ERROR:99999', html)
        self.assertEqual(self.refresh(item).desc, '**bold** and #iref:99999')

    def test_eval_ref_values_are_evaluated_for_display(self):
        a = self.make_item(self.project, 'DataItem', 'D', 'a', value='2')
        self.make_item(self.project, 'DataItem', 'D', 'b', value='#iref:%d * 3' % a.id)
        html = self.client.get(self.list_url('DataItem')).content.decode()
        self.assertIn('D:a</a> * 3 = 6.0', html)

    def test_link_columns_and_traceability_columns(self):
        requirement = self.make_item(self.project, 'Requirement', 'R', 'req', value='r')
        ver_item = self.make_item(self.project, 'VerItem', 'V', 'ver', title='Verifier')
        self.make_item(self.project, 'VerLink', 'L', 'link', p_link=ver_item, s_link=requirement, title='l')
        html = self.client.get(self.list_url('Requirement') + '?disp=disp_trac').content.decode()
        self.assertIn('Verification Links', html)
        self.assertIn('>V:ver</a> (Verifier)', html)
        verlinks = self.client.get(self.list_url('VerLink')).content.decode()
        self.assertIn('>V:ver</a>', verlinks)
        self.assertIn('>R:req</a>', verlinks)


class FindReplaceTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.a = self.make_item(self.project, 'Service', 'D', 'a', title='foo one foo', status='CNF',
                                updated_at=now() - timedelta(days=1))
        self.b = self.make_item(self.project, 'Service', 'E', 'b', title='no match')
        self.c = self.make_item(self.project, 'Service', 'D', 'c', title='foo three')
        self.list = self.list_url('Service')

    def replace(self, field='title', find='foo', replace='bar', url=None, ajax=True):
        extra = AJAX if ajax else {}
        return self.client.post(url or self.list, {'field': field, 'find': find, 'replace': replace}, **extra)

    def test_replaces_in_all_matching_items_of_the_list(self):
        before = self.a.updated_at
        response = self.replace()
        self.assertEqual(response.json(), {'updated_count': 2})
        self.assertEqual(self.refresh(self.a).title, 'bar one bar')
        self.assertEqual(self.refresh(self.c).title, 'bar three')
        self.assertEqual(self.refresh(self.b).title, 'no match')
        a = self.refresh(self.a)
        self.assertEqual(a.status, 'CNF')                          # no obsolete copy is made
        self.assertEqual(SpecItem.objects.filter(cat='Service').count(), 3)
        self.assertGreater(a.updated_at, before)
        self.assertEqual(a.owner_id, self.rw_user.id)

    def test_replacement_is_limited_to_the_selected_domain_and_list(self):
        response = self.replace(url=self.list_url('Service', sel_val='E'))
        self.assertEqual(response.json(), {'updated_count': 0})
        self.assertEqual(self.refresh(self.a).title, 'foo one foo')
        other, other_vs = self.make_project('Other', owner=self.owner)
        foreign = self.make_item(other, 'Service', 'D', 'f', title='foo')
        alias = self.make_item(self.project, 'Service', 'D', 'a', val_set=ValSet.objects.create(project=self.project, name='Alt', desc=''),
                               title='foo alias')
        self.make_item(self.project, 'Service', 'D', 'gone', status='DEL', title='foo del')
        self.assertEqual(self.replace().json(), {'updated_count': 2})
        self.assertEqual(self.refresh(foreign).title, 'foo')
        self.assertEqual(self.refresh(alias).title, 'foo alias')
        self.assertEqual(SpecItem.objects.get(name='gone').title, 'foo del')

    def test_non_ajax_post_also_applies_and_renders_the_list(self):
        response = self.replace(ajax=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.refresh(self.c).title, 'bar three')
        self.assertIn('page_items', response.context)

    def test_errors_are_reported_and_nothing_is_changed(self):
        cases = [
            (dict(find='x', replace='x'), '__all__', 'Error: Find and replace values must be different'),
            (dict(field='bogus'), 'field', 'Select a valid field'),
            (dict(field='name', find='a', replace='b c'), '__all__', identifier_error),
            (dict(field='title', find='foo', replace='y' * 256), 'replace', 'Ensure this value has at most 255 characters (it has 256).'),
            (dict(field='title', find='foo', replace='y' * 200), '__all__', None),     # resulting title exceeds the model limit
        ]
        for kwargs, key, message in cases:
            with self.subTest(kwargs=kwargs):
                response = self.replace(**kwargs)
                self.assertEqual(response.status_code, 400)
                errors = response.json()['errors']
                self.assertIn(key, errors)
                if message:
                    self.assertEqual(errors[key][0]['message'], message)
                self.assertEqual(self.refresh(self.a).title, 'foo one foo')

    def test_renaming_to_an_existing_identifier_is_rejected_atomically(self):
        self.make_item(self.project, 'Service', 'D', 'a2')
        x = self.make_item(self.project, 'Service', 'D', 'a1')
        response = self.replace(field='name', find='a1', replace='a2')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors']['__all__'][0]['message'], "Error: Name 'a2' already exists in domain 'D'")
        self.assertEqual(self.refresh(x).name, 'a1')
        self.assertEqual(self.replace(field='name', find='a1', replace='a9').json(), {'updated_count': 1})
        self.assertEqual(self.refresh(x).name, 'a9')

    def test_link_fields_are_not_searched(self):
        svc = self.make_item(self.project, 'Service', 'S', 'svc')
        self.make_item(self.project, 'Packet', 'P', 'p', p_link=svc, title='foo')
        response = self.replace(field='p_link', url=self.list_url('Packet'))
        self.assertEqual(response.json(), {'updated_count': 0})


class HistoryTests(EditorTestCase):
    def test_history_page_for_every_category(self):
        for cat in ALL_CATS:
            with self.subTest(cat=cat):
                item = self.make_item(self.project, cat, 'Dom1', 'Item_' + cat, status='CNF', title='t')
                response = self.client.get(self.url('list_spec_item_history', cat, self.project.id, self.app_id(cat), item.id, 'Sel_All'))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['history'])
                self.assertEqual(response.context['disp_list'], TEMPLATE['cats'][cat]['disp_def'])
                self.assertEqual([i.id for i in response.context['page_items']], [item.id])
                self.assertContains(response, 'Change Log')

    def test_history_lists_all_versions_newest_first(self):
        service = self.make_item(self.project, 'Service', 'S', 's')
        packet = self.make_item(self.project, 'Packet', 'P', 'pkt', p_link=service, p_kind='TC', status='CNF',
                                title='v1', value='v', t1='a', t2='b')
        url = self.item_url('edit_spec_item', packet)
        self.assertEqual(self.client.post(url, self.form_payload(url, title='v2', change_log='second')).status_code, 302)
        self.login(self.owner)
        self.assertEqual(self.client.post(self.url('make_project_release', self.project.id),
                                          {'description': 'R1'}).status_code, 302)
        self.login(self.rw_user)
        url = self.item_url('edit_spec_item', packet)
        self.assertEqual(self.client.post(url, self.form_payload(url, title='v3', change_log='third')).status_code, 302)
        response = self.client.get(self.url('list_spec_item_history', 'Packet', self.project.id, 0, packet.id, 'Sel_All'))
        items = response.context['page_items']
        self.assertEqual([(i.title, i.status) for i in items], [('v3', 'MOD'), ('v2', 'OBS'), ('v1', 'OBS')])
        self.assertEqual(items[0].change_log, 'third')
        self.assertEqual(items[1].change_log, 'second')
        self.assertEqual(items[2].change_log, '')
        self.assertContains(response, 'MOD (')
        self.assertContains(response, 'third')
        self.assertContains(response, 'History of %s:%s' % (packet.domain, packet.name))


class ReleaseTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        self.proj_new = self.make_item(self.project, 'Service', 'S', 'new')
        self.proj_mod = self.make_item(self.project, 'Service', 'S', 'mod', status='MOD')
        self.proj_del = self.make_item(self.project, 'Service', 'S', 'del', status='DEL')
        self.proj_obs = self.make_item(self.project, 'Service', 'S', 'obs', status='OBS')
        self.app_new = self.make_item(self.project, 'Requirement', 'R', 'new', application=self.application)
        self.app2 = self.make_application(self.project, 'App2')
        self.app2_new = self.make_item(self.project, 'Requirement', 'R', 'new2', application=self.app2)

    def statuses(self):
        items = {'proj_new': self.proj_new, 'proj_mod': self.proj_mod, 'proj_del': self.proj_del,
                 'proj_obs': self.proj_obs, 'app_new': self.app_new, 'app2_new': self.app2_new}
        return {key: self.refresh(item).status for key, item in items.items()}

    def test_project_release_confirms_new_and_modified_items_and_creates_releases(self):
        self.login(self.owner)
        old_release = self.project.release
        old_app_releases = {self.application.id: self.application.release_id, self.app2.id: self.app2.release_id}
        before = Release.objects.count()
        response = self.client.post(self.url('make_project_release', self.project.id), {'description': 'Release one'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/editor')
        self.assertEqual(self.statuses(), {'proj_new': 'CNF', 'proj_mod': 'CNF', 'proj_del': 'DEL', 'proj_obs': 'OBS',
                                           'app_new': 'CNF', 'app2_new': 'CNF'})
        project = type(self.project).objects.get(id=self.project.id)
        self.assertEqual((project.release.project_version, project.release.application_version), (1, 0))
        self.assertEqual(project.release.previous, old_release)
        self.assertEqual((project.release.desc, project.release.release_author_id), ('Release one', self.owner.id))
        for app in (self.application, self.app2):
            app = type(app).objects.get(id=app.id)
            self.assertEqual((app.release.project_version, app.release.application_version), (1, 0))
            self.assertEqual(app.release.desc, 'Release one')
            self.assertEqual(app.release.previous_id, old_app_releases[app.id])
        self.assertEqual(Release.objects.count(), before + 3)

    def test_blank_release_description_creates_no_release(self):
        self.login(self.owner)
        before = Release.objects.count()
        response = self.client.post(self.url('make_project_release', self.project.id), {'description': '   '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Release.objects.count(), before)
        self.assertEqual(self.refresh(self.proj_new).status, 'NEW')

    def test_only_the_owner_can_make_releases(self):
        before = Release.objects.count()
        for name, arg in (('make_project_release', self.project.id), ('make_application_release', self.application.id)):
            response = self.client.post(self.url(name, arg), {'description': 'x'})
            self.assertEqual((response.status_code, response.url), (302, '/editor'))
        self.assertEqual(Release.objects.count(), before)
        self.assertEqual(self.refresh(self.proj_new).status, 'NEW')

    def test_application_release_only_affects_that_application(self):
        self.login(self.owner)
        old_project_release = self.project.release_id
        response = self.client.post(self.url('make_application_release', self.application.id), {'description': 'App rel'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.statuses(), {'proj_new': 'NEW', 'proj_mod': 'MOD', 'proj_del': 'DEL', 'proj_obs': 'OBS',
                                           'app_new': 'CNF', 'app2_new': 'NEW'})
        application = type(self.application).objects.get(id=self.application.id)
        self.assertEqual(application.release.application_version, 1)
        self.assertEqual(application.release.desc, 'App rel')
        self.assertEqual(type(self.project).objects.get(id=self.project.id).release_id, old_project_release)

    def test_listing_a_release_shows_the_items_as_they_were(self):
        t0 = timezone.now() - timedelta(days=10)
        t1 = timezone.now() - timedelta(days=5)
        t2 = timezone.now() - timedelta(days=1)
        release = Release.objects.create(release_author=self.owner, desc='old', updated_at=t1, project_version=1,
                                         application_version=0, previous=self.project.release)
        self.project.release = release
        self.project.save()
        kept = self.make_item(self.project, 'Service', 'R', 'kept', status='CNF', created_at=t0, updated_at=t0)
        self.make_item(self.project, 'Service', 'R', 'created_later', status='CNF', created_at=t2, updated_at=t2)
        self.make_item(self.project, 'Service', 'R', 'changed_later', status='CNF', created_at=t0, updated_at=t2)
        self.make_item(self.project, 'Service', 'R', 'deleted_before', status='DEL', created_at=t0, updated_at=t0)
        deleted_after = self.make_item(self.project, 'Service', 'R', 'deleted_after', status='DEL', created_at=t0, updated_at=t2)
        self.make_item(self.project, 'Service', 'R', 'work_in_progress', status='NEW', created_at=t0, updated_at=t0)
        response = self.client.get(self.list_url('Service', sel_rel_id=release.id))
        self.assertEqual(sorted(i.name for i in response.context['page_items']), sorted([kept.name, deleted_after.name]))
        self.assertEqual(response.context['sel_rel'], release)
        self.assertEqual([r.id for r in response.context['releases']], [release.id, release.previous_id])
        self.assertContains(response, 'Release: 1.0')
