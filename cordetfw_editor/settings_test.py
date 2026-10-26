"""
Test settings. Generates a synthetic config file in a temporary directory and
points CORDETFW_CONFIG_PATH at it before the production settings are imported,
so that settings.py, views.py and ext_cats.py never read /etc.
"""

import atexit
import json
import os
import shutil
import tempfile

_test_root = tempfile.mkdtemp(prefix='cordetfw-tests-')
atexit.register(shutil.rmtree, _test_root, ignore_errors=True)

_config_path = os.path.join(_test_root, 'config.json')
with open(_config_path, 'w', encoding='utf-8') as _f:
    json.dump({
        'SECURE_KEY': 'test-only-key-never-use-in-production',
        'DEBUG': False,
        'ALLOWED_HOSTS': ['testserver', 'localhost', '127.0.0.1'],
        'DATABASES': {'default': {
            'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'
        }},
        'MEDIA_ROOT': _test_root,
        'LOG_FILE': 'test.log',
        'BASE_URL': '/editor',
        'FWPROFILE_DB': {'HOST': 'fwprofile-test-host', 'USER': 'test',
                         'PWD': 'test', 'NAME': 'fwprofile_test'},
    }, _f)

# Deliberately override any inherited deployment path in this test-only module.
os.environ['CORDETFW_CONFIG_PATH'] = _config_path

from .settings import *  # noqa: E402,F401,F403

TEST_ROOT = _test_root
STATIC_ROOT = os.path.join(_test_root, 'static')
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
