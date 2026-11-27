"""Reading and saving the stored configuration of a project (Project.config) with a conflict token.

The token identifies the stored value: `sha256:` plus the SHA-256 of the canonical JSON of the stored value
(sorted keys, no blanks), so it does not depend on the key order the database returns (MySQL reorders object
keys). An unconfigured project (`{}`) has a token like any other. Nothing here keeps state between calls.
"""
import hashlib
import hmac
import json

from django.db import transaction

from editor.config_validation import validate_config_json
from editor.models import Project

TOKEN_PREFIX = 'sha256:'


class StaleConfigError(Exception):
    """The stored configuration is not the one the editor was based on."""


class InvalidConfigError(Exception):
    """The submitted configuration is not valid; `errors` is a list of ConfigError."""

    def __init__(self, errors):
        super().__init__('invalid configuration')
        self.errors = errors


def config_token(stored):
    canonical = json.dumps(stored, sort_keys=True, separators=(',', ':'))
    return TOKEN_PREFIX + hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def read_stored_config(project_id):
    """The stored value (`{}` if unconfigured) from a fresh query, or None if there is no such project."""
    return Project.objects.filter(id=project_id).values_list('config', flat=True).first()


def save_project_config(project_id, body, token):
    """
    Validate the JSON text `body` against the project's data and store it as the project's configuration,
    provided the stored value still has the token `token`. Returns the token of the new stored value.

    The project row is locked (SELECT ... FOR UPDATE, effective on MySQL/InnoDB) in one transaction before the
    token is compared, and the comparison, the validation and the write all happen under that lock, so two
    concurrent saves cannot both pass the check. SQLite has no row locks; its single-writer transactions
    cannot lose an update either (the second writer fails instead of overwriting).
    Raises StaleConfigError (nothing written) and InvalidConfigError (nothing written).
    """
    with transaction.atomic():
        project = Project.objects.select_for_update().get(id=project_id)
        if not hmac.compare_digest(config_token(project.config).encode(), token.encode()):
            raise StaleConfigError()
        config, errors = validate_config_json(body, project)
        if errors:
            raise InvalidConfigError(errors)
        project.config = config
        project.save(update_fields=['config'])     # update_fields: updated_at is not touched
        return config_token(read_stored_config(project_id))
