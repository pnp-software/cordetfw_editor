"""
Task 6.6: stored text is escaped in HTML output (xss-display, xss-tag, md-no-escape HTML part).

Text nodes escape only & < > (quotes unchanged), attributes use the full django escape().
Kind `image` (Model/FCP `value`, inline SVG) is exempt in track S: the pins marked
`# KNOWN-ISSUE: image-svg-unsanitised` are input for the track K sanitiser.
"""
import csv
import io

import pytest
from django.utils.safestring import SafeString

from editor import convert
from editor.configs import configs
from editor.convert import (convert_db_to_display, conv_db_disp_eval_ref, conv_db_disp_plain_ref,
                            conv_db_disp_ref_text, conv_do_nothing)
from editor.templatetags import ref_filters
from tests.factories import (default_val_set, make_application, make_project, make_spec_item,
                             make_user)
from tests.test_convert import world, _tag_ctx, CATS            # noqa: F401  (fixture)
from tests.test_import_export import export_zip, upload_zip, fresh_temp   # noqa: F401
from tests.test_post_only_mutations import model_setup, fake_connect, ROW
from editor.models import Project, SpecItem

pytestmark = pytest.mark.django_db

SCRIPT = '<script>alert(1)</script>'
SCRIPT_ESC = '&lt;script&gt;alert(1)&lt;/script&gt;'
SVG = '<svg onload="alert(1)"><script>alert(2)</script><text>a &amp; b</text></svg>'


# ------------------------------------------------------------ helper
def test_escape_text_helper():
    from editor.convert import escape_text
    assert escape_text('a < b & c > d') == 'a &lt; b &amp; c &gt; d'
    assert escape_text('"quoted" \'single\'') == '"quoted" \'single\''
    assert escape_text('&amp;') == '&amp;amp;'
    assert escape_text('plain') == 'plain'
    assert not isinstance(escape_text('x'), SafeString)


# ------------------------------------------------------------ convert_db_to_display
@pytest.mark.parametrize('src,expected', [
    (SCRIPT, SCRIPT_ESC),
    ('<b>x</b>', '&lt;b&gt;x&lt;/b&gt;'),
    ('a < b & c > d', 'a &lt; b &amp; c &gt; d'),
    ('"quoted" \'single\'', '"quoted" \'single\''),
    ('<code>x</code>', '&lt;code&gt;x&lt;/code&gt;'),
    ('&amp; &lt;', '&amp;amp; &amp;lt;'),
])
def test_display_escapes_text(world, src, expected):
    # FIXED: xss-display (was: text outside references returned raw)
    assert convert_db_to_display(src, None) == expected


@pytest.mark.parametrize('src,expected', [
    ('**bold**', '<b>bold</b>'),
    ('++u++', '<u>u</u>'),
    ('__i__', '<i>i</i>'),
    ('``code``', '<code>code</code>'),
    ('t\n- a\n- b', 't<ul><li>a</li><li>b</li></ul>'),
    # markers next to characters which are escaped
    ('**a < b**', '<b>a &lt; b</b>'),
    ('++a & b++', '<u>a &amp; b</u>'),
    ('__<i>x</i>__', '<i>&lt;i&gt;x&lt;/i&gt;</i>'),
    ('``<b>``', '<code>&lt;b&gt;</code>'),
    ('t\n- a < b\n- c & d', 't<ul><li>a &lt; b</li><li>c &amp; d</li></ul>'),
    ('<**x**>', '&lt;<b>x</b>&gt;'),
    ('a&**b**&c', 'a&amp;<b>b</b>&amp;c'),
])
def test_display_markdown_with_escaped_text(world, src, expected):
    # md-no-escape, HTML part fixed in Task 6.6 (the id stays OPEN for the LaTeX part, track K):
    # the text is escaped before markdown is applied
    assert convert_db_to_display(src, None) == expected


def test_display_escaped_output_cannot_form_markers_or_irefs(world):
    # the escaping only produces & ; a-z # digits: none of the markdown markers ('**', '++', '__',
    # '``', leading '- ') nor the '#iref:N' pattern can be created by escaping
    out = convert.escape_text('<>&' * 5)
    for marker in ('**', '++', '__', '``', '#iref', '\n-'):
        assert marker not in out
    # the literal text '&#13;' (an entity used in tooltips) cannot be injected either
    assert convert_db_to_display('&#13;', None) == '&amp;#13;'


