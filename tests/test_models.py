"""Characterization tests for editor/models.py (CRUD, __str__, defaults, on_delete behaviour)."""
import warnings
from datetime import date, datetime, timezone

import pytest
from django.db.models import ProtectedError

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from tests.factories import (FIXED_TIME, default_val_set, make_application, make_project,
                             make_project_user, make_release, make_spec_item, make_user,
                             make_val_set)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- CRUD

def test_release_crud():
    user = make_user()
    rel = make_release(user, project_version=2, application_version=3, desc='d')
    rel.refresh_from_db()
    assert (rel.project_version, rel.application_version, rel.desc) == (2, 3, 'd')
    assert rel.release_author == user
    assert rel.updated_at == FIXED_TIME
    assert rel.previous is None
    rel.desc = 'changed'
    rel.save()
    assert Release.objects.get(pk=rel.pk).desc == 'changed'
    pk = rel.pk
    rel.delete()
    assert not Release.objects.filter(pk=pk).exists()


def test_project_crud():
    user = make_user()
    project = make_project(user, name='P1', cats='DataItem', desc='D')
    project.refresh_from_db()
    assert (project.name, project.cats, project.desc) == ('P1', 'DataItem', 'D')
    assert project.owner == user
    assert project.release.desc == 'Initial release for project P1'
    # updated_at is auto_now: set to a recent aware datetime on every save
    first = project.updated_at
    assert first.tzinfo is not None
    project.name = 'P2'
    project.save()
    project.refresh_from_db()
    assert project.name == 'P2'
    assert project.updated_at >= first
    # reverse accessors
    assert list(user.owned_projects.all()) == [project]
    ValSet.objects.filter(project=project).delete()
    project.delete()
    assert not Project.objects.exists()


def test_project_user_crud():
    owner, other = make_user('owner'), make_user('other')
    project = make_project(owner)
    pu = make_project_user(project, other)
    pu.refresh_from_db()
    assert pu.role == 'RO'
    assert isinstance(pu.updated_at, date) and not isinstance(pu.updated_at, datetime)
    pu.role = 'RW'
    pu.save()
    assert ProjectUser.objects.get(pk=pu.pk).role == 'RW'
    assert list(project.project_users.all()) == [pu]
    assert list(other.used_projects.all()) == [pu]
    pu.delete()
    assert not ProjectUser.objects.exists()


def test_project_user_role_not_validated_on_save():
    """role has choices but save() does not enforce them (only full_clean does)."""
    owner, other = make_user('owner'), make_user('other')
    project = make_project(owner)
    pu = ProjectUser.objects.create(project=project, user=other, role='XX')
    pu.refresh_from_db()
    assert pu.role == 'XX'
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        pu.full_clean()


def test_application_crud():
    user = make_user()
    project = make_project(user)
    app = make_application(project, name='A1', cats='Model', desc='AD')
    app.refresh_from_db()
    assert (app.name, app.cats, app.desc) == ('A1', 'Model', 'AD')
    assert app.project == project
    assert list(project.applications.all()) == [app]
    app.name = 'A2'
    app.save()
    assert Application.objects.get(pk=app.pk).name == 'A2'
    app.delete()
    assert not Application.objects.exists()


def test_application_cats_default_empty_string():
    user = make_user()
    project = make_project(user)
    rel = make_release(user)
    app = Application.objects.create(name='A', desc='d', project=project, release=rel)
    assert app.cats == ''


def test_val_set_crud():
    user = make_user()
    project = make_project(user)
    vs = make_val_set(project, name='VS', desc='x')
    vs.refresh_from_db()
    assert (vs.name, vs.desc, vs.project) == ('VS', 'x', project)
    assert isinstance(vs.updated_at, date) and not isinstance(vs.updated_at, datetime)
    assert sorted(v.name for v in project.val_sets.all()) == ['Default', 'VS']
    vs.name = 'VS2'
    vs.save()
    assert ValSet.objects.get(pk=vs.pk).name == 'VS2'
    vs.delete()
    assert not ValSet.objects.filter(name='VS2').exists()


