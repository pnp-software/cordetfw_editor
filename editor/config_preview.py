"""Preview of an unsaved project configuration.

`build_preview(config, project)` turns a validated configuration into the data of the preview fragment
(`project_config_preview.html`): index menus, and for each category its add/edit form, table layouts, short
descriptions and relationships as the settings define them. Forms, layouts and short descriptions are shown as the
item pages will show them (without hidden attributes); the hidden attributes of a category are listed separately.
It only reads (item counts of the project) and never stores anything. The template escapes every value, so names,
labels and choices taken from the configuration cannot inject markup.
"""
from django.db.models import Count

from editor.config_cleanup import hidden_attributes
from editor.link_rules import LINK_FIELDS
from editor.models import SpecItem
from editor.project_config import shown_config

SHORT_DESC_LABELS = {'expand_text': 'Expanded text', 'href_tip': 'Link tooltip', 'expand_tip': 'Expansion tooltip'}


def _rule_text(rule, cats):
    if not isinstance(rule, dict):
        return 'no choices'
    names = rule.get('targets')
    if names is not None:
        text = 'items of ' + ', '.join(_cat_name(cats, name) for name in names)
    else:
        text = 'items of every category except ' + (', '.join(_cat_name(cats, n) for n in rule.get('all_except', []))
                                                    or 'none')
    if rule.get('scope') == 'application':
        text += ' (same application only)'
    return text


def _cat_name(cats, cat):
    definition = cats.get(cat)
    return definition['name'] if isinstance(definition, dict) and 'name' in definition else cat


def _control(attr_id, attr, definition, cats):
    """(control type, choices as (value, label) pairs, relationship text) of an attribute in the form."""
    kind = attr.get('kind')
    if attr_id in ('p_kind', 's_kind'):
        return 'select', list(definition.get(attr_id + '_choices', {}).items()), ''
    if attr_id in LINK_FIELDS:
        return 'select', [], _rule_text(definition.get('links', {}).get(attr_id), cats)
    if kind == 'plain_ref':
        return 'select', [], 'chosen from the project'
    if kind == 'int':
        return 'number', [], ''
    if kind in ('plain_text',):
        return 'text', [], ''
    return 'textarea', [], ''


def _layout(columns, attrs, cats):
    rows = []
    for column in columns:
        if 'trac_cat' in column:
            cell = 'links of %s (%s)' % (_cat_name(cats, column['trac_cat']), column.get('trac_link', ''))
            rows.append({'header': column['header'], 'cell': cell, 'trac': True, 'order_by': ''})
        else:
            labels = [attrs[name]['label'] if name in attrs else name for name in column.get('attrs', [])]
            order_by = column.get('order_by')
            rows.append({'header': column['header'], 'cell': ' / '.join(labels), 'trac': False,
                         'order_by': attrs[order_by]['label'] if order_by in attrs else (order_by or '')})
    return rows


def _category(cat, definition, cats, counts, hidden):
    """`definition` as the item pages use it (no hidden attributes); `hidden`: (id, label) of the hidden ones."""
    attrs = definition['attrs']
    fields = []
    for attr_id, attr in attrs.items():
        control, choices, relation = _control(attr_id, attr, definition, cats)
        fields.append({'id': attr_id, 'label': attr['label'], 'kind': attr['kind'], 'required': attr['req_in_form'],
                       'control': control, 'choices': choices, 'relation': relation})
    expand = definition['expand']
    expansions = [{'link': link, 'target': _cat_name(cats, expand[link]), 'label': expand.get(link[0] + '_label', '')}
                  for link in ('p_link', 's_link') if expand.get(link) not in (None, 'None')]
    short_desc = [{'title': title, 'labels': [attrs[n]['label'] if n in attrs else n
                                                for n in definition['short_desc'].get(key, [])]}
                  for key, title in SHORT_DESC_LABELS.items()]
    return {
        'id': cat, 'name': definition['name'], 'abbr': definition['abbr'], 'level': definition['level'],
        'page_size': definition['page_size'], 'index_level': definition['access_from_index']['level'],
        'item_count': counts.get(cat, 0), 'fields': fields,
        'layouts': [{'title': title, 'rows': _layout(definition[key], attrs, cats)}
                    for key, title in (('disp_def', 'Default list'), ('disp_short', 'Short list'),
                                       ('disp_trac', 'Traceability list'))],
        'short_desc': short_desc, 'expansions': expansions,
        'tracs': [{'cat': _cat_name(cats, t['trac_cat']), 'link': t['trac_link']} for t in definition['tracs']],
        'validators': [spec['name'] for spec in definition['validators']],
        'hidden_fields': [{'id': attr_id, 'label': label} for attr_id, label in hidden],
    }


def build_preview(config, project):
    """Template context for the preview of the (valid) configuration `config` of `project`."""
    cats = config['cats']
    counts = {row['cat']: row['n'] for row in
              SpecItem.objects.filter(project_id=project.id).values('cat').annotate(n=Count('id')).order_by()}
    shown = shown_config(config)['cats']
    categories = [_category(cat, shown[cat], shown, counts,
                            [(name, definition['attrs'][name]['label']) for name in hidden_attributes(definition)])
                  for cat, definition in cats.items()]
    hidden = [{'id': cat, 'count': count} for cat, count in sorted(counts.items()) if cat not in cats]
    return {
        'project': project,
        'categories': categories,
        'project_menu': [c for c in categories if c['index_level'] == 'Project'],
        'application_menu': [c for c in categories if c['index_level'] == 'Application'],
        'hidden': hidden,
    }
