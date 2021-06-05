from django.core.exceptions import ObjectDoesNotExist
from editor.models import ProjectUser
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


def can_add_val_set(request):
    """ Return True if user is admin """
    if request.user.is_staff:
        return True
    else:
        messages.error(request, 'This operation is only accessible to a staff user')
        return False

