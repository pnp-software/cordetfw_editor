"""Characterization tests for query/chain helpers in editor.utilities."""
from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth import login
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from editor.models import SpecItem
from editor.utilities import (get_domains, get_expand_items, get_previous_list,
                              get_spec_item_query, make_obs_spec_item_copy,
                              mark_spec_item_aliases_as_del, remove_spec_item_aliases,
                              update_dom_name_in_val_set)
from tests.backend import is_mysql
from tests.factories import (default_val_set, make_application, make_project, make_release,
                             make_spec_item, make_user, make_val_set)

pytestmark = pytest.mark.django_db


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


R_TIME = utc(2024, 3, 1, 12, 0, 0)       # time of the selected release
JAN = utc(2024, 1, 10, 9, 0)
FEB = utc(2024, 2, 10, 9, 0)
MAR_LATE = utc(2024, 3, 20, 9, 0)
APR = utc(2024, 4, 10, 9, 0)


def make_request(user):
    request = RequestFactory().get('/')
    request.session = SessionStore()
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request._messages = FallbackStorage(request)
    return request


def names(query):
    return [i.name for i in query]


# ------------------------------------------------------------------ latest version

@pytest.fixture
def timeline():
    owner = make_user('owner')
    project = make_project(owner)
    release = make_release(owner, project_version=1, updated_at=R_TIME)
    vs = default_val_set(project)

    def mk(name, status, created, updated, previous=None, **kw):
        return make_spec_item(project, name=name, status=status, created_at=created,
                              updated_at=updated, previous=previous, **kw)

    items = {}
    items['new_before'] = mk('new_before', 'NEW', FEB, FEB)
    items['mod_before'] = mk('mod_before', 'MOD', FEB, FEB)
    items['cnf_ok'] = mk('cnf_ok', 'CNF', JAN, FEB)
    items['cnf_created_after'] = mk('cnf_created_after', 'CNF', APR, APR)
    items['cnf_updated_after'] = mk('cnf_updated_after', 'CNF', FEB, APR)
    items['cnf_at_R'] = mk('cnf_at_R', 'CNF', R_TIME, R_TIME)
    items['del_before'] = mk('del_before', 'DEL', JAN, FEB)
    items['del_after'] = mk('del_after', 'DEL', JAN, APR)
    items['del_at_R'] = mk('del_at_R', 'DEL', JAN, R_TIME)
    # DEL item whose predecessor was obsoleted after the release
    items['obs_late'] = mk('del_chain_late', 'OBS', JAN, MAR_LATE)
    items['del_chain_late'] = mk('del_chain_late', 'DEL', JAN, APR, previous=items['obs_late'])
    # DEL item whose predecessor was obsoleted before the release
    items['obs_early'] = mk('del_chain_early', 'OBS', JAN, FEB)
    items['del_chain_early'] = mk('del_chain_early', 'DEL', JAN, APR, previous=items['obs_early'])
    items['obs_before'] = mk('obs_before', 'OBS', JAN, FEB)
    items['obs_after'] = mk('obs_after', 'OBS', JAN, APR)
    items['obs_at_R'] = mk('obs_at_R', 'OBS', JAN, R_TIME)
    # OBS whose previous version was obsoleted after the release: the older one wins
    items['obs_older'] = mk('obs_chain', 'OBS', JAN, MAR_LATE)
    items['obs_newer'] = mk('obs_chain', 'OBS', JAN, APR, previous=items['obs_older'])
    # OBS created after the release is excluded by created_at
    items['obs_created_after'] = mk('obs_created_after', 'OBS', APR, utc(2024, 5, 1))
    # items that never qualify, whatever the release
    other_vs = make_val_set(project, 'VS1')
    items['other_vs'] = mk('other_vs', 'CNF', JAN, FEB, val_set=other_vs)
    items['other_cat'] = mk('other_cat', 'CNF', JAN, FEB, cat='EnumType')
    other_project = make_project(make_user('o2'), name='P2')
    items['other_project'] = make_spec_item(other_project, name='other_project', status='CNF',
                                            created_at=JAN, updated_at=FEB)
    return project, vs, release, items


def q(project, vs, release=None, cat='DataItem', app_id=0, sel_val='Sel_All', order_by=None):
    return get_spec_item_query(project.id, app_id, vs.id, cat, release, sel_val, order_by)


