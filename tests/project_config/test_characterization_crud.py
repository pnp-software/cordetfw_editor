import pytest

from editor.models import SpecItem, ValSet
from tests.project_config.base import (ALL_CATS, PARENT_PARAM_CATS, REQUIRED_LINKS, SVG, TEMPLATE, World,
                                       add_payload, ext_mocks, make_item, now, refresh)

pytestmark = pytest.mark.django_db

EXT_CATS = [c for c in ALL_CATS if TEMPLATE['cats'][c]['ext_attrs']]

DATA_ATTRS = ('domain', 'name', 'title', 'desc', 'value', 'rationale', 'remarks', 'implementation',
              't1', 't2', 't3', 't4', 't5', 'n1', 'n2', 'n3', 'p_kind', 's_kind', 'change_log')


@pytest.fixture
def w(client):
    return World(client)


def edit_attr(cat):
    """An attribute the user can change when editing (FW Profile attributes come from the source item)."""
    return 'title' if 'title' not in TEMPLATE['cats'][cat]['ext_attrs'] else 'rationale'


def form_errors(response):
    return getattr(response, 'context', None) and response.context['form'].errors


def parent_query(cat, parents):
    if cat not in PARENT_PARAM_CATS or not parents:
        return ''
    return '?p_parent_id=%d&s_parent_id=%d' % (parents['p_link'].id, parents['s_link'].id)


def make_full_item(w, cat, status='NEW', name='Item1'):
    """Create an item of category cat via the ORM with every configured attribute filled in."""
    parents = w.parent_items(cat)
    payload = add_payload(cat, parents, name=name)
    fields = {k: v for k, v in payload.items() if k not in ('p_link', 's_link')}
    for link, parent in parents.items():
        fields[link] = parent
    if cat in EXT_CATS:
        fields.update(domain='ExtDom', name=name, value=SVG, n1=10, n2=20, n3=77)
        if cat == 'FCP':
            fields.update(title='Ext title', desc='Ext desc')
    item = make_item(w.project, cat, fields.pop('domain', 'Dom1'), fields.pop('name'),
                     status=status, owner=w.owner, **fields)
    return item, parents


def snapshot(item):
    item = refresh(item)
    data = {attr: getattr(item, attr) for attr in DATA_ATTRS}
    data.update(p_link=item.p_link_id, s_link=item.s_link_id, val_set=item.val_set_id,
                application=item.application_id, project=item.project_id, cat=item.cat)
    return data


def test_all_template_categories_are_covered():
    assert len(ALL_CATS) == 30
    for link_cat in REQUIRED_LINKS:
        assert link_cat in ALL_CATS


@pytest.mark.parametrize('cat', ALL_CATS)
def test_add(w, cat):
    parents = w.parent_items(cat)
    query = parent_query(cat, parents)
    payload = add_payload(cat, parents)
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
        with ext_mocks(cat):
            response = w.client.post(w.add_url(cat, query), payload)
    else:
        response = w.client.post(w.add_url(cat, query), payload)
    assert response.status_code == 302, form_errors(response)
    item = SpecItem.objects.get(project=w.project, cat=cat)
    for attr, value in expected.items():
        if attr in ('p_link', 's_link'):
            assert getattr(item, attr + '_id') == value, attr
        else:
            assert getattr(item, attr) == value, attr
    for attr in ('rationale', 'remarks', 'implementation', 't1', 't2', 't3', 't4', 't5', 'desc', 'value'):
        if attr not in TEMPLATE['cats'][cat]['attrs']:
            assert getattr(item, attr) == '', attr
    assert item.status == 'NEW'
    assert item.val_set_id == w.default_val_set.id
    assert item.owner_id == w.rw_user.id
    assert item.project_id == w.project.id
    assert item.application_id == (w.application.id if w.app_id(cat) else None)
    assert item.updated_at >= before
    assert item.previous is None
    assert SpecItem.objects.filter(project=w.project, cat=cat).count() == 1
    # Redirect: to the list of the category, or to the expanded parent when parents are passed in
    scope = '/%d/%d/%d/Sel_All/0/list_spec_items' % (w.project.id, w.app_id(cat), w.default_val_set.id)
    if cat in PARENT_PARAM_CATS:
        parent = parents['s_link']
        assert response.url == '/editor/%s%s?expand_id=%d&expand_link=s_link#%s:%s' % (
            parent.cat, scope, parent.id, parent.domain, parent.name)
    else:
        assert response.url == '/editor/%s%s#%s:%s' % (cat, scope, item.domain, item.name)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_edit_new(w, cat):
    item, parents = make_full_item(w, cat)
    before = snapshot(item)
    url = w.item_url('edit_spec_item', item, query=parent_query(cat, parents))
    payload = w.form_payload(url, **{edit_attr(cat): 'Edited text'})
    response = w.client.post(url, payload)
    assert response.status_code == 302, form_errors(response)
    assert snapshot(item) == dict(before, **{edit_attr(cat): 'Edited text'})
    assert SpecItem.objects.filter(project=w.project, cat=cat).count() == 1
    item = refresh(item)
    assert item.status == 'NEW'
    assert item.owner_id == w.rw_user.id
    assert item.previous is None


