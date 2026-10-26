"""
Characterization tests for editor/convert.py, editor/markdown.py and
editor/templatetags/ref_filters.py (real cexprtk, no mocks).
"""
import logging
from datetime import datetime, timezone

import pytest
from django.utils.safestring import SafeString

from editor import convert
from editor.configs import configs
from editor.convert import (frmt_string, convert_db_to_display, convert_edit_to_db,
                            convert_exp_to_db, convert_db_to_edit, convert_db_to_latex,
                            conv_do_nothing, conv_db_disp_plain_ref, conv_db_disp_date,
                            conv_db_disp_ref_text, conv_db_disp_table,
                            conv_db_disp_spec_item_ref, conv_db_disp_eval_ref,
                            render_for_eval, eval_di_value, get_pattern_edit)
from editor.markdown import markdown_to_html, markdown_to_latex
from editor.templatetags import ref_filters
from tests.factories import make_user, make_project, make_spec_item, make_release, make_application

pytestmark = pytest.mark.django_db

CATS = 'DataItem,EnumType,EnumValue,DataItemType,VerLink,Packet,DerPacket,PacketPar,Service'


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def convert_log():
    """Capture records of the editor.convert logger directly (the app logger does not propagate)."""
    handler = _ListHandler()
    lg = logging.getLogger('editor.convert')
    lg.addHandler(handler)
    yield handler.messages
    lg.removeHandler(handler)


@pytest.fixture
def world():
    """Deterministic project with a few items; ids are small and predictable (fresh DB per test)."""
    owner = make_user()
    project = make_project(owner, cats=CATS)
    etype = make_spec_item(project, 'EnumType', 'D', 'T1', status='CNF', title='t', desc='d <&>')
    n1 = make_spec_item(project, 'DataItem', 'D', 'x', status='NEW', p_link=etype, value='2*3')
    n2 = make_spec_item(project, 'DataItem', 'D', 'y', status='CNF', p_link=etype,
                        value='#iref:%d+1' % n1.id)
    return dict(owner=owner, project=project, etype=etype, x=n1, y=n2)


# ---------------------------------------------------------------- frmt_string
@pytest.mark.parametrize('src,expected', [
    ('plain', 'plain'),
    ('', ''),
    ('a\r\nb', 'a \\newline b'),
    ('a\rb', 'a \\newline b'),
    ('a\nb', 'a \\newline b'),
    ('50%', '50\\%'),
    ('a&b', 'a\\&b'),
    ('#x', '\\#x'),
    ('a^b', 'a\\textasciicircum b'),
    ('a~b', 'a\\textasciitilde b'),
    ('a_b', 'a\\_b'),
    ('a\r\nb\rc\nd%&#^~_', 'a \\newline b \\newline c \\newline d\\%\\&\\#\\textasciicircum \\textasciitilde \\_'),
    ('{}$\\', '{}$\\'),            # braces, dollar and backslash are NOT escaped
    ('caf\u00e9 \u20ac', 'caf\u00e9 \u20ac'),
])
def test_frmt_string(src, expected):
    assert frmt_string(src) == expected


