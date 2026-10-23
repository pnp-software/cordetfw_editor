"""
Security audit (Task 6.2): characterization tests for the findings of the S1 audit.

Every test pins the CURRENT behaviour, including the insecure one, and carries a
`# KNOWN-ISSUE: <id>` marker (see docs/migration/known-issues/security-audit.md and
docs/fixes/register.md). Tests without a marker pin behaviour that was checked and is safe.

World: two projects A and B with different owners. The attackers are members of A only:
  ro_a - RO member of A     rw_a - RW member of A
  outsider - logged in, no membership     staff - is_staff, no membership
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.core.validators import validate_email
from django.db.models import ProtectedError
from django.test import Client

from editor.models import Project, ProjectUser, SpecItem, ValSet
from tests.factories import (FIXED_TIME, default_val_set, make_application, make_project,
                             make_project_user, make_spec_item, make_user, make_val_set)

pytestmark = pytest.mark.django_db

REPO_ROOT = Path(__file__).resolve().parents[1]
CATS = 'DataItem,EnumType,EnumValue,DataItemType,Requirement,Model,InfoItem'


def msgs(resp):
    return [m.message for m in get_messages(resp.wsgi_request)]


class World:
    def __init__(self):
        self.owner_a = make_user('owner_a')
        self.owner_b = make_user('owner_b')
        self.ro_a = make_user('ro_a')
        self.rw_a = make_user('rw_a')
        self.outsider = make_user('outsider')
        self.staff = make_user('staff', is_staff=True)
        self.a = make_project(self.owner_a, 'ProjA', cats=CATS)
        self.b = make_project(self.owner_b, 'ProjB', cats=CATS, desc='Secret B description')
        make_project_user(self.a, self.ro_a, 'RO')
        make_project_user(self.a, self.rw_a, 'RW')
        self.dvs_a = default_val_set(self.a)
        self.dvs_b = default_val_set(self.b)
        self.app_a = make_application(self.a, 'AppA', cats='Requirement,Model')
        self.app_b = make_application(self.b, 'AppB', cats='Requirement,Model')
        # project-level items of B
        self.b_type = make_spec_item(self.b, cat='DataItemType', domain='BT', name='BInt',
                                     title='B secret type', desc='B type desc', n1=4, status='CNF')
        self.b_di = make_spec_item(self.b, cat='DataItem', domain='BD', name='BItem', title='B secret title',
                                   desc='B secret desc', value='42', p_link=self.b_type, p_kind='CNS',
                                   status='CNF')
        # application-level item of B
        self.b_req = make_spec_item(self.b, cat='Requirement', domain='BR', name='BReq', application=self.app_b,
                                    title='B secret requirement', value='B requirement text', p_kind='FUN',
                                    s_kind='TST', status='CNF')
        # A has its own type so that A forms validate
        self.a_type = make_spec_item(self.a, cat='DataItemType', domain='AT', name='AInt', title='A type', n1=4)

    def client(self, user, csrf=False):
        c = Client(enforce_csrf_checks=csrf)
        c.force_login(user)
        return c


@pytest.fixture
def w():
    return World()


def lurl(cat, project_id, app_id, vs_id, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/list_spec_items' % (cat, project_id, app_id, vs_id, sel_val, rel)


def eurl(cat, project_id, app_id, vs_id, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/export_spec_items' % (cat, project_id, app_id, vs_id, sel_val, rel)


def iurl(view, cat, project_id, item_id, app_id=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/%s' % (cat, project_id, app_id, item_id, sel_val, rel, view)


def aurl(cat, project_id, app_id=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%s/%d/add_spec_item' % (cat, project_id, app_id, sel_val, rel)


def listed(resp):
    return [(i.domain, i.name) for i in resp.context['page_items']]


# ---------------------------------------------------------------------------------------------
# 1 idor-app-valset-cross-project
# ---------------------------------------------------------------------------------------------

def test_01_idor_app_valset_cross_project_list(w):
    # KNOWN-ISSUE: idor-app-valset-cross-project
    c = w.client(w.ro_a)
    resp = c.get(lurl('Requirement', w.a.id, w.app_b.id, w.dvs_b.id))
    assert resp.status_code == 200
    assert listed(resp) == [('BR', 'BReq')]
    assert b'B secret requirement' in resp.content and b'B requirement text' in resp.content
    assert resp.context['domains'] == ['Sel_All', 'BR']          # get_domains is unscoped too


def test_01_idor_app_valset_cross_project_export(w):
    # KNOWN-ISSUE: idor-app-valset-cross-project
    c = w.client(w.ro_a)
    resp = c.get(eurl('Requirement', w.a.id, w.app_b.id, w.dvs_b.id))
    assert resp.status_code == 200
    assert b'B secret requirement' in resp.content
    assert resp['Content-Disposition'] == 'attachment; filename= "AppBRequirement.csv"'


def test_01_idor_app_valset_cross_project_find_replace(w):
    # KNOWN-ISSUE: idor-app-valset-cross-project
    c = w.client(w.ro_a)        # read-only member of A, no relation to B
    resp = c.post(lurl('Requirement', w.a.id, w.app_b.id, w.dvs_b.id),
                  {'field': 'title', 'find': 'secret', 'replace': 'PWNED'},
                  HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    assert resp.json() == {'updated_count': 1}
    w.b_req.refresh_from_db()
    assert w.b_req.title == 'B PWNED requirement'
    assert w.b_req.owner == w.ro_a


def test_01_project_level_cats_not_affected(w):
    # Checked and safe: refutes the "valset" half for project-level categories: project_id filter still applies.
    c = w.client(w.ro_a)
    resp = c.get(lurl('DataItem', w.a.id, 0, w.dvs_b.id))
    assert resp.status_code == 200
    assert listed(resp) == []
    assert resp.context['val_set'] == w.dvs_b           # only the foreign ValSet object leaks (name)


# ---------------------------------------------------------------------------------------------
# 2 idor-item-project (extended)
# ---------------------------------------------------------------------------------------------

def di_post(**over):
    data = {'domain': 'BD', 'name': 'BItem', 'title': 'overwritten by A', 'desc': 'x', 'value': '1',
            'rationale': '', 'remarks': '', 'implementation': '', 'p_kind': 'CNS', 't1': '', 't2': '',
            'change_log': 'pwn', 'n1': '0', 'n2': '0', 'n3': '0', 's_kind': 'INV', 's_data': '{}'}
    data.update(over)
    return data


def test_02_idor_item_project_edit_post(w):
    # KNOWN-ISSUE: idor-item-project
    c = w.client(w.rw_a)
    resp = c.post(iurl('edit_spec_item', 'DataItem', w.a.id, w.b_di.id), di_post(p_link=w.a_type.id))
    assert resp.status_code == 302
    w.b_di.refresh_from_db()
    assert w.b_di.project == w.b                       # still B's item ...
    assert w.b_di.title == 'overwritten by A'          # ... but modified through A's URL
    assert w.b_di.status == 'MOD' and w.b_di.owner == w.rw_a
    assert w.b_di.p_link == w.a_type                   # and now links into project A
    assert w.b_di.previous.status == 'OBS' and w.b_di.previous.project == w.b


def test_02_idor_item_project_del_post_marks_b_cnf_and_aliases_del(w):
    # KNOWN-ISSUE: idor-item-project
    vs_b1 = make_val_set(w.b, 'VS1')
    alias = make_spec_item(w.b, cat='DataItemType', domain='BT', name='BInt', val_set=vs_b1,
                           p_link=w.b_type, status='CNF', n1=4)
    c = w.client(w.rw_a)
    get = c.get(iurl('del_spec_item', 'DataItemType', w.a.id, w.b_type.id))
    assert get.status_code == 200 and b'B secret type' in get.content     # GET leaks
    resp = c.post(iurl('del_spec_item', 'DataItemType', w.a.id, w.b_type.id), {'change_log': 'gone'})
    assert resp.status_code == 302
    w.b_type.refresh_from_db()
    alias.refresh_from_db()
    assert (w.b_type.status, w.b_type.owner, w.b_type.change_log) == ('DEL', w.rw_a, 'gone')
    assert alias.status == 'DEL'


def test_02_idor_item_project_split_get_and_post(w):
    # KNOWN-ISSUE: idor-item-project
    vs_a1 = make_val_set(w.a, 'VSA1')
    c = w.client(w.rw_a)
    get = c.get(iurl('split_spec_item', 'DataItemType', w.a.id, w.b_type.id))
    assert get.status_code == 200 and b'B secret type' in get.content
    resp = c.post(iurl('split_spec_item', 'DataItemType', w.a.id, w.b_type.id),
                  {'title': 't', 'desc': '', 'value': '', 'rationale': '', 'remarks': '', 'implementation': '',
                   'change_log': '', 'n1': '4', 'val_set': vs_a1.id})
    assert resp.status_code == 302
    new = SpecItem.objects.get(project=w.a, val_set=vs_a1)
    assert new.p_link == w.b_type                       # A's item points into B (PROTECT)
    with pytest.raises(ProtectedError):
        SpecItem.objects.filter(id=w.b_type.id).delete()


def test_02_idor_item_project_refresh_get(w):
    # KNOWN-ISSUE: idor-item-project
    b_model = make_spec_item(w.b, cat='Model', domain='OldDom', name='OldName', application=w.app_b, n3=77,
                             value='<svg>old</svg>', p_kind='SM', status='CNF')
    cursor = mock.Mock()
    cursor.fetchall.return_value = [(77, 1, 'NewName', 3, 'Procedure', FIXED_TIME,
                                     '{"globals": {"fwprop": {"smTags": "NewDom"}}}', '<svg>new</svg>', 1, 2)]
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    c = w.client(w.rw_a, csrf=True)
    with mock.patch('editor.ext_cats.mdb.connect', return_value=conn):
        resp = c.get(iurl('refresh_spec_item', 'Model', w.a.id, b_model.id, app_id=w.app_a.id))
    assert resp.status_code == 302
    b_model.refresh_from_db()
    assert (b_model.project, b_model.name, b_model.value, b_model.status) == (w.b, 'NewName', '<svg>new</svg>', 'MOD')
    assert b_model.owner == w.rw_a


def test_02_idor_item_project_history_needs_only_read(w):
    # KNOWN-ISSUE: idor-item-project
    c = w.client(w.ro_a)
    resp = c.get('/editor/DataItem/%d/0/%d/Sel_All/list_spec_item_history' % (w.a.id, w.b_di.id))
    assert resp.status_code == 200
    assert resp.context['page_items'] == [w.b_di]
    assert b'B secret title' in resp.content


def test_02_copy_of_foreign_item_is_blocked_incidentally(w):
    # Safe (by accident): copy only works in the Default ValSet of the project of the URL.
    c = w.client(w.rw_a)
    resp = c.get(iurl('copy_spec_item', 'DataItem', w.a.id, w.b_di.id))
    assert resp.status_code == 302 and resp.url == '/editor'
    assert msgs(resp) == ['Only SpecItems in default ValSet can be copied ']


# ---------------------------------------------------------------------------------------------
# 3 idor-parent-link-cross-project
# ---------------------------------------------------------------------------------------------

def test_03_idor_parent_link_cross_project(w):
    # KNOWN-ISSUE: idor-parent-link-cross-project
    b_enum = make_spec_item(w.b, cat='EnumType', domain='BE', name='BEnum', title='B secret enum', n1=1,
                            status='NEW')
    c = w.client(w.rw_a)
    url = aurl('EnumValue', w.a.id) + '?s_parent_id=%d' % b_enum.id
    get = c.get(url)
    assert get.status_code == 200
    assert 'BE:BEnum (B secret enum)' in get.context['sub_title']
    assert list(get.context['form'].fields['s_link'].queryset) == [b_enum]
    resp = c.post(url, {'domain': 'AE', 'name': 'v1', 'title': 't', 'desc': '', 'value': '1', 'rationale': '',
                        'remarks': '', 'implementation': '', 'change_log': '', 's_link': b_enum.id})
    assert resp.status_code == 302
    assert resp.url.startswith('/editor/EnumType/%d/0/%d/Sel_All/0/list_spec_items?expand_id=%d'
                               % (w.a.id, w.dvs_a.id, b_enum.id))
    new = SpecItem.objects.get(project=w.a, name='v1')
    assert new.s_link == b_enum
    # B's owner can no longer delete its NEW item (PROTECT), only an error message
    cb = w.client(w.owner_b)
    d = cb.get(iurl('del_spec_item', 'EnumType', w.b.id, b_enum.id))
    assert d.status_code == 302
    assert SpecItem.objects.filter(id=b_enum.id).exists()
    assert any(m.startswith('Failure to delete BE:BEnum') for m in msgs(d))


# ---------------------------------------------------------------------------------------------
# 4 idor-app-write-cross-project
# ---------------------------------------------------------------------------------------------

def test_04_idor_app_write_cross_project(w):
    # KNOWN-ISSUE: idor-app-write-cross-project
    c = w.client(w.rw_a)
    resp = c.post(aurl('Requirement', w.a.id, app_id=w.app_b.id),
                  {'domain': 'Injected', 'name': 'r1', 'title': 't', 'value': 'v', 'rationale': '', 'remarks': '',
                   'implementation': '', 't1': '', 't2': '', 'p_kind': 'STD', 's_kind': 'TST', 'change_log': ''})
    assert resp.status_code == 302
    item = SpecItem.objects.get(name='r1')
    assert (item.project, item.application, item.val_set) == (w.a, w.app_b, w.dvs_a)
    # B's domain list now shows A's domain
    cb = w.client(w.owner_b)
    lb = cb.get(lurl('Requirement', w.b.id, w.app_b.id, w.dvs_b.id))
    assert 'Injected' in lb.context['domains']
    # B's application release confirms A's item
    cb.post('/editor/%d/make_application_release' % w.app_b.id, {'description': 'rel'})
    item.refresh_from_db()
    assert item.status == 'CNF'
    # staff deleting project B fails half-way
    cs = w.client(w.staff)
    with pytest.raises(ProtectedError):
        cs.get('/editor/%d/del_project' % w.b.id)
    assert Project.objects.filter(id=w.b.id).exists()
    assert not ValSet.objects.filter(project=w.b).exists()
    assert not SpecItem.objects.filter(project=w.b).exists()


# ---------------------------------------------------------------------------------------------
# 5 mutation-via-get
# ---------------------------------------------------------------------------------------------

def test_05_mutation_via_get_del_val_set_and_roles(w):
    # KNOWN-ISSUE: mutation-via-get
    vs = make_val_set(w.a, 'Tmp')
    c = w.client(w.staff, csrf=True)          # CSRF enforcement does not apply to GET
    r = c.get('/editor/%d/edit_project?del_val_set_id=%d' % (w.a.id, vs.id))
    assert r.status_code == 200
    assert not ValSet.objects.filter(id=vs.id).exists()
    r = c.get('/editor/%d/edit_project?user_id=%d&role=ADMIN' % (w.a.id, w.outsider.id))
    assert ProjectUser.objects.get(project=w.a, user=w.outsider).role == 'ADMIN'


def test_05_mutation_via_get_user_id_without_role_500(w):
    # KNOWN-ISSUE: mutation-via-get
    from django.db import IntegrityError
    c = w.client(w.staff)
    with pytest.raises(IntegrityError):
        c.get('/editor/%d/edit_project?user_id=%d' % (w.a.id, w.outsider.id))


# ---------------------------------------------------------------------------------------------
# 6 edit-project-del-user-unscoped (extended to ValSets)
# ---------------------------------------------------------------------------------------------

def test_06_staff_valset_unscoped(w):
    # KNOWN-ISSUE: edit-project-valset-unscoped
    c = w.client(w.staff)
    vs_b = make_val_set(w.b, 'BVS')
    # edit_val_set: ValSet of B renamed through A's URL
    r = c.post('/editor/%d/%d/edit_val_set' % (w.a.id, vs_b.id), {'name': 'renamed', 'description': 'd'})
    assert r.status_code == 302
    vs_b.refresh_from_db()
    assert vs_b.name == 'renamed' and vs_b.project == w.b
    # del_val_set_id of B through A's URL
    c.get('/editor/%d/edit_project?del_val_set_id=%d' % (w.a.id, vs_b.id))
    assert not ValSet.objects.filter(id=vs_b.id).exists()
    # a second "Default" ValSet breaks the project
    c.post('/editor/%d/add_val_set' % w.a.id, {'name': 'Default', 'description': 'dup'})
    assert ValSet.objects.filter(project=w.a, name='Default').count() == 2
    with pytest.raises(ValSet.MultipleObjectsReturned):
        w.client(w.owner_a).get(lurl('DataItem', w.a.id, 0, w.dvs_a.id))


# ---------------------------------------------------------------------------------------------
# 7 release-id-unscoped
# ---------------------------------------------------------------------------------------------

def test_07_release_id_unscoped(w):
    # KNOWN-ISSUE: release-id-unscoped
    c = w.client(w.ro_a)
    r = c.get(lurl('DataItemType', w.a.id, 0, w.dvs_a.id, rel=w.b.release.id))
    assert r.status_code == 200
    assert r.context['sel_rel'] == w.b.release       # only its date/version is used for filtering A


# ---------------------------------------------------------------------------------------------
# 8 index-lists-all-projects
# ---------------------------------------------------------------------------------------------

def test_08_index_lists_all_projects(w):
    # KNOWN-ISSUE: index-lists-all-projects
    c = w.client(w.outsider)
    r = c.get('/editor/')
    assert r.status_code == 200
    assert b'ProjB' in r.content and b'Secret B description' in r.content and b'owner_b' in r.content
    assert b'AppB' in r.content
    # ids of foreign projects are not linked for outsiders (only for user_has_access/owner)
    assert ('/editor/%d/export_project' % w.b.id).encode() not in r.content


# ---------------------------------------------------------------------------------------------
# 9 eval-ref-dos
# ---------------------------------------------------------------------------------------------

LOOP_SUM = 'var s:=0; for (var i:=0; i<1000; i+=1) { s+=i; }; s'


def test_09_eval_ref_rw_can_store_loop_and_list_page_evaluates_it(w):
    # KNOWN-ISSUE: eval-ref-dos
    c = w.client(w.rw_a)
    one = make_spec_item(w.a, cat='DataItem', domain='AD', name='one', value='0', p_link=w.a_type, p_kind='CNS')
    resp = c.post(aurl('DataItem', w.a.id),
                  di_post(domain='AD', name='loop', value='#DataItem:AD:one; %s' % LOOP_SUM,
                          p_link=w.a_type.id))
    assert resp.status_code == 302
    item = SpecItem.objects.get(project=w.a, name='loop')
    assert item.value == '#iref:%d; %s' % (one.id, LOOP_SUM)
    r = w.client(w.ro_a).get(lurl('DataItem', w.a.id, 0, w.dvs_a.id))
    assert b'= 499500.0' in r.content                   # arbitrary loop executed during page render
    e = w.client(w.ro_a).get(eurl('DataItem', w.a.id, 0, w.dvs_a.id) + '?export=latex_format')
    assert b'499500.0' in e.content                      # and during LaTeX export (no iref needed)


def test_09_eval_ref_fanout_is_exponential(w):
    # KNOWN-ISSUE: eval-ref-dos
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from editor.convert import eval_di_value
    leaf = make_spec_item(w.a, cat='DataItem', domain='F', name='l0', value='1', p_link=w.a_type)
    prev = leaf
    for k in range(1, 11):
        prev = make_spec_item(w.a, cat='DataItem', domain='F', name='l%d' % k,
                              value='#iref:%d+#iref:%d' % (prev.id, prev.id), p_link=w.a_type)
    with CaptureQueriesContext(connection) as q:
        assert eval_di_value(prev.value) == '1024.0'
    assert len(q.captured_queries) == 2 ** 11 - 2       # 2046 queries for 11 stored rows




CEXPRTK_CHILD = textwrap.dedent('''
    import resource, sys, cexprtk
    # hard address-space cap so that a runaway allocation can never exceed ~500 MB
    resource.setrlimit(resource.RLIMIT_AS, (500 * 1024 * 1024, 500 * 1024 * 1024))
    print(cexprtk.evaluate_expression(sys.argv[1], {}), flush=True)
''')


def run_cexprtk(expr, timeout):
    """Evaluate expr with the real cexprtk in a child process (killed on timeout)."""
    return subprocess.run([sys.executable, '-c', CEXPRTK_CHILD, expr], capture_output=True,
                          timeout=timeout, text=True)


def test_09_eval_ref_unbounded_loop_never_returns():
    # KNOWN-ISSUE: eval-ref-dos
    # A stored value is passed to cexprtk without any limit on loops: it does not finish.
    with pytest.raises(subprocess.TimeoutExpired):
        run_cexprtk('var x:=1; while (x>0) { x+=1; }; x', timeout=2)
    with pytest.raises(subprocess.TimeoutExpired):
        run_cexprtk('for (var i:=0; i<1e10; i+=1) { 0 }', timeout=2)


def test_09_eval_ref_large_vector_is_allocated():
    # KNOWN-ISSUE: eval-ref-dos
    # 20M doubles (160 MB) are accepted by cexprtk; only the child's RLIMIT_AS stops larger ones.
    r = run_cexprtk('var v[20000000]; v[0]:=7; v[0]', timeout=10)
    assert r.stdout.strip() == '7.0'


# ---------------------------------------------------------------------------------------------
# 10 iref-cross-project-disclosure
# ---------------------------------------------------------------------------------------------

def test_10_iref_cross_project_disclosure(w):
    # KNOWN-ISSUE: iref-cross-project-disclosure
    c = w.client(w.rw_a)
    resp = c.post(aurl('DataItem', w.a.id),
                  di_post(domain='AD', name='leak', value='#iref:%d' % w.b_di.id,
                          desc='see #iref:%d' % w.b_di.id, p_link=w.a_type.id))
    assert resp.status_code == 302
    leak = SpecItem.objects.get(project=w.a, name='leak')
    assert leak.desc == 'see #iref:%d' % w.b_di.id          # literal iref passes convert_edit_to_db
    r = w.client(w.ro_a).get(lurl('DataItem', w.a.id, 0, w.dvs_a.id))
    assert b'BD:BItem' in r.content
    assert b'B secret title' in r.content and b'B secret desc' in r.content    # tooltip of B's item
    assert b'= 42.0' in r.content                                            # B's value via eval
    ed = c.get(iurl('edit_spec_item', 'DataItem', w.a.id, leak.id))
    assert ed.context['form'].initial['desc'] == 'see #DataItem:BD:BItem'


# ---------------------------------------------------------------------------------------------
# 11 latex-export-injection
# ---------------------------------------------------------------------------------------------

def test_11_latex_export_injection(w):
    # KNOWN-ISSUE: latex-export-injection
    make_spec_item(w.a, cat='DataItem', domain='AD', name='tex', p_link=w.a_type,
                   title=r'\input{/etc/passwd}', desc=r'\immediate\write18{id} $x$',
                   value=r'\input{/etc/hostname}')
    r = w.client(w.ro_a).get(eurl('DataItem', w.a.id, 0, w.dvs_a.id) + '?export=latex_format')
    body = r.content.decode()
    assert r'\input{/etc/passwd}' in body
    assert r'\immediate\write18{id} $x$' in body
    # Value (convert_db_to_latex) and NVal (raw eval fallback) both keep the backslash commands
    assert r'|\input{/etc/hostname}|\input{/etc/hostname}|' in body


# ---------------------------------------------------------------------------------------------
# 12 order-by-unrestricted
# ---------------------------------------------------------------------------------------------

def test_12_order_by_sensitive_owner_fields(w):
    # KNOWN-ISSUE: order-by-unrestricted
    u1 = make_user('aaa_user')
    u2 = make_user('zzz_user')
    User.objects.filter(id=u1.id).update(password='md5$zzz', is_superuser=False)
    User.objects.filter(id=u2.id).update(password='md5$aaa', is_superuser=True)
    make_spec_item(w.a, cat='DataItemType', domain='O', name='n1', owner=u1)
    make_spec_item(w.a, cat='DataItemType', domain='O', name='n2', owner=u2)
    c = w.client(w.ro_a)
    for field, expected in (('owner__password', ['n2', 'n1']), ('-owner__password', ['n1', 'n2']),
                            ('owner__is_superuser', ['n1', 'n2']), ('owner__email', ['n1', 'n2'])):
        r = c.get(lurl('DataItemType', w.a.id, 0, w.dvs_a.id, sel_val='O') + '?order_by=' + field)
        assert r.status_code == 200
        assert [n for _, n in listed(r)] == expected, field


# ---------------------------------------------------------------------------------------------
# 13 csv-formula-injection
# ---------------------------------------------------------------------------------------------

def test_13_csv_formula_injection(w):
    # KNOWN-ISSUE: csv-formula-injection
    make_spec_item(w.a, cat='DataItemType', domain='X', name='f', title='=HYPERLINK("http://x","y")',
                   desc='@SUM(1)')
    r = w.client(w.ro_a).get(eurl('DataItemType', w.a.id, 0, w.dvs_a.id))
    # csv quoting only doubles the quotes; the cell still starts with '=' when opened in a spreadsheet
    assert '|"=HYPERLINK(""http://x"",""y"")"|' in r.content.decode()
    assert '|@SUM(1)|' in r.content.decode()


# ---------------------------------------------------------------------------------------------
# 14 link-suggest-js-string
# ---------------------------------------------------------------------------------------------

def test_14_link_suggest_js_string(w):
    # KNOWN-ISSUE: link-suggest-js-string
    make_spec_item(w.a, cat='DataItemType', domain='J', name='bs', title='ends with backslash\\')
    make_spec_item(w.a, cat='DataItemType', domain='J', name='nl', title="line1\nline2")
    make_spec_item(w.a, cat='DataItemType', domain='J', name='q', title="it's <b>")
    r = w.client(w.rw_a).get(aurl('DataItemType', w.a.id))
    body = r.content.decode()
    assert "comment: 'ends with backslash\\'}" in body       # backslash escapes the closing quote
    assert "comment: 'line1\nline2'}" in body                # raw newline inside a JS string literal
    assert "comment: 'it&#x27;s &lt;b&gt;'}" in body         # quotes/tags are HTML-escaped: no XSS


# ---------------------------------------------------------------------------------------------
# 15 import-traceback-in-message
# ---------------------------------------------------------------------------------------------

def test_15_import_traceback_in_message(w):
    # KNOWN-ISSUE: import-traceback-in-message
    from django.core.files.uploadedfile import SimpleUploadedFile
    header = 'Domain|Name|Title|Description|Default Value|Rationale|Remarks|Native Type|ValSet|Change Log|Owner|Size'
    row = 'D|n|t|d|v|r|r|i|Default|c|x|notanint'
    f = SimpleUploadedFile('x.csv', (header + '\n' + row + '\n').encode())
    c = w.client(w.rw_a)
    r = c.post('/editor/DataItemType/%d/0/%d/Sel_All/import_spec_items' % (w.a.id, w.dvs_a.id),
               {'upload_file': f})
    assert r.status_code == 302
    m = msgs(r)
    assert len(m) == 1 and 'Traceback (most recent call last)' in m[0]
    assert os.sep + 'editor' + os.sep + 'views.py' in m[0]        # server file paths disclosed


# ---------------------------------------------------------------------------------------------
# 16 ext-cats-sql-injection (narrowed)
# ---------------------------------------------------------------------------------------------

def test_16_ext_cats_email_is_only_injection_vector(w):
    # KNOWN-ISSUE: ext-cats-sql-injection
    validate_email("x'or+1#@a.com")          # Django's EmailValidator accepts the payload
    w.rw_a.email = "x'or+1#@a.com"
    w.rw_a.save()
    cursor = mock.Mock()
    cursor.fetchall.return_value = []
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    c = w.client(w.rw_a)
    with mock.patch('editor.ext_cats.mdb.connect', return_value=conn):
        c.get(aurl('Model', w.a.id, app_id=w.app_a.id))
    assert cursor.execute.call_args_list[0].args[0] == "SELECT * FROM users WHERE email = 'x'or+1#@a.com'"


# ---------------------------------------------------------------------------------------------
# 17 / 18 / 19 / 23 settings (operator)
# ---------------------------------------------------------------------------------------------

def test_17_no_secure_proxy_ssl_header(settings, w):
    # KNOWN-ISSUE: no-secure-proxy-ssl-header
    assert settings.SECURE_PROXY_SSL_HEADER is None
    r = w.client(w.ro_a).get('/editor/', HTTP_X_FORWARDED_PROTO='https')
    assert r.wsgi_request.is_secure() is False


def test_18_axes_lockout_by_ip_only(settings):
    # KNOWN-ISSUE: axes-ip-only-lockout
    assert settings.AXES_LOCKOUT_PARAMETERS == ['ip_address']      # axes default, not overridden
    assert settings.AXES_FAILURE_LIMIT == 3
    alice = make_user('alice')
    login = '/editor/login/'
    # 3 wrong guesses from one IP lock that IP ...
    c1 = Client(REMOTE_ADDR='10.0.0.1')
    for _ in range(3):
        c1.post(login, {'username': 'alice', 'password': 'bad'})
    assert c1.post(login, {'username': 'alice', 'password': 'test-password-123'}).status_code == 429
    # ... but the same account can be guessed again from any other IP
    for ip in ('10.0.0.2', '10.0.0.3'):
        c = Client(REMOTE_ADDR=ip)
        for _ in range(2):
            assert c.post(login, {'username': 'alice', 'password': 'bad'}).status_code == 200
    r = Client(REMOTE_ADDR='10.0.0.4').post(login, {'username': 'alice', 'password': 'test-password-123'})
    assert r.status_code == 302
    # X-Forwarded-For is ignored (single proxy IP => everyone shares one counter)
    c5 = Client(REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='1.2.3.4')
    assert c5.post(login, {'username': 'alice', 'password': 'test-password-123'}).status_code == 429


def test_19_tracked_dev_secret_key():
    # KNOWN-ISSUE: tracked-dev-secret-key
    tracked = subprocess.run(['git', 'ls-files', 'dj_cordetfw_config.json'], cwd=REPO_ROOT,
                             capture_output=True, text=True).stdout.strip()
    assert tracked == 'dj_cordetfw_config.json'
    cfg = json.loads((REPO_ROOT / 'dj_cordetfw_config.json').read_text())
    assert cfg['DEBUG'] is True and len(cfg['SECURE_KEY']) == 50


def test_23_session_and_header_defaults(settings):
    # KNOWN-ISSUE: session-and-reset-hardening
    assert settings.SESSION_COOKIE_AGE == 1209600
    assert settings.SECURE_HSTS_SECONDS == 0
    assert settings.SECURE_SSL_REDIRECT is False
    assert 'csp' not in ' '.join(settings.MIDDLEWARE).lower()


# ---------------------------------------------------------------------------------------------
# 20 temp-files-world-readable
# ---------------------------------------------------------------------------------------------

def test_20_temp_files_permissions_and_predictable_name(w, isolated_temp_dir):
    # KNOWN-ISSUE: temp-files-world-readable
    old = os.umask(0o022)
    try:
        r = w.client(w.ro_a).get('/editor/%d/export_project' % w.a.id)
        b''.join(r.streaming_content)
    finally:
        os.umask(old)
    (d,) = os.listdir(isolated_temp_dir)
    assert d.startswith('cordetfw_editor_20')                   # timestamp name, predictable
    full = os.path.join(isolated_temp_dir, d)
    assert oct(os.stat(full).st_mode & 0o777) == '0o755'
    assert oct(os.stat(os.path.join(full, 'spec_items.csv')).st_mode & 0o777) == '0o644'




# ---------------------------------------------------------------------------------------------
# 21 import-project-no-limits / 22 import-project-attribution-forgery: staff only
# ---------------------------------------------------------------------------------------------



def exported_tables(w):
    import io
    import zipfile
    r = w.client(w.owner_a).get('/editor/%d/export_project' % w.a.id)
    z = zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content)))
    return {n: z.read(n).decode() for n in z.namelist()}


def zip_upload(files):
    import io
    import zipfile
    from django.core.files.uploadedfile import SimpleUploadedFile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, data in files.items():
            z.writestr(n, data)
    return SimpleUploadedFile('p.zip', buf.getvalue(), content_type='application/zip')


def test_21_import_project_no_limits(w, isolated_temp_dir):
    # KNOWN-ISSUE: import-project-no-limits
    big = b'\0' * (20 * 1024 * 1024)                    # 20 MB member, ~20 KB compressed
    up = zip_upload({'big.bin': big, '../escape.txt': b'x', 'project.csv': 'name\n'})
    assert up.size < 200 * 1024
    r = w.client(w.staff).post('/editor/import_project', {'upload_file': up})
    assert r.status_code == 302
    (d,) = [x for x in os.listdir(isolated_temp_dir) if x.startswith('cordetfw_editor_')]
    assert os.path.getsize(os.path.join(isolated_temp_dir, d, 'big.bin')) == 20 * 1024 * 1024
    assert os.path.exists(os.path.join(isolated_temp_dir, d, 'escape.txt'))     # zip-slip neutralised
    assert not os.path.exists(os.path.join(isolated_temp_dir, 'escape.txt'))


def test_22_import_project_unvalidated_cat_status(w, isolated_temp_dir):
    # KNOWN-ISSUE: import-project-attribution-forgery
    import shutil
    from editor.utilities import spec_item_to_edit
    t = exported_tables(w)
    for d in os.listdir(isolated_temp_dir):          # avoid the known same-second temp dir collision
        shutil.rmtree(os.path.join(isolated_temp_dir, d))
    t['project.csv'] = t['project.csv'].replace('ProjA', 'ProjImported')
    t['spec_items.csv'] = t['spec_items.csv'].replace('DataItemType', 'BogusCat').replace(',NEW,', ',HACKED,')
    t['releases.csv'] = t['releases.csv'].replace('owner_a', 'owner_b')        # release author forged
    r = w.client(w.staff).post('/editor/import_project', {'upload_file': zip_upload(t)})
    assert r.status_code == 302
    p = Project.objects.get(name='ProjImported')
    item = SpecItem.objects.get(project=p, name='AInt')
    assert (item.cat, item.status) == ('BogusCat', 'HACKED')
    assert p.release.release_author == w.owner_b
    with pytest.raises(KeyError):
        spec_item_to_edit(item)
