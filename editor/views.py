from django.shortcuts import render

from django.contrib import messages
from django.shortcuts import render, redirect
from django.forms import formset_factory                                 
from editor.models import Project, ProjectUser, Application, Release
from django.views import generic
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib.auth import update_session_auth_hash, get_user
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.forms.models import model_to_dict
from django.core.exceptions import ObjectDoesNotExist
from zipfile import ZipFile 
from datetime import datetime
from itertools import chain
import cexprtk
import logging

base_url = '/editor'
logger = logging.getLogger(__name__)


def index(request):
    projects = Project.objects.order_by('name').all()
    listOfProjects = []
    userRequestName = str(request.user)     
    for project in projects:
        projectUsers = ProjectUser.objects.filter(project_id=project.id)
        userHasAccess = ProjectUser.objects.filter(project_id=project.id).filter(user__username__contains=userRequestName).exists()
            
        applications = Application.objects.order_by('name').filter(project_id=project.id)
        default_val_set_id = ValSet.objects.filter(project_id=project.id).get(name='Default').id
        listOfApplications = []
        for application in applications:
            listOfApplications.append(application)
        listOfProjects.append({'project': project, 
                               'applications': listOfApplications,
                               'default_val_set_id': default_val_set_id,
                               'user_has_access': userHasAccess})

    context = {'list_of_projects': listOfProjects}
    return render(request, 'index.html', context=context)
 

def help(request):
    """Help function for home page of CordetFwEditor site"""
    context = {'project_name': 'n.a.'}
    return render(request, 'help.html', context=context)

