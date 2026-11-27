"""Phase 0 characterization: add/edit/copy/split/delete of items for every template category.

The tests capture the behavior of the editor before the configuration refactoring and must keep passing
afterwards. Test methods are generated per category so that a failure names the category.
"""
from editor.models import SpecItem, ValSet
from tests.project_config.base import (ALL_CATS, EditorTestCase, PARENT_PARAM_CATS, REQUIRED_LINKS, SVG, TEMPLATE, now)

EXT_CATS = [c for c in ALL_CATS if TEMPLATE['cats'][c]['ext_attrs']]

def edit_attr(cat):
    """An attribute the user can change when editing (FW Profile attributes come from the source item)."""
    return 'title' if 'title' not in TEMPLATE['cats'][cat]['ext_attrs'] else 'rationale'


DATA_ATTRS = ('domain', 'name', 'title', 'desc', 'value', 'rationale', 'remarks', 'implementation',
              't1', 't2', 't3', 't4', 't5', 'n1', 'n2', 'n3', 'p_kind', 's_kind', 'change_log')


class CrudMixin:
    """Helpers shared by the generated CRUD tests."""

    def parent_query(self, parents):
        if not parents:
            return ''
        return '?p_parent_id=%d&s_parent_id=%d' % (parents['p_link'].id, parents['s_link'].id)

    def make_full_item(self, cat, status='NEW', name='Item1'):
        """Create an item of category cat via the ORM with every configured attribute filled in."""
        parents = self.parent_items(cat)
        payload = self.add_payload(cat, parents, name=name)
        fields = {k: v for k, v in payload.items() if k not in ('p_link', 's_link')}
        for link, parent in parents.items():
            fields[link] = parent
        if cat in EXT_CATS:
            fields.update(domain='ExtDom', name=name, value=SVG, n1=10, n2=20, n3=77)
            if cat == 'FCP':
                fields.update(title='Ext title', desc='Ext desc')
        item = self.make_item(self.project, cat, fields.pop('domain', 'Dom1'), fields.pop('name'),
                              status=status, owner=self.owner, **fields)
        return item, parents

    def snapshot(self, item):
        item = self.refresh(item)
        data = {attr: getattr(item, attr) for attr in DATA_ATTRS}
        data.update(p_link=item.p_link_id, s_link=item.s_link_id, val_set=item.val_set_id,
                    application=item.application_id, project=item.project_id, cat=item.cat)
        return data


