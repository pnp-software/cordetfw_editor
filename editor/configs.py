from editor.models import SpecItem, Requirement

configs = {'Requirement':{'name': 'Requirement',
                          'title': 'List of Requirements',
                          'has_children': False,
                          'child_cat': '',
                          'cols': [{'Name': 'ver_method', 'Label': 'Ver'}],
                          'form_fields': {'domain': {'label': 'Domain', 'req': True, 'model': 'SpecItem'},
                                          'name': {'label': 'Name', 'req': True, 'model': 'SpecItem'},
                                          'title': {'label': 'Title', 'req': False, 'model': 'SpecItem'},
                                          'desc': {'label': 'Description', 'req': False, 'model': 'SpecItem'},
                                          'value': {'label': 'Normative Text', 'req': True, 'model': 'SpecItem'},
                                          'justification': {'label': 'Rationale', 'req': False, 'model': 'SpecItem'},
                                          'remarks': {'label': 'Remarks', 'req': False, 'model': 'SpecItem'},
                                          'kind': {'label': 'Kind', 'req': True, 'model': 'SpecItem'},
                                          'ver_method': {'label': 'Ver. Method', 'req': True, 'model': 'Requirement'}
                                          }
                         },
               'DataItemType': {'name': 'Data Item Type',
                                'title': 'List of Requirements',
                                'has_children': True,
                                'child_cat': 'EnumItem',
                                'cols': {}
                               },
               'DataItem': {'name': 'Data Item',
                            'title': 'List of Requirements',
                            'has_children': False,
                            'child_cat': '',
                            'cols': {}
                           }
              }

def config_spec_item(spec_item, dic):
    """ Initialize the spec_item attributes with the value of the corresponding dictionary entries """
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
