import os
import re
import json
import logging
from django.contrib import messages
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user
from django.contrib.auth.models import User
from django.forms.models import model_to_dict
from django.db.models import ForeignKey
from django.conf import settings
from datetime import datetime
from editor.models import SpecItem, ProjectUser, Application, Release, Project, ValSet
       
with open(settings.BASE_DIR + '/editor/static/json/configs.json') as config_file:
    configs = json.load(config_file)
      
# Regex pattern for text emphasis markdown
# Bold is: '**...**'
# Underline is: '++...++'
# Italicize is: '__...__'
# Teletype is: '``...``'
pattern_emphasis = re.compile('(\*\*)(.+)(\*\*)|(\+\+)(.+)(\+\+)|(__)(.+)(__)|(``)(.+)(``)')     

pattern_bullets = re.compile('((\n^-\s.+$)+)', re.MULTILINE)    

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
def emphasis_to_html(match):
    if match.group(1) != None:
        return '<b>'+match.group(2)+'</b>'
    elif match.group(4) != None:
        return '<u>'+match.group(5)+'</u>'
    elif match.group(7) != None:
        return '<i>'+match.group(8)+'</i>'
    elif match.group(10) != None:
        return '<code>'+match.group(11)+'</code>'

# ----------------------------------------------------------------------
def bulleted_list_to_html(match):
    s1 = match.group(1).replace('\n','')
    s2 = s1.replace('\r','')
    bullet_items = s2.split('- ')
    s_html = '<ul>'
    for i, bullet_item in enumerate(bullet_items): 
        if i>0:
            s_html = s_html + '<li>'+bullet_item+'</li>'
    return s_html + '</ul>'

# ----------------------------------------------------------------------
def emphasis_to_latex(match):
    if match.group(1) != None:
        return '\\textbf{'+match.group(2)+'}'
    elif match.group(4) != None:
        return '\\underline{'+match.group(5)+'}'
    elif match.group(7) != None:
        return '\\textit{'+match.group(8)+'}'
    elif match.group(10) != None:
        return '\\texttt{'+match.group(11)+'}'

# ----------------------------------------------------------------------
def markdown_to_html(s):
    s_emph = pattern_emphasis.sub(emphasis_to_html, s)
    s_bullets = pattern_bullets.sub(bulleted_list_to_html, s_emph)
    return s_bullets

# ----------------------------------------------------------------------
def markdown_to_latex(s):
    return pattern_emphasis.sub(emphasis_to_latex, s)
