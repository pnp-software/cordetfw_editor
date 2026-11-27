from datetime import timedelta

import pytest
from django.utils import timezone

from editor.forms import identifier_error
from editor.models import Application, Project, Release, SpecItem, ValSet
from tests.project_config.base import (ALL_CATS, TEMPLATE, World, add_payload, make_application, make_item,
                                       make_project, make_user, now, refresh)

pytestmark = pytest.mark.django_db

AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
PAGINATION_KEYS = ('page_number', 'has_previous', 'previous_page', 'has_next', 'next_page')


@pytest.fixture
def w(client):
    return World(client)


@pytest.fixture
def replaceable(w):
    """Services D:a (CNF, changed a day ago), E:b and D:c; two of them have 'foo' in the title."""
    w.a = make_item(w.project, 'Service', 'D', 'a', title='foo one foo', status='CNF',
                    updated_at=now() - timedelta(days=1))
    w.b = make_item(w.project, 'Service', 'E', 'b', title='no match')
    w.c = make_item(w.project, 'Service', 'D', 'c', title='foo three')
    return w


@pytest.fixture
def releasable(w):
    """Project and application items of every status, and a second application App2."""
    w.proj_new = make_item(w.project, 'Service', 'S', 'new')
    w.proj_mod = make_item(w.project, 'Service', 'S', 'mod', status='MOD')
    w.proj_del = make_item(w.project, 'Service', 'S', 'del', status='DEL')
    w.proj_obs = make_item(w.project, 'Service', 'S', 'obs', status='OBS')
    w.app_new = make_item(w.project, 'Requirement', 'R', 'new', application=w.application)
    w.app2 = make_application(w.project, 'App2')
    w.app2_new = make_item(w.project, 'Requirement', 'R', 'new2', application=w.app2)
    return w


def content(response):
    assert response.status_code == 200
    return response.content.decode()


# ------------------------------------------------------------------ lists

@pytest.mark.parametrize('disp', ['disp_def', 'disp_short', 'disp_trac'])
@pytest.mark.parametrize('cat', ALL_CATS)
def test_every_category_lists_with_every_display_mode(w, cat, disp):
    cfg = TEMPLATE['cats'][cat]
    item = make_item(w.project, cat, 'Dom1', 'Item1', title='Title ' + cat)
    response = w.client.get(w.list_url(cat) + '?disp=' + disp)
    assert response.status_code == 200
    assert response.context['config'] == cfg
    assert response.context['disp_list'] == cfg[disp]
    assert response.context['n_pad_fields'] == range(len(cfg[disp]) - 3)
    assert response.context['find_replace_fields'] == cfg['attrs']
    assert response.context['page_items'].paginator.per_page == cfg['page_size']
    assert [i.id for i in response.context['page_items']] == [item.id]
    html = response.content.decode()
    for column in cfg[disp]:
        assert column['header'] in html
    assert 'id="Dom1:Item1"' in html
    assert 'Add ' + cfg['name'] in html


def test_list_excludes_deleted_obsolete_other_val_set_other_cat_and_other_project(w):
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    other, _ = make_project('Other', owner=w.owner)
    shown = [make_item(w.project, 'Service', 'B', 'b'), make_item(w.project, 'Service', 'A', 'z'),
             make_item(w.project, 'Service', 'A', 'a', status='CNF'),
             make_item(w.project, 'Service', 'A', 'm', status='MOD')]
    make_item(w.project, 'Service', 'A', 'del', status='DEL')
    make_item(w.project, 'Service', 'A', 'obs', status='OBS')
    make_item(w.project, 'Service', 'A', 'alias', val_set=alt)
    make_item(w.project, 'Packet', 'A', 'pkt')
    make_item(other, 'Service', 'A', 'foreign')
    response = w.client.get(w.list_url('Service'))
    assert [(i.domain, i.name) for i in response.context['page_items']] == [('A', 'a'), ('A', 'm'), ('A', 'z'),
                                                                           ('B', 'b')]
    assert response.context['domains'] == ['Sel_All', 'A', 'B']
    assert len(shown) == 4
    alias_list = w.client.get(w.list_url('Service', val_set=alt))
    assert [i.name for i in alias_list.context['page_items']] == ['alias']


