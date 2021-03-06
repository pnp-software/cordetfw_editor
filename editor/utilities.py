import os
import re
import cexprtk
import logging
from django.contrib import messages
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user
from django.contrib.auth.models import User
from django.forms.models import model_to_dict
from django.db.models import ForeignKey
from datetime import datetime
from editor.models import SpecItem, ProjectUser, Application, Release, Project, ValSet
from editor.configs import configs
from .choices import HISTORY_STATUS, SPEC_ITEM_CAT, REQ_KIND, DI_KIND, \
                 MODEL_KIND, PCKT_KIND, VER_ITEM_KIND, REQ_VER_METHOD, VER_STATUS

# Max recursion depth for expression in data item value fields
EVAL_MAX_REC = 10   

# Regular expression pattern for internal references in the database
pattern_db = re.compile('#(iref):([0-9]+)')     

# Regular expression pattern for plain reference in export format
pattern_ref_exp = re.compile('([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)')     

# Create regular expression pattern for references in edited fields
s = ''
for cat_desc in SPEC_ITEM_CAT:
    s = s+cat_desc[0]+'|'
pattern_edit = re.compile('#('+s[:-1]+'):([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)')

logger = logging.getLogger(__name__)


def frmt_string(s):
    """ Format string for output to a Latex text file. """
    replacements = [['\r\n', ' \\newline '],
                ['\r', ' \\newline '],
                ['\n', ' \\newline '],
                ['%', '\\%'],
                ['&', '\\&'],
                ['#', '\\#'],
                ['^', "\\textasciicircum"],
                ['~', "\\textasciitilde"],
                ['_', "\\_"]]
    for old, new in replacements:
       s = s.replace(old, new)    
    return s


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


def get_list_refs(s):
    """
    Return the list of references in the argument string.
    A reference has the form: #<cat>:<domain>:<name>.
    The function returns a list of triplets: <cat>:<domain>:<name>.
    """
    return re.findall("#([a-z]+:[a-zA-Z0-9_]+:[a-zA-Z0-9_]+)", s)
    
    
def convert_edit_to_db(s):
    """
    The argument is a text field in edit representation (with internal
    references in the format '#cat:domain:name'). The function converts
    it to database representation (internal references become: iref:<id>).
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_edit.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        id = SpecItem.objects.exclude(status='OBS').exclude(status='DEL').get(domain=ref[1], name=ref[2]).id
        s_mod = s[:match.start()] + '#iref:' + str(id)
    except ObjectDoesNotExist:
        logger.warning('Non-existent internal reference: '+str(ref))
        s_mod = s[:match.start()] + ref[0] + ':' + ref[1] + ':' + ref[2]
    
    return s_mod + convert_edit_to_db(s[match.end():])
    
    
def convert_exp_to_db(s):
    """
    The argument is a plain reference field in export representation 
    (the reference is represented by the string domain:name). 
    The function converts it to database representation.
    Invalid references raise an exception which must be handled by the caller.
    """
    m = pattern_ref_exp.match(s)
    ref = m.group().split(':')
    return SpecItem.objects.exclude(status='OBS').exclude(status='DEL').get(domain=ref[0], name=ref[1])
    

def convert_db_to_edit(s):
    """
    The argument string is a text field read from the database. It
    contains internal references in the format #iref:n.
    The internal references are replaced with: #<cat>:<domain>:<name>.
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_db.search(s)
    if match == None:
      return s
    ref = match.group().split(':')
    try:
      if ref[0] == '#iref': 
        item = SpecItem.objects.get(id=ref[1]) 
        s_mod = s[:match.start()]+'#'+item.cat+':'+item.domain+':'+item.name
      else:
        s_mod = s[:match.start()]+ref[0]+':'+ref[1]
    except ObjectDoesNotExist:
      s_mod = s[:match.start()]+'ERROR:ERROR'
    return s_mod + convert_db_to_edit(s[match.end():])