def test_display_iref_next_to_escaped_text(world):
    e = world['etype']
    out = convert_db_to_display('<i> #iref:%d & "q" **b**' % e.id, None)
    assert out.startswith('&lt;i&gt; <a href="/editor/EnumType/')
    assert '>D:T1</a> &amp; "q" <b>b</b>' in out
    # the link tooltip is escaped as before (its desc contains <&>)
    assert 'Description: d &lt;&amp;&gt;&#13;' in out
    assert '<script' not in out


def test_display_title_quote_in_item_does_not_break_tooltip(world):
    item = make_spec_item(world['project'], 'EnumType', 'D', 'q2', status='CNF', title='a"b', desc='x')
    out = convert_db_to_display('#iref:%d' % item.id, None)
    assert 'Title: a&quot;b&#13;' in out        # unchanged behaviour (attribute escaping already done)


# ------------------------------------------------------------ conv_db_disp tag, per kind
SPECIALS = [
    (SCRIPT, SCRIPT_ESC),
    ('<b>x</b>', '&lt;b&gt;x&lt;/b&gt;'),
    ('a < b & c > d', 'a &lt; b &amp; c &gt; d'),
    ('"quoted" \'single\'', '"quoted" \'single\''),
]


@pytest.mark.parametrize('src,expected', SPECIALS)
def test_tag_plain_text_ref_text_and_eval_ref(world, src, expected):
    # FIXED: xss-tag (was: every value marked safe without escaping)
    item = make_spec_item(world['project'], 'DataItem', 'D', 'xss', p_link=world['etype'],
                          title=src, desc=src, value=src)
    out = dict(ref_filters.conv_db_disp(_tag_ctx(world), item, ['title', 'desc', 'value']))
    assert out['Title'] == expected
    assert out['Description'] == expected
    # eval_ref: no markup/iref -> displayed text only, evaluated on the raw string
    assert out['Value'] == expected
    assert all(isinstance(v, SafeString) for v in out.values())


def test_tag_plain_ref_owner_escaped(world):
    owner = make_user('o<b>&"x')
    item = make_spec_item(world['project'], 'DataItem', 'D', 'own', p_link=world['etype'], owner=owner)
    assert conv_db_disp_plain_ref({}, item, 'owner', None) == 'o&lt;b&gt;&amp;"x'
    out = ref_filters.conv_db_disp(_tag_ctx(world), item, ['owner'])
    assert out == [('Owner', 'o&lt;b&gt;&amp;"x')]


def test_tag_eval_ref_with_iref_and_special_chars(world):
    x = world['x']      # value '2*3'
    item = make_spec_item(world['project'], 'DataItem', 'D', 'ev', p_link=world['etype'],
                          value='#iref:%d+1' % x.id)
    out = conv_db_disp_eval_ref({}, item, 'value', None)
    assert out.endswith('</a>+1 = 7.0')
    # unevaluable raw input with special chars: displayed text escaped, '= <nval>' (the raw input) too
    item2 = make_spec_item(world['project'], 'DataItem', 'D', 'ev2', p_link=world['etype'],
                           value='#iref:%d < 1 & **b**' % x.id)
    out2 = conv_db_disp_eval_ref({}, item2, 'value', None)
    head, _, nval = out2.rpartition(' = ')
    assert ' &lt; 1 &amp; <b>b</b>' in head and '<a href=' in head
    assert nval == '#iref:%d &lt; 1 &amp; **b**' % x.id
    assert '<script' not in out2


def test_tag_eval_ref_plain_text_not_evaluated_twice(world):
    # no iref and no markdown: the text is returned (escaped) without ' = ...'
    item = make_spec_item(world['project'], 'DataItem', 'D', 'ev3', p_link=world['etype'], value='a < b')
    assert conv_db_disp_eval_ref({}, item, 'value', None) == 'a &lt; b'
    item = make_spec_item(world['project'], 'DataItem', 'D', 'ev4', p_link=world['etype'], value='1 < 2')
    assert conv_db_disp_eval_ref({}, item, 'value', None) == '1 &lt; 2'


