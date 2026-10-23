"""
Deny-list check for the SVG held in `image` fields (Model/FCP `value`).

Task 6.6b: `image` values are rendered unescaped, so every write path rejects markup that can run
script. This is a simple deny-list; the allowlist sanitiser is tracked as `image-svg-unsanitised`
(track K).
"""
import html
import re

from django.core.exceptions import ValidationError

_I = re.IGNORECASE
# A start tag, tolerating '>' inside quoted attribute values.
_TAG = r'<[a-z][^\s>/]*(?:[^>"\']|"[^"]*"|\'[^\']*\')*?'
_SEP = r'(?<=[\s"\'/])'                       # an attribute name starts after whitespace, a quote or '/'

RULES = (
    ('script element', re.compile(r'<\s*script', _I)),
    ('event handler attribute', re.compile(_TAG + _SEP + r'on[a-z]+\s*=', _I)),
    ('foreignObject element', re.compile(r'<\s*foreignobject', _I)),
    ('iframe element', re.compile(r'<\s*iframe', _I)),
    ('embed element', re.compile(r'<\s*embed', _I)),
    ('object element', re.compile(r'<\s*object', _I)),
    ('href attribute', re.compile(_TAG + _SEP + r'(?:[a-z]+:)?href\s*=', _I)),
    ('a element', re.compile(r'<\s*a[\s>/]', _I)),
    ('use element', re.compile(r'<\s*use[\s>/]', _I)),
    ('image element', re.compile(r'<\s*image[\s>/]', _I)),
    ('animate element', re.compile(r'<\s*animate', _I)),
    ('set element', re.compile(r'<\s*set[\s>/]', _I)),
    ('style element', re.compile(r'<\s*style', _I)),
    ('entity or doctype declaration', re.compile(r'<!\s*(?:entity|doctype)', _I)),
)
_JS_URL = re.compile(r'javascript:', _I)
_CTRL = re.compile(r'[\x00-\x20\x7f]+')


def svg_rule_violation(value):
    """Name of the first deny-list rule `value` breaks, or None."""
    if not value:
        return None
    s = str(value)
    for name, pattern in RULES:
        if pattern.search(s):
            return name
    decoded = s
    for _ in range(3):                         # entity variations such as &#x6a;avascript:
        decoded = html.unescape(decoded)
    if _JS_URL.search(_CTRL.sub('', decoded)):
        return 'javascript: URL'
    return None


def check_svg_value(value):
    """Raise ValidationError if the SVG in `value` contains active content (empty value allowed)."""
    rule = svg_rule_violation(value)
    if rule:
        raise ValidationError('The image (SVG) contains disallowed content (%s)' % rule)
