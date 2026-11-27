from django.contrib.auth import get_user
from django.contrib import messages
from editor.models import SpecItem, ValSet
from editor.cat_validators import run_validators
from editor.link_rules import get_link_choices

#-------------------------------------------------------------------------------------------------
# Accessors which take the configuration explicitly (from get_project_config / get_request_config)
def has_cat(config, cat):
    """True if the configuration defines the category."""
    return cat in config['cats']

def get_cat_config(config, cat):
    """Definition of a category; KeyError if the configuration does not define it."""
    return config['cats'][cat]

def get_attr_config(config, cat, attr):
    """Definition of an attribute (label, kind, req_in_form) of a category; KeyError if undefined."""
    return config['cats'][cat]['attrs'][attr]

def get_general_setting(config, key):
    """A project-level general setting (csv_sep, eol_sep, short_desc_len, max_depth); never temp_dir."""
    return config['general'][key]

#-------------------------------------------------------------------------------------------------
# Relationship choices and category-specific checks, driven by the `links` and `validators` settings of the
# category in the project configuration (see editor/link_rules.py and editor/cat_validators.py).
# `config` is the full configuration of the project (get_request_config in a view).

def get_p_link_choices(cat, project, application, p_parent_id, s_parent_id, config):
    """ 
        If p_parent_id is different from None, the function returns the spec_items which 
        have p_parent_id as their p_link parent. Otherwise, it returns the range of 
        choices for the 'p_link' attribute of a spec_item of a given category 
    """
    return get_link_choices(config, 'p_link', cat, project, application,
                            p_parent_id, s_parent_id)

#-------------------------------------------------------------------------------------------------    
def get_s_link_choices(cat, project, application, s_parent_id, p_parent_id, config):
    """ 
        If s_parent_id is different from None, the function returns the spec_items which 
        have s_parent_id as their s_link parent. Otherwise, it returns the range of 
        choices for the 's_link' attribute of a spec_item of a given category 
    """
    return get_link_choices(config, 's_link', cat, project, application,
                            s_parent_id, p_parent_id)

#-------------------------------------------------------------------------------------------------    
def do_cat_specific_checks(form, config):
    """ Run the validators configured for the category of the form; return an error message or '' """
    cat_config = config.get('cats', {}).get(form.cat)
    if not isinstance(cat_config, dict) or 'validators' not in cat_config:
        return ''
    return run_validators(form, form.cleaned_data, cat_config['validators'], 'cats.%s.validators' % form.cat)