def test_query_latest_excludes_del_and_obs(timeline):
    project, vs, _, _ = timeline
    assert sorted(names(q(project, vs))) == sorted([
        'new_before', 'mod_before', 'cnf_ok', 'cnf_created_after', 'cnf_updated_after', 'cnf_at_R'])


def test_query_latest_ignores_dates(timeline):
    project, vs, _, items = timeline
    result = set(q(project, vs).values_list('pk', flat=True))
    assert items['cnf_created_after'].pk in result
    assert items['cnf_updated_after'].pk in result


def test_query_at_release_visibility_rules(timeline):
    project, vs, release, items = timeline
    result = {i.pk for i in q(project, vs, release)}
    expected_in = ['cnf_ok', 'cnf_at_R',            # CNF: created<=R and updated<=R (boundary included)
                   'del_after', 'del_at_R',          # DEL: updated >= R and no/late previous
                   'del_chain_early',                # DEL whose previous.updated_at <= R
                   'obs_late',                       # OBS: updated >= R
                   'obs_after', 'obs_at_R',
                   'obs_older']                      # OBS chain: older version obsoleted after R
    expected_out = ['new_before', 'mod_before',      # NEW/MOD never in a release
                    'cnf_created_after',             # created after R
                    'cnf_updated_after',             # CNF updated after R
                    'del_before',                    # deleted before R
                    'del_chain_late',                # DEL, previous.updated_at > R
                    'obs_early', 'obs_before',       # OBS obsoleted before R
                    'obs_newer',                     # OBS whose previous.updated_at > R
                    'obs_created_after',             # created after R
                    'other_vs', 'other_cat', 'other_project']
    assert {items[k].pk for k in expected_in} == result
    assert not (result & {items[k].pk for k in expected_out})
    assert len(expected_in) + len(expected_out) == len(items)


def test_query_at_release_boundary_just_before_and_after(timeline):
    """Release time shifted by one microsecond flips the boundary items."""
    project, vs, release, items = timeline
    release.updated_at = R_TIME - timedelta(microseconds=1)
    release.save()
    result = {i.pk for i in q(project, vs, release)}
    assert items['cnf_at_R'].pk not in result       # created_at > R now
    assert items['del_at_R'].pk in result
    assert items['obs_at_R'].pk in result
    release.updated_at = R_TIME + timedelta(microseconds=1)
    release.save()
    result = {i.pk for i in q(project, vs, release)}
    assert items['cnf_at_R'].pk in result
    assert items['del_at_R'].pk not in result       # DEL updated < R
    assert items['obs_at_R'].pk not in result       # OBS updated < R


def test_query_at_release_before_everything_is_empty(timeline):
    project, vs, release, _ = timeline
    release.updated_at = utc(2023, 1, 1)
    release.save()
    assert list(q(project, vs, release)) == []


def test_query_filters_by_val_set(timeline):
    project, vs, release, items = timeline
    other_vs = items['other_vs'].val_set
    assert names(q(project, other_vs)) == ['other_vs']
    assert names(q(project, other_vs, release)) == ['other_vs']


def test_query_filters_by_cat(timeline):
    project, vs, _, _ = timeline
    assert names(q(project, vs, cat='EnumType')) == ['other_cat']
    assert list(q(project, vs, cat='EnumValue')) == []


def test_query_filters_by_project(timeline):
    project, vs, _, items = timeline
    assert items['other_project'].pk not in {i.pk for i in q(project, vs)}


def test_query_sel_val_filters_domain():
    project = make_project(make_user())
    make_spec_item(project, domain='A', name='a1')
    make_spec_item(project, domain='B', name='b1')
    make_spec_item(project, domain='B', name='b2')
    vs = default_val_set(project)
    assert names(q(project, vs, sel_val='B')) == ['b1', 'b2']
    assert names(q(project, vs, sel_val='A')) == ['a1']
    assert names(q(project, vs, sel_val='Nope')) == []
    assert names(q(project, vs, sel_val='Sel_All')) == ['a1', 'b1', 'b2']
    # Backend dependent: case-sensitive on SQLite, case-insensitive on MySQL (production).
    assert names(q(project, vs, sel_val='b')) == (['b1', 'b2'] if is_mysql() else [])