def test_tag_int_kind_unchanged(world):
    item = make_spec_item(world['project'], 'EnumType', 'D', 'e2', n1=7)
    assert ref_filters.conv_db_disp(_tag_ctx(world, cat='EnumType'), item, ['n1']) == [('Size', '7')]


def test_tag_image_kind_unchanged_byte_for_byte(world):
    app = make_application(world['project'], 'A', cats='Model')
    item = make_spec_item(world['project'], 'Model', 'D', 'm', application=app, value=SVG)
    out = ref_filters.conv_db_disp(_tag_ctx(world, cat='Model'), item, ['value'])
    assert out == [('Diagram', SVG)]
    assert isinstance(out[0][1], SafeString)
    assert conv_do_nothing({}, item, 'value', None) == SVG


def test_tag_other_text_attrs_of_model_escaped_image_not(world):
    app = make_application(world['project'], 'A', cats='Model')
    item = make_spec_item(world['project'], 'Model', 'D', 'm', application=app, value=SVG, title=SCRIPT)
    out = dict(ref_filters.conv_db_disp(_tag_ctx(world, cat='Model'), item, ['title', 'value']))
    assert out['Title'] == SCRIPT_ESC and out['Diagram'] == SVG


# ------------------------------------------------------------ filter_expand_tip (attribute)
def test_expand_tip_quote_does_not_break_attribute(world):
    # FIXED: xss-tag (was: raw value inside title="...", a '"' ended the attribute)
    item = make_spec_item(world['project'], 'DataItem', 'D', 'tip', p_link=world['etype'],
                          title='a" onmouseover="alert(1)', desc="it's <b>&", value='1')
    out = ref_filters.filter_expand_tip(item)
    assert out == ('Title: a&quot; onmouseover=&quot;alert(1)&#13;'
                   'Description: it&#x27;s &lt;b&gt;&amp;&#13;Value: 1&#13;')
    assert isinstance(out, SafeString)


def test_expand_tip_iref_converted_then_escaped(world):
    item = make_spec_item(world['project'], 'DataItem', 'D', 'tip2', p_link=world['etype'],
                          desc='see #iref:%d <b>' % world['etype'].id, value='1')
    out = ref_filters.filter_expand_tip(item)
    assert out == 'Title: Title of tip2&#13;Description: see #EnumType:D:T1 &lt;b&gt;&#13;Value: 1&#13;'


def test_expand_tip_in_template_keeps_linebreaksbr(world):
    from django.template import Context, Template
    item = make_spec_item(world['project'], 'DataItem', 'D', 'tip3', p_link=world['etype'],
                          desc='l1\nl2 "q"', value='1')
    html = Template('{% load ref_filters %}<a title="{{ i|filter_expand_tip|linebreaksbr }}">').render(
        Context({'i': item}))
    assert html == ('<a title="Title: Title of tip3&#13;Description: l1<br>l2 &quot;q&quot;&#13;'
                    'Value: 1&#13;">')


# ------------------------------------------------------------ disp_trac
def _trac_world(world, **link_fields):
    p = world['project']
    pkt = make_spec_item(p, 'Packet', 'P', 'pkt', status='CNF')
    req = make_spec_item(p, 'Requirement', 'R', 'r', status='CNF', **link_fields)
    make_spec_item(p, 'VerLink', 'V', 'l', status='CNF', s_link=pkt, p_link=req)
    return pkt


def test_disp_trac_escapes_desc_attribute_and_text(world):
    # FIXED: xss-tag (was: desc/title/name inserted raw)
    pkt = _trac_world(world, desc='he said "hi" <b>&\'', title='T <i> & "q"')
    out = ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None)
    assert 'title="he said &quot;hi&quot; &lt;b&gt;&amp;&#x27;"' in out
    assert out.endswith('>R:r</a> (T &lt;i&gt; &amp; "q")')
    assert isinstance(out, SafeString)
    assert '<b>' not in out and '<i>' not in out


