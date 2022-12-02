import re
import json
import cexprtk
import logging
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from editor.models import SpecItem, Project, ValSet
from editor.markdown import markdown_to_html, markdown_to_latex

with open(settings.BASE_DIR + '/editor/static/json/configs.json') as config_file:
    configs = json.load(config_file)

# Regex pattern for internal references to specification items as they
# are stored in the database (e.g. '#iref:1234')
pattern_db = re.compile('#(iref):([0-9]+)')

# Regex pattern for plain references to specification items as they
# rendered in export representation (e.g. 'dom:name')
pattern_ref_exp = re.compile('([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)')

logger = logging.getLogger(__name__)


def get_pattern_edit(project_id):
    """
    Return the regex expression which catches the references to specification items in
    edit representation (i.e. of the form '#cat:dom:name'). The regex expression depends
    on the project because each project has a different set of categories.
    """
    project = Project.objects.get(id=project_id)
    s = project.cats.replace(',', '|')
    return re.compile('#('+s+'):([a-zA-Z0-9_]+):([a-zA-Z0-9_]+)')


def frmt_string(s):
    """ Format string for output to a Latex text file. """
    replacements = [['\r\n', ' \\newline '],
                ['\r', ' \\newline '],
                ['\n', ' \\newline '],
                ['%', '\\%'],
                ['&', '\\&'],
                ['#', '\\#'],
                ['^', "\\textasciicircum "],
                ['~', "\\textasciitilde "],
                ['_', "\\_"]]
    for old, new in replacements:
       s = s.replace(old, new)    
    return s


def convert_db_to_display(s):
    """
    The string s is a text field read from the database. It
    contains markdown text and internal references in the form #iref:n. 
    Internal references are replaced with <domain>:<name> and hyperlinks.
    If the target of the hyperlink is an item which is either NEW, MODified or
    DELeted, the hyperlink is in red font.
    Invalid references are replaced with: ERROR:n.
    Markdown text is converted to html.
    The output of this function is guaranteed to be safe for displat in an
    HTML page because the text read from the database is escaped.
    """
    def iref_to_html(match):
        """ Function called by sub() to replace occurrences of the #iref:n regex pattern """
        try:
            item = SpecItem.objects.get(id=match.group(2))
            project_id = str(item.project.id) if item.project != None else '0'
            application_id = str(item.application.id) if item.application != None else '0'
            target = '/editor/'+item.cat+'/'+project_id+'/'+application_id+'/'+str(item.val_set.id)+'/'+\
                    item.domain+'\list_spec_items'
            title_attrs = configs['cats'][item.cat]['short_desc']['href_tip']
            title = ''
            for title_attr in title_attrs:
                title = title + configs['cats'][item.cat]['attrs'][title_attr]['label'] +': '+\
                        escape(convert_db_to_edit(getattr(item, title_attr))) + '&#13;'
            if item.status in ['DEL', 'MOD', 'NEW']:
                title = 'Status: ' + escape(item.status) + '&#13;' + title
                iref_html = '<a href=\"' + escape(target) + '#' + escape(item.domain) + ':' + \
                            escape(item.name) + '\" class="link-danger" title=\"' + title + '\">' + \
                            escape(item.domain) + ':' + escape(item.name) + '</a>'
            else: 
                iref_html = '<a href=\"' + escape(target) + '#' + escape(item.domain) + ':' + \
                            escape(item.name) + '\" title=\"' + title + '\">' + \
                            escape(item.domain) + ':' + escape(item.name) + '</a>'
            return iref_html
        except ObjectDoesNotExist:
            return 'ERROR:'+match.group(2)
    s_iref = pattern_db.sub(iref_to_html, s)
    return markdown_to_html(s_iref)
    

def conv_do_nothing(context, item, name):
    """ Returns the value of attribute 'name' of spec_item 'item' without change """
    return getattr(item, name)


