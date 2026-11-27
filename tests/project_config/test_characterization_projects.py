import pytest
from django.contrib.messages import get_messages

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from tests.project_config.base import ALL_CATS, World, make_item, make_project, make_user

pytestmark = pytest.mark.django_db

CATS_HELP = 'Must contain a comma-separated list of categories from: ' + ', '.join(ALL_CATS)


@pytest.fixture
def w(client):
    return World(client)


@pytest.fixture
def staff(w):
    """A staff user without project access, logged in."""
    user = make_user('staff', is_staff=True)
    w.login(user)
    return user


def add_project(w, cats, name='NewProj'):
    return w.client.post(w.url('add_project'), {'name': name, 'owner': w.owner.id, 'cats': cats,
                                                'description': 'A new project'})


# ------------------------------------------------------------------ projects

def test_add_project_creates_project_release_and_default_val_set(w, staff):
    response = add_project(w, ' Service , Packet,DerPacket,PacketPar,VerLink , EnumType,EnumValue,DataItem,'
                              'DataItemType,Requirement')
    assert (response.status_code, response.url) == (302, '/editor')
    project = Project.objects.get(name='NewProj')
    assert project.cats == ('Service,Packet,DerPacket,PacketPar,VerLink,EnumType,EnumValue,DataItem,'
                            'DataItemType,Requirement')
    assert (project.owner_id, project.desc) == (w.owner.id, 'A new project')
    release = project.release
    assert (release.project_version, release.application_version, release.previous) == (0, 0, None)
    assert project.release.desc == 'Initial release for project NewProj'
    assert project.release.release_author_id == staff.id
    assert list(ValSet.objects.filter(project=project).values_list('name', 'desc')) == [('Default', 'Default ValSet')]


def test_unknown_categories_are_rejected(w, staff):
    response = add_project(w, 'Service,Bogus')
    assert response.status_code == 200
    assert response.context['form'].errors['cats'] == [CATS_HELP]
    assert not Project.objects.filter(name='NewProj').exists()


@pytest.mark.parametrize('cats,message', [
    ('Packet', 'Category Packet requires dependent category DerPacket'),
    ('Packet,DerPacket', 'Category Packet requires dependent category PacketPar'),
    ('Service', 'Category Service requires dependent category Packet'),
    ('ParReq', 'Category ParReq requires dependent category TracLink'),
    ('Requirement', 'Category Requirement requires dependent category VerLink'),
    ('DerReq,VerLink', 'Category DerReq requires dependent category TracLink'),
])
def test_categories_require_their_expand_and_traceability_dependencies(w, staff, cats, message):
    response = add_project(w, cats)
    assert response.status_code == 200
    assert response.context['form'].errors['cats'] == [message]
    assert not Project.objects.filter(name='NewProj').exists()


@pytest.mark.parametrize('cat', ['InfoItem', 'VerLink', 'TracLink', 'EnumValue', 'AdaptPoint', 'FCP', 'Model',
                                 'ComIntEvt'])
def test_categories_without_dependencies_are_accepted_alone(w, staff, cat):
    assert add_project(w, cat, name='P_' + cat).status_code == 302


def test_only_staff_can_add_projects(w, staff):
    w.login(w.owner)
    response = add_project(w, 'InfoItem')
    assert (response.status_code, response.url) == (302, '/editor')
    assert not Project.objects.filter(name='NewProj').exists()


def test_edit_project_requires_staff_even_for_the_owner(w, staff):
    w.login(w.owner)
    url = w.url('edit_project', w.project.id)
    response = w.client.post(url, {'name': 'Hijacked', 'owner': w.owner.id, 'cats': 'InfoItem', 'description': 'x'})
    assert (response.status_code, response.url) == (302, '/editor')
    assert Project.objects.get(id=w.project.id).name == 'Proj'


def test_staff_can_edit_project_name_owner_and_categories(w, staff):
    url = w.url('edit_project', w.project.id)
    response = w.client.post(url, {'name': 'Renamed', 'owner': w.rw_user.id, 'cats': 'InfoItem, VerLink',
                                   'description': 'new desc'})
    assert (response.status_code, response.url) == (302, '/editor')
    project = Project.objects.get(id=w.project.id)
    assert (project.name, project.desc, project.owner_id, project.cats) == ('Renamed', 'new desc', w.rw_user.id,
                                                                            'InfoItem,VerLink')
    bad = w.client.post(url, {'name': 'Renamed', 'owner': w.rw_user.id, 'cats': 'Requirement', 'description': 'd'})
    assert bad.context['form'].errors['cats'] == ['Category Requirement requires dependent category VerLink']


def test_edit_project_form_is_prefilled(w, staff):
    response = w.client.get(w.url('edit_project', w.project.id))
    form = response.context['form']
    assert (form['name'].value(), form['cats'].value()) == ('Proj', w.project.cats)
    assert [u.user.username for u in response.context['project_users']] == ['rw_user']
    assert [v.name for v in response.context['val_sets']] == ['Default']


def test_project_users_are_managed_through_posts(w, staff):
    newcomer = make_user('newcomer')
    url = w.url('edit_project', w.project.id)
    w.client.post(url, {'user_id': newcomer.id, 'role': 'RO'})
    assert ProjectUser.objects.get(project=w.project, user=newcomer).role == 'RO'
    w.client.post(url, {'user_id': newcomer.id, 'role': 'RW'})
    assert ProjectUser.objects.get(project=w.project, user=newcomer).role == 'RW'
    assert ProjectUser.objects.filter(project=w.project, user=newcomer).count() == 1
    w.client.post(url, {'del_user_id': ProjectUser.objects.get(project=w.project, user=newcomer).id})
    assert not ProjectUser.objects.filter(project=w.project, user=newcomer).exists()


