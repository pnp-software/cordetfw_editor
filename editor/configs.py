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
                                  'expand': {'s_link': 'None', 
                                             'p_link': 'None'},
                                  'tracs': [{'trac_cat':'VerLink', 'trac_link':'s_link'}],
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
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Ver', 'attrs':['s_kind'], 'order_by':'s_kind'},
                                               {'header':'Owner', 'attrs':['owner'], 'order_by':'owner'}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Ver', 'attrs':['s_kind'], 'order_by':'s_kind'}
                                               ],
                                  'disp_trac': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Ver', 'attrs':['s_kind'], 'order_by':'s_kind'},
                                               {'header':'Verification Links', 'trac_cat':'VerLink', 'trac_link':'s_link'}
                                               ]
                                 },
                   'AdaptPoint':{'name': 'Adaptation Point',
                                  'abbr': 'AP',
                                  'ext_attrs': [],
                                  'expand': {'s_link': 'None', 
                                             'p_link': 'Requirement'},
                                  'tracs': [],
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
                                  'expand': {'s_link': 'None',
                                             'p_link': 'DataItem', 'p_label': 'Data Item'},
                                  'tracs': [],
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
                                          },
                                  'disp_def': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Description', 'attrs':['title', 'desc', 'rationale', 'remarks']},
                                               {'header':'Def. Val.', 'attrs':['value']},
                                               {'header':'Native Type', 'attrs':['implementation']},
                                               {'header':'Size', 'attrs':['n1']},
                                               {'header':'Owner', 'attrs':['owner'], 'order_by':'owner'}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Description', 'attrs':['title']},
                                               {'header':'Def. Val.', 'attrs':['value']},
                                               {'header':'Native Type', 'attrs':['implementation']},
                                               {'header':'Size', 'attrs':['n1']}
                                               ],
                                  'disp_trac': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Description', 'attrs':['title']},
                                               {'header':'Def. Val.', 'attrs':['value']},
                                               {'header':'Native Type', 'attrs':['implementation']},
                                               {'header':'Size', 'attrs':['n1']}
                                               ],
                                 },
                       'EnumType': {'name': 'Enumerated Type',
                                  'abbr': 'ETyp',
                                  'ext_attrs': [],
                                  'expand': {'s_link': 'EnumValue', 's_label': 'Enumerated Item',
                                             'p_link': 'DataItem', 'p_label': 'Data Item'},
                                  'tracs': [],
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
                                  'ext_attrs': ['domain', 'name', 'value', 'p_kind', 'n1', 'n2'],
                                  'expand': {'p_link': 'None',
                                             's_link': 'None'},
                                  'tracs': [],
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
                                           't1':        {'label': 'Diag Scale', 'req_in_form': True, 'kind': 'plain_text'},
                                           'n1':        {'label': 'Width', 'req_in_form': True, 'kind': 'int'},
                                           'n2':        {'label': 'Height', 'req_in_form': True, 'kind': 'int'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'}
                                          },
                                  'disp_def': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title and Description', 'attrs':['title', 'desc', 'rationale', 'remarks', 'implementation']},
                                               {'header':'Diagram', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Owner', 'attrs':['owner'], 'order_by':'owner'}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Diagram', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'}
                                               ],
                                  'disp_trac': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Diagram', 'attrs':['value']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Verification Links', 'trac_cat':'VerLink', 'trac_link':'s_link'}
                                               ]
                                 },
                       'Service': {'name': 'Service',
                                  'abbr': 'Serv',
                                  'ext_attrs': [],
                                  'expand': {'p_link': 'Packet', 'p_label': 'Packet',
                                             's_link': 'None'},
                                  'tracs': [{'trac_cat':'VerLink', 'trac_link':'s_link'}],
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
                                  'expand': {'s_link': 'Packet', 's_label': 'Derived Packet',
                                             'p_link': 'PacketPar', 'p_label': 'Parameter'},
                                  'tracs': [{'trac_cat':'VerLink', 'trac_link':'s_link'}],
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
                                  'expand': {'s_link': 'None',
                                             'p_link': 'Packet', 'p_label': 'Parent Packet'},
                                  'tracs': [{'trac_cat':'VerLink', 'trac_link':'s_link'}],
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
                                  'expand': {'s_link': 'None',
                                             'p_link': 'None'},
                                  'tracs': [{'trac_cat':'VerLink', 'trac_link':'s_link'}],
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
                                  'expand': {'s_link': 'None',
                                             'p_link': 'None'
                                             },
                                  'tracs': [],
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
                                   'expand': {'s_link': 'None',
                                              'p_link': 'None'
                                              },
                                  'tracs': [{'trac_cat':'VerLink', 'trac_link':'s_link'}],
                                   'access_from_index': {'level': 'Project'},           
                                   'attrs': {'domain':  {'label': 'Domain', 'req_in_form': True, 'kind': 'plain_text'},
                                           'name':      {'label': 'Name', 'req_in_form': True, 'kind': 'plain_text'},
                                           'title':     {'label': 'Title', 'req_in_form': True, 'kind': 'plain_text'},
                                           'desc':      {'label': 'Description', 'req_in_form': False, 'kind': 'ref_text'},
                                           'value':     {'label': 'Value', 'req_in_form': True, 'kind': 'eval_ref'},
                                           'rationale': {'label': 'Rationale', 'req_in_form': False, 'kind': 'ref_text'},
                                           'remarks':   {'label': 'Remarks', 'req_in_form': False, 'kind': 'ref_text'},
                                           'implementation': {'label': 'Implementation', 'req_in_form': False, 'kind': 'ref_text'},
                                           'p_link':    {'label': 'Type', 'req_in_form': True, 'kind': 'spec_item_ref'},
                                           'p_kind':    {'label': 'Kind', 'req_in_form': True, 'kind': 'plain_text'},
                                           't1':        {'label': 'Multiplicity', 'req_in_form': False, 'kind': 'ref_text'},
                                           't2':        {'label': 'Unit', 'req_in_form': False, 'kind': 'plain_text'},
                                           'owner':     {'label': 'Owner',  'req_in_form': False, 'kind': 'plain_text'},
                                           'val_set':   {'label': 'ValSet', 'req_in_form': False, 'kind': 'plain_ref'}
                                           },
                                  'disp_def': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Description', 'attrs':['title', 'desc', 'rationale', 'remarks', 'implementation']},
                                               {'header':'Value', 'attrs':['value']},
                                               {'header':'Unit', 'attrs':['t2']},
                                               {'header':'Mult', 'attrs':['t1']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Type', 'attrs':['p_link'], 'order_by':'p_link'},
                                               {'header':'Owner', 'attrs':['owner']}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Description', 'attrs':['title']},
                                               {'header':'Value', 'attrs':['value']},
                                               {'header':'Unit', 'attrs':['t2']},
                                               {'header':'Mult', 'attrs':['t1']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Type', 'attrs':['p_link'], 'order_by':'p_link'}
                                               ],
                                  'disp_trac': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Description', 'attrs':['title']},
                                               {'header':'Value', 'attrs':['value']},
                                               {'header':'Unit', 'attrs':['t2']},
                                               {'header':'Mult', 'attrs':['t1']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Type', 'attrs':['p_link'], 'order_by':'p_link'}
                                               ]
                                 },
                       'VerItem': {'name': 'Verification Item',
                                   'abbr': 'Ver',
                                   'ext_attrs': [],
                                   'expand': {'s_link': 'None',
                                              'p_link': 'VerLink', 'p_label': 'Verification Link'
                                              },
                                   'tracs': [{'trac_cat':'VerLink', 'trac_link':'p_link'}],
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
                                           },
                                  'disp_def': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title and Description', 'attrs':['title', 'rationale', 'remarks', 'implementation']},
                                               {'header':'Text', 'attrs':['value', 't1', 't2', 't3']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Status', 'attrs':['s_kind'], 'order_by':'s_kind'},
                                               {'header':'Owner', 'attrs':['owner'], 'order_by':'owner'}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value', 't1', 't2', 't3']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Status', 'attrs':['s_kind'], 'order_by':'s_kind'},
                                               ],
                                  'disp_trac': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value', 't1', 't2', 't3']},
                                               {'header':'Kind', 'attrs':['p_kind'], 'order_by':'p_kind'},
                                               {'header':'Status', 'attrs':['s_kind'], 'order_by':'s_kind'},
                                               {'header':'Verified Items', 'trac_cat':'VerLink', 'trac_link':'p_link'}
                                               ]
                                   },
                       'VerLink': {'name': 'Verification Link',
                                   'abbr': 'VerL',
                                   'ext_attrs': [],
                                   'expand': {'s_link': 'None',
                                              'p_link': 'None'
                                              },
                                   'access_from_index': {'level': 'Project'},  
                                   'tracs': [],         
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
                                           },
                                  'disp_def': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title and Description', 'attrs':['title', 'rationale', 'remarks']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Ver Item', 'attrs':['p_link'], 'order_by':'p_link'},
                                               {'header':'Spec Item', 'attrs':['s_link'], 'order_by':'s_link'},
                                               {'header':'Owner', 'attrs':['owner'], 'order_by':'owner'}
                                               ],
                                  'disp_short': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Ver Item', 'attrs':['p_link'], 'order_by':'p_link'},
                                               {'header':'Spec Item', 'attrs':['s_link'], 'order_by':'s_link'},
                                               ],
                                  'disp_trac': [{'header':'Domain', 'attrs':['domain']},
                                               {'header':'Name', 'attrs':['name']},
                                               {'header':'Title', 'attrs':['title']},
                                               {'header':'Text', 'attrs':['value']},
                                               {'header':'Ver Item', 'attrs':['p_link'], 'order_by':'p_link'},
                                               {'header':'Spec Item', 'attrs':['s_link'], 'order_by':'s_link'}
                                               ]
                                   }  
                   } 
            }
              
              
