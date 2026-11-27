"""Validation of a project configuration (the JSON stored in Project.config).

`validate_config(config, project)` is the single validator, also behind `validate_config_json` (raw JSON text)
and `validate_config_file` (an upload). It never raises for a malformed configuration, never modifies its argument
and only reads the database (when `project` is given).

Error contract: a list of `ConfigError(path, message)`; empty means valid. `path` is the JSON path of the
offending setting, e.g. `cats.Packet.attrs.t1.label`, `cats.Packet.disp_def[2].attrs[0]`, `general.max_depth`;
the root is ''. A key which is not a plain identifier is written as `["a.b"]`. Messages are plain text built
partly from submitted values: whoever displays them must escape them. The order is deterministic (categories
and attributes are visited in sorted order, so the result does not depend on the key order of the JSON, which
MySQL does not preserve) and the list is cut at `MAX_ERRORS` entries (the last one says how many were left out).

Rules:

* structure: top-level keys `general` and `cats`, every setting of a category present, no unknown setting;
* types and limits: integers are not booleans, texts are printable without surrounding blanks and have a
  maximum length, category identifiers fit `SpecItem.cat` (24 characters), choice values fit
  `SpecItem.p_kind`/`s_kind` (24), `page_size` 1..1000, `short_desc_len` 10..1000, `max_depth` 1..500;
* names: category identifiers are `[A-Za-z][A-Za-z0-9_]*`, not `None`, unique ignoring case; display names and
  abbreviations are unique ignoring case; attribute labels are unique within a category ignoring blanks and case;
* attributes: only fields of `SpecItem` (`ALLOWED_KINDS`), each with its supported kind(s); `domain` and `name`
  are mandatory, required in forms and cannot be hidden (they identify an item in imports, exports and
  references); the optional `hidden` is true or false; the default list (`disp_def`) keeps at least one column
  with an attribute which is not hidden;
* references: `ext_attrs`, `short_desc`, `disp_*` columns and `order_by` name attributes of the same category;
  `expand`, `tracs`, `links`, validators and `disp_trac` columns name categories of the configuration;
  `ext_attrs` requires the external (FW Profile) support code for the category;
* `access_from_index.level` is `Project`, `Application` or `None` and fits `level` (a category of level
  `application` is not offered from the project index and the other way round);
* choice lists: `p_kind_choices`/`s_kind_choices` map values to labels; they must not be empty when the
  attribute is shown (not hidden) and required;
* `general`: `csv_sep`, `eol_sep`, `short_desc_len`, `max_depth`; server settings (`temp_dir`) are rejected.

Compatibility with the stored data (only when a project is given): for every category kept in the
configuration the stored `p_kind`/`s_kind` values must be choices (also when the attribute is hidden, because
the edit form validates the hidden value) and the stored `p_link`/`s_link` pairs (item category, target
category) must be allowed by the category's link rule, provided that the target category is kept too. Removing
a category or an attribute (or hiding an attribute) is always allowed: the stored data is not touched, so nothing
here requires data to change.
"""
import json
import re
from collections import Counter
from dataclasses import dataclass

from editor.cat_validators import check_validator_specs
from editor.config_cleanup import hidden_attributes, shown_columns
from editor.link_rules import LINK_FIELDS, check_link_rule, check_link_rules, check_trac_settings, rule_allows
from editor.models import SpecItem
from editor.project_config import DATA_COLUMNS, SERVER_ONLY_GENERAL_KEYS

MAX_ERRORS = 100
MAX_JSON_BYTES = 1024 * 1024
MAX_TEXT = 100                      # labels, headers, display names
MAX_CAT_LENGTH = 24                 # SpecItem.cat, p_kind and s_kind are CharField(max_length=24)
PAGE_SIZE_RANGE = (1, 1000)
SHORT_DESC_LEN_RANGE = (10, 1000)
MAX_DEPTH_RANGE = (1, 500)          # recursion depth of release deletion; Python's own limit is about 1000