def test_spec_item_crud():
    user = make_user()
    project = make_project(user)
    item = make_spec_item(project, cat='DataItem', domain='D', name='N', title='T',
                          desc='desc', value='1', t1='a', n1=5)
    item.refresh_from_db()
    assert (item.cat, item.domain, item.name, item.title) == ('DataItem', 'D', 'N', 'T')
    assert (item.desc, item.value, item.t1, item.n1) == ('desc', '1', 'a', 5)
    assert item.owner == user and item.project == project
    assert item.application is None
    assert item.val_set == default_val_set(project)
    assert list(project.project_spec_items.all()) == [item]
    assert list(user.owned_spec_items.all()) == [item]
    item.title = 'T2'
    item.save()
    assert SpecItem.objects.get(pk=item.pk).title == 'T2'
    item.delete()
    assert not SpecItem.objects.exists()


def test_spec_item_application_reverse_accessor():
    user = make_user()
    project = make_project(user)
    app = make_application(project, cats='Model')
    item = make_spec_item(project, cat='Model', application=app)
    assert list(app.application_spec_items.all()) == [item]


def test_spec_item_links_reverse_accessors():
    user = make_user()
    project = make_project(user)
    parent = make_spec_item(project, name='Parent')
    child = make_spec_item(project, name='Child', p_link=parent, s_link=parent)
    assert list(parent.p_children.all()) == [child]
    assert list(parent.s_children.all()) == [child]


# ---------------------------------------------------------------- __str__

def test_release_str():
    user = make_user()
    assert str(make_release(user, project_version=3, application_version=12)) == '3.12'


def test_project_str():
    user = make_user()
    assert str(make_project(user, name='My Project')) == 'My Project'


def test_project_user_str():
    owner, other = make_user('owner'), make_user('bob')
    project = make_project(owner, name='PP')
    assert str(make_project_user(project, other)) == 'bob as user of: PP'


def test_application_and_val_set_str():
    user = make_user()
    project = make_project(user)
    assert str(make_application(project, name='AppName')) == 'AppName'
    assert str(make_val_set(project, name='VSname')) == 'VSname'
    assert str(default_val_set(project)) == 'Default'


def test_spec_item_str_with_title():
    project = make_project(make_user())
    item = make_spec_item(project, domain='Dom', name='Nm', title='The title', desc='ignored')
    assert str(item) == 'Dom:Nm (The title)'


def test_spec_item_str_empty_title_uses_desc():
    project = make_project(make_user())
    item = make_spec_item(project, domain='Dom', name='Nm', title='', desc='short desc')
    assert str(item) == 'Dom:Nm (short desc)'


def test_spec_item_str_empty_title_empty_desc():
    project = make_project(make_user())
    item = make_spec_item(project, domain='Dom', name='Nm', title='')
    assert str(item) == 'Dom:Nm ()'


@pytest.mark.parametrize('length,truncated', [(63, False), (64, True), (65, True), (200, True)])
def test_spec_item_str_desc_truncation(length, truncated):
    """desc is shortened only when len(desc) >= 64: first 64 chars + '...'."""
    project = make_project(make_user())
    desc = ''.join(chr(ord('a') + i % 26) for i in range(length))
    item = make_spec_item(project, domain='D', name='N', title='', desc=desc)
    if truncated:
        assert str(item) == 'D:N (' + desc[:64] + '...)'
    else:
        assert str(item) == 'D:N (' + desc + ')'


# ---------------------------------------------------------------- s_data JSON

def test_s_data_default_is_empty_dict():
    project = make_project(make_user())
    item = make_spec_item(project)
    item.refresh_from_db()
    assert item.s_data == {}


def test_s_data_round_trip_nested_and_unicode():
    project = make_project(make_user())
    data = {'a': 1, 'b': [1, 2, {'c': None}], 'd': {'e': {'f': True}}, 'u': 'Grüße – 日本語 ✓',
            'float': 1.5, 'empty': [], 'quote': 'a"b\\c'}
    item = make_spec_item(project, s_data=data)
    item.refresh_from_db()
    assert item.s_data == data


