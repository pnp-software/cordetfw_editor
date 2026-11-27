"""Declarative relationship rules of a project configuration (`cats.<Cat>.links`) and traceability settings.

Schema of `cats.<Cat>.links` (both keys optional; a missing rule offers no choices):

    {"p_link": RULE, "s_link": RULE}
    RULE = {"targets": [Cat, ...]              # items of these categories are offered, or
            "all_except": [Cat, ...],          # items of all categories but these (exactly one of the two)
            "scope": "project" | "application",           # optional, default "project"
            "order_by": ["domain", "name"],               # optional, subset of ORDER_FIELDS (default shown)
            "narrow_by_other_parent": {"target_field": "p_link" | "s_link",    # optional
                                       "parent_field": "p_link" | "s_link"}}

Choices never include items with status DEL or OBS and always belong to the project. With scope "application"
only items of the application the form is used in are offered (none without an application). When the opposite
link's parent item is given (adding an item from an expanded item), `narrow_by_other_parent` restricts the
targets to those whose `target_field` equals the `parent_field` of that parent item. A parent item passed for the
link itself overrides the rule (only that item, if it belongs to the project).

Schema of `cats.<Cat>.tracs` (traceability): a list of {"trac_cat": Cat, "trac_link": "p_link" | "s_link"}.
`trac_cat` is the link category (e.g. TracLink, VerLink); `trac_link` is the endpoint of its items which points
to the item being listed, the other endpoint is the referenced item.

Configuration is data: nothing here evaluates or imports anything named in it. The `check_*` functions return
a list of (json_path, message) tuples.
"""
from editor.models import SpecItem

LINK_FIELDS = ('p_link', 's_link')
SCOPES = ('project', 'application')
ORDER_FIELDS = ('cat', 'domain', 'name')
DEFAULT_ORDER = ['domain', 'name']
RULE_KEYS = ('targets', 'all_except', 'scope', 'order_by', 'narrow_by_other_parent')
NARROW_KEYS = ('target_field', 'parent_field')
TRAC_KEYS = ('trac_cat', 'trac_link')


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def get_link_rule(config, cat, link):
    """The rule for `link` of category `cat`, or None when the configuration defines none (or is malformed)."""
    cat_config = config.get('cats', {}).get(cat) if isinstance(config, dict) else None
    links = cat_config.get('links') if isinstance(cat_config, dict) else None
    rule = links.get(link) if isinstance(links, dict) else None
    return rule if isinstance(rule, dict) else None


def get_link_choices(config, link, cat, project, application, parent_id, other_parent_id):
    """
    Queryset of the items which can be chosen for `link` ('p_link' or 's_link') of an item of category `cat`
    in `project`, as defined by `config` (see the module docstring). A malformed rule offers nothing.
    """
    if parent_id is not None:
        return SpecItem.objects.filter(id=int(parent_id), project_id=project.id)

    rule = get_link_rule(config, cat, link)
    if rule is None or check_link_rule(rule, link):
        return SpecItem.objects.none()

    items = SpecItem.objects.filter(project_id=project.id).exclude(status='DEL').exclude(status='OBS')
    if rule.get('scope', 'project') == 'application':
        if application is None:
            return SpecItem.objects.none()
        items = items.filter(application_id=application.id)
    if 'targets' in rule:
        items = items.filter(cat__in=rule['targets'])
    else:
        items = items.exclude(cat__in=rule['all_except'])
    narrow = rule.get('narrow_by_other_parent')
    if narrow is not None and other_parent_id is not None:
        other_parent = SpecItem.objects.get(id=other_parent_id, project_id=project.id)
        items = items.filter(**{narrow['target_field']: getattr(other_parent, narrow['parent_field'])})
    return items.order_by(*rule.get('order_by', DEFAULT_ORDER))


