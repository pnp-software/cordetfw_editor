"""
Strict allowlist validator for the SVG held in `image` fields (Model/FCP `value`).

Task 6.6c (replaces the 6.6b deny-list): `image` values are rendered unescaped, so every write path
rejects anything that is not a plain SVG built from the elements, attributes and CSS properties the
FW Profile diagrams use (derived from the 240 production diagrams, operator-approved 2026-10-24).
The validator only validates; it never rewrites a value.

`svg_rule_violation(value)` returns None or the short name of the first rule broken;
`check_svg_value(value)` raises ValidationError.
"""
import re
import xml.etree.ElementTree as ET

from django.core.exceptions import ValidationError

SVG_NS = 'http://www.w3.org/2000/svg'
MAX_LENGTH = 200_000
MAX_DEPTH = 6
MAX_ELEMENTS = 20_000

_SHAPES = ('rect', 'path', 'line', 'circle', 'ellipse', 'polyline', 'polygon')
_GROUPABLE = _SHAPES + ('text', 'g')

# element -> allowed children
CHILDREN = {
    'svg': ('desc', 'defs') + _GROUPABLE,
    'g': _GROUPABLE,
    'text': ('tspan',),
    'desc': (), 'tspan': (), 'defs': (),
}
CHILDREN.update({shape: () for shape in _SHAPES})
TEXT_ELEMENTS = ('desc', 'text', 'tspan')

ATTRIBUTES = {
    'svg': 'width height viewBox preserveAspectRatio version style',
    'rect': 'x y width height r rx ry fill fill-opacity stroke stroke-width stroke-dasharray transform style',
    'path': 'd x y fill stroke stroke-width stroke-dasharray stroke-linecap stroke-linejoin transform style',
    'text': 'x y fill stroke stroke-width font font-size text-anchor style',
    'tspan': 'x dx dy style',
    'g': 'transform fill stroke stroke-width style',
    'line': 'x1 y1 x2 y2 stroke stroke-width stroke-dasharray stroke-linecap transform style',
    'circle': 'cx cy r fill fill-opacity stroke stroke-width transform style',
    'ellipse': 'cx cy rx ry fill fill-opacity stroke stroke-width transform style',
    'polyline': 'points fill fill-opacity stroke stroke-width stroke-dasharray stroke-linejoin transform style',
    'polygon': 'points fill fill-opacity stroke stroke-width stroke-dasharray stroke-linejoin transform style',
    'desc': '', 'defs': '',
}
ATTRIBUTES = {k: frozenset(v.split()) for k, v in ATTRIBUTES.items()}

_A = re.ASCII
_NUMBER = re.compile(r'-?\d*\.?\d+([eE][-+]?\d+)?(px|%)?', _A)
_COLOR = re.compile(r'#[0-9a-fA-F]{3,8}|none', _A)
_TRANSFORM_ITEM = r'(translate|scale|rotate|matrix)\(\s*[-0-9eE.,\s]*\)'
_TRANSFORM = re.compile(r'\s*%s(?:[\s,]*%s)*\s*' % (_TRANSFORM_ITEM, _TRANSFORM_ITEM), _A)
_FONT = re.compile(r'[\w\s\-.,%#"\']*', _A)

_NUMERIC_ATTRS = ('x y dx dy width height r rx ry cx cy x1 y1 x2 y2 font-size stroke-width fill-opacity').split()
VALUE_PATTERNS = {name: _NUMBER for name in _NUMERIC_ATTRS}
VALUE_PATTERNS.update({
    'fill': _COLOR, 'stroke': _COLOR,
    'd': re.compile(r'[MmLlHhVvCcSsQqTtAaZz0-9eE+\-.,\s]*', _A),
    'points': re.compile(r'[0-9eE+\-.,\s]*', _A),
    'transform': _TRANSFORM,
    'stroke-dasharray': re.compile(r'-?[0-9.,\s]*', _A),
    'viewBox': re.compile(r'[-0-9eE.,\s]+', _A),
    'stroke-linecap': re.compile(r'butt|round|square'),
    'stroke-linejoin': re.compile(r'miter|round|bevel'),
    'text-anchor': re.compile(r'start|middle|end'),
    'preserveAspectRatio': re.compile(r'[A-Za-z\s]+', _A),
    'version': re.compile(r'[0-9.]+', _A),
    'font': _FONT,
})

