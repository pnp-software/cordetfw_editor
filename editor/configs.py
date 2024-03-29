import json
import re
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user
from django.contrib import messages
from django.conf import settings
from editor.models import SpecItem, ValSet
from editor.convert import pattern_db

with open(settings.BASE_DIR + '/editor/static/json/configs.json') as config_file:
    configs = json.load(config_file)

#-------------------------------------------------------------------------------------------------    
def get_p_link_choices(cat, project, application, p_parent_id, s_parent_id):
    """ 
        If p_parent_id is different from None, the function returns the spec_items which 
        have p_parent_id as their p_link parent. Otherwise, it returns the range of 
        choices for the 'p_link' attribute of a spec_item of a given category 
    """
    if p_parent_id != None:
        return SpecItem.objects.filter(id=int(p_parent_id)) 
        
    if cat == 'DataItem':
        q1 = SpecItem.objects.filter(project_id=project.id, cat='DataItemType').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')        
        q2 = SpecItem.objects.filter(project_id=project.id, cat='EnumType').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name') 
        return q1 | q2

    if cat == 'RiskScenario':
        return SpecItem.objects.filter(project_id=project.id, cat='OpContext').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    

    if cat == 'VerLink':
        return SpecItem.objects.filter(project_id=project.id, cat='VerItem').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    

    if cat == 'Packet':
        return SpecItem.objects.filter(project_id=project.id, cat='Service').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    

    if cat == 'InCommand' or cat == 'OutComponent':
        q1 = SpecItem.objects.filter(project_id=project.id, cat='Packet').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
        q2 = SpecItem.objects.filter(project_id=project.id, cat='DerPacket').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
        return q1 | q2   

    if cat == 'PacketPar':
        q1 = SpecItem.objects.filter(project_id=project.id, cat='Packet').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
        q2 = SpecItem.objects.filter(project_id=project.id, cat='DerPacket').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
        return q1 | q2

    if cat == 'DerPacket':
        if s_parent_id != None:
            s_parent = SpecItem.objects.get(id=s_parent_id)
            return SpecItem.objects.filter(project_id=project.id, cat='EnumValue', s_link=s_parent.s_link).\
                            exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
        else:
            return SpecItem.objects.filter(project_id=project.id, cat='EnumValue').\
                            exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    

    if (cat == 'AdaptPoint') and (application != None):
        return SpecItem.objects.filter(application_id=application.id, cat='Requirement').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
                        
    return SpecItem.objects.none()
    
#-------------------------------------------------------------------------------------------------    
def get_s_link_choices(cat, project, application, s_parent_id, p_parent_id):
    """ 
        If s_parent_id is different from None, the function returns the spec_items which 
        have s_parent_id as their s_link parent. Otherwise, it returns the range of 
        choices for the 's_link' attribute of a spec_item of a given category 
    """
    if s_parent_id != None:
        return SpecItem.objects.filter(id=int(s_parent_id))
        
    if cat == 'RiskScenario':
        return SpecItem.objects.filter(project_id=project.id, cat='DisrEvt').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    

    if cat == 'EnumValue': 
        return SpecItem.objects.filter(project_id=project.id, cat='EnumType'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')

    if cat == 'PacketPar':  
        return SpecItem.objects.filter(project_id=project.id, cat='DataItem'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')

    if cat == 'DerPacket':  
        return SpecItem.objects.filter(project_id=project.id, cat='Packet'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')

    if cat == 'Packet':     
        return SpecItem.objects.filter(project_id=project.id, cat='EnumType'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')

    if cat == 'VerStep':     
        return SpecItem.objects.filter(project_id=project.id, cat='VerItem'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')

    if cat == 'VerLink':
        return SpecItem.objects.filter(project_id=project.id).exclude(cat='VerItem').exclude(cat='VerLink'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('cat', 'domain', 'name')
                        
    return SpecItem.objects.none()

#-------------------------------------------------------------------------------------------------    
def do_cat_specific_checks(form):
    """ Perform the category-specific checks for data items """
    cd = form.cleaned_data
    
    # Verify that the value of a data item of enumerated type is an internal reference to an enumerated 
    # value of the data item's type
    if (form.cat == 'DataItem') and (cd['p_link'].cat == 'EnumType'):
        m = re.match(pattern_db, cd['value'].strip())
        if (m == None) or (m.span()[1] != len(cd['value'].strip())):
            return 'Data item value must be a reference to an enumerated value of the item type'
        ref = cd['value'].strip().split(':')
        try:
            enum_val = SpecItem.objects.get(id=ref[1], cat='EnumValue')
        except ObjectDoesNotExist:
            return 'Data item value must be a reference to an enumerated value of the item type: '+\
                   'The reference is invalid'
        if enum_val.s_link.id != cd['p_link'].id:
            return 'Data item value must be a reference to an enumerated value of the item type'
    
    return ''
