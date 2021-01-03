from django import template
from django.utils.safestring import mark_safe
from ..utilities import render_for_display
register = template.Library()

@register.filter(is_safe=True)
def filter_refs(s):
    """
    The argument is a string which contains references and must be rendered in an html page.
    The input should be passed through escape() before being filtered to ensure that any html code entered 
    by the (possibly malicious) user has been sanitized.
    """
    return mark_safe(render_for_display(s, 1))

