import re
import os
import logging
import csv
import datetime
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.utils.timezone import make_aware
from editor.models import Project, ProjectUser, Release, ValSet, SpecItem, Application
from editor.utilities import frmt_string
from editor.convert import convert_edit_to_db
from editor.configs import configs
from editor.choices import HISTORY_STATUS
from editor.svg_check import check_svg_value

# Limits for the project ZIP import (import-project-no-limits). A real export holds six csv files; a
# project of ~20,000 items is a few MB to a few tens of MB uncompressed. The limits are >= 20x that.
logger = logging.getLogger(__name__)

IMPORT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024         # size of the uploaded (compressed) file
IMPORT_MAX_MEMBERS = 100                            # number of entries in the archive
IMPORT_MAX_MEMBER_BYTES = 200 * 1024 * 1024         # uncompressed size of one entry
IMPORT_MAX_TOTAL_BYTES = 200 * 1024 * 1024          # uncompressed size of all entries
IMPORT_MEMBERS = ('project.csv', 'applications.csv', 'val_sets.csv', 'project_users.csv',
                  'releases.csv', 'spec_items.csv')


def extract_project_zip(zip_path, imp_dir):
    """
    Extract the expected csv tables of a project export from the zip file at zip_path into
    imp_dir. Other entries are ignored (never extracted, so their names cannot place files
    anywhere). The limits above are enforced on the sizes actually read, not on the sizes
    declared in the archive. Raises ValueError if a limit is exceeded.
    """
    from zipfile import ZipFile
    with ZipFile(zip_path, 'r') as zip_obj:
        infos = zip_obj.infolist()
        if len(infos) > IMPORT_MAX_MEMBERS:
            raise ValueError('the archive has more than '+str(IMPORT_MAX_MEMBERS)+' entries')
        if sum(i.file_size for i in infos) > IMPORT_MAX_TOTAL_BYTES:
            raise ValueError('the archive is larger than '+str(IMPORT_MAX_TOTAL_BYTES//(1024*1024))+' MB uncompressed')
        total = 0
        names = {}
        for info in infos:
            names.setdefault(info.filename, info)       # first entry of a name wins, as for extractall
        for name in IMPORT_MEMBERS:
            if name not in names:
                continue
            read = 0
            with zip_obj.open(names[name]) as src, open(os.path.join(imp_dir, name), 'wb') as dst:
                while True:
                    chunk = src.read(1024*1024)
                    if not chunk:
                        break
                    read += len(chunk)
                    total += len(chunk)
                    if read > IMPORT_MAX_MEMBER_BYTES:
                        raise ValueError('the entry '+name+' is larger than '+
                                         str(IMPORT_MAX_MEMBER_BYTES//(1024*1024))+' MB uncompressed')
                    if total > IMPORT_MAX_TOTAL_BYTES:
                        raise ValueError('the archive is larger than '+
                                         str(IMPORT_MAX_TOTAL_BYTES//(1024*1024))+' MB uncompressed')
                    dst.write(chunk)


class ImportAborted(Exception):
    """The import cannot continue; the message is shown to the user and nothing is imported."""


#--------------------------------------------------------------------------------
def import_project_tables(request, imp_dir):
    """
    Import the csv tables in directory imp_dir. The whole import is one database transaction
    (import-project-not-atomic): either the project is created completely or nothing is created and a
    single error message is shown. Messages about individual items that were skipped are shown only
    if the import succeeds.
    """
    notes = []
    try:
        with transaction.atomic():
            _import_project_tables(imp_dir, notes)
    except ImportAborted as e:
        messages.error(request, str(e))
        return
    except Exception as e:
        logger.exception('import_project failed')
        messages.error(request, 'Unable to import project: '+repr(e)+'; nothing was imported')
        return
    for note in notes:
        messages.error(request, note)


def project_role(project_user):
    """ import-project-role-lost: the role of the exported project user; unknown values are read-only """
    role = project_user.get('role', 'RO')
    return role if role in ('RO', 'RW') else 'RO'


def created_at_kwargs(spec_item):
    """ import-project-created-at-lost: the exported creation time; without one the model default applies """
    value = spec_item.get('created_at')
    if not value:
        return {}
    return {'created_at': make_aware(datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S"))}


def restore_updated_at(instance, value, is_date=False):
    """
    import-project-auto-now-timestamps: Project, Application (datetime) and ValSet, ProjectUser (date) have
    auto_now updated_at fields that are set to 'now' by save(). Write the exported value afterwards with
    queryset.update(), which bypasses auto_now. An empty or unreadable value leaves the import time.
    """
    try:
        if is_date:
            parsed = datetime.datetime.strptime(value, "%Y-%m-%d").date()
        else:
            parsed = make_aware(datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return
    type(instance).objects.filter(pk=instance.pk).update(updated_at=parsed)


def item_full_name(row):
    return row['cat']+':'+row['domain']+':'+row['name']+' (status: '+row['status']+')'


def _import_project_tables(imp_dir, notes):
    
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
                raise ImportAborted('A project called '+project_dict['name']+' already exists')
    except ImportAborted:
        raise
    except Exception as e:
        raise ImportAborted('Failure to open or read import project file '+project_csv+': '+str(e))
    
    # Check that the project owner exists
    try:
        project_owner = User.objects.get(username=project_dict['owner'])
    except Exception as e:
        raise ImportAborted('The project owner '+project_dict['owner']+' does not exist: '+str(e))
        
    # Check that project categories are defined in configs.json
    for cat in project_dict['cats'].split(','):
        if not cat.strip() in configs['cats']:
            raise ImportAborted('The project category '+cat+' is not defined in configs.json')
    
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
        raise ImportAborted('Failure to open or read import release file '+releases_csv+': '+str(e))

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
        raise ImportAborted('Failure to open or read import ValSet file '+val_set_csv+': '+str(e))

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
        raise ImportAborted('Failure to open or read import ProjectUser file '+project_user_csv+': '+str(e))
        
    # Check that all project users exist
    user_name_2_user = {}    
    try:
        for project_user in project_users:
            user_name_2_user[project_user['user']] = User.objects.get(username=project_user['user'])
    except Exception as e:
        raise ImportAborted('The project user '+project_user['user']+' does not exist: '+str(e))
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
        raise ImportAborted('Failure to open or read import Application file '+application_csv+': '+str(e))
        
    # Check that the application categories are defined in configs.json
    for application in applications:
        for cat in application['cats'].split(','):
            if not cat.strip() in configs['cats']:
                raise ImportAborted('The category '+cat+' in application '+application['name']+' is not defined in configs.json')
        
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
        raise ImportAborted('Failure to open or read import SpecItem file '+spec_item_csv+': '+str(e))
        
    # Import the release instances into the database
    old_id_2_new_id = {}
    for release in releases:
        try:
            release_author = User.objects.get(username=release['release_author'])
        except Exception as e:
            raise ImportAborted('The release author '+release['release_author']+' does not exist: '+str(e))
        new_release = Release(release_author = release_author,
                              desc = release['desc'],
                              updated_at = release['updated_at'],
                              project_version = release['project_version'],
                              application_version = release.get('application_version') or 0)
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
    restore_updated_at(new_project, project_dict['updated_at'])

    # Import the ValSet instances
    val_set_old_id_2_new = {}
    for val_set in val_sets:
        new_val_set = ValSet(updated_at = val_set['updated_at'],
                             project = new_project,
                             name = val_set['name'],
                             desc = val_set['desc'])
        new_val_set.save()
        restore_updated_at(new_val_set, val_set['updated_at'], is_date=True)
        val_set_old_id_2_new[val_set['id']] = new_val_set
    
    # Import the Project Users
    for project_user in project_users:
        new_project_user = ProjectUser(updated_at = project_user['updated_at'],
                                       project = new_project,
                                       user = user_name_2_user[project_user['user']],
                                       role = project_role(project_user))
        new_project_user.save()
        restore_updated_at(new_project_user, project_user['updated_at'], is_date=True)
        
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
        restore_updated_at(new_application, application['updated_at'])
        application_old_id_2_new[application['id']] = new_application
    
    # Import SpecItems
    added_members = set()

    def resolve_item_owner(spec_item):
        # import-project-owner-not-member (operator decision 2026-10-24): an owner who is neither the project
        # owner nor a project user keeps the item if the user exists on this server (and becomes a read-only
        # project user), otherwise the item is assigned to the project owner. Users are never created.
        name = spec_item['owner']
        if name in user_name_2_user:
            return user_name_2_user[name]
        user = User.objects.filter(username=name).first()
        if user is None:
            notes.append('Spec_item '+item_full_name(spec_item)+': the owner '+name+' does not exist on this server, '+
                         'the item was assigned to the project owner '+project_owner.username)
            return project_owner
        ProjectUser(project = new_project, user = user, role = 'RO').save()
        user_name_2_user[name] = user
        notes.append('The user '+name+' owns imported items but is not a user of the project: '+
                     'added as read-only user of the project')
        return user

    spec_item_old_id_2_new = {}
    spec_item_new_id_2_old = {}
    valid_status = [choice[0] for choice in HISTORY_STATUS]
    for spec_item in spec_items:
        # import-project-attribution-forgery: category and status must be known values
        if spec_item['cat'] not in configs['cats']:
            notes.append('Failure to import spec_item ' + spec_item['cat']+':'+spec_item['domain']+':'+
                           spec_item['name'] + ': the category ' + spec_item['cat'] + ' is not defined in configs.json')
            continue
        if spec_item['status'] not in valid_status:
            notes.append('Failure to import spec_item ' + spec_item['cat']+':'+spec_item['domain']+':'+
                           spec_item['name'] + ': the status ' + spec_item['status'] + ' is not valid (valid values are: '+
                           ', '.join(valid_status) + ')')
            continue
        try:
            if configs['cats'].get(spec_item['cat'], {}).get('attrs', {}).get('value', {}).get('kind') == 'image':
                check_svg_value(spec_item['value'])       # Task 6.6b: image-svg-unsanitised
            new_spec_item = SpecItem(cat = spec_item['cat'],
                                     name = spec_item['name'],
                                     domain = spec_item['domain'],
                                     project = new_project,
                                     application = application_old_id_2_new[spec_item['application']],
                                     title = spec_item['title'],
                                     desc = spec_item['desc'],
                                     owner = resolve_item_owner(spec_item),
                                     val_set = val_set_old_id_2_new[spec_item['val_set']],
                                     status = spec_item['status'],
                                     updated_at = make_aware(datetime.datetime.strptime(spec_item['updated_at'], "%Y-%m-%d %H:%M:%S")),
                                     **created_at_kwargs(spec_item),
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
            with transaction.atomic():          # savepoint: a failing row must not break the import transaction
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
            notes.append(msg + 'Error is: ' + repr(e))
        
    # Extract all new items and then save again to force update of internal and direct links    
    new_spec_items = SpecItem.objects.filter(project_id=new_project.id)
    for new_spec_item in new_spec_items:
        old_spec_item = spec_item_new_id_2_old[new_spec_item.id] 
        for field in ('previous', 'p_link', 's_link'):
            old_target = old_spec_item[field]
            if old_target == '':
                continue
            target = spec_item_old_id_2_new.get(old_target)
            if target is None:      # import-project-dangling-link-crash: missing or rejected item
                notes.append('Spec_item '+item_full_name(old_spec_item)+': the '+field+' (item id '+old_target+
                             ') is not in the imported data, the '+field+' was set to None')
            setattr(new_spec_item, field, target)

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
        
        
        
        
        
        
        
    
    
    
    