def test_query_sel_val_also_applies_at_release():
    owner = make_user()
    project = make_project(owner)
    release = make_release(owner, updated_at=R_TIME)
    make_spec_item(project, domain='A', name='a1', status='CNF', created_at=JAN, updated_at=FEB)
    make_spec_item(project, domain='B', name='b1', status='CNF', created_at=JAN, updated_at=FEB)
    assert names(q(project, default_val_set(project), release, sel_val='B')) == ['b1']


def test_query_application_level_category_filters_by_application():
    project = make_project(make_user())
    app1 = make_application(project, name='A1', cats='Model')
    app2 = make_application(project, name='A2', cats='Model')
    make_spec_item(project, cat='Model', name='m1', application=app1)
    make_spec_item(project, cat='Model', name='m2', application=app2)
    make_spec_item(project, cat='Model', name='m_noapp')
    vs = default_val_set(project)
    assert names(q(project, vs, cat='Model', app_id=app1.id)) == ['m1']
    assert names(q(project, vs, cat='Model', app_id=app2.id)) == ['m2']
    # application_id 0 -> filter by project: all items of the category
    # Backend dependent: SQLite (binary) sorts digits before '_', MySQL's collation sorts '_' first.
    assert names(q(project, vs, cat='Model', app_id=0)) == \
        (['m_noapp', 'm1', 'm2'] if is_mysql() else ['m1', 'm2', 'm_noapp'])


def test_query_project_level_category_ignores_application_id():
    project = make_project(make_user())
    app = make_application(project, name='A1', cats='Model')
    make_spec_item(project, cat='DataItem', name='d1')
    vs = default_val_set(project)
    assert names(q(project, vs, cat='DataItem', app_id=app.id)) == ['d1']


def test_query_application_level_at_release():
    owner = make_user()
    project = make_project(owner)
    app1 = make_application(project, name='A1', cats='Model')
    app2 = make_application(project, name='A2', cats='Model')
    release = make_release(owner, updated_at=R_TIME)
    make_spec_item(project, cat='Model', name='m1', application=app1, status='CNF', created_at=JAN, updated_at=FEB)
    make_spec_item(project, cat='Model', name='m2', application=app2, status='CNF', created_at=JAN, updated_at=FEB)
    assert names(q(project, default_val_set(project), release, cat='Model', app_id=app1.id)) == ['m1']


# ------------------------------------------------------------------ ordering

def test_query_default_ordering_domain_then_name():
    project = make_project(make_user())
    for dom, name in [('b', 'x'), ('a', 'z'), ('a', 'y'), ('B', 'a'), ('b', 'a')]:
        make_spec_item(project, domain=dom, name=name)
    result = [(i.domain, i.name) for i in q(project, default_val_set(project))]
    # Backend dependent: SQLite's binary collation sorts upper case first; MySQL's
    # case-insensitive collation interleaves 'B' and 'b'. On MySQL ('B','a') and ('b','a')
    # have EQUAL sort keys, so their relative order is undefined and compared as a set.
    if is_mysql():
        assert result[:2] == [('a', 'y'), ('a', 'z')]
        assert set(result[2:4]) == {('B', 'a'), ('b', 'a')}
        assert result[4:] == [('b', 'x')]
    else:
        assert result == [('B', 'a'), ('a', 'y'), ('a', 'z'), ('b', 'a'), ('b', 'x')]


def test_query_default_ordering_distinct_keys_is_deterministic():
    project = make_project(make_user())
    for dom, name in [('b', 'x'), ('a', 'z'), ('a', 'y'), ('c', 'a')]:
        make_spec_item(project, domain=dom, name=name)
    result = [(i.domain, i.name) for i in q(project, default_val_set(project))]
    assert result == [('a', 'y'), ('a', 'z'), ('b', 'x'), ('c', 'a')]


def test_query_order_by_p_link_sorts_by_target_domain_name():
    project = make_project(make_user())
    t1 = make_spec_item(project, cat='DataItemType', domain='Z', name='t1')
    t2 = make_spec_item(project, cat='DataItemType', domain='A', name='t2')
    t3 = make_spec_item(project, cat='DataItemType', domain='A', name='t1')
    make_spec_item(project, domain='D', name='i1', p_link=t1)
    make_spec_item(project, domain='D', name='i2', p_link=t2)
    make_spec_item(project, domain='D', name='i3', p_link=t3)
    vs = default_val_set(project)
    assert names(q(project, vs, order_by='p_link')) == ['i3', 'i2', 'i1']
    assert names(q(project, vs)) == ['i1', 'i2', 'i3']


