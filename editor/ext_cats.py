import MySQLdb as mdb
import re
import sys
import json
import os
from django.core.exceptions import MultipleObjectsReturned
from django.contrib.auth import update_session_auth_hash, get_user
from django.contrib import messages
from operator import itemgetter
from datetime import datetime
from editor.choices import MODEL_KIND
from editor.svg_check import svg_rule_violation

#--------------------------------------------------------------------------------
def connect(request):
    """ Open connection to fwprofile db. In case of error, an error msg is returned. """
    try:
        with open(os.environ.get('CORDETFW_CONFIG_PATH', '/etc/dj_cordetfw_config.json')) as config_file:
            config = json.load(config_file)
    except Exception as e:
        messages.error(request, 'Unable to access credentials for FW Profile database')
        return (None, None)
    try:
        fw_db = mdb.connect(config['FWPROFILE_DB']['HOST'], 
                            config['FWPROFILE_DB']['USER'], 
                            config['FWPROFILE_DB']['PWD'],
                            config['FWPROFILE_DB']['NAME'])
        fw_db_cur = fw_db.cursor()
    except Exception as e:
        messages.error(request, 'Unable to connect to the FW Profile database: '+ repr(e))
        return (None, None)
    
    return (fw_db, fw_db_cur)


#--------------------------------------------------------------------------------
def get_model_domain(json_rep):
    """ Return the domain of a model """
    jsonObj = json.loads(json_rep)
    return jsonObj['globals']['fwprop']['smTags']


def get_visible_models(request, model_id=None):
    email = request.user.email
    if not email:
        return []

    fw_db, fw_db_cur = connect(request)
    if fw_db is None:
        return []

    try:
        query = (
            'SELECT diagrams.* FROM diagrams WHERE ('
            'EXISTS (SELECT 1 FROM users WHERE users.id = diagrams.userID '
            'AND users.email = %s) OR '
            'EXISTS (SELECT 1 FROM shares WHERE shares.diagramID = diagrams.id '
            "AND shares.email = %s AND shares.perm IN ('ro', 'rw')))"
        )
        parameters = [email, email]
        if model_id is not None:
            query += ' AND diagrams.id = %s'
            parameters.append(model_id)
        fw_db_cur.execute(query, parameters)
        return fw_db_cur.fetchall()
    finally:
        fw_db.close()


#--------------------------------------------------------------------------------
def ext_model_refresh(request, spec_item):
    # NOTE: the attributes refreshed here must stay in sync with views.REFRESHED_ATTRS
    """ 
    Argument spec_item holds an external model which needs to be refreshed.
    The function retrieves the model from the FW Profile Database. If the 
    model cannot be extracted from the database, the function issues a warning
    and returns 'NOT_FOUND'. 
    If the model does exist in the FW Profile Database, the function checks 
    whether its svg image is different from the one held in spec_item.
    If it is different, it updates spec_item with the new model instance
    and returns 'REFRESH'. If, instead, the svg image has not changed, the 
    function return 'NO_CHANGE'.
    """
    model_id = spec_item.n3
    try:
        diagrams = get_visible_models(request, model_id)
    except Exception as e:
        messages.error(request, 'Error while accessing model with ID \"'+str(model_id)+': '+str(e))
        return 'NOT_FOUND'
    
    if len(diagrams) == 0:
        messages.warning(request, 'Model not found or not shared with you in FW Profile Database (its ID is: '+str(model_id)+')')
        return 'NOT_FOUND'
        
    if diagrams[0][7] == spec_item.value:
        return 'NO_CHANGE'
    
    svg_error = svg_rule_violation(diagrams[0][7])        # Task 6.6b: image-svg-unsanitised
    if svg_error:
        messages.error(request, 'Model with ID \"'+str(model_id)+'\" not refreshed: its image contains disallowed content ('+svg_error+')')
        return 'INVALID'

    spec_item.domain = get_model_domain(diagrams[0][6]) or ''        
    spec_item.name = diagrams[0][2]
    if diagrams[0][4] == 'Procedure':
        spec_item.p_kind = MODEL_KIND[1][0]
    else:
        spec_item.p_kind = MODEL_KIND[0][0]
    spec_item.updated_at = diagrams[0][5]
    spec_item.value = diagrams[0][7]     # svg representation of diagram
    spec_item.n1 = diagrams[0][8]        # figure width
    spec_item.n2 = diagrams[0][9]        # figure height
    spec_item.n3 = diagrams[0][0]        # ID in FW Profile Database

    return 'REFRESH'


