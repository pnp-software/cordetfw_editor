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
from datetime import datetime
from editor.models import SpecItem, ProjectUser, Application, Release, Project, ValSet
from editor.configs import configs
from editor.choices import SPEC_ITEM_CAT
                     
# Regex pattern for internal references to specification items as they
# are stored in the database (e.g. '#iref:1234')
pattern_db = re.compile('#(iref):([0-9]+)')     

# Regex pattern for plain references to specification items as they
# rendered in export representation (e.g. 'dom:name')
pattern_ref_exp = re.compile('([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)')     

# Regex pattern for internal references to specification items as they
# rendered in edit representation (e.g. '#cat:dom:name')
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


def convert_db_to_display(s, n):
    """
    The string s is a text field read from the database. It
    contains internal references in the form #iref:n. References in
    the argument string are replaced with <domain>:<name> and hyperlinks.
    Invalid references are replaced with: ERROR:ERROR.
    This function is called recursively to handle all references in string s.
    The argument n is the depth of recursion. 
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
            s_mod = s[:match.start()]+'<a href=\"'+target+'#'+item.domain+':'+item.name+'\" title=\"'+item.title+'\">'+\
                    item.domain+':'+item.name+'</a>'
        else:
            s_mod = s[:match.start()]+ref[0]+':'+ref[1]  
    except ObjectDoesNotExist:
        s_mod = s[:match.start()]+ref[0]+':'+'ERROR:ERROR'
        
    return s_mod + convert_db_to_display(s[match.end():], n+1)


def conv_do_nothing(context, item, name):
    """ Returns the value of attribute 'name' of spec_item 'item' without change """
    return getattr(item, name)


def conv_db_disp_plain_ref(context, item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute value contains internal references ('ref_text' content kind)
    """
    return str(getattr(item, name))


def conv_db_disp_date(context, item, name):
    """ TBD """
    return s


def conv_db_disp_ref_text(context, item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute value contains internal references ('ref_text' content kind)
    """
    s = getattr(item, name)
    return convert_db_to_display(s, 1)
    
    
def conv_db_disp_spec_item_ref(context, spec_item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute is a link to another spec_item ('spec_item_ref' content kind)
    """
    application_id = context['application_id']
    default_val_set_id = context['default_val_set_id']
    sel_dom = context['sel_dom']
    spec_item_link = getattr(spec_item, name)
    
    s_name = spec_item_link.domain + ':' + spec_item_link.name
    s_href = '/editor/'+spec_item_link.cat+'/'+str(spec_item.project.id)+'/'+str(application_id)+\
             '/'+str(default_val_set_id)+'/'+spec_item_link.domain+'/list_spec_items#'+s_name
    s_title = spec_item_link.title + ':' + spec_item_link.desc
    
    return '<a href=\"'+s_href+'\" title=\"'+s_title+'\">'+s_name+'</a>'
   
 
def conv_db_disp_eval_ref(context, item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute value contains internal references ('ref_text' content kind)
    """
    s = getattr(item, name)
    conv_s = convert_db_to_display(s, 1)
    if conv_s != s:
        nval = eval_di_value(s)
        return conv_s + ' = ' + nval
    else:
        return s
   
   
def convert_edit_to_db(project, s):
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
        id = SpecItem.objects.exclude(status='OBS').exclude(status='DEL').\
                get(project_id=project.id, cat=ref[0][1:], domain=ref[1], name=ref[2]).id
        s_mod = s[:match.start()] + '#iref:' + str(id)
    except ObjectDoesNotExist:
        logger.warning('Non-existent internal reference: '+str(ref))
        s_mod = s[:match.start()] + ref[0] + ':' + ref[1] + ':' + ref[2]
    
    return s_mod + convert_edit_to_db(project, s[match.end():])
    
    
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
    if n > configs['General']['max_depth']:
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
        
        
