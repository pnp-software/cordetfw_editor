import os
import csv
import traceback
import json

from io import StringIO
from zipfile import ZipFile 
from datetime import datetime
from tablib import Dataset
from itertools import chain
from zipfile import ZipFile
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
from django.core.exceptions import ObjectDoesNotExist
from django.forms.models import model_to_dict
from django.core.paginator import Paginator
from django.http import FileResponse
from django.utils.timezone import get_current_timezone
from django.db.models import OuterRef, Subquery

from editor.configs import configs
from editor.models import Project, ProjectUser, Application, Release, ValSet, SpecItem
from editor.forms import ApplicationForm, ProjectForm, ValSetForm, ReleaseForm, SpecItemForm, FindReplaceForm
from editor.utilities import get_domains, do_application_release, do_project_release, \
                             get_previous_list, spec_item_to_edit, spec_item_to_latex, \
                             spec_item_to_export, export_to_spec_item, get_expand_items, \
                             get_redirect_url, make_temp_dir, get_default_val_set_id, \
                             del_release, list_trac_items_for_latex, make_obs_spec_item_copy, \
                             mark_spec_item_aliases_as_del, create_and_init_spec_item, \
                             remove_spec_item, update_dom_name_in_val_set, remove_spec_item_aliases, \
                             get_spec_item_query
from editor.imports import import_project_tables
from editor.resources import ProjectResource, ApplicationResource, ProjectUserResource, \
                             ValSetResource, SpecItemResource, ReleaseResource
from editor.ext_cats import ext_model_refresh
from editor.access import is_project_owner, has_read_access_to_project, \
                    can_create_project, can_add_val_set, has_write_access_to_project, \
                    can_repair

import cexprtk
import logging
    
with open('/etc/dj_cordetfw_config.json') as config_file:
    config = json.load(config_file)
    
base_url = config['BASE_URL']
logger = logging.getLogger(__name__)

def index(request):
    projects = Project.objects.order_by('name').all()
    listOfProjects = []
    userRequestName = str(request.user)     
    for project in projects:
        userHasAccess = ProjectUser.objects.filter(project_id=project).\
                                        filter(user__username__contains=userRequestName).exists()
         
        applications = project.applications.all().order_by('name') 
        default_val_set_id = get_default_val_set_id(request, project)
        
        # Create iterable holding the names of the categories for this project
        project_cats = list(map(lambda x: x.strip(), project.cats.split(',')))
        # Create a subset of configs['cats'] holding only the project categories
        project_configs = {key: value for key, value in configs['cats'].items() if key in project_cats}
        
        listOfProjects.append({'project': project, 
                               'applications': list(applications),
                               'default_val_set_id': default_val_set_id,
                               'project_configs': project_configs,
                               'user_has_access': userHasAccess})
    context = {'list_of_projects': listOfProjects}
    return render(request, 'index.html', context=context)
 

def help(request):
    """Help function for home page of CordetFwEditor site"""
    context = {'project_name': 'n.a.'}
    return render(request, 'help.html', context=context)


@login_required  
def repair(request):
    """Repair database"""
    if not can_repair(request):
        return redirect(base_url)
    messages.warning(request, 'Nothing to repair')
    return redirect(base_url)


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
            messages.error(request, 'Please correct the error below')
    else:
        form = PasswordChangeForm(request.user)


@login_required         
def add_application(request, project_id):
    project = Project.objects.get(id=project_id)
    if not is_project_owner(request, project):
        return redirect(base_url)
    
    if request.method == 'POST':    # Bind form to posted data 
        form = ApplicationForm(project, request.POST)
        if form.is_valid():
            new_application = Application(name = form.cleaned_data['name'],
                                          desc = form.cleaned_data['description'],
                                          cats = form.cleaned_data['cats'],
                                          project = project)
            do_application_release(request, new_application, "Initial release for application " \
                                   + new_application.name)
            new_application.save()
            return redirect(base_url)
    else:   
        form = ApplicationForm(project)

    context = {'form': form, 'project': project, 'title': 'Add Application to Project '+project.name, }
    return render(request, 'generic_form.html', context)    

@login_required         
def add_project(request):
    if not can_create_project(request):
        return redirect(base_url)
    
    if request.method == 'POST':    
        form = ProjectForm(None, request.POST)
        if form.is_valid():
            new_project = Project(name = form.cleaned_data['name'],
                                  desc = form.cleaned_data['description'],
                                  cats = form.cleaned_data['cats'],
                                  updated_at = datetime.now(tz=get_current_timezone()),
                                  owner = form.cleaned_data['owner'])
            new_release = Release(desc = "Initial release for project " + new_project.name,
                                  release_author = get_user(request),
                                  updated_at = datetime.now(tz=get_current_timezone()),
                                  application_version = 0,
                                  project_version = 0,
                                  previous = None)
            new_release.save()
            new_project.release = new_release
            new_project.save()
            default_val_set = ValSet(desc = 'Default ValSet',
                                     updated_at = datetime.today(),
                                     project = new_project,
                                     name = 'Default')
            default_val_set.save()
            return redirect(base_url)
    else:   
        form = ProjectForm(None)

    context = {'form': form, 'title': 'Add New Project', }
    return render(request, 'generic_form.html', context)    


