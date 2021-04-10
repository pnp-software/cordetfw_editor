import MySQLdb as mdb
import re
import sys
import json
from django.core.exceptions import MultipleObjectsReturned
from django.contrib.auth import update_session_auth_hash, get_user
from django.contrib import messages
from operator import itemgetter
from datetime import datetime
from editor.choices import MODEL_KIND

#--------------------------------------------------------------------------------
def connect(request):
    """ Open connection to fwprofile db. In case of error, an error msg is returned. """
    try:
        with open('/etc/dj_cordetfw_config.json') as config_file:
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


#--------------------------------------------------------------------------------
def ext_model_refresh(request, spec_item):
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
    fw_db, fw_db_cur = connect(request)

    model_id = spec_item.n3
    try:
        fw_db_cur.execute('SELECT * FROM diagrams WHERE ID = '+str(model_id)) 
        diagrams = fw_db_cur.fetchall()
    except Exception as e:
        messages.error(request, 'Error while accessing model with ID \"'+str(model_id)+': '+str(e))
        return 'NOT_FOUND'
    
    if len(diagrams) == 0:
        messages.warning(request, 'Model not found in FW Profile Database (its ID is: '+str(model_id)+')')
        return 'NOT_FOUND'
        
    if diagrams[0][7] == spec_item.value:
        return 'NO_CHANGE'
    
    spec_item.domain = get_model_domain(diagrams[0][6])        
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

    fw_db.close()
    return 'REFRESH'


#--------------------------------------------------------------------------------
def ext_model_get_choice(request, model_id):
    """ 
    Function takes as input the choice made by the user out of the option presented
    by function ext_model_get_choices. It returns a dictionary holding the values of
    the external attributes for the chosen model instance (or None if the model
    instance cannot be found).
    (NB: The external attributes are those listed at the 'ext_att' key in the
         'configus' dictionary).
    """
    fw_db, fw_db_cur = connect(request)
    
    try:
        fw_db_cur.execute('SELECT * FROM diagrams WHERE ID = '+str(model_id)) 
        diagrams = fw_db_cur.fetchall()
    except Exception as e:
        messages.error(request, 'Error while accessing model with ID \"'+str(model_id)+': '+str(e))
        return None

    ext_item_dict = {}
            
    ext_item_dict['domain'] = get_model_domain(diagrams[0][6])        
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
 
    fw_db.close()
    return ext_item_dict

 
#--------------------------------------------------------------------------------
def ext_model_get_choices(request):
    """ 
    Return the list of models available for import in the editor.
    These are the models in the FW Profile DB owned by the user calling this function.
    """
    fw_db, fw_db_cur = connect(request)
    
    user_email = request.user.email
    try:
        fw_db_cur.execute('SELECT * FROM users WHERE email = \''+str(user_email)+'\'')    
        user = fw_db_cur.fetchall()
    except Exception as e:
        messages.error(request, 'User \"'+str(request.user)+'\" with e-mail \"'+user_email+\
                            '\" not found in FW Profile DB: '+str(e))
        return None
    
    try:
        fw_db_cur.execute('SELECT * FROM diagrams WHERE userID = '+str(user[0][0])+' ORDER BY name') 
        diagrams = fw_db_cur.fetchall()
    except Exception as e:
        messages.error(request, 'Error trying to retrieve the models for user \"'+user_email+':'+str(e))
        return None
    
    model_list = []
    for diagram in diagrams:
        dom_name = (diagram[0], get_model_domain(diagram[6])+' : '+diagram[2])
        model_list.append(dom_name)

    fw_db.close()
    return model_list