# ------------------------------------------------------------------ markdown
@pytest.mark.parametrize('src,html,latex', [
    ('**b**', '<b>b</b>', '\\textbf{b}'),
    ('++u++', '<u>u</u>', '\\underline{u}'),
    ('__i__', '<i>i</i>', '\\textit{i}'),
    ('``code``', '<code>code</code>', '\\texttt{code}'),
    ('**b** ++u++ __i__ ``c``', '<b>b</b> <u>u</u> <i>i</i> <code>c</code>',
     '\\textbf{b} \\underline{u} \\textit{i} \\texttt{c}'),
    # nesting is not supported: inner markers are left untouched
    ('**a ++b++ c**', '<b>a ++b++ c</b>', '\\textbf{a ++b++ c}'),
    # emphasis does not span lines
    ('**a\nb**', '**a\nb**', '**a\nb**'),
    ('x ** y', 'x ** y', 'x ** y'),
    ('plain', 'plain', 'plain'),
    ('', '', ''),
    # bullets: the list must be preceded by a newline
    ('a\n- x\n- y\nb', 'a<ul><li>x</li><li>y</li></ul>\nb',
     'a\\begin{itemize}\\item x\\item y\\end{itemize} \\ \nb'),
    ('a\r\n- x\r\n- y\r\nz', 'a\r<ul><li>x</li><li>y</li></ul>\nz',
     'a\r\\begin{itemize}\\item x\\item y\\end{itemize} \\ \nz'),
    # a list that starts at the very beginning of the text loses its first item (not a bullet)
    ('- x\n- y', '- x<ul><li>y</li></ul>', '- x\\begin{itemize}\\item y\\end{itemize} \\ '),
    ('- a **b**\n- c', '- a <b>b</b><ul><li>c</li></ul>',
     '- a \\textbf{b}\\begin{itemize}\\item c\\end{itemize} \\ '),
    ('t\n- a **b**\n- c', 't<ul><li>a <b>b</b></li><li>c</li></ul>',
     't\\begin{itemize}\\item a \\textbf{b}\\item c\\end{itemize} \\ '),
    # no escaping whatsoever in the markdown functions themselves (LaTeX part and nesting stay open, track K).
    # md-no-escape HTML part FIXED in Task 6.6: markdown_to_html receives text already escaped by
    # convert_db_to_display (its only caller), see tests/test_escaping_6_6.py
    # KNOWN-ISSUE: md-no-escape
    ('<script>alert(1)</script> <b>&"x</b>', '<script>alert(1)</script> <b>&"x</b>',
     '<script>alert(1)</script> <b>&"x</b>'),
    ('**<i>x</i>**', '<b><i>x</i></b>', '\\textbf{<i>x</i>}'),
    ('\u00fc **\u00e9**', '\u00fc <b>\u00e9</b>', '\u00fc \\textbf{\u00e9}'),
])
def test_markdown(src, html, latex):
    assert markdown_to_html(src) == html
    assert markdown_to_latex(src) == latex


def test_markdown_bullet_item_with_hyphen_splits():
    # an item containing '- ' is split in two <li> elements
    assert markdown_to_html('t\n- a - b') == 't<ul><li>a </li><li>b</li></ul>'


# ------------------------------------------------------- convert_db_to_display
def test_display_internal_ref_cnf_and_new(world):
    e, x = world['etype'], world['x']
    out = convert_db_to_display('hi #iref:%d and #iref:%d' % (e.id, x.id), None)
    # KNOWN-ISSUE: ref-link-backslash  (target uses '\list_spec_items' with a backslash instead of '/')
    assert out == (
        'hi <a href="/editor/EnumType/%d/0/%d/D/0\\list_spec_items#D:T1" '
        'title="Title: t&#13;Description: d &lt;&amp;&gt;&#13;">D:T1</a> and '
        '<a href="/editor/DataItem/%d/0/%d/D/0\\list_spec_items#D:x" class="link-danger" '
        'title="Status: NEW&#13;Title: Title of x&#13;Description: &#13;Value: 2*3&#13;">D:x</a>'
        % (world['project'].id, e.val_set_id, world['project'].id, x.val_set_id))


@pytest.mark.parametrize('status', ['NEW', 'MOD', 'DEL'])
def test_display_link_danger_for_status(world, status):
    item = make_spec_item(world['project'], 'DataItem', 'D', 'st_' + status, status=status,
                          p_link=world['etype'])
    out = convert_db_to_display('#iref:%d' % item.id, None)
    assert 'class="link-danger"' in out
    assert 'title="Status: %s&#13;' % status in out


@pytest.mark.parametrize('status', ['CNF', 'OBS'])
def test_display_no_danger_for_other_status(world, status):
    item = make_spec_item(world['project'], 'DataItem', 'D', 'st_' + status, status=status,
                          p_link=world['etype'])
    out = convert_db_to_display('#iref:%d' % item.id, None)
    assert 'link-danger' not in out
    assert 'Status:' not in out