TOP_KEYS = ('general', 'cats')
GENERAL_KEYS = ('csv_sep', 'eol_sep', 'short_desc_len', 'max_depth')
CAT_KEYS = ('name', 'level', 'abbr', 'page_size', 'ext_attrs', 'expand', 'short_desc', 'tracs', 'links',
            'validators', 'access_from_index', 'attrs', 'p_kind_choices', 's_kind_choices', 'disp_def',
            'disp_short', 'disp_trac')
ATTR_KEYS = ('label', 'req_in_form', 'kind')       # required
OPTIONAL_ATTR_KEYS = ('hidden',)
EXPAND_KEYS = ('s_link', 'p_link', 's_label', 'p_label')
SHORT_DESC_KEYS = ('expand_text', 'href_tip', 'expand_tip')
COLUMN_KEYS = ('header', 'attrs', 'order_by', 'trac_cat', 'trac_link')
LAYOUTS = ('disp_def', 'disp_short', 'disp_trac')
LEVELS = ('project', 'application')
ACCESS_LEVELS = ('Project', 'Application', 'None')
ACCESS_BY_LEVEL = {'project': ('Project', 'None'), 'application': ('Application', 'None')}
EOL_SEPARATORS = ('\n', '\r\n')
CSV_SEP_FORBIDDEN = '"\r\n \x00'

_TEXT_KINDS = ('plain_text', 'ref_text')
# Kinds an attribute can have, per SpecItem field. `date` and `table` have display functions but no support in
# the forms, imports and exports, so they are not offered.
ALLOWED_KINDS = {
    **{name: _TEXT_KINDS for name in ('title', 'desc', 'rationale', 'remarks', 'implementation', 't1', 't2', 't3',
                                      't4', 't5', 'change_log')},
    'value': _TEXT_KINDS + ('eval_ref', 'image'),
    'domain': ('plain_text',), 'name': ('plain_text',), 'p_kind': ('plain_text',), 's_kind': ('plain_text',),
    'p_link': ('spec_item_ref',), 's_link': ('spec_item_ref',),
    'val_set': ('plain_ref',), 'owner': ('plain_ref',),
    'n1': ('int',), 'n2': ('int',), 'n3': ('int',),
}
REQUIRED_ATTRS = ('domain', 'name')

_CAT_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,%d}\Z' % (MAX_CAT_LENGTH - 1))
_ABBR = re.compile(r'[A-Za-z0-9_-]{1,%d}\Z' % MAX_CAT_LENGTH)
_CHOICE_VALUE = re.compile(r'[^\s\x00-\x1f\x7f]{1,%d}\Z' % MAX_CAT_LENGTH)
_PLAIN_KEY = re.compile(r'[A-Za-z0-9_-]+\Z')


@dataclass(frozen=True)
class ConfigError:
    """One problem of a configuration: the JSON path of the setting and a plain-text message."""
    path: str
    message: str

    def as_dict(self):
        return {'path': self.path, 'message': self.message}

    def __str__(self):
        return '%s: %s' % (self.path or '(root)', self.message)


def key_path(base, key):
    """Path of member `key` of the object at `base` (`a.b`, or `a["b.c"]` for a key which is not a plain name)."""
    if isinstance(key, str) and _PLAIN_KEY.match(key):
        return base + '.' + key if base else key
    return '%s[%s]' % (base, json.dumps(key, default=repr, ensure_ascii=True)[:80])


def _show(value):
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + '...'


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _text_problem(value, maximum=MAX_TEXT):
    if not isinstance(value, str):
        return 'must be a text'
    if not value or value != value.strip():
        return 'must not be empty or start or end with a blank'
    if len(value) > maximum:
        return 'must have at most %d characters' % maximum
    if not value.isprintable():
        return 'must not contain control characters'
    return ''


def _check_text(value, path, errors, maximum=MAX_TEXT):
    problem = _text_problem(value, maximum)
    if problem:
        errors.append(ConfigError(path, problem))


def _check_range(value, path, errors, bounds):
    if not _is_int(value) or not bounds[0] <= value <= bounds[1]:
        errors.append(ConfigError(path, 'must be an integer from %d to %d' % bounds))


def _unknown_keys(obj, allowed, path, errors):
    for key in sorted(obj, key=str):
        if key not in allowed:
            errors.append(ConfigError(key_path(path, key), 'unknown setting'))


