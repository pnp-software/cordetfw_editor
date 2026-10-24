"""
Golden HTML snapshots of the main pages, rendered from ONE deterministic dataset.

Determinism:
 * every snapshot test builds the same data in the same order (stable ids, in-memory sqlite);
 * all timestamps come from tests.factories.FIXED_TIME, and auto_now fields
   (Project.updated_at, ValSet.updated_at, ProjectUser.updated_at, Application.updated_at)
   are pinned with QuerySet.update() after creation;
 * CSRF tokens are normalised by tests.golden.normalize_html.
No further normalisation is needed.

Record with UPDATE_GOLDEN=1 on the baseline only.
"""
from datetime import datetime, timezone

import pytest
from django.template.loader import render_to_string

from editor.models import Application, Project, ProjectUser, ValSet
from tests.factories import (FIXED_TIME, default_val_set, make_application, make_project,
                             make_project_user, make_release, make_spec_item, make_user,
                             make_val_set)
from tests.golden import assert_golden, normalize_html

# reset_sequences keeps primary keys stable on MySQL, whose AUTO_INCREMENT survives rollbacks.
pytestmark = pytest.mark.django_db(transaction=True, reset_sequences=True)

ALL_CATS = 'DataItem,EnumType,EnumValue,DataItemType,InfoItem,Model'
REL_TIME = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)


def build_dataset():
    """Create the fixed dataset; returns a dict of the created objects."""
    owner = make_user('owner', is_staff=True)
    owner.first_name, owner.last_name = 'Olga', 'Owner'
    owner.save()
    writer = make_user('writer')
    reader = make_user('reader')
    project = make_project(owner, 'Proj', cats=ALL_CATS, desc='Project for snapshots')
    dvs = default_val_set(project)
    vs1 = make_val_set(project, 'VS1', 'Alternative values')
    make_project_user(project, writer, 'RW')
    make_project_user(project, reader, 'RO')
    app = make_application(project, 'App', cats='InfoItem,Model', desc='Application for snapshots')

    dtype = make_spec_item(project, cat='DataItemType', domain='Types', name='Int32', title='32-bit integer',
                           desc='Signed integer', n1=32)
    etype = make_spec_item(project, cat='EnumType', domain='Enums', name='Colour', title='Colour type',
                           desc='Enumerated **colours**', n1=8, status='CNF')
    red = make_spec_item(project, cat='EnumValue', domain='Enums', name='Red', title='Red', value='1',
                         s_link=etype, status='CNF')
    green = make_spec_item(project, cat='EnumValue', domain='Enums', name='Green', title='Green', value='2',
                           s_link=etype, status='CNF')
    d1 = make_spec_item(project, cat='DataItem', domain='Alpha', name='count', title='Counter',
                        desc='Counts things.\n\n- first bullet\n- second bullet\n\nSee #iref:%d for the type.' % dtype.id,
                        value='42', p_kind='VAR', p_link=dtype, t1='1', t2='ms',
                        rationale='Needed for **bold** reasons', remarks='Unicode: Größe — µs ✓ 日本語')
    d2 = make_spec_item(project, cat='DataItem', domain='Alpha', name='colour', title='Current colour',
                        desc='Uses #iref:%d' % red.id, value='#iref:%d' % red.id, p_kind='CTX', p_link=etype,
                        status='CNF')
    old = make_spec_item(project, cat='DataItem', domain='Beta', name='level', title='Level v1', value='1',
                         p_kind='PAR', p_link=dtype, status='OBS')
    d3 = make_spec_item(project, cat='DataItem', domain='Beta', name='level', title='Level v2', value='2',
                        p_kind='PAR', p_link=dtype, status='MOD', previous=old, change_log='Raised to 2')
    alias = make_spec_item(project, cat='DataItem', domain='Alpha', name='count', title='Counter (VS1)',
                           value='43', p_kind='VAR', p_link=d1, val_set=vs1)
    info = make_spec_item(project, cat='InfoItem', domain='Info', name='note', title='A note',
                          value='Application level item', application=app)

    # a project release, so that the release dropdown has entries
    rel = make_release(owner, project_version=1, previous=project.release, updated_at=REL_TIME, desc='First release')
    project.release = rel
    project.save()

    # pin auto_now fields
    Project.objects.update(updated_at=FIXED_TIME)
    Application.objects.update(updated_at=FIXED_TIME)
    ValSet.objects.update(updated_at=FIXED_TIME.date())
    ProjectUser.objects.update(updated_at=FIXED_TIME.date())
    return dict(owner=owner, writer=writer, reader=reader, project=project, dvs=dvs, vs1=vs1, app=app,
                dtype=dtype, etype=etype, red=red, green=green, d1=d1, d2=d2, d3=d3, old=old, alias=alias,
                info=info, rel=rel)


@pytest.fixture
def ds(client):
    data = build_dataset()
    client.force_login(data['owner'])
    return data


def snap(name, response, status=200):
    assert response.status_code == status
    assert_golden('pages/%s.html' % name, normalize_html(response.content))


