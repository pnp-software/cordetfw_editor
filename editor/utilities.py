import os
import re
import cexprtk
import logging
from tablib import Dataset
from django.contrib import messages
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user
from django.contrib.auth.models import User
from django.forms.models import model_to_dict
from django.db.models import ForeignKey
from django.utils.timezone import get_current_timezone
from datetime import datetime
from editor.models import SpecItem, ProjectUser, Application, Release, Project, ValSet
from editor.configs import configs
from editor.ext_cats import get_model
from editor.convert import convert_db_to_edit, frmt_string, convert_edit_to_db, \
                           convert_exp_to_db, convert_db_to_latex, eval_di_value
from editor.choices import HISTORY_STATUS, SPEC_ITEM_CAT, REQ_KIND, DI_KIND, \
                           MODEL_KIND, PCKT_KIND, VER_ITEM_KIND, REQ_VER_METHOD, VER_STATUS


logger = logging.getLogger(__name__)


def snake_to_camel(s):
    """ Convert string from snake_case to CamelCase """
    return ''.join(x.capitalize() or '_' for x in s.split('_'))


def get_csv_line(csv_items):
    """ Convert a list of items into a string formatted to be output to a csv file. """
    if len(csv_items) == 0:
       return '\n'

    s = ""
    for i in range(len(csv_items)-1):
       if csv_items[i] == None:
          s = s + '|'
       else:
          s = s + frmt_string(csv_items[i]) + '|'
    s = s + frmt_string(csv_items[len(csv_items)-1]) + '\n'
    return s

          
def spec_item_to_edit(spec_item):
    """ 
    The argument is a specification item and the output is a dictionary representing the specification
    item in a format suitable for display in a form.
    """
    dic = model_to_dict(spec_item)
    for key, value in configs['cats'][spec_item.cat]['attrs'].items():
        if value['kind'] == 'ref_text':
            dic[key] = convert_db_to_edit(dic[key])
    return dic
    
    
def spec_item_to_latex(spec_item):
    """ 
    The argument is a specification item and the output is a dictionary as follows: 
    - Key: label of the fields to be exported to latex format
    - Value: value of field in latex representation
    The field label is the label as given in the configs dictionary without spaces.  
    """
    cat_attrs = configs['cats'][spec_item.cat]['attrs']
    dic = {}
    for key, value in configs['cats'][spec_item.cat]['attrs'].items():
        label = cat_attrs[key]['label'].replace(' ','')
        if value['kind'] == 'ref_text':
            dic[label] = frmt_string(convert_db_to_latex(getattr(spec_item, key)))
        elif value['kind'] == 'spec_item_ref':
            dic[label] = frmt_string(str(getattr(spec_item, key))).split(' ')[0]
        elif value['kind'] == 'plain_text':
            dic[label] = frmt_string(str(getattr(spec_item, key)))
        elif value['kind'] == 'eval_ref':
            dic[label] = frmt_string(convert_db_to_latex(getattr(spec_item, key)))
            dic['NVal'] = eval_di_value(spec_item.value)
        elif value['kind'] == 'image':
            dic[label] = 'TBD image data'
        else:
            dic[label] = frmt_string(str(getattr(spec_item, key)))
    
    dic['UpdatedAt'] = spec_item.updated_at.strftime('%d-%m-%Y %H:%M')    
    dic['Owner'] = frmt_string(str(spec_item.owner))
    dic['Status'] = spec_item.status
    dic['Project'] = frmt_string(str(spec_item.project))
    dic['Application'] = frmt_string(str(spec_item.application))
    return dic
    

def spec_item_to_export(spec_item):
    """ 
    The argument is a specification item and the output is a dictionary as follows: 
    - Key: label of the fields to be exported
    - Value: value of field in export representation
    The field label is the label as given in the configs dictionary.  
    """
    cat_attrs = configs['cats'][spec_item.cat]['attrs']
    dic = {}
    for key, value in configs['cats'][spec_item.cat]['attrs'].items():
        if value['kind'] == 'ref_text':
            dic[cat_attrs[key]['label']] = convert_db_to_edit(getattr(spec_item, key))
        elif value['kind'] == 'spec_item_ref':
            dic[cat_attrs[key]['label']] = str(getattr(spec_item, key)).split(' ')[0]
        else:
            dic[cat_attrs[key]['label']] = str(getattr(spec_item, key))
    return dic
        
            