def _required_keys(obj, required, path, errors):
    for key in required:
        if key not in obj:
            errors.append(ConfigError(key_path(path, key), 'is required'))


def _tuples(problems, errors):
    errors.extend(ConfigError(path, message) for path, message in problems)


def validate_config(config, project=None):
    """List of ConfigError (see the module docstring); with `project` also checks the stored data."""
    errors = []
    if not isinstance(config, dict):
        return [ConfigError('', 'the configuration must be a JSON object')]
    _unknown_keys(config, TOP_KEYS, '', errors)
    _required_keys(config, TOP_KEYS, '', errors)
    if 'general' in config:
        _check_general(config['general'], errors)
    if 'cats' in config:
        if not isinstance(config['cats'], dict):
            errors.append(ConfigError('cats', 'must be an object'))
        else:
            _check_cats(config['cats'], errors)
            if project is not None:
                _check_stored_data(config['cats'], project, errors)
    if len(errors) > MAX_ERRORS:
        left = len(errors) - MAX_ERRORS
        errors = errors[:MAX_ERRORS] + [ConfigError('', '%d more error(s) not shown' % left)]
    return errors


def _check_general(general, errors):
    if not isinstance(general, dict):
        errors.append(ConfigError('general', 'must be an object'))
        return
    for key in sorted(general, key=str):
        if key in SERVER_ONLY_GENERAL_KEYS:
            errors.append(ConfigError(key_path('general', key),
                                      'is a server setting and cannot be part of a project configuration'))
        elif key not in GENERAL_KEYS:
            errors.append(ConfigError(key_path('general', key), 'unknown setting'))
    _required_keys(general, GENERAL_KEYS, 'general', errors)
    csv_sep = general.get('csv_sep')
    if 'csv_sep' in general and (not isinstance(csv_sep, str) or len(csv_sep) != 1 or csv_sep.isalnum()
                                 or csv_sep in CSV_SEP_FORBIDDEN or not (csv_sep.isprintable() or csv_sep == '\t')):
        errors.append(ConfigError('general.csv_sep', 'must be one character which is not a letter, digit, '
                                                     'blank, quote or line break'))
    if 'eol_sep' in general and general['eol_sep'] not in EOL_SEPARATORS:
        errors.append(ConfigError('general.eol_sep', 'must be "\\n" or "\\r\\n"'))
    if 'short_desc_len' in general:
        _check_range(general['short_desc_len'], 'general.short_desc_len', errors, SHORT_DESC_LEN_RANGE)
    if 'max_depth' in general:
        _check_range(general['max_depth'], 'general.max_depth', errors, MAX_DEPTH_RANGE)


def _check_cats(cats, errors):
    names = sorted(cats, key=str)
    first_by_lower = {}
    for key in names:
        path = key_path('cats', key)
        if not isinstance(key, str) or not _CAT_NAME.match(key):
            errors.append(ConfigError(path, 'the category identifier must be 1-%d letters, digits or underscores '
                                            'and start with a letter' % MAX_CAT_LENGTH))
        elif key.lower() == 'none':
            errors.append(ConfigError(path, '"None" is reserved'))
        elif key.lower() in first_by_lower:
            errors.append(ConfigError(path, 'the identifier differs only in case from "%s"' % first_by_lower[key.lower()]))
        else:
            first_by_lower[key.lower()] = key
    # Attribute names of each category for the reference checks of the validators (a malformed `attrs` is empty)
    view = {'cats': {key: {'attrs': definition['attrs'] if isinstance(definition, dict)
                           and isinstance(definition.get('attrs'), dict) else {}}
                     for key, definition in cats.items()}}
    for key in names:
        _check_cat(key, cats[key], cats, view, errors)
    for setting, label in (('name', 'display name'), ('abbr', 'abbreviation')):
        first = {}
        for key in names:
            value = cats[key].get(setting) if isinstance(cats[key], dict) else None
            if not isinstance(value, str):
                continue
            if value.lower() in first:
                errors.append(ConfigError(key_path(key_path('cats', key), setting),
                                          'the %s "%s" is already used by category "%s"' % (
                                              label, value, first[value.lower()])))
            else:
                first[value.lower()] = key