def check_link_rule(rule, path, cats=None):
    """Errors of one rule; `cats` (iterable of category names) enables the check of category references."""
    if not isinstance(rule, dict):
        return [(path, 'must be an object')]
    errors = [('%s.%s' % (path, key), 'unknown setting') for key in rule if key not in RULE_KEYS]
    if ('targets' in rule) == ('all_except' in rule):
        errors.append((path, 'exactly one of "targets" and "all_except" is required'))
    for key in ('targets', 'all_except'):
        if key not in rule:
            continue
        if not _is_str_list(rule[key]) or (key == 'targets' and not rule[key]):
            errors.append((path + '.' + key, 'must be %s list of category names' % (
                'a non-empty' if key == 'targets' else 'a')))
        elif cats is not None:
            errors += [('%s.%s[%d]' % (path, key, i), 'unknown category "%s"' % name)
                       for i, name in enumerate(rule[key]) if name not in cats]
    if 'scope' in rule and rule['scope'] not in SCOPES:
        errors.append((path + '.scope', 'must be one of ' + ', '.join(SCOPES)))
    if 'order_by' in rule:
        order = rule['order_by']
        if not _is_str_list(order) or not order or any(name not in ORDER_FIELDS for name in order):
            errors.append((path + '.order_by', 'must be a non-empty list of: ' + ', '.join(ORDER_FIELDS)))
    if 'narrow_by_other_parent' in rule:
        narrow = rule['narrow_by_other_parent']
        narrow_path = path + '.narrow_by_other_parent'
        if not isinstance(narrow, dict):
            errors.append((narrow_path, 'must be an object'))
        else:
            errors += [('%s.%s' % (narrow_path, key), 'unknown setting') for key in narrow if key not in NARROW_KEYS]
            errors += [(narrow_path + '.' + key, 'must be one of ' + ', '.join(LINK_FIELDS))
                       for key in NARROW_KEYS if narrow.get(key) not in LINK_FIELDS]
    return errors


def check_link_rules(links, path, cats=None):
    """Errors of a `links` object (the rules of one category)."""
    if not isinstance(links, dict):
        return [(path, 'must be an object')]
    errors = []
    for key, rule in links.items():
        if key not in LINK_FIELDS:
            errors.append(('%s.%s' % (path, key), 'unknown link; must be one of ' + ', '.join(LINK_FIELDS)))
        else:
            errors += check_link_rule(rule, path + '.' + key, cats)
    return errors


def check_trac_settings(tracs, path, cats=None):
    """Errors of a `tracs` list (traceability settings of one category)."""
    if not isinstance(tracs, list):
        return [(path, 'must be a list')]
    errors = []
    for i, trac in enumerate(tracs):
        trac_path = '%s[%d]' % (path, i)
        if not isinstance(trac, dict):
            errors.append((trac_path, 'must be an object'))
            continue
        errors += [('%s.%s' % (trac_path, key), 'unknown setting') for key in trac if key not in TRAC_KEYS]
        if not isinstance(trac.get('trac_cat'), str):
            errors.append((trac_path + '.trac_cat', 'must be a category name'))
        elif cats is not None and trac['trac_cat'] not in cats:
            errors.append((trac_path + '.trac_cat', 'unknown category "%s"' % trac['trac_cat']))
        if trac.get('trac_link') not in LINK_FIELDS:
            errors.append((trac_path + '.trac_link', 'must be one of ' + ', '.join(LINK_FIELDS)))
    return errors


def rule_allows(rule, cat):
    """True if a well-formed rule offers items of category `cat` as targets."""
    if 'targets' in rule:
        return cat in rule['targets']
    return cat not in rule['all_except']


def prune_link_rules(links, cats):
    """
    Copy of a `links` object without names of categories not in `cats` in "targets"/"all_except"; a rule left
    without targets is removed. Malformed parts are kept (check_link_rules reports them).
    """
    if not isinstance(links, dict):
        return links
    pruned = {}
    for link, rule in links.items():
        if isinstance(rule, dict):
            rule = dict(rule)
            if 'targets' in rule and _is_str_list(rule['targets']):
                rule['targets'] = [name for name in rule['targets'] if name in cats]
                if not rule['targets']:
                    continue
            elif 'all_except' in rule and _is_str_list(rule['all_except']):
                rule['all_except'] = [name for name in rule['all_except'] if name in cats]
        pruned[link] = rule
    return pruned
