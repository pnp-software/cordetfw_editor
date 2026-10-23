# SVG allowlist for `image` fields (editor/svg_check.py)

Kind `image` (Model/FCP `value`, FW Profile diagram) is rendered unescaped in the list page, so the stored
value must be an SVG that cannot execute or break out. The validator only validates; it never rewrites a value.

**Provenance.** 7 elements observed in the 240 production diagrams (dump 2026-10-21) + operator-approved inert
shapes g, line, circle, ellipse, polyline, polygon (2026-10-24); keyword values as observed.

**Rule for additions.** Any future addition (element, attribute, property, keyword) must be inert both as an SVG
element and as an unknown HTML-namespace element, because a browser that leaves the SVG foreign content (a
breakout) reparses the same markup as HTML.

## Where it is enforced

| place | behaviour |
| --- | --- |
| `editor/forms.py` `SpecItemForm.clean`, mode `add` only | value from the FW Profile choice is validated (`check_svg_value`, form error). In edit/copy/split the value is taken from the source item and in del nothing is written: no validation, so an item whose stored diagram is invalid can still be edited, copied, split and deleted |
| `editor/imports.py` (ZIP/JSON import), `editor/views.py` (CSV import) | values from the uploaded file are validated, the import is refused on a violation |
| `editor/ext_cats.py` (refresh from / add from the FW Profile database) | the fetched diagram is validated before it is stored |
| `editor/convert.py` `conv_db_disp_image` (render) | a stored value that breaks a rule is replaced by the text `[diagram not shown: invalid content]`; a valid value is output byte for byte |
| `editor/templates/list_spec_items.html` | `image` cells are not passed through `linebreaksbr` (filter `linebreaksbr_cell`), so newlines inside the SVG stay newlines; all other cells keep `linebreaksbr` |

Empty value and `None` mean "no diagram" and are allowed.

## Pre-parse rules (on the raw string; rule name in brackets)

1. Must be a `str` [not a string]; at most 200,000 characters [too long].
2. After stripping XML whitespace only (space, tab, CR, LF) it starts with `<svg` and ends with `</svg>` [not an svg
   document]. NBSP, U+3000, `\x0b`, `\x0c`, `\x1c` and other Unicode whitespace are not stripped.
3. No `<!` (DOCTYPE, comment, CDATA) [declaration, comment or CDATA]; no `<?` [processing instruction].
4. No entity reference except `&quot; &amp; &lt; &gt; &apos;` and numeric `&#N;` / `&#xH;` [entity reference].
5. No element name containing a colon, i.e. the raw string must not match `</?[^\s>/!?]*:` [prefixed element].
6. Must parse as XML [malformed xml].
7. Namespaces: the only declaration allowed is the default `xmlns="http://www.w3.org/2000/svg"` on the root
   element. Any `xmlns:prefix`, any `xmlns` on a non-root element, any other URI or `xmlns=""` [namespace
   declaration]. Production: all 240 diagrams have exactly this one declaration on the root.
8. The root is `{http://www.w3.org/2000/svg}svg` [root element]; at most 20,000 elements [too many elements];
   nesting depth at most 6 (root = 1) [nesting too deep].

## Elements and allowed children

| element | children |
| --- | --- |
| `svg` (root only) | desc, defs, rect, path, line, circle, ellipse, polyline, polygon, text, g |
| `g` | rect, path, line, circle, ellipse, polyline, polygon, text, g |
| `text` | tspan |
| `rect path line circle ellipse polyline polygon desc tspan defs` | none |

Anything else, or an allowed element in a place not listed, is [element not allowed]; an element outside the SVG
namespace is [foreign namespace]. Character data is allowed only inside `desc`, `text` and `tspan`; elsewhere only
XML whitespace (also between children, except that tails inside `text` may be text) [text not allowed].

## Attributes per element (anything else: [attribute not allowed]; prefixed / namespaced names: [prefixed attribute])

| element | attributes |
| --- | --- |
| svg | width height viewBox preserveAspectRatio version style |
| rect | x y width height r rx ry fill fill-opacity stroke stroke-width stroke-dasharray transform style |
| path | d x y fill stroke stroke-width stroke-dasharray stroke-linecap stroke-linejoin transform style |
| text | x y fill stroke stroke-width font font-size text-anchor style |
| tspan | x dx dy style |
| g | transform fill stroke stroke-width style |
| line | x1 y1 x2 y2 stroke stroke-width stroke-dasharray stroke-linecap transform style |
| circle | cx cy r fill fill-opacity stroke stroke-width transform style |
| ellipse | cx cy rx ry fill fill-opacity stroke stroke-width transform style |
| polyline, polygon | points fill fill-opacity stroke stroke-width stroke-dasharray stroke-linejoin transform style |
| desc, defs | none |

## Value patterns (full match, ASCII; failure: [attribute value])

All patterns are linear: every repetition is over one character class or over alternatives with distinct first
characters (no overlapping quantifiers; tested with 190,000 character adversarial inputs, each rejected in < 0.5 s).

| attribute(s) | pattern |
| --- | --- |
| x y dx dy width height r rx ry cx cy x1 y1 x2 y2 font-size stroke-width fill-opacity | number `-?(?:\d+(?:\.\d+)?\|\.\d+)(?:[eE][-+]?\d+)?(?:px\|%)?` |
| fill, stroke | `#` + 3 to 8 hex digits, or `none` |
| d | characters `MmLlHhVvCcSsQqTtAaZz0-9eE+-.,` and whitespace |
| points | characters `0-9eE+-.,` and whitespace |
| transform | one or more of `translate(...) scale(...) rotate(...) matrix(...)`, arguments from `-0-9eE.,` and whitespace, separated by whitespace/commas |
| stroke-dasharray | `-?[0-9.,\s]*` |
| viewBox | `[-0-9eE.,\s]+` |
| stroke-linecap | butt, round, square |
| stroke-linejoin | miter, round, bevel |
| text-anchor | start, middle, end |
| preserveAspectRatio | letters and whitespace |
| version | digits and dots |
| font | `[\w\s\-.,%#"']*` |

## Length caps per attribute value [attribute too long]

numbers: 64; d and points: 50,000; transform and style: 2,000; every other attribute: 256. Production maxima
(240 diagrams): numbers 19, d 110, points not used, transform 57, style 184, font 12, viewBox 17; largest whole
diagram 45,954 characters.

## `style` attribute

Declarations separated by `;`; an empty declaration is ignored. Property and value are stripped of XML whitespace
only (so `style=" display: none"` is accepted, `style="<NBSP>display: none"` is [style property]). A declaration
without `:` is [style declaration]. Value must not contain `url(`, `expression`, `@import`, `javascript`, a
backslash or `<` (case-insensitive) [style value (url/expression/import/script)] and must match the `font`
pattern [style value].

Properties with a free value (the `font` pattern): background-color, fill-opacity, font, font-family, font-size,
font-stretch, font-style, font-variant-caps, font-weight, line-height, stroke-linecap, stroke-linejoin,
text-anchor. Properties with keyword values (as observed in production) [style keyword]:

| property | values |
| --- | --- |
| position | relative |
| overflow | hidden |
| display | none |
| cursor | default, move, nw-resize |
| white-space | pre |