def test_display_missing_ref_and_markdown():
    assert convert_db_to_display('a #iref:9999 **x**', None) == 'a ERROR:9999 <b>x</b>'


def test_display_sel_rel_id_in_link(world):
    rel = make_release(world['owner'])
    out = convert_db_to_display('#iref:%d' % world['etype'].id, rel)
    assert '/D/%d\\list_spec_items' % rel.id in out


def test_display_application_id_in_link(world):
    app = make_application(world['project'], cats='DataItem')
    item = make_spec_item(world['project'], 'DataItem', 'D', 'appitem', application=app,
                          p_link=world['etype'])
    out = convert_db_to_display('#iref:%d' % item.id, None)
    assert '/editor/DataItem/%d/%d/' % (world['project'].id, app.id) in out


def test_display_html_special_chars_in_names_escaped_but_text_not(world):
    # FIXED: xss-display (was: '<script>x</script> & <b>' returned raw)
    out = convert_db_to_display('<script>x</script> & <b>', None)
    assert out == '&lt;script&gt;x&lt;/script&gt; &amp; &lt;b&gt;'


def test_display_ref_escapes_domain_name_title(world):
    item = make_spec_item(world['project'], 'EnumType', 'D', 'q', status='CNF',
                          title='<i>t</i>', desc='"q"')
    out = convert_db_to_display('#iref:%d' % item.id, None)
    assert 'Title: &lt;i&gt;t&lt;/i&gt;&#13;Description: &quot;q&quot;&#13;' in out


# ------------------------------------------------------------ edit/db/latex
def test_convert_edit_to_db(world, convert_log):
    e, x = world['etype'], world['x']
    out = convert_edit_to_db(world['project'], '#DataItem:D:x #DataItem:D:zz #EnumType:D:T1.')
    assert out == '#iref:%d #DataItem:D:zz #iref:%d.' % (x.id, e.id)
    assert convert_log == ['Non-existent internal reference: #DataItem:D:zz']


def test_convert_edit_to_db_unmatched_category_untouched(world):
    # 'Requirement' is not a category of the project: pattern does not match
    s = '#Requirement:D:x #foo:bar:baz'
    assert convert_edit_to_db(world['project'], s) == s


def test_convert_edit_to_db_ignores_deleted_and_obsolete(world):
    make_spec_item(world['project'], 'DataItem', 'D', 'gone', status='DEL', p_link=world['etype'])
    make_spec_item(world['project'], 'DataItem', 'D', 'old', status='OBS', p_link=world['etype'])
    assert convert_edit_to_db(world['project'], '#DataItem:D:gone #DataItem:D:old') == \
        '#DataItem:D:gone #DataItem:D:old'


def test_convert_edit_to_db_dotted_identifiers(world):
    item = make_spec_item(world['project'], 'DataItem', 'a.b', 'c.d', status='CNF', p_link=world['etype'])
    assert convert_edit_to_db(world['project'], '#DataItem:a.b:c.d') == '#iref:%d' % item.id


def test_convert_edit_to_db_case_sensitivity_and_trailing_dot(world):
    # the regex does not capture a trailing dot
    item = world['x']
    assert convert_edit_to_db(world['project'], 'see #DataItem:D:x.') == 'see #iref:%d.' % item.id


def test_convert_edit_to_db_unicode_and_html(world):
    s = '<b>\u00fc & \u20ac</b> #DataItem:D:x'
    assert convert_edit_to_db(world['project'], s) == '<b>\u00fc & \u20ac</b> #iref:%d' % world['x'].id


def test_convert_db_to_edit(world):
    e = world['etype']
    assert convert_db_to_edit('#iref:%d #iref:999' % e.id) == '#EnumType:D:T1 ERROR:999'
    assert convert_db_to_edit('') == ''
    assert convert_db_to_edit('<b>\u00fc</b>') == '<b>\u00fc</b>'


