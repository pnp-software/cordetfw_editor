from django.contrib.auth import get_user
from django.contrib import messages
from editor.models import SpecItem, ValSet

configs = {'General': {'csv_sep': '|',
                       'eol_sep': '\n',
                       'temp_dir': '/tmp',
                       'short_desc_len': 100,
                       'max_depth': 200
                       },
           'cats': {'Requirement':{'name': 'Requirement',
                                  'abbr': 'Req',
                                  'ext_attrs': [],
                                  'n_list_fields': 6,
                                  'expand': {'s_link': 'None', 
                                             'p_link': 'None'},
                                  'access_from_index': {'level': 'Application'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'value':     {'label': 'Text', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation':  {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet',  'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           's_kind':    {'label': 'Ver', 'req_in_form': True, 'kind': 'plain_text'}
                                           },
                                  'disp_def': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title and Description', 'attrs':['title', 'rationale', 'remarks', 'implementation']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind']},
                                               {'header':'Ver', 'attrs':['s_kind']},
                                               {'header':'Owner', 'attrs':['owner']}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind']},
                                               {'header':'Ver', 'attrs':['s_kind']}
                                               ]
                                 },
                   'AdaptPoint':{'name': 'Adaptation Point',
                                  'abbr': 'AP',
                                  'ext_attrs': [],
                                  'n_list_fields': 6,
                                  'expand': {'s_link': 'None', 
                                             'p_link': 'Requirement'},
                                  'access_from_index': {'level': 'Application'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Text', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation':  {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                           'p_link':    {'label': 'Parent Req', 'req_in_form': False, 'kind': 'spec_item_ref'},
                                           'val_set':   {'label': 'ValSet',  'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          }
                                 },
                       'DataItemType': {'name': 'Data Item Type',
                                  'abbr': 'Typ',
                                  'ext_attrs': [],
                                  'n_list_fields': 6,
                                  'expand': {'s_link': 'None',
                                             'p_link': 'DataItem', 'p_label': 'Data Item'},
                                  'access_from_index': {'level': 'Project'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Default Value Type', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Native Type', 'req_in_form': False, 'kind': 'ref_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'n1':        {'label': 'Size', 'req_in_form': True, 'kind': 'int'}
                                          }
                                 },
                       'EnumType': {'name': 'Enumerated Type',
                                  'abbr': 'ETyp',
                                  'ext_attrs': [],
                                  'n_list_fields': 6,
                                  'expand': {'s_link': 'EnumValue', 's_label': 'Enumerated Item',
                                             'p_link': 'DataItem', 'p_label': 'Data Item'},
                                  'access_from_index': {'level': 'Project'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Default Value Type', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Native Type', 'req_in_form': False, 'kind': 'ref_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'n1':        {'label': 'Size', 'req_in_form': True, 'kind': 'int'}
                                          }
                                 },
                       'Model': {'name': 'Behavioural Model',
                                  'abbr': 'Mod',
                                  'ext_attrs': ['value', 'p_kind'],
                                  'n_list_fields': 5,
                                  'expand': {'p_link': 'None',
                                             's_link': 'None'},
                                  'access_from_index': {'level': 'Application'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Diagram', 'req_in_form': False, 'kind': 'image'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          }
                                 },
                       'Service': {'name': 'Service',
                                  'abbr': 'Serv',
                                  'ext_attrs': [],
                                  'n_list_fields': 5,
                                  'expand': {'p_link': 'Packet', 'p_label': 'Packet',
                                             's_link': 'None'},
                                  'access_from_index': {'level': 'Project'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Type', 'req_in_form': True, 'kind': 'plain_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          }
                                 },
                        'Packet': {'name': 'Packet',
                                  'abbr': 'Pckt',
                                  'ext_attrs': [],
                                  'n_list_fields': 5,
                                  'expand': {'s_link': 'Packet', 's_label': 'Derived Packet',
                                             'p_link': 'PacketPar', 'p_label': 'Parameter'},
                                  'access_from_index': {'level': 'Project'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Sub-Type', 'req_in_form': True, 'kind': 'plain_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_link':    {'label': 'Type', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           't1':        {'label': 'Parameters', 'req_in_form': True, 'kind': 'ref_text'},
                                           't2':        {'label': 'Destination', 'req_in_form': True, 'kind': 'ref_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          }
                                 },
                        'DerPacket': {'name': 'Derived Packet',
                                  'abbr': 'DPckt',
                                  'ext_attrs': [],
                                  'n_list_fields': 9,
                                  'expand': {'s_link': 'None',
                                             'p_link': 'Packet', 'p_label': 'Parent Packet'},
                                  'access_from_index': {'level': 'None'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Sub-Type', 'req_in_form': True, 'kind': 'plain_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           's_link':    {'label': 'Parent Packet', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           'p_link':    {'label': 'Discriminat', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           't1':        {'label': 'Parameters', 'req_in_form': True, 'kind': 'ref_text'},
                                           't2':        {'label': 'Destination', 'req_in_form': True, 'kind': 'ref_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          }
                                 },
                        'PacketPar': {'name': 'Packet Parameter',
                                  'abbr': 'PcktPar',
                                  'ext_attrs': [],
                                  'n_list_fields': 10,
                                  'expand': {'s_link': 'None',
                                             'p_link': 'None'},
                                  'access_from_index': {'level': 'None'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Default Value', 'req_in_form': True, 'kind': 'plain_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_kind':    {'label': 'Role', 'req_in_form': True, 'kind': 'plain_text'},
                                           'p_link':    {'label': 'Packet', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           's_link':    {'label': 'Data Item', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           'n1':        {'label': 'Position', 'req_in_form': True, 'kind': 'int'},
                                           'n2':        {'label': 'Group Size', 'req_in_form': False, 'kind': 'int'},
                                           'n3':        {'label': 'Rep counter', 'req_in_form': False, 'kind': 'int'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          }
                                 },
                      'EnumValue': {'name': 'Enumerated Value',
                                  'abbr': 'EVal',
                                  'ext_attrs': [],
                                  'n_list_fields': 6,
                                  'expand': {'s_link': 'None',
                                             'p_link': 'None'
                                             },
                                  'access_from_index': {'level': 'None'},           
                                  'attrs': {'domain':   {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Value', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           's_link':    {'label': 'Type', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                          }
                                 },
                       'DataItem': {'name': 'Data Item',
                                  'abbr': 'Di',
                                  'ext_attrs': [],
                                   'n_list_fields': 8,
                                   'expand': {'s_link': 'None',
                                              'p_link': 'None'
                                              },
                                   'access_from_index': {'level': 'Project'},           
                                   'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Value', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_link':    {'label': 'Type', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                           't1':        {'label': 'Multiplicity', 'req_in_form': False, 'kind': 'ref_text'},
                                           't2':        {'label': 'Unit', 'req_in_form': False, 'kind': 'plain_text'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                           }
                                 },
                       'VerItem': {'name': 'Verification Item',
                                   'abbr': 'Ver',
                                   'ext_attrs': [],
                                   'n_list_fields': 7,
                                   'expand': {'s_link': 'None',
                                              'p_link': 'VerLink', 'p_label': 'Verification Link'
                                              },
                                   'access_from_index': {'level': 'Application'},           
                                   'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Definition', 'req_in_form': True, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                           's_kind':    {'label': 'Status', 'req_in_form': True, 'kind': 'plain_text'},
                                           't1':        {'label': 'PreCondition', 'req_in_form': False, 'kind': 'ref_text'},
                                           't2':        {'label': 'PostCondition', 'req_in_form': False, 'kind': 'ref_text'},
                                           't3':        {'label': 'Outcome', 'req_in_form': False, 'kind': 'ref_text'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                           }
                                   },
                       'VerLink': {'name': 'Verification Link',
                                   'abbr': 'VerL',
                                   'ext_attrs': [],
                                   'n_list_fields': 5,
                                   'expand': {'s_link': 'None',
                                              'p_link': 'None'
                                              },
                                   'access_from_index': {'level': 'None'},           
                                   'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Ver Conditions', 'req_in_form': False, 'kind': 'ref_text'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_link':    {'label': 'Ver Item', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           's_link':    {'label': 'Spec Item', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                           }
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
    if spec_item.p_children != None:    
        for child in spec_item.p_children.all():
            if child.val_set.name != 'Default':
                child.status = 'DEL'
                child.save()

          
def update_dom_name_in_val_set(spec_item):
    """ 
    Propagate a change in domain:name in spec_item to spec_items in other ValSets.
    This function assumes that spec_item is in the Default ValSet
    """
    if spec_item.p_children != None:    
        for child in spec_item.p_children.all():
            if child.val_set.name != 'Default':
                child.name = spec_item.name
                child.domain = spec_item.domain
                child.save()
    
    
     
