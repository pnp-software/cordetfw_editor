from django.contrib.auth import get_user
from django.contrib import messages
from editor.models import SpecItem, Requirement, ValSet, Packet, PacketBehaviour, PacketPar, VerItem

configs = {'Requirement':{'name': 'Requirement',
                          'title_list': 'List of Requirements',
                          'title_history': 'History of Requirement ',
                          'has_children': False,
                          'child_cat': '',
                          'cols': [{'name': 'ver_method', 'label': 'Ver'}],
                          'form_fields': {'domain': {'label': 'Domain', 'req': True, 'model': 'SpecItem'},
                                          'name': {'label': 'Name', 'req': True, 'model': 'SpecItem'},
                                          'title': {'label': 'Title', 'req': True, 'model': 'SpecItem'},
                                          'desc': {'label': 'Description', 'req': False, 'model': 'SpecItem'},
                                          'value': {'label': 'Normative Text', 'req': True, 'model': 'SpecItem'},
                                          'justification': {'label': 'Rationale', 'req': False, 'model': 'SpecItem'},
                                          'remarks': {'label': 'Remarks', 'req': False, 'model': 'SpecItem'},
                                          'kind': {'label': 'Kind', 'req': True, 'model': 'SpecItem'},
                                          'val_set': {'label': 'ValSet', 'req': False, 'model': 'SpecItem'},
                                          'ver_method': {'label': 'Ver. Method', 'req': True, 'model': 'Requirement'}
                                          }
                         },
               'DataItemType': {'name': 'Data Item Type',
                          'title_list': 'List of Data Item Types',
                          'title_history': 'History of Data Item Type ',
                          'has_children': True,
                          'child_desc': {'cat': 'EnumItem', 'name': 'Enumerated Item'},
                          'cols': [{'name': 'dim', 'label': 'Size'}],
                          'form_fields': {'domain': {'label': 'Domain', 'req': True, 'model': 'SpecItem'},
                                          'name': {'label': 'Name', 'req': True, 'model': 'SpecItem'},
                                          'title': {'label': 'Short Desc.', 'req': True, 'model': 'SpecItem'},
                                          'desc': {'label': 'Description', 'req': False, 'model': 'SpecItem'},
                                          'value': {'label': 'Native Type', 'req': False, 'model': 'SpecItem'},
                                          'dim': {'label': 'Size in Bits', 'req': False, 'model': 'SpecItem'},
                                          'justification': {'label': 'Rationale', 'req': False, 'model': 'SpecItem'},
                                          'remarks': {'label': 'Remarks', 'req': False, 'model': 'SpecItem'},
                                          'kind': {'label': 'Enumerated', 'req': True, 'model': 'SpecItem'},
                                          'val_set': {'label': 'ValSet', 'req': False, 'model': 'SpecItem'}
                                          }
                         },
               'EnumItem': {'name': 'Enumerated Item',
                          'title_list': 'List of Enumerated Items',
                          'title_history': 'History of Enumerated Item ',
                          'has_children': False,
                          'child_cat': '',
                          'cols': [],
                          'form_fields': {'name': {'label': 'Enum Name', 'req': True, 'model': 'SpecItem'},
                                          'title': {'label': 'Short Desc.', 'req': True, 'model': 'SpecItem'},
                                          'desc': {'label': 'Description', 'req': False, 'model': 'SpecItem'},
                                          'value': {'label': 'Enum Value', 'req': True, 'model': 'SpecItem'},
                                          'parent': {'label': 'Data Type', 'req': True, 'model': 'SpecItem'},
                                          'justification': {'label': 'Rationale', 'req': False, 'model': 'SpecItem'},
                                          'remarks': {'label': 'Remarks', 'req': False, 'model': 'SpecItem'},
                                          'val_set': {'label': 'ValSet', 'req': False, 'model': 'SpecItem'}
                                          }
                         },
               'DataItem': {'name': 'Data Item',
                          'title_list': 'List of Data Items',
                          'title_history': 'History of Data Item ',
                          'has_children': False,
                          'child_cat': '',
                          'cols': [],
                          'form_fields': {'domain': {'label': 'Domain', 'req': True, 'model': 'SpecItem'},
                                          'name': {'label': 'Name', 'req': True, 'model': 'SpecItem'},
                                          'title': {'label': 'Short Desc.', 'req': True, 'model': 'SpecItem'},
                                          'desc': {'label': 'Description', 'req': False, 'model': 'SpecItem'},
                                          'value': {'label': 'Value', 'req': True, 'model': 'SpecItem'},
                                          'kind': {'label': 'Kind', 'req': True, 'model': 'SpecItem'},
                                          'dim': {'label': 'Mult.', 'req': True, 'model': 'SpecItem'},
                                          'parent': {'label': 'Data Type', 'req': True, 'model': 'SpecItem'},
                                          'justification': {'label': 'Rationale', 'req': False, 'model': 'SpecItem'},
                                          'remarks': {'label': 'Remarks', 'req': False, 'model': 'SpecItem'},
                                          'val_set': {'label': 'ValSet', 'req': False, 'model': 'SpecItem'}
                                          }
                         }
              }
              

