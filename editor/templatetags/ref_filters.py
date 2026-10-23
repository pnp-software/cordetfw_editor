from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape
from django.db.models import Q
from ..models import SpecItem
from ..configs import configs
from ..convert import conv_do_nothing, conv_db_disp_ref_text, conv_db_disp_plain_ref, \
                      conv_db_disp_spec_item_ref, conv_db_disp_date, eval_di_value, \
                      convert_db_to_edit, convert_db_to_display, conv_db_disp_table, \
                      conv_db_disp_plain_text, escape_text
from .. import convert

register = template.Library()

# The key is the name of a kind of specification item attribute content; the value
# is the function which transforms that content from database to display representation  
conv_db_disp_func = {"plain_text": "conv_db_disp_plain_text",
                     'ref_text': "conv_db_disp_ref_text",
                     'plain_ref': "conv_db_disp_plain_ref",
                     'spec_item_ref': "conv_db_disp_spec_item_ref",
                     'eval_ref': 'conv_db_disp_eval_ref',
                     'int': "conv_do_nothing",
                     'image': "conv_do_nothing",
                     'date': "conv_db_disp_date",
                     'table': "conv_db_disp_table"}


@register.simple_tag(takes_context=True)
def conv_db_disp(context, spec_item, attr_names):
    """ 
    For each attribute 'attr_name' in 'attr_names', derive the value of 'attr_name' of
    spec_item 'spec_item' and convert it from db to display format.
    The function returns a list of tuples (name, value) where 'name' is the
    label corresponding to the attribute 'attr_name' and 'value' is the converted
    value of the attribute.
    Only non-empty attributes are returned. 
    """
    values = []
    for attr_name in attr_names:
        attr_content_kind = configs['cats'][spec_item.cat]['attrs'][attr_name]['kind']
        conv_func = conv_db_disp_func[attr_content_kind]
        s = getattr(convert, conv_func)(context, spec_item, attr_name, context['sel_rel'])
        if s != '':
            values.append((context['config']['attrs'][attr_name]['label'], mark_safe(s)))
    return values

 
def trac_link_html(target, item):
    """
    Hyperlink to 'item' for the traceability display. Attribute values (href, title) get the full
    escape(); the text nodes (domain:name and title) escape only &, < and >.
    """
    return '<a class="link-table-list-spec" href="' + escape(target + '#' + item.domain + ':' + item.name) + \
           '" title="' + escape(item.desc) + '">' + escape_text(item.domain) + ':' + escape_text(item.name) + \
           '</a> (' + escape_text(item.title) + ')'