def test_domain_filter_and_ordering(w):
    for domain, name, title in (('A', 'x', 'c'), ('A', 'y', 'a'), ('B', 'z', 'b')):
        make_item(w.project, 'Service', domain, name, title=title)
    by_domain = w.client.get(w.list_url('Service', sel_val='B'))
    assert [i.name for i in by_domain.context['page_items']] == ['z']
    by_title = w.client.get(w.list_url('Service') + '?order_by=title')
    assert [i.name for i in by_title.context['page_items']] == ['y', 'z', 'x']
    assert by_title.context['order_by'] == 'title'
    assert 'order_by=title&' in by_title.context['get_parameter_sting']


def test_order_by_link_and_owner(w):
    svc_b = make_item(w.project, 'Service', 'S', 'b')
    svc_a = make_item(w.project, 'Service', 'S', 'a')
    make_item(w.project, 'Packet', 'P', 'p1', p_link=svc_b, owner=w.rw_user)
    make_item(w.project, 'Packet', 'P', 'p2', p_link=svc_a, owner=w.owner)
    by_link = w.client.get(w.list_url('Packet') + '?order_by=p_link')
    assert [i.name for i in by_link.context['page_items']] == ['p2', 'p1']
    by_owner = w.client.get(w.list_url('Packet') + '?order_by=owner')
    assert [i.name for i in by_owner.context['page_items']] == ['p2', 'p1']


def test_pagination(w):
    SpecItem.objects.bulk_create([
        SpecItem(cat='Service', domain='D', name='s%03d' % i, project=w.project, val_set=w.default_val_set,
                 owner=w.owner, status='NEW', updated_at=now(), created_at=now())
        for i in range(101)])
    assert TEMPLATE['cats']['Service']['page_size'] == 100
    first = w.client.get(w.list_url('Service'))
    assert len(first.context['page_items']) == 100
    assert {k: first.context['pagination'][k] for k in PAGINATION_KEYS} == {
        'page_number': 1, 'has_previous': False, 'previous_page': None, 'has_next': True, 'next_page': 2}
    second = w.client.get(w.list_url('Service') + '?page=2')
    assert [i.name for i in second.context['page_items']] == ['s100']
    assert {k: second.context['pagination'][k] for k in PAGINATION_KEYS} == {
        'page_number': 2, 'has_previous': True, 'previous_page': 1, 'has_next': False, 'next_page': None}
    assert 'page=1' in content(second)


def test_expand_lists_the_children_of_the_expanded_item(w):
    packet = make_item(w.project, 'Packet', 'P', 'pkt', title='Pkt')
    der = make_item(w.project, 'DerPacket', 'P', 'der', s_link=packet)
    par = make_item(w.project, 'PacketPar', 'P', 'par', p_link=packet)
    make_item(w.project, 'DerPacket', 'P', 'gone', s_link=packet, status='DEL')
    make_item(w.project, 'PacketPar', 'P', 'other', p_link=make_item(w.project, 'Packet', 'P', 'p2'))
    s_resp = w.client.get(w.list_url('Packet') + '?expand_id=%d&expand_link=s_link' % packet.id)
    assert [i.id for i in s_resp.context['expand_items']] == [der.id]
    assert s_resp.context['expand_id'] == packet.id
    assert 'Add Derived Packet Child' in content(s_resp)
    p_resp = w.client.get(w.list_url('Packet') + '?expand_id=%d&expand_link=p_link' % packet.id)
    assert [i.id for i in p_resp.context['expand_items']] == [par.id]
    assert 'Add Parameter Child' in content(p_resp)
    none_resp = w.client.get(w.list_url('Service') + '?expand_id=1&expand_link=s_link')
    assert none_resp.context['expand_items'] is None


