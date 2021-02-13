import re
from django.utils.html import escape
from django.core.exceptions import ObjectDoesNotExist
from editor.models import SpecItem, Application, VerItemToSpecItem
from .utilities import convert_spec_item_to_latex

LINK_SEP = '|'
pattern_text = re.compile("#([a-z]+:[a-zA-Z0-9_]+:[a-zA-Z0-9_]+)")

#--------------------------------------------------------------------------------
def parse_links(s, application_id):
    """
    Verify that the string holds a well-formed set of test case links and extract
    the links as a list of dictionaries (or else return a dictionary with an error message).
    """
    s.replace('\r','')      # Makes sure that only '\n' is used as line separator
    lines = s.split('\n')
    print('llines: '+str(lines))
    link_descs = []
    n = 1
    for line in lines:
        if line.strip() == '':
            continue
        comps = line.split(LINK_SEP)
        if len(comps) != 2:
            link_desc = {'error': 'Line ' + str(n) + ' does not hold 2 items'}
            link_descs.append(link_desc)
            continue
        link_desc = parse_link(comps, n, application_id)
        link_descs.append(link_desc)
        n = n+1

    return link_descs

#--------------------------------------------------------------------------------
def parse_link(comps, line_nmb, application_id):
    """
    Verify that the string holds a well-formed test case link and extract and return
    the links as a dictionaries (or else return a dictionary with an error message).
    """
    link = comps[0].strip()
    if link[0] != '#':
        return {'error': 'Mal-formed link ' + link + ' at line number ' + str(line_nmb)}

    link_elem = link.split(':')
    if len(link_elem) != 3:
        return {'error': 'Mal-formed link ' + link + ' at line number ' + str(line_nmb)}

    if link_elem[0] == '#di':
        try:
            project_id = Application.objects.get(id=application_id).project.id
            def_val_set = DataItemValSet.objects.get(project_id=project_id, name='Default')
            link_id = DataItem.objects.filter(project_id=project_id, val_set=def_val_set).exclude(status='DEL').\
                            exclude(status='OBS').get(domain=link_elem[1], name=link_elem[2]).id
            return {'kind': 'DI',
                    'ver_item': link_id,
                    'cond': comps[1]}
        except ObjectDoesNotExist:
            return {'error': 'Non existent data item reference ' + link}
        
    if link_elem[0] == '#req':
        try:
            link_id = Requirement.objects.filter(application_id=application_id).exclude(status='DEL').\
                            exclude(status='OBS').get(domain=link_elem[1], name=link_elem[2]).id
            return {'kind': 'REQ',
                    'ver_item': link_id,
                    'cond': comps[1]}
        except ObjectDoesNotExist:
            return {'error': 'Non existent data item reference ' + link}

    if link_elem[0] == '#mod':
        try:
            link = FwProfileModel.objects.filter(application_id=application_id).exclude(status='DEL').\
                            exclude(status='OBS').get(domain=link_elem[1], name=link_elem[2])
            return {'kind': link.kind,
                    'ver_item': link.id,
                    'cond': comps[1]}
        except ObjectDoesNotExist:
            return {'error': 'Non existent data item reference ' + link}

    return {'error': 'Non existent verification item kind ' + link}

#--------------------------------------------------------------------------------
def update_links(test_case, link_descs):
    """ Delete the existing test case links in TestCaseToSpecItem and put in the new ones. """
    tc2specs = TestCaseToVerItem.objects.filter(test_case=test_case.id).delete()
    for link_desc in link_descs:
        tc2spec = TestCaseToVerItem(test_case = test_case,
                                    kind = link_desc['kind'],
                                    ver_item = link_desc['ver_item'],
                                    cond = link_desc['cond'])
        tc2spec.save()
    return 

