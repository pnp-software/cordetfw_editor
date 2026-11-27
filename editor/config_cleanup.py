"""Reference cleanup for a project configuration after a category or an attribute definition is removed.

Removing a definition never touches its stored data (the values stay with the items and in the project export),
but the configuration must not keep references to it in `expand`, `tracs`, `links`, `validators`, `short_desc`,
`ext_attrs` or the `disp_*` layouts. Every function returns a new configuration and leaves its argument untouched;
nothing here uses the database. Malformed parts are left as they are (validate_config reports them), so the
functions can be applied to unvalidated input.

An attribute definition with `"hidden": true` stays in the stored configuration with the references to it; the
item pages use the configuration without it (`remove_hidden_attributes`), so for them it is exactly a removed one.
"""
import copy

from editor.cat_validators import prune_validators
from editor.link_rules import prune_link_rules

LAYOUTS = ('disp_def', 'disp_short', 'disp_trac')


class _Without:
    """Membership test which is true for everything except the given names."""

    def __init__(self, names=()):
        self.names = set(names)

    def __contains__(self, name):
        return name not in self.names


def _is_name(value):
    return isinstance(value, str)


def _clean_definition(definition, cats, attrs):
    """In place: drop references to categories not `in cats` and attributes not `in attrs` (membership tests)."""
    if not isinstance(definition, dict):
        return
    if isinstance(definition.get('ext_attrs'), list):
        definition['ext_attrs'] = [name for name in definition['ext_attrs'] if not _is_name(name) or name in attrs]
    expand = definition.get('expand')
    if isinstance(expand, dict):
        for link in ('s_link', 'p_link'):
            if _is_name(expand.get(link)) and expand[link] != 'None' and expand[link] not in cats:
                expand[link] = 'None'
    if isinstance(definition.get('tracs'), list):
        definition['tracs'] = [trac for trac in definition['tracs']
                               if not (isinstance(trac, dict) and _is_name(trac.get('trac_cat'))
                                       and trac['trac_cat'] not in cats)]
    if 'links' in definition:
        definition['links'] = prune_link_rules(definition['links'], cats)
    if 'validators' in definition:
        definition['validators'] = prune_validators(definition['validators'], cats, attrs)
    short_desc = definition.get('short_desc')
    if isinstance(short_desc, dict):
        for key, names in short_desc.items():
            if isinstance(names, list):
                short_desc[key] = [name for name in names if not _is_name(name) or name in attrs]
    for layout in LAYOUTS:
        if isinstance(definition.get(layout), list):
            definition[layout] = _clean_layout(definition[layout], cats, attrs)


def _clean_layout(columns, cats, attrs):
    kept = []
    for column in columns:
        if isinstance(column, dict):
            if isinstance(column.get('attrs'), list):
                column['attrs'] = [name for name in column['attrs'] if not _is_name(name) or name in attrs]
                if not column['attrs']:
                    continue                  # a column without attributes shows nothing
                if _is_name(column.get('order_by')) and column['order_by'] not in attrs:
                    del column['order_by']
            elif 'attrs' not in column and _is_name(column.get('trac_cat')) and column['trac_cat'] not in cats:
                continue
        kept.append(column)
    return kept


def _cats_of(config):
    cats = config.get('cats') if isinstance(config, dict) else None
    return cats if isinstance(cats, dict) else None


def remove_dangling_references(config):
    """Copy of `config` without references to categories or attributes which the configuration does not define."""
    config = copy.deepcopy(config)
    cats = _cats_of(config)
    if cats is not None:
        for definition in cats.values():
            attrs = definition.get('attrs') if isinstance(definition, dict) else None
            _clean_definition(definition, cats, attrs if isinstance(attrs, dict) else _Without())
    return config


def remove_category(config, cat):
    """Copy of `config` without category `cat` and without the references to it in the other categories."""
    config = copy.deepcopy(config)
    cats = _cats_of(config)
    if cats is not None:
        cats.pop(cat, None)
        for definition in cats.values():
            _clean_definition(definition, _Without([cat]), _Without())
    return config


def remove_attribute(config, cat, attr):
    """Copy of `config` without attribute `attr` of category `cat` and without the references to it in `cat`."""
    config = copy.deepcopy(config)
    cats = _cats_of(config)
    definition = cats.get(cat) if cats is not None else None
    if isinstance(definition, dict):
        if isinstance(definition.get('attrs'), dict):
            definition['attrs'].pop(attr, None)
        _clean_definition(definition, _Without(), _Without([attr]))
    return config


def hidden_attributes(definition):
    """Names of the attributes of a category definition which are marked `"hidden": true` (in definition order)."""
    attrs = definition.get('attrs') if isinstance(definition, dict) else None
    if not isinstance(attrs, dict):
        return []
    return [name for name, attr in attrs.items() if isinstance(attr, dict) and attr.get('hidden') is True]


def has_hidden_attributes(config):
    """True if an attribute definition of any category of `config` is marked hidden."""
    cats = _cats_of(config)
    return cats is not None and any(hidden_attributes(definition) for definition in cats.values())


def remove_hidden_attributes(config):
    """Copy of `config` without the hidden attribute definitions and the references to them (as remove_attribute)."""
    config = copy.deepcopy(config)
    cats = _cats_of(config)
    if cats is not None:
        for definition in cats.values():
            hidden = hidden_attributes(definition)
            if hidden:
                for name in hidden:
                    definition['attrs'].pop(name)
                _clean_definition(definition, _Without(), _Without(hidden))
    return config


def shown_columns(columns, hidden):
    """Copy of a `disp_*` layout as the list shows it when the attributes `hidden` are hidden."""
    return _clean_layout(copy.deepcopy(columns), _Without(), _Without(hidden))
