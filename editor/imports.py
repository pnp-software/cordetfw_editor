import re
import os
import csv
import datetime
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils.timezone import make_aware
from editor.models import Project, ProjectUser, Release, ValSet, SpecItem, Application
from editor.utilities import frmt_string
from editor.convert import convert_edit_to_db, update_pattern_edit
from editor.configs import configs

#--------------------------------------------------------------------------------
def import_project_tables(request, imp_dir):
    """ Import the csv tables in directory imp_dir """
    
    # Read the project table  
    project_csv = os.path.join(imp_dir,'project.csv')
    try:
        dict =  csv.DictReader(open(project_csv, 'r'))
        with open(project_csv, 'r') as fd:
            reader = csv.DictReader(fd)
            for row in reader:          # Project file should have only one line
                project_dict = row
                break
            if Project.objects.filter(name=project_dict['name']).exists():
                messages.error(request, 'A project called '+project_dict['name']+' already exists')
                return
    except Exception as e:
        messages.error(request, 'Failure to open or read import project file '+project_csv+': '+str(e))
        return
    
    # Check that the project owner exists
    try:
        project_owner = User.objects.get(username=project_dict['owner'])
    except Exception as e:
        messages.error(request, 'The project owner '+project_dict['owner']+' does not exist: '+str(e))
        return   
        
    # Check that project categories are defined in configs.json
    for cat in project_dict['cats'].split(','):
        if not cat.strip() in configs['cats']:
            messages.error(request, 'The project category '+cat+' is not defined in configs.json')
            return   
    
    # Read the release table
    releases_csv = os.path.join(imp_dir,'releases.csv')
    try:
        dict =  csv.DictReader(open(releases_csv, 'r'))
        releases = []
        with open(releases_csv, 'r') as fd:
            reader = csv.DictReader(fd)
            for row in reader:          
                releases.append(row)
    except Exception as e:
        messages.error(request, 'Failure to open or read import release file '+releases_csv+': '+str(e))
        return

    # Read the ValSet table
    val_set_csv = os.path.join(imp_dir,'val_sets.csv')
    try:
        dict =  csv.DictReader(open(val_set_csv, 'r'))
        val_sets = []
        with open(val_set_csv, 'r') as fd:
            reader = csv.DictReader(fd)
            for row in reader:          
                val_sets.append(row)
    except Exception as e:
        messages.error(request, 'Failure to open or read import ValSet file '+val_set_csv+': '+str(e))
        return

    # Read the ProjectUser table
    project_user_csv = os.path.join(imp_dir,'project_users.csv')
    try:
        dict =  csv.DictReader(open(project_user_csv, 'r'))
        project_users = []
        with open(project_user_csv, 'r') as fd:
            reader = csv.DictReader(fd)
            for row in reader:          
                project_users.append(row)
    except Exception as e:
        messages.error(request, 'Failure to open or read import ProjectUser file '+project_user_csv+': '+str(e))
        return
        
    # Check that all project users exist
    user_name_2_user = {}    
    try:
        for project_user in project_users:
            user_name_2_user[project_user['user']] = User.objects.get(username=project_user['user'])
    except Exception as e:
        messages.error(request, 'The project user '+project_user['user']+' does not exist: '+str(e))
        return   
    user_name_2_user[project_owner.username] = project_owner 
        
    # Read the Application table
    application_csv = os.path.join(imp_dir,'applications.csv')
    try:
        dict =  csv.DictReader(open(application_csv, 'r'))
        applications = []
        with open(application_csv, 'r') as fd:
            reader = csv.DictReader(fd)
            for row in reader:          
                applications.append(row)
    except Exception as e:
        messages.error(request, 'Failure to open or read import Application file '+application_csv+': '+str(e))
        return
        
    # Check that the application categories are defined in configs.json
    for application in applications:
        for cat in application['cats'].split(','):
            if not cat.strip() in configs['cats']:
                messages.error(request, 'The category '+cat+' in application '+application['name']+' is not defined in configs.json')
                return   
        
    # Read the SpecItem table
    spec_item_csv = os.path.join(imp_dir,'spec_items.csv')
    try:
        dict =  csv.DictReader(open(application_csv, 'r'))
        spec_items = []
        with open(spec_item_csv, 'r') as fd:
            reader = csv.DictReader(fd)
            for row in reader:          
                spec_items.append(row)
    except Exception as e:
        messages.error(request, 'Failure to open or read import SpecItem file '+spec_item_csv+': '+str(e))
        return
        
    # Import the release instances into the database
    old_id_2_new_id = {}
    for release in releases:
        try:
            release_author = User.objects.get(username=release['release_author'])
        except Exception as e:
            messages.error(request, 'The release author '+release['release_author']+' does not exist: '+str(e))
            return
        new_release = Release(release_author = release_author,
                              desc = release['desc'],
                              updated_at = release['updated_at'],
                              project_version = release['project_version'])
        new_release.save()
        old_id_2_new_id[release['id']] = new_release.id
    for release in releases:
        if (release['previous'] != None) and (release['previous'] != ''):
            release_saved = Release.objects.get(id=old_id_2_new_id[release['id']])
            release_saved.previous = Release.objects.get(id=old_id_2_new_id[release['previous']])
            release_saved.save()

    # Import the project instance
    new_project = Project(name = project_dict['name'],
                          desc = project_dict['desc'],
                          cats = project_dict['cats'],
                          updated_at = project_dict['updated_at'],
                          owner = project_owner)
    new_project.release_id = old_id_2_new_id[project_dict['release']]
    new_project.save()
    update_pattern_edit(new_project)    # Update the regex expressions associtated to the project
    
    # Import the ValSet instances
    val_set_old_id_2_new = {}
    for val_set in val_sets:
        new_val_set = ValSet(updated_at = val_set['updated_at'],
                             project = new_project,
                             name = val_set['name'],
                             desc = val_set['desc'])
        new_val_set.save()
        val_set_old_id_2_new[val_set['id']] = new_val_set
    
    # Import the Project Users
    for project_user in project_users:
        new_project_user = ProjectUser(updated_at = project_user['updated_at'],
                                       project = new_project,
                                       user = user_name_2_user[project_user['user']])
        new_project_user.save()
        
    # Import the Applications
    application_old_id_2_new = {}
    application_old_id_2_new[''] = None
    for application in applications:
        new_application = Application(updated_at = application['updated_at'],
                                       project = new_project,
                                       desc = application['desc'],
                                       cats = application['cats'],
                                       name = application['name'])
        new_application.release_id = old_id_2_new_id[application['release']]
        new_application.save()
        application_old_id_2_new[application['id']] = new_application
    
    # Import SpecItems
    spec_item_old_id_2_new = {}
    spec_item_new_id_2_old = {}
    for spec_item in spec_items:
        try:
            new_spec_item = SpecItem(cat = spec_item['cat'],
                                     name = spec_item['name'],
                                     domain = spec_item['domain'],
                                     project = new_project,
                                     application = application_old_id_2_new[spec_item['application']],
                                     title = spec_item['title'],
                                     desc = spec_item['desc'],
                                     owner = user_name_2_user[spec_item['owner']],
                                     val_set = val_set_old_id_2_new[spec_item['val_set']],
                                     status = spec_item['status'],
                                     updated_at = make_aware(datetime.datetime.strptime(spec_item['updated_at'], "%Y-%m-%d %H:%M:%S")),
                                     rationale = spec_item['rationale'],
                                     implementation = spec_item['implementation'],
                                     remarks = spec_item['remarks'],
                                     s_data = spec_item['s_data'],
                                     p_kind = spec_item['p_kind'],
                                     s_kind = spec_item['s_kind'],
                                     value = spec_item['value'],
                                     t1 = spec_item['t1'],
                                     t2 = spec_item['t2'],
                                     t3 = spec_item['t3'],
                                     t4 = spec_item['t4'],
                                     t5 = spec_item['t5'],
                                     n1 = spec_item['n1'],
                                     n2 = spec_item['n2'],
                                     n3 = spec_item['n3'],
                                     change_log = spec_item['change_log'])
            new_spec_item.save()
            spec_item_old_id_2_new[spec_item['id']] = new_spec_item
            spec_item_new_id_2_old[new_spec_item.id] = spec_item
        except Exception as e:
            spec_item_full_name = spec_item['cat']+':'+spec_item['domain']+':'+spec_item['name']+' (staus: '+spec_item['status']+')'
            msg = 'Failure to import spec_item ' + spec_item_full_name + ' Probable causes are: ' +\
                  '(a) application identifier (' + spec_item['application'] + ') is not recognized; ' +\
                  '(b) spec_item owner '+ spec_item['owner'] +' is not a project user '+\
                  '(c) ValSet identifier (' + spec_item['val_set'] + ') is not recognized; ' +\
                  '(d) Update time (' + spec_item['updated_at'] + ') is not in format Y-m-d H-M-S; '
            messages.error(request, msg + 'Error is: ' + repr(e))
        
    # Extract all new items and then save again to force update of internal and direct links    
    new_spec_items = SpecItem.objects.filter(project_id=new_project.id)
    for new_spec_item in new_spec_items:
        old_spec_item = spec_item_new_id_2_old[new_spec_item.id] 
        if old_spec_item['previous'] != '':
            new_spec_item.previous = spec_item_old_id_2_new[old_spec_item['previous']]
        if old_spec_item['p_link'] != '':
            new_spec_item.p_link = spec_item_old_id_2_new[old_spec_item['p_link']]
        if old_spec_item['s_link'] != '':
            new_spec_item.s_link = spec_item_old_id_2_new[old_spec_item['s_link']]
        
        new_spec_item.desc = convert_edit_to_db(new_project, new_spec_item.desc)
        new_spec_item.rationale = convert_edit_to_db(new_project, new_spec_item.rationale)
        new_spec_item.implementation = convert_edit_to_db(new_project, new_spec_item.implementation)
        new_spec_item.remarks = convert_edit_to_db(new_project, new_spec_item.remarks)
        new_spec_item.t1 = convert_edit_to_db(new_project, new_spec_item.t1)
        new_spec_item.t2 = convert_edit_to_db(new_project, new_spec_item.t2)
        new_spec_item.t3 = convert_edit_to_db(new_project, new_spec_item.t3)
        new_spec_item.t4 = convert_edit_to_db(new_project, new_spec_item.t4)
        new_spec_item.t5 = convert_edit_to_db(new_project, new_spec_item.t5)
        new_spec_item.value = convert_edit_to_db(new_project, new_spec_item.value)
        new_spec_item.save()
        
        
        
        
        
        
        
    
    
    
    