def test_query_order_by_s_link_sorts_by_target_domain_name():
    project = make_project(make_user())
    t1 = make_spec_item(project, cat='EnumValue', domain='B', name='v')
    t2 = make_spec_item(project, cat='EnumValue', domain='A', name='v')
    make_spec_item(project, domain='D', name='i1', s_link=t1)
    make_spec_item(project, domain='D', name='i2', s_link=t2)
    assert names(q(project, default_val_set(project), order_by='s_link')) == ['i2', 'i1']


def test_query_order_by_owner_sorts_by_username_then_domain_name():
    owner = make_user('owner')
    project = make_project(owner)
    zed, amy, bob = make_user('zed'), make_user('amy'), make_user('bob')
    make_spec_item(project, domain='D', name='n1', owner=zed)
    make_spec_item(project, domain='D', name='n3', owner=amy)
    make_spec_item(project, domain='C', name='n4', owner=amy)
    make_spec_item(project, domain='D', name='n2', owner=bob)
    assert names(q(project, default_val_set(project), order_by='owner')) == ['n4', 'n3', 'n2', 'n1']


def test_query_order_by_other_field_then_domain_name():
    project = make_project(make_user())
    make_spec_item(project, domain='D', name='n1', title='b')
    make_spec_item(project, domain='D', name='n2', title='a')
    make_spec_item(project, domain='C', name='n3', title='b')
    vs = default_val_set(project)
    assert names(q(project, vs, order_by='title')) == ['n2', 'n3', 'n1']
    assert names(q(project, vs, order_by='-title')) == ['n3', 'n1', 'n2']
    assert names(q(project, vs, order_by='n1')) == ['n3', 'n1', 'n2']   # all zero -> domain,name


def test_query_order_by_p_link_ties_compared_as_set():
    # items sharing the same link target have equal sort keys under order_by=p_link (no
    # tie-breaker): their relative order is undefined, so only membership is asserted
    project = make_project(make_user())
    t = make_spec_item(project, cat='DataItemType', domain='T', name='t')
    for n in ('i1', 'i2', 'i3'):
        make_spec_item(project, domain='D', name=n, p_link=t)
    vs = default_val_set(project)
    assert set(names(q(project, vs, order_by='p_link'))) == {'i1', 'i2', 'i3'}
    assert len(names(q(project, vs, order_by='p_link'))) == 3


def test_query_invalid_order_by_raises_field_error():
    from django.core.exceptions import FieldError
    project = make_project(make_user())
    make_spec_item(project)
    with pytest.raises(FieldError):
        list(q(project, default_val_set(project), order_by='nonexistent'))


# ------------------------------------------------------------------ get_domains

def test_get_domains_project_level():
    project = make_project(make_user())
    make_spec_item(project, domain='B', name='1')
    make_spec_item(project, domain='A', name='2')
    make_spec_item(project, domain='A', name='3')
    make_spec_item(project, domain='', name='4')
    make_spec_item(project, domain='Gone', name='5', status='DEL')
    make_spec_item(project, domain='Old', name='6', status='OBS')
    make_spec_item(project, domain='Other', name='7', cat='EnumType')
    make_spec_item(make_project(make_user('u2'), name='P2'), domain='OtherProject', name='8')
    assert get_domains('DataItem', 0, project.id) == ['Sel_All', 'A', 'B']
    assert get_domains('EnumType', 0, project.id) == ['Sel_All', 'Other']
    assert get_domains('EnumValue', 0, project.id) == ['Sel_All']


def test_get_domains_includes_all_val_sets():
    project = make_project(make_user())
    make_spec_item(project, domain='A', name='1')
    make_spec_item(project, domain='V', name='2', val_set=make_val_set(project, 'VS1'))
    assert get_domains('DataItem', 0, project.id) == ['Sel_All', 'A', 'V']