def test_round_trip_edit_db_edit(world):
    s = 'a #DataItem:D:x b #EnumType:D:T1 c'
    assert convert_db_to_edit(convert_edit_to_db(world['project'], s)) == s


def test_round_trip_unknown_ref_kept(world):
    s = 'a #DataItem:D:nope'
    assert convert_db_to_edit(convert_edit_to_db(world['project'], s)) == s


def test_convert_exp_to_db(world):
    p = world['project']
    assert convert_exp_to_db(p, 'D:x') == world['x']
    assert convert_exp_to_db(p, 'D:x (some title)') == world['x']
    assert convert_exp_to_db(p, '') is None
    assert convert_exp_to_db(p, 'nocolon') is None
    assert convert_exp_to_db(p, 'D:missing') is None


def test_convert_exp_to_db_dotted_or_dashed_names_not_supported(world):
    # KNOWN-ISSUE: exp-ref-no-dots  (pattern_ref_exp has no '.'/'-': such references resolve to None)
    make_spec_item(world['project'], 'DataItem', 'a.b', 'c', status='CNF', p_link=world['etype'])
    make_spec_item(world['project'], 'DataItem', 'a-b', 'c', status='CNF', p_link=world['etype'])
    assert convert_exp_to_db(world['project'], 'a.b:c') is None
    assert convert_exp_to_db(world['project'], 'a-b:c') is None


def test_convert_exp_to_db_ambiguous_returns_none(world):
    # same domain:name in two categories -> MultipleObjectsReturned swallowed
    make_spec_item(world['project'], 'EnumType', 'D', 'x', status='CNF')
    assert convert_exp_to_db(world['project'], 'D:x') is None


def test_convert_db_to_latex(world):
    e = world['etype']
    assert convert_db_to_latex('#iref:%d_& 50%% **x** 9 #iref:999' % e.id) == \
        'D:T1\\_\\& 50\\% \\textbf{x} 9 ERROR:999'
    # markdown conversion happens before escaping: '__i__' -> \textit{i}, then remaining '_' escaped
    assert convert_db_to_latex('__i__ a_b') == '\\textit{i} a\\_b'


def test_convert_db_to_latex_bullets_exact():
    out = convert_db_to_latex('t\n- a\n- b')
    assert out == 't\\begin{itemize}\\item a\\item b\\end{itemize} \\ '


def test_convert_db_to_latex_no_escape_of_html_and_unicode():
    assert convert_db_to_latex('<b>&</b> \u00fc') == '<b>\\&</b> \u00fc'


def test_pattern_edit_depends_on_project(world):
    pat = get_pattern_edit(world['project'].id)
    assert pat.match('#DataItem:D:x')
    assert pat.match('#Requirement:D:x') is None


# ------------------------------------------------------------ conv_* functions
def _ctx(world, sel_rel=None):
    return {'application_id': 0, 'default_val_set_id': world['x'].val_set_id,
            'sel_val': 'Sel_All', 'sel_rel': sel_rel,
            'config': configs['cats']['DataItem']}


def test_conv_do_nothing_and_plain_ref(world):
    x = world['x']
    assert conv_do_nothing({}, x, 'name', None) == 'x'
    assert conv_do_nothing({}, x, 'n1', None) == 0
    assert conv_db_disp_plain_ref({}, x, 'n1', None) == '0'
    assert conv_db_disp_plain_ref({}, x, 'owner', None) == 'alice'


def test_conv_db_disp_date_name_error():
    # KNOWN-ISSUE: conv-date-nameerror  (body returns undefined name 's')
    with pytest.raises(NameError):
        conv_db_disp_date({}, None, 'x', None)


def test_conv_db_disp_ref_text(world):
    item = make_spec_item(world['project'], 'DataItem', 'D', 'rt', p_link=world['etype'],
                          desc='see #iref:999 **b**')
    assert conv_db_disp_ref_text({}, item, 'desc', None) == 'see ERROR:999 <b>b</b>'