def test_breadcrumb_lists_categories_by_access_level(w):
    project, vs = make_project('Small', owner=w.owner, cats=['Service', 'DataItem', 'Requirement'],
                               rw_users=[w.rw_user])
    app = make_application(project, 'AppA', cats=['Requirement'])
    make_application(project, 'Empty', cats=[])
    response = w.client.get(w.list_url('Service', project=project, val_set=vs, application_id=0))
    crumb = response.context['breadcrumb']
    assert [d['list_as'] for d in crumb['active']] == ['Data Item']
    assert [d['list_as'] for d in crumb['rest']] == ['Small / AppA / Requirement']
    assert crumb['rest'][0]['application_id'] == app.id
    app_resp = w.client.get(w.list_url('Requirement', project=project, val_set=vs, application_id=app.id))
    crumb = app_resp.context['breadcrumb']
    assert crumb['application_name_active'] == 'AppA'
    assert [d['list_as'] for d in crumb['active']] == []
    assert sorted(d['list_as'] for d in crumb['rest']) == ['Small / Data Item', 'Small / Service']


# ------------------------------------------------------------------ index

def test_index_offers_the_categories_of_the_project_by_access_level(w):
    project, vs = make_project('Small', owner=w.owner, cats=['Service', 'Requirement', 'EnumValue', 'DataItem'])
    app = make_application(project, 'AppA', cats=['Requirement'])
    w.login(w.owner)
    response = w.client.get('/editor/')
    entry = [e for e in response.context['list_of_projects'] if e['project'].id == project.id][0]
    assert list(entry['project_configs']) == [c for c in ALL_CATS
                                              if c in ('Service', 'Requirement', 'EnumValue', 'DataItem')]
    assert entry['default_val_set_id'] == vs.id
    assert entry['applications'] == [app]
    prefix = '/editor/%s/' + str(project.id) + '/%d/' + str(vs.id) + '/Sel_All/0/list_spec_items?disp=disp_def'
    html = content(response)
    assert prefix % ('Service', 0) in html
    assert prefix % ('DataItem', 0) in html
    assert prefix % ('Requirement', app.id) in html
    assert prefix % ('Requirement', 0) not in html
    assert prefix % ('EnumValue', 0) not in html      # access_from_index level 'None'


def test_index_hides_manage_menu_from_users_without_access(w):
    project, _ = make_project('Secret', owner=make_user('boss'), cats=['Service'])
    w.login(w.rw_user)
    response = w.client.get('/editor/')
    assert '/editor/Service/%d/0/' % project.id not in content(response)


# ------------------------------------------------------------------ display of references

def test_references_are_stored_as_item_ids_and_displayed_as_links(w):
    target = make_item(w.project, 'Service', 'S', 'svc', title='Svc title', value='Svc value')
    payload = add_payload('Packet', {'p_link': target}, desc='see #Service:S:svc and #Service:S:nope')
    assert w.client.post(w.add_url('Packet'), payload).status_code == 302
    packet = SpecItem.objects.get(cat='Packet')
    assert packet.desc == 'see #iref:%d and #Service:S:nope' % target.id
    edit = w.client.get(w.item_url('edit_spec_item', packet)).context['form']
    assert edit['desc'].value() == 'see #Service:S:svc and #Service:S:nope'
    html = w.client.get(w.list_url('Packet')).content.decode()
    assert '>S:svc</a>' in html
    assert 'class="link-danger"' in html                        # NEW target is shown in red
    assert 'Title: Svc title&#13;' in html                      # tooltip built from short_desc.href_tip
    assert 'Type: Svc value&#13;' in html


def test_dangling_references_and_markdown(w):
    item = make_item(w.project, 'Service', 'S', 'svc', desc='**bold** and #iref:99999', title='t')
    html = w.client.get(w.list_url('Service')).content.decode()
    assert '<b>bold</b> and ERROR:99999' in html
    assert refresh(item).desc == '**bold** and #iref:99999'