def _check_cat(cat, definition, cats, view, errors):
    path = key_path('cats', cat)
    if not isinstance(definition, dict):
        errors.append(ConfigError(path, 'must be an object'))
        return
    _unknown_keys(definition, CAT_KEYS, path, errors)
    _required_keys(definition, CAT_KEYS, path, errors)

    def at(key):
        return key_path(path, key)

    if 'name' in definition:
        _check_text(definition['name'], at('name'), errors)
    if 'level' in definition and definition['level'] not in LEVELS:
        errors.append(ConfigError(at('level'), 'must be one of: ' + ', '.join(LEVELS)))
    if 'abbr' in definition and (not isinstance(definition['abbr'], str) or not _ABBR.match(definition['abbr'])):
        errors.append(ConfigError(at('abbr'), 'must be 1-%d letters, digits, underscores or dashes' % MAX_CAT_LENGTH))
    if 'page_size' in definition:
        _check_range(definition['page_size'], at('page_size'), errors, PAGE_SIZE_RANGE)
    if 'access_from_index' in definition:
        _check_access(definition['access_from_index'], definition.get('level'), at('access_from_index'), errors)

    attrs = definition.get('attrs')
    attr_names = set(attrs) if isinstance(attrs, dict) else None     # None: malformed, skip reference checks
    if 'attrs' in definition:
        _check_attrs(attrs, at('attrs'), errors)
    if 'ext_attrs' in definition:
        _check_ext_attrs(cat, definition['ext_attrs'], attr_names, at('ext_attrs'), errors)
    if 'expand' in definition:
        _check_expand(definition['expand'], cats, at('expand'), errors)
    if 'short_desc' in definition:
        _check_short_desc(definition['short_desc'], attr_names, at('short_desc'), errors)
    if 'tracs' in definition:
        _tuples(check_trac_settings(definition['tracs'], at('tracs'), cats), errors)
    if 'links' in definition:
        _tuples(check_link_rules(definition['links'], at('links'), cats), errors)
    if 'validators' in definition:
        _tuples(check_validator_specs(definition['validators'], at('validators'), view, cat), errors)
    hidden = hidden_attributes(definition)
    for kind in ('p_kind', 's_kind'):
        if kind + '_choices' in definition:
            shown = isinstance(attrs, dict) and isinstance(attrs.get(kind), dict) \
                and attrs[kind].get('req_in_form') is True and kind not in hidden
            _check_choices(definition[kind + '_choices'], at(kind + '_choices'), shown, errors)
    for layout in LAYOUTS:
        if layout in definition:
            _check_layout(definition[layout], at(layout), layout, attr_names, cats, errors)
    default_layout = definition.get('disp_def')
    if hidden and isinstance(default_layout, list) and default_layout and not shown_columns(default_layout, hidden):
        errors.append(ConfigError(at('disp_def'), 'must have at least one column with an attribute which is not '
                                                  'hidden: it is the default display'))


def _check_access(access, level, path, errors):
    if not isinstance(access, dict):
        errors.append(ConfigError(path, 'must be an object'))
        return
    _unknown_keys(access, ('level',), path, errors)
    _required_keys(access, ('level',), path, errors)
    if 'level' not in access:
        return
    if access['level'] not in ACCESS_LEVELS:
        errors.append(ConfigError(path + '.level', 'must be one of: ' + ', '.join(ACCESS_LEVELS)))
    elif isinstance(level, str) and level in ACCESS_BY_LEVEL and access['level'] not in ACCESS_BY_LEVEL[level]:
        errors.append(ConfigError(path + '.level', 'a category of level "%s" can only be accessed from the index '
                                                   'with: %s' % (level, ', '.join(ACCESS_BY_LEVEL[level]))))


