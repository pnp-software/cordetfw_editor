from django.shortcuts import render

from django.contrib import messages
from django.shortcuts import render, redirect
from django.forms import formset_factory                                 
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

from editor.models import Project, ProjectUser, Application, Release, ValSet, SpecItem
from editor.forms import ApplicationForm, ProjectForm, ValSetForm, ReleaseForm
from editor.utilities import get_domains, do_application_release, do_project_release, \
                             get_previous_list
from .access import is_project_owner, has_access_to_project, has_access_to_application, \
                    is_spec_item_owner, can_create_project

import cexprtk
import logging

base_url = '/editor'
logger = logging.getLogger(__name__)

config_list = {'Requirement':{'name': 'Requirement',
                              'title': 'List of Requirements',
                              'has_children': False,
                              'child_cat': '',
                              'cols': {'Name': 'ver_method', 'Label': 'Ver'}
                             },
               'DataItemType': {'name': 'Data Item Type',
                                'title': 'List of Requirements',
                                'has_children': True,
                                'child_cat': 'EnumItem',
                                'cols': {}
                               },
               'DataItem': {'name': 'Data Item',
                            'title': 'List of Requirements',
                            'has_children': False,
                            'child_cat': '',
                            'cols': {}
                           }
              }


def index(request):
    projects = Project.objects.order_by('name').all()
    listOfProjects = []
    userRequestName = str(request.user)     
    for project in projects:
        userHasAccess = ProjectUser.objects.filter(project_id=project.id).\
                                        filter(user__username__contains=userRequestName).exists()
         
        applications = project.applications.all().order_by('name') 
        default_val_set_id = ValSet.objects.filter(project_id=project.id).get(name='Default').id
        listOfProjects.append({'project': project, 
                               'applications': list(applications),
                               'default_val_set_id': default_val_set_id,
                               'user_has_access': userHasAccess})
    context = {'list_of_projects': listOfProjects}
    return render(request, 'index.html', context=context)
 

def help(request):
    """Help function for home page of CordetFwEditor site"""
    context = {'project_name': 'n.a.'}
    return render(request, 'help.html', context=context)


@login_required         
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Important!
            messages.success(request, 'Your password was successfully updated!')
            return redirect('change_password')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = PasswordChangeForm(request.user)


@login_required         
def add_application(request, project_id):
    project = Project.objects.get(id=project_id)
    if not is_project_owner(request.user, project):
        return redirect(base_url)
    
    if request.method == 'POST':    # Bind form to posted data 
        form = ApplicationForm(request.POST)
        if form.is_valid():
            new_application = Application(name = form.cleaned_data['name'],
                                          desc = form.cleaned_data['description'],
                                          project = project)
            do_application_release(request, new_application, "Initial Release")
            new_application.save()
            return redirect(base_url)
    else:   
        form = ApplicationForm()

    context = {'form': form, 'project': project, 'title': 'Add Application to Project '+project.name, }
    return render(request, 'basic_form.html', context)    

@login_required         
def add_project(request):
    if not can_create_project(request.user):
        return redirect(base_url)
    
    if request.method == 'POST':    
        form = ProjectForm(request.POST)
        if form.is_valid():
            new_project = Project(name = form.cleaned_data['name'],
                                  desc = form.cleaned_data['description'],
                                  updated_at = datetime.now(),
                                  owner = form.cleaned_data['owner'])
            new_release = Release(desc = "Initial release after project creation",
                          release_author = get_user(request),
                          updated_at = datetime.now(),
                          application_version = 0,
                          project_version = 0,
                          previous = None)
            default_val_set = ValSet(desc = 'Default ValSet',
                                     updated_at = datetime.today(),
                                     project = new_project,
                                     name = 'Default')
            new_release.save()
            new_project.release = new_release
            new_project.save()
            default_val_set.save()
            return redirect(base_url)
    else:   
        form = ProjectForm()

    context = {'form': form, 'title': 'Add New Project', }
    return render(request, 'basic_form.html', context)    