def test_eval_ref_values_are_evaluated_for_display(w):
    a = make_item(w.project, 'DataItem', 'D', 'a', value='2')
    make_item(w.project, 'DataItem', 'D', 'b', value='#iref:%d * 3' % a.id)
    html = w.client.get(w.list_url('DataItem')).content.decode()
    assert 'D:a</a> * 3 = 6.0' in html


def test_link_columns_and_traceability_columns(w):
    requirement = make_item(w.project, 'Requirement', 'R', 'req', value='r')
    ver_item = make_item(w.project, 'VerItem', 'V', 'ver', title='Verifier')
    make_item(w.project, 'VerLink', 'L', 'link', p_link=ver_item, s_link=requirement, title='l')
    html = w.client.get(w.list_url('Requirement') + '?disp=disp_trac').content.decode()
    assert 'Verification Links' in html
    assert '>V:ver</a> (Verifier)' in html
    verlinks = w.client.get(w.list_url('VerLink')).content.decode()
    assert '>V:ver</a>' in verlinks
    assert '>R:req</a>' in verlinks


# ------------------------------------------------------------------ find and replace

def replace(w, field='title', find='foo', replace='bar', url=None, ajax=True):
    extra = AJAX if ajax else {}
    return w.client.post(url or w.list_url('Service'), {'field': field, 'find': find, 'replace': replace}, **extra)


def test_replaces_in_all_matching_items_of_the_list(replaceable):
    before = replaceable.a.updated_at
    response = replace(replaceable)
    assert response.json() == {'updated_count': 2}
    assert refresh(replaceable.a).title == 'bar one bar'
    assert refresh(replaceable.c).title == 'bar three'
    assert refresh(replaceable.b).title == 'no match'
    a = refresh(replaceable.a)
    assert a.status == 'CNF'                          # no obsolete copy is made
    assert SpecItem.objects.filter(cat='Service').count() == 3
    assert a.updated_at > before
    assert a.owner_id == replaceable.rw_user.id


def test_replacement_is_limited_to_the_selected_domain_and_list(replaceable):
    response = replace(replaceable, url=replaceable.list_url('Service', sel_val='E'))
    assert response.json() == {'updated_count': 0}
    assert refresh(replaceable.a).title == 'foo one foo'
    other, _ = make_project('Other', owner=replaceable.owner)
    foreign = make_item(other, 'Service', 'D', 'f', title='foo')
    alias = make_item(replaceable.project, 'Service', 'D', 'a',
                      val_set=ValSet.objects.create(project=replaceable.project, name='Alt', desc=''),
                      title='foo alias')
    make_item(replaceable.project, 'Service', 'D', 'gone', status='DEL', title='foo del')
    assert replace(replaceable).json() == {'updated_count': 2}
    assert refresh(foreign).title == 'foo'
    assert refresh(alias).title == 'foo alias'
    assert SpecItem.objects.get(name='gone').title == 'foo del'


def test_non_ajax_post_also_applies_and_renders_the_list(replaceable):
    response = replace(replaceable, ajax=False)
    assert response.status_code == 200
    assert refresh(replaceable.c).title == 'bar three'
    assert 'page_items' in response.context


@pytest.mark.parametrize('kwargs,key,message', [
    (dict(find='x', replace='x'), '__all__', 'Error: Find and replace values must be different'),
    (dict(field='bogus'), 'field', 'Select a valid field'),
    (dict(field='name', find='a', replace='b c'), '__all__', identifier_error),
    (dict(field='title', find='foo', replace='y' * 256), 'replace',
     'Ensure this value has at most 255 characters (it has 256).'),
    (dict(field='title', find='foo', replace='y' * 200), '__all__', None),     # resulting title exceeds the model limit
])
def test_errors_are_reported_and_nothing_is_changed(replaceable, kwargs, key, message):
    response = replace(replaceable, **kwargs)
    assert response.status_code == 400
    errors = response.json()['errors']
    assert key in errors
    if message:
        assert errors[key][0]['message'] == message
    assert refresh(replaceable.a).title == 'foo one foo'


