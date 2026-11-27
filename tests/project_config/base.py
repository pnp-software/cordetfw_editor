import copy
import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from editor.project_config import load_template

# Snapshot of the shared template; tests must never mutate it.
TEMPLATE = load_template()
ALL_CATS = list(TEMPLATE['cats'].keys())
APP_CATS = [c for c in ALL_CATS if TEMPLATE['cats'][c]['level'] == 'application']
PROJECT_CATS = [c for c in ALL_CATS if TEMPLATE['cats'][c]['level'] != 'application']
BACKEND = 'django.contrib.auth.backends.ModelBackend'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'

# Link targets required to be able to submit the add form of a category (p_link/s_link marked
# required in the template). Parent items are created through the ORM.
REQUIRED_LINKS = {
    'VerLink': {'p_link': 'VerItem', 's_link': 'Requirement'},
    'TracLink': {'p_link': 'DerReq', 's_link': 'ParReq'},
    'Packet': {'p_link': 'Service'},
    'DerPacket': {'p_link': 'EnumValue', 's_link': 'Packet'},
    'PacketPar': {'p_link': 'Packet', 's_link': 'DataItem'},
    'InCommand': {'p_link': 'Packet'},
    'OutComponent': {'p_link': 'Packet'},
    'DataItem': {'p_link': 'DataItemType'},
    'EnumValue': {'s_link': 'EnumType'},
}
# Categories whose link choices only exist when the parent items are passed in the query string.
PARENT_PARAM_CATS = ('TracLink',)


def now():
    return timezone.now()


