"""Task 6.6c: allowlist validator for `image` (SVG) values (editor/svg_check.py); includes the 6.6b deny-list cases."""
import pytest
from django.core.exceptions import ValidationError

from editor.svg_check import MAX_LENGTH, check_svg_value, svg_rule_violation

NS = 'xmlns="http://www.w3.org/2000/svg"'
OPEN = '<svg ' + NS + '>'

# every allowed element, attribute and CSS property
FULL = (
    '<svg ' + NS + ' width="100px" height="50%" viewBox="0 0 100.5 -50e1" preserveAspectRatio="xMidYMid meet" '
    'version="1.1" style="position: relative; overflow: hidden; cursor: nw-resize; display: none; '
    'white-space: pre; background-color: #fff; fill-opacity: 0.5; font: 12px Arial, sans-serif; '
    'font-family: &quot;Arial&quot;, \'Helvetica\'; font-size: 12px; font-stretch: normal; font-style: italic; '
    'font-variant-caps: normal; font-weight: bold; line-height: 1.5; stroke-linecap: round; '
    'stroke-linejoin: bevel; text-anchor: middle">'
    '<desc>made by &quot;x&quot; &#160; &#xA0; &amp; &lt;b&gt; &apos;</desc><defs/>'
    '<rect x="1" y="2" width="3" height="4" r="1" rx="1" ry="1" fill="#fff" fill-opacity=".5" stroke="none" '
    'stroke-width="2" stroke-dasharray="-1.5 2,3" transform="translate(1,2) scale(2) rotate(45 1 1), '
    'matrix(1 0 0 1 0 0)" style="cursor: move"/>'
    '<path d="M0 0L1 1H2V3C1 2 3 4 5 6S1 2 3 4Q1 2 3 4T5 6A1 1 0 0 1 2 2Zm-1e-3,.5z" x="1" y="1" fill="#ffff" '
    'stroke="#12345678" stroke-width="1px" stroke-dasharray="1 2" stroke-linecap="butt" '
    'stroke-linejoin="miter" transform="translate(1)" style="display: none"/>'
    '<g transform="scale(1)" fill="#000" stroke="none" stroke-width="1" style="cursor: default">'
    '<text x="1" y="2" fill="#000" stroke="none" stroke-width="1" font="12px Arial" font-size="12" '
    'text-anchor="end" style="white-space: pre">a &quot; &#160; &amp; &lt; &gt;<tspan x="1" dx="2" dy="3" '
    'style="font-weight: bold">b &quot;&#160;&amp;&lt;&gt;</tspan> tail</text>'
    '<g><line x1="0" y1="0" x2="5" y2="5" stroke="#000" stroke-width="1" stroke-dasharray="-1 2" '
    'stroke-linecap="square" transform="translate(1)" style="cursor: move"/>'
    '<circle cx="1" cy="1" r="2" fill="#000" fill-opacity="1" stroke="#000" stroke-width="1" '
    'transform="scale(1)" style="cursor: move"/>'
    '<ellipse cx="1" cy="1" rx="2" ry="3" fill="none" fill-opacity="1" stroke="#000" stroke-width="1" '
    'transform="scale(1)" style="cursor: move"/>'
    '<polyline points="0,0 1,1 2,3" fill="none" fill-opacity="1" stroke="#000" stroke-width="1" '
    'stroke-dasharray="1 1" stroke-linejoin="round" transform="scale(1)" style="cursor: move"/>'
    '<polygon points="0,0 1,1 2,3" fill="#000" fill-opacity="1" stroke="#000" stroke-width="1" '
    'stroke-dasharray="1 1" stroke-linejoin="round" transform="scale(1)" style="cursor: move"/>'
    '</g></g></svg>')

GOOD = [
    '',
    FULL,
    '  \n' + OPEN + '\n  <g>\n  <text>one &lt;script&gt; as text and an online=shop remark</text>\n  </g>\n</svg>\n ',
    OPEN + '<path d="M0 0L1 1" fill="none"/><rect fill="#abc"/></svg>',     # inert shapes
    OPEN + '</svg>',
    OPEN + '<text x="1">a &gt; b</text></svg>',
]


@pytest.mark.parametrize('value', GOOD)
def test_accepts(value):
    assert svg_rule_violation(value) is None
    check_svg_value(value)


def test_none_is_allowed():
    assert svg_rule_violation(None) is None
    check_svg_value(None)


def ns(value):
    """The deny-list cases (written without a namespace) with the SVG namespace on the root."""
    return value.replace('<svg', '<svg ' + NS, 1)