@pytest.mark.parametrize('cat', ALL_CATS)
def test_edit_cnf(w, cat):
    item, parents = make_full_item(w, cat, status='CNF')
    before = snapshot(item)
    url = w.item_url('edit_spec_item', item, query=parent_query(cat, parents))
    payload = w.form_payload(url, change_log='Reason for change', **{edit_attr(cat): 'Edited text'})
    response = w.client.post(url, payload)
    assert response.status_code == 302, form_errors(response)
    edited = refresh(item)
    assert edited.id == item.id
    assert edited.status == 'MOD'
    assert getattr(edited, edit_attr(cat)) == 'Edited text'
    if 'change_log' in TEMPLATE['cats'][cat]['attrs']:
        assert edited.change_log == 'Reason for change'
    obsolete = edited.previous
    assert obsolete is not None
    assert obsolete.id != item.id
    assert obsolete.status == 'OBS'
    assert getattr(obsolete, edit_attr(cat)) == before[edit_attr(cat)]
    assert obsolete.name == before['name']
    assert obsolete.previous is None
    assert SpecItem.objects.filter(project=w.project, cat=cat).count() == 2


@pytest.mark.parametrize('cat', ALL_CATS)
def test_copy(w, cat):
    item, parents = make_full_item(w, cat)
    before = snapshot(item)
    url = w.item_url('copy_spec_item', item, query=parent_query(cat, parents))
    payload = w.form_payload(url, name='Copy1')
    response = w.client.post(url, payload)
    if cat in EXT_CATS:     # FW Profile attributes, incl. domain and name, always come from the source item
        assert response.status_code == 200
        assert 'name' in response.context['form'].errors
        assert SpecItem.objects.filter(project=w.project, cat=cat).count() == 1
        return
    assert response.status_code == 302, form_errors(response)
    assert snapshot(item) == before
    copy = SpecItem.objects.get(project=w.project, cat=cat, name='Copy1')
    assert copy.id != item.id
    assert snapshot(copy) == dict(before, name='Copy1')
    assert copy.status == 'NEW'
    assert copy.owner_id == w.rw_user.id
    assert copy.previous is None
    assert SpecItem.objects.filter(project=w.project, cat=cat).count() == 2


@pytest.mark.parametrize('cat', ALL_CATS)
def test_split(w, cat):
    item, parents = make_full_item(w, cat)
    before = snapshot(item)
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='Alternative')
    url = w.item_url('split_spec_item', item, query=parent_query(cat, parents))
    payload = w.form_payload(url, val_set=alt.id)
    response = w.client.post(url, payload)
    assert response.status_code == 302, form_errors(response)
    assert snapshot(item) == before
    alias = SpecItem.objects.get(project=w.project, cat=cat, val_set=alt)
    assert alias.p_link_id == item.id                  # the split item points to its original
    assert (alias.domain, alias.name) == (item.domain, item.name)
    assert alias.status == 'NEW'
    assert alias.owner_id == w.rw_user.id
    assert snapshot(alias) == dict(before, val_set=alt.id, p_link=item.id)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_del_new(w, cat):
    item, parents = make_full_item(w, cat)
    url = w.item_url('del_spec_item', item, query=parent_query(cat, parents))
    assert w.client.get(url).status_code == 200    # GET only shows the form
    assert SpecItem.objects.filter(id=item.id).exists()
    response = w.client.post(url)
    assert response.status_code == 302
    assert not SpecItem.objects.filter(id=item.id).exists()    # NEW items are removed physically
    assert SpecItem.objects.filter(project=w.project, cat=cat).count() == 0


@pytest.mark.parametrize('cat', ALL_CATS)
def test_del_cnf(w, cat):
    item, parents = make_full_item(w, cat, status='CNF')
    before = snapshot(item)
    url = w.item_url('del_spec_item', item, query=parent_query(cat, parents))
    assert w.client.get(url).status_code == 200          # CNF items need a change log first
    payload = w.form_payload(url, change_log='Obsolete requirement')
    response = w.client.post(url, payload)
    assert response.status_code == 302, form_errors(response)
    deleted = refresh(item)
    assert deleted.status == 'DEL'
    assert deleted.change_log == 'Obsolete requirement'
    assert deleted.owner_id == w.rw_user.id
    assert snapshot(deleted) == dict(before, change_log='Obsolete requirement')
