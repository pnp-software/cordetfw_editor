from django.contrib.auth import get_user
from django.contrib import messages
from editor.models import SpecItem, ValSet

configs = {'General': {'csv_sep': '|',
                       'eol_sep': '\n'
                       },
           'Requirement':{'name': 'Requirement',
                          'expand_cat': 'None',
                          'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                   'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                   'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                   'desc':      {'label': 'Desc', 'req_in_form': False, 'kind': 'ref_text'},
                                   'value':     {'label': 'Text', 'req_in_form': True, 'kind': 'ref_text'},
                                   'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                   'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                   'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                   'val_set':   {'label': 'ValSet',  'req_in_form': False, 'kind': 'plain_ref'},
                                   's_kind':    {'label': 'Ver Method', 'req_in_form': True, 'kind': 'plain_text'}
                                  }
                         },
               'DataItemType': {'name': 'Data Item Type',
                          'expand_cat': 'EnumItem', 
                          'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                   'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                   'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                   'desc':      {'label': 'Desc', 'req_in_form': False, 'kind': 'ref_text'},
                                   'value':     {'label': 'Native Type', 'req_in_form': True, 'kind': 'ref_text'},
                                   'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                   'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                   'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                   'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                   'n1':        {'label': 'Size', 'req_in_form': True, 'kind': 'int'}
                                  }
                         },
               'EnumItem': {'name': 'Enumerated Item',
                          'expand_cat': 'None',
                          'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                   'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                   'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                   'desc':      {'label': 'Desc', 'req_in_form': False, 'kind': 'ref_text'},
                                   'value':     {'label': 'Value', 'req_in_form': True, 'kind': 'ref_text'},
                                   'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                   'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                   's_link':    {'label': 'Type', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                   'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                  }
                         },
               'DataItem': {'name': 'Data Item',
                           'expand_cat': 'None',
                           'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                   'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                   'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                   'desc':      {'label': 'Desc', 'req_in_form': False, 'kind': 'ref_text'},
                                   'value':     {'label': 'Value', 'req_in_form': True, 'kind': 'ref_text'},
                                   'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                   'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                   'p_link':    {'label': 'Type', 'req_in_form': False, 'kind': 'spec_item_ref'},
                                   't1':        {'label': 'Multiplicty', 'req_in_form': False, 'kind': 'ref_text'},
                                   'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                   }
                         },
               'VerItem': {'name': 'Verification Item',
                           'expand_cat': 'VerLink',
                           'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                   'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                   'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                   'desc':      {'label': 'Desc', 'req_in_form': False, 'kind': 'ref_text'},
                                   'value':     {'label': 'Definition', 'req_in_form': True, 'kind': 'ref_text'},
                                   'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                   'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                   'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                   's_kind':    {'label': 'Ver Status', 'req_in_form': True, 'kind': 'plain_text'},
                                   't1':        {'label': 'PreCondition', 'req_in_form': False, 'kind': 'ref_text'},
                                   't2':        {'label': 'PostCondition', 'req_in_form': False, 'kind': 'ref_text'},
                                   't3':        {'label': 'Outcome', 'req_in_form': False, 'kind': 'ref_text'},
                                   'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                   }
                           },
               'VerLink': {'name': 'Verification Item',
                           'expand_cat': 'None',
                           'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                   'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                   'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                   'desc':      {'label': 'Desc', 'req_in_form': False, 'kind': 'ref_text'},
                                   'value':     {'label': 'Ver Conditions', 'req_in_form': False, 'kind': 'ref_text'},
                                   'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                   'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                   'p_link':    {'label': 'Ver Item', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                   's_link':    {'label': 'Spec Item', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                   'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                   }
                           }  
            }
              
              
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
    if spec_item.children != None:    
        for child in spec_item.children.all():
            if child.val_set.name != 'Default':
                child.status = 'DEL'
                child.save()

          
def update_dom_name_in_val_set(spec_item):
    """ 
    Propagate a change in domain:name in spec_item to spec_items in other ValSets.
    This function assumes that spec_item is in the Default ValSet
    """
    if spec_item.children != None:    
        for child in spec_item.children.all():
            if child.val_set.name != 'Default':
                child.name = spec_item.name
                child.domain = spec_item.domain
                child.save()
    
    
     