def export_to_spec_item(request, project, imp_dict, spec_item):
    """ 
    Argument imp_dict is a dictionary created by reading a line in a 
    plain import file.
    The function converts the dictionary entries to db format and uses them 
    to initialize the argument spec_item.
    Only attributes listed in the 'attrs' field of the configuration dictionary
    of the spec_item category are converted.
    Only attributes which are imported are initialized.
    The function will raise an exception if one of the fields expected
    in the dictionary is not found. 
    """
    cat_attrs = configs['cats'][spec_item.cat]['attrs']
    for key, value in configs['cats'][spec_item.cat]['attrs'].items():
        if key == 'val_set':
            spec_item.val_set = ValSet.objects.get(project_id=project.id, name=imp_dict[cat_attrs[key]['label']])
        elif key == 'owner':    # Owner is overridden by import function
            continue
        elif value['kind'] == 'ref_text':
            setattr(spec_item, key, convert_edit_to_db(project, imp_dict[cat_attrs[key]['label']]))
        elif value['kind'] == 'spec_item_ref':
            setattr(spec_item, key, convert_exp_to_db(imp_dict[cat_attrs[key]['label']]))
        else:
            setattr(spec_item, key, imp_dict[cat_attrs[key]['label']])


def get_user_choices(project):
    """ 
        Return a list of pairs (id, user) representing the users in the system 
        (excluding, if it exists, the owner of the project)
    """
    user_choices = []
    if project != None:
        users = User.objects.all().exclude(id=project.owner.id).order_by('username').\
                                           values_list('id', 'username', 'first_name', 'last_name')
        user_choices.append((project.owner.id, project.owner.username+' ('+project.owner.first_name+' '+project.owner.last_name+')'))
    else:
        users = User.objects.all().order_by('username').values_list('id','username', 'first_name', 'last_name')
    for user in users:
       if ((user[2] != '') or (user[3] != '')):
          user_choices.append((user[0], user[1]+' ('+user[2]+' '+user[3]+')'))
       else:
          user_choices.append((user[0], user[1]))      
    return user_choices


def get_previous_list(item):
    """ 
    Item is a model instance with a 'previous' field. This function returns the list of previous items for 'item'.
    """
    items =[]
    items.append(item)
    while True:
       if not item.previous:
          break
       else:
          item = item.previous
          items.append(item)
    return items
        
        
def get_p_kind_choices(cat):
    """ Return the range of choices for the 'p_kind' attribute of a specification of a given category """
    if cat == 'Requirement':
       return REQ_KIND
    elif cat == 'DataItem':
       return DI_KIND
    elif cat == 'Model':
       return MODEL_KIND
    elif cat == 'Packet':
       return PCKT_KIND
    elif cat == 'PacketPar':
       return PCKT_PAR_KIND
    elif cat == 'VerItem':
       return VER_ITEM_KIND
    return (("INV","Invalid"),)


def get_s_kind_choices(cat):
    """ Return the range of choices for the 's_kind' attribute of a specification of a given category """
    if cat == 'Requirement':
       return REQ_VER_METHOD
    if cat == 'VerItem':
       return VER_STATUS
    return (("INV","Invalid"),)
  
    
def get_expand_items(cat, project_id, val_set_id, expand_id, expand_link):
    """ 
    Get the list of expand_items for the spec_item whose ID is expand_id.
    The expand_link is either 's_link' or 'p_link'    
    If the expand_link is 's_link', the expand_items are the spec_items whose
    s_link points to expand_id (i.e. they are the children of expand_id 
    according to s_link).
    If the expand_link is 'p_link', the expand_items the spec_items whose
    p_link points to expand_id (i.e. they are the children of expand_id 
    according to p_link).
    The information in configs[cat]['expand'] determines whether or not
    a given spec_item has s_link or p_link children. 
    """
    if configs['cats'][cat]['expand'][expand_link] == 'None':
        return None
    expand_items = None
    if expand_link == 's_link':
        expand_items = SpecItem.objects.filter(project_id=project_id, \
                            cat=configs['cats'][cat]['expand'][expand_link], \
                            s_link_id=expand_id, \
                            val_set_id=val_set_id).\
                            exclude(status='DEL').exclude(status='OBS').order_by('domain','name')
    if expand_link == 'p_link':
        expand_items = SpecItem.objects.filter(project_id=project_id, \
                            cat=configs['cats'][cat]['expand'][expand_link], \
                            p_link_id=expand_id, \
                            val_set_id=val_set_id).\
                            exclude(status='DEL').exclude(status='OBS').order_by('domain','name')
    return expand_items
   

