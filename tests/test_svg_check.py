"""Task 6.6b: deny-list validator for `image` (SVG) values (editor/svg_check.py)."""
import pytest
from django.core.exceptions import ValidationError

from editor.svg_check import check_svg_value, svg_rule_violation

GOOD = [
    '',
    '<svg><text>plain</text></svg>',
    ('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><g fill="#fff" '
     'style="font-family:Arial;font-size:12px"><rect x="1" y="1" width="8" height="8"/>'
     '<text x="2" y="5"><tspan dy="1">a&quot;b&#160;c &amp; d</tspan></text></g></svg>'),
    '<svg><text>one &lt;script&gt; as text, and an online=shop remark, and a > b</text></svg>',
    '<svg><path d="M0 0L1 1" id="settle"/><rect fill="url(#grad)"/><linearGradient id="grad"/></svg>',
    '<svg><text title="a > b">x</text></svg>',
]


@pytest.mark.parametrize('value', GOOD)
def test_accepts(value):
    assert svg_rule_violation(value) is None
    check_svg_value(value)


@pytest.mark.parametrize('value,rule', [
    ('<svg><script>alert(1)</script></svg>', 'script element'),
    ('<svg><SCRIPT src=x></SCRIPT></svg>', 'script element'),
    ('<svg><  script>x</script></svg>', 'script element'),
    ('<svg onload="alert(1)"></svg>', 'event handler attribute'),
    ('<svg ONLOAD = alert(1)></svg>', 'event handler attribute'),
    ('<svg/onload=alert(1)>', 'event handler attribute'),
    ('<svg><rect x="1"onclick="a()"/></svg>', 'event handler attribute'),
    ('<svg><rect title=">" onmouseover="a()"/></svg>', 'event handler attribute'),
    ("<svg><rect\tonfocus='a()'/></svg>", 'event handler attribute'),
    ('<svg><a href="https://x">t</a></svg>', 'href attribute'),
    ('<svg><rect xlink:href="https://x"/></svg>', 'href attribute'),
    ('<svg><rect HREF = "x"/></svg>', 'href attribute'),
    ('<svg><a xlink:title="t">t</a></svg>', 'a element'),
    ('<svg><A>t</A></svg>', 'a element'),
    ('<svg><text x="1" y="1">javascript:alert(1)</text></svg>', 'javascript: URL'),
    ('<svg><text>JavaScript:alert(1)</text></svg>', 'javascript: URL'),
    ('<svg><text>&#x6a;avascript:alert(1)</text></svg>', 'javascript: URL'),
    ('<svg><text>&#106;avascript:alert(1)</text></svg>', 'javascript: URL'),
    ('<svg><text>java&Tab;script:alert(1)</text></svg>', 'javascript: URL'),
    ('<svg><text>java\nscript:alert(1)</text></svg>', 'javascript: URL'),
    ('<svg><text>&amp;#x6a;avascript:x</text></svg>', 'javascript: URL'),
    ('<svg><foreignObject><div/></foreignObject></svg>', 'foreignObject element'),
    ('<svg><FOREIGNOBJECT/></svg>', 'foreignObject element'),
    ('<svg><iframe src="x"></iframe></svg>', 'iframe element'),
    ('<svg><embed src="x"/></svg>', 'embed element'),
    ('<svg><object data="x"></object></svg>', 'object element'),
    ('<svg><use xlink:foo="#a"/></svg>', 'use element'),
    ('<svg><use/></svg>', 'use element'),
    ('<svg><image width="1"/></svg>', 'image element'),
    ('<svg><animate attributeName="x"/></svg>', 'animate element'),
    ('<svg><animateTransform/></svg>', 'animate element'),
    ('<svg><set attributeName="x" to="1"/></svg>', 'set element'),
    ('<svg><style>*{}</style></svg>', 'style element'),
    ('<svg><STYLE type="text/css">x</STYLE></svg>', 'style element'),
    ('<!DOCTYPE svg><svg/>', 'entity or doctype declaration'),
    ('<!ENTITY x "y"><svg/>', 'entity or doctype declaration'),
    ('<! doctype svg><svg/>', 'entity or doctype declaration'),
])
def test_rejects(value, rule):
    assert svg_rule_violation(value) == rule
    with pytest.raises(ValidationError):
        check_svg_value(value)


def test_none_is_allowed():
    assert svg_rule_violation(None) is None
