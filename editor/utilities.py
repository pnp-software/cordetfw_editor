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
from editor.models import SpecItem, ProjectUser, Application, Release, Project
from editor.configs import configs
from .choices import HISTORY_STATUS, SPEC_ITEM_CAT, REQ_KIND, DI_KIND, DIT_KIND, \
                 MODEL_KIND, PCKT_KIND, VER_ITEM_KIND, REQ_VER_METHOD

# Max recursion depth for expression in data item value fields
EVAL_MAX_REC = 10   

# Regular expression pattern for internal references in the database
pattern_db = re.compile("#(iref):([0-9]+)")     

# Create regular expression pattern for references in edited fields
s = ''
for cat_desc in SPEC_ITEM_CAT:
    s = s+cat_desc[0]+'|'
pattern_text = re.compile('#('+s[:-1]+'):([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)')

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
    
    
def render_for_db(s):
    """
    Replace internal references in the argument string with: iref:<id>.
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_text.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        id = SpecItem.objects.exclude(status='OBS').exclude(status='DEL').get(domain=ref[1], name=ref[2]).id
        s_mod = s[:match.start()] + '#iref:' + str(id)
    except ObjectDoesNotExist:
        logger.warning('Non-existent internal reference: '+str(ref))
        s_mod = s[:match.start()] + ref[0] + ':' + ref[1] + ':' + ref[2]
    
    return s_mod + render_for_db(s[match.end():])
    

def render_for_edit(s):
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
    return s_mod + render_for_edit(s[match.end():])


def render_for_export(s):
    """ 
    The argument string is a text field read from the database. 
    Internal references in the form #iref:n are converted to the
    for: <domain>:<name>. 
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_db.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        if ref[0] == '#iref': 
            item = SpecItem.objects.get(id=ref[1])
            s_mod = s[:match.start()] + item.dom+':'+item.name
        else:
            s_mod = s[:match.start()]+ref[0]+':'+ref[1]  
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+'ERROR:ERROR'
       
    return s_mod + render_for_export(s[match.end():])


def render_for_display(s, n):
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
    if n == 1:  # If the function has been called by the application
        s = escape(s)
    
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
            s_mod = s[:match.start()]+'<a href=\"'+target+'\" title=\"'+item.title+'\">'+item.domain+':'+item.name+'</a>'
        else:
            s_mod = s[:match.start()]+ref[0]+':'+ref[1]  
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+ref[0]+':'+'ERROR:ERROR'
        
    return s_mod + render_for_display(s[match.end():], n+1)
 

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
    The argument string is assumed to hold a mathematical expression expressed in terms of references to data items.
    The function first replaces the references to the data items with their values (this is done with function render_for_eval)
    and then it attempts to evaluate the resulting expression using package cexprtk.
    """
    se = render_for_eval(s, 1)
    try:
        return str(cexprtk.evaluate_expression(se,{}))
    except:
        return s
        
        
def model_to_form(spec_item):
    """ 
    The argument is a specification item and the output is a dictionary representing the specification
    item in a format suitable for display in a form.
    """
    dic = model_to_dict(spec_item)
    for key, value in configs[spec_item.cat]['attrs'].items():
        if value['int_ref'] == True:
            dic[key] = render_for_edit(dic[key])
    return dic
    
    
def model_to_export(spec_item):
    """ 
    The argument is a specification item and the output is a dictionary as follows: 
    - Key: label of the fields to be exported
    - Value: value of field to be exported in a format suitable for use in a latex doc
    The field label is the same as the field name. Only fields in the 
    """
    dic = {}
    cat_attrs = configs[spec_item.cat]['attrs']
    dic['id'] = str(spec_item.id)
    dic['cat'] = frmt_string(spec_item.cat)
    dic['name'] = frmt_string(spec_item.name)
    dic['domain'] = frmt_string(spec_item.domain)
    dic['project'] = frmt_string(str(spec_item.project))
    dic['application'] = frmt_string(str(spec_item.application))
    dic['title'] = frmt_string(spec_item.title)
    dic['desc'] = frmt_string(render_for_export(spec_item.desc))
    dic['value'] = frmt_string(render_for_export(spec_item.value))
    if 'dim' in cat_attrs:
        dic['dim'] = str(spec_item.dim)
    if 'parent' in cat_attrs:
        dic[cat_attrs['parent']['label']] = frmt_string(str(spec_item.parent))
    dic['owner'] = frmt_string(str(spec_item.owner))
    dic['status'] = str(spec_item.status)
    dic['updated_at'] = spec_item.updated_at.strftime('%d-%m-%Y %H:%M')
    dic['previous'] = str(spec_item.previous.id) if (spec_item.previous != None) else 0
    dic['justification'] = frmt_string(render_for_export(spec_item.justification))
    dic['remarks'] = frmt_string(render_for_export(spec_item.remarks))
    dic['val_set'] = frmt_string(str(spec_item.val_set))
    if 'kind' in cat_attrs:
        dic['kind'] = str(spec_item.kind)
    
    if spec_item.cat == 'Requirement':
        dic['ver_method'] = frmt_string(render_for_export(spec_item.req.ver_method))
 
    return dic
        

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
        
        
def get_kind_choices(cat):
    """ Return the range of choices for the 'kind' attribute of a specification of a given category """
    if cat == 'Requirement':
       return REQ_KIND
    elif cat == 'DataItem':
       return DI_KIND
    elif cat == 'DataItemType':
       return DIT_KIND
    elif cat == 'Model':
       return MODEL_KIND
    elif cat == 'Packet':
       return PCKT_KIND
    elif cat == 'PacketPar':
       return PCKT_PAR_KIND
    elif cat == 'VerItem':
       return VER_ITEM_KIND
    return (("INV","Invalid"),)
  
def get_parent_choices(cat, project_id):
    """ Return the range of choices for the 'parent' attribute of a specification of a given category """
    if cat == 'EnumItem':
        pcl = SpecItem.objects.filter(project_id=project_id, cat='DataItemType', kind='ENUM').\
                                    exclude(status='DEL').exclude(status='OBS').order_by('name').values_list('id','name','title')
        return [(pc[0], pc[1]+' ('+pc[2]+')') for pc in pcl]                            
    if cat == 'DataItem':
        pcl = SpecItem.objects.filter(project_id=project_id, cat='DataItemType').\
                                    exclude(status='DEL').exclude(status='OBS').order_by('name').values_list('id','name','title')
        return [(pc[0], pc[1]+' ('+pc[2]+')') for pc in pcl] 
        
    return [('Invalid','Invalid')]
    
         
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
    