def test_conv_db_disp_table(world):
    item = make_spec_item(world['project'], 'DataItem', 'D', 'tb', p_link=world['etype'],
                          s_data={'a': 1})
    assert conv_db_disp_table({}, item, 's_data', None) == "{'a': 1}"


def test_conv_db_disp_spec_item_ref_none(world):
    assert conv_db_disp_spec_item_ref(_ctx(world), world['etype'], 'p_link', None) == ''


def test_conv_db_disp_spec_item_ref_cnf_and_new(world):
    ctx = _ctx(world)
    pid = world['project'].id
    vs = world['x'].val_set_id
    out = conv_db_disp_spec_item_ref(ctx, world['x'], 'p_link', None)
    # target is CNF EnumType (project level)
    assert out == ('<a href="/editor/EnumType/%d/0/%d/D/0/list_spec_items#D:T1" '
                   'title="Title: t&#13;Description: d &lt;&amp;&gt;&#13;">D:T1</a>' % (pid, vs))
    world['etype'].status = 'MOD'
    world['etype'].save()
    world['x'].refresh_from_db()
    out = conv_db_disp_spec_item_ref(ctx, world['x'], 'p_link', None)
    assert out == ('<a href="/editor/EnumType/%d/0/%d/D/0/list_spec_items#D:T1" class="link-danger" '
                   'title="Status: MOD&#13;Title: t&#13;Description: d &lt;&amp;&gt;&#13;">D:T1</a>' % (pid, vs))


def test_conv_db_disp_spec_item_ref_application_level_and_release(world):
    app = make_application(world['project'], cats='Requirement')
    req = make_spec_item(world['project'], 'Requirement', 'R', 'r1', status='CNF', application=app,
                         value='v')
    tl = make_spec_item(world['project'], 'VerLink', 'V', 'l1', status='CNF', s_link=req)
    rel = make_release(world['owner'])
    ctx = _ctx(world)
    ctx['application_id'] = app.id
    out = conv_db_disp_spec_item_ref(ctx, tl, 's_link', rel)
    assert out == ('<a href="/editor/Requirement/%d/%d/%d/R/%d/list_spec_items#R:r1" '
                   'title="Title: Title of r1&#13;Text: v&#13;">R:r1</a>'
                   % (world['project'].id, app.id, world['x'].val_set_id, rel.id))


def test_conv_db_disp_eval_ref(world):
    x, y = world['x'], world['y']
    # no references: value returned unchanged (no evaluation)
    assert conv_db_disp_eval_ref({}, x, 'value', None) == '2*3'
    # with references: display + ' = ' + evaluated value
    out = conv_db_disp_eval_ref({}, y, 'value', None)
    assert out.endswith('</a>+1 = 7.0')
    assert out.startswith('<a href="/editor/DataItem/')


def test_conv_db_disp_eval_ref_unevaluable(world):
    item = make_spec_item(world['project'], 'DataItem', 'D', 'bad', p_link=world['etype'],
                          value='#iref:%d+' % world['x'].id)
    out = conv_db_disp_eval_ref({}, item, 'value', None)
    assert out.endswith('</a>+ = #iref:%d+' % world['x'].id)


# ------------------------------------------------------- render_for_eval / eval
def test_eval_di_value_real_cexprtk(world):
    assert eval_di_value('2*(3+4)') == '14.0'
    assert eval_di_value('10/4') == '2.5'
    assert eval_di_value('1e3') == '1000.0'
    assert eval_di_value('sqrt(16)') == '4.0'
    assert isinstance(eval_di_value('1+1'), str)


def test_eval_di_value_invalid_returns_input():
    assert eval_di_value('2+') == '2+'
    assert eval_di_value('abc') == 'abc'
    assert eval_di_value('') == ''


