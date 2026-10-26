"""
Plain helper factories (no factory_boy) for the characterization suite.

All timestamps are fixed so that rendered pages and exported files are
deterministic and can be compared against golden files.
"""

from datetime import datetime, timezone

from django.contrib.auth.models import User

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet

FIXED_TIME = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
PASSWORD = 'test-password-123'


def make_user(username='alice', is_staff=False, is_superuser=False, password=PASSWORD):
    return User.objects.create_user(username=username, password=password,
                                    email=username + '@example.com',
                                    is_staff=is_staff, is_superuser=is_superuser)


def make_release(author, project_version=0, application_version=0, previous=None,
                 desc='Initial release', updated_at=FIXED_TIME):
    return Release.objects.create(release_author=author, desc=desc, updated_at=updated_at,
                                  project_version=project_version,
                                  application_version=application_version, previous=previous)


def make_project(owner, name='Proj', cats='DataItem,EnumType,EnumValue,DataItemType',
                 desc='Project description'):
    """Create a project the way views.add_project does: initial release 0.0 + Default ValSet."""
    release = make_release(owner, desc='Initial release for project ' + name)
    project = Project.objects.create(name=name, desc=desc, cats=cats, owner=owner, release=release)
    ValSet.objects.create(project=project, name='Default', desc='Default ValSet')
    return project


def default_val_set(project):
    return ValSet.objects.get(project=project, name='Default')


def make_val_set(project, name='VS1', desc='Alternative value set'):
    return ValSet.objects.create(project=project, name=name, desc=desc)


def make_project_user(project, user, role='RO'):
    return ProjectUser.objects.create(project=project, user=user, role=role)


def make_application(project, name='App', cats='', desc='Application description'):
    release = make_release(project.owner, project_version=project.release.project_version,
                           desc='Initial release for application ' + name)
    return Application.objects.create(name=name, desc=desc, cats=cats, project=project,
                                      release=release)


def make_spec_item(project, cat='DataItem', domain='Dom', name='Item', owner=None,
                   val_set=None, application=None, status='NEW', **fields):
    fields.setdefault('title', 'Title of ' + name)
    fields.setdefault('updated_at', FIXED_TIME)
    fields.setdefault('created_at', FIXED_TIME)
    return SpecItem.objects.create(
        cat=cat, domain=domain, name=name, project=project, application=application,
        owner=owner or project.owner, val_set=val_set or default_val_set(project),
        status=status, **fields)