# 6.6b deny-list cases, kept as regression tests: value -> rule of the allowlist validator
DENY_LIST_CASES = [
    ('<svg><script>alert(1)</script></svg>', 'element not allowed'),
    ('<svg><SCRIPT src=x></SCRIPT></svg>', 'malformed xml'),
    ('<svg><  script>x</script></svg>', 'malformed xml'),
    ('<svg onload="alert(1)"></svg>', 'attribute not allowed'),
    ('<svg ONLOAD = alert(1)></svg>', 'malformed xml'),
    ('<svg/onload=alert(1)>', 'not an svg document'),
    ('<svg><rect x="1"onclick="a()"/></svg>', 'malformed xml'),
    ('<svg><rect title=">" onmouseover="a()"/></svg>', 'attribute not allowed'),
    ("<svg><rect\tonfocus='a()'/></svg>", 'attribute not allowed'),
    ('<svg><a href="https://x">t</a></svg>', 'element not allowed'),
    ('<svg><rect xlink:href="https://x"/></svg>', 'malformed xml'),
    ('<svg><rect HREF = "x"/></svg>', 'attribute not allowed'),
    ('<svg><rect href="x"/></svg>', 'attribute not allowed'),
    ('<svg><a xlink:title="t">t</a></svg>', 'malformed xml'),
    ('<svg><A>t</A></svg>', 'element not allowed'),
    ('<svg><text x="1" y="1">javascript:alert(1)</text></svg>', None),       # plain text, inert
    ('<svg><text>&#x6a;avascript:alert(1)</text></svg>', None),
    ('<svg><rect fill="javascript:alert(1)"/></svg>', 'attribute value'),
    ('<svg><rect style="fill-opacity: javascript:alert(1)"/></svg>', 'style value (url/expression/import/script)'),
    ('<svg><rect style="fill-opacity: &#106;avascript:x"/></svg>', 'style value (url/expression/import/script)'),
    ('<svg><text>java&Tab;script:alert(1)</text></svg>', 'entity reference'),
    ('<svg><foreignObject><div/></foreignObject></svg>', 'element not allowed'),
    ('<svg><FOREIGNOBJECT/></svg>', 'element not allowed'),
    ('<svg><iframe src="x"></iframe></svg>', 'element not allowed'),
    ('<svg><embed src="x"/></svg>', 'element not allowed'),
    ('<svg><object data="x"></object></svg>', 'element not allowed'),
    ('<svg><use xlink:foo="#a"/></svg>', 'malformed xml'),
    ('<svg><use/></svg>', 'element not allowed'),
    ('<svg><image width="1"/></svg>', 'element not allowed'),
    ('<svg><animate attributeName="x"/></svg>', 'element not allowed'),
    ('<svg><animateTransform/></svg>', 'element not allowed'),
    ('<svg><set attributeName="x" to="1"/></svg>', 'element not allowed'),
    ('<svg><style>*{}</style></svg>', 'element not allowed'),
    ('<svg><STYLE type="text/css">x</STYLE></svg>', 'element not allowed'),
]


@pytest.mark.parametrize('value,rule', DENY_LIST_CASES)
def test_deny_list_cases_with_namespace(value, rule):
    assert svg_rule_violation(ns(value)) == rule
    if rule:
        with pytest.raises(ValidationError):
            check_svg_value(ns(value))
    else:
        check_svg_value(ns(value))


@pytest.mark.parametrize('value', [c[0] for c in DENY_LIST_CASES if c[1]])
def test_deny_list_cases_as_written_are_rejected(value):
    # without the namespace every one of them fails already on the root
    assert svg_rule_violation(value) is not None
    with pytest.raises(ValidationError):
        check_svg_value(value)