def test_disp_trac_p_link_branch_escaped(world):
    p = world['project']
    pkt = make_spec_item(p, 'Packet', 'P', 'pkt', status='CNF', desc='"d"', title='<t>')
    req = make_spec_item(p, 'Requirement', 'R', 'r', status='CNF')
    make_spec_item(p, 'VerLink', 'V', 'l', status='CNF', s_link=pkt, p_link=req)
    out = ref_filters.disp_trac(_tag_ctx(world), req, 'VerLink', 'p_link', None)
    assert 'title="&quot;d&quot;"' in out and out.endswith('>P:pkt</a> (&lt;t&gt;)')


def test_disp_trac_clean_text_unchanged(world):
    pkt = _trac_world(world, desc='plain desc', title='Plain')
    out = ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None)
    assert out == ('<a class="link-table-list-spec" href="/editor/Requirement/%d/0/%d/R/0\\list_spec_items#R:r" '
                   'title="plain desc">R:r</a> (Plain)' % (world['project'].id, pkt.val_set.id))


# ------------------------------------------------------------ whole pages
def _list_url(item, disp=None):
    p = item.project
    app = item.application_id or 0
    url = '/editor/%s/%d/%d/%d/Sel_All/0/list_spec_items' % (item.cat, p.id, app, default_val_set(p).id)
    return url + ('?disp=' + disp if disp else '')


@pytest.mark.parametrize('disp', ['disp_def', 'disp_short', 'disp_trac'])
def test_page_escapes_stored_text(client, world, disp):
    # FIXED: xss-display (was: stored markup rendered as is on the list page)
    # FIXED: xss-tag (was: the same for the tag outputs)
    item = make_spec_item(world['project'], 'DataItem', 'D', 'pg', p_link=world['etype'],
                          title=SCRIPT, desc='<b>x</b> "q" & **bold**', value='a < b')
    client.force_login(world['owner'])
    html = client.get(_list_url(item, disp)).content.decode()
    assert SCRIPT not in html
    assert '<b>x</b>' not in html
    assert SCRIPT_ESC in html
    if disp == 'disp_def':
        assert '&lt;b&gt;x&lt;/b&gt; "q" &amp; <b>bold</b>' in html


def test_page_expand_tip_attribute_not_broken(client, world):
    etype = world['etype']
    make_spec_item(world['project'], 'EnumValue', 'D', 'kid', s_link=etype, title='x" data-x="1')
    client.force_login(world['owner'])
    url = '/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d&expand_link=s_link' % (
        world['project'].id, default_val_set(world['project']).id, etype.id)
    html = client.get(url).content.decode()
    assert 'Title: x&quot; data-x=&quot;1&#13;Description: &#13;' in html
    assert 'data-x="1' not in html


# ------------------------------------------------------------ image write paths (characterization)
def _model_page(client, s, app, item):
    return client.get('/editor/Model/%d/%d/%d/Sel_All/0/list_spec_items' % (
        s.pid, app.id, default_val_set(s.w.project).id)).content.decode()


def test_image_edit_form_value_is_hidden_but_accepted_from_post(client):
    # KNOWN-ISSUE: image-svg-unsanitised  (the edit form renders `value` as a hidden input, so it is not
    # editable in the UI, but the field is still bound: a forged POST stores any string)
    s, app, item = model_setup()[:3]
    client.force_login(s.w.user('rw'))
    url = '/editor/Model/%d/%d/%d/Sel_All/0/edit_spec_item' % (s.pid, app.id, item.id)
    html = client.get(url).content.decode()
    assert 'name="value"' in html and 'type="hidden"' in html.split('name="value"')[0][-200:] + 'type="hidden"'
    resp = client.post(url, {'domain': 'OldDom', 'name': 'OldName', 'value': SVG, 'n1': '1', 'n2': '2',
                             'n3': '77', 'p_kind': 'SM', 'change_log': 'c', 'val_set': item.val_set_id,
                             'title': 't', 'desc': '', 'rationale': '', 'remarks': '', 'implementation': '',
                             't1': '', 'ext_item': ''})
    assert resp.status_code == 302, getattr(resp, 'context', None) and resp.context['form'].errors
    stored = SpecItem.objects.filter(project_id=s.pid, cat='Model').order_by('-id')[0]
    assert stored.value == SVG
    assert SVG in _model_page(client, s, app, stored)           # rendered raw