def test_get_domains_application_level():
    project = make_project(make_user())
    app1 = make_application(project, name='A1', cats='Model')
    app2 = make_application(project, name='A2', cats='Model')
    make_spec_item(project, cat='Model', domain='X', name='1', application=app1)
    make_spec_item(project, cat='Model', domain='Y', name='2', application=app2)
    make_spec_item(project, cat='Model', domain='Z', name='3')
    assert get_domains('Model', app1.id, project.id) == ['Sel_All', 'X']
    assert get_domains('Model', app2.id, project.id) == ['Sel_All', 'Y']
    assert get_domains('Model', 0, project.id) == ['Sel_All', 'X', 'Y', 'Z']


# ------------------------------------------------------------------ get_expand_items

def test_get_expand_items_s_link():
    project = make_project(make_user())
    vs = default_val_set(project)
    parent = make_spec_item(project, cat='EnumType', name='ET')
    other_parent = make_spec_item(project, cat='EnumType', name='ET2')
    make_spec_item(project, cat='EnumValue', domain='B', name='v2', s_link=parent)
    make_spec_item(project, cat='EnumValue', domain='A', name='v1', s_link=parent)
    make_spec_item(project, cat='EnumValue', domain='A', name='gone', s_link=parent, status='DEL')
    make_spec_item(project, cat='EnumValue', domain='A', name='old', s_link=parent, status='OBS')
    make_spec_item(project, cat='EnumValue', name='elsewhere', s_link=other_parent)
    make_spec_item(project, cat='EnumValue', name='in_vs1', s_link=parent, val_set=make_val_set(project, 'VS1'))
    make_spec_item(project, cat='DataItem', name='wrongcat', s_link=parent)
    result = get_expand_items('EnumType', project.id, vs.id, parent.id, 's_link')
    assert names(result) == ['v1', 'v2']
    assert names(get_expand_items('EnumType', project.id, vs.id, str(parent.id), 's_link')) == ['v1', 'v2']


def test_get_expand_items_p_link():
    project = make_project(make_user())
    vs = default_val_set(project)
    parent = make_spec_item(project, cat='EnumType', name='ET')
    make_spec_item(project, cat='DataItem', domain='B', name='d2', p_link=parent)
    make_spec_item(project, cat='DataItem', domain='A', name='d1', p_link=parent)
    make_spec_item(project, cat='DataItem', name='dgone', p_link=parent, status='DEL')
    make_spec_item(project, cat='EnumValue', name='wrongcat', p_link=parent)
    assert names(get_expand_items('EnumType', project.id, vs.id, parent.id, 'p_link')) == ['d1', 'd2']


def test_get_expand_items_none_configured_returns_none():
    project = make_project(make_user())
    vs = default_val_set(project)
    parent = make_spec_item(project, cat='DataItem', name='D')
    assert get_expand_items('DataItem', project.id, vs.id, parent.id, 'p_link') is None
    assert get_expand_items('DataItem', project.id, vs.id, parent.id, 's_link') is None


def test_get_expand_items_unknown_link_raises_key_error():
    project = make_project(make_user())
    with pytest.raises(KeyError):
        get_expand_items('EnumType', project.id, default_val_set(project).id, 1, 'bogus')


# ------------------------------------------------------------------ get_previous_list

def test_get_previous_list_spec_item_chain():
    project = make_project(make_user())
    a = make_spec_item(project, name='n', status='OBS')
    b = make_spec_item(project, name='n', status='OBS', previous=a)
    c = make_spec_item(project, name='n', status='MOD', previous=b)
    assert get_previous_list(c) == [c, b, a]
    assert get_previous_list(a) == [a]


# ------------------------------------------------------------------ make_obs_spec_item_copy

