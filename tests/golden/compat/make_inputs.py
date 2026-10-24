"""
Generator for the import compatibility corpus (Task 7.0).

NOT a test and NOT run automatically.  The files under inputs/ are exports made ONCE by the
code of release track-s-rc1 (c602bbb) from synthetic factory data and are committed; they are
the "exports of the current production version" that every later importer must still accept.
Regenerate deliberately (only on the baseline code, never to make a test pass):

    COMPAT_REGEN=1 .venv/bin/python -m pytest tests/test_compat_corpus.py -k regenerate

This module is loaded by tests/test_compat_corpus.py via importlib (it is not a package).
Everything is synthetic (users, names, text); all timestamps are fixed.
"""
from datetime import datetime, timezone

from editor.models import Application, Project, ProjectUser, Release, SpecItem, ValSet
from tests.factories import make_user

T0 = datetime(2023, 12, 1, 8, 0, 0, tzinfo=timezone.utc)
T1 = datetime(2024, 2, 20, 16, 45, 30, tzinfo=timezone.utc)
T2 = datetime(2024, 3, 3, 3, 3, 3, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------------------------
# Manifest.  kind project_zip: file (under inputs/) or members_dir (tests/golden-relative dir with
# the six CSV members, zipped in memory); users = accounts that exist in the fresh DB before the
# import (the importer 'importer' is always created as staff).  kind spec_items_csv: file (under
# inputs/) or golden (tests/golden-relative CSV); imported by 'writer' into the base world
# (tests.test_import_export.build_world) at /editor/<cat>/1/<app>/<val_set>/Sel_All/import_spec_items.
# known_issue: ids from docs/fixes/register.md whose current (buggy) outcome is recorded.
# ---------------------------------------------------------------------------------------------
GOLDEN_USERS = ['owner', 'reader', 'writer']
MANIFEST = [
    {'name': 'zip_golden_export', 'kind': 'project_zip', 'members_dir': 'export/project',
     'users': GOLDEN_USERS,
     'edge': 'existing golden project export (iref, CRLF, s_data, RO/RW, VS1, app with cats, releases, NEW/MOD/CNF/OBS, p_link/s_link)'},
    {'name': 'zip_refs_text', 'kind': 'project_zip', 'file': 'zip_refs_text.zip', 'users': ['ref_owner'],
     'edge': '#iref: to live item, dangling #iref:, "None" text, CRLF in desc/remarks/rationale/value/t1, nested unicode s_data'},
    {'name': 'zip_roles_valsets_releases', 'kind': 'project_zip', 'file': 'zip_roles_valsets_releases.zip',
     'users': ['rv_owner', 'rv_ro1', 'rv_rw1', 'rv_rw2', 'rv_ro2'], 'known_issue': ['import-project-role-lost'],
     'edge': 'owner + 2 RO + 2 RW members, ValSets Default/VS1/VS2 with items, 3-step project release chain'},
    {'name': 'zip_apps_versions', 'kind': 'project_zip', 'file': 'zip_apps_versions.zip', 'users': ['ap_owner'],
     'known_issue': ['import-project-application-version-lost'],
     'edge': 'two applications with cats and application_version 1 / 2, items in project and in each app'},
    {'name': 'zip_app_empty_cats', 'kind': 'project_zip', 'file': 'zip_app_empty_cats.zip', 'users': ['ec_owner'],
     'known_issue': ['import-project-empty-app-cats'],
     'edge': 'application with empty cats (rejected by the importer today)'},
    {'name': 'zip_statuses_links', 'kind': 'project_zip', 'file': 'zip_statuses_links.zip', 'users': ['st_owner'],
     'edge': 'NEW/MOD/CNF/DEL/OBS items, previous chain, p_link and s_link (split items)'},
    {'name': 'zip_dotted_names', 'kind': 'project_zip', 'file': 'zip_dotted_names.zip', 'users': ['dn_owner'],
     'edge': 'dots/dashes inside project, domain and item names, irefs to them'},
    {'name': 'zip_owner_not_member', 'kind': 'project_zip', 'file': 'zip_owner_not_member.zip',
     'users': ['om_owner', 'om_outsider'], 'known_issue': ['import-project-owner-not-member'],
     'edge': 'unlinked item owned by a user who is neither project owner nor member (item dropped with message)'},
    {'name': 'zip_owner_not_member_linked', 'kind': 'project_zip', 'file': 'zip_owner_not_member_linked.zip',
     'users': ['ol_owner', 'ol_outsider'],
     'known_issue': ['import-project-owner-not-member', 'import-project-dangling-link-crash'],
     'edge': 'dropped item is the p_link target of a kept item (KeyError after partial import)'},
    # spec-item CSV exports (goldens referenced, not copied)
    {'name': 'csv_golden_di_project', 'kind': 'spec_items_csv', 'golden': 'export/spec_items/di_project.csv',
     'cat': 'DataItem', 'application': 0, 'val_set': 1,
     'edge': 'golden DataItem export, Default ValSet, into the same world (CNF items get OBS copies)'},
    {'name': 'csv_golden_di_vs1', 'kind': 'spec_items_csv', 'golden': 'export/spec_items/di_project_vs1.csv',
     'cat': 'DataItem', 'application': 0, 'val_set': 2, 'edge': 'golden DataItem export of ValSet VS1'},
    {'name': 'csv_golden_enumtype', 'kind': 'spec_items_csv', 'golden': 'export/spec_items/enumtype_project.csv',
     'cat': 'EnumType', 'application': 0, 'val_set': 1, 'edge': 'golden EnumType export'},
    {'name': 'csv_golden_enumvalue', 'kind': 'spec_items_csv', 'golden': 'export/spec_items/enumvalue_project.csv',
     'cat': 'EnumValue', 'application': 0, 'val_set': 1, 'edge': 'golden EnumValue export (parent links)'},
    {'name': 'csv_golden_req_application', 'kind': 'spec_items_csv',
     'golden': 'export/spec_items/req_application.csv',
     'cat': 'Requirement', 'application': 1, 'val_set': 1, 'edge': 'golden Requirement export of an application'},
    {'name': 'csv_golden_req_no_application', 'kind': 'spec_items_csv',
     'golden': 'export/spec_items/req_no_application.csv',
     'cat': 'Requirement', 'application': 0, 'val_set': 1,
     'edge': 'golden Requirement export of the project scope (no application), imported at application 0'},
    {'name': 'csv_ext_dataitem', 'kind': 'spec_items_csv', 'file': 'csv_ext_dataitem.csv',
     'cat': 'DataItem', 'application': 0, 'val_set': 1,
     'edge': 'DataItem export with dotted domain/name, iref + dangling iref, CRLF in desc/remarks, unicode; new items'},
    {'name': 'csv_ext_dataitem_vs1', 'kind': 'spec_items_csv', 'file': 'csv_ext_dataitem_vs1.csv',
     'cat': 'DataItem', 'application': 0, 'val_set': 2,
     'edge': 'DataItem export of a non-Default ValSet incl. an item missing from Default'},
]


def _rel(author, pv=0, av=0, previous=None, desc='Release', at=T0):
    return Release.objects.create(release_author=author, desc=desc, updated_at=at,
                                  project_version=pv, application_version=av, previous=previous)


def _project(owner, name, cats='DataItem,EnumType,EnumValue,DataItemType,Requirement', rel=None):
    rel = rel or _rel(owner, desc='Initial release for project ' + name)
    p = Project.objects.create(name=name, desc='Synthetic project ' + name, cats=cats, owner=owner, release=rel)
    ValSet.objects.create(project=p, name='Default', desc='Default ValSet')
    return p


def _item(p, cat, domain, name, owner=None, vs=None, app=None, status='CNF', **kw):
    kw.setdefault('title', 'Title of ' + name)
    kw.setdefault('updated_at', T1)
    kw.setdefault('created_at', T0)
    return SpecItem.objects.create(
        project=p, cat=cat, domain=domain, name=name, owner=owner or p.owner, application=app, status=status,
        val_set=vs or ValSet.objects.get(project=p, name='Default'), **kw)


def _fix_auto_times(p):
    Project.objects.filter(id=p.id).update(updated_at=T1)
    Application.objects.filter(project=p).update(updated_at=T1)
    ValSet.objects.filter(project=p).update(updated_at=T1.date())
    ProjectUser.objects.filter(project=p).update(updated_at=T1.date())


def build_refs_text():
    o = make_user('ref_owner')
    p = _project(o, 'Refs Text')
    ty = _item(p, 'DataItemType', 'Types', 'uint8', implementation='unsigned char', n1=1)
    b = _item(p, 'DataItem', 'Dom', 'B', p_link=ty, value='1', p_kind='CNS')
    _item(p, 'DataItem', 'Dom', 'A', p_link=ty, p_kind='VAR', value='#iref:%d * 2' % b.id,
          desc='See #iref:%d and dangling #iref:424242 and the word None and #iref:None.\r\nSecond line\r\nThird' % b.id,
          rationale='Why\r\nbecause', remarks='line1\r\n\r\nline3\n', t1='x\r\ny', t2='µm ä ☺',
          s_data={'k': [1, 2, {'deep': 'ü'}], 'e': {}, 'n': None, 'u': 'ä ☺'}, n1=3, n2=0, n3=7,
          change_log='first\r\nsecond')
    _item(p, 'DataItem', 'Dom', 'C', p_link=None, desc='None', value='None', status='NEW', s_data={})
    _fix_auto_times(p)


def build_roles_valsets_releases():
    o = make_user('rv_owner')
    users = {n: make_user(n) for n in ['rv_ro1', 'rv_rw1', 'rv_rw2', 'rv_ro2']}
    r0 = _rel(o, 0, 0, desc='Initial release for project')
    r1 = _rel(users['rv_rw1'], 1, 0, r0, 'Release 1', T1)
    r2 = _rel(o, 2, 0, r1, 'Release 2\nmultiline', T2)
    p = _project(o, 'Roles ValSets', rel=r2)
    for n, role in [('rv_ro1', 'RO'), ('rv_rw1', 'RW'), ('rv_rw2', 'RW'), ('rv_ro2', 'RO')]:
        ProjectUser.objects.create(project=p, user=users[n], role=role)
    d = ValSet.objects.get(project=p, name='Default')
    v1 = ValSet.objects.create(project=p, name='VS1', desc='First alternative')
    v2 = ValSet.objects.create(project=p, name='VS2', desc='Second "quoted" | alternative')
    for vs, val in [(d, '1'), (v1, '2'), (v2, '3')]:
        _item(p, 'DataItem', 'Dom', 'Count', vs=vs, value=val, p_kind='CNS', owner=users['rv_rw1'])
    _item(p, 'DataItem', 'Dom', 'Only_Default', owner=users['rv_rw2'], status='MOD')
    _fix_auto_times(p)


def build_apps_versions():
    o = make_user('ap_owner')
    p = _project(o, 'Apps Versions')
    a0 = _rel(o, 0, 0, desc='Initial release for application A')
    a1 = _rel(o, 0, 1, a0, 'App release 1', T1)
    b0 = _rel(o, 0, 0, desc='Initial release for application B')
    b1 = _rel(o, 0, 1, b0, 'B 1', T1)
    b2 = _rel(o, 1, 2, b1, 'B 2', T2)
    appa = Application.objects.create(name='App A', desc='A', cats='Requirement', project=p, release=a1)
    appb = Application.objects.create(name='App B', desc='B | with pipe', cats='Requirement,DataItem',
                                      project=p, release=b2)
    shared = _item(p, 'DataItem', 'Dom', 'Shared')
    _item(p, 'Requirement', 'AppDom', 'R1', app=appa, status='NEW', value='shall do #iref:%d' % shared.id)
    _item(p, 'Requirement', 'AppDom', 'R1', app=appb, status='CNF', value='B shall do')
    _item(p, 'DataItem', 'BDom', 'BData', app=appb, status='MOD')
    _fix_auto_times(p)


def build_app_empty_cats():
    o = make_user('ec_owner')
    p = _project(o, 'Empty Cats')
    a0 = _rel(o, desc='Initial release for application')
    Application.objects.create(name='Bare App', desc='no cats', cats='', project=p, release=a0)
    _item(p, 'DataItem', 'Dom', 'X')
    _fix_auto_times(p)


def build_statuses_links():
    o = make_user('st_owner')
    p = _project(o, 'Statuses Links')
    ty = _item(p, 'EnumType', 'Types', 'Color', n1=4)
    old = _item(p, 'EnumType', 'Types', 'Shade', status='OBS', updated_at=T0)
    new = _item(p, 'EnumType', 'Types', 'Shade', previous=old, status='MOD')
    r = _item(p, 'EnumValue', 'Types', 'Red', s_link=ty, value='0', status='NEW')
    _item(p, 'EnumValue', 'Types', 'Green', s_link=ty, value='1', status='CNF')
    _item(p, 'EnumValue', 'Types', 'Gone', s_link=ty, value='2', status='DEL')
    split = _item(p, 'DataItem', 'Dom', 'Split', p_link=new, s_link=r, value='#iref:%d' % r.id, status='MOD')
    _item(p, 'DataItem', 'Dom', 'Child', p_link=ty, s_link=split, status='NEW')
    _fix_auto_times(p)


def build_dotted_names():
    o = make_user('dn_owner')
    p = _project(o, 'Proj.v1.2-rc')
    a = _item(p, 'DataItem', 'Dom.sub', 'a.b', value='1')
    _item(p, 'DataItem', 'Dom-x.y', 'x-y.z', value='#iref:%d + 1' % a.id, desc='refers to #iref:%d' % a.id)
    _fix_auto_times(p)


def build_owner_not_member(linked):
    pre = 'ol' if linked else 'om'
    o = make_user(pre + '_owner')
    out = make_user(pre + '_outsider')
    p = _project(o, 'Owner Linked' if linked else 'Owner Not Member')
    ty = _item(p, 'DataItemType', 'Types', 'uint8', owner=out if linked else o)
    _item(p, 'DataItem', 'Dom', 'Kept', p_link=ty if linked else None, desc='#iref:%d' % ty.id)
    if not linked:
        _item(p, 'DataItem', 'Dom', 'Orphan', owner=out)
    _fix_auto_times(p)


ZIP_WORLDS = {
    'zip_refs_text': (build_refs_text, 'Refs Text'),
    'zip_roles_valsets_releases': (build_roles_valsets_releases, 'Roles ValSets'),
    'zip_apps_versions': (build_apps_versions, 'Apps Versions'),
    'zip_app_empty_cats': (build_app_empty_cats, 'Empty Cats'),
    'zip_statuses_links': (build_statuses_links, 'Statuses Links'),
    'zip_dotted_names': (build_dotted_names, 'Proj.v1.2-rc'),
    'zip_owner_not_member': (lambda: build_owner_not_member(False), 'Owner Not Member'),
    'zip_owner_not_member_linked': (lambda: build_owner_not_member(True), 'Owner Linked'),
}


def build_csv_extended():
    """The base world (tests.test_import_export.build_world) plus extra DataItems for CSV export."""
    from tests.test_import_export import build_world
    w = build_world()
    SpecItem.objects.create(
        id=201, project=w.project, cat='DataItem', domain='Dom.sub', name='ext.one', title='Ext one',
        owner=w.owner, val_set=w.default, status='NEW', updated_at=T2, created_at=T0, p_link=w.uint8,
        value='#iref:201 + 1', p_kind='CNS', s_kind='', n1=1,
        desc='Line1\r\nLine2 with #iref:107 and dangling #iref:424242 and ä µ',
        remarks='r1\r\nr2', rationale='because | pipe')
    SpecItem.objects.create(
        id=202, project=w.project, cat='DataItem', domain='Dom', name='ext-two', title='Ext two',
        owner=w.owner, val_set=w.vs1, status='NEW', updated_at=T2, created_at=T0, p_link=w.uint8, value='9',
        p_kind='CNS')   # only in VS1, not in Default
    return w


CSV_EXPORTS = {
    'csv_ext_dataitem': '/editor/DataItem/1/0/1/Sel_All/0/export_spec_items',
    'csv_ext_dataitem_vs1': '/editor/DataItem/1/0/2/Sel_All/0/export_spec_items',
}
