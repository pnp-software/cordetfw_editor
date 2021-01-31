from django.core.exceptions import ObjectDoesNotExist
from editor.models import ProjectUser


def is_project_owner(user, project):
    """ Return True if user owns the project """
    return (user.id == project.owner.id) 


def has_access_to_project(user, project):
    """ Return True if user owns the project or is assigned to it """
    return (user.id == project.owner.id) or (ProjectUser.objects.filter(user_id=user.id, project_id=project.id).exists())
    

def has_access_to_application(user, application):
    """ Return True if user is assigned to or owns the project to which the application belongs """
    return (ProjectUser.objects.filter(user_id=user.id, project_id=application.project.id).exists()) or \
           (application.project.owner == user)
    

def is_spec_item_owner(user, item):
    """ Return True if user owns the specification item """
    return (user == item.owner) 


def can_create_project(user):
    """ Return True if user is admin """
    return (user.is_staff) 


def can_add_val_set(user):
    """ Return True if user is admin """
    return (user.is_staff) 