def make_add_test(cat):
    def test(self):
        parents = self.parent_items(cat)
        query = self.parent_query(parents) if cat in PARENT_PARAM_CATS else ''
        payload = self.add_payload(cat, parents)
        expected = dict(payload)
        before = now()
        if cat in EXT_CATS:
            payload['ext_item'] = 77
            for key in TEMPLATE['cats'][cat]['ext_attrs']:
                payload.pop(key, None)
            expected = {k: v for k, v in expected.items() if k not in TEMPLATE['cats'][cat]['ext_attrs']}
            expected.update(domain='ExtDom', name='ExtName', value=SVG, n1=10, n2=20, n3=77)
            if cat == 'FCP':
                expected.update(title='Ext title', desc='Ext desc')
            with self.ext_mocks(cat):
                response = self.client.post(self.add_url(cat, query), payload)
        else:
            response = self.client.post(self.add_url(cat, query), payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        item = SpecItem.objects.get(project=self.project, cat=cat)
        for attr, value in expected.items():
            if attr in ('p_link', 's_link'):
                self.assertEqual(getattr(item, attr + '_id'), value, attr)
            else:
                self.assertEqual(getattr(item, attr), value, attr)
        # Attributes that are not configured for the category keep their defaults
        for attr in ('rationale', 'remarks', 'implementation', 't1', 't2', 't3', 't4', 't5', 'desc', 'value'):
            if attr not in TEMPLATE['cats'][cat]['attrs']:
                self.assertEqual(getattr(item, attr), '', attr)
        self.assertEqual(item.status, 'NEW')
        self.assertEqual(item.val_set_id, self.default_val_set.id)
        self.assertEqual(item.owner_id, self.rw_user.id)
        self.assertEqual(item.project_id, self.project.id)
        self.assertEqual(item.application_id, self.application.id if self.app_id(cat) else None)
        self.assertGreaterEqual(item.updated_at, before)
        self.assertIsNone(item.previous)
        self.assertEqual(SpecItem.objects.filter(project=self.project, cat=cat).count(), 1)
        # Redirect: to the list of the category, or to the expanded parent when parents are passed in
        scope = '/%d/%d/%d/Sel_All/0/list_spec_items' % (self.project.id, self.app_id(cat), self.default_val_set.id)
        if cat in PARENT_PARAM_CATS:
            parent = parents['s_link']
            self.assertEqual(response.url, '/editor/%s%s?expand_id=%d&expand_link=s_link#%s:%s' %
                             (parent.cat, scope, parent.id, parent.domain, parent.name))
        else:
            self.assertEqual(response.url, '/editor/%s%s#%s:%s' % (cat, scope, item.domain, item.name))
    return test


def make_edit_new_test(cat):
    def test(self):
        item, parents = self.make_full_item(cat)
        before = self.snapshot(item)
        url = self.item_url('edit_spec_item', item, query=self.parent_query(parents) if cat in PARENT_PARAM_CATS else '')
        payload = self.form_payload(url, **{edit_attr(cat): 'Edited text'})
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        after = self.snapshot(item)
        expected = dict(before, **{edit_attr(cat): 'Edited text'})
        self.assertEqual(after, expected)
        self.assertEqual(SpecItem.objects.filter(project=self.project, cat=cat).count(), 1)
        item = self.refresh(item)
        self.assertEqual(item.status, 'NEW')
        self.assertEqual(item.owner_id, self.rw_user.id)
        self.assertIsNone(item.previous)
    return test


def make_edit_cnf_test(cat):
    def test(self):
        item, parents = self.make_full_item(cat, status='CNF')
        before = self.snapshot(item)
        url = self.item_url('edit_spec_item', item, query=self.parent_query(parents) if cat in PARENT_PARAM_CATS else '')
        payload = self.form_payload(url, change_log='Reason for change', **{edit_attr(cat): 'Edited text'})
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        edited = self.refresh(item)
        self.assertEqual(edited.id, item.id)
        self.assertEqual(edited.status, 'MOD')
        self.assertEqual(getattr(edited, edit_attr(cat)), 'Edited text')
        self.assertEqual(edited.change_log, 'Reason for change' if 'change_log' in TEMPLATE['cats'][cat]['attrs'] else edited.change_log)
        obsolete = edited.previous
        self.assertIsNotNone(obsolete)
        self.assertNotEqual(obsolete.id, item.id)
        self.assertEqual(obsolete.status, 'OBS')
        self.assertEqual(getattr(obsolete, edit_attr(cat)), before[edit_attr(cat)])
        self.assertEqual(obsolete.name, before['name'])
        self.assertIsNone(obsolete.previous)
        self.assertEqual(SpecItem.objects.filter(project=self.project, cat=cat).count(), 2)
    return test


def make_copy_test(cat):
    def test(self):
        item, parents = self.make_full_item(cat)
        before = self.snapshot(item)
        query = self.parent_query(parents) if cat in PARENT_PARAM_CATS else ''
        url = self.item_url('copy_spec_item', item, query=query)
        payload = self.form_payload(url, name='Copy1')
        response = self.client.post(url, payload)
        if cat in EXT_CATS:     # FW Profile attributes, incl. domain and name, always come from the source item
            self.assertEqual(response.status_code, 200)
            self.assertIn('name', response.context['form'].errors)
            self.assertEqual(SpecItem.objects.filter(project=self.project, cat=cat).count(), 1)
            return
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        self.assertEqual(self.snapshot(item), before)       # the original is untouched
        copy = SpecItem.objects.get(project=self.project, cat=cat, name='Copy1')
        self.assertNotEqual(copy.id, item.id)
        self.assertEqual(self.snapshot(copy), dict(before, name='Copy1'))
        self.assertEqual(copy.status, 'NEW')
        self.assertEqual(copy.owner_id, self.rw_user.id)
        self.assertIsNone(copy.previous)
        self.assertEqual(SpecItem.objects.filter(project=self.project, cat=cat).count(), 2)
    return test


def make_split_test(cat):
    def test(self):
        item, parents = self.make_full_item(cat)
        before = self.snapshot(item)
        alt = ValSet.objects.create(project=self.project, name='Alt', desc='Alternative')
        query = self.parent_query(parents) if cat in PARENT_PARAM_CATS else ''
        url = self.item_url('split_spec_item', item, query=query)
        payload = self.form_payload(url, val_set=alt.id)
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        self.assertEqual(self.snapshot(item), before)
        alias = SpecItem.objects.get(project=self.project, cat=cat, val_set=alt)
        self.assertEqual(alias.p_link_id, item.id)                  # the split item points to its original
        self.assertEqual((alias.domain, alias.name), (item.domain, item.name))
        self.assertEqual(alias.status, 'NEW')
        self.assertEqual(alias.owner_id, self.rw_user.id)
        expected = dict(before, val_set=alt.id, p_link=item.id)
        self.assertEqual(self.snapshot(alias), expected)
    return test


def make_del_new_test(cat):
    def test(self):
        item, parents = self.make_full_item(cat)
        query = self.parent_query(parents) if cat in PARENT_PARAM_CATS else ''
        self.assertEqual(self.client.get(self.item_url('del_spec_item', item, query=query)).status_code, 200)    # GET only shows the form
        self.assertTrue(SpecItem.objects.filter(id=item.id).exists())
        response = self.client.post(self.item_url('del_spec_item', item, query=query))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SpecItem.objects.filter(id=item.id).exists())    # NEW items are removed physically
        self.assertEqual(SpecItem.objects.filter(project=self.project, cat=cat).count(), 0)
    return test