class EditorTestCase(TestCase):
    """Creates a fresh owner, an RW user and an empty project (with Default ValSet) for each test."""

    def setUp(self):
        self.owner = self.make_user('owner')
        self.rw_user = self.make_user('rw_user')
        self.project, self.default_val_set = self.make_project('Proj', owner=self.owner, rw_users=[self.rw_user])
        self.application = self.make_application(self.project, 'App')
        self.client.force_login(self.rw_user, backend=BACKEND)

    # ---------------------------------------------------------------- factories
    def make_user(self, username, **kwargs):
        return User.objects.create_user(username, password='pw', **kwargs)

    def make_project(self, name, owner=None, cats=None, rw_users=(), ro_users=()):
        owner = owner or self.make_user(name + '_owner')
        release = Release.objects.create(release_author=owner, desc='Initial', updated_at=now(),
                                         project_version=0, application_version=0)
        project = Project.objects.create(name=name, desc='Desc ' + name, owner=owner, release=release,
                                         cats=','.join(cats if cats is not None else ALL_CATS))
        val_set = ValSet.objects.create(project=project, name='Default', desc='Default ValSet')
        for user in rw_users:
            ProjectUser.objects.create(project=project, user=user, role='RW')
        for user in ro_users:
            ProjectUser.objects.create(project=project, user=user, role='RO')
        return project, val_set

    def make_application(self, project, name, cats=None):
        release = Release.objects.create(release_author=project.owner, desc='Initial', updated_at=now(),
                                         project_version=0, application_version=0)
        return Application.objects.create(project=project, name=name, desc='Desc ' + name, release=release,
                                          cats=','.join(cats if cats is not None else APP_CATS))

    def make_item(self, project, cat, domain, name, application=None, val_set=None, status='NEW',
                  owner=None, **fields):
        """Create a SpecItem directly in the database (no form validation)."""
        if val_set is None:
            val_set = ValSet.objects.get(project=project, name='Default')
        if application is None and TEMPLATE['cats'].get(cat, {}).get('level') == 'application':
            application = project.applications.first()
        stamp = fields.pop('updated_at', now())
        values = dict(cat=cat, domain=domain, name=name, project=project, application=application,
                      val_set=val_set, status=status, owner=owner or project.owner,
                      updated_at=stamp, created_at=fields.pop('created_at', stamp))
        values.update(fields)
        return SpecItem.objects.create(**values)

    # ---------------------------------------------------------------- helpers
    def app_id(self, cat, application=None):
        """Application id to put in the URL for a category (0 for project-level categories)."""
        if TEMPLATE['cats'].get(cat, {}).get('level') == 'application':
            return (application or self.application).id
        return 0

    def url(self, name, *args):
        return reverse(name, args=args)

    def list_url(self, cat, project=None, val_set=None, sel_val='Sel_All', sel_rel_id=0, application_id=None):
        project = project or self.project
        val_set = val_set or self.default_val_set
        if application_id is None:
            application_id = self.app_id(cat)
        return self.url('list_spec_items', cat, project.id, application_id, val_set.id, sel_val, sel_rel_id)

    def item_url(self, name, item, sel_val='Sel_All', sel_rel_id=0, query=''):
        return self.url(name, item.cat, item.project_id, self.app_id(item.cat, item.application),
                        item.id, sel_val, sel_rel_id) + query

    def add_url(self, cat, query='', sel_val='Sel_All'):
        return self.url('add_spec_item', cat, self.project.id, self.app_id(cat), sel_val, 0) + query

    def login(self, user):
        self.client.force_login(user, backend=BACKEND)

    def form_payload(self, url, **overrides):
        """What a browser would post back after loading the form at url (hidden inputs included)."""
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        data = {}
        for bound in response.context['form']:
            if bound.field.disabled:
                continue
            value = bound.value()
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            data[bound.html_name] = value
        data.update(overrides)
        return data

    def messages_of(self, response):
        return [str(m) for m in response.wsgi_request._messages]

    def refresh(self, item):
        return SpecItem.objects.get(id=item.id)

    def parent_items(self, cat):
        """Create (via the ORM) the link targets needed to add an item of category cat."""
        parents = {}
        for link, target_cat in REQUIRED_LINKS.get(cat, {}).items():
            parents[link] = self.make_item(self.project, target_cat, 'ParDom', 'Par_' + link)
        return parents

    def add_payload(self, cat, parents, **overrides):
        """Valid add-form payload for category cat built from the template attrs."""
        cfg = TEMPLATE['cats'][cat]
        data = {}
        for attr in cfg['attrs']:
            if attr in cfg['ext_attrs'] or attr in ('val_set', 'owner', 'change_log'):
                continue
            if attr in ('domain', 'name'):
                data[attr] = 'Dom1' if attr == 'domain' else 'Item1'
            elif attr in ('p_kind', 's_kind'):
                choices = list(cfg[attr + '_choices'])
                data[attr] = choices[0]
            elif attr in ('p_link', 's_link'):
                if attr in parents:
                    data[attr] = parents[attr].id
            elif attr in ('n1', 'n2', 'n3'):
                data[attr] = {'n1': 1, 'n2': 2, 'n3': 3}[attr]
            elif cfg['attrs'][attr]['kind'] == 'eval_ref':
                data[attr] = '5'
            else:
                data[attr] = 'text_' + attr
        data.update(overrides)
        return data

    def ext_mocks(self, cat):
        """Context manager patching the FW Profile access used by categories with external attributes."""
        name = 'model' if cat == 'Model' else 'fcp'
        if cat == 'Model':
            choice = {'domain': 'ExtDom', 'name': 'ExtName', 'p_kind': 'SM', 'updated_at': now(),
                      'value': SVG, 'n1': 10, 'n2': 20, 'n3': 77}
        else:
            choice = {'domain': 'ExtDom', 'name': 'ExtName', 'updated_at': now(), 'title': 'Ext title',
                      'desc': 'Ext desc', 'value': SVG, 'n1': 10, 'n2': 20, 'n3': 77}
        stack = mock.patch.multiple('editor.ext_cats', create=False,
                                    **{'ext_%s_get_choices' % name: mock.Mock(return_value=[(77, 'ExtDom : ExtName')]),
                                       'ext_%s_get_choice' % name: mock.Mock(return_value=choice)})
        return stack