def get_redirect_url(cat, project_id, application_id, default_val_set_id, \
                     sel_dom, s_parent_id, p_parent_id, target_spec_item):
    """
    Compute the url to which the user is re-directed after having added/copied/edited
    a spec_item. If s_parent_id or p_parent_id are different from 'None', then the 
    add/copy/edit operation is being done on a spec_item in an expansion list and
    hence the re-direct is to the list_spec_items view with an expand_id. 
    """
    if (s_parent_id != None):
        s_parent = SpecItem.objects.get(id=s_parent_id)
        target = '#expand:'+target_spec_item.domain+':'+target_spec_item.name if target_spec_item!=None else ''
        return '/editor/'+s_parent.cat+'/'+str(project_id)+'/'+str(application_id)+'/'+str(default_val_set_id)+\
                           '/'+sel_dom+'/list_spec_items?expand_id='+s_parent_id+'&expand_link=s_link'+target        
    if (p_parent_id != None):
        p_parent = SpecItem.objects.get(id=p_parent_id)
        target = '#expand:'+target_spec_item.domain+':'+target_spec_item.name if target_spec_item!=None else ''
        return '/editor/'+p_parent.cat+'/'+str(project_id)+'/'+str(application_id)+'/'+str(default_val_set_id)+\
                           '/'+sel_dom+'/list_spec_items?expand_id='+p_parent_id+'&expand_link=p_link'+target         
    
    target = '#'+target_spec_item.domain+':'+target_spec_item.name if target_spec_item!=None else ''
    return '/editor/'+cat+'/'+str(project_id)+'/'+str(application_id)+'/'+str(default_val_set_id)+\
                           '/'+sel_dom+'/list_spec_items'+target
      
         
def get_domains(cat, application_id, project_id):
    """ 
    Return the list of domains for the specification items in the argument category. If application_id is zero,
    then the model are filtered by project; otherwise they are filter by application.
    """           
    domains = ['All_Domains']
    if application_id == 0:
       for domain in SpecItem.objects.filter(project_id=project_id).filter(cat=cat).exclude(status='DEL'). \
                                exclude(status='OBS').order_by('domain').values_list('domain').distinct():
          domains.append(domain[0])
    else:
       for domain in SpecItem.objects.filter(application_id=application_id).filter(cat=cat).exclude(status='DEL'). \
                                exclude(status='OBS').order_by('domain').values_list('domain').distinct():
          domains.append(domain[0])
    return domains    
                   
 
def do_application_release(request, application, description, is_proj_release = False):
    """ 
    Do an application release by updating the status of the application requirements, models and test cases.
    """
    spec_items = SpecItem.objects.filter(application_id=application.id)
    for spec_item in spec_items:
       if (spec_item.status == 'NEW') or (spec_item.status == 'MOD'):
          spec_item.status = 'CNF'
          spec_item.save()

    if application.release_id == None:    # Application has just been created
       new_application_version = 0
       previous = None
    elif not is_proj_release:         # Application release is not done as part of a project release
       new_application_version =  application.release.application_version+1
       previous = application.release
    else:
       new_application_version =  0
       previous = application.release
    
    new_release = Release(desc = description,
                     release_author = get_user(request),
                     updated_at = datetime.now(tz=get_current_timezone()),
                     application_version = new_application_version,
                     project_version = application.project.release.project_version,
                     previous = previous)
    new_release.save()
    application.release = new_release
    application.save()
          

def do_project_release(request, project, description):
    """ 
    Do a project release by updating the status of the project data items, data types and applications.
    """
    spec_items = SpecItem.objects.filter(project_id=project.id). filter(application_id=None)
    for spec_item in spec_items:
       if (spec_item.status == 'NEW') or (spec_item.status == 'MOD'):
          spec_item.status = 'CNF'
          spec_item.save()

    new_release = Release(desc = description,
                     release_author = get_user(request),
                     updated_at = datetime.now(tz=get_current_timezone()),
                     application_version = 0,
                     project_version = project.release.project_version+1,
                     previous = project.release)
    new_release.save()
    project.release = new_release
    project.save()
    
    applications = Application.objects.filter(project_id=project.id)
    for application in applications:
       do_application_release(request, application, description, is_proj_release = True)
    
    
def make_temp_dir(dir_path, name):
    """ Create a directory 'name_<TimeStamp>' in the directory 'dir_path' and return 
        the dir name or an empty string if the creation failed
    """
    new_dir_path = os.path.join(dir_path,name+datetime.now(tz=get_current_timezone()).strftime('%Y_%m_%d_%H_%M_%S'))
    try:  
        os.mkdir(new_dir_path)  
    except OSError as e:  
        messages.error(request, 'Failure to create export directory at '+exp_dir+': '+str(e))
        return ''
    return new_dir_path

   
def get_default_val_set_id(request, project):
    """ 
        Return the default ValSet id for the argument project. If the ValSet cannot
        be retrieved, a value of zero is returned.
    """
    try:
        id = ValSet.objects.filter(project_id=project.id).get(name='Default').id    
        return id 
    except Exception as e:
        messages.error(request, 'Failure to retrieve the ValSet for project '+str(project)+\
                       '. This probably meanns that the data for the projects are corrupted. '+\
                       'Error message was: '+str(e))
        return 0
    

