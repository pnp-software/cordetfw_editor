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
pattern_emphasis = re.compile('(\*\*)(.+?)(\*\*)|(\+\+)(.+?)(\+\+)|(__)(.+?)(__)|(``)(.+?)(``)')     

pattern_bullets = re.compile('((\n^-\s.+$)+)', re.MULTILINE)    

# Regex pattern for tables: a header row, a separator row ('| --- | --- |')
# and zero or more body rows. Cells are separated by '|' (escaped as '\|').
pattern_table = re.compile(r'^[ \t]*\|[^\r\n]*\|[ \t]*\r?\n'
                           r'[ \t]*\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*'
                           r'(?:\r?\n[ \t]*\|[^\r\n]*\|[ \t]*)*(?:\r?\n)?', re.MULTILINE)

pattern_cell_sep = re.compile(r'(?<!\\)\|')

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
def bulleted_list_to_latex(match):
    s1 = match.group(1).replace('\n','')
    s2 = s1.replace('\r','')
    bullet_items = s2.split('- ')
    s_html = '\\begin{itemize}'
    for i, bullet_item in enumerate(bullet_items): 
        if i>0:
            s_html = s_html + '\\item '+bullet_item
    return s_html + '\\end{itemize}'+' \ ' # Backslash adds a space

# ----------------------------------------------------------------------
def parse_table(s):
    """ Return the rows (lists of cell strings) of markdown table s, without the separator row """
    rows = []
    for i, line in enumerate(s.strip().splitlines()):
        if i == 1:
            continue
        line = line.strip()[1:-1]
        rows.append([c.strip().replace('\\|', '|') for c in pattern_cell_sep.split(line)])
    n_cols = max(len(row) for row in rows)
    return [row + ['']*(n_cols-len(row)) for row in rows]

# ----------------------------------------------------------------------
def split_tables(s):
    """ Split s into a list of (is_table, segment) tuples """
    segments = []
    pos = 0
    for match in pattern_table.finditer(s):
        if match.start() > pos:
            segments.append((False, s[pos:match.start()]))
        segments.append((True, match.group()))
        pos = match.end()
    if pos < len(s):
        segments.append((False, s[pos:]))
    return segments

# ----------------------------------------------------------------------
def table_to_html(match):
    # No newlines in the output: displayed text goes through linebreaksbr
    rows = parse_table(match.group())
    s_html = '<table class="table table-bordered table-sm md-table mb-1"><thead><tr>'
    for cell in rows[0]:
        s_html = s_html + '<th>' + pattern_emphasis.sub(emphasis_to_html, cell) + '</th>'
    s_html = s_html + '</tr></thead><tbody>'
    for row in rows[1:]:
        s_html = s_html + '<tr>'
        for cell in row:
            s_html = s_html + '<td>' + pattern_emphasis.sub(emphasis_to_html, cell) + '</td>'
        s_html = s_html + '</tr>'
    return s_html + '</tbody></table>'

# ----------------------------------------------------------------------
def table_to_latex(s, conv_cell):
    """
    Convert markdown table s to a latex longtable (requires \\usepackage{longtable}) which
    breaks across pages and repeats the header row on each page; conv_cell converts the content of a cell
    """
    rows = parse_table(s)
    n = len(rows[0])
    # Equal-width wrapping columns which together fill the line width
    col_width = '\\dimexpr(\\linewidth-' + str(2*n) + '\\tabcolsep-' + str(n+1) + '\\arrayrulewidth)/' + str(n) + '\\relax'
    s_latex = '\\begin{longtable}{|' + ('p{' + col_width + '}|')*n + '}\\hline '
    s_latex = s_latex + ' & '.join('\\textbf{' + conv_cell(c) + '}' for c in rows[0]) + ' \\\\ \\hline \\endhead '
    for row in rows[1:]:
        s_latex = s_latex + ' & '.join(conv_cell(c) for c in row) + ' \\\\ \\hline '
    return s_latex + '\\end{longtable} '

# ----------------------------------------------------------------------
def markdown_to_html(s):
    s = pattern_table.sub(table_to_html, s)
    s_emph = pattern_emphasis.sub(emphasis_to_html, s)
    s_bullets = pattern_bullets.sub(bulleted_list_to_html, s_emph)
    return s_bullets

# ----------------------------------------------------------------------
def markdown_to_latex(s):
    s_emph = pattern_emphasis.sub(emphasis_to_latex, s)
    s_bullets = pattern_bullets.sub(bulleted_list_to_latex, s_emph)
    return s_bullets