def test_old_get_links_no_longer_change_the_project(w, staff):
    newcomer = make_user('newcomer')
    response = w.client.get(w.url('edit_project', w.project.id) + '?user_id=%d&role=RW' % newcomer.id)
    assert response.status_code == 200
    assert not ProjectUser.objects.filter(project=w.project, user=newcomer).exists()


def test_val_sets_are_managed_by_staff_only(w, staff):
    add_url = w.url('add_val_set', w.project.id)
    response = w.client.post(add_url, {'name': 'Extra', 'description': 'Extra set'})
    assert response.url == '/editor/%d/edit_project' % w.project.id
    extra = ValSet.objects.get(project=w.project, name='Extra')
    w.client.post(w.url('edit_val_set', w.project.id, extra.id), {'name': 'Extra2', 'description': 'd2'})
    assert ValSet.objects.get(id=extra.id).name == 'Extra2'
    w.client.post(w.url('edit_project', w.project.id), {'del_val_set_id': extra.id})
    assert not ValSet.objects.filter(id=extra.id).exists()
    w.login(w.owner)
    assert w.client.post(add_url, {'name': 'Nope', 'description': 'd'}).url == '/editor'
    assert not ValSet.objects.filter(name='Nope').exists()


def test_val_set_in_use_cannot_be_deleted(w, staff):
    alt = ValSet.objects.create(project=w.project, name='Alt', desc='')
    make_item(w.project, 'Service', 'S', 'x', val_set=alt)
    response = w.client.post(w.url('edit_project', w.project.id), {'del_val_set_id': alt.id}, follow=True)
    assert ValSet.objects.filter(id=alt.id).exists()
    assert any('Failure to delete ValSet' in str(m) for m in get_messages(response.wsgi_request))


def test_delete_project_removes_its_data_only(w, staff):
    other, _ = make_project('Other', owner=w.owner)
    other_item = make_item(other, 'Service', 'S', 'keep')
    service = make_item(w.project, 'Service', 'S', 'svc')
    make_item(w.project, 'Packet', 'P', 'pkt', p_link=service)
    make_item(w.project, 'Requirement', 'R', 'req')
    releases_before = Release.objects.count()
    assert w.client.get(w.url('del_project', w.project.id)).status_code == 405
    assert Project.objects.filter(id=w.project.id).exists()
    response = w.client.post(w.url('del_project', w.project.id))
    assert (response.status_code, response.url) == (302, '/editor')
    assert not Project.objects.filter(id=w.project.id).exists()
    assert not SpecItem.objects.filter(project_id=w.project.id).exists()
    assert not ValSet.objects.filter(project_id=w.project.id).exists()
    assert not Application.objects.filter(project_id=w.project.id).exists()
    assert not ProjectUser.objects.filter(project_id=w.project.id).exists()
    assert Release.objects.count() == releases_before - 2       # project release + application release
    assert SpecItem.objects.filter(id=other_item.id).exists()
    assert Project.objects.filter(id=other.id).exists()


# ------------------------------------------------------------------ applications

def test_owner_adds_an_application_with_categories_of_the_project(w):
    w.login(w.owner)
    response = w.client.post(w.url('add_application', w.project.id),
                             {'name': 'Second', 'description': 'desc', 'cats': 'Requirement, ParReq'})
    assert (response.status_code, response.url) == (302, '/editor')
    application = Application.objects.get(name='Second')
    assert (application.project_id, application.desc, application.cats) == (w.project.id, 'desc', 'Requirement,ParReq')
    assert (application.release.project_version, application.release.application_version,
            application.release.previous) == (0, 0, None)
    assert application.release.desc == 'Initial release for application Second'


def test_application_categories_must_belong_to_the_project(w):
    w.login(w.owner)
    project, _ = make_project('Small', owner=w.owner, cats=['Requirement', 'VerLink'])
    response = w.client.post(w.url('add_application', project.id),
                             {'name': 'A', 'description': 'd', 'cats': 'Requirement,ParReq'})
    assert response.status_code == 200
    assert response.context['form'].errors['cats'] == [
        'Must contain a comma-separated list of categories from: Requirement,VerLink']
    assert not Application.objects.filter(project=project).exists()


def test_edit_application(w):
    w.login(w.owner)
    response = w.client.post(w.url('edit_application', w.application.id),
                             {'name': 'Renamed', 'description': 'new', 'cats': 'Requirement'})
    assert (response.status_code, response.url) == (302, '/editor')
    application = Application.objects.get(id=w.application.id)
    assert (application.name, application.desc, application.cats) == ('Renamed', 'new', 'Requirement')


def test_only_the_owner_manages_applications(w):
    for user in (w.rw_user, make_user('staff', is_staff=True)):
        w.login(user)
        response = w.client.post(w.url('add_application', w.project.id),
                                 {'name': 'Sneaky', 'description': 'd', 'cats': 'Requirement'})
        assert (response.status_code, response.url) == (302, '/editor')
        response = w.client.post(w.url('edit_application', w.application.id),
                                 {'name': 'Sneaky', 'description': 'd', 'cats': 'Requirement'})
        assert response.url == '/editor'
    assert not Application.objects.filter(name='Sneaky').exists()
    assert Application.objects.get(id=w.application.id).name == 'App'
