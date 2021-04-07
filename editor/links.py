import re
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from editor.models import SpecItem
from .utilities import frmt_string

#--------------------------------------------------------------------------------
# TBD: This function should be removed!
def list_ver_items_for_display(spec_item):
    """
    Return a string listing the verification items which have a verification link to the 
    argument spec_item. The ver_items in the list are formatted for display
    in an html page.
    If the argument spec_item belongs to the 'VerItem' category (e.g. it is a test case),
    then the return string lists the specification items which are verified by it; 
    otherwise, the return string lists the verification items which verify it.
    """
    if spec_item.cat != 'VerItem':
        ver_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat='VerLink',
                    s_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
    else:
        ver_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat='VerLink',
                    p_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
        
    s = ''
    for link in ver_links:
        if s != '':
            s = s + '<br>'
        if spec_item.cat != 'VerItem':
            target = '/editor/'+link.p_link.cat+'/'+str(link.p_link.project_id)+'/'+str(link.p_link.application_id)+\
                    '/'+str(spec_item.val_set.id)+'/'+link.p_link.domain+'\list_spec_items'
            s = s + '<a href=\"'+target+'#'+link.p_link.domain+':'+link.p_link.name+'\" title=\"'+\
                link.p_link.desc+'\">' + link.p_link.domain + ':' + link.p_link.name + '</a> (' + link.p_link.title + ')'
        else:
            target = '/editor/'+link.s_link.cat+'/'+str(link.s_link.project_id)+'/'+str(link.s_link.application_id)+\
                    '/'+str(spec_item.val_set.id)+'/'+link.s_link.domain+'\list_spec_items'
            s = s + '<a href=\"'+target+'#'+link.s_link.domain+':'+link.s_link.name+'\" title=\"'+\
                link.s_link.desc+'\">' + link.s_link.domain + ':' + link.s_link.name + '</a> (' + link.s_link.title + ')'
            
    return s

#--------------------------------------------------------------------------------
def list_ver_items_for_latex(spec_item):
    """
    Return a string listing the verification items which have a verification link to the 
    argument spec_item. The ver_items in the list are formatted for latex output.
    If the argument spec_item belongs to the 'VerItem' category (e.g. it is a test case),
    then the return string lists the specification items which are verified by it; 
    otherwise, the return string lists the verification items which verify it.
    """
    if spec_item.cat != 'VerItem':
        ver_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat='VerLink',
                s_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
    else:
        ver_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat='VerLink',
                p_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
    s = ''
    for link in ver_links:
        if s != '':
            s = s + '\n'
        if spec_item.cat != 'VerItem':
            s = s + link.p_link.domain+':' + link.p_link.name + ' (' + link.p_link.title + ')'
        else:
            s = s + link.s_link.domain+':' + link.s_link.name + ' (' + link.s_link.title + ')'
    return frmt_string(s)