@login_required         
def edit_project(request, project_id):
    if not can_create_project(request):
        return redirect(base_url)
    project = Project.objects.get(id=project_id)
    
    # Handle case where edit_project is invoked to add a new user to the project or to change its role.
    # If the new user is not yet attached to the project, it is added to it in the specified role.
    # If the specified user is already attached to the project, it is checked whether it is necessary
    # to change its role
    user_id = request.GET.get('user_id')
    user_role = request.GET.get('role')
    if user_id != None:    
        user =  ProjectUser.objects.filter(project_id=project_id, user_id=user_id)
        if not ProjectUser.objects.filter(project_id=project_id, user_id=user_id).exists():
            new_project_user = ProjectUser(updated_at = datetime.now(tz=get_current_timezone()),
                                           user = User.objects.get(id=user_id),
                                           project = project,
                                           role = user_role)
            new_project_user.save()
        else:
            user =  ProjectUser.objects.get(project_id=project_id, user_id=user_id)
            if user.role != user_role:
                user.role = user_role
                user.save()
    
    # Handle case where edit_project is invoked to delete a user from the project 
    del_user_id = request.GET.get('del_user_id')
    if del_user_id != None:     
        ProjectUser.objects.filter(id=del_user_id).delete()

    # Handle case where edit_project is invoked to delete a ValSet from the project 
    del_val_set_id = request.GET.get('del_val_set_id')
    if del_val_set_id != None:     
        try:
            ValSet.objects.filter(id=del_val_set_id).delete()    
        except Exception as e:
            messages.error(request, 'Failure to delete ValSet with id '+str(del_val_set_id)+\
                                    ', possibly because it is still in use: '+repr(e))

    if request.method == 'POST':    # Bind form to posted data 
        form = ProjectForm(project, request.POST)
        if form.is_valid():
            project.name = form.cleaned_data['name']
            project.desc = form.cleaned_data['description']
            project.owner = form.cleaned_data['owner']
            project.cats = form.cleaned_data['cats']
            project.save()
            return redirect(base_url)
    else:   
        form = ProjectForm(project, initial={'name': project.name, 
                                             'description': project.desc, 
                                             'cats': project.cats,
                                             'owner': project.owner})
    
    users = User.objects.all().exclude(username=project.owner).order_by('username').values()
    project_users = list(ProjectUser.objects.filter(project_id=project_id))
    val_sets = list(ValSet.objects.filter(project_id=project_id))
    context = {'form': form, 'project': project, 'users': users, \
                'project_users': project_users, 'val_sets': val_sets}
    return render(request, 'edit_project.html', context)    


@login_required         
def del_project(request, project_id):
    if not can_create_project(request):
        return redirect(base_url)
    project = Project.objects.get(id=project_id)
    
    project_release = project.release
    
    spec_items = SpecItem.objects.filter(project_id=project_id)
    for spec_item in spec_items:    # Remove all cross-references between spec_items
        spec_item.p_link = None
        spec_item.s_link = None
        spec_item.previous = None
        spec_item.save()
    SpecItem.objects.filter(project_id=project_id).delete()
    
    ValSet.objects.filter(project_id=project_id).delete()
    applications = Application.objects.filter(project_id=project_id)
    for application in applications:
        application_release = application.release
        application.delete()
        del_release(request, application_release, 1)
        
    ProjectUser.objects.filter(project_id=project_id).delete()
    Project.objects.filter(id=project_id).delete()
    del_release(request, project_release, 1)

    return redirect(base_url)    


@login_required
def edit_application(request, application_id):
    application = Application.objects.get(id = application_id)
    project = application.project
    if not is_project_owner(request, project):
        return redirect(base_url)

    if request.method == 'POST':
        form = ApplicationForm(project, request.POST)
        if form.is_valid():
            application.name = form.cleaned_data['name']
            application.desc = form.cleaned_data['description']
            application.cats = form.cleaned_data['cats']
            application.save()
            return redirect(base_url)
    else:
        form = ApplicationForm(project, initial={'name': application.name,
                                                 'description': application.desc,
                                                 'cats': application.cats})

    context = {'form': form, 'title': 'Edit Application '+application.name, }
    return render(request, 'generic_form.html', context)


@login_required         
def make_project_release(request, project_id):
    project = Project.objects.get(id=project_id)
    if not is_project_owner(request, project):
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
    if not is_project_owner(request, application.project):
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
def add_val_set(request, project_id):
    project = Project.objects.get(id=project_id)
    if not can_add_val_set(request):
        return redirect(base_url)
    
    redirect_url = '/editor/'+str(project_id)+'/edit_project'
    if request.method == 'POST':    
        form = ValSetForm(request.POST)
        if form.is_valid():
            new_val_set = ValSet(name = form.cleaned_data['name'],
                                 desc = form.cleaned_data['description'],
                                 project = project,
                                 updated_at = datetime.now(tz=get_current_timezone()))
            new_val_set.save()
            return redirect(redirect_url)
    else:   
        form = ValSetForm()

    context = {'form': form, 'project': project, 'title': 'Add ValSet to Project '+project.name}
    return render(request, 'generic_form.html', context)    

