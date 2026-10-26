"""Parsing and validation of optional keys of /etc/dj_cordetfw_config.json (kept import-light
so that it can be unit-tested without importing the settings module)."""

from django.core.exceptions import ImproperlyConfigured

AXES_LOCKOUT_PARAMETER_NAMES = ('ip_address', 'username', 'user_agent')


def parse_axes_lockout_parameters(config):
    """Return the validated AXES_LOCKOUT_PARAMETERS value from the config dict, or None when the
    optional key is absent (the caller then leaves the setting alone: axes default, IP only).

    Shape: non-empty list whose items are either a parameter name (lock when ANY such item
    reaches the failure limit) or a non-empty list of names (lock on that COMBINATION)."""
    if 'AXES_LOCKOUT_PARAMETERS' not in config:
        return None
    value = config['AXES_LOCKOUT_PARAMETERS']
    allowed = ', '.join(AXES_LOCKOUT_PARAMETER_NAMES)
    problem = ('AXES_LOCKOUT_PARAMETERS in the config file must be a non-empty list of strings or of '
               'non-empty lists of strings, each one of: %s (e.g. ["ip_address", "username"]); got %r'
               % (allowed, value))
    if not isinstance(value, list) or not value:
        raise ImproperlyConfigured(problem)
    for item in value:
        names = item if isinstance(item, list) else [item]
        if not names or any(not isinstance(n, str) or n not in AXES_LOCKOUT_PARAMETER_NAMES for n in names):
            raise ImproperlyConfigured(problem)
    return value
