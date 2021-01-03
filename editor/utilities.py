import re
import cexprtk
import logging
from django.contrib import messages
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user
from django.contrib.auth.models import User
from django.db.models import ForeignKey
from datetime import datetime
from editor.models import SpecItem, ProjectUser, Application, Release, Project

EVAL_MAX_REC = 10
MAX_DESC_LEN = 40
pattern_db = re.compile("#(di|mod|req|eVal):([0-9_]+)")
pattern_text = re.compile("#([a-z]+:[a-zA-Z0-9_]+:[a-zA-Z0-9_]+)")
pattern_di = re.compile("#(di):([0-9_]+)")
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
    

def render_for_edit(s):
    """
    Replace references in the argument string with: <domain>:<name>.
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_db.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        if ref[0] == '#di':
            item = DataItem.objects.get(id=ref[1])
            name = item.name
            domain = item.domain
        elif ref[0] == '#mod':
            item = FwProfileModel.objects.get(id=ref[1])
            name = item.name
            domain = item.domain
        elif ref[0] == '#req':
            item = Requirement.objects.get(id=ref[1])
            name = item.name
            domain = item.domain
        else:
            name = 'ERROR'
            domain = 'ERROR'                  
        s_mod = s[:match.start()]+ref[0]+':'+domain+':'+name
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+ref[0]+':'+'ERROR:ERROR'
    return s_mod + render_for_edit(s[match.end():])


def render_for_export(s):
    """
    Replace references in the argument string with: <name>.
    Invalid references are replaced with: ERROR:ERROR.
    """
    match = pattern_db.search(s)
    if match == None:
        return s
    ref = match.group().split(':')
    try:
        if ref[0] == '#di':
            item = DataItem.objects.get(id=ref[1])
            s_mod = s[:match.start()] + item.name
        elif ref[0] == '#mod':
            item = FwProfileModel.objects.get(id=ref[1])
            s_mod = s[:match.start()] + '\\ref{mod:'+item.name+'}'
        elif ref[0] == '#req':
            item = Requirement.objects.get(id=ref[1])
            s_mod = s[:match.start()] + item.domain+'-'+item.name
        elif ref[0] == '#eVal':
            item = EnumDataType.objects.get(id=ref[1])
            s_mod = s[:match.start()] + item.name
        else:
            s_mod = s[:match.start()]+ref[0]+':'+'ERROR:ERROR'
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+ref[0]+':'+'ERROR:ERROR'
        
    return s_mod + render_for_export(s[match.end():])


def render_for_display(s, n):
    """
    TBD
    Replace references in the argument string with: <domain>:<name> and hyperlinks.
    Invalid references are replaced with: ERROR:ERROR.
    This function is called recursively to handle all references in string s.
    The argument n is the depth of recursion. 
    The input string is first passed through escape() to sanitize any potentially
    malicious html code entered by the user.
    """

    return s



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
             
             
def get_list_of_domains(model, application_id, project_id):
    """ 
    Return the list of domains for the specification items in the argument model. If application_id is zero,
    then the model are filter by project; otherwise they are filter by application.
     """             
    listOfDomains = ['All_Domains']
    if application_id == 0:
        for domain in model.objects.filter(project_id=project_id).exclude(status='DEL'). \
                                        exclude(status='OBS').order_by('domain').values_list('domain').distinct():
            listOfDomains.append(domain[0])
    else:
        for domain in model.objects.filter(application_id=application_id).exclude(status='DEL'). \
                                        exclude(status='OBS').order_by('domain').values_list('domain').distinct():
            listOfDomains.append(domain[0])
    return listOfDomains     
                       
 
def do_application_release(request, application, description, is_proj_release = False):
    """ 
    Do an application release by updating the status of the application requirements, models and test cases.
    """
    requirements = Requirement.objects.filter(application_id=application.id)
    for requirement in requirements:
        if (requirement.status == 'NEW') or (requirement.status == 'MOD'):
            requirement.status = 'CNF'
            requirement.save()

    models = FwProfileModel.objects.filter(application_id=application.id)
    for model in models:
        if (model.status == 'NEW') or (model.status == 'MOD'):
            model.status = 'CNF'
            model.save()

    test_cases = TestCase.objects.filter(application_id=application.id)
    for test_case in test_cases:
        if (test_case.status == 'NEW') or (test_case.status == 'MOD'):
            test_case.status = 'CNF'
            test_case.save()
            
    if application.release == None:     # Application has just been created
        new_application_version = 0
        previous = None
    elif not is_proj_release:           # Application release is done as part of a project release
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
    data_items = DataItem.objects.filter(project_id=project.id)
    for data_item in data_items:
        if (data_item.status == 'NEW') or (data_item.status == 'MOD'):
            data_item.status = 'CNF'
            data_item.save()

    data_types = DataType.objects.filter(project_id=project.id)
    for data_type in data_types:
        if (data_type.status == 'NEW') or (data_type.status == 'MOD'):
            data_type.status = 'CNF'
            data_type.save()

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
            
    