@register.simple_tag(takes_context=True)
def disp_trac(context, spec_item, trac_cat, trac_link, sel_rel):
    """ 
    Generate the display representation of the traceability information for a spec_item.
    If S is spec_item, then this function assumes that the traceability link is stored
    in category 'trac_cat' and that attribute 'trac_link' holds the link from trac_cat
    to spec_item. trac_link is either 's_link' or 'p_link'.
    To illustrate, suppose that 'trac_link' is equal to 's_link'; in this case, the  
    function proceeds in two steps:
    - It extracts all the spec_items L1, L2, ... Ln which belong to category trac_cat  
      and which point to S through their s_link
    - It returns a string holding a list of the spec_items which are pointed at by
      L1, L2, ... Ln through their p_link
    """
    
    if sel_rel == None:
        sel_rel_id = 0
        if trac_link == 's_link':
            trac_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat=trac_cat,
                        s_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
        else:
            trac_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat=trac_cat,
                        p_link_id=spec_item.id).exclude(status='DEL').exclude(status='OBS')
    else:
        sel_rel_id = sel_rel.id
        if trac_link == 's_link':
            trac_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat=trac_cat,
                        s_link_id=spec_item.id).exclude(status='NEW').exclude(status='MOD')
        else:
            trac_links = SpecItem.objects.filter(project_id=spec_item.project_id, cat=trac_cat,
                        p_link_id=spec_item.id).exclude(status='NEW').exclude(status='MOD')
        # Only retain items created before the release date
        trac_links = trac_links.filter(created_at__lte=sel_rel.updated_at)
        # Exclude CNF items updated after the release date
        trac_links = trac_links.exclude(Q(status='CNF') & Q(updated_at__gt=sel_rel.updated_at))
        # Exclude items deleted before the release date 
        trac_links = trac_links.exclude(Q(status='DEL') & Q(updated_at__lt=sel_rel.updated_at))
        # Exclude items which were first updated after the release data and then deleted
        trac_links = trac_links.exclude(Q(status='DEL') & (Q(previous__isnull=False) & Q(previous__updated_at__gt=sel_rel.updated_at)))
        # Exclude items representing updates done before the release date 
        trac_links = trac_links.exclude(Q(status='OBS') & Q(updated_at__lt=sel_rel.updated_at))
        # Exclude items representing updates done after releases later than the selected release
        trac_links = trac_links.exclude(Q(status='OBS') & (Q(previous__isnull=False) & Q(previous__updated_at__gt=sel_rel.updated_at)))

    s = ''
    
    for link in trac_links:
        application_id = str(link.p_link.application_id)
        if application_id == 'None':
            application_id = '0'

        if trac_link == 's_link' and link.p_link != None:
            target = '/editor/'+link.p_link.cat+'/'+str(link.p_link.project_id)+'/'+application_id+\
                    '/'+str(spec_item.val_set.id)+'/'+link.p_link.domain+'/'+str(sel_rel_id)+'\\list_spec_items'
            s = s + trac_link_html(target, link.p_link)
            s = s + '\n'
            continue
        
        if trac_link == 'p_link' and link.s_link != None:
            target = '/editor/'+link.s_link.cat+'/'+str(link.s_link.project_id)+'/'+application_id+\
                    '/'+str(spec_item.val_set.id)+'/'+link.s_link.domain+'/'+str(sel_rel_id)+'\\list_spec_items'
            s = s + trac_link_html(target, link.s_link)
            s = s + '\n'    
            continue
        
    return mark_safe(s[:-1])    # The last '\n' is removed
 
 
@register.filter(is_safe=True)
def filter_expand_tip(spec_item):
    """
    The argument is a spec_item which appears in an "expand" list.
    The function returns the hovering tip for the spec_item.
    The tip is used inside a title="..." attribute: the stored values are escaped with escape()
    (the '&#13;' line separators are added afterwards).
    """
    attrs = configs['cats'][spec_item.cat]['short_desc']['expand_tip']
    s = ''
    for attr in attrs:
        s = s + configs['cats'][spec_item.cat]['attrs'][attr]['label'] +': '+\
                escape(convert_db_to_edit(getattr(spec_item, attr))) + '&#13;'
    return mark_safe(s)


@register.filter(is_safe=True)
def get_dict_item(dict, key):
    """ Return the value of the argument key in the argument dictionary """
    return dict.get(key)


@register.filter(is_safe=True)
def get_model_field(instance, field_name):
    """ Return the value of the model's instance field """
    return getattr(instance, field_name)


@register.filter(is_safe=True)
def get_label(config, attr):
    """ Return the [attrs]['label'] value of the configuration dictiornary """
    return config[attr]['label']


@register.filter(is_safe=True)
def get_short_desc(spec_item):
    """ Return a short description of the specification item """
    attrs = configs['cats'][spec_item.cat]['short_desc']['expand_text']
    desc = ''
    for attr in attrs:
        desc = desc + getattr(spec_item, attr) + ': '

    if len(desc) > configs['general']['short_desc_len']:
        return desc[:configs['general']['short_desc_len']]+' ...'
    else:
        return desc[:-2]


@register.filter
def js_str_after_html_escape(value):
    """
    For a value already HTML-escaped by autoescape and placed in a single-quoted JS string literal
    that later reaches an `html:` sink (link_suggest.html). Autoescape already encodes < > & ' ";
    this protects the literal itself: backslash, CR, LF, U+2028 and U+2029 become literal backslash
    sequences, so the JS string decodes back to the HTML-escaped text. Other bytes are unchanged
    (Task 6.6b, link-suggest-js-string).
    """
    s = str(value)
    s = s.replace('\\', '\\\\').replace('\r', '\\r').replace('\n', '\\n')
    s = s.replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    return mark_safe(s)