def test_eval_di_value_resolves_references(world):
    x, y = world['x'], world['y']
    assert eval_di_value('#iref:%d' % x.id) == '6.0'
    # no parentheses are added around the substituted value: 2*3+1*2 = 8
    assert eval_di_value('#iref:%d*2' % y.id) == '8.0'
    assert eval_di_value('#iref:%d+#iref:%d' % (x.id, y.id)) == '13.0'  # 6 + 7


def test_eval_di_value_missing_reference_returns_input():
    assert eval_di_value('#iref:9999+1') == '#iref:9999+1'


def test_render_for_eval_substitutes_without_evaluating(world):
    assert render_for_eval('#iref:%d+1' % world['y'].id, 1) == '2*3+1+1'
    assert render_for_eval('plain', 1) == 'plain'
    assert render_for_eval('#iref:9999', 1) == '#iref:9999'


def test_render_for_eval_max_depth(world, monkeypatch, convert_log):
    loop = make_spec_item(world['project'], 'DataItem', 'D', 'loop', p_link=world['etype'], value='1')
    loop.value = '#iref:%d+1' % loop.id
    loop.save()
    monkeypatch.setitem(convert.configs['general'], 'max_depth', 3)
    out = render_for_eval(loop.value, 1)
    # depths 1..3 substitute the value; at depth 4 the reference is returned unchanged
    assert out == '#iref:%d+1+1+1+1' % loop.id
    assert convert_log == ['Exceeded recursion depth when evaluating #iref:%d+1' % loop.id]


def test_render_for_eval_max_depth_exact(world, monkeypatch):
    loop = make_spec_item(world['project'], 'DataItem', 'D', 'loop', p_link=world['etype'], value='1')
    loop.value = 'A#iref:%d' % loop.id
    loop.save()
    monkeypatch.setitem(convert.configs['general'], 'max_depth', 2)
    out = render_for_eval(loop.value, 1)
    # n=1 -> item.value rendered at n=2 -> rendered at n=3 (>2) returned unchanged
    assert out == 'AAA#iref:%d' % loop.id


def test_eval_di_value_cyclic_reference_terminates(world):
    loop = make_spec_item(world['project'], 'DataItem', 'D', 'loop', p_link=world['etype'], value='1')
    loop.value = '#iref:%d+1' % loop.id
    loop.save()
    assert eval_di_value(loop.value) == loop.value


# ------------------------------------------------------------- ref_filters
def _tag_ctx(world, sel_rel=None, cat='DataItem'):
    return {'sel_rel': sel_rel, 'config': configs['cats'][cat], 'application_id': 0,
            'default_val_set_id': world['x'].val_set_id, 'sel_val': 'Sel_All'}


def test_ref_filters_conv_db_disp_func_table_matches_convert():
    for func in ref_filters.conv_db_disp_func.values():
        assert hasattr(convert, func) or func == 'conv_db_disp_eval_ref'
    assert ref_filters.conv_db_disp_func['date'] == 'conv_db_disp_date'


def test_tag_conv_db_disp(world):
    y = world['y']
    out = ref_filters.conv_db_disp(_tag_ctx(world), y, ['domain', 'name', 'title', 'desc', 'value', 'p_link'])
    labels = [o[0] for o in out]
    # 'desc' is empty -> skipped
    assert labels == ['Domain', 'Name', 'Title', 'Value', 'Type']
    assert out[0] == ('Domain', 'D')
    assert out[1] == ('Name', 'y')
    assert all(isinstance(o[1], SafeString) for o in out)
    assert out[3][1].endswith('</a>+1 = 7.0')
    assert out[4][1].startswith('<a href="/editor/EnumType/')


def test_tag_conv_db_disp_mark_safe_does_not_escape(world):
    # FIXED: xss-tag (was: values marked safe without escaping, out == [('Title', '<script>1</script>')])
    item = make_spec_item(world['project'], 'DataItem', 'D', 'xss', p_link=world['etype'],
                          title='<script>1</script>')
    out = ref_filters.conv_db_disp(_tag_ctx(world), item, ['title'])
    assert out == [('Title', '&lt;script&gt;1&lt;/script&gt;')]
    assert isinstance(out[0][1], SafeString)