def test_renaming_to_an_existing_identifier_is_rejected_atomically(replaceable):
    make_item(replaceable.project, 'Service', 'D', 'a2')
    x = make_item(replaceable.project, 'Service', 'D', 'a1')
    response = replace(replaceable, field='name', find='a1', replace='a2')
    assert response.status_code == 400
    assert response.json()['errors']['__all__'][0]['message'] == "Error: Name 'a2' already exists in domain 'D'"
    assert refresh(x).name == 'a1'
    assert replace(replaceable, field='name', find='a1', replace='a9').json() == {'updated_count': 1}
    assert refresh(x).name == 'a9'


def test_link_fields_are_not_searched(replaceable):
    svc = make_item(replaceable.project, 'Service', 'S', 'svc')
    make_item(replaceable.project, 'Packet', 'P', 'p', p_link=svc, title='foo')
    response = replace(replaceable, field='p_link', url=replaceable.list_url('Packet'))
    assert response.json() == {'updated_count': 0}


# ------------------------------------------------------------------ history

@pytest.mark.parametrize('cat', ALL_CATS)
def test_history_page_for_every_category(w, cat):
    item = make_item(w.project, cat, 'Dom1', 'Item_' + cat, status='CNF', title='t')
    response = w.client.get(w.url('list_spec_item_history', cat, w.project.id, w.app_id(cat), item.id, 'Sel_All'))
    assert response.status_code == 200
    assert response.context['history']
    assert response.context['disp_list'] == TEMPLATE['cats'][cat]['disp_def']
    assert [i.id for i in response.context['page_items']] == [item.id]
    assert 'Change Log' in response.content.decode()


def test_history_lists_all_versions_newest_first(w):
    service = make_item(w.project, 'Service', 'S', 's')
    packet = make_item(w.project, 'Packet', 'P', 'pkt', p_link=service, p_kind='TC', status='CNF',
                       title='v1', value='v', t1='a', t2='b')
    url = w.item_url('edit_spec_item', packet)
    assert w.client.post(url, w.form_payload(url, title='v2', change_log='second')).status_code == 302
    w.login(w.owner)
    assert w.client.post(w.url('make_project_release', w.project.id), {'description': 'R1'}).status_code == 302
    w.login(w.rw_user)
    url = w.item_url('edit_spec_item', packet)
    assert w.client.post(url, w.form_payload(url, title='v3', change_log='third')).status_code == 302
    response = w.client.get(w.url('list_spec_item_history', 'Packet', w.project.id, 0, packet.id, 'Sel_All'))
    items = response.context['page_items']
    assert [(i.title, i.status) for i in items] == [('v3', 'MOD'), ('v2', 'OBS'), ('v1', 'OBS')]
    assert items[0].change_log == 'third'
    assert items[1].change_log == 'second'
    assert items[2].change_log == ''
    html = content(response)
    assert 'MOD (' in html
    assert 'third' in html
    assert 'History of %s:%s' % (packet.domain, packet.name) in html


# ------------------------------------------------------------------ releases

def statuses(w):
    items = {'proj_new': w.proj_new, 'proj_mod': w.proj_mod, 'proj_del': w.proj_del,
             'proj_obs': w.proj_obs, 'app_new': w.app_new, 'app2_new': w.app2_new}
    return {key: refresh(item).status for key, item in items.items()}


