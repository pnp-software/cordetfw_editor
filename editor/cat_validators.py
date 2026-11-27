"""Registry of the category validators a project configuration can select (`cats.<Cat>.validators`).

A configuration lists validators as {"name": NAME, "params": {...}}. NAME must be a key of VALIDATORS (functions
of this module) and the params must match its declaration. Nothing is imported, evaluated or executed on the basis
of a configuration value; an unknown name or a malformed entry is a validation error (`check_validator_specs`) and,
if it reaches a form anyway, an error message which rejects the item (`run_validators`).

Supported validators:

* link_conditional_reference: if the item's `link` ('p_link'/'s_link') points to an item of category
  `when_link_cat`, then `field` must contain exactly one internal reference to an item of category `ref_cat`
  whose `ref_link` is that linked item. `message` is the error text; ': The reference is invalid' is appended
  when the reference does not resolve to an item of `ref_cat` in the project.
"""
import re

from django.core.exceptions import ObjectDoesNotExist

from editor.convert import pattern_db
from editor.link_rules import LINK_FIELDS
from editor.models import SpecItem

MAX_MESSAGE_LENGTH = 300

# Parameter kinds: 'str' (non-empty text), 'link' (one of LINK_FIELDS), 'cat' (a category of the configuration),
# 'attr' (an attribute of the category which declares the validator).
PARAM_KINDS = ('str', 'link', 'cat', 'attr')


def _link_conditional_reference(form, cleaned_data, params):
    link_item = cleaned_data.get(params['link'])
    if (link_item is None) or (link_item.cat != params['when_link_cat']):
        return ''
    message = params['message']
    text = (cleaned_data.get(params['field']) or '').strip()
    m = re.match(pattern_db, text)
    if (m is None) or (m.span()[1] != len(text)):
        return message
    ref = text.split(':')
    try:
        target = SpecItem.objects.get(id=ref[1], cat=params['ref_cat'], project_id=form.project.id)
    except ObjectDoesNotExist:
        return message + ': The reference is invalid'
    back_link = getattr(target, params['ref_link'])
    if (back_link is None) or (back_link.id != link_item.id):
        return message
    return ''


# name -> (function(form, cleaned_data, params) -> error message or '', {parameter: kind}); all required
VALIDATORS = {
    'link_conditional_reference': (_link_conditional_reference, {
        'field': 'attr', 'link': 'link', 'when_link_cat': 'cat', 'ref_cat': 'cat', 'ref_link': 'link',
        'message': 'str'}),
}


def check_validator_specs(specs, path, config=None, cat=None):
    """
    Errors of a `validators` list as (json_path, message) tuples. With `config` (a full configuration) and
    `cat` (the declaring category) category and attribute references are checked too.
    """
    if not isinstance(specs, list):
        return [(path, 'must be a list')]
    errors = []
    for i, spec in enumerate(specs):
        errors += _check_spec(spec, '%s[%d]' % (path, i), config, cat)
    return errors


def _check_spec(spec, path, config, cat):
    if not isinstance(spec, dict):
        return [(path, 'must be an object')]
    errors = [('%s.%s' % (path, key), 'unknown setting') for key in spec if key not in ('name', 'params')]
    name = spec.get('name')
    if not isinstance(name, str) or name not in VALIDATORS:
        return errors + [(path + '.name', 'unknown validator %s; supported: %s' % (
            repr(name)[:60], ', '.join(sorted(VALIDATORS))))]
    params = spec.get('params')
    if not isinstance(params, dict):
        return errors + [(path + '.params', 'must be an object')]
    declared = VALIDATORS[name][1]
    errors += [('%s.params.%s' % (path, key), 'unknown parameter') for key in params if key not in declared]
    for key, kind in declared.items():
        value = params.get(key)
        param_path = path + '.params.' + key
        if key not in params:
            errors.append((param_path, 'is required'))
        elif not isinstance(value, str) or not value:
            errors.append((param_path, 'must be a non-empty string'))
        elif kind == 'link' and value not in LINK_FIELDS:
            errors.append((param_path, 'must be one of ' + ', '.join(LINK_FIELDS)))
        elif kind == 'str' and len(value) > MAX_MESSAGE_LENGTH:
            errors.append((param_path, 'must have at most %d characters' % MAX_MESSAGE_LENGTH))
        elif config is not None and kind == 'cat' and value not in config.get('cats', {}):
            errors.append((param_path, 'unknown category "%s"' % value))
        elif config is not None and kind == 'attr' and value not in config.get('cats', {}).get(cat, {}).get('attrs', {}):
            errors.append((param_path, 'unknown attribute "%s" of category "%s"' % (value, cat)))
    return errors


def spec_is_dangling(spec, keeps_cat, keeps_attr):
    """True if a well-formed spec refers to a category or an attribute for which keeps_cat/keeps_attr is False."""
    declared = VALIDATORS[spec['name']][1]
    return any((kind == 'cat' and not keeps_cat(spec['params'][key])) or
               (kind == 'attr' and not keeps_attr(spec['params'][key]))
               for key, kind in declared.items())


def prune_validators(specs, keeps_cat, keeps_attr):
    """
    Copy of a `validators` list without the entries which refer to categories/attributes that no longer exist.
    Malformed entries are kept: reporting them is the job of check_validator_specs.
    """
    if not isinstance(specs, list):
        return specs
    return [spec for spec in specs
            if _check_spec(spec, '', None, None) or not spec_is_dangling(spec, keeps_cat, keeps_attr)]


def run_validators(form, cleaned_data, specs, path):
    """
    Run the validators of one category; return the first error message, or '' if all pass. A spec which does
    not satisfy the schema is a configuration error message (the item is rejected, never checked loosely).
    """
    errors = check_validator_specs(specs, path)
    if errors:
        return 'Configuration error at %s: %s' % errors[0]
    for spec in specs:
        message = VALIDATORS[spec['name']][0](form, cleaned_data, spec['params'])
        if message:
            return message
    return ''