def conv_db_disp_plain_ref(context, item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute value only contains plain text
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
    return convert_db_to_display(s)
    
    
def conv_db_disp_table(context, item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute value contains a json description of a table.
    TBD: the table is simply rendered as a json string with internal references and mark-up resolved.
    """
    s = getattr(item, name)     # 's' is a json object
    return convert_db_to_display(str(s))
    
    
def conv_db_disp_spec_item_ref(context, spec_item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute is a link to another spec_item ('spec_item_ref' content kind).
    If the target spec_item is MODified or DELeted, then its hyperlink is in red.
    The output of this function is guaranteed to be safe for displat in an
    HTML page because the text read from the database is escaped.
    """
    spec_item_link = getattr(spec_item, name)
    if spec_item_link == None:
        return ''
    cat = spec_item_link.cat
    application_id = context['application_id'] if configs['cats'][cat]['level'] == 'application' else 0
    default_val_set_id = context['default_val_set_id']
    sel_val = context['sel_val']
    s_name = spec_item_link.domain + ':' + spec_item_link.name
    s_href = '/editor/'+cat+'/'+str(spec_item.project.id)+'/'+str(application_id)+\
             '/'+str(default_val_set_id)+'/'+spec_item_link.domain+'/list_spec_items#'+s_name

    title_attrs = configs['cats'][spec_item_link.cat]['short_desc']['href_tip']
    s_title = ''
    for title_attr in title_attrs:
        s_title = s_title + configs['cats'][spec_item_link.cat]['attrs'][title_attr]['label'] +': '+\
                  escape(convert_db_to_edit(getattr(spec_item_link, title_attr))) + '&#13;'
    
    if spec_item_link.status in ['MOD', 'DEL', 'NEW']:
        s_title = 'Status: ' + spec_item_link.status + '&#13;' + s_title
        return '<a href=\"' + escape(s_href) + '\" class="link-danger" title=\"' + \
               s_title + '\">' + escape(s_name) + '</a>'
    else:
        return '<a href=\"' + escape(s_href) + '\" title=\"' + s_title + \
               '\">' + escape(s_name) + '</a>'
   
 
def conv_db_disp_eval_ref(context, item, name):
    """ 
    Convert attribute 'name' of spec_item 'item' from database to display representation
    on the assumption that the attribute value is of 'eval_ref' kind)
    """
    s = getattr(item, name)
    conv_s = convert_db_to_display(s)
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
    Invalid references are left unchanged but an entry is made
    in the logger.
    """
    def edit_to_iref(match):
        """ Function called by sub() to replace occurrences of the #iref:n regex pattern """
        try:
            default_val_set = ValSet.objects.filter(project_id=project.id).get(name='Default')
            id = SpecItem.objects.exclude(status='OBS').exclude(status='DEL').\
                    get(project_id=project.id, cat=match.group(1), domain=match.group(2), \
                        name=match.group(3), val_set=default_val_set.id).id
            return '#iref:' + str(id)
        except ObjectDoesNotExist:
            logger.warning('Non-existent internal reference: '+str(match.group()))
            return '#' + match.group(1) + ':' + match.group(2) + ':' + match.group(3)
    
    s_db = get_pattern_edit(project.id).sub(edit_to_iref, s)
    return s_db
    
    
def convert_exp_to_db(project, s):
    """
    The argument is a plain reference field in export representation 
    (the reference is represented by the string domain:name). 
    The function converts it to database representation.
    If the field is empty or the reference is invalid, None is returned.
    """
    try:
        m = pattern_ref_exp.match(s)
        ref = m.group().split(':')
        return SpecItem.objects.exclude(status='OBS').exclude(status='DEL').\
                            get(project_id=project.id, domain=ref[0], name=ref[1])
    except Exception as e:
        return None
    

def convert_db_to_edit(s):
    """
    The argument string is a text field read from the database. It
    contains internal references in the format #iref:n.
    The internal references are replaced with: #<cat>:<domain>:<name>.
    Invalid references are replaced with: ERROR:n.
    """
    def iref_to_edit(match):
        """ Function called by sub() to replace occurrences of the #iref:n regex pattern """
        try:
            item = SpecItem.objects.get(id=match.group(2))
            return '#'+item.cat+':'+item.domain+':'+item.name
        except ObjectDoesNotExist:
            return 'ERROR:'+match.group(2)
    
    return pattern_db.sub(iref_to_edit, s)


def convert_db_to_latex(s):
    """ 
    The argument string is a text field read from the database which 
    contains markdown text and internal references.
    Internal references in the form #iref:n are converted to the
    for: <domain>:<name> and special latex characters are escaped.
    Invalid references are replaced with: ERROR:n.
    Markdown text is converted to latex.
    """
    def iref_to_latex(match):
        """ Function called by sub() to replace occurrences of the #iref:n regex pattern """
        try:
            item = SpecItem.objects.get(id=match.group(2))
            return item.domain+':'+item.name
        except ObjectDoesNotExist:
            return 'ERROR:'+match.group(2)
    
    s_iref = pattern_db.sub(iref_to_latex, s)
    s_md = markdown_to_latex(s_iref)
    return frmt_string(s_md)
 

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
    if n > configs['general']['max_depth']:
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
        
        
