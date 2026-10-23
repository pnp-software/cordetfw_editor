"""Characterization tests for project/application releases (views + editor.utilities)."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from django.contrib.auth import login
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.db.models import ProtectedError
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from editor.configs import configs
from editor.models import Application, Release, SpecItem
from editor.utilities import (del_release, do_application_release, do_project_release,
                              get_previous_list)
from tests.factories import (FIXED_TIME, default_val_set, make_application, make_project,
                             make_release, make_spec_item, make_user, make_val_set)

pytestmark = pytest.mark.django_db


def make_request(user):
    request = RequestFactory().get('/')
    request.session = SessionStore()
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request._messages = FallbackStorage(request)
    return request


def status_of(item):
    return SpecItem.objects.get(pk=item.pk).status


def now_window():
    return datetime.now(timezone.utc)


def versions(release):
    return (release.project_version, release.application_version)


class Scenario:
    """Project with project-level items of every status, two applications with items,
    an item in another ValSet and an unrelated second project."""

    def __init__(self):
        self.owner = make_user('owner')
        self.releaser = make_user('releaser')
        self.project = make_project(self.owner, name='Proj')
        p = self.project
        self.p_new = make_spec_item(p, name='pnew', status='NEW')
        self.p_mod = make_spec_item(p, name='pmod', status='MOD')
        self.p_cnf = make_spec_item(p, name='pcnf', status='CNF')
        self.p_del = make_spec_item(p, name='pdel', status='DEL')
        self.p_obs = make_spec_item(p, name='pobs', status='OBS')
        self.vs = make_val_set(p, 'VS1')
        self.p_new_vs = make_spec_item(p, name='pnewvs', status='NEW', val_set=self.vs)
        self.app1 = make_application(p, name='App1', cats='Model')
        self.app2 = make_application(p, name='App2', cats='Model')
        self.a1_new = make_spec_item(p, cat='Model', name='a1new', status='NEW', application=self.app1)
        self.a1_mod = make_spec_item(p, cat='Model', name='a1mod', status='MOD', application=self.app1)
        self.a1_cnf = make_spec_item(p, cat='Model', name='a1cnf', status='CNF', application=self.app1)
        self.a1_del = make_spec_item(p, cat='Model', name='a1del', status='DEL', application=self.app1)
        self.a1_obs = make_spec_item(p, cat='Model', name='a1obs', status='OBS', application=self.app1)
        self.a2_new = make_spec_item(p, cat='Model', name='a2new', status='NEW', application=self.app2)
        self.other_owner = make_user('other')
        self.other = make_project(self.other_owner, name='Other')
        self.o_new = make_spec_item(self.other, name='onew', status='NEW')
        self.oapp = make_application(self.other, name='OApp')
        self.oa_new = make_spec_item(self.other, cat='Model', name='oanew', status='NEW',
                                     application=self.oapp)

    def statuses(self):
        return {i.name: status_of(i) for i in SpecItem.objects.all()}


@pytest.fixture
def sc():
    return Scenario()


# ------------------------------------------------------------------ do_project_release

def test_do_project_release_versions_and_chain(sc):
    old = sc.project.release
    old_app1, old_app2 = sc.app1.release, sc.app2.release
    before = now_window()
    do_project_release(make_request(sc.releaser), sc.project, 'First project release')
    after = now_window()

    sc.project.refresh_from_db()
    new = sc.project.release
    assert new.pk != old.pk
    assert versions(new) == (1, 0)
    assert new.previous == old
    assert versions(old) == (0, 0)
    assert new.desc == 'First project release'
    assert new.release_author == sc.releaser
    assert before <= new.updated_at <= after

    # every application of the project is released too, with application_version reset to 0
    for app, old_rel in ((sc.app1, old_app1), (sc.app2, old_app2)):
        app.refresh_from_db()
        assert versions(app.release) == (1, 0)
        assert app.release.previous == old_rel
        assert app.release.desc == 'First project release'
        assert app.release.release_author == sc.releaser
    # other project untouched
    sc.oapp.refresh_from_db()
    assert versions(sc.oapp.release) == (0, 0)
    sc.other.refresh_from_db()
    assert versions(sc.other.release) == (0, 0)


def test_do_project_release_resets_application_version(sc):
    do_application_release(make_request(sc.releaser), sc.app1, 'app rel')
    sc.app1.refresh_from_db()
    assert versions(sc.app1.release) == (0, 1)
    do_project_release(make_request(sc.releaser), sc.project, 'proj rel')
    sc.app1.refresh_from_db()
    sc.app2.refresh_from_db()
    assert versions(sc.app1.release) == (1, 0)
    assert versions(sc.app2.release) == (1, 0)
    assert [versions(r) for r in get_previous_list(sc.app1.release)] == [(1, 0), (0, 1), (0, 0)]


def test_do_project_release_item_statuses(sc):
    do_project_release(make_request(sc.releaser), sc.project, 'rel')
    assert sc.statuses() == {
        'pnew': 'CNF', 'pmod': 'CNF', 'pcnf': 'CNF', 'pdel': 'DEL', 'pobs': 'OBS',
        'pnewvs': 'CNF',   # no ValSet filtering
        'a1new': 'CNF', 'a1mod': 'CNF', 'a1cnf': 'CNF', 'a1del': 'DEL', 'a1obs': 'OBS',
        'a2new': 'CNF',    # applications are released as part of the project release
        'onew': 'NEW', 'oanew': 'NEW',   # other project untouched
    }


def test_do_project_release_does_not_touch_updated_at(sc):
    do_project_release(make_request(sc.releaser), sc.project, 'rel')
    assert SpecItem.objects.get(pk=sc.p_new.pk).updated_at == FIXED_TIME
    assert SpecItem.objects.get(pk=sc.a1_new.pk).updated_at == FIXED_TIME


def test_do_project_release_twice_increments(sc):
    do_project_release(make_request(sc.releaser), sc.project, 'one')
    do_project_release(make_request(sc.releaser), sc.project, 'two')
    sc.project.refresh_from_db()
    assert [versions(r) for r in get_previous_list(sc.project.release)] == [(2, 0), (1, 0), (0, 0)]
    assert [r.desc for r in get_previous_list(sc.project.release)][:2] == ['two', 'one']


def test_project_release_with_no_items_or_applications():
    owner = make_user()
    project = make_project(owner)
    do_project_release(make_request(owner), project, 'empty')
    project.refresh_from_db()
    assert versions(project.release) == (1, 0)


# ------------------------------------------------------------------ do_application_release

def test_do_application_release_versions_and_chain(sc):
    old = sc.app1.release
    proj_release = sc.project.release
    before = now_window()
    do_application_release(make_request(sc.releaser), sc.app1, 'App release')
    after = now_window()
    sc.app1.refresh_from_db()
    new = sc.app1.release
    assert versions(new) == (0, 1)
    assert new.previous == old
    assert new.desc == 'App release'
    assert new.release_author == sc.releaser
    assert before <= new.updated_at <= after
    # project release is untouched, other application is untouched
    sc.project.refresh_from_db()
    assert sc.project.release == proj_release
    sc.app2.refresh_from_db()
    assert versions(sc.app2.release) == (0, 0)


def test_do_application_release_increments_application_version(sc):
    for n in (1, 2, 3):
        do_application_release(make_request(sc.releaser), sc.app1, 'r%d' % n)
        sc.app1.refresh_from_db()
        assert versions(sc.app1.release) == (0, n)


def test_do_application_release_uses_current_project_version(sc):
    do_project_release(make_request(sc.releaser), sc.project, 'p')
    sc.project.refresh_from_db()
    sc.app1.refresh_from_db()
    do_application_release(make_request(sc.releaser), sc.app1, 'a')
    sc.app1.refresh_from_db()
    assert versions(sc.app1.release) == (1, 1)


def test_do_application_release_item_statuses(sc):
    do_application_release(make_request(sc.releaser), sc.app1, 'rel')
    assert sc.statuses() == {
        'pnew': 'NEW', 'pmod': 'MOD', 'pcnf': 'CNF', 'pdel': 'DEL', 'pobs': 'OBS',
        'pnewvs': 'NEW',
        'a1new': 'CNF', 'a1mod': 'CNF', 'a1cnf': 'CNF', 'a1del': 'DEL', 'a1obs': 'OBS',
        'a2new': 'NEW',
        'onew': 'NEW', 'oanew': 'NEW',
    }


def test_do_application_release_for_new_application_without_release(sc):
    app = Application(name='Fresh', desc='d', cats='Model', project=sc.project)
    assert app.release_id is None
    do_application_release(make_request(sc.releaser), app, 'Initial release for application Fresh')
    app.refresh_from_db()
    assert versions(app.release) == (0, 0)
    assert app.release.previous is None
    assert Application.objects.filter(name='Fresh').count() == 1
    # KNOWN-ISSUE: add-app-releases-null-app-items (see test_add_application_releases_all_items_without_application)
    assert status_of(sc.p_new) == 'CNF'
    assert status_of(sc.o_new) == 'CNF'
    assert status_of(sc.a1_new) == 'NEW'


def test_do_application_release_for_new_application_after_project_release(sc):
    do_project_release(make_request(sc.releaser), sc.project, 'p')
    sc.project.refresh_from_db()
    app = Application(name='Fresh', desc='d', cats='Model', project=sc.project)
    do_application_release(make_request(sc.releaser), app, 'init')
    app.refresh_from_db()
    assert versions(app.release) == (1, 0)
    assert app.release.previous is None


def test_do_application_release_as_part_of_project_release_flag(sc):
    do_application_release(make_request(sc.releaser), sc.app1, 'x', is_proj_release=True)
    sc.app1.refresh_from_db()
    assert versions(sc.app1.release) == (0, 0)   # version reset instead of incremented
    assert sc.app1.release.previous is not None


# ------------------------------------------------------------------ get_previous_list / del_release

def test_get_previous_list_single_and_chain():
    user = make_user()
    r0 = make_release(user)
    r1 = make_release(user, project_version=1, previous=r0)
    r2 = make_release(user, project_version=2, previous=r1)
    assert get_previous_list(r0) == [r0]
    assert get_previous_list(r2) == [r2, r1, r0]


def test_del_release_deletes_whole_chain():
    user = make_user()
    r0 = make_release(user)
    r1 = make_release(user, project_version=1, previous=r0)
    r2 = make_release(user, project_version=2, previous=r1)
    request = make_request(user)
    assert del_release(request, r2, 1) is True
    assert Release.objects.count() == 0
    assert list(get_messages(request)) == []


def test_del_release_only_deletes_older_part_of_chain():
    user = make_user()
    r0 = make_release(user)
    r1 = make_release(user, project_version=1, previous=r0)
    r2 = make_release(user, project_version=2, previous=r1)
    del_release(make_request(user), r1, 1)
    assert list(Release.objects.values_list('pk', flat=True)) == [r2.pk]
    r2.refresh_from_db()
    assert r2.previous is None   # SET_DEFAULT


def test_del_release_depth_limit(monkeypatch):
    monkeypatch.setitem(configs['general'], 'max_depth', 1)
    user = make_user()
    r0 = make_release(user)
    r1 = make_release(user, project_version=1, previous=r0)
    r2 = make_release(user, project_version=2, previous=r1)
    r3 = make_release(user, project_version=3, previous=r2)
    request = make_request(user)
    # n=1 deletes r3, recursion n=2 > max_depth(1) -> error message, r2/r1/r0 remain
    assert del_release(request, r3, 1) is True
    assert sorted(Release.objects.values_list('pk', flat=True)) == [r0.pk, r1.pk, r2.pk]
    assert [m.message for m in get_messages(request)] == [
        'Attempt to delete a release has reached the limit on the depth of recursion: 2']
    # direct call above the limit returns False and deletes nothing
    request = make_request(user)
    assert del_release(request, r2, 2) is False
    assert Release.objects.count() == 3


def test_del_release_referenced_by_project_is_protected(sc):
    with pytest.raises(ProtectedError):
        del_release(make_request(sc.owner), sc.project.release, 1)


# ------------------------------------------------------------------ views

def post_release(client, url, description):
    return client.post(url, {'description': description})


def test_make_project_release_view_post(client, sc):
    client.force_login(sc.owner)
    old = sc.project.release
    before = now_window()
    response = post_release(client, f'/editor/{sc.project.id}/make_project_release', 'View release')
    after = now_window()
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    sc.project.refresh_from_db()
    new = sc.project.release
    assert versions(new) == (1, 0)
    assert new.previous == old
    assert new.desc == 'View release'
    assert new.release_author == sc.owner
    assert before <= new.updated_at <= after
    assert status_of(sc.p_new) == 'CNF' and status_of(sc.a2_new) == 'CNF'
    assert status_of(sc.o_new) == 'NEW'
    for app in (sc.app1, sc.app2):
        app.refresh_from_db()
        assert versions(app.release) == (1, 0)


def test_make_project_release_description_is_stripped_by_form(client, sc):
    client.force_login(sc.owner)
    post_release(client, f'/editor/{sc.project.id}/make_project_release', '  padded  ')
    sc.project.refresh_from_db()
    assert sc.project.release.desc == 'padded'   # CharField strips its input


@pytest.mark.parametrize('description', ['', '   ', '\n\t '])
def test_make_project_release_blank_description_rerenders_form(client, sc, description):
    client.force_login(sc.owner)
    old = sc.project.release
    n_releases = Release.objects.count()
    statuses = sc.statuses()
    response = post_release(client, f'/editor/{sc.project.id}/make_project_release', description)
    assert response.status_code == 200
    assert response.templates[0].name == 'make_release.html'
    assert 'description' in response.context['form'].errors
    sc.project.refresh_from_db()
    assert sc.project.release == old
    assert Release.objects.count() == n_releases
    assert sc.statuses() == statuses


def test_make_project_release_get_renders_release_list(client, sc):
    do_project_release(make_request(sc.releaser), sc.project, 'Second <b>release</b>')
    client.force_login(sc.owner)
    response = client.get(f'/editor/{sc.project.id}/make_project_release')
    assert response.status_code == 200
    assert response.context['entity_being_released'] == sc.project
    releases = response.context['releases']
    assert [versions(r) for r in releases] == [(1, 0), (0, 0)]
    html = response.content.decode()
    assert 'Make New release for Proj' in html
    assert 'Project description' in html
    assert 'Release History' in html
    rows = re.findall(r'<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>', html, re.S)
    assert len(rows) == 2
    assert rows[0][:3] == ('1.0', 'Second &lt;b&gt;release&lt;/b&gt;', 'releaser')
    assert rows[1] == ('0.0', 'Initial release for project Proj', 'owner', '15-01-2024 10:30')


def test_make_project_release_get_does_not_release(client, sc):
    client.force_login(sc.owner)
    statuses = sc.statuses()
    client.get(f'/editor/{sc.project.id}/make_project_release')
    assert sc.statuses() == statuses
    sc.project.refresh_from_db()
    assert versions(sc.project.release) == (0, 0)


def test_make_application_release_view_post(client, sc):
    client.force_login(sc.owner)
    old = sc.app1.release
    response = post_release(client, f'/editor/{sc.app1.id}/make_application_release', 'App view release')
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    sc.app1.refresh_from_db()
    assert versions(sc.app1.release) == (0, 1)
    assert sc.app1.release.previous == old
    assert sc.app1.release.desc == 'App view release'
    assert sc.app1.release.release_author == sc.owner
    assert status_of(sc.a1_new) == 'CNF' and status_of(sc.a1_mod) == 'CNF'
    assert status_of(sc.a1_del) == 'DEL' and status_of(sc.a1_obs) == 'OBS'
    assert status_of(sc.a2_new) == 'NEW' and status_of(sc.p_new) == 'NEW'
    sc.project.refresh_from_db()
    assert versions(sc.project.release) == (0, 0)


def test_make_application_release_blank_description_rerenders_form(client, sc):
    client.force_login(sc.owner)
    old = sc.app1.release
    response = post_release(client, f'/editor/{sc.app1.id}/make_application_release', '')
    assert response.status_code == 200
    assert 'description' in response.context['form'].errors
    sc.app1.refresh_from_db()
    assert sc.app1.release == old
    assert status_of(sc.a1_new) == 'NEW'


def test_make_application_release_get_lists_application_releases(client, sc):
    do_application_release(make_request(sc.releaser), sc.app1, 'second')
    client.force_login(sc.owner)
    response = client.get(f'/editor/{sc.app1.id}/make_application_release')
    assert response.status_code == 200
    assert [versions(r) for r in response.context['releases']] == [(0, 1), (0, 0)]
    html = response.content.decode()
    assert 'Make New release for App1' in html
    assert 'Application description' in html
    assert '<td>0.1</td>' in html and '<td>0.0</td>' in html


def test_add_application_view_creates_initial_release(client, sc):
    client.force_login(sc.owner)
    response = client.post(f'/editor/{sc.project.id}/add_application',
                           {'name': 'NewApp', 'description': 'new app', 'cats': 'DataItem, EnumType'})
    assert response.status_code == 302
    assert response['Location'] == '/editor'
    app = Application.objects.get(name='NewApp')
    assert app.project == sc.project
    assert app.desc == 'new app'
    assert app.cats == 'DataItem,EnumType'     # spaces removed
    assert versions(app.release) == (0, 0)
    assert app.release.desc == 'Initial release for application NewApp'
    assert app.release.release_author == sc.owner
    assert app.release.previous is None
    assert Application.objects.filter(project=sc.project).count() == 3
    assert Application.objects.count() == 4


def test_add_application_after_project_release_uses_project_version(client, sc):
    do_project_release(make_request(sc.owner), sc.project, 'p')
    client.force_login(sc.owner)
    client.post(f'/editor/{sc.project.id}/add_application',
                {'name': 'LateApp', 'description': 'd', 'cats': 'DataItem'})
    app = Application.objects.get(name='LateApp')
    assert versions(app.release) == (1, 0)


def test_add_application_releases_all_items_without_application(client, sc):
    """KNOWN-ISSUE: add-app-releases-null-app-items. add_application calls
    do_application_release on the not-yet-saved Application (id None), so
    filter(application_id=None) matches every NEW/MOD spec item that has no application,
    in ALL projects: they are silently turned into CNF. Items of existing applications
    are not touched."""
    client.force_login(sc.owner)
    client.post(f'/editor/{sc.project.id}/add_application',
                {'name': 'NewApp', 'description': 'd', 'cats': 'DataItem'})
    assert sc.statuses() == {
        'pnew': 'CNF', 'pmod': 'CNF', 'pcnf': 'CNF', 'pdel': 'DEL', 'pobs': 'OBS',
        'pnewvs': 'CNF',
        'a1new': 'NEW', 'a1mod': 'MOD', 'a1cnf': 'CNF', 'a1del': 'DEL', 'a1obs': 'OBS',
        'a2new': 'NEW',
        'onew': 'CNF',     # item of ANOTHER project is released as well
        'oanew': 'NEW',
    }


def test_add_application_invalid_category_rerenders_form(client, sc):
    client.force_login(sc.owner)
    response = client.post(f'/editor/{sc.project.id}/add_application',
                           {'name': 'Bad', 'description': 'd', 'cats': 'Nonexistent'})
    assert response.status_code == 200
    assert 'cats' in response.context['form'].errors
    assert not Application.objects.filter(name='Bad').exists()


def test_add_application_category_check_is_a_substring_match(client, sc):
    """KNOWN-ISSUE: app-cats-substring. ApplicationForm.clean_cats tests
    `cat in project.cats` on the raw string, so 'Data' (a substring of 'DataItem') is accepted
    although it is not a project category."""
    client.force_login(sc.owner)
    response = client.post(f'/editor/{sc.project.id}/add_application',
                           {'name': 'Sub', 'description': 'd', 'cats': 'Data'})
    assert response.status_code == 302
    assert Application.objects.get(name='Sub').cats == 'Data'


def test_add_application_blank_fields_rerender_form(client, sc):
    client.force_login(sc.owner)
    response = client.post(f'/editor/{sc.project.id}/add_application', {'name': '', 'description': '', 'cats': ''})
    assert response.status_code == 200
    assert set(response.context['form'].errors) == {'name', 'description', 'cats'}
    assert Application.objects.count() == 3


def test_index_shows_release_versions(client, sc):
    do_project_release(make_request(sc.releaser), sc.project, 'p')
    client.force_login(sc.owner)
    response = client.get('/editor/')
    assert response.status_code == 200
    html = response.content.decode()
    assert '1.0' in html