#--------------------------------------------------------------------------------
def render_links_as_list(test_case):
    """ Return a list of dictionaries describing the verification links to a test case. """
    tc2vers = TestCaseToVerItem.objects.filter(test_case=test_case.id).order_by('kind','ver_item')
    link_list = []
    for tc2ver in tc2vers:
        link_item = {}
        try:
            link_item['cond'] = tc2ver.cond
            link_item['kind'] = tc2ver.kind
            link_item['id'] = tc2ver.id
            if tc2ver.kind == 'REQ':
                req = Requirement.objects.get(id=tc2ver.ver_item)
                link_item['name'] = req.domain+'-'+req.name
                link_item['title'] = req.title
                link_item['desc'] = req.text
            elif tc2ver.kind == 'DI':
                di = DataItem.objects.get(id=tc2ver.ver_item)
                link_item['name'] = di.name
                link_item['title'] = get_short_desc(di.description)
                link_item['desc'] = di.description
            elif tc2ver.kind == 'State Machine' or tc2ver.kind == 'Procedure':
                mod = FwProfileModel.objects.get(id=tc2ver.ver_item)
                link_item['name'] = mod.name
                link_item['title'] = mod.title
                link_item['desc'] = ''
            else:
                print('Invalid verification item kind ' + tc2ver.kind + ' for test case ' + test_case.name)
                link_item['name'] = 'Error'
                link_item['title'] = 'Error'
                link_item['desc'] = 'Error'
        except:
            print('Non-existent verification item ' + tc2ver.kind + ':' + str(tc2ver.ver_item) + ' for test case ' + test_case.name)
            link_item['name'] = 'Error'
            link_item['title'] = 'Error'
            link_item['desc'] = 'Error'
        
        link_list.append(link_item)
        
    return link_list

#--------------------------------------------------------------------------------
def render_links_for_edit(test_case):
    """ Return a string holding the links attached to the argument test case. """
    tc2vers = TestCaseToVerItem.objects.filter(test_case=test_case.id)
    s = ''
    for tc2ver in tc2vers:
        if len(s) > 0:
            s = s + '\n'
        try:
            if tc2ver.kind == 'REQ':
                req = Requirement.objects.get(id=tc2ver.ver_item)
                domain = req.domain
                name = req.name
                s = s + '#req:'
            elif tc2ver.kind == 'DI':
                di = DataItem.objects.get(id=tc2ver.ver_item)
                domain = di.domain
                name = di.name
                s = s + '#di:'
            elif tc2ver.kind == 'State Machine' or tc2ver.kind == 'Procedure':
                mod = FwProfileModel.objects.get(id=tc2ver.ver_item)
                domain = mod.domain
                name = mod.name
                s = s + '#mod:'
            else:
                print('Invalid verification item kind ' + tc2ver.kind + ' for test case ' + test_case.name)
                domain = 'Error'
                name = 'Error'
        except:
            print('Non existent verification item ' + tc2ver.kind + ':' + str(tc2ver.ver_item) + ' for test case ' + test_case.name)
            domain = 'Error'
            name = 'Error'
        
        s = s + domain + ':' + name + ' |' + tc2ver.cond 
        
    return s

#--------------------------------------------------------------------------------
def render_ver_items_for_display(test_case):
    tc2vers = TestCaseToVerItem.objects.filter(test_case=test_case.id).order_by('kind','ver_item')
    application_id = test_case.application.id
    project_id = test_case.application.project.id
    s = ''
    for tc2ver in tc2vers:
        if len(s) > 0:
            s = s + '<br>'
        try:
            if tc2ver.kind == 'REQ':
                req = Requirement.objects.get(id=tc2ver.ver_item)
                target = '/CordetFwEditor/'+str(project_id)+'/'+str(application_id)+'/list_requirements?domainSelected='+req.domain
                s= s + '<a href=\"'+target+'\" title=\"'+req.title+': '+convert_spec_item_to_latex(req.text)+ \
                          '\">'+req.domain+'-'+req.name+'</a>'+' ('+tc2ver.cond+')'
            elif tc2ver.kind == 'DI':
                di = DataItem.objects.get(id=tc2ver.ver_item)
                val_set_id = DataItemValSet.objects.get(project_id=project_id, name='Default').id
                sel_domain = di.domain
                target = '/CordetFwEditor/'+str(project_id)+'/'+str(val_set_id)+'?domainSelected='+sel_domain
                s = s + '<a href=\"'+target+'\" title=\"'+convert_spec_item_to_latex(di.value)+' '+\
                          di.unit+' ('+di.description+')\">'+di.name+'</a>'+' ('+tc2ver.cond+')'
            elif tc2ver.kind == 'State Machine':
                mod = FwProfileModel.objects.get(id=tc2ver.ver_item)
                target = '/CordetFwEditor/'+str(project_id)+'/'+str(application_id)+'/view_model?model_id='+str(mod.id)+'&domainSelected='+mod.domain
                s = s + '<a href=\"'+target+'\" title=\"'+mod.kind+' '+mod.desc+' '+'\">'+mod.name + '</a>'+' SM ('+tc2ver.cond+')'          
            elif tc2ver.kind == 'Procedure':
                mod = FwProfileModel.objects.get(id=tc2ver.ver_item)
                target = '/CordetFwEditor/'+str(project_id)+'/'+str(application_id)+'/view_model?model_id='+str(mod.id)+'&domainSelected='+mod.domain
                s = s + '<a href=\"'+target+'\" title=\"'+mod.kind+' '+mod.desc+' '+'\">'+mod.name + '</a>'+' Proc. ('+tc2ver.cond+')'          
            else:
                print('Invalid verification item kind ' + tc2ver.kind + ' for test case ' + test_case.name)
                s = s + 'Invalid verification item kind ' + tc2ver.kind
        except:
            print('Non existent verification item ' + s + ':' + str(tc2ver.ver_item) + ' for test case ' + test_case.name)
            s = s + 'Non existent verification item ' + tc2ver.kind + ':' + str(tc2ver.ver_item)
        
    return s 
        
