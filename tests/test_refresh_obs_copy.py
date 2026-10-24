"""Task 7.8: refresh-cnf-obs-copy-new-content -- the OBS copy made by a refresh of a CNF item
must hold the PREVIOUS version; the MOD item holds the refreshed content."""
from datetime import datetime, timezone

import pytest

from editor.models import SpecItem
from editor.utilities import get_spec_item_query
from tests.factories import make_application, make_release, make_spec_item
from tests.test_access import Setup
from tests.test_post_only_mutations import ROW, fake_connect

pytestmark = pytest.mark.django_db

OLD_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><desc>old</desc></svg>'
NEW_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><desc>new</desc></svg>'


def setup_item(status):
    s = Setup()
    app = make_application(s.w.project, 'ModApp', cats='Model')
    item = make_spec_item(s.w.project, cat='Model', domain='OldDom', name='OldName', application=app,
                          title='Old title', n1=1, n2=2, n3=77, value=OLD_SVG, p_kind='SM', status=status)
    url = f'/editor/Model/{s.pid}/{app.id}/{item.id}/Sel_All/0/refresh_spec_item'
    return s, app, item, url


# FIXED: refresh-cnf-obs-copy-new-content (was: the OBS copy held the refreshed content)
def test_refresh_cnf_obs_copy_holds_previous_version(client):
    s, app, item, url = setup_item('CNF')
    client.force_login(s.w.owner)
    with fake_connect([ROW]):
        assert client.post(url).status_code == 302
    item.refresh_from_db()
    assert item.status == 'MOD'
    assert (item.domain, item.name, item.value, item.n1, item.n2, item.n3) == \
        ('NewDom', 'NewName', NEW_SVG, 11, 22, 77)
    assert item.title == 'Old title'
    obs = item.previous
    assert obs.status == 'OBS' and obs.id != item.id
    assert (obs.domain, obs.name, obs.title, obs.value, obs.n1, obs.n2, obs.n3, obs.p_kind) == \
        ('OldDom', 'OldName', 'Old title', OLD_SVG, 1, 2, 77, 'SM')
    assert SpecItem.objects.filter(project=s.w.project, cat='Model').count() == 2


# FIXED: refresh-cnf-obs-copy-new-content (was: release views before the refresh showed the new content)
def test_refresh_cnf_release_view_before_refresh_shows_old_content(client):
    s, app, item, url = setup_item('CNF')
    release = make_release(s.w.owner, 1, 0, updated_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
    client.force_login(s.w.owner)
    with fake_connect([ROW]):
        client.post(url)
    vs = item.val_set_id
    shown = list(get_spec_item_query(s.pid, app.id, vs, 'Model', release, 'Sel_All', None))
    assert [(i.status, i.domain, i.name, i.value) for i in shown] == [('OBS', 'OldDom', 'OldName', OLD_SVG)]
    latest = list(get_spec_item_query(s.pid, app.id, vs, 'Model', None, 'Sel_All', None))
    assert [(i.status, i.domain, i.name, i.value) for i in latest] == [('MOD', 'NewDom', 'NewName', NEW_SVG)]


@pytest.mark.parametrize('status', ['NEW', 'MOD'])
def test_refresh_new_or_mod_updates_in_place_without_copy(client, status):
    s, app, item, url = setup_item(status)
    client.force_login(s.w.owner)
    with fake_connect([ROW]):
        client.post(url)
    item.refresh_from_db()
    assert (item.status, item.name, item.value, item.previous) == (status, 'NewName', NEW_SVG, None)
    assert SpecItem.objects.filter(project=s.w.project, cat='Model').count() == 1


@pytest.mark.parametrize('rows', [[], [ROW[:7] + (OLD_SVG,) + ROW[8:]], [ROW[:7] + ('<svg onload="x()"/>',) + ROW[8:]]])
def test_refresh_no_change_not_found_invalid_create_nothing(client, rows):
    s, app, item, url = setup_item('CNF')
    client.force_login(s.w.owner)
    with fake_connect(rows):
        client.post(url)
    item.refresh_from_db()
    assert (item.status, item.name, item.value, item.previous) == ('CNF', 'OldName', OLD_SVG, None)
    assert SpecItem.objects.filter(project=s.w.project, cat='Model').count() == 1