def lurl(ds, cat='DataItem', app=0, vs=None, sel_val='Sel_All', rel=0):
    vs = vs or ds['dvs']
    return '/editor/%s/%d/%d/%d/%s/%d/list_spec_items' % (cat, ds['project'].id, app, vs.id, sel_val, rel)


def iurl(ds, view, cat, item, app=0, sel_val='Sel_All', rel=0):
    return '/editor/%s/%d/%d/%d/%s/%d/%s' % (cat, ds['project'].id, app, item.id, sel_val, rel, view)


def test_snapshot_top_page(client):
    snap('top_page', client.get('/'))


def test_snapshot_index_anonymous(client):
    build_dataset()
    snap('index_anonymous', client.get('/editor/'))


def test_snapshot_index_logged_in(client, ds):
    snap('index_logged_in', client.get('/editor/'))


def test_snapshot_help(client, ds):
    snap('help', client.get('/editor/help/'))


def test_snapshot_login(client):
    snap('login', client.get('/editor/login/'))


def test_snapshot_password_reset_form(client):
    snap('password_reset_form', client.get('/editor/password_reset/'))


def test_snapshot_list_data_items(client, ds):
    # KNOWN-ISSUE: ref-link-backslash (golden contains '0\\list_spec_items' links)
    snap('list_data_items', client.get(lurl(ds)))


def test_snapshot_list_data_items_short(client, ds):
    snap('list_data_items_short', client.get(lurl(ds), {'disp': 'disp_short', 'order_by': 'p_kind'}))


def test_snapshot_list_data_items_release(client, ds):
    snap('list_data_items_release', client.get(lurl(ds, rel=ds['rel'].id)))


def test_snapshot_list_data_items_valset(client, ds):
    snap('list_data_items_valset', client.get(lurl(ds, vs=ds['vs1'])))


def test_snapshot_list_enum_types_expanded(client, ds):
    snap('list_enum_types_expand',
         client.get(lurl(ds, 'EnumType'), {'expand_id': ds['etype'].id, 'expand_link': 's_link'}))


def test_snapshot_list_application_items(client, ds):
    snap('list_info_items_application', client.get(lurl(ds, 'InfoItem', app=ds['app'].id)))


def test_snapshot_history(client, ds):
    snap('list_history', client.get('/editor/DataItem/%d/0/%d/Sel_All/list_spec_item_history'
                                    % (ds['project'].id, ds['d3'].id)))


def test_snapshot_add_spec_item(client, ds):
    snap('add_spec_item', client.get('/editor/DataItem/%d/0/Sel_All/0/add_spec_item' % ds['project'].id))


def test_snapshot_edit_spec_item(client, ds):
    snap('edit_spec_item', client.get(iurl(ds, 'edit_spec_item', 'DataItem', ds['d1'])))


def test_snapshot_split_spec_item(client, ds):
    snap('split_spec_item', client.get(iurl(ds, 'split_spec_item', 'DataItem', ds['d2'])))


def test_snapshot_del_spec_item(client, ds):
    snap('del_spec_item', client.get(iurl(ds, 'del_spec_item', 'DataItem', ds['d2'])))


def test_snapshot_edit_project(client, ds):
    snap('edit_project', client.get('/editor/%d/edit_project' % ds['project'].id))


def test_snapshot_make_release(client, ds):
    snap('make_project_release', client.get('/editor/%d/make_project_release' % ds['project'].id))


def test_snapshot_upload_file(client, ds):
    snap('import_spec_items', client.get('/editor/DataItem/%d/0/%d/Sel_All/import_spec_items'
                                         % (ds['project'].id, ds['dvs'].id)))


def test_snapshot_generic_form_add_project(client, ds):
    snap('add_project', client.get('/editor/add_project'))


def test_snapshot_generic_form_add_application(client, ds):
    snap('add_application', client.get('/editor/%d/add_application' % ds['project'].id))


def test_snapshot_lockout_template():
    html = render_to_string('lockout.html')
    assert_golden('pages/lockout.html', normalize_html(html))


# ---------------------------------------------------------------------------
# Pages re-rendered after an invalid POST
# ---------------------------------------------------------------------------

def test_snapshot_login_failed_post(client):
    """Failed login: pins the re-rendered page, which must not echo the typed password."""
    make_user('alice')
    response = client.post('/editor/login/', {'username': 'alice', 'password': 'wrong-pw-123'})
    # FIXED: login-echoes-password (was: assert b'value="wrong-pw-123"' in response.content)
    assert b'wrong-pw-123' not in response.content
    assert b'name="username" value="alice"' in response.content
    snap('login_failed_post', response)


def test_snapshot_login_get_has_none_values(client):
    # KNOWN-ISSUE: form-none-literal (unbound form: value="None" rendered in the login inputs)
    response = client.get('/editor/login/')
    assert response.content.count(b'value="None"') == 2