def test_s_data_list_and_scalar_round_trip():
    project = make_project(make_user())
    item = make_spec_item(project, name='L', s_data=[1, 'x'])
    item2 = make_spec_item(project, name='S', s_data='text')
    item.refresh_from_db()
    item2.refresh_from_db()
    assert item.s_data == [1, 'x']
    assert item2.s_data == 'text'


# ---------------------------------------------------------------- on_delete

def test_delete_project_with_spec_items_is_protected():
    project = make_project(make_user())
    make_spec_item(project)
    with pytest.raises(ProtectedError):
        project.delete()
    assert Project.objects.filter(pk=project.pk).exists()


def test_delete_project_with_val_set_is_protected():
    project = make_project(make_user())
    with pytest.raises(ProtectedError):
        project.delete()


def test_delete_project_with_application_is_protected():
    project = make_project(make_user())
    ValSet.objects.filter(project=project).delete()
    make_application(project)
    with pytest.raises(ProtectedError):
        project.delete()


def test_delete_project_with_project_user_is_protected():
    owner = make_user('o')
    project = make_project(owner)
    ValSet.objects.filter(project=project).delete()
    make_project_user(project, make_user('u'))
    with pytest.raises(ProtectedError):
        project.delete()


def test_delete_user_owning_project_is_protected():
    owner = make_user()
    make_project(owner)
    with pytest.raises(ProtectedError):
        owner.delete()


def test_delete_user_with_project_user_is_protected():
    owner, other = make_user('o'), make_user('u')
    project = make_project(owner)
    make_project_user(project, other)
    with pytest.raises(ProtectedError):
        other.delete()


def test_delete_user_owning_spec_item_is_protected():
    owner, other = make_user('o'), make_user('u')
    project = make_project(owner)
    make_spec_item(project, owner=other)
    with pytest.raises(ProtectedError):
        other.delete()


def test_delete_user_authoring_release_is_protected():
    user = make_user()
    make_release(user)
    with pytest.raises(ProtectedError):
        user.delete()


def test_delete_release_used_by_project_is_protected():
    project = make_project(make_user())
    with pytest.raises(ProtectedError):
        project.release.delete()


def test_delete_release_used_by_application_is_protected():
    project = make_project(make_user())
    app = make_application(project)
    with pytest.raises(ProtectedError):
        app.release.delete()


def test_delete_val_set_with_spec_items_is_protected():
    project = make_project(make_user())
    vs = make_val_set(project)
    make_spec_item(project, val_set=vs)
    with pytest.raises(ProtectedError):
        vs.delete()


def test_delete_application_with_spec_items_is_protected():
    project = make_project(make_user())
    app = make_application(project, cats='Model')
    make_spec_item(project, cat='Model', application=app)
    with pytest.raises(ProtectedError):
        app.delete()


def test_delete_spec_item_referenced_by_p_link_is_protected():
    project = make_project(make_user())
    parent = make_spec_item(project, name='P')
    make_spec_item(project, name='C', p_link=parent)
    with pytest.raises(ProtectedError):
        parent.delete()


def test_delete_spec_item_referenced_by_s_link_is_protected():
    project = make_project(make_user())
    parent = make_spec_item(project, name='P')
    make_spec_item(project, name='C', s_link=parent)
    with pytest.raises(ProtectedError):
        parent.delete()


# ---------------------------------------------------------------- previous O2O SET_DEFAULT

def test_spec_item_previous_set_to_none_when_previous_deleted():
    project = make_project(make_user())
    old = make_spec_item(project, name='N', status='OBS')
    new = make_spec_item(project, name='N', status='MOD', previous=old)
    assert new.previous == old
    old.delete()
    new.refresh_from_db()
    assert new.previous is None
    assert new.previous_id is None
    assert SpecItem.objects.filter(pk=new.pk).exists()