def test_make_obs_spec_item_copy_rewires_chain_without_saving_original():
    owner, editor = make_user('owner'), make_user('editor')
    project = make_project(owner)
    older = make_spec_item(project, name='N', status='OBS', title='v1')
    original = make_spec_item(project, name='N', status='CNF', title='v2', previous=older,
                              desc='d', value='val', t1='x', n1=7, s_data={'k': [1]},
                              created_at=JAN, updated_at=FEB)
    original_id = original.pk
    before = datetime.now(timezone.utc)
    returned = make_obs_spec_item_copy(make_request(editor), original)
    after = datetime.now(timezone.utc)

    # the returned instance is the ORIGINAL row, status MOD, pointing to the new OBS copy, unsaved
    assert returned.pk == original_id
    assert returned is not original
    assert returned.status == 'MOD'
    obs_copy = returned.previous
    assert obs_copy.pk != original_id
    db_original = SpecItem.objects.get(pk=original_id)
    assert db_original.status == 'CNF'          # not yet saved by make_obs_spec_item_copy
    assert db_original.previous is None         # previous pointer was reset (and not yet re-set)

    # the argument object was turned into the OBS copy
    assert original.pk == obs_copy.pk
    assert original.status == 'OBS'

    # the OBS copy in the DB
    db_copy = SpecItem.objects.get(pk=obs_copy.pk)
    assert db_copy.status == 'OBS'
    assert db_copy.previous == older            # takes over the old previous
    assert db_copy.owner == editor
    assert before <= db_copy.updated_at <= after
    assert db_copy.created_at == JAN            # created_at preserved
    for field in ('cat', 'domain', 'name', 'project_id', 'title', 'desc', 'value', 't1', 'n1',
                  's_data', 'val_set_id', 'application_id'):
        assert getattr(db_copy, field) == getattr(db_original, field), field
    assert db_original.owner == owner           # original owner/updated_at not changed yet
    assert db_original.updated_at == FEB

    # after the caller saves the returned instance the chain is older <- obs copy <- original
    returned.save()
    db_original = SpecItem.objects.get(pk=original_id)
    assert db_original.status == 'MOD'
    assert get_previous_list(db_original) == [db_original, db_copy, older]
    assert SpecItem.objects.filter(project=project, name='N').count() == 3


def test_make_obs_spec_item_copy_without_previous():
    project = make_project(make_user())
    original = make_spec_item(project, name='N', status='CNF')
    returned = make_obs_spec_item_copy(make_request(project.owner), original)
    returned.save()
    returned.refresh_from_db()
    assert returned.status == 'MOD'
    assert returned.previous.status == 'OBS'
    assert returned.previous.previous is None


def test_make_obs_spec_item_copy_twice_builds_longer_chain():
    project = make_project(make_user())
    item = make_spec_item(project, name='N', status='CNF', title='v1')
    request = make_request(project.owner)
    item = make_obs_spec_item_copy(request, item)
    item.status = 'CNF'      # simulate a release between edits
    item.title = 'v2'
    item.save()
    item = make_obs_spec_item_copy(request, SpecItem.objects.get(pk=item.pk))
    item.title = 'v3'
    item.save()
    chain = get_previous_list(SpecItem.objects.get(pk=item.pk))
    assert [(i.status, i.title) for i in chain] == [('MOD', 'v3'), ('OBS', 'v2'), ('OBS', 'v1')]


def test_obs_copy_not_in_latest_listing():
    project = make_project(make_user())
    item = make_spec_item(project, name='N', status='CNF')
    returned = make_obs_spec_item_copy(make_request(project.owner), item)
    returned.save()
    assert names(q(project, default_val_set(project))) == ['N']
    assert SpecItem.objects.filter(name='N', status='OBS').count() == 1


# ------------------------------------------------------------------ alias helpers

@pytest.fixture
def aliases():
    owner, editor = make_user('owner'), make_user('editor')
    project = make_project(owner)
    vs1 = make_val_set(project, 'VS1')
    vs2 = make_val_set(project, 'VS2')
    parent = make_spec_item(project, domain='Dom', name='Parent')
    alias1 = make_spec_item(project, domain='Dom', name='Parent', val_set=vs1, p_link=parent)
    alias2 = make_spec_item(project, domain='Dom', name='Parent', val_set=vs2, p_link=parent)
    in_default = make_spec_item(project, domain='Dom', name='ChildInDefault', p_link=parent)
    unrelated = make_spec_item(project, domain='Dom', name='Unrelated', val_set=vs1)
    return dict(owner=owner, editor=editor, project=project, parent=parent, alias1=alias1,
                alias2=alias2, in_default=in_default, unrelated=unrelated)


def test_remove_spec_item_aliases_deletes_only_non_default_children(aliases):
    request = make_request(aliases['editor'])
    remove_spec_item_aliases(request, aliases['parent'])
    remaining = set(SpecItem.objects.values_list('pk', flat=True))
    assert aliases['alias1'].pk not in remaining
    assert aliases['alias2'].pk not in remaining
    assert aliases['in_default'].pk in remaining
    assert aliases['unrelated'].pk in remaining
    assert aliases['parent'].pk in remaining
    assert list(get_messages(request)) == []


