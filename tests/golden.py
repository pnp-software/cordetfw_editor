"""
Golden-file assertions: compare output against a file under tests/golden/.

Goldens are recorded on the old (Django 3.2) stack and are the compatibility
contract for the upgrade. Regenerate with UPDATE_GOLDEN=1 only on the baseline
commit; any later golden change needs an explained, reviewed commit.
"""

import os
import re
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / 'golden'

_CSRF_INPUT = re.compile(rb'(name="csrfmiddlewaretoken" value=")[^"]+(")')


def normalize_html(content):
    """Remove per-request noise (CSRF tokens) from rendered HTML."""
    if isinstance(content, str):
        content = content.encode('utf-8')
    return _CSRF_INPUT.sub(rb'\1CSRF\2', content)


def assert_golden(name, content):
    """Assert that content (bytes or str) equals the golden file tests/golden/<name>."""
    if isinstance(content, str):
        content = content.encode('utf-8')
    path = GOLDEN_DIR / name
    if os.environ.get('UPDATE_GOLDEN') == '1':
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return
    assert path.exists(), 'Missing golden file %s (record it with UPDATE_GOLDEN=1 on the baseline)' % path
    expected = path.read_bytes()
    if content != expected:
        actual_path = path.with_name(path.name + '.actual')
        actual_path.write_bytes(content)
        raise AssertionError('Output differs from golden %s; actual output written to %s'
                             % (path, actual_path))