# CSS properties of the style attribute; None = free value from _FONT charset, tuple = keyword values
# observed in the production diagrams
STYLE_PROPERTIES = {p: None for p in (
    'background-color fill-opacity font font-family font-size font-stretch font-style font-variant-caps '
    'font-weight line-height stroke-linecap stroke-linejoin text-anchor').split()}
STYLE_PROPERTIES.update({
    'position': ('relative',),
    'overflow': ('hidden',),
    'display': ('none',),
    'cursor': ('default', 'move', 'nw-resize'),
    'white-space': ('pre',),
})
_STYLE_BAD = re.compile(r'url\(|expression|@import|javascript|\\|<', re.IGNORECASE)

_ENTITY = re.compile(r'&(?!(?:quot|amp|lt|gt|apos);|#[0-9]+;|#x[0-9a-fA-F]+;)')
_BLANK = re.compile(r'\s*')


def _style_violation(style):
    for declaration in style.split(';'):
        if not declaration.strip():
            continue
        prop, sep, value = declaration.partition(':')
        if not sep:
            return 'style declaration'
        prop, value = prop.strip(), value.strip()
        if prop not in STYLE_PROPERTIES:
            return 'style property'
        if _STYLE_BAD.search(value):
            return 'style value (url/expression/import/script)'
        if not _FONT.fullmatch(value):
            return 'style value'
        keywords = STYLE_PROPERTIES[prop]
        if keywords is not None and value not in keywords:
            return 'style keyword'
    return None


def _attribute_violation(name, value, element):
    if name.startswith('{') or ':' in name:
        return 'prefixed attribute'
    if name not in ATTRIBUTES[element]:
        return 'attribute not allowed'
    if name == 'style':
        return _style_violation(value)
    if not VALUE_PATTERNS[name].fullmatch(value):
        return 'attribute value'
    return None


def _element_violation(el, depth, parent):
    if depth > MAX_DEPTH:
        return 'nesting too deep'
    if not isinstance(el.tag, str) or not el.tag.startswith('{'):
        return 'foreign namespace'
    ns, _, name = el.tag[1:].partition('}')
    if ns != SVG_NS:
        return 'foreign namespace'
    if name not in CHILDREN or (parent is not None and name not in CHILDREN[parent]):
        return 'element not allowed'
    for attr, value in el.attrib.items():
        rule = _attribute_violation(attr, value, name)
        if rule:
            return rule
    if el.text and not _BLANK.fullmatch(el.text) and name not in TEXT_ELEMENTS:
        return 'text not allowed'
    for child in el:
        if child.tail and not _BLANK.fullmatch(child.tail) and name != 'text':
            return 'text not allowed'
        rule = _element_violation(child, depth + 1, name)
        if rule:
            return rule
    return None


def svg_rule_violation(value):
    """Name of the first rule `value` breaks, or None (empty value / None: no diagram, allowed)."""
    if value is None or value == '':
        return None
    if not isinstance(value, str):
        return 'not a string'
    if len(value) > MAX_LENGTH:
        return 'too long'
    s = value.strip()
    if not (s.startswith('<svg') and s.endswith('</svg>')):
        return 'not an svg document'
    if '<!' in s:
        return 'declaration, comment or CDATA'
    if '<?' in s:
        return 'processing instruction'
    if _ENTITY.search(s):
        return 'entity reference'
    try:
        root = ET.fromstring(s)
    except (ET.ParseError, ValueError, RecursionError):
        return 'malformed xml'
    if root.tag != '{%s}svg' % SVG_NS:
        return 'root element'
    count = sum(1 for _ in root.iter())
    if count > MAX_ELEMENTS:
        return 'too many elements'
    return _element_violation(root, 1, None)


def check_svg_value(value):
    """Raise ValidationError if `value` is not an allowed SVG (empty value allowed)."""
    rule = svg_rule_violation(value)
    if rule:
        raise ValidationError('The image (SVG) contains disallowed content (%s)' % rule)