def _check_attrs(attrs, path, errors):
    if not isinstance(attrs, dict):
        errors.append(ConfigError(path, 'must be an object'))
        return
    for name in REQUIRED_ATTRS:
        if name not in attrs:
            errors.append(ConfigError(key_path(path, name), 'is required'))
    labels = {}
    for name in sorted(attrs, key=str):
        attr_path = key_path(path, name)
        attr = attrs[name]
        if name not in ALLOWED_KINDS:
            errors.append(ConfigError(attr_path, 'is not a field of the item model; allowed: '
                                                 + ', '.join(sorted(ALLOWED_KINDS))))
        if not isinstance(attr, dict):
            errors.append(ConfigError(attr_path, 'must be an object'))
            continue
        _unknown_keys(attr, ATTR_KEYS + OPTIONAL_ATTR_KEYS, attr_path, errors)
        _required_keys(attr, ATTR_KEYS, attr_path, errors)
        if 'label' in attr:
            problem = _text_problem(attr['label'])
            if problem:
                errors.append(ConfigError(attr_path + '.label', problem))
            else:
                normalized = attr['label'].replace(' ', '').lower()
                if normalized in labels:
                    errors.append(ConfigError(attr_path + '.label', 'the label is already used by attribute "%s" '
                                                                    '(labels are the column names of exports)' % labels[normalized]))
                else:
                    labels[normalized] = name
        if 'req_in_form' in attr:
            if not isinstance(attr['req_in_form'], bool):
                errors.append(ConfigError(attr_path + '.req_in_form', 'must be true or false'))
            elif name in REQUIRED_ATTRS and not attr['req_in_form']:
                errors.append(ConfigError(attr_path + '.req_in_form', 'must be true: the item is identified by it'))
        if 'hidden' in attr:
            if not isinstance(attr['hidden'], bool):
                errors.append(ConfigError(attr_path + '.hidden', 'must be true or false'))
            elif name in REQUIRED_ATTRS and attr['hidden']:
                errors.append(ConfigError(attr_path + '.hidden', 'must be false: the item is identified by it'))
        if 'kind' in attr:
            kind = attr['kind']
            kinds = ALLOWED_KINDS.get(name)
            if not isinstance(kind, str) or (kinds is not None and kind not in kinds):
                allowed = kinds if kinds is not None else sorted({k for ks in ALLOWED_KINDS.values() for k in ks})
                errors.append(ConfigError(attr_path + '.kind', 'must be %s: %s' % (
                    'one of' if len(allowed) > 1 else 'exactly', ', '.join(allowed))))


def _check_name_list(names, path, attr_names, errors):
    if not isinstance(names, list):
        errors.append(ConfigError(path, 'must be a list'))
        return
    for i, name in enumerate(names):
        item_path = '%s[%d]' % (path, i)
        if not isinstance(name, str):
            errors.append(ConfigError(item_path, 'must be an attribute name'))
        elif attr_names is not None and name not in attr_names:
            errors.append(ConfigError(item_path, 'unknown attribute "%s"' % name))


def _check_ext_attrs(cat, names, attr_names, path, errors):
    _check_name_list(names, path, attr_names, errors)
    if isinstance(names, list) and names and not _has_external_support(cat):
        errors.append(ConfigError(path, 'attributes can only be taken from the external repository for categories '
                                        'which the editor supports (%s)' % ', '.join(_external_cats())))
    if isinstance(names, list) and len(set(map(repr, names))) != len(names):
        errors.append(ConfigError(path, 'must not list an attribute twice'))


def _external_cats():
    from editor import ext_cats
    return sorted(name[4:-len('_get_choices')] for name in dir(ext_cats)
                  if name.startswith('ext_') and name.endswith('_get_choices'))


def _has_external_support(cat):
    """True if editor.ext_cats has the code which loads items of category `cat` from the external repository."""
    from editor import ext_cats
    return isinstance(cat, str) and all(callable(getattr(ext_cats, 'ext_%s_%s' % (cat.lower(), suffix), None))
                                        for suffix in ('get_choices', 'get_choice'))


def _check_expand(expand, cats, path, errors):
    if not isinstance(expand, dict):
        errors.append(ConfigError(path, 'must be an object'))
        return
    _unknown_keys(expand, EXPAND_KEYS, path, errors)
    _required_keys(expand, ('s_link', 'p_link'), path, errors)
    for link in LINK_FIELDS:
        if link not in expand:
            continue
        target = expand[link]
        if not isinstance(target, str) or (target != 'None' and target not in cats):
            errors.append(ConfigError(key_path(path, link), 'must be "None" or the identifier of a category'))
        elif target != 'None' and link[0] + '_label' not in expand:
            errors.append(ConfigError(key_path(path, link[0] + '_label'), 'is required when the link is expanded'))
        label = link[0] + '_label'
        if label in expand:
            _check_text(expand[label], key_path(path, label), errors)