#--------------------------------------------------------------------------------
def ext_model_get_choice(request, model_id):
    """ 
    Function takes as input the choice made by the user out of the options presented
    by function ext_model_get_choices. It returns a dictionary holding the values of
    the external attributes for the chosen model instance (or None if the model
    instance cannot be found).
    (NB: The external attributes are those listed at the 'ext_att' key in the
         'configs' dictionary).
    """
    try:
        diagrams = get_visible_models(request, model_id)
    except Exception as e:
        messages.error(request, 'Error while accessing model with ID \"'+str(model_id)+': '+str(e))
        return None

    if not diagrams:
        messages.warning(request, 'Model not found or not shared with you in FW Profile Database')
        return None

    ext_item_dict = {}
            
    ext_item_dict['domain'] = get_model_domain(diagrams[0][6]) or ''        
    ext_item_dict['name'] = diagrams[0][2]
    if diagrams[0][4] == 'Procedure':
        ext_item_dict['p_kind'] = MODEL_KIND[1][0]
    else:
        ext_item_dict['p_kind'] = MODEL_KIND[0][0]
    ext_item_dict['updated_at'] = diagrams[0][5]
    ext_item_dict['value'] = diagrams[0][7]     # svg representation of diagram
    ext_item_dict['n1'] = diagrams[0][8]        # figure width
    ext_item_dict['n2'] = diagrams[0][9]        # figure height
    ext_item_dict['n3'] = diagrams[0][0]        # ID in FW Profile Database
 
    return ext_item_dict

 
#--------------------------------------------------------------------------------
def ext_model_get_choices(request):
    """ 
    Return the list of models available for import in the editor.
    These are the models visible to the user in the FW Profile DB, including
    models shared by other users.
    """
    empty_choice_list = [(0, 'No Model Found')]
    
    try:
        diagrams = get_visible_models(request)
    except Exception as e:
        messages.error(request, 'Error trying to retrieve the models from FW Profile DB: '+str(e))
        return empty_choice_list
    
    model_list = []
    for diagram in diagrams:
        dom_name = (diagram[0], (get_model_domain(diagram[6]) or '')+' : '+diagram[2])     # ext-cats-null-domain
        model_list.append(dom_name)

    if model_list == []:
        messages.error(request, 'No models found in FW Profile Database for user \"'+\
                                str(request.user))
        return empty_choice_list
        

    return sorted(model_list, key=lambda tup: (tup[1].split(':')[0], tup[1].split(':')[1]))

#--------------------------------------------------------------------------------
def get_owned_diagrams(request, diagram_id):
    """
    Return the rows of the diagram with the given ID if it is owned by the user calling
    this function (FCPs are only offered to their owner, see ext_fcp_get_choices).
    Parameterized query; the connection is closed on every path. Errors from the database
    are raised; an unusable connection or a user without e-mail yields an empty list.
    """
    email = request.user.email
    if not email:
        return []
    fw_db, fw_db_cur = connect(request)
    if fw_db is None:
        return []
    try:
        fw_db_cur.execute(
            'SELECT diagrams.* FROM diagrams WHERE diagrams.id = %s AND '
            'EXISTS (SELECT 1 FROM users WHERE users.id = diagrams.userID AND users.email = %s)',
            [diagram_id, email])
        return fw_db_cur.fetchall()
    finally:
        fw_db.close()


#--------------------------------------------------------------------------------
def ext_fcp_get_choices(request):
    """ 
    Return the list of FCP models available for import in the editor.
    These are the models in the FW Profile DB whose names starts with 
    'fcp_' and which are owned by the user calling this function.
    """
    empty_choice_list = [(0, 'No FCP Found')]

    fw_db, fw_db_cur = connect(request)
    if fw_db is None:
        return empty_choice_list

    try:
        user_email = request.user.email
        try:
            fw_db_cur.execute('SELECT * FROM users WHERE email = %s', [user_email])
            user = fw_db_cur.fetchall()
        except Exception as e:
            messages.error(request, 'User \"'+str(request.user)+'\" with e-mail \"'+str(user_email)+\
                                '\" not found in FW Profile DB: '+str(e))
            return empty_choice_list

        try:
            fw_db_cur.execute('SELECT * FROM diagrams WHERE userID = %s', [user[0][0]])
            diagrams = fw_db_cur.fetchall()
        except Exception as e:
            messages.error(request, 'Error trying to retrieve the FCPs for user \"'+str(user_email)+':'+str(e))
            return empty_choice_list
    finally:
        fw_db.close()

    model_list = []
    for diagram in diagrams:
        domain = get_model_domain(diagram[6])
        if domain is None or not domain.endswith('Fcp'):       # ext-cats-null-domain: no domain = not an FCP
            continue
        model_list.append((diagram[0], domain+' : '+diagram[2]))

    if model_list == []:
        messages.error(request, 'No FCPs found in FW Profile Database for user \"'+\
                                str(request.user)+'\" with e-mail \"'+str(user_email))
        return empty_choice_list

    return sorted(model_list, key=lambda tup: (tup[1].split(':')[0], tup[1].split(':')[1]))