@login_required         
def edit_project(request, project_id):
    if not can_create_project(request.user):
        return redirect(base_url)
    project = Project.objects.get(id=project_id)
    
    # Handle case where edit_project is invoked to add a new user to the project 
    user_id = request.GET.get('user_id')
    if user_id != None:     
        if not ProjectUser.objects.filter(project_id=project_id, user_id=user_id).exists():
            new_project_user = ProjectUser(updated_at = datetime.now(),
                                           user = User.objects.get(id=user_id),
                                           project = project)
            new_project_user.save()
    
    # Handle case where edit_project is invoked to delete a user from the project 
    del_user_id = request.GET.get('del_user_id')
    if del_user_id != None:     
        ProjectUser.objects.filter(id=del_user_id).delete()

    # Handle case where edit_project is invoked to delete a ValSet from the project 
    del_val_set_id = request.GET.get('del_val_set_id')
    if del_val_set_id != None:     
        try:
            DataItemValSet.objects.filter(id=del_val_set_id).delete()    
        except Exception as e:
            messages.error(request, 'Failure to delete ValSet with id '+str(del_val_set_id)+', possibly because it is still in use: '+repr(e))

    if request.method == 'POST':    # Bind form to posted data 
        form = ProjectForm(request.POST)
        if form.is_valid():
            project.name = form.cleaned_data['name']
            project.desc = form.cleaned_data['description']
            project.owner = form.cleaned_data['owner']
            project.save()
            return redirect(base_url)
    else:   
        form = ProjectForm(initial={'name': project.name, 
                                    'description': project.desc, 
                                    'owner': project.owner})
    
    users = User.objects.all().order_by('username').values()
    project_users = list(ProjectUser.objects.filter(project_id=project_id))
    val_sets = list(ValSet.objects.filter(project_id=project_id))
    context = {'form': form, 'title': 'Edit Project '+project.name, }
    return render(request, 'basic_form.html', context)    


@login_required         
def edit_application(request, application_id):
    application = Application.objects.get(id = application_id)
    project = application.project
    if not is_project_owner(request.user, project):
        return redirect(base_url)
    
    if request.method == 'POST':    
        form = ApplicationForm(request.POST)
        if form.is_valid():
            application.name = form.cleaned_data['name']
            application.desc = form.cleaned_data['description']
            application.save()
            return redirect(base_url)
    else:   
        form = ApplicationForm(initial={'name': application.name, 'description': application.desc})
    
    context = {'form': form, 'title': 'Edit Application '+application.name, }
    return render(request, 'basic_form.html', context)    


@login_required         
def make_project_release(request, project_id):
    project = Project.objects.get(id=project_id)
    if not is_project_owner(request.user, project):
        return redirect(base_url)
    
    if request.method == 'POST':    
        form = ReleaseForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['description'].strip() != '':
                do_project_release(request, project, form.cleaned_data['description'])
                return redirect(base_url)
    else:   
        form = ReleaseForm()
            
    context = {'form': form, 'releases': get_previous_list(project.release), 'entity_being_released': project}
    return render(request, 'make_release.html', context)   


@login_required         
def make_application_release(request, application_id):
    application = Application.objects.get(id=application_id)
    if not is_project_owner(request.user, application.project):
        return redirect(base_url)
    
    if request.method == 'POST':    
        form = ReleaseForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['description'].strip() != '':
                do_application_release(request, application, form.cleaned_data['description'])
                return redirect(base_url)
    else:   
        form = ReleaseForm()
        
    context = {'form': form, 'releases': get_previous_list(application.release), 'entity_being_released': application}
    return render(request, 'make_release.html', context)   


@login_required         
def list_spec_items(request, cat, project_id, application_id, val_set_id, sel_dom):
    # If application_id is zero, then the items to be listed are 'project items'; otherwise they are 'application items'
    project = Project.objects.get(id=project_id)
    if not has_access_to_project(request.user, project):
        return redirect(base_url)
    
    if (application_id == 0):
        items = SpecItem.objects.filter(project_id=project_id).filter(cat=cat).filter(val_set_id=val_set_id).order_by('domain','name') 
    else:
        items = SpecItem.objects.filter(application_id=application_id).filter(cat=cat).filter(val_set_id=val_set_id).order_by('domain','name') 
        
    if (sel_dom != "All_Domains"):
        items = items.filter(domain=sel_dom)

    domains = get_domains(cat, application_id, project_id) 
    val_sets = ValSet.objects.filter(project_id=project_id).order_by('name')
    context = {'items': items, 'project': project, 'application_id': application_id, 'domains': domains, 'sel_dom': sel_dom,\
               'val_set_id':val_set_id, 'val_sets':val_sets, 'config':config_list[cat], 'cat':cat}
    return render(request, 'list_spec_items.html', context)    


@login_required         
def add_spec_item(request, cat, project_id, application_id, sel_dom):
    # TBD
    redirect_url = '/editor/'
    return redirect(redirect_url)


@login_required         
def edit_spec_item(request, cat, project_id, application_id, item_id, sel_dom):
    # TBD
    redirect_url = '/editor/'
    return redirect(redirect_url)


@login_required         
def copy_spec_item(request, cat, project_id, application_id, item_id, sel_dom):
    # TBD
    redirect_url = '/editor/'
    return redirect(redirect_url)


@login_required         
def del_spec_item(request, cat, project_id, application_id, item_id, sel_dom):
    # TBD
    redirect_url = '/editor/'
    return redirect(redirect_url)


@login_required         
def export_spec_items(request, cat, project_id, application_id, val_set_id, sel_dom):
    # TBD
    redirect_url = '/editor/'
    return redirect(redirect_url)


@login_required         
def export_project(request, project_id):
    # TBD
    redirect_url = '/editor/'
    return redirect(redirect_url)