#--------------------------------------------------------------------------------
def get_trace_req_to_tc(application_id):
    """ 
    Return a list of dictionaries with each entry describing a requirement to be verified by test 
    and the test cases which verify it.
    """
    reqs = Requirement.objects.filter(application_id=application_id, ver_method='TST').\
                            order_by('domain','name').exclude(status='DEL').exclude(status='OBS')
    req_to_tc = []
    for req in reqs:
        tc_to_vers = TestCaseToVerItem.objects.filter(kind='REQ', ver_item=req.id)
        list_of_tc = []
        for tc_to_ver in tc_to_vers:
            list_of_tc.append({'id':tc_to_ver.test_case.id, 'domain':tc_to_ver.test_case.domain, 'name':tc_to_ver.test_case.name, 'cond':tc_to_ver.cond})
        req_to_tc.append({'req_domain':req.domain, 'req_name':req.name, 'req_title':req.title, 'req_text':req.text, 'list_of_tc':list_of_tc}) 
    return req_to_tc
    
#--------------------------------------------------------------------------------
def get_trace_di_to_tc(project_id):
    """ Return a list of dictionaries with each entry describing a data item and the test cases which verify it. """
    data_items = DataItem.objects.filter(project_id=project_id).order_by('domain','name').exclude(status='DEL').exclude(status='OBS')
    di_to_tc = []
    for data_item in data_items:
        tc_to_vers = TestCaseToVerItem.objects.filter(kind='DI', ver_item=data_item.id)
        list_of_tc = []
        for tc_to_ver in tc_to_vers:
            list_of_tc.append({'id':tc_to_ver.test_case.id,'domain':tc_to_ver.test_case.domain, 'name':tc_to_ver.test_case.name, 'cond':tc_to_ver.cond})
        di_to_tc.append({'di_domain':data_item.domain, 'di_name':data_item.name, 'di_desc':data_item.description, 'list_of_tc':list_of_tc}) 
    return di_to_tc
    
#--------------------------------------------------------------------------------
def get_trace_mod_to_tc(application_id):
    """ Return a list of dictionaries with each entry describing a model and the test cases which verify it."""
    mods = FwProfileModel.objects.filter(application_id=application_id).\
                                            order_by('domain','name').exclude(status='DEL').exclude(status='OBS')
    mod_to_tc = []
    for mod in mods:
        tc_to_vers = TestCaseToVerItem.objects.filter(ver_item=mod.id).exclude(kind='REQ').exclude(kind='DI')
        list_of_tc = []
        for tc_to_ver in tc_to_vers:
            list_of_tc.append({'id':tc_to_ver.test_case.id, 'domain':tc_to_ver.test_case.domain, 'name':tc_to_ver.test_case.name, 'cond':tc_to_ver.cond})
        mod_to_tc.append({'mod_domain':mod.domain, 'mod_name':mod.name, 'mod_kind':mod.kind, 'mod_desc':mod.desc, 'list_of_tc':list_of_tc}) 
    return mod_to_tc
 