def test_snapshot_edit_spec_item_invalid_post(client, ds):
    d1 = ds['d1']
    response = client.post(iurl(ds, 'edit_spec_item', 'DataItem', d1), {
        'domain': 'Alpha', 'name': 'count', 'title': '', 'desc': 'changed', 'value': '', 'p_kind': 'VAR',
        'val_set': ds['dvs'].id, 'p_link': ds['dtype'].id, 't1': '1', 't2': 'ms',
    })
    html = response.content.decode()
    assert 'is-invalid' in html and 'invalid-feedback' in html
    # KNOWN-ISSUE: p-link-selection-lost (p_link selection not preserved on re-render, str vs int compare)
    p_link_select = html[html.index('id="id_p_link"'):]
    p_link_select = p_link_select[:p_link_select.index('</select>')]
    assert 'selected' not in p_link_select
    snap('edit_spec_item_invalid_post', response)


def test_snapshot_add_spec_item_invalid_post(client, ds):
    response = client.post('/editor/DataItem/%d/0/Sel_All/0/add_spec_item' % ds['project'].id, {
        'domain': 'Alpha', 'name': 'bad name!', 'title': '', 'p_kind': 'VAR',
        'p_link': ds['dtype'].id,
    })
    assert b'is-invalid' in response.content
    snap('add_spec_item_invalid_post', response)


def test_snapshot_add_project_invalid_post(client, ds):
    response = client.post('/editor/add_project', {'name': '', 'description': '', 'owner': ds['owner'].id})
    assert b'is-invalid' in response.content
    snap('add_project_invalid_post', response)


def test_snapshot_make_release_invalid_post(client, ds):
    response = client.post('/editor/%d/make_project_release' % ds['project'].id, {'description': ''})
    assert response.status_code == 200
    snap('make_project_release_invalid_post', response)


def _reset_url(client):
    from django.contrib.auth.models import User
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    user = make_user('resetter')
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    first = client.get('/editor/reset/%s/%s/' % (uid, token))
    assert first.status_code == 302
    return first['Location']


def test_snapshot_password_reset_confirm_get(client):
    # Changed in Task 3.5 (Django 5.2): inputs gain aria-describedby/aria-invalid, error lists an id
    set_url = _reset_url(client)
    snap('password_reset_confirm', client.get(set_url))


def test_snapshot_password_reset_confirm_mismatch_post(client):
    # Changed in Task 3.5 (Django 5.2): inputs gain aria-describedby/aria-invalid, error lists an id
    set_url = _reset_url(client)
    response = client.post(set_url, {'new_password1': 'N3w-Passw0rd-xyz', 'new_password2': 'Different-Pw-987'})
    assert response.status_code == 200
    snap('password_reset_confirm_mismatch_post', response)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_snapshot_pagination_elided_page_7(client, ds, monkeypatch):
    from editor.configs import configs
    monkeypatch.setitem(configs['cats']['EnumType'], 'page_size', 1)
    for i in range(15):
        make_spec_item(ds['project'], cat='EnumType', domain='Pg', name='Pg%02d' % i, title='Paged %02d' % i,
                       status='CNF')
    response = client.get(lurl(ds, 'EnumType'), {'page': 7})
    html = response.content.decode()
    assert '…' in html and 'page-item active' in html
    snap('list_enum_types_page7', response)


# ---------------------------------------------------------------------------
# Flash messages
# ---------------------------------------------------------------------------

def test_snapshot_flash_messages(client, ds):
    """warning (repair), error (CSV header echoing markup), success (import) rendered after a redirect."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    import csv
    import io
    assert client.get('/editor/repair/').status_code == 302          # warning queued
    url = '/editor/DataItem/%d/0/%d/Sel_All/import_spec_items' % (ds['project'].id, ds['dvs'].id)
    bad = b'<b>Dom&amp;ain</b>|Name\r\nx|y\r\n'
    assert client.post(url, {'upload_file': SimpleUploadedFile('bad.csv', bad)}).status_code == 302  # error queued
    labels = ['Domain', 'Name', 'Title', 'Description', 'Value', 'Rationale', 'Remarks', 'Implementation',
              'Type', 'Kind', 'Multiplicity', 'Unit', 'Owner', 'Change Log', 'ValSet']
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=labels, delimiter='|', lineterminator='\r\n')
    w.writeheader()
    w.writerow({'Domain': 'Imp', 'Name': 'imported', 'Title': 'Imported', 'Description': '', 'Value': '5',
                'Rationale': '', 'Remarks': '', 'Implementation': '', 'Type': 'Types:Int32', 'Kind': 'CNS',
                'Multiplicity': '', 'Unit': '', 'Owner': 'x', 'Change Log': '', 'ValSet': 'Default'})
    response = client.post(url, {'upload_file': SimpleUploadedFile('ok.csv', out.getvalue().encode())}, follow=True)
    html = response.content.decode()
    assert 'alert-warning' in html and 'alert-danger' in html and 'alert-success' in html
    assert '&lt;b&gt;Dom&amp;amp;ain&lt;/b&gt;' in html
    snap('flash_messages', response)