@pytest.mark.parametrize('value,rule', [
    ('<!DOCTYPE svg><svg/>', 'not an svg document'),
    ('<!ENTITY x "y"><svg/>', 'not an svg document'),
    ('<! doctype svg><svg/>', 'not an svg document'),
    (OPEN + '<!DOCTYPE x><g/></svg>', 'declaration, comment or CDATA'),
    (OPEN + '<!ENTITY x "y"><g/></svg>', 'declaration, comment or CDATA'),
    (OPEN + '<!-- note --><g/></svg>', 'declaration, comment or CDATA'),
    (OPEN + '<text><![CDATA[x]]></text></svg>', 'declaration, comment or CDATA'),
    (OPEN + '<?php x ?></svg>', 'processing instruction'),
    (OPEN + '<?xml-stylesheet href="x"?></svg>', 'processing instruction'),
    ('<?xml version="1.0"?>' + OPEN + '</svg>', 'not an svg document'),
    (OPEN[:-1] + ' x="1"></svg>', 'attribute not allowed'),
    (OPEN + '<blink/></svg>', 'element not allowed'),
    (OPEN + '<rect onclick="x"/></svg>', 'attribute not allowed'),
    (OPEN + '<rect fill="red"/></svg>', 'attribute value'),
    ('<svg ' + NS + ' xmlns:xlink="http://www.w3.org/1999/xlink"><rect xlink:href="#a"/></svg>', 'prefixed attribute'),
    ('<svg ' + NS + ' xml:space="preserve"></svg>', 'prefixed attribute'),
    (OPEN + '<g xmlns="http://example.org/x"/></svg>', 'foreign namespace'),
    (OPEN + '<h:p xmlns:h="http://www.w3.org/1999/xhtml">x</h:p></svg>', 'foreign namespace'),
    (OPEN + 'loose text<g/></svg>', 'text not allowed'),
    (OPEN + '<g>loose text</g></svg>', 'text not allowed'),
    (OPEN + '<g/>loose tail</svg>', 'text not allowed'),
    (OPEN + '<rect/>x</svg>', 'text not allowed'),
    (OPEN + '<text><g/></text></svg>', 'element not allowed'),
    (OPEN + '<desc><tspan/></desc></svg>', 'element not allowed'),
    (OPEN + '<defs><rect/></defs></svg>', 'element not allowed'),
    (OPEN + '<rect><g/></rect></svg>', 'element not allowed'),
    (OPEN + '<g><desc/></g></svg>', 'element not allowed'),
    (OPEN + '</svg>' + OPEN + '</svg>', 'malformed xml'),
    ('before' + OPEN + '</svg>', 'not an svg document'),
    (OPEN + '</svg>after', 'not an svg document'),
    (OPEN + '</svg><g/>', 'not an svg document'),
    ('<html xmlns="http://www.w3.org/1999/xhtml"><svg></svg></html>', 'not an svg document'),
    ('<svg xmlns="http://example.org/x"></svg>', 'root element'),
    ('<svg></svg>', 'root element'),
    ('<svgx ' + NS + '></svgx></svg>', 'malformed xml'),
    (OPEN + '<rect style="fill-opacity: url(#a)"/></svg>', 'style value (url/expression/import/script)'),
    (OPEN + '<rect style="background-color: rgb(1,2,3)"/></svg>', 'style value'),
    (OPEN + '<rect style="font-size: calc(1px)"/></svg>', 'style value'),
    (OPEN + '<rect style="position: fixed"/></svg>', 'style keyword'),
    (OPEN + '<rect style="display: block"/></svg>', 'style keyword'),
    (OPEN + '<rect style="behavior: x"/></svg>', 'style property'),
    (OPEN + '<rect style="fill-opacity"/></svg>', 'style declaration'),
    (OPEN + '<rect style="font: a\\62 c"/></svg>', 'style value (url/expression/import/script)'),
    (OPEN + '<rect style="font: @import x"/></svg>', 'style value (url/expression/import/script)'),
    (OPEN + '<rect transform="translate(1) evil(2)"/></svg>', 'attribute value'),
    (OPEN + '<rect width="1e"/></svg>', 'attribute value'),
    (OPEN + '<path d="M0 0 url(x)"/></svg>', 'attribute value'),
    (OPEN + '<path stroke-linecap="arrow"/></svg>', 'attribute value'),
    (OPEN + '<text font="a(b)"/></svg>', 'attribute value'),
    ('<svg ' + NS + ' version="1.1;x"></svg>', 'attribute value'),
    (OPEN + '<g>' * 6 + '</g>' * 6 + '</svg>', 'nesting too deep'),
    (OPEN + '<g/>' * 20_000 + '</svg>', 'too many elements'),
    (OPEN + '<text>' + 'a' * MAX_LENGTH + '</text></svg>', 'too long'),
    (OPEN + '<text>&nbsp;</text></svg>', 'entity reference'),
    (OPEN + '<text>&foo;</text></svg>', 'entity reference'),
    (OPEN + '<text>&amp</text></svg>', 'entity reference'),
    (OPEN + '<text>&#xZZ;</text></svg>', 'entity reference'),
    (OPEN + '<text>&#0;</text></svg>', 'malformed xml'),
    (OPEN + '<g></svg>', 'malformed xml'),
    (OPEN + '<g>', 'not an svg document'),
    (OPEN + '<text>a</text></svg>\x00</svg>', 'malformed xml'),
    (123, 'not a string'),
    (b'<svg/>', 'not a string'),
])
def test_rejects(value, rule):
    assert svg_rule_violation(value) == rule
    with pytest.raises(ValidationError):
        check_svg_value(value)


def test_depth_and_count_limits():
    assert svg_rule_violation(OPEN + '<g>' * 5 + '<rect/>' + '</g>' * 5 + '</svg>') == 'nesting too deep'
    assert svg_rule_violation(OPEN + '<g>' * 4 + '<rect/>' + '</g>' * 4 + '</svg>') is None
    assert svg_rule_violation(OPEN + '<g/>' * 19_999 + '</svg>') is None


def test_value_is_never_rewritten():
    value = '  ' + FULL + '\n'
    before = value
    assert svg_rule_violation(value) is None
    assert value == before
