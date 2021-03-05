from django import template
from django.utils.safestring import mark_safe
from ..configs import configs
from ..utilities import convert_db_to_display, eval_di_value, convert_db_to_edit
register = template.Library()

@register.filter(is_safe=True)
def filter_refs(s):
    """
    The argument is a string which contains references and must be rendered in an html page.
    The input should be passed through escape() before being filtered to ensure that any html code entered 
    by the (possibly malicious) user has been sanitized.
    """
    return mark_safe(convert_db_to_display(s, 1))

@register.filter(is_safe=True)
def filter_ver_items(tc):
    """
    The argument is a test case record.
    The filter returns a string holding a description of the items verified by the test case.
    """
    return mark_safe(render_ver_items_for_display(tc))

@register.filter(is_safe=True)
def filter_di_value(val):
    """ Parse the mathematical expression in a data item value and return its numerical value. """
    return mark_safe(eval_di_value(val))

@register.filter(is_safe=True)
def filter_refs_for_tip(s):
    """
    The argument is a string which contains references and must be rendered in the tip field of an html page.
    The input should be passed through escape() before being filtered to ensure that any html code entered 
    by the (possibly malicious) user has been sanitized.
    """
    return mark_safe(convert_db_to_edit(s))

@register.filter(is_safe=True)
def get_dict_item(dict, key):
    """ Return the value of the argument key in the argument dictionary """
    return dict.get(key)

@register.filter(is_safe=True)
def get_short_desc(spec_item):
    """ Return a short description of the specification item """
    if spec_item.cat == 'VerLink':
        desc = spec_item.title + ': '+spec_item.value + ' (' + spec_item.p_link.domain + ':' + \
               spec_item.p_link.name + ' -> ' + spec_item.s_link.domain + ':' + \
               spec_item.s_link.name + ')'
    else:
        desc = spec_item.title + ':'  + spec_item.desc        
    if len(desc) > configs['General']['short_desc_len']:
        return desc[:configs['General']['short_desc_len']]+' ...'
    else:
        return desc