def del_release(request, release, n):
    """ 
        Recursively delete a release and its previous releases. If the depth of recursion 
        exceeds max_depth, an error is declared and False is returned.
    """
    if n > configs['General']['max_depth']:
        messages.error(request, 'Attempt to delete a release has reached the limit '+\
                                    'on the depth of recursion: '+str(n))
        return False
        
    previous_release = release.previous
    release.delete()        
    if previous_release != None:
        del_release(request, previous_release, n+1)
    return True                                 


def list_trac_items_for_latex(spec_item, trac_cat, trac_link):
    """
    Generate the latex representation of the traceability information for spec_item.
    If S is spec_item, then this function assumes that the traceability link is stored
    in category 'trac_cat' and that attribute 'trac_link' holds the link from trac_cat
    to spec_item. trac_link is either 's_link' or 'p_link'.
    To illustrate, suppose that 'trac_link' is equal to 's_link'; in this case, 
    the function proceeds in two steps:
    - It extracts all the spec_items L1, L2, ... Ln which belong to category spec_cat  
      and which point to S through their s_link
    - It returns a string holding a list of the spec_items which are pointed at by
      L1, L2, ... Ln through p_link
    """
    if trac_link == 's_link':
        trac_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat=trac_cat,
                     s_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
    else:
        trac_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat=trac_cat,
                     p_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
    
    s = ''
    for link in trac_links:
        if trac_link == 's_link':
            s = s + link.p_link.domain+':' + link.p_link.name + ' ('+ link.p_link.title +')'
        else:
            s = s + link.s_link.domain+':' + link.s_link.name + ' ('+ link.s_link.title +')'
        s = s + '\n'    
    return frmt_string(s[:-1])    # The last '\n' is removed
    
def make_obs_spec_item_copy(request, spec_item):
    """ 
    The argument spec_item must be made obsolete: the previous pointer of spec_item is reset;
    a copy of the spec_item is created; its status is set to OBS; the spec_item copy is saved 
    to the database; the status of the argument spec_item is set to MOD; its previous
    pointer is set to point to the newly created OBS copy; the original spec_item instance
    is returned to the caller 
    """
    edited_spec_item_id = spec_item.id
    previous = spec_item.previous
    spec_item.previous = None
    spec_item.save()            # Reset the previous pointer of the spec_item 
    
    spec_item.status = 'OBS'
    spec_item.previous = previous
    spec_item.id = None
    spec_item.save()            # Create new instance holding the OBS version of the spec_item
    
    edited_spec_item = SpecItem.objects.get(id=edited_spec_item_id) # Retrieve original spec_item instance
    edited_spec_item.previous = spec_item   # Now spec_item points to newly-created OBS copy 
    edited_spec_item.status = 'MOD'
    return edited_spec_item     # Return the modified instance of spec_item


def create_and_init_spec_item(request, cat, init_dict):
    """ Create a spec_item of category 'cat' and initialize it with the values in init_dict """
    new_spec_item = SpecItem()
    for attr in configs['cats'][cat]['attrs']:
        if attr in init_dict:
            setattr(new_spec_item, attr, init_dict[attr])
    return new_spec_item


def remove_spec_item(request, spec_item):
    """ Delete the spec_item from the database together with its category-specific items """
    try:
        spec_item.delete()
    except Exception as e:
        messages.error(request, 'Failure to delete ' + str(spec_item) + \
                                ', possibly because other spec_items reference it: ' + str(e))
        return
     
     
def remove_spec_item_aliases(request, spec_item):
    """ Remove spec_items attached to argument spec_items but in other ValSets """
    if spec_item.p_children != None:    
        for child in spec_item.p_children.all():
            if child.val_set.name != 'Default':
                remove_spec_item(request, child)
  
  
def mark_spec_item_aliases_as_del(request, spec_item):
    """ Set status of spec_items attached to argument spec_item but in other ValSet to DEL """           
    if spec_item.p_children != None:    
        for child in spec_item.p_children.all():
            if child.val_set.name != 'Default':
                child.status = 'DEL'
                child.save()

          
def update_dom_name_in_val_set(spec_item):
    """ 
    Propagate a change in domain:name in spec_item to spec_items in other ValSets.
    This function assumes that spec_item is in the Default ValSet
    """
    if spec_item.p_children != None:    
        for child in spec_item.p_children.all():
            if child.val_set.name != 'Default':
                child.name = spec_item.name
                child.domain = spec_item.domain
                child.save()
    
    