def _check_short_desc(short_desc, attr_names, path, errors):
    if not isinstance(short_desc, dict):
        errors.append(ConfigError(path, 'must be an object'))
        return
    _unknown_keys(short_desc, SHORT_DESC_KEYS, path, errors)
    _required_keys(short_desc, SHORT_DESC_KEYS, path, errors)
    for key in SHORT_DESC_KEYS:
        if key in short_desc:
            _check_name_list(short_desc[key], key_path(path, key), attr_names, errors)


def _check_choices(choices, path, shown_and_required, errors):
    if not isinstance(choices, dict):
        errors.append(ConfigError(path, 'must be an object'))
        return
    if shown_and_required and not choices:
        errors.append(ConfigError(path, 'must have at least one choice: the attribute is required in the form'))
    for value in sorted(choices, key=str):
        value_path = key_path(path, value)
        if not isinstance(value, str) or not _CHOICE_VALUE.match(value):
            errors.append(ConfigError(value_path, 'the stored value must be 1-%d characters without blanks or '
                                                  'control characters' % MAX_CAT_LENGTH))
        _check_text(choices[value], value_path, errors)


def _check_layout(columns, path, layout, attr_names, cats, errors):
    if not isinstance(columns, list):
        errors.append(ConfigError(path, 'must be a list'))
        return
    if layout == 'disp_def' and not columns:
        errors.append(ConfigError(path, 'must have at least one column: it is the default display'))
    for i, column in enumerate(columns):
        column_path = '%s[%d]' % (path, i)
        if not isinstance(column, dict):
            errors.append(ConfigError(column_path, 'must be an object'))
            continue
        _unknown_keys(column, COLUMN_KEYS, column_path, errors)
        if 'header' not in column:
            errors.append(ConfigError(column_path + '.header', 'is required'))
        else:
            _check_text(column['header'], column_path + '.header', errors)
        if ('attrs' in column) == ('trac_cat' in column):
            errors.append(ConfigError(column_path, 'exactly one of "attrs" and "trac_cat" is required'))
        if 'attrs' in column:
            if isinstance(column['attrs'], list) and not column['attrs']:
                errors.append(ConfigError(column_path + '.attrs', 'must not be empty'))
            _check_name_list(column['attrs'], column_path + '.attrs', attr_names, errors)
            if 'trac_link' in column:
                errors.append(ConfigError(column_path + '.trac_link', 'only a traceability column has this setting'))
            if 'order_by' in column and (not isinstance(column['order_by'], str)
                                         or (attr_names is not None and column['order_by'] not in attr_names)):
                errors.append(ConfigError(column_path + '.order_by', 'must be an attribute of the category'))
        if 'trac_cat' in column:
            if layout != 'disp_trac':
                errors.append(ConfigError(column_path + '.trac_cat', 'traceability columns are only used in disp_trac'))
            if not isinstance(column['trac_cat'], str) or column['trac_cat'] not in cats:
                errors.append(ConfigError(column_path + '.trac_cat', 'must be the identifier of a category'))
            if column.get('trac_link') not in LINK_FIELDS:
                errors.append(ConfigError(column_path + '.trac_link', 'must be one of: ' + ', '.join(LINK_FIELDS)))
            if 'order_by' in column:
                errors.append(ConfigError(column_path + '.order_by', 'a traceability column cannot be sorted'))