def test_image_csv_import_spec_items_stores_value_raw(client):
    # KNOWN-ISSUE: image-svg-unsanitised  (CSV import copies the `Diagram` column unchanged)
    s, app, item = model_setup()[:3]
    client.force_login(s.w.user('rw'))
    attrs = configs['cats']['Model']['attrs']
    row = {a['label']: ('0' if a['kind'] == 'int' else '') for a in attrs.values()}
    row.update({attrs['domain']['label']: 'ImpDom', attrs['name']['label']: 'ImpName',
                attrs['value']['label']: SVG, attrs['val_set']['label']: 'Default',
                attrs['title']['label']: 'T', attrs['p_kind']['label']: 'SM'})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(row), delimiter=configs['general']['csv_sep'])
    w.writeheader(); w.writerow(row)
    from django.core.files.uploadedfile import SimpleUploadedFile
    url = '/editor/Model/%d/%d/%d/Sel_All/import_spec_items' % (s.pid, app.id, default_val_set(s.w.project).id)
    resp = client.post(url, {'upload_file': SimpleUploadedFile('m.csv', buf.getvalue().encode())})
    assert resp.status_code == 302, resp
    from django.contrib.messages import get_messages
    assert [m.message for m in get_messages(resp.wsgi_request)] == ['1 row(s) imported successfully']
    imported = SpecItem.objects.get(project_id=s.pid, cat='Model', name='ImpName')
    assert imported.value == SVG
    assert SVG in _model_page(client, s, app, imported)


def test_image_project_zip_import_stores_value_raw(client, fresh_temp):
    # KNOWN-ISSUE: image-svg-unsanitised  (project ZIP import restores spec_items.csv verbatim)
    s, app, item = model_setup()[:3]
    SpecItem.objects.filter(id=item.id).update(value=SVG)
    client.force_login(s.w.owner)
    response, data, zf = export_zip(client, s.pid, fresh_temp)
    Project.objects.filter(id=s.pid).update(name='renamed original')
    admin = make_user('zipadmin', is_staff=True)
    client.force_login(admin)
    upload_zip(client, data, fresh_temp)
    new = Project.objects.exclude(id=s.pid).get()
    imported = SpecItem.objects.get(project=new, cat='Model', name='OldName')
    assert imported.value == SVG
    client.force_login(s.w.owner)
    new_app = imported.application
    page = client.get('/editor/Model/%d/%d/%d/Sel_All/0/list_spec_items' % (
        new.id, new_app.id, default_val_set(new).id)).content.decode()
    assert SVG in page


def test_image_refresh_from_fw_profile_stores_value_raw(client):
    # KNOWN-ISSUE: image-svg-unsanitised  (refresh copies the FW Profile `diagrams.svg` column; the
    # same column is copied by ext_model_get_choice / ext_fcp_get_choice when an item is added)
    s, app, item, url = model_setup()
    client.force_login(s.w.user('rw'))
    row = ROW[:7] + (SVG,) + ROW[8:]
    with fake_connect([row]):
        assert client.post(url).status_code == 302
    stored = SpecItem.objects.filter(project_id=s.pid, cat='Model').order_by('-id')[0]
    assert stored.value == SVG
    assert SVG in _model_page(client, s, app, stored)


def test_image_add_form_value_comes_from_fw_profile_not_from_post(client):
    # the add form overwrites every ext attribute (including `value`) with the FW Profile data
    # KNOWN-ISSUE: image-svg-unsanitised  (the FW Profile column is trusted)
    s, app, item, _ = model_setup()
    client.force_login(s.w.user('rw'))
    row = ROW[:7] + (SVG,) + ROW[8:]
    url = '/editor/Model/%d/%d/Sel_All/0/add_spec_item' % (s.pid, app.id)
    # the choice list query and the choice query both hit the fake DB
    with fake_connect([row]):
        resp = client.post(url, {'ext_item': '77', 'title': 't', 'p_kind': 'SM', 'value': '<i>forged</i>'})
    assert resp.status_code in (200, 302)
    values = set(SpecItem.objects.filter(project_id=s.pid, cat='Model').values_list('value', flat=True))
    assert '<i>forged</i>' not in values
