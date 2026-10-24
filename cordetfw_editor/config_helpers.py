"""Parsing and validation of optional keys of /etc/dj_cordetfw_config.json (kept import-light
so that it can be unit-tested without importing the settings module)."""

import hashlib

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


# Keys that must never be used with DEBUG off: the placeholder of the tracked dj_cordetfw_config.json
# (tryout / development only) and the key that was tracked there before (tracked-dev-secret-key).
INSECURE_KEY_PREFIX = 'insecure-dev-only-'
_RETIRED_KEY_SHA256 = '20aa62c61ddc42dd4cbe6bba621862707b8dacd4d66354627f2b9c202a7b3986'


def check_secret_key(secret_key, debug):
    """Refuse to start with a development placeholder (or the retired tracked) SECURE_KEY unless
    DEBUG is on. Returns the key."""
    insecure = (not isinstance(secret_key, str) or secret_key.startswith(INSECURE_KEY_PREFIX)
                or hashlib.sha256(secret_key.encode()).hexdigest() == _RETIRED_KEY_SHA256)
    if insecure and not debug:
        raise ImproperlyConfigured(
            'SECURE_KEY in the config file is a development placeholder or a published key; '
            'set a private random SECURE_KEY (and keep DEBUG false) for any non-development use')
    return secret_key