def test_project_release_confirms_new_and_modified_items_and_creates_releases(releasable):
    w = releasable
    w.login(w.owner)
    old_release = w.project.release
    old_app_releases = {w.application.id: w.application.release_id, w.app2.id: w.app2.release_id}
    before = Release.objects.count()
    response = w.client.post(w.url('make_project_release', w.project.id), {'description': 'Release one'})
    assert response.status_code == 302
    assert response.url == '/editor'
    assert statuses(w) == {'proj_new': 'CNF', 'proj_mod': 'CNF', 'proj_del': 'DEL', 'proj_obs': 'OBS',
                           'app_new': 'CNF', 'app2_new': 'CNF'}
    project = Project.objects.get(id=w.project.id)
    assert (project.release.project_version, project.release.application_version) == (1, 0)
    assert project.release.previous == old_release
    assert (project.release.desc, project.release.release_author_id) == ('Release one', w.owner.id)
    for app in (w.application, w.app2):
        app = Application.objects.get(id=app.id)
        assert (app.release.project_version, app.release.application_version) == (1, 0)
        assert app.release.desc == 'Release one'
        assert app.release.previous_id == old_app_releases[app.id]
    assert Release.objects.count() == before + 3


def test_blank_release_description_creates_no_release(releasable):
    releasable.login(releasable.owner)
    before = Release.objects.count()
    response = releasable.client.post(releasable.url('make_project_release', releasable.project.id),
                                      {'description': '   '})
    assert response.status_code == 200
    assert Release.objects.count() == before
    assert refresh(releasable.proj_new).status == 'NEW'


def test_only_the_owner_can_make_releases(releasable):
    w = releasable
    before = Release.objects.count()
    for name, arg in (('make_project_release', w.project.id), ('make_application_release', w.application.id)):
        response = w.client.post(w.url(name, arg), {'description': 'x'})
        assert (response.status_code, response.url) == (302, '/editor')
    assert Release.objects.count() == before
    assert refresh(w.proj_new).status == 'NEW'


def test_application_release_only_affects_that_application(releasable):
    w = releasable
    w.login(w.owner)
    old_project_release = w.project.release_id
    response = w.client.post(w.url('make_application_release', w.application.id), {'description': 'App rel'})
    assert response.status_code == 302
    assert statuses(w) == {'proj_new': 'NEW', 'proj_mod': 'MOD', 'proj_del': 'DEL', 'proj_obs': 'OBS',
                           'app_new': 'CNF', 'app2_new': 'NEW'}
    application = Application.objects.get(id=w.application.id)
    assert application.release.application_version == 1
    assert application.release.desc == 'App rel'
    assert Project.objects.get(id=w.project.id).release_id == old_project_release


def test_listing_a_release_shows_the_items_as_they_were(releasable):
    w = releasable
    t0 = timezone.now() - timedelta(days=10)
    t1 = timezone.now() - timedelta(days=5)
    t2 = timezone.now() - timedelta(days=1)
    release = Release.objects.create(release_author=w.owner, desc='old', updated_at=t1, project_version=1,
                                     application_version=0, previous=w.project.release)
    w.project.release = release
    w.project.save()
    kept = make_item(w.project, 'Service', 'R', 'kept', status='CNF', created_at=t0, updated_at=t0)
    make_item(w.project, 'Service', 'R', 'created_later', status='CNF', created_at=t2, updated_at=t2)
    make_item(w.project, 'Service', 'R', 'changed_later', status='CNF', created_at=t0, updated_at=t2)
    make_item(w.project, 'Service', 'R', 'deleted_before', status='DEL', created_at=t0, updated_at=t0)
    deleted_after = make_item(w.project, 'Service', 'R', 'deleted_after', status='DEL', created_at=t0, updated_at=t2)
    make_item(w.project, 'Service', 'R', 'work_in_progress', status='NEW', created_at=t0, updated_at=t0)
    response = w.client.get(w.list_url('Service', sel_rel_id=release.id))
    assert sorted(i.name for i in response.context['page_items']) == sorted([kept.name, deleted_after.name])
    assert response.context['sel_rel'] == release
    assert [r.id for r in response.context['releases']] == [release.id, release.previous_id]
    assert 'Release: 1.0' in content(response)