def get_p_link_choices(cat, project, application, p_parent_id):
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
    if cat == 'VerLink':
        return SpecItem.objects.filter(project_id=project.id, cat='VerItem').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
    if cat == 'Packet':
        return SpecItem.objects.filter(project_id=project.id, cat='Service').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
    if (cat == 'AdaptPoint') and (application != None):
        return SpecItem.objects.filter(application_id=application.id, cat='Requirement').\
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')    
                        
    return SpecItem.objects.none()
    
    
def get_s_link_choices(cat, project, application, s_parent_id):
    """ 
        If s_parent_id is different from None, the function returns the spec_items which 
        have s_parent_id as their s_link parent. Otherwise, it returns the range of 
        choices for the 's_link' attribute of a spec_item of a given category 
    """
    if s_parent_id != None:
        return SpecItem.objects.filter(id=int(s_parent_id))
    if cat == 'EnumValue':
        return SpecItem.objects.filter(project_id=project.id, cat='EnumType'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('domain', 'name')
    if cat == 'VerLink':
        return SpecItem.objects.filter(project_id=project.id).exclude(cat='VerItem').exclude(cat='VerLink'). \
                        exclude(status='DEL').exclude(status='OBS').order_by('cat', 'domain', 'name')
                        
    return SpecItem.objects.none()

     
