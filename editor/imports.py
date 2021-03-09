import re
import os
import csv
from django.contrib.auth.models import User
from django.contrib import messages
from editor.models import Project, ProjectUser, Release, ValSet, SpecItem, Application
from editor.utilities import frmt_string

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
                          updated_at = project_dict['updated_at'],
                          owner = project_owner)
    new_project.release_id = old_id_2_new_id[project_dict['release']]
    new_project.save()
    
    # Import the ValSet instances
    #for val_set in val_sets:
    #    if 