def convert_db_to_latex(s):
    """ 
    The argument string is a text field read from the database. 
    Internal references in the form #iref:n are converted to the
    for: <domain>:<name> and special latex characters are escaped.
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_db.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        if ref[0] == '#iref': 
            item = SpecItem.objects.get(id=ref[1])
            s_mod = frmt_string(s[:match.start()] + item.domain+':'+item.name)
        else:
            s_mod = frmt_string(s[:match.start()]+ref[0]+':'+ref[1])
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+'ERROR:ERROR'
       
    return s_mod + convert_db_to_latex(s[match.end():])


def convert_db_to_display(s, n):
    """
    The string s is a text field read from the database. It
    contains internal references in the form #iref:n. References in
    the argument string are replaced with <domain>:<name> and hyperlinks.
    Invalid references are replaced with: ERROR:ERROR.
    This function is called recursively to handle all references in string s.
    The argument n is the depth of recursion. 
    The input string is first passed through escape() to sanitize any potentially
    malicious html code entered by the user.
    """
    match = pattern_db.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        if ref[0] == '#iref': 
            item = SpecItem.objects.get(id=ref[1])
            project_id = str(item.project.id) if item.project != None else '0'
            application_id = str(item.application.id) if item.application != None else '0'
            target = '/editor/'+item.cat+'/'+project_id+'/'+application_id+'/'+str(item.val_set.id)+'/'+\
                    item.domain+'\list_spec_items'
            s_mod = s[:match.start()]+'<a href=\"'+target+'#'+item.domain+':'+item.name+'\" title=\"'+item.domain+': '+item.title+'\">'+item.name+'</a>'
        else:
            s_mod = s[:match.start()]+ref[0]+':'+ref[1]  
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+ref[0]+':'+'ERROR:ERROR'
        
    return s_mod + convert_db_to_display(s[match.end():], n+1)
 

def render_for_eval(s, n):
    """ 
    String s is a text field read from the database. 
    It contains internal references in the form #iref:n. This function
    assumes that all such references are pointing to data items and 
    replaces these references with the numerical values of the data items.
    This function is called recursively to handle all references in string s.
    The argument n is the depth of recursion. This is limited to EVAL_MAX_REC.
    If the function finds an invalid reference or a reference to a 
    specification item which is not a data item, it returns the string
    unchanged.
    """
    if n > EVAL_MAX_REC:
        logger.warning('Exceeded recursion depth when evaluating '+s)
        return s

    match = pattern_db.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        if ref[0] == '#iref': 
            item = SpecItem.objects.get(id=ref[1])
        else:
            return s
    except ObjectDoesNotExist:
        return s

    s_mod = s[:match.start()] + render_for_eval(item.value, n+1)
    return s_mod + render_for_eval(s[match.end():], n)


def eval_di_value(s):
    """
    The argument string is assumed to hold a mathematical expression expressed 
    in terms of references to data items.
    The function first replaces the references to the data items with their 
    values (this is done with function render_for_eval)
    and then it attempts to evaluate the resulting expression using package cexprtk.
    """
    se = render_for_eval(s, 1)
    try:
        return str(cexprtk.evaluate_expression(se,{}))
    except:
        return s
        
        
def spec_item_to_edit(spec_item):
    """ 
    The argument is a specification item and the output is a dictionary representing the specification
    item in a format suitable for display in a form.
    """
    dic = model_to_dict(spec_item)
    for key, value in configs[spec_item.cat]['attrs'].items():
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
    cat_attrs = configs[spec_item.cat]['attrs']
    dic = {}
    for key, value in configs[spec_item.cat]['attrs'].items():
        label = cat_attrs[key]['label'].replace(' ','')
        if value['kind'] == 'ref_text':
            dic[label] = frmt_string(convert_db_to_latex(getattr(spec_item, key)))
        elif value['kind'] == 'spec_item_ref':
            dic[label] = frmt_string(str(getattr(spec_item, key))).split(' ')[0]
        elif value['kind'] == 'plain_text':
            dic[label] = frmt_string(str(getattr(spec_item, key)))
        else:
            dic[label] = frmt_string(str(getattr(spec_item, key)))
    
    if spec_item.cat == 'DataItem':
        dic['NValue'] = eval_di_value(spec_item.value)

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
    cat_attrs = configs[spec_item.cat]['attrs']
    dic = {}
    for key, value in configs[spec_item.cat]['attrs'].items():
        if value['kind'] == 'ref_text':
            dic[cat_attrs[key]['label']] = convert_db_to_edit(getattr(spec_item, key))
        elif value['kind'] == 'spec_item_ref':
            dic[cat_attrs[key]['label']] = str(getattr(spec_item, key)).split(' ')[0]
        else:
            dic[cat_attrs[key]['label']] = str(getattr(spec_item, key))
    return dic
        
            
def export_to_spec_item(imp_dict, spec_item):
    """ 
    Argument imp_dict is a dictionary created by reading a line in a 
    plain import file.
    The function converts the dictionary entries to db format and uses them 
    to initialize the argument spec_item.
    Only attributes which are imported are initialized.
    The function will raise an exception if one of the fields expected
    in the dictionary is not found. 
    """
    cat_attrs = configs[spec_item.cat]['attrs']
    for key, value in configs[spec_item.cat]['attrs'].items():
        if key == 'val_set':
            spec_item.val_set = ValSet.objects.get(name=imp_dict[cat_attrs[key]['label']])
        elif key == 'owner':
            continue
        elif value['kind'] == 'ref_text':
            setattr(spec_item, key, convert_edit_to_db(imp_dict[cat_attrs[key]['label']]))
        elif value['kind'] == 'spec_item_ref':
            setattr(spec_item, key, convert_exp_to_db(imp_dict[cat_attrs[key]['label']]))
        else:
            setattr(spec_item, key, imp_dict[cat_attrs[key]['label']])


def get_user_choices():
    """ Return a list of pairs (id, user) representing the users in the system """
    users = User.objects.all().order_by('username').values_list('id','username', 'first_name', 'last_name')
    user_choices = []
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
  
  
def get_p_link_choices(cat, project_id, p_parent_id):
    """ Return the range of choices for the 'p_link' attribute of a specification of a given category """
    if p_parent_id != None:
        return SpecItem.objects.filter(id=int(p_parent_id)) 
    if cat == 'DataItem':
        q1 = SpecItem.objects.filter(project_id=project_id, cat='DataItemType').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')        
        q2 = SpecItem.objects.filter(project_id=project_id, cat='EnumType').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name') 
        return q1 | q2
    if cat == 'VerLink':
        return SpecItem.objects.filter(project_id=project_id, cat='VerItem').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
    return SpecItem.objects.none()
    
    
def get_s_link_choices(cat, project_id, s_parent_id):
    """ Return the range of choices for the 's_link' attribute of a spec_item of a given category """
    if s_parent_id != None:
        return SpecItem.objects.filter(id=int(s_parent_id))
    if cat == 'EnumValue':
        return SpecItem.objects.filter(project_id=project_id, cat='EnumType'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')
    if cat == 'VerLink':
        return SpecItem.objects.filter(project_id=project_id).exclude(cat='VerItem'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('cat', 'domain', 'name')
                        
                        
    return SpecItem.objects.none()
    
    
def get_expand_items(cat, project_id, val_set_id, expand_id, expand_link):
    """ 
    Get the list of expand_items for the spec_item whose ID is expand_id.
    The expand_link is either 's_link' or 'p_link'    
    If the expand_link is 's_link', the expand_items the spec_items whose
    s_link points to expand_id (i.e. they are the children of expand_id 
    according to s_link).
    If the expand_link is 'p_link', the expand_items the spec_items whose
    p_link points to expand_id (i.e. they are the children of expand_id 
    according to p_link).
    The information in configs[cat]['expand'] determines whether or not
    a given spec_item has s_link or p_link children. 
    """
    if configs[cat]['expand'][expand_link] == 'None':
        return None
    expand_items = None
    if expand_link == 's_link':
        expand_items = SpecItem.objects.filter(project_id=project_id, \
                            cat=configs[cat]['expand'][expand_link], \
                            s_link_id=expand_id, \
                            val_set_id=val_set_id).\
                            exclude(status='DEL').exclude(status='OBS').order_by('domain','name')
    if expand_link == 'p_link':
        expand_items = SpecItem.objects.filter(project_id=project_id, \
                            cat=configs[cat]['expand'][expand_link], \
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
                     updated_at = datetime.now(),
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
                     updated_at = datetime.now(),
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
    new_dir_path = os.path.join(dir_path,name+datetime.now().strftime('%Y_%m_%d_%H_%M_%S'))
    try:  
        os.mkdir(new_dir_path)  
    except OSError as e:  
        messages.error(request, 'Failure to create export directory at '+exp_dir+': '+str(e))
        return ''
    return new_dir_path