def test_tag_conv_db_disp_int_attr(world):
    item = make_spec_item(world['project'], 'EnumType', 'D', 'e2', n1=0)
    out = ref_filters.conv_db_disp(_tag_ctx(world, cat='EnumType'), item, ['n1'])
    # int 0 != '' so it is kept; mark_safe stringifies it
    assert out == [('Size', '0')]


def test_disp_trac_s_link(world):
    p = world['project']
    pkt = make_spec_item(p, 'Packet', 'P', 'pk', status='CNF', p_kind='TC', title='PT', desc='PD')
    req = make_spec_item(p, 'Service', 'S', 'sv', status='CNF', title='ST', desc='SD')
    link = make_spec_item(p, 'VerLink', 'V', 'l', status='CNF', s_link=pkt, p_link=req)
    out = ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None)
    assert out == ('<a class="link-table-list-spec" href="/editor/Service/%d/0/%d/S/0\\list_spec_items#S:sv" '
                   'title="SD">S:sv</a> (ST)' % (p.id, pkt.val_set_id))
    assert isinstance(out, SafeString)


def test_disp_trac_p_link_branch(world):
    p = world['project']
    req = make_spec_item(p, 'Service', 'S', 'sv', status='CNF', title='ST', desc='SD')
    pkt = make_spec_item(p, 'Packet', 'P', 'pk', status='CNF', p_kind='TC', title='PT', desc='PD')
    link = make_spec_item(p, 'VerLink', 'V', 'l', status='CNF', s_link=pkt, p_link=req)
    out = ref_filters.disp_trac(_tag_ctx(world), req, 'VerLink', 'p_link', None)
    assert out == ('<a class="link-table-list-spec" href="/editor/Packet/%d/0/%d/P/0\\list_spec_items#P:pk" '
                   'title="PD">P:pk</a> (PT)' % (p.id, req.val_set_id))


def test_disp_trac_excludes_del_obs_without_release_and_joins_lines(world):
    p = world['project']
    pkt = make_spec_item(p, 'Packet', 'P', 'pk', status='CNF', p_kind='TC')
    for n, st in (('a', 'CNF'), ('b', 'NEW'), ('c', 'DEL'), ('d', 'OBS')):
        r = make_spec_item(p, 'Service', 'S', n, status='CNF')
        make_spec_item(p, 'VerLink', 'V', 'l' + n, status=st, s_link=pkt, p_link=r)
    out = ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None)
    assert out.count('\n') == 1       # two lines: a (CNF) and b (NEW)
    assert 'S:a' in out and 'S:b' in out and 'S:c' not in out and 'S:d' not in out
    assert not out.endswith('\n')


def test_disp_trac_empty_returns_empty_string(world):
    pkt = make_spec_item(world['project'], 'Packet', 'P', 'pk', status='CNF', p_kind='TC')
    assert ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None) == ''


def test_disp_trac_with_release_filters_by_dates(world):
    p = world['project']
    rel = make_release(world['owner'], updated_at=datetime(2024, 1, 20, tzinfo=timezone.utc))
    pkt = make_spec_item(p, 'Packet', 'P', 'pk', status='CNF', p_kind='TC')
    ok = make_spec_item(p, 'Service', 'S', 'ok', status='CNF')
    late = make_spec_item(p, 'Service', 'S', 'late', status='CNF')
    new = make_spec_item(p, 'Service', 'S', 'new', status='CNF')
    make_spec_item(p, 'VerLink', 'V', 'l1', status='CNF', s_link=pkt, p_link=ok)
    make_spec_item(p, 'VerLink', 'V', 'l2', status='CNF', s_link=pkt, p_link=late,
                   created_at=datetime(2024, 2, 1, tzinfo=timezone.utc))
    make_spec_item(p, 'VerLink', 'V', 'l3', status='NEW', s_link=pkt, p_link=new)
    make_spec_item(p, 'VerLink', 'V', 'l4', status='CNF', s_link=pkt, p_link=new,
                   updated_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
    out = ref_filters.disp_trac(_tag_ctx(world, rel), pkt, 'VerLink', 's_link', rel)
    assert 'S:ok' in out and 'S:late' not in out and 'S:new' not in out
    assert '/S/%d\\list_spec_items' % rel.id in out


def test_disp_trac_p_link_none_crash(world):
    # KNOWN-ISSUE: disp-trac-plink-none  (link.p_link.application_id is evaluated before the None check)
    p = world['project']
    pkt = make_spec_item(p, 'Packet', 'P', 'pk', status='CNF', p_kind='TC')
    make_spec_item(p, 'VerLink', 'V', 'l', status='CNF', s_link=pkt, p_link=None)
    with pytest.raises(AttributeError):
        ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None)


