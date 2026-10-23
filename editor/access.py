from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.shortcuts import get_object_or_404
from editor.models import ProjectUser, SpecItem, Application, ValSet, Release
from django.contrib import messages


def is_project_owner(request, project):
    """ Return True if user owns the project """
    if request.user.id == project.owner.id:
        return True
    else:
        messages.error(request, 'This operation is only accessible to the owner of project '+project.name)
        return False


def has_read_access_to_project(request, project):
    """ Return True if user owns the project or is assigned to it """
    if (request.user.id == project.owner.id) or (ProjectUser.objects.\
                filter(user_id=request.user.id, project_id=project.id).exists()):
        return True
    else:
        messages.error(request, 'This operation requires read access to project '+project.name)
        return False


def user_has_write_access_to_project(user_id, project):
    """ Silent variant of has_write_access_to_project (same logic, no message queued) """
    if user_id == project.owner.id:
        return True
    try:
        user = ProjectUser.objects.filter(user_id=user_id, project_id=project.id)
        return user[0].role == 'RW'
    except Exception:
        return False


def has_write_access_to_project(request, project):
    """ Return True if user owns the project or is assigned to it with read/write access """
    if (request.user.id == project.owner.id):
        return True
    try:
        user = ProjectUser.objects.filter(user_id=request.user.id, project_id=project.id)
        if user[0].role == 'RW':
            return True
        else:
            messages.error(request, 'This operation requires read/write access to project '+project.name)
            return False
    except Exception as e:
        messages.error(request, 'This operation requires read/write access to project '+project.name)
        return False


def can_create_project(request):
    """ Return True if user is admin """
    if request.user.is_staff:
        return True
    else:
        messages.error(request, 'This operation is only accessible to a staff user')
        return False


def can_repair(request):
    """ Return True if user is admin """
    if request.user.is_staff:
        return True
    else:
        messages.error(request, 'This operation is only accessible to a staff user')
        return False


def can_add_val_set(request):
    """ Return True if user is admin """
    if request.user.is_staff:
        return True
    else:
        messages.error(request, 'This operation is only accessible to a staff user')
        return False



# ---------------------------------------------------------------------------------------------
# Object lookups scoped to the project whose access was checked (Task 6.4). An id taken from the
# URL, GET or POST that does not belong to the project gives a 404 and never touches the object.
# ---------------------------------------------------------------------------------------------

def get_spec_item_in_project_or_404(project, item_id):
    """ Return the SpecItem with the argument id if it belongs to the project; otherwise raise Http404 """
    return get_object_or_404(SpecItem, id=item_id, project_id=project.id)


def get_application_in_project_or_404(project, application_id):
    """ Return None if application_id is zero, else the Application of the project or raise Http404 """
    if application_id == 0:
        return None
    return get_object_or_404(Application, id=application_id, project_id=project.id)


def get_val_set_in_project_or_404(project, val_set_id):
    """ Return the ValSet with the argument id if it belongs to the project; otherwise raise Http404 """
    return get_object_or_404(ValSet, id=val_set_id, project_id=project.id)


def get_release_for_project_or_404(project, application, sel_rel_id):
    """
    Return None if sel_rel_id is zero. Otherwise return the release if it is in the chain of
    previous releases of the project (or, if an application is given, of the application);
    else raise Http404.
    """
    if sel_rel_id == 0:
        return None
    release = project.release
    while release is not None:
        if release.id == sel_rel_id:
            return release
        release = release.previous
    if application is not None:
        release = application.release
        while release is not None:
            if release.id == sel_rel_id:
                return release
            release = release.previous
    raise Http404('No such release in this project')


def check_parents_in_project_or_404(project, s_parent_id, p_parent_id):
    """
    Verify that s_parent_id and p_parent_id (strings from the query string or None) identify
    spec_items of the project. Return the pair (s_parent, p_parent) (None for an absent id).
    """
    parents = []
    for parent_id in (s_parent_id, p_parent_id):
        if parent_id is None:
            parents.append(None)
            continue
        try:
            parent_id = int(parent_id)
        except ValueError:
            raise Http404('Invalid parent id')
        parents.append(get_spec_item_in_project_or_404(project, parent_id))
    return parents[0], parents[1]


def val_set_name_is_default_in_db(project, name, exclude_id=None):
    """
    Return True if the database (column collation) considers name equal to the name of a Default
    ValSet of the project. On MySQL with utf8mb4_unicode_ci this catches 'Défault' and full-width
    variants that the Python comparison in is_default_val_set_name misses; on SQLite it only
    matches the exact string.
    """
    return ValSet.objects.filter(project_id=project.id, name=name).filter(name='Default') \
        .exclude(id=exclude_id).exists()


def is_default_val_set_name(name):
    """ Return True if the name is that of the Default ValSet (compared like a case-insensitive MySQL collation) """
    return name.strip().lower() == 'default'