def _check_stored_data(cats, project, errors):
    """Stored kind values and link pairs of the categories kept in the configuration remain valid."""
    kinds = Counter()
    links = Counter()
    rows = SpecItem.objects.filter(project_id=project.id).values_list(
        'cat', 'p_kind', 's_kind', 'p_link__cat', 's_link__cat').iterator()
    for cat, p_kind, s_kind, p_target, s_target in rows:
        if cat not in cats or not isinstance(cats[cat], dict):
            continue
        kinds[(cat, 'p_kind', p_kind)] += 1
        kinds[(cat, 's_kind', s_kind)] += 1
        if p_target is not None:
            links[(cat, 'p_link', p_target)] += 1
        if s_target is not None:
            links[(cat, 's_link', s_target)] += 1
    for (cat, kind, value), count in sorted(kinds.items()):
        choices = cats[cat].get(kind + '_choices')
        if value != '' and isinstance(choices, dict) and value not in choices:
            errors.append(ConfigError(key_path(key_path('cats', cat), kind + '_choices'),
                                      'the stored %s value "%s" of %d item(s) is not a choice' % (kind, value, count)))
    for (cat, link, target), count in sorted(links.items()):
        if target not in cats:
            continue                                    # the target category is hidden: nothing to check
        links_setting = cats[cat].get('links')
        rule = links_setting.get(link) if isinstance(links_setting, dict) else None
        if rule is not None and check_link_rule(rule, link):
            continue                                    # malformed rule: already reported
        if rule is None or not rule_allows(rule, target):
            errors.append(ConfigError(key_path(key_path(key_path('cats', cat), 'links'), link),
                                      'stored %s of %d item(s) of category "%s" point to items of category "%s", '
                                      'which this %s' % (link, count, cat, target,
                                                         'rule does not allow' if rule is not None
                                                         else 'category has no rule for')))


class _DuplicateKeys(dict):
    """dict which remembers keys that occurred twice in the JSON object it was built from."""
    duplicates = ()


def _object_hook(pairs):
    obj = _DuplicateKeys()
    seen = set()
    duplicates = []
    for key, value in pairs:
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        obj[key] = value
    obj.duplicates = duplicates
    return obj


def _normalize(value, path, errors):
    """Replace the _DuplicateKeys objects by plain dicts and report the duplicate keys with their path."""
    if isinstance(value, _DuplicateKeys):
        errors.extend(ConfigError(key_path(path, key), 'the key occurs more than once in the object')
                      for key in value.duplicates)
        return {key: _normalize(item, key_path(path, key), errors) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, '%s[%d]' % (path, i), errors) for i, item in enumerate(value)]
    return value


def _reject_constant(name):
    raise ValueError('%s is not allowed' % name)


def validate_config_json(text, project=None):
    """
    Parse JSON text (str or UTF-8 bytes) and validate it. Returns (config, errors); config is None if unparsable.
    Size over MAX_JSON_BYTES, syntax errors, NaN/Infinity, deep nesting and duplicate keys are errors.
    """
    if isinstance(text, bytes):
        if len(text) > MAX_JSON_BYTES:
            return None, [ConfigError('', 'the configuration is larger than %d bytes' % MAX_JSON_BYTES)]
        try:
            text = text.decode('utf-8-sig')
        except UnicodeDecodeError:
            return None, [ConfigError('', 'the configuration must be UTF-8 text')]
    elif not isinstance(text, str):
        return None, [ConfigError('', 'the configuration must be JSON text')]
    elif len(text.encode('utf-8', 'surrogatepass')) > MAX_JSON_BYTES:
        return None, [ConfigError('', 'the configuration is larger than %d bytes' % MAX_JSON_BYTES)]
    try:
        parsed = json.loads(text, object_pairs_hook=_object_hook, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        return None, [ConfigError('', 'invalid JSON at line %d, column %d: %s' % (exc.lineno, exc.colno, exc.msg))]
    except (ValueError, RecursionError) as exc:
        return None, [ConfigError('', 'invalid JSON: %s' % ('nested too deeply' if isinstance(exc, RecursionError)
                                                            else exc))]
    errors = []
    try:
        config = _normalize(parsed, '', errors)
    except RecursionError:
        return None, [ConfigError('', 'invalid JSON: nested too deeply')]
    return config, errors + validate_config(config, project)


def validate_config_file(uploaded, project=None):
    """Like `validate_config_json` for an uploaded (binary) file; reads at most MAX_JSON_BYTES + 1 bytes."""
    try:
        data = uploaded.read(MAX_JSON_BYTES + 1)
    except (OSError, ValueError):
        return None, [ConfigError('', 'the file cannot be read')]
    if isinstance(data, str):
        data = data.encode('utf-8', 'surrogatepass')
    return validate_config_json(data, project)