def test_remove_spec_item_aliases_reports_protected_alias(aliases):
    grandchild = make_spec_item(aliases['project'], name='Grand', val_set=aliases['alias1'].val_set,
                                p_link=aliases['alias1'])
    request = make_request(aliases['editor'])
    remove_spec_item_aliases(request, aliases['parent'])
    ids = set(SpecItem.objects.values_list('pk', flat=True))
    assert aliases['alias1'].pk in ids              # still referenced by grandchild
    assert aliases['alias2'].pk not in ids          # others are still processed
    messages = [m.message for m in get_messages(request)]
    assert len(messages) == 1
    assert messages[0].startswith('Failure to delete Dom:Parent (Title of Parent), '
                                  'possibly because other spec_items reference it: ')
    assert grandchild.pk in ids


def test_mark_spec_item_aliases_as_del(aliases):
    before = datetime.now(timezone.utc)
    mark_spec_item_aliases_as_del(make_request(aliases['editor']), aliases['parent'])
    after = datetime.now(timezone.utc)
    for key in ('alias1', 'alias2'):
        item = SpecItem.objects.get(pk=aliases[key].pk)
        assert item.status == 'DEL'
        assert item.owner == aliases['editor']
        assert before <= item.updated_at <= after
    for key in ('in_default', 'unrelated', 'parent'):
        item = SpecItem.objects.get(pk=aliases[key].pk)
        assert item.status == 'NEW'
        assert item.owner == aliases['owner']
    assert SpecItem.objects.count() == 5


def test_update_dom_name_in_val_set(aliases):
    parent = aliases['parent']
    parent.name = 'Renamed'
    parent.domain = 'NewDom'
    parent.save()
    update_dom_name_in_val_set(parent)
    for key in ('alias1', 'alias2'):
        item = SpecItem.objects.get(pk=aliases[key].pk)
        assert (item.domain, item.name) == ('NewDom', 'Renamed')
    unchanged = SpecItem.objects.get(pk=aliases['in_default'].pk)
    assert (unchanged.domain, unchanged.name) == ('Dom', 'ChildInDefault')
    unrelated = SpecItem.objects.get(pk=aliases['unrelated'].pk)
    assert (unrelated.domain, unrelated.name) == ('Dom', 'Unrelated')


def test_alias_helpers_only_follow_p_link_not_s_link():
    """The helpers use p_children only: aliases linked through s_link are ignored."""
    project = make_project(make_user())
    vs1 = make_val_set(project, 'VS1')
    parent = make_spec_item(project, name='Parent')
    s_alias = make_spec_item(project, name='Parent', val_set=vs1, s_link=parent)
    request = make_request(project.owner)
    remove_spec_item_aliases(request, parent)
    mark_spec_item_aliases_as_del(request, parent)
    update_dom_name_in_val_set(parent)
    s_alias.refresh_from_db()
    assert s_alias.status == 'NEW'


# ------------------------------------------------------------------ make_temp_dir

def test_make_temp_dir_creates_timestamped_directory(tmp_path, monkeypatch):
    import os
    from editor import utilities

    class FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2024, 1, 2, 3, 4, 5, tzinfo=tz)

    monkeypatch.setattr(utilities, 'datetime', FixedDatetime)
    path = utilities.make_temp_dir(str(tmp_path), 'exp_')
    assert path == os.path.join(str(tmp_path), 'exp_2024_01_02_03_04_05')
    assert os.path.isdir(path)


def test_make_temp_dir_failure_path_raises_name_error(tmp_path, monkeypatch):
    """KNOWN-ISSUE: make-temp-dir-name-error. When the directory already exists (e.g. two exports
    within the same second) the error handler references the undefined names `request` and
    `exp_dir`, so a NameError escapes instead of the intended error message / empty string."""
    from editor import utilities

    class FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2024, 1, 2, 3, 4, 5, tzinfo=tz)

    monkeypatch.setattr(utilities, 'datetime', FixedDatetime)
    utilities.make_temp_dir(str(tmp_path), 'exp_')
    with pytest.raises(NameError):
        utilities.make_temp_dir(str(tmp_path), 'exp_')
