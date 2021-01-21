from django.contrib.auth import get_user
from editor.models import SpecItem, Requirement, ValSet, Packet, PacketBehaviour, PacketPar, VerItem

configs = {'Requirement':{'name': 'Requirement',
                          'title_list': 'List of Requirements',
                          'title_history': 'History of Requirement ',
                          'has_children': False,
                          'child_cat': '',
                          'cols': [{'Name': 'ver_method', 'Label': 'Ver'}],
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
                          'child_cat': 'EnumItem',
                          'cols': [{'Name': 'dim', 'Label': 'Size'}],
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
               'EnumtemT': {'name': 'Enumerated Item',
                          'title_list': 'List of Enumerated Items',
                          'title_history': 'History of Enumerated Item ',
                          'has_children': False,
                          'child_cat': '',
                          'cols': [],
                          'form_fields': {'domain': {'label': 'Domain', 'req': True, 'model': 'SpecItem'},
                                          'name': {'label': 'Name', 'req': True, 'model': 'SpecItem'},
                                          'title': {'label': 'Short Desc.', 'req': True, 'model': 'SpecItem'},
                                          'desc': {'label': 'Description', 'req': False, 'model': 'SpecItem'},
                                          'value': {'label': 'Native Type', 'req': True, 'model': 'SpecItem'},
                                          'parent': {'label': 'Type', 'req': True, 'model': 'SpecItem'},
                                          'justification': {'label': 'Rationale', 'req': False, 'model': 'SpecItem'},
                                          'remarks': {'label': 'Remarks', 'req': False, 'model': 'SpecItem'},
                                          'val_set': {'label': 'ValSet', 'req': False, 'model': 'SpecItem'}
                                          }
                         },
               'DataItem': {'name': 'Data Item',
                            'title': 'List of Requirements',
                            'has_children': False,
                            'child_cat': '',
                            'cols': {}
                           }
              }

def dict_to_spec_item(dic, spec_item):
    """ 
    Initialize the spec_item attributes with the value of the corresponding dictionary entries. 
    If the dictionary also contains category-specific data then: if the spec_item, already has
    a category-specific model instance, this is updated with the data from the dictionary; if,
    instead, the spec_item has no category specific model instance, the categoy-specific model
    instance is created and initialized with the data from the dictionary.
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
        spec_item.size = dic['dim']
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

          
def duplicate_spec_item(request, spec_item):
    """ Create a copy of spec_item, save it to the database and return it """
    if spec_item.cat == 'Requirement':
        req = spec_item.req
        req.id = None
        req.save()              # Create new instance holding the old version of the Requirement
        spec_item.req = req     # Now spec_item points to the newly-created Requirement instance
    spec_item.id = None
    spec_item.save()            # Create new instance holding the old version of the spec_item
    return spec_item            # Return the newly-created instance of spec_item


def remove_spec_item(request, spec_item):
    """ Delete the spec_item from the database together with its category-specific items """
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
    try:
        spec_item.delete()
    except Exception as e:
        messages.error(request, 'Failure to delete ' + str(spec_item) + \
                                ', possibly because it is still in use: ' + str(e))
          
          
def save_spec_item(spec_item):
    """ Save the spec_item and its associated category-specific model instances """
    if spec_item.req != None:
        spec_item.req.save()
    spec_item.save()