@login_required         
def edit_val_set(request, project_id, val_set_id):
    project = Project.objects.get(id=project_id)
    val_set = ValSet.objects.get(id=val_set_id)
    if not can_add_val_set(request):
        return redirect(base_url)
    
    redirect_url = '/editor/'+str(project_id)+'/edit_project'
    if request.method == 'POST':    
        form = ValSetForm(request.POST)
        if form.is_valid():
            val_set.name = form.cleaned_data['name']
            val_set.desc = form.cleaned_data['description']
            val_set.updated_at = datetime.now(tz=get_current_timezone())
            val_set.save()
            return redirect(redirect_url)
    else:   
        form = ValSetForm(initial={'name': val_set.name, 'description': val_set.desc})

    context = {'form': form, 'project': project, 'title': 'Edit ValSet '+val_set.name}
    return render(request, 'generic_form.html', context)    


@login_required         
def list_spec_items(request, cat, project_id, application_id, val_set_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    if not has_read_access_to_project(request, project):
        return redirect(base_url)

    val_set = ValSet.objects.get(id=val_set_id)
    val_sets = ValSet.objects.filter(project_id=project_id).order_by('name')
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    get_parameter_sting = '?'
    expand_id = request.GET.get('expand_id')
    if expand_id is not None:
        get_parameter_sting += 'expand_id=' + str(expand_id) + '&'
    expand_link = request.GET.get('expand_link')
    if expand_link is not None:
        get_parameter_sting += 'expand_link=' + str(expand_link) + '&'
    disp = 'disp_def' if (request.GET.get('disp') == None) else request.GET.get('disp')
    if disp is not None:
        get_parameter_sting += 'disp=' + str(disp) + '&'
    order_by = request.GET.get('order_by')
    if order_by is not None:
        get_parameter_sting += 'order_by=' + str(order_by) + '&'
    n_pad_fields = range(len(configs['cats'][cat][disp])-3)

    # Get selected release object and the list of previous releases
    if sel_rel_id != 0:
        sel_rel = Release.objects.get(id=sel_rel_id)    # Release to be displayed
    else:
        sel_rel = None
    releases = get_previous_list(project.release)       # Only project releases are handled

    # Prepare data for dropdown in header through which users can access
    # the list of all project and applications spec_items
    breadcrumb = {}
    breadcrumb['rest'] = []
    drop_down_items = []
    project_cats = list(map(str.strip, project.cats.split(',')))
    for cat_item in project_cats:
        if (cat_item == cat and application_id == 0) or configs['cats'][cat_item]['access_from_index']['level'] != 'Project':
            continue
        drop_down_item = {}
        if application_id == 0:
            list_as = configs['cats'][cat_item]['name']
        else:
            list_as = project.name + ' / ' + configs['cats'][cat_item]['name']
        drop_down_item['list_as'] = list_as
        drop_down_item['spec_item'] = cat_item
        drop_down_item['project_id'] = project_id
        drop_down_item['application_id'] = 0
        drop_down_item['val_set_id'] = default_val_set.id
        drop_down_item['domain_id'] = sel_val
        drop_down_items.append(drop_down_item)
    if application_id == 0:
        breadcrumb['active'] = drop_down_items
    else:
        breadcrumb['rest'] = drop_down_items
    applications = project.applications.all().order_by('name')
    for application_item in applications:
        drop_down_items = []
        application_cats = list(map(str.strip, application_item.cats.split(',')))
        if application_cats == ['']:    # There are no categories in this application
            continue
        for cat_item in application_cats:
            if (cat_item == cat and application_id == application_item.id) or configs['cats'][cat_item]['access_from_index']['level'] != 'Application':
                continue
            drop_down_item = {}
            if application_id == application_item.id:
                list_as = configs['cats'][cat_item]['name']
            else:
                list_as = project.name + ' / ' + application_item.name + ' / ' + configs['cats'][cat_item]['name']
            drop_down_item['list_as'] = list_as
            drop_down_item['spec_item'] = cat_item
            drop_down_item['project_id'] = project_id
            drop_down_item['application_id'] = application_item.id
            drop_down_item['val_set_id'] = default_val_set.id
            drop_down_item['domain_id'] = sel_val
            drop_down_items.append(drop_down_item)
        if application_id == application_item.id:
            breadcrumb['application_name_active'] = application_item.name
            breadcrumb['active'] = drop_down_items
        else:
            breadcrumb['rest'] += drop_down_items

    # Create list of items to be displayed
    items = get_spec_item_query(project_id, application_id, val_set_id, cat, sel_rel, sel_val, order_by)
                             
    if (expand_id != None) and (expand_link != 'None'):   # parent_id must be listed together with its children
        expand_items = get_expand_items(cat, project_id, val_set_id, expand_id, expand_link)     
        expand_id = int(expand_id)      # Cast is necessary for comparison to spec_item_id in list_spec_items.html
    else:
        expand_items = None

    # Find & Replace (POST form)
    if request.method == 'POST':
        form = FindReplaceForm(request.POST)
        if form.is_valid():
            field_to_search = form.cleaned_data['field']
            find_string = form.cleaned_data['find']
            replace_string = form.cleaned_data['replace']
            if field_to_search in configs['cats'][cat]['attrs'].keys():
                fields_to_check = items.values('id', field_to_search)
                for field_to_check in fields_to_check:
                    if find_string in field_to_check[field_to_search]:
                        new_value = field_to_check[field_to_search].replace(find_string, replace_string)
                        update_spec_item = SpecItem.objects.get(id=field_to_check['id'])
                        setattr(update_spec_item, field_to_search, new_value)
                        update_spec_item.updated_at = datetime.now(tz=get_current_timezone())
                        update_spec_item.owner = get_user(request)
                        update_spec_item.save()

    domains = get_domains(cat, application_id, project_id)

    # Pagination
    paginator_items = Paginator(items, configs['cats'][cat]['page_size'])
    page_number = 1
    if 'page' in request.GET:
        page_number = int(request.GET.get('page'))
    page_items = paginator_items.page(page_number)
    previous_page = None
    if page_items.has_previous():
        previous_page = page_items.previous_page_number()
    next_page = None
    if page_items.has_next():
        next_page = page_items.next_page_number()
    pagination = {
        'page_number': page_number,
        'has_previous': page_items.has_previous(),
        'previous_page': previous_page,
        'has_next': page_items.has_next(),
        'next_page': next_page,
        'page_list': paginator_items.get_elided_page_range(page_number)
    }
    
    context = {
        'page_items': page_items, 
        'pagination': pagination, 
        'project': project,
        'application_id': application_id, 
        'domains': domains,
        'sel_val': sel_val, 
        'val_set': val_set, 
        'val_sets': val_sets,
        'default_val_set_id': default_val_set.id,
        'config': configs['cats'][cat], 
        'cat': cat, 
        'breadcrumb': breadcrumb,
        'expand_id': expand_id, 
        'expand_items': expand_items,
        'expand_link': expand_link, 
        'n_pad_fields': n_pad_fields, 
        'disp': disp,
        'disp_list': configs['cats'][cat][disp], 
        'history': False,
        'find_replace_fields': configs['cats'][cat]['attrs'],
        'order_by': order_by, 
        'sel_rel': sel_rel,
        'sel_rel_id': sel_rel_id,
        'releases': releases,
        'get_parameter_sting': get_parameter_sting
    }
    return render(request, 'list_spec_items.html', context)    


@login_required         
def add_spec_item(request, cat, project_id, application_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    s_parent_id = request.GET.get('s_parent_id')
    p_parent_id = request.GET.get('p_parent_id')
    if not has_write_access_to_project(request, project):
        return redirect(base_url)

    if application_id != 0:
        application = Application.objects.get(id=application_id)
        title = 'Add '+configs['cats'][cat]['name']+' to Application '+application.name
    else:
        application = None
        title = 'Add '+configs['cats'][cat]['name']
        
    sub_title = ''    
    if (s_parent_id != None):
        s_parent = SpecItem.objects.get(id=s_parent_id)
        sub_title = sub_title + configs['cats'][cat]['attrs']['s_link']['label'] + ' ' + str(s_parent)     
    if (p_parent_id != None):
        p_parent = SpecItem.objects.get(id=p_parent_id)
        sub_title = sub_title + configs['cats'][cat]['attrs']['s_link']['label'] + ' ' + str(p_parent)     
        
    if request.method == 'POST':   
        form = SpecItemForm('add', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, request.POST)
        if form.is_valid():
            new_spec_item = create_and_init_spec_item(request, cat, form.cleaned_data)
            new_spec_item.cat = cat
            new_spec_item.val_set = default_val_set
            new_spec_item.updated_at = datetime.now(tz=get_current_timezone())
            new_spec_item.created_at = datetime.now(tz=get_current_timezone())
            new_spec_item.owner = get_user(request)
            new_spec_item.status = 'NEW'
            new_spec_item.project = project
            new_spec_item.application = application
            new_spec_item.save()
            redirect_url = get_redirect_url(cat, project_id, application_id, default_val_set.id,\
                                            sel_val, sel_rel_id, s_parent_id, p_parent_id, new_spec_item)
            return redirect(redirect_url)
    else:   
        form = SpecItemForm('add', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id)

    spec_items = SpecItem.objects.filter(project_id=project_id, val_set=default_val_set.id).\
                        exclude(status='DEL').exclude(status='OBS').order_by('cat','domain','name')
    context = {'form': form, 'project': project, 'title': title, 'sub_title': sub_title, \
               'sel_val': sel_val, 'config': configs['cats'][cat], 'cat': cat, 'spec_items': spec_items}
    return render(request, 'spec_item_form.html', context)  


@login_required         
def edit_spec_item(request, cat, project_id, application_id, item_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    s_parent_id = request.GET.get('s_parent_id')
    p_parent_id = request.GET.get('p_parent_id')
    if application_id != 0:
        application = Application.objects.get(id=application_id)
        title = 'Edit '+configs['cats'][cat]['name']+' in Application '+application.name
    else:
        application = None
        title = 'Edit '+configs['cats'][cat]['name']+' in Project '+project.name
    if not has_write_access_to_project(request, project):
        return redirect(base_url)
  
    spec_item = SpecItem.objects.get(id=item_id)
    if not spec_item.status in ('CNF', 'MOD', 'NEW'):
        messages.error(request, 'Only SpecItems in state CNF, MOD or NEW can be edited ')
        return redirect(base_url)
    
    if request.method == 'POST':   
        form = SpecItemForm('edit', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                            request.POST, initial=spec_item_to_edit(spec_item))
        if form.is_valid():
            if spec_item.status == 'CNF':
                spec_item = make_obs_spec_item_copy(request, spec_item)
            for key, value in form.cleaned_data.items():    # Copy form inputs into spec_item
                setattr(spec_item, key, value)    
            spec_item.updated_at = datetime.now(tz=get_current_timezone())
            spec_item.owner = get_user(request)
            spec_item.save()
            if (spec_item.val_set.name == 'Default') and (('name' in form.changed_data) or ('domain' in form.changed_data)):
                update_dom_name_in_val_set(spec_item)
            redirect_url = get_redirect_url(cat, project_id, application_id, default_val_set.id,\
                                            sel_val, sel_rel_id, s_parent_id, p_parent_id, spec_item)
            return redirect(redirect_url)
    else:   
        initial_spec_item_values = spec_item_to_edit(spec_item)
        if spec_item.status == 'CNF':
            initial_spec_item_values['change_log'] = ''
        form = SpecItemForm('edit', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                            initial=initial_spec_item_values)

    # Generate list of items for the auto-completion list
    spec_items = SpecItem.objects.filter(project_id=project_id, val_set=default_val_set.id).\
                        exclude(status='DEL').exclude(status='OBS')
    query_sets = SpecItem.objects.none()
    for cat in project.cats.split(','):
        query_set = spec_items.filter(cat=cat.strip())
        query_sets = query_sets | query_set
        
    context = {'form': form, 'project': project, 'title': title, 'spec_items': query_sets.order_by('cat','domain','name')}
    return render(request, 'spec_item_form.html', context) 


@login_required         
def refresh_spec_item(request, cat, project_id, application_id, item_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    if not has_write_access_to_project(request, project):
        return redirect(base_url)
    
    spec_item = SpecItem.objects.get(id=item_id)
    refresh_outcome = ext_model_refresh(request, spec_item)
    if refresh_outcome == 'REFRESH':
        if spec_item.status == 'CNF':
            spec_item = make_obs_spec_item_copy(request, spec_item)
        spec_item.updated_at = datetime.now(tz=get_current_timezone())
        spec_item.owner = get_user(request)
        spec_item.save()
    elif refresh_outcome == 'NOT_FOUND':
        messages.warning(request,'External spec_item no longer exists -- no refresh can be done')
    elif refresh_outcome == 'NO_CHANGE':
        messages.warning(request,'External spec_item has not changed -- no refresh needed')
 
    redirect_url = '/editor/'+cat+'/'+str(project_id)+'/'+str(application_id)+'/'+\
                    str(default_val_set.id)+'/'+sel_val+'/'+str(sel_rel_id)+'/list_spec_items#'+spec_item.domain+':'+spec_item.name
    return redirect(redirect_url)
    

@login_required         
def copy_spec_item(request, cat, project_id, application_id, item_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    spec_item = SpecItem.objects.get(id=item_id)
    spec_item.change_log = ''
    s_parent_id = request.GET.get('s_parent_id')
    p_parent_id = request.GET.get('p_parent_id')
    if application_id != 0:
        application = Application.objects.get(id=application_id)
        title = 'Copy '+configs['cats'][cat]['name']+' in Application '+application.name
    else:
        application = None
        title = 'Copy '+configs['cats'][cat]['name']+' in Project '+project.name
    if not has_write_access_to_project(request, project) or (spec_item.val_set.name != 'Default'):
        return redirect(base_url)
    if spec_item.val_set != default_val_set:
        messages.error(request, 'Only SpecItems in default ValSet can be copied ')
        return redirect(base_url)
  
    if request.method == 'POST':   
        form = SpecItemForm('copy', request, cat, project, application, configs['cats'][cat], s_parent_id, \
                            p_parent_id, request.POST, initial=spec_item_to_edit(spec_item))
        if form.is_valid():
            new_spec_item = create_and_init_spec_item(request, cat, form.cleaned_data)
            new_spec_item.cat = cat
            new_spec_item.updated_at = datetime.now(tz=get_current_timezone())
            new_spec_item.created_at = datetime.now(tz=get_current_timezone())
            new_spec_item.owner = get_user(request)
            new_spec_item.project = project
            new_spec_item.application = application
            new_spec_item.status = 'NEW'
            new_spec_item.save()
            redirect_url = get_redirect_url(cat, project_id, application_id, default_val_set.id,\
                                            sel_val, sel_rel_id, s_parent_id, p_parent_id, new_spec_item)
            return redirect(redirect_url)
    else:   
        form = SpecItemForm('copy', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                            initial=spec_item_to_edit(spec_item))

    # Generate list of items for the auto-completion list
    spec_items = SpecItem.objects.filter(project_id=project_id, val_set=default_val_set.id).\
                        exclude(status='DEL').exclude(status='OBS').order_by('cat','domain','name')
    context = {'form': form, 'project': project, 'title': title, 'spec_items': spec_items}
    return render(request, 'spec_item_form.html', context) 

@login_required         
def split_spec_item(request, cat, project_id, application_id, item_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    spec_item = SpecItem.objects.get(id=item_id)
    s_parent_id = request.GET.get('s_parent_id')
    p_parent_id = request.GET.get('p_parent_id')
    if application_id != 0:
        application = Application.objects.get(id=application_id)
        title = 'Split '+configs['cats'][cat]['name']+' in Application '+application.name
    else:
        application = None
        title = 'Split '+configs['cats'][cat]['name']+' in Project '+project.name
    if not has_write_access_to_project(request, project)  or (spec_item.val_set.name != 'Default'):
        return redirect(base_url)
    if not spec_item.status in ('CNF', 'MOD', 'NEW'):
        messages.error(request, 'Only SpecItems in state CNF, MOD or NEW can be split ')
        return redirect(base_url)
  
    if request.method == 'POST':   
        form = SpecItemForm('split', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                             request.POST, initial=spec_item_to_edit(spec_item))
        if form.is_valid():
            new_spec_item = create_and_init_spec_item(request, cat, form.cleaned_data)
            new_spec_item.cat = cat
            new_spec_item.updated_at = datetime.now(tz=get_current_timezone())
            new_spec_item.created_at = datetime.now(tz=get_current_timezone())
            new_spec_item.owner = get_user(request)
            new_spec_item.project = project
            new_spec_item.application = application
            new_spec_item.p_link = spec_item
            new_spec_item.status = 'NEW'
            new_spec_item.save()
            redirect_url = get_redirect_url(cat, project_id, application_id, default_val_set.id,\
                                            sel_val, sel_rel_id, s_parent_id, p_parent_id, new_spec_item)
            return redirect(redirect_url)
    else:   
        form = SpecItemForm('split', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                            initial=spec_item_to_edit(spec_item))

    # Generate list of items for the auto-completion list
    spec_items = SpecItem.objects.filter(project_id=project_id, val_set=default_val_set.id).\
                        exclude(status='DEL').exclude(status='OBS').order_by('cat','domain','name')
    context = {'form': form, 'project': project, 'title': title, 'spec_items': spec_items}
    return render(request, 'spec_item_form.html', context) 


@login_required         
def del_spec_item(request, cat, project_id, application_id, item_id, sel_val, sel_rel_id):
    spec_item = SpecItem.objects.get(id=item_id)
    project = Project.objects.get(id=project_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    s_parent_id = request.GET.get('s_parent_id')
    p_parent_id = request.GET.get('p_parent_id')
    if application_id != 0:
        application = Application.objects.get(id=application_id)
        title = 'Delete '+configs['cats'][cat]['name']+' in Application '+application.name
    else:
        application = None
        title = 'Delete '+configs['cats'][cat]['name']+' in Project '+project.name
    if not has_write_access_to_project(request, project):
        return redirect(base_url)
    if not spec_item.status in ('CNF', 'MOD', 'NEW'):
        messages.error(request, 'Only SpecItems in state CNF, MOD or NEW can be deleted ')
        return redirect(base_url)

    if spec_item.status == 'NEW':
        if spec_item.val_set.name == 'Default':
            remove_spec_item_aliases(request, spec_item)
        remove_spec_item(request, spec_item)
        redirect_url = get_redirect_url(cat, project_id, application_id, default_val_set.id,\
                                                sel_val, sel_rel_id, s_parent_id, p_parent_id, None)
        return redirect(redirect_url)
  
    if request.method == 'POST':   
        form = SpecItemForm('del', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                            request.POST, initial=spec_item_to_edit(spec_item))
        if form.is_valid():
            if spec_item.val_set.name == 'Default':
                mark_spec_item_aliases_as_del(request, spec_item)
            spec_item.status = 'DEL' 
            spec_item.updated_at = datetime.now(tz=get_current_timezone())
            spec_item.owner = get_user(request)
            spec_item.change_log = form.cleaned_data['change_log']
            spec_item.save() 
            redirect_url = get_redirect_url(cat, project_id, application_id, default_val_set.id,\
                                                    sel_val, sel_rel_id, s_parent_id, p_parent_id, None)
            return redirect(redirect_url)
    else:   
        form = SpecItemForm('del', request, cat, project, application, configs['cats'][cat], s_parent_id, p_parent_id, \
                            initial=spec_item_to_edit(spec_item))

    # Generate list of items for the auto-completion list
    spec_items = SpecItem.objects.filter(project_id=project_id, val_set=default_val_set.id).\
                        exclude(status='DEL').exclude(status='OBS').order_by('cat','domain','name')
    context = {'form': form, 'project': project, 'title': title, 'spec_items': spec_items}
    return render(request, 'spec_item_form.html', context) 

        
@login_required         
def export_spec_items(request, cat, project_id, application_id, val_set_id, sel_val, sel_rel_id):
    project = Project.objects.get(id=project_id)
    order_by = request.GET.get('order_by')
    if application_id != 0:
        application = Application.objects.get(id=application_id)
    else:
        application = None
    if not has_read_access_to_project(request, project):
        return redirect(base_url)
    export_type = request.GET.get('export')

    # Get selected release object 
    if sel_rel_id != 0:
        sel_rel = Release.objects.get(id=sel_rel_id)   # Selected release to be displayed
    else:
        sel_rel = None

    items = get_spec_item_query(project_id, application_id, val_set_id, cat, sel_rel, sel_val, order_by)

    if configs['cats'][cat]['level'] == 'project':   # Items to be exported are 'project items'
        fdName = project.name.replace(' ','_') + cat + '.csv'
    else:                       # Items to be exported are 'application items'
        if application == None:
            fdName = project.name.replace(' ','') + cat + '.csv'
        else:
            fdName = application.name.replace(' ','') + cat + '.csv'
        
    csv_sep = configs['general']['csv_sep']
    fd = StringIO()
    for i, item in enumerate(items):
        if (export_type == 'latex_format'):
            item_dic = spec_item_to_latex(item)
            for trac in configs['cats'][cat]['tracs']:
                item_dic[trac['trac_cat']] = list_trac_items_for_latex(item, trac['trac_cat'], trac['trac_link'])
        else:
            item_dic = spec_item_to_export(item)
        if i == 0:      # Open DictWriter and write header fields
            csv_writer = csv.DictWriter(fd, delimiter=csv_sep, fieldnames=list(item_dic.keys()))
            csv_writer.writeheader()
        csv_writer.writerow(item_dic)
    exp_string = fd.getvalue()
    fd.close()        
            
    content_disposition = 'attachment; filename= "' + fdName + '"'
    response = HttpResponse(exp_string, content_type='text/plain')
    response['Content-Disposition'] = content_disposition
    return response            


def import_spec_items(request, cat, project_id, application_id, val_set_id, sel_val):
    project = Project.objects.get(id=project_id)
    val_set = ValSet.objects.filter(project_id=project.id).get(id=val_set_id)
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    if application_id != 0:
        application = Application.objects.get(id=application_id)
    else:
        application = None
    if not has_write_access_to_project(request, project):
        return redirect(base_url)

    redirect_url = '/editor/'+cat+'/'+str(project_id)+'/'+str(application_id)+'/'+str(val_set_id)+\
                           '/'+sel_val+'/'+str(0)+'/list_spec_items'    
  
    if request.method == 'POST':   
        try:
            csv_file = request.FILES['upload_file']
        except Exception as e:
            messages.error(request,'Unable to upload file: '+repr(e))
            return redirect(redirect_url)
        if csv_file.multiple_chunks():
            messages.error(request,'Uploaded file '+csv_file.name+' is too big, size in MB is: '+str(csv_file.size/(1000*1000)))
            return redirect(redirect_url)
        try:
            file_data = csv_file.read().decode('utf-8')
            f = StringIO(file_data)
            items = csv.DictReader(f, delimiter=configs['general']['csv_sep'])
            csv_domain = configs['cats'][cat]['attrs']['domain']['label']
            csv_name = configs['cats'][cat]['attrs']['name']['label']
            csv_val_set = configs['cats'][cat]['attrs']['val_set']['label']
            for i, item in enumerate(items):
                if (sel_val != 'Sel_All') and (item[csv_domain] != sel_val):
                    messages.error(request, ' '+str(i+1)+': Incorrect domain: expected '+sel_val+' but found '+item[csv_domain])
                    continue
                if item[csv_val_set] != val_set.name:
                    messages.error(request, ' '+str(i+1)+': Incorrect ValSet: expected '+val_set+' but found '+item[csv_val_set])
                    continue
                q_all_cat = SpecItem.objects.filter(project_id=project_id, \
                            name=item[csv_name], domain=item[csv_domain]).exclude(status='DEL').exclude(status='OBS')    
                if q_all_cat.exclude(cat=cat).exists():
                    messages.error(request, ' '+str(i+1)+': '+item[csv_domain]+':'+item[csv_name]+' already in use outside selected category')
                    continue
                if val_set.name != 'Default':
                    if not q_all_cat.filter(cat=cat, val_set_id=default_val_set.id).exists():
                        messages.error(request, ' '+str(i+1)+': '+item[csv_domain]+':'+item[csv_name]+' missing from Default ValSet')
                        continue
                q_cat = q_all_cat.filter(cat=cat, val_set_id=val_set.id)
                if not bool(q_cat):     # The domain:name is new in selected category
                    new_spec_item = SpecItem()
                    new_spec_item.cat = cat
                    export_to_spec_item(request, project, item, new_spec_item)   
                    new_spec_item.status = 'NEW'
                    new_spec_item.updated_at = datetime.now(tz=get_current_timezone())
                    new_spec_item.created_at = datetime.now(tz=get_current_timezone())
                    new_spec_item.previous = None
                    new_spec_item.owner = get_user(request)
                    new_spec_item.project = project
                    new_spec_item.application = application                    
                    new_spec_item.save()
                else:
                    if q_cat[0].status == 'CNF':
                        overriden_item = q_cat[0]
                        spec_item = make_obs_spec_item_copy(request, overriden_item)
                        export_to_spec_item(request, project, item, spec_item)
                        spec_item.updated_at = datetime.now(tz=get_current_timezone())
                        spec_item.owner = get_user(request)
                        spec_item.save()
                    else:
                        export_to_spec_item(request, project, item, q_cat[0]) 
                        q_cat[0].updated_at = datetime.now(tz=get_current_timezone())
                        q_cat[0].owner = get_user(request)
                        q_cat[0].save()
        except Exception as e:
            messages.error(request, 'Unable to read or process uploaded file at line '+str(i+2)+'; traceback: '+traceback.format_exc())
    else:
        context = {'project': project, 'title': 'Upload CSV File'}
        return render(request, 'upload_file.html', context)
    return redirect(redirect_url)


@login_required    
def import_project(request):
    if not can_create_project(request):
        return redirect(base_url)
  
    if request.method == 'POST':   
        try:
            zip_file = request.FILES['upload_file']
        except Exception as e:
            messages.error(request,'Unable to upload file: '+repr(e))
            return redirect(base_url)

        # Create directory where import file is unzipped
        temp_dir = configs['general']['temp_dir']
        csv_sep = configs['general']['csv_sep']
        imp_dir = make_temp_dir(temp_dir, 'cordetfw_editor_')
        if imp_dir == '':
            return redirect(base_url)
            
        # Unzip import file    
        imp_project = os.path.join(imp_dir,'import_project.zip')
        with open(imp_project, 'wb') as fd:
            for chunk in zip_file.chunks():
                fd.write(chunk)
        try:
            zip_obj = ZipFile(imp_project, 'r')
            zip_obj.extractall(imp_dir)
        except Exception as e:
            messages.error(request,'Unable to import project zip file: '+repr(e))
            return redirect(base_url)
        zip_obj.close()

        import_project_tables(request, imp_dir)
    else:
        context = {'title': 'Upload Zip File'}
        return render(request, 'upload_file.html', context)

    return redirect(base_url)


@login_required         
def export_project(request, project_id):
    project = Project.objects.get(id=project_id)
    if not has_read_access_to_project(request, project):
        return redirect(base_url)

    temp_dir = configs['general']['temp_dir']
    csv_sep = configs['general']['csv_sep']
    exp_dir = make_temp_dir(temp_dir, 'cordetfw_editor_')
    if exp_dir == '':
        return redirect(base_url)
    
    project_exp = ProjectResource().export(Project.objects.filter(id=project_id))
    with open(os.path.join(exp_dir,'project.csv'),'w', encoding='utf-8') as fd:
        fd.write(project_exp.csv)

    spec_items_exp = SpecItemResource().export(SpecItem.objects.filter(project_id=project_id))
    with open(os.path.join(exp_dir,'spec_items.csv'),'w', encoding='utf-8') as fd:
        fd.write(spec_items_exp.csv)

    val_set_exp = ValSetResource().export(ValSet.objects.filter(project_id=project_id))
    with open(os.path.join(exp_dir,'val_sets.csv'),'w', encoding='utf-8') as fd:
        fd.write(val_set_exp.csv)

    project_users_exp = ProjectUserResource().export(ProjectUser.objects.filter(project_id=project_id))
    with open(os.path.join(exp_dir,'project_users.csv'),'w', encoding='utf-8') as fd:
        fd.write(project_users_exp.csv)

    release_list = []
    release = project.release
    while release != None:
        release_list.append(release.id)
        release = release.previous
    applications = Application.objects.filter(project_id=project_id)
    for application in applications:
        release = application.release
        while release != None:
            release_list.append(release.id)
            release = release.previous
    releases = Release.objects.filter(id__in=release_list)
    
    releases_exp = ReleaseResource().export(releases)
    with open(os.path.join(exp_dir,'releases.csv'),'w', encoding='utf-8') as fd:
        fd.write(releases_exp.csv)

    applications_exp = ApplicationResource().export(applications)
    with open(os.path.join(exp_dir,'applications.csv'),'w', encoding='utf-8') as fd:
        fd.write(applications_exp.csv)

    zip_file_path = os.path.join(exp_dir,'cordetfw_editor_'+project.name+'.zip')
    zip_obj = ZipFile(zip_file_path, 'w')
    zip_obj.write(os.path.join(exp_dir,'project.csv'), 'project.csv')
    zip_obj.write(os.path.join(exp_dir,'applications.csv'), 'applications.csv')
    zip_obj.write(os.path.join(exp_dir,'val_sets.csv'), 'val_sets.csv')
    zip_obj.write(os.path.join(exp_dir,'project_users.csv'), 'project_users.csv')
    zip_obj.write(os.path.join(exp_dir,'releases.csv'), 'releases.csv')
    zip_obj.write(os.path.join(exp_dir,'spec_items.csv'), 'spec_items.csv')
    zip_obj.close()            
            
    zip_file = open(zip_file_path, 'rb')
    return FileResponse(zip_file)        


@login_required         
def list_spec_item_history(request, cat, project_id, application_id, item_id, sel_val):
    # If application_id is zero, then the items to be listed are 'project items'; otherwise they are 'application items'
    project = Project.objects.get(id=project_id)
    if not has_read_access_to_project(request, project):
        return redirect(base_url)
    
    default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
    val_set = ValSet.objects.get(id=default_val_set.id)
    disp = 'disp_def'
    disp_list = configs['cats'][cat][disp]
                                                    
    spec_item = SpecItem.objects.get(id=item_id)
    items = get_previous_list(spec_item)
    context = {'page_items': items, 'project': project, 'application_id': application_id, 'sel_val': sel_val,\
               'config': configs['cats'][cat], 'cat': cat, 'expand_id': 0, 'val_set_id': val_set.id, \
               'val_set': val_set, 'default_val_set_id': default_val_set.id, 'disp': disp, \
               'disp_list': disp_list, 'history': True, 'sel_rel': None, 'sel_rel_id': 0 }
    return render(request, 'list_spec_items.html', context)    
