"""Helpers for the per-project configuration stored in Project.config.

`resolve_config` gives the stored configuration (configuration editor, project export); `get_project_config` and
`get_request_config` give it as the item pages use it, without hidden attributes. Nothing here is cached beyond the
lifetime of a request object.
"""
import copy
import json

from django.conf import settings

from editor.cat_validators import prune_validators
from editor.config_cleanup import has_hidden_attributes, remove_dangling_references, remove_hidden_attributes
from editor.link_rules import prune_link_rules
from editor.models import Application, Project, SpecItem

# Relationship settings of every category definition (link_rules.py, cat_validators.py); older stored ones lack them.
RELATIONSHIP_KEYS = ('links', 'validators')
# Server settings which must never be part of a project configuration.
SERVER_ONLY_GENERAL_KEYS = ('temp_dir',)

# SpecItem columns to which an attribute definition of a category can refer. A definition has stored data
# if at least one item of the category holds a value other than EMPTY_VALUES in that column.
DATA_COLUMNS = ('domain', 'name', 'title', 'desc', 'value', 'rationale', 'remarks', 'implementation',
                'p_link', 's_link', 'p_kind', 's_kind', 't1', 't2', 't3', 't4', 't5', 'n1', 'n2', 'n3',
                'val_set', 'owner', 'change_log')
EMPTY_VALUES = (None, '', 0)


def load_template():
    """Read the shared template from disk (a new copy at every call; nothing is cached)."""
    with open(settings.BASE_DIR + '/editor/static/json/configs.json') as template_file:
        return json.load(template_file)


def add_missing_relationship_settings(config):
    """
    In place, give a category definition without `links` or `validators` (stored by an earlier version) the
    template's value, restricted to the configuration's categories. Present keys, even empty, are never changed.
    Returns True if anything was added; the template is read only when needed.
    """
    cats = config.get('cats') if isinstance(config, dict) else None
    if not isinstance(cats, dict):
        return False
    lacking = [cat for cat, definition in cats.items()
               if isinstance(definition, dict) and any(key not in definition for key in RELATIONSHIP_KEYS)]
    if not lacking:
        return False
    template_cats = load_template()['cats']
    added = False
    for cat in lacking:
        definition, template_definition = cats[cat], template_cats.get(cat)
        if template_definition is None:
            continue
        if 'links' not in definition:
            definition['links'] = prune_link_rules(template_definition['links'], cats)
            added = True
        if 'validators' not in definition:
            definition['validators'] = prune_validators(template_definition['validators'], cats,
                                                        definition.get('attrs', {}))
            added = True
    return added


def resolve_config(stored):
    """
    New, independent configuration from a stored Project.config value (the template if empty), completed in memory
    by add_missing_relationship_settings and without SERVER_ONLY_GENERAL_KEYS.
    """
    config = copy.deepcopy(stored) if stored else load_template()
    if stored:
        add_missing_relationship_settings(config)
    general = config.get('general')
    if isinstance(general, dict):
        for key in SERVER_ONLY_GENERAL_KEYS:
            general.pop(key, None)
    return config


def shown_config(config):
    """
    `config` as forms, lists, references, item imports/exports and Find & Replace use it: a copy without hidden
    attributes and the references to them if any is hidden (their stored values are kept), else `config` itself.
    """
    return remove_hidden_attributes(config) if has_hidden_attributes(config) else config


def get_project_config(project):
    """Configuration held by the `project` instance as the item pages use it (shown_config); always a new copy."""
    return shown_config(resolve_config(project.config))


def get_request_config(request, project):
    """
    Like get_project_config, but read once per project and request (a fresh single-column query, so a stale instance
    is not used) and kept on the request object only. Callers must treat it as read-only.
    """
    configs_by_project = request.__dict__.setdefault('_project_configs', {})
    if project.id not in configs_by_project:
        stored = Project.objects.filter(id=project.id).values_list('config', flat=True).first()
        configs_by_project[project.id] = shown_config(resolve_config(stored))
    return configs_by_project[project.id]


def split_cats(cats):
    """Names in a comma-separated category list as stored in Project.cats and Application.cats."""
    return [name.strip() for name in (cats or '').split(',') if name.strip()]


def get_listed_cats(project):
    """Categories named by the project and by its applications."""
    names = split_cats(project.cats)
    for application_cats in Application.objects.filter(project_id=project.id).values_list('cats', flat=True):
        names += split_cats(application_cats)
    return set(names)


def get_data_usage(project):
    """{category: set of attribute names with stored data} over all items of the project (any status or ValSet)."""
    usage = {}
    items = SpecItem.objects.filter(project_id=project.id).values('cat', *DATA_COLUMNS).iterator()
    for item in items:
        fields = usage.setdefault(item['cat'], set())
        for column in DATA_COLUMNS:
            if item[column] not in EMPTY_VALUES:
                fields.add(column)
    return usage


def get_unknown_cats(template, project):
    """Categories which the project, its applications or its items use but the template does not define."""
    used = get_listed_cats(project) | set(get_data_usage(project))
    return sorted(used - set(template['cats']))


def filter_template_for_data(template, project):
    """
    New configuration for the project derived from the template (not modified). Categories listed in Project.cats or
    the applications' cats keep all definitions, categories with items only the field definitions with stored data;
    the others, and references to removed categories and fields, are removed. Server settings are not copied.
    """
    listed = get_listed_cats(project)
    usage = get_data_usage(project)
    config = {'general': {key: copy.deepcopy(value) for key, value in template['general'].items()
                          if key not in SERVER_ONLY_GENERAL_KEYS},
              'cats': {}}
    for cat, definition in template['cats'].items():
        if cat in listed:
            config['cats'][cat] = copy.deepcopy(definition)
        elif cat in usage:
            config['cats'][cat] = copy.deepcopy(definition)
            config['cats'][cat]['attrs'] = {name: attr for name, attr in copy.deepcopy(definition['attrs']).items()
                                            if name in usage[cat]}
    return remove_dangling_references(config)
