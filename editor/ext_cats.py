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
def get_model_kind(json_rep):
    """ Return the model kind (SM or PR) """
    jsonObj = json.loads(json_rep)
    return jsonObj['globals']['fwprop']['editorType'].upper()

#--------------------------------------------------------------------------------
def get_model(request, domain, name):
    """ Return a dictionary describing the FW Profile model of name 'name' in project 'domain' """
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
        fw_db_cur.execute('SELECT * FROM diagrams WHERE userID = '+str(user[0][0])+' AND name = \''+name+'\'') 
        diagrams = fw_db_cur.fetchall()
    except Exception as e:
        messages.error(request, 'No model with name \"'+name+'\" for user \"'+user_email+\
                            '\" found FW Profile DB: '+str(e))
        return None

    for diagram in diagrams:
        if get_model_domain(diagram[6]) == domain:
            d = {}
            d['name'] = diagram[2]
            d['kind'] = diagram[4]
            d['updated_at'] = diagram[5]
            d['json_rep'] = diagram[6]
            d['svg_rep'] = diagram[7]
            d['width'] = diagram[8]
            d['height'] = diagram[9]
            d['domain'] = domain
            fw_db.close()
            return d
   
    messages.error(request, 'No model of name \"'+name+'\" exists in FW Project \"'+domain+'\" for user \"'+user_email+'\"')
    fw_db.close()
    return None

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
        messages.error(request, 'No model with ID \"'+str(model_id)+': '+str(e))
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
        fw_db_cur.execute('SELECT * FROM diagrams WHERE userID = '+str(user[0][0])) 
        diagrams = fw_db_cur.fetchall()
    except Exception as e:
        messages.error(request, 'Error trying to retrieve the models for for user \"'+user_email+':'+str(e))
        return None
    
    model_list = []
    for diagram in diagrams:
        dom_name = (diagram[0], get_model_domain(diagram[6])+':'+diagram[2])
        model_list.append(dom_name)

    fw_db.close()
    return model_list