def test_disp_trac_application_id(world):
    p = world['project']
    app = make_application(p, cats='Requirement')
    pkt = make_spec_item(p, 'Packet', 'P', 'pk', status='CNF', p_kind='TC')
    req = make_spec_item(p, 'Requirement', 'R', 'r', status='CNF', application=app)
    make_spec_item(p, 'VerLink', 'V', 'l', status='CNF', s_link=pkt, p_link=req)
    out = ref_filters.disp_trac(_tag_ctx(world), pkt, 'VerLink', 's_link', None)
    assert '/editor/Requirement/%d/%d/' % (p.id, app.id) in out


def test_filter_expand_tip(world):
    x = world['x']
    # expand_tip of DataItem: title, desc, value ; refs converted to edit format; escaped (Task 6.6)
    item = make_spec_item(world['project'], 'DataItem', 'D', 'tip', p_link=world['etype'],
                          desc='see #iref:%d <b>' % world['etype'].id, value='1')
    out = ref_filters.filter_expand_tip(item)
    assert out == 'Title: Title of tip&#13;Description: see #EnumType:D:T1 &lt;b&gt;&#13;Value: 1&#13;'
    assert isinstance(out, SafeString)


def test_filter_get_dict_item():
    assert ref_filters.get_dict_item({'a': 1}, 'a') == 1
    assert ref_filters.get_dict_item({'a': 1}, 'b') is None


def test_filter_get_model_field(world):
    assert ref_filters.get_model_field(world['x'], 'name') == 'x'
    with pytest.raises(AttributeError):
        ref_filters.get_model_field(world['x'], 'nonexistent')


def test_filter_get_label():
    assert ref_filters.get_label(configs['cats']['DataItem']['attrs'], 'p_link') == 'Type'
    with pytest.raises(KeyError):
        ref_filters.get_label(configs['cats']['DataItem']['attrs'], 'zzz')


def test_filter_get_short_desc(world):
    x = world['x']       # expand_text = [title, desc]
    # desc is empty: 'Title of x: ' + '' + ': ' with the last two chars cut
    assert ref_filters.get_short_desc(x) == 'Title of x: '


def test_filter_get_short_desc_truncation(world):
    long = make_spec_item(world['project'], 'DataItem', 'D', 'long', p_link=world['etype'],
                          title='T' * 60, desc='d' * 60)
    out = ref_filters.get_short_desc(long)
    # desc = 'TTT..: ddd..: ' is 126 chars (> short_desc_len 100): cut at 100 and ' ...' appended
    assert out == ('T' * 60 + ': ' + 'd' * 38) + ' ...'
    assert len(out) == 104


def test_filter_get_short_desc_boundary(world):
    # exactly 100 chars of desc incl. the trailing ': ' separators is NOT truncated
    item = make_spec_item(world['project'], 'DataItem', 'D', 'b', p_link=world['etype'],
                          title='T' * 48, desc='d' * 48)   # 48+2+48+2 = 100
    out = ref_filters.get_short_desc(item)
    assert out == 'T' * 48 + ': ' + 'd' * 48