def make_del_cnf_test(cat):
    def test(self):
        item, parents = self.make_full_item(cat, status='CNF')
        before = self.snapshot(item)
        query = self.parent_query(parents) if cat in PARENT_PARAM_CATS else ''
        url = self.item_url('del_spec_item', item, query=query)
        self.assertEqual(self.client.get(url).status_code, 200)          # CNF items need a change log first
        payload = self.form_payload(url, change_log='Obsolete requirement')
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302, getattr(response, 'context', None) and response.context['form'].errors)
        deleted = self.refresh(item)
        self.assertEqual(deleted.status, 'DEL')
        self.assertEqual(deleted.change_log, 'Obsolete requirement')
        self.assertEqual(deleted.owner_id, self.rw_user.id)
        self.assertEqual(self.snapshot(deleted), dict(before, change_log='Obsolete requirement'))
    return test


class CrudTests(CrudMixin, EditorTestCase):
    """Generated: test_<operation>_<category> for all categories of the template."""

    def test_all_template_categories_are_covered(self):
        self.assertEqual(len(ALL_CATS), 30)
        for link_cat in REQUIRED_LINKS:
            self.assertIn(link_cat, ALL_CATS)


for _cat in ALL_CATS:
    for _op, _factory in (('add', make_add_test), ('edit_new', make_edit_new_test),
                          ('edit_cnf', make_edit_cnf_test), ('copy', make_copy_test),
                          ('split', make_split_test), ('del_new', make_del_new_test),
                          ('del_cnf', make_del_cnf_test)):
        setattr(CrudTests, 'test_%s_%s' % (_op, _cat), _factory(_cat))
