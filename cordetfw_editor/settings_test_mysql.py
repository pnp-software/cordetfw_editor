"""
Test settings against a disposable MySQL server (never a production endpoint).
Credentials come from the environment:
    CORDETFW_TEST_MYSQL_HOST (default 127.0.0.1), CORDETFW_TEST_MYSQL_PORT (default 3306),
    CORDETFW_TEST_MYSQL_USER, CORDETFW_TEST_MYSQL_PASSWORD
The account only needs rights on the disposable test database.
"""

import os

from .settings_test import *  # noqa: F401,F403  (first: it points the config path at the test config)
from .settings import apply_mysql_connection_defaults  # noqa: E402

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'cordetfw_migration_test',
        'HOST': os.environ.get('CORDETFW_TEST_MYSQL_HOST', '127.0.0.1'),
        'PORT': os.environ.get('CORDETFW_TEST_MYSQL_PORT', '3306'),
        'USER': os.environ['CORDETFW_TEST_MYSQL_USER'],
        'PASSWORD': os.environ['CORDETFW_TEST_MYSQL_PASSWORD'],
        'TEST': {'NAME': 'test_cordetfw_migration_test'},
    }
}
apply_mysql_connection_defaults(DATABASES)