#--------------------------------------------------------------------------------
def get_fcp_desc(json_rep): 
    """ Return the title and description of the FCP held in the argument json object """
    jsonObj = json.loads(json_rep)
    fcpStates = jsonObj["states"]
    for state in fcpStates:
        note = state["fwprop"]["note"]
        start = note.find("Title:")
        if (start > -1):
            end = note.find("\n")
            title = note[start+6:end].strip()
            descStart = note.find("\n")
            desc = note[descStart+1:]
            desc = desc.replace("\n"," ")
            desc = desc.strip() 
            return {'title': title, 'desc': desc}
    return None    

def get_fcp_title_desc(request, json_rep, fcp_id):
    """ Return (title, desc) of an FCP; if it has no 'Title:' note: warn and return ('', '') """
    fcp_desc = get_fcp_desc(json_rep)
    if fcp_desc is None:
        messages.warning(request, 'FCP with ID \"'+str(fcp_id)+'\" has no title: no state note holds \"Title:\"')
        return ('', '')
    return (fcp_desc['title'], fcp_desc['desc'])

#--------------------------------------------------------------------------------
def ext_fcp_get_choice(request, fcp_id):
    """ 
    Function takes as input the choice made by the user out of the options presented
    by function ext_fcp_get_choices. It returns a dictionary holding the values of
    the external attributes for the chosen FCP instance (or None if the FCP
    instance cannot be found).
    (NB: The external attributes are those listed at the 'ext_att' key in the
         'configs' dictionary).
    """        
    try:
        diagrams = get_owned_diagrams(request, fcp_id)
    except Exception as e:
        messages.error(request, 'Error while accessing model with ID \"'+str(fcp_id)+': '+str(e))
        return None

    if not diagrams:
        messages.warning(request, 'FCP not found in FW Profile Database (its ID is: '+str(fcp_id)+')')
        return None

    ext_item_dict = {}
            
    ext_item_dict['domain'] = get_model_domain(diagrams[0][6]) or ''        
    ext_item_dict['name'] = diagrams[0][2]
    ext_item_dict['updated_at'] = diagrams[0][5]
    ext_item_dict['title'], ext_item_dict['desc'] = get_fcp_title_desc(request, diagrams[0][6], fcp_id)
    ext_item_dict['value'] = diagrams[0][7]     # svg representation of diagram
    ext_item_dict['n1'] = diagrams[0][8]        # figure width
    ext_item_dict['n2'] = diagrams[0][9]        # figure height
    ext_item_dict['n3'] = diagrams[0][0]        # ID in FW Profile Database
 
    return ext_item_dict

#--------------------------------------------------------------------------------
def ext_fcp_refresh(request, spec_item):
    """ 
    Argument spec_item holds an external FCP which needs to be refreshed.
    The function retrieves the FCP from the FW Profile Database. If the 
    FCP cannot be extracted from the database, the function issues a warning
    and returns 'NOT_FOUND'. 
    If the FCP does exist in the FW Profile Database, the function checks 
    whether its svg image is different from the one held in spec_item.
    If it is different, it updates spec_item with the new FCP instance
    and returns 'REFRESH'. If, instead, the svg image has not changed, the 
    function return 'NO_CHANGE'.
    """
    model_id = spec_item.n3
    try:
        diagrams = get_owned_diagrams(request, model_id)
    except Exception as e:
        messages.error(request, 'Error while accessing model with ID \"'+str(model_id)+': '+str(e))
        return 'NOT_FOUND'
    
    if len(diagrams) == 0:
        messages.warning(request, 'FCP not found in FW Profile Database (its ID is: '+str(model_id)+')')
        return 'NOT_FOUND'
        
    if diagrams[0][7] == spec_item.value:
        return 'NO_CHANGE'
    
    svg_error = svg_rule_violation(diagrams[0][7])        # Task 6.6b: image-svg-unsanitised
    if svg_error:
        messages.error(request, 'FCP with ID \"'+str(model_id)+'\" not refreshed: its image contains disallowed content ('+svg_error+')')
        return 'INVALID'

    spec_item.domain = get_model_domain(diagrams[0][6]) or ''        
    spec_item.name = diagrams[0][2]
    spec_item.title, spec_item.desc = get_fcp_title_desc(request, diagrams[0][6], model_id)
    spec_item.updated_at = diagrams[0][5]
    spec_item.value = diagrams[0][7]     # svg representation of diagram
    spec_item.n1 = diagrams[0][8]        # figure width
    spec_item.n2 = diagrams[0][9]        # figure height
    spec_item.n3 = diagrams[0][0]        # ID in FW Profile Database

    return 'REFRESH'