def test_spec_item_previous_chain_middle_deleted():
    project = make_project(make_user())
    a = make_spec_item(project, name='N', status='OBS')
    b = make_spec_item(project, name='N', status='OBS', previous=a)
    c = make_spec_item(project, name='N', status='MOD', previous=b)
    b.delete()
    c.refresh_from_db()
    a.refresh_from_db()
    assert c.previous is None
    assert a.pk is not None


def test_spec_item_previous_is_one_to_one():
    from django.db import IntegrityError, transaction
    project = make_project(make_user())
    old = make_spec_item(project, name='N', status='OBS')
    make_spec_item(project, name='N1', status='MOD', previous=old)
    with pytest.raises(IntegrityError), transaction.atomic():
        make_spec_item(project, name='N2', status='MOD', previous=old)


def test_release_previous_set_to_none_when_previous_deleted():
    user = make_user()
    old = make_release(user, project_version=0)
    new = make_release(user, project_version=1, previous=old)
    old.delete()
    new.refresh_from_db()
    assert new.previous is None


def test_release_previous_reverse_accessor():
    user = make_user()
    old = make_release(user)
    new = make_release(user, project_version=1, previous=old)
    assert old.release == new  # O2O reverse accessor named after the model


# ---------------------------------------------------------------- defaults

def test_spec_item_field_defaults():
    project = make_project(make_user())
    item = SpecItem.objects.create(
        cat='DataItem', name='N', domain='D', project=project, title='t',
        owner=project.owner, val_set=default_val_set(project), updated_at=FIXED_TIME)
    item.refresh_from_db()
    assert item.status == 'NEW'
    assert item.desc == item.rationale == item.remarks == item.implementation == ''
    assert item.value == item.t1 == item.t2 == item.t3 == item.t4 == item.t5 == ''
    assert (item.n1, item.n2, item.n3) == (0, 0, 0)
    assert item.change_log == ''
    assert item.p_kind == item.s_kind == ''
    assert item.p_link is None and item.s_link is None
    assert item.previous is None and item.application is None
    assert item.s_data == {}


def test_spec_item_created_at_default_naive_datetime_stored_as_utc():
    # FIXED: naive-created-at-default (was: default was the naive datetime(2000,1,1); save warned and
    # the unsaved instance held a naive value). The default is now aware UTC; stored value is unchanged.
    project = make_project(make_user())
    with warnings.catch_warnings():
        warnings.simplefilter('error', RuntimeWarning)
        item = SpecItem.objects.create(
            cat='DataItem', name='N', domain='D', project=project, title='t',
            owner=project.owner, val_set=default_val_set(project), updated_at=FIXED_TIME)
    assert item.created_at == datetime(2000, 1, 1, tzinfo=timezone.utc)
    assert item.created_at.tzinfo is not None
    item.refresh_from_db()
    assert item.created_at == datetime(2000, 1, 1, tzinfo=timezone.utc)


def test_release_version_defaults():
    # KNOWN-ISSUE: release-version-default-str (default="0" is a string on unsaved instances)
    user = make_user()
    unsaved = Release(release_author=user, desc='d', updated_at=FIXED_TIME)
    # the default is the string "0" until the instance is reloaded from the DB
    assert unsaved.project_version == '0'
    assert unsaved.application_version == '0'
    unsaved.save()
    unsaved.refresh_from_db()
    assert unsaved.project_version == 0
    assert unsaved.application_version == 0
    assert unsaved.previous is None


def test_val_set_default_name():
    project = make_project(make_user())
    vs = ValSet.objects.create(project=project, desc='d')
    assert vs.name == 'Default'


def test_project_user_default_role():
    owner, other = make_user('o'), make_user('u')
    project = make_project(owner)
    assert ProjectUser.objects.create(project=project, user=other).role == 'RO'


def test_updated_at_auto_now_fields_are_overridden_on_save():
    user = make_user()
    project = make_project(user)
    app = make_application(project)
    fixed = datetime(2001, 2, 3, tzinfo=timezone.utc)
    Application.objects.filter(pk=app.pk).update(updated_at=fixed)
    app.refresh_from_db()
    assert app.updated_at == fixed
    app.save()
    app.refresh_from_db()
    assert app.updated_at > fixed