def dict_to_spec_item(dic, spec_item):
    """ 
    Initialize the spec_item attributes with the value of the corresponding dictionary entries. 
    If the dictionary also contains category-specific data then: if the spec_item, already has
    a category-specific model instance, this is updated with the data from the dictionary; if,
    instead, the spec_item has no category specific model instance, the categoy-specific model
    instance is created and initialized with the data from the dictionary.
    Function render_for_edit is used to resolve internal references in text fields.
    """
    if 'domain' in dic:
        spec_item.domain = dic['domain']
    if 'name' in dic:
        spec_item.name = dic['name']
    if 'title' in dic:
        spec_item.title = dic['title']
    if 'desc' in dic:
        spec_item.desc = dic['desc']
    if 'value' in dic:
        spec_item.value = dic['value']
    if 'justification' in dic:
        spec_item.justification = dic['justification']
    if 'remarks' in dic:
        spec_item.remarks = dic['remarks']
    if 'kind' in dic:
        spec_item.kind = dic['kind']
    if 'dim' in dic:
        spec_item.dim = dic['dim']
    if ('parent' in dic) and (dic['parent'] != ''):
        spec_item.parent = SpecItem.objects.get(id=dic['parent'])
    if ('val_set' in dic) and (dic['val_set'] != ''):
        spec_item.val_set = ValSet.objects.get(id=dic['val_set'])
    if spec_item.cat == 'Requirement':
        if 'ver_method' in dic:
            if spec_item.req == None:
                new_req = Requirement()
                new_req.ver_method = dic['ver_method']
                spec_item.req = new_req
            else:
                spec_item.req.ver_method = dic['ver_method']

          
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
    
    if spec_item.cat == 'Requirement':
        req = spec_item.req
        req.id = None
        req.save()              # Create new instance holding the old version of Requirement instance
        spec_item.req = req     # Now spec_item points to the newly-created Requirement instance
    
    spec_item.status = 'OBS'
    spec_item.previous = previous
    spec_item.id = None
    spec_item.save()            # Create new instance holding the OBS version of the spec_item
    
    edited_spec_item = SpecItem.objects.get(id=edited_spec_item_id) # Retrive original spec_item instance
    edited_spec_item.previous = spec_item   # Now spec_item points to newly-created OBS copy 
    edited_spec_item.status = 'MOD'
    return edited_spec_item     # Return the newly-created instance of spec_item


def remove_spec_item(request, spec_item):
    """ Delete the spec_item from the database together with its category-specific items """
    try:
        spec_item.delete()
    except Exception as e:
        messages.error(request, 'Failure to delete ' + str(spec_item) + \
                                ', possibly because other spec_item reference it: ' + str(e))
        return
    if spec_item.req != None:
        spec_item.req.delete()    
    elif spec_item.packet != None:
        spec_item.packet.delete()
    elif spec_item.packet_par != None:
        spec_item.packet_par.delete()
    elif spec_item.packet_behaviour != None:
        spec_item.packet_behaviour.delete() 
    elif spec_item.ver_item != None:
        spec_item.ver_item.delete()
     
def remove_spec_item_aliases(request, spec_item):
    """ Remove spec_items attached to argument spec_items but in other ValSets """
    if spec_item.children != None:    
        for child in spec_item.children.all():
            if child.val_set.name != 'Default':
                remove_spec_item(child)
  
  
def mark_spec_item_aliases_as_del(request, spec_item):
    """ Set status of spec_items attached to argument spec_item but in other ValSet to DEL """           
    if spec_item.children != None:    
        for child in spec_item.children.all():
            if child.val_set.name != 'Default':
                child.status = 'DEL'
                child.save()

          
def save_spec_item(spec_item):
    """ Save the spec_item and its associated category-specific model instances """
    if spec_item.req != None:
        spec_item.req.save()
    spec_item.save()


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
    
    
     
