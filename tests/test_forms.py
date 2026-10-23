"""
Characterization tests for editor/forms.py (plus views.get_find_replace_updates).

Notes on the database: the baseline suite runs on SQLite, whose '=' comparison is
case-sensitive. Production (MySQL) uses a case-insensitive collation, which is why the
code excludes the edited item itself in edit mode. Tests below pin the SQLite behaviour.
"""
import json
from types import SimpleNamespace

import pytest
from django import forms
from django.core.exceptions import ValidationError, FieldDoesNotExist
from django.test import RequestFactory
from django.contrib.messages.storage.cookie import CookieStorage

from editor import ext_cats
from editor.configs import configs, do_cat_specific_checks, get_p_link_choices, get_s_link_choices
from editor.forms import (validate_identifier, identifier_error, ProjectForm, ApplicationForm,
                          ValSetForm, ReleaseForm, FindReplaceForm, SpecItemForm)
from editor.models import SpecItem, ValSet
from editor.utilities import spec_item_to_edit
from editor.views import get_find_replace_updates
from tests.backend import is_mysql
from tests.factories import (make_user, make_project, make_spec_item, make_val_set, make_application,
                             default_val_set)

pytestmark = pytest.mark.django_db

ALL_CATS = list(configs['cats'].keys())
EXT_CATS = [c for c in ALL_CATS if configs['cats'][c]['ext_attrs']]
IDENT_ERR = 'Error: Only alphanumeric characters, underscores and dashes allowed; dots must be internal'


# =============================================================== validate_identifier
@pytest.mark.parametrize('value', ['abc', 'a_b-c', 'a.b', 'a.b.c', '123', 'A1_-', '0.1', 'a-b.c-d'])
def test_validate_identifier_valid(value):
    assert validate_identifier(value) is None


@pytest.mark.parametrize('value', ['.a', 'a.', '..', 'a..b', 'a b', ' a', 'a ', '', 'café', 'a:b',
                                   'a/b', 'a\n', '.', 'a.-.b.', 'a,b', '١'])
def test_validate_identifier_invalid(value):
    with pytest.raises(ValidationError) as exc:
        validate_identifier(value)
    assert exc.value.messages == [IDENT_ERR]
    assert identifier_error == IDENT_ERR


# ====================================================================== ProjectForm
def _project_form_data(owner, **over):
    d = {'name': 'P', 'owner': str(owner.id), 'cats': 'DataItem,VerLink', 'description': 'desc'}
    d.update(over)
    return d


def test_project_form_owner_choices_owner_first():
    owner = make_user('zed')
    a = make_user('alice')
    b = make_user('bob')
    project = make_project(owner)
    form = ProjectForm(project)
    assert form.fields['owner'].choices == [(owner.id, 'zed ( )'), (a.id, 'alice'), (b.id, 'bob')]
    # without a project all users are sorted by username
    form2 = ProjectForm(None)
    assert form2.fields['owner'].choices == [(a.id, 'alice'), (b.id, 'bob'), (owner.id, 'zed')]


def test_project_form_labels_and_widgets():
    owner = make_user()
    form = ProjectForm(None)
    assert form.fields['cats'].label == 'Categories'
    # KNOWN-ISSUE: help-double-space  (predefined_cats is already ', '-joined, then ',' -> ', ' again)
    assert form.fields['cats'].help_text.startswith('A subset of: ParReq,  DerReq,  VerItem,  VerStep,')
    assert form.fields['cats'].help_text == 'A subset of: ' + ',  '.join(configs['cats'].keys())
    assert form.fields['description'].widget.attrs['rows'] == 2
    assert type(form.fields['description'].widget).__name__ == 'Textarea'
    assert form.predefined_cats == ', '.join(configs['cats'].keys())


def test_project_form_valid_and_clean_owner():
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['owner'] == owner
    assert form.cleaned_data['cats'] == 'DataItem,VerLink'


def test_project_form_cats_spaces_stripped():
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner, cats=' DataItem , VerLink '))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['cats'] == 'DataItem,VerLink'


def test_project_form_required_fields():
    form = ProjectForm(None, data={})
    assert not form.is_valid()
    assert set(form.errors) == {'name', 'owner', 'cats', 'description'}


@pytest.mark.parametrize('cats', ['Foo', 'DataItem,Foo', 'DataItem,,VerLink', 'DataItem,VerLink,', 'dataitem'])
def test_project_form_unknown_cat(cats):
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner, cats=cats))
    assert not form.is_valid()
    assert form.errors['cats'] == ['Must contain a comma-separated list of categories from: '
                                   + ', '.join(configs['cats'].keys())]


@pytest.mark.parametrize('cats,msg', [
    # 'tracs' dependency (DataItem has a traceability category VerLink)
    ('DataItem', 'Category DataItem requires dependent category VerLink'),
    # 's_link' expand dependency is checked before p_link and tracs
    ('EnumType', 'Category EnumType requires dependent category EnumValue'),
    # 'p_link' expand dependency
    ('EnumType,EnumValue', 'Category EnumType requires dependent category DataItem'),
    ('DataItemType,VerLink', 'Category DataItemType requires dependent category DataItem'),
    ('DerReq', 'Category DerReq requires dependent category TracLink'),
    ('DerReq,TracLink', 'Category DerReq requires dependent category VerLink'),
])
def test_project_form_missing_dependent_cats(cats, msg):
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner, cats=cats))
    assert not form.is_valid()
    assert len(form.errors['cats']) == 1
    assert form.errors['cats'][0].startswith(msg)


def test_project_form_internal_spaces_are_removed():
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner, cats='Data Item, Ver Link'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['cats'] == 'DataItem,VerLink'


def test_project_form_dependency_messages_exact():
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner, cats='Packet,VerLink'))
    assert not form.is_valid()
    assert form.errors['cats'] == ['Category Packet requires dependent category DerPacket']
    form = ProjectForm(None, data=_project_form_data(owner, cats='Packet,DerPacket,VerLink'))
    assert not form.is_valid()
    assert form.errors['cats'] == ['Category Packet requires dependent category PacketPar']
    form = ProjectForm(None, data=_project_form_data(owner, cats='Packet,DerPacket,PacketPar,VerLink'))
    assert form.is_valid(), form.errors


def test_project_form_full_enum_set_valid():
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(
        owner, cats='EnumType,EnumValue,DataItem,DataItemType,VerLink'))
    assert form.is_valid(), form.errors


def test_project_form_all_cats_valid():
    owner = make_user()
    form = ProjectForm(None, data=_project_form_data(owner, cats=','.join(configs['cats'].keys())))
    assert form.is_valid(), form.errors


def test_project_form_invalid_owner_id():
    owner = make_user()
    data = _project_form_data(owner)
    data['owner'] = '99999'
    form = ProjectForm(None, data=data)
    assert not form.is_valid()
    assert 'owner' in form.errors


# ================================================================= ApplicationForm
def _app_form(project, **over):
    d = {'name': 'A', 'description': 'd', 'cats': 'DataItem'}
    d.update(over)
    return ApplicationForm(project, data=d)


@pytest.fixture
def proj():
    owner = make_user()
    return make_project(owner, cats='DataItem,EnumType,EnumValue,DataItemType')


def test_application_form_init(proj):
    form = ApplicationForm(proj)
    assert form.fields['cats'].label == 'Categories'
    assert form.fields['cats'].help_text == 'A subset of: DataItem, EnumType, EnumValue, DataItemType'
    assert form.fields['description'].widget.attrs['rows'] == 2
    assert form.fields['cats'].widget.attrs['rows'] == 2


def test_application_form_valid(proj):
    form = _app_form(proj, cats='DataItem, EnumType')
    assert form.is_valid(), form.errors
    assert form.cleaned_data['cats'] == 'DataItem,EnumType'


def test_application_form_required(proj):
    form = ApplicationForm(proj, data={})
    assert not form.is_valid()
    assert set(form.errors) == {'name', 'description', 'cats'}


def test_application_form_cat_not_in_project(proj):
    form = _app_form(proj, cats='DataItem,Requirement')
    assert not form.is_valid()
    assert form.errors['cats'] == ['Must contain a comma-separated list of categories from: '
                                   'DataItem,EnumType,EnumValue,DataItemType']


@pytest.mark.parametrize('cats', ['Item', 'Enum', 'Type,Value', 'DataItem,,EnumType', 'DataItemTyp'])
def test_application_form_substring_of_project_cats_accepted(proj, cats):
    # KNOWN-ISSUE: appform-cats-substring  (membership is tested on the project.cats STRING, so any
    # substring such as 'Item' or even '' (from ',,') is accepted)
    form = _app_form(proj, cats=cats)
    assert form.is_valid(), form.errors
    assert form.cleaned_data['cats'] == cats


def test_application_form_trailing_comma_accepted(proj):
    # KNOWN-ISSUE: appform-cats-substring  ('' is a substring of project.cats)
    form = _app_form(proj, cats='DataItem,')
    assert form.is_valid()
    assert form.cleaned_data['cats'] == 'DataItem,'


# ============================================================== ValSetForm/ReleaseForm
def test_valset_and_release_forms():
    f = ValSetForm(data={'name': 'VS', 'description': 'd'})
    assert f.is_valid()
    assert f.fields['description'].widget.attrs == {'size': '255', 'cols': '40', 'rows': 2}
    assert not ValSetForm(data={}).is_valid()
    r = ReleaseForm(data={'description': 'x'})
    assert r.is_valid() and r.cleaned_data == {'description': 'x'}
    assert not ReleaseForm(data={}).is_valid()


# ================================================================= FindReplaceForm
def test_find_replace_form():
    assert list(FindReplaceForm().fields) == ['field', 'find', 'replace']
    f = FindReplaceForm(data={'field': 'title', 'find': 'a', 'replace': 'b'})
    assert f.is_valid()
    assert not FindReplaceForm(data={'field': 'title', 'find': 'a'}).is_valid()
    long = 'x' * 256
    f = FindReplaceForm(data={'field': 'title', 'find': long, 'replace': 'b'})
    assert not f.is_valid() and 'find' in f.errors
    # find==replace is NOT rejected by the form itself (it is rejected by get_find_replace_updates)
    assert FindReplaceForm(data={'field': 'title', 'find': 'a', 'replace': 'a'}).is_valid()


# ======================================================= get_find_replace_updates
@pytest.fixture
def fr():
    owner = make_user()
    project = make_project(owner)
    et = make_spec_item(project, 'EnumType', 'D', 'T1', status='CNF')
    a = make_spec_item(project, 'DataItem', 'D', 'alpha', status='CNF', p_link=et, title='Alpha one')
    b = make_spec_item(project, 'DataItem', 'D', 'beta', status='CNF', p_link=et, title='Beta one')
    return dict(project=project, vs=default_val_set(project), et=et, a=a, b=b)


def _gfr(fr, field, find, replace, items=None):
    items = items if items is not None else SpecItem.objects.filter(project_id=fr['project'].id, cat='DataItem')
    return get_find_replace_updates(items, fr['project'].id, fr['vs'].id, field, find, replace)


def test_gfr_find_equals_replace(fr):
    with pytest.raises(ValidationError) as e:
        _gfr(fr, 'title', 'x', 'x')
    assert e.value.messages == ['Error: Find and replace values must be different']


def test_gfr_title_updates(fr):
    updates = _gfr(fr, 'title', 'one', 'two')
    assert sorted((i.name, v) for i, v in updates) == [('alpha', 'Alpha two'), ('beta', 'Beta two')]
    # nothing is saved
    fr['a'].refresh_from_db()
    assert fr['a'].title == 'Alpha one'


def test_gfr_non_matching_items_skipped(fr):
    assert _gfr(fr, 'title', 'Alpha', 'Gamma') == [(fr['a'], 'Gamma one')]
    assert _gfr(fr, 'title', 'zzz', 'y') == []


def test_gfr_unknown_field(fr):
    with pytest.raises(FieldDoesNotExist):
        _gfr(fr, 'nonexistent', 'a', 'b')


def test_gfr_non_string_field_skipped(fr):
    assert _gfr(fr, 'n1', '0', '1') == []
    assert _gfr(fr, 'p_link', '1', '2') == []


def test_gfr_identifier_validation_on_replace(fr):
    for field in ('domain', 'name'):
        for bad in ('', 'a b', 'a..b', '.a', 'x:y'):
            with pytest.raises(ValidationError) as e:
                _gfr(fr, field, 'a', bad)
            assert e.value.messages == [IDENT_ERR]


def test_gfr_identifier_validation_not_applied_to_other_fields(fr):
    assert _gfr(fr, 'title', 'Alpha', 'a b..c')[0][1] == 'a b..c one'


def test_gfr_name_update_ok(fr):
    updates = _gfr(fr, 'name', 'alpha', 'gamma')
    assert [(i.name, v) for i, v in updates] == [('alpha', 'gamma')]


def test_gfr_duplicate_with_unselected_item(fr):
    with pytest.raises(ValidationError) as e:
        _gfr(fr, 'name', 'alpha', 'beta')
    assert e.value.messages == ["Error: Name 'beta' already exists in domain 'D'"]


def test_gfr_duplicate_between_two_updated_items(fr):
    p = fr['project']
    make_spec_item(p, 'DataItem', 'D', 'a1', status='CNF', p_link=fr['et'])
    make_spec_item(p, 'DataItem', 'D', '1a', status='CNF', p_link=fr['et'])
    with pytest.raises(ValidationError) as e:
        _gfr(fr, 'name', '1', 'a')            # a1 -> aa and 1a -> aa
    assert e.value.messages == ["Error: Name 'aa' already exists in domain 'D'"]


def test_gfr_duplicate_after_domain_change(fr):
    other = make_spec_item(fr['project'], 'DataItem', 'E', 'alpha', status='CNF', p_link=fr['et'])
    with pytest.raises(ValidationError) as e:
        _gfr(fr, 'domain', 'D', 'E', items=SpecItem.objects.filter(id=fr['a'].id))
    assert e.value.messages == ["Error: Name 'alpha' already exists in domain 'E'"]


def test_gfr_duplicate_ignores_del_obs_and_other_valsets(fr):
    make_spec_item(fr['project'], 'DataItem', 'D', 'gamma', status='DEL', p_link=fr['et'])
    make_spec_item(fr['project'], 'DataItem', 'D', 'gamma', status='OBS', p_link=fr['et'])
    vs1 = make_val_set(fr['project'])
    make_spec_item(fr['project'], 'DataItem', 'D', 'gamma', status='CNF', p_link=fr['et'], val_set=vs1)
    updates = _gfr(fr, 'name', 'alpha', 'gamma')
    assert [(i.name, v) for i, v in updates] == [('alpha', 'gamma')]


def test_gfr_model_field_clean_max_length(fr):
    with pytest.raises(ValidationError):
        _gfr(fr, 'title', 'Alpha one', 'x' * 256)


def test_gfr_model_field_clean_blank(fr):
    # replacing the whole title by '' is rejected by the model field (blank=False)
    with pytest.raises(ValidationError):
        _gfr(fr, 'title', 'Alpha one', '')


def test_gfr_domain_name_duplicate_check_skipped_for_other_fields(fr):
    # two items with the same domain:name in different statuses do not matter for 'title'
    make_spec_item(fr['project'], 'DataItem', 'D', 'alpha', status='CNF', p_link=fr['et'])
    assert len(_gfr(fr, 'title', 'one', 'two')) == 2


def test_gfr_case_only_rename_allowed(fr):
    updates = _gfr(fr, 'name', 'alpha', 'Alpha')
    assert [(i.name, v) for i, v in updates] == [('alpha', 'Alpha')]


# =============================================================== SpecItemForm helpers
def _request(user=None):
    request = RequestFactory().get('/')
    request.user = user or SimpleNamespace(email='alice@example.com', username='alice')
    request._messages = CookieStorage(request)
    return request


@pytest.fixture
def fake_fw_db(monkeypatch):
    """Fake only MySQLdb.connect (rule 7): one diagram owned by the requesting user."""
    smtags = 'DomFcp'
    fw_json = json.dumps({'globals': {'fwprop': {'smTags': smtags}},
                          'states': [{'fwprop': {'note': 'Title: My FCP\nLong\ndescription'}}]})
    diagram = (11, 0, 'mname', 0, 'StateMachine', 'upd', fw_json, '<svg>1</svg>', 10, 20)

    class Cur:
        rows = []

        def execute(self, sql):
            if 'FROM users' in sql:
                self.rows = [(7,)]
            elif 'WHERE userID' in sql or 'WHERE ID' in sql:
                self.rows = [diagram]
            else:
                self.rows = []

        def fetchall(self):
            return self.rows

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    monkeypatch.setattr(ext_cats.mdb, 'connect', lambda *a, **k: Conn())
    return diagram


@pytest.fixture
def world():
    owner = make_user()
    cats = ','.join(configs['cats'].keys())
    project = make_project(owner, cats=cats)
    etype = make_spec_item(project, 'EnumType', 'D', 'T1', status='CNF', title='t', desc='d')
    return dict(owner=owner, project=project, etype=etype, vs=default_val_set(project))


def build(world, mode, cat='DataItem', data=None, initial=None, item=None, application=None,
          s_parent_id=None, p_parent_id=None, item_id=None, request=None):
    """Construct a SpecItemForm like views.py does."""
    if item is not None and initial is None:
        initial = spec_item_to_edit(item)
        item_id = item.id if item_id is None else item_id
    kwargs = {'item_id': item_id}
    if data is not None:
        kwargs['data'] = data
    if initial is not None:
        kwargs['initial'] = initial
    return SpecItemForm(mode, request or _request(), cat, world['project'], application,
                        configs['cats'][cat], s_parent_id, p_parent_id, **kwargs)


def fi(form, name):
    f = form.fields[name]
    return (type(f.widget).__name__, f.required, f.label, f.disabled)


# =================================================== add mode over ALL 30 categories
def _expected_field(cat, name, base_field):
    """Re-derive from configs.json the expected (widget, required, label) of a field in add mode."""
    cfg = configs['cats'][cat]
    attrs, ext = cfg['attrs'], cfg['ext_attrs']
    base_widget = type(base_field.widget).__name__
    if name == 'submit':
        return ('HiddenInput', False, 'Submit', False)
    if name == 'cancel':
        return ('HiddenInput', False, 'Cancel', False)
    if name == 'ext_item' and ext:
        return ('Select', True, cat, False)
    if name not in attrs or name in ext:
        return ('HiddenInput', False, None, False)
    required = base_field.required and attrs[name]['req_in_form']
    widget = 'HiddenInput' if name == 'val_set' else base_widget
    return (widget, required, attrs[name]['label'], False)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_add_mode_fields_table(world, fake_fw_db, cat):
    form = build(world, 'add', cat)
    assert list(form.fields) == list(SpecItemForm.base_fields)
    for name, field in form.fields.items():
        expected = _expected_field(cat, name, SpecItemForm.base_fields[name])
        assert fi(form, name) == expected, (cat, name)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_add_mode_kind_choices_and_links(world, fake_fw_db, cat):
    form = build(world, 'add', cat)
    cfg = configs['cats'][cat]
    assert form.fields['p_kind'].choices == list(cfg['p_kind_choices'].items())
    assert form.fields['s_kind'].choices == list(cfg['s_kind_choices'].items())
    assert list(form.fields['p_link'].queryset) == list(
        get_p_link_choices(cat, world['project'], None, None, None))
    assert list(form.fields['s_link'].queryset) == list(
        get_s_link_choices(cat, world['project'], None, None, None))
    assert form.fields['p_link'].empty_label == ''
    assert form.fields['s_link'].empty_label == ''
    assert form.fields['val_set'].empty_label is None
    assert form.fields['submit'].label == 'Submit'
    assert form.fields['cancel'].help_text == '/editor/%s/%d/0/%d/Sel_All/0/list_spec_items' % (
        cat, world['project'].id, world['vs'].id)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_add_mode_empty_post_required_errors(world, fake_fw_db, cat):
    form = build(world, 'add', cat, data={})
    assert not form.is_valid()
    cfg = configs['cats'][cat]
    expected = {n for n, a in cfg['attrs'].items()
                if a['req_in_form'] and n not in cfg['ext_attrs'] and n not in ('val_set', 'owner')
                and n in SpecItemForm.base_fields}
    if cfg['ext_attrs']:
        expected.add('ext_item')
    assert set(form.errors) == expected, cat


@pytest.mark.parametrize('cat', ALL_CATS)
def test_add_mode_textarea_row_attrs(world, fake_fw_db, cat):
    form = build(world, 'add', cat)
    for name in ('desc', 'value', 'rationale', 'implementation', 'remarks', 'change_log',
                 't1', 't2', 't3', 't4', 't5'):
        widget = form.fields[name].widget
        if type(widget).__name__ == 'HiddenInput':      # hidden fields get a fresh widget
            assert widget.attrs == {}
            continue
        assert widget.attrs.get('rows') == 1
        assert widget.attrs.get('class') == 'link-suggest'


# ------------------- hard-coded snapshot of 3 categories (guards against library changes)
SNAPSHOT_ADD = {
    'DataItem': {
        'domain': ('TextInput', True, 'Domain', False),
        'name': ('TextInput', True, 'Name', False),
        'title': ('TextInput', False, 'Title', False),
        'desc': ('Textarea', False, 'Description', False),
        'value': ('Textarea', True, 'Value', False),
        'rationale': ('Textarea', False, 'Rationale', False),
        'implementation': ('Textarea', False, 'Implementation', False),
        'remarks': ('Textarea', False, 'Remarks', False),
        'change_log': ('Textarea', False, 'Change Log', False),
        's_data': ('HiddenInput', False, None, False),
        'p_kind': ('Select', True, 'Kind', False),
        's_kind': ('HiddenInput', False, None, False),
        'val_set': ('HiddenInput', False, 'ValSet', False),
        'p_link': ('Select', True, 'Type', False),
        's_link': ('HiddenInput', False, None, False),
        'n1': ('HiddenInput', False, None, False),
        'n2': ('HiddenInput', False, None, False),
        'n3': ('HiddenInput', False, None, False),
        't1': ('Textarea', False, 'Multiplicity', False),
        't2': ('Textarea', False, 'Unit', False),
        't3': ('HiddenInput', False, None, False),
        't4': ('HiddenInput', False, None, False),
        't5': ('HiddenInput', False, None, False),
        'ext_item': ('HiddenInput', False, None, False),
        'submit': ('HiddenInput', False, 'Submit', False),
        'cancel': ('HiddenInput', False, 'Cancel', False),
    },
    'Requirement': {
        'domain': ('TextInput', True, 'Domain', False),
        'name': ('TextInput', True, 'Name', False),
        'title': ('TextInput', False, 'Title', False),
        'desc': ('HiddenInput', False, None, False),
        'value': ('Textarea', True, 'Text', False),
        'rationale': ('Textarea', False, 'Rationale', False),
        'implementation': ('Textarea', False, 'Implementation', False),
        'remarks': ('Textarea', False, 'Remarks', False),
        'change_log': ('Textarea', False, 'Change Log', False),
        's_data': ('HiddenInput', False, None, False),
        'p_kind': ('Select', True, 'Kind', False),
        's_kind': ('Select', True, 'Ver', False),
        'val_set': ('HiddenInput', False, 'ValSet', False),
        'p_link': ('HiddenInput', False, None, False),
        's_link': ('HiddenInput', False, None, False),
        'n1': ('HiddenInput', False, None, False),
        'n2': ('HiddenInput', False, None, False),
        'n3': ('HiddenInput', False, None, False),
        't1': ('Textarea', False, 'Close Out', False),
        't2': ('Textarea', False, 'Validation', False),
        't3': ('HiddenInput', False, None, False),
        't4': ('HiddenInput', False, None, False),
        't5': ('HiddenInput', False, None, False),
        'ext_item': ('HiddenInput', False, None, False),
        'submit': ('HiddenInput', False, 'Submit', False),
        'cancel': ('HiddenInput', False, 'Cancel', False),
    },
}


@pytest.mark.parametrize('cat', ['DataItem', 'Requirement'])
def test_add_mode_snapshot(world, cat):
    form = build(world, 'add', cat)
    assert {n: fi(form, n) for n in form.fields} == SNAPSHOT_ADD[cat]


def test_add_mode_snapshot_model_external(world, fake_fw_db):
    form = build(world, 'add', 'Model')
    assert {n: fi(form, n) for n in form.fields} == SNAPSHOT_ADD_MODEL_DATA
    assert form.fields['ext_item'].choices == [(11, 'DomFcp : mname')]


SNAPSHOT_ADD_MODEL_DATA = {
    'domain': ('HiddenInput', False, None, False),
    'name': ('HiddenInput', False, None, False),
    'title': ('TextInput', True, 'Title', False),
    'desc': ('Textarea', False, 'Description', False),
    'value': ('HiddenInput', False, None, False),
    'rationale': ('Textarea', False, 'Rationale', False),
    'implementation': ('Textarea', False, 'Implementation', False),
    'remarks': ('Textarea', False, 'Remarks', False),
    'change_log': ('Textarea', False, 'Change Log', False),
    's_data': ('HiddenInput', False, None, False),
    'p_kind': ('Select', True, 'Kind', False),
    's_kind': ('HiddenInput', False, None, False),
    'val_set': ('HiddenInput', False, 'ValSet', False),
    'p_link': ('HiddenInput', False, None, False),
    's_link': ('HiddenInput', False, None, False),
    'n1': ('HiddenInput', False, None, False),
    'n2': ('HiddenInput', False, None, False),
    'n3': ('HiddenInput', False, None, False),
    't1': ('Textarea', False, 'Diag Scale', False),
    't2': ('HiddenInput', False, None, False),
    't3': ('HiddenInput', False, None, False),
    't4': ('HiddenInput', False, None, False),
    't5': ('HiddenInput', False, None, False),
    'ext_item': ('Select', True, 'Model', False),
    'submit': ('HiddenInput', False, 'Submit', False),
    'cancel': ('HiddenInput', False, 'Cancel', False),
}


# ============================================================ mode specific behaviour
@pytest.fixture
def item(world):
    return make_spec_item(world['project'], 'DataItem', 'D', 'x', status='CNF', p_link=world['etype'],
                          title='Title x', value='1', p_kind='CNS', desc='see #iref:%d' % world['etype'].id)


def test_edit_mode_fields(world, item):
    form = build(world, 'edit', item=item)
    assert form.fields['val_set'].disabled is True
    assert type(form.fields['val_set'].widget).__name__ == 'Select'
    assert list(form.fields['val_set'].queryset) == [world['vs']]
    assert form.fields['domain'].disabled is False and form.fields['name'].disabled is False
    assert fi(form, 'p_link') == ('Select', True, 'Type', False)
    assert form.fields['submit'].label == 'Submit'
    assert form.initial['desc'] == 'see #EnumType:D:T1'


def test_copy_mode_fields(world, item):
    form = build(world, 'copy', item=item)
    assert form.fields['val_set'].disabled is True
    assert list(form.fields['val_set'].queryset) == [world['vs']]
    assert fi(form, 'domain') == ('TextInput', True, 'Domain', False)
    assert form.fields['submit'].label == 'Submit'


def test_split_mode_fields(world, item):
    vs1 = make_val_set(world['project'], 'AAA')
    form = build(world, 'split', item=item)
    assert fi(form, 'domain') == ('TextInput', True, 'Domain', True)
    assert fi(form, 'name') == ('TextInput', True, 'Name', True)
    assert fi(form, 'p_link') == ('HiddenInput', True, 'Type', True)
    assert fi(form, 's_link') == ('HiddenInput', False, None, True)
    assert form.fields['val_set'].disabled is False
    assert list(form.fields['val_set'].queryset) == [vs1, world['vs']]      # ordered by name


def test_split_mode_val_set_widget(world, item):
    # val_set is not hidden in split mode (only add mode hides it)
    form = build(world, 'split', item=item)
    assert type(form.fields['val_set'].widget).__name__ == 'Select'


def test_del_mode_fields(world, item):
    form = build(world, 'del', item=item)
    assert form.fields['submit'].label == 'Delete'
    for name in ('domain', 'name', 'title', 'desc', 'value', 'rationale', 'implementation', 'remarks',
                 'p_kind', 'val_set', 'p_link', 't1', 't2'):
        assert form.fields[name].disabled is True, name
    assert form.fields['change_log'].disabled is False
    # fields not in the category attrs are not disabled
    assert form.fields['n1'].disabled is False
    assert form.fields['submit'].disabled is False
    assert list(form.fields['val_set'].queryset) == [world['vs']]


def test_edit_mode_requires_initial_val_set(world):
    with pytest.raises(KeyError):
        build(world, 'edit', data={}, initial={})


def test_labels_in_all_modes_come_from_config(world, item):
    for mode in ('edit', 'copy', 'split', 'del'):
        form = build(world, mode, item=item)
        assert form.fields['t1'].label == 'Multiplicity'
        assert form.fields['p_link'].label == 'Type'
        assert form.fields['p_kind'].label == 'Kind'


def test_p_link_s_link_with_parent_ids(world, item):
    form = build(world, 'add', 'DataItem', p_parent_id=str(world['etype'].id))
    assert list(form.fields['p_link'].queryset) == [world['etype']]
    form = build(world, 'add', 'DataItem', s_parent_id=str(item.id))
    assert list(form.fields['s_link'].queryset) == [item]


def test_add_mode_dataitem_p_link_choices_contents(world):
    q = make_spec_item(world['project'], 'DataItemType', 'A', 'dt', status='CNF')
    make_spec_item(world['project'], 'DataItemType', 'A', 'gone', status='DEL')
    form = build(world, 'add', 'DataItem')
    assert list(form.fields['p_link'].queryset) == [q, world['etype']]
    assert list(form.fields['s_link'].queryset) == []


def test_application_cancel_location(world):
    app = make_application(world['project'], cats='Requirement')
    form = build(world, 'add', 'Requirement', application=app)
    assert form.fields['cancel'].help_text == '/editor/Requirement/%d/%d/%d/Sel_All/0/list_spec_items' % (
        world['project'].id, app.id, world['vs'].id)


# ====================================================================== clean_s_data
def dataitem_post(world, **over):
    d = {'domain': 'D', 'name': 'new', 'title': 'T', 'desc': '', 'value': '5', 'rationale': '',
         'implementation': '', 'remarks': '', 'change_log': '', 'p_kind': 'CNS',
         'p_link': str(world['etype'].id), 't1': '', 't2': ''}
    d.update(over)
    return d


def test_clean_s_data_none_becomes_string_braces(world):
    dt = make_spec_item(world['project'], 'DataItemType', 'T', 'int', status='CNF')
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id)))
    assert form.is_valid(), form.errors
    # KNOWN-ISSUE: s-data-string  (None is replaced by the STRING '{}', not by an empty dict)
    assert form.cleaned_data['s_data'] == '{}'


def test_clean_s_data_given_json(world):
    dt = make_spec_item(world['project'], 'DataItemType', 'T', 'int', status='CNF')
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), s_data='{"a": 1}'))
    assert form.is_valid(), form.errors
    # s_data is hidden for DataItem but still processed when posted
    assert form.cleaned_data['s_data'] == {'a': 1}


def test_clean_s_data_invalid_json(world):
    dt = make_spec_item(world['project'], 'DataItemType', 'T', 'int', status='CNF')
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), s_data='{bad'))
    assert not form.is_valid()
    assert 's_data' in form.errors


# ================================================================ SpecItemForm.clean
@pytest.fixture
def dt(world):
    return make_spec_item(world['project'], 'DataItemType', 'T', 'int', status='CNF')


def test_add_valid_converts_ref_text_and_eval_ref(world, dt):
    other = make_spec_item(world['project'], 'DataItem', 'D', 'other', status='CNF', p_link=dt, value='3')
    form = build(world, 'add', data=dataitem_post(
        world, p_link=str(dt.id), desc='see #EnumType:D:T1 and #DataItem:D:other',
        value='#DataItem:D:other*2', rationale='#DataItem:D:nope', change_log='c'))
    assert form.is_valid(), form.errors
    cd = form.cleaned_data
    assert cd['desc'] == 'see #iref:%d and #iref:%d' % (world['etype'].id, other.id)
    assert cd['value'] == '#iref:%d*2' % other.id
    assert cd['rationale'] == '#DataItem:D:nope'           # invalid refs are left unchanged
    assert cd['p_link'] == dt
    assert cd['val_set'] is None
    assert cd['n1'] is None


def test_add_duplicate_domain_name(world, dt):
    make_spec_item(world['project'], 'DataItem', 'D', 'new', status='CNF', p_link=dt)
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id)))
    assert not form.is_valid()
    assert form.errors['name'] == ["Error: Name 'new' already exists in domain 'D'"]
    assert form.non_field_errors() == []


@pytest.mark.parametrize('status', ['NEW', 'MOD', 'CNF'])
def test_add_duplicate_detected_for_active_statuses(world, dt, status):
    make_spec_item(world['project'], 'DataItem', 'D', 'new', status=status, p_link=dt)
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id)))
    assert not form.is_valid()
    assert 'name' in form.errors


@pytest.mark.parametrize('status', ['DEL', 'OBS'])
def test_add_duplicate_ignored_for_del_obs(world, dt, status):
    make_spec_item(world['project'], 'DataItem', 'D', 'new', status=status, p_link=dt)
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id)))
    assert form.is_valid(), form.errors


def test_add_duplicate_only_in_default_val_set(world, dt):
    vs1 = make_val_set(world['project'])
    make_spec_item(world['project'], 'DataItem', 'D', 'new', status='CNF', p_link=dt, val_set=vs1)
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id)))
    assert form.is_valid(), form.errors


def test_add_duplicate_in_other_project_ignored(world, dt):
    other_proj = make_project(world['owner'], name='Other')
    odt = make_spec_item(other_proj, 'DataItemType', 'T', 'int', status='CNF')
    make_spec_item(other_proj, 'DataItem', 'D', 'new', status='CNF', p_link=odt)
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id)))
    assert form.is_valid(), form.errors


def test_add_duplicate_case_difference(world, dt):
    # Backend dependent: SQLite compares case-sensitively, so a case-only difference is NOT a
    # duplicate; MySQL's case-insensitive collation (production) rejects it.
    make_spec_item(world['project'], 'DataItem', 'D', 'NEW1', status='CNF', p_link=dt)
    form = build(world, 'add', data=dataitem_post(world, name='new1', p_link=str(dt.id)))
    if is_mysql():
        assert not form.is_valid()
        assert form.errors['name'] == ["Error: Name 'new1' already exists in domain 'D'"]
    else:
        assert form.is_valid(), form.errors


def test_add_invalid_identifier_errors(world, dt):
    form = build(world, 'add', data=dataitem_post(world, domain='a b', name='.x', p_link=str(dt.id)))
    assert not form.is_valid()
    assert form.errors['domain'] == [IDENT_ERR]
    assert form.errors['name'] == [IDENT_ERR]


def test_add_max_length(world, dt):
    form = build(world, 'add', data=dataitem_post(world, name='n' * 256, p_link=str(dt.id)))
    assert not form.is_valid()
    assert 'name' in form.errors


def test_copy_duplicate_domain_name(world, dt, item):
    form = build(world, 'copy', item=item, data=dataitem_post(world, name='x', p_link=str(dt.id)))
    assert not form.is_valid()
    assert form.errors['name'] == ["Error: Name 'x' already exists in domain 'D'"]


def test_copy_new_name_ok_and_val_set_from_initial(world, dt, item):
    form = build(world, 'copy', item=item, data=dataitem_post(world, name='x2', p_link=str(dt.id),
                                                               val_set='99999'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['val_set'] == world['vs']     # disabled: data ignored


def test_edit_unchanged_name_not_checked(world, dt, item):
    # a pre-existing duplicate is not reported if domain/name are unchanged
    make_spec_item(world['project'], 'DataItem', 'D', 'x', status='NEW', p_link=dt)
    form = build(world, 'edit', item=item, data=dataitem_post(world, name='x', p_link=str(dt.id), title='T2'))
    assert form.is_valid(), form.errors


def test_edit_changed_name_duplicate(world, dt, item):
    make_spec_item(world['project'], 'DataItem', 'D', 'y', status='CNF', p_link=dt)
    form = build(world, 'edit', item=item, data=dataitem_post(world, name='y', p_link=str(dt.id)))
    assert not form.is_valid()
    assert form.errors['name'] == ["Error: Name 'y' already exists in domain 'D'"]


def test_edit_changed_domain_duplicate(world, dt, item):
    make_spec_item(world['project'], 'DataItem', 'E', 'x', status='CNF', p_link=dt)
    form = build(world, 'edit', item=item, data=dataitem_post(world, domain='E', name='x', p_link=str(dt.id)))
    assert not form.is_valid()
    assert form.errors['name'] == ["Error: Name 'x' already exists in domain 'E'"]


def test_edit_changed_name_to_free_name_ok(world, dt, item):
    form = build(world, 'edit', item=item, data=dataitem_post(world, name='free', p_link=str(dt.id)))
    assert form.is_valid(), form.errors


def test_edit_case_only_rename_allowed(world, dt, item):
    form = build(world, 'edit', item=item, data=dataitem_post(world, domain='d', name='X', p_link=str(dt.id)))
    assert 'name' in form.changed_data and 'domain' in form.changed_data
    assert form.is_valid(), form.errors


def test_edit_form_keeps_item_id_for_self_exclusion(world, dt, item):
    # On a case-insensitive collation (MySQL) the duplicate query would match the item's own row;
    # the form excludes item_id to accept a case-only rename. SQLite cannot reproduce the collation,
    # so only the item_id plumbing and the accepted rename are pinned here.
    form = build(world, 'edit', item=item, data=dataitem_post(world, name='X', p_link=str(dt.id)))
    assert form.item_id == item.id
    assert form.is_valid(), form.errors


def test_edit_without_item_id_still_validates(world, dt, item):
    form = build(world, 'edit', initial=spec_item_to_edit(item), data=dataitem_post(world, name='zzz', p_link=str(dt.id)))
    assert form.item_id is None
    assert form.is_valid(), form.errors


def test_split_duplicate_val_set(world, dt, item):
    vs1 = make_val_set(world['project'], 'VS1')
    make_spec_item(world['project'], 'DataItem', 'D', 'x', status='CNF', p_link=dt, val_set=vs1)
    form = build(world, 'split', item=item, data=dataitem_post(world, val_set=str(vs1.id), p_link=str(dt.id)))
    assert not form.is_valid()
    assert form.non_field_errors() == ['Split Error: ValSet is already in use for this domain:name']


def test_split_into_own_val_set_is_duplicate(world, dt, item):
    form = build(world, 'split', item=item, data=dataitem_post(world, val_set=str(world['vs'].id)))
    assert not form.is_valid()
    assert form.non_field_errors() == ['Split Error: ValSet is already in use for this domain:name']


def test_split_free_val_set_ok_and_domain_name_from_initial(world, dt):
    di = make_spec_item(world['project'], 'DataItem', 'D', 'x', status='CNF', p_link=dt, p_kind='CNS',
                        title='t', value='1')
    vs1 = make_val_set(world['project'], 'VS1')
    make_spec_item(world['project'], 'DataItem', 'D', 'x', status='DEL', p_link=dt, val_set=vs1)
    form = build(world, 'split', item=di,
                 data=dataitem_post(world, domain='ignored', name='ignored', val_set=str(vs1.id), value='7',
                                    p_link='99999'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['domain'] == 'D' and form.cleaned_data['name'] == 'x'
    assert form.cleaned_data['val_set'] == vs1
    assert form.cleaned_data['p_link'] == dt        # p_link comes from initial (disabled)


def test_split_category_specific_check_still_applies(world, item):
    vs1 = make_val_set(world['project'], 'VS1')
    # item.p_link is an EnumType: the value must reference an EnumValue
    form = build(world, 'split', item=item, data=dataitem_post(world, val_set=str(vs1.id), value='7'))
    assert not form.is_valid()
    assert form.non_field_errors() == ['Data item value must be a reference to an enumerated value of the item type']


def test_del_mode_valid_with_only_change_log(world, dt):
    di = make_spec_item(world['project'], 'DataItem', 'D', 'z', status='CNF', p_link=dt, title='t', value='1',
                          p_kind='CNS')
    form = build(world, 'del', item=di, data={'change_log': 'bye'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['change_log'] == 'bye'
    assert form.cleaned_data['name'] == 'z'
    assert form.cleaned_data['p_link'] == dt


def test_del_mode_no_duplicate_checks(world, dt):
    di = make_spec_item(world['project'], 'DataItem', 'D', 'z', status='CNF', p_link=dt, title='t', value='1',
                        p_kind='CNS')
    make_spec_item(world['project'], 'DataItem', 'D', 'z', status='NEW', p_link=dt, title='t', value='1')
    form = build(world, 'del', item=di, data={'change_log': ''})
    assert form.is_valid(), form.errors


def test_del_mode_posted_values_ignored(world, dt):
    di = make_spec_item(world['project'], 'DataItem', 'D', 'z', status='CNF', p_link=dt, title='t', value='1',
                          p_kind='CNS')
    form = build(world, 'del', item=di, data={'name': 'other', 'title': 'other'})
    assert form.is_valid(), form.errors
    assert form.cleaned_data['name'] == 'z'
    assert form.cleaned_data['title'] == 't'


# ---------------------------------------------------------- eval_ref rules in clean
def test_eval_ref_reference_to_cat_without_field(world, dt):
    make_spec_item(world['project'], 'DerPacket', 'P', 'dp', status='CNF')
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), value='#DerPacket:P:dp+1'))
    assert not form.is_valid()
    assert form.non_field_errors() == [
        "The field \"value\" of kind eval_ref contains internal reference ('DerPacket', 'P', 'dp') "
        "to a spec_item which does not support field \"value\""]


def test_eval_ref_reference_to_non_eval_ref_field(world, dt):
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), value='#EnumType:D:T1+1'))
    assert not form.is_valid()
    assert form.non_field_errors() == [
        "The field \"value\" of kind eval_ref contains internal reference ('EnumType', 'D', 'T1') "
        "to a spec_item whose field \"value\" is not of kind eval_ref"]


def test_eval_ref_reference_check_does_not_need_existing_target(world, dt):
    # only the category of the reference is inspected: a nonexistent DataItem is accepted
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), value='#DataItem:D:ghost+1'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['value'] == '#DataItem:D:ghost+1'


def test_eval_ref_checked_before_duplicate_name(world, dt):
    make_spec_item(world['project'], 'DataItem', 'D', 'new', status='CNF', p_link=dt)
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), value='#EnumType:D:T1'))
    assert not form.is_valid()
    # the ValidationError aborts clean() before the duplicate check can add its error
    assert 'name' not in form.errors
    assert len(form.non_field_errors()) == 1


def test_eval_ref_in_enum_value_field(world):
    form = build(world, 'add', 'EnumValue', data={
        'domain': 'D', 'name': 'v1', 'title': 'T', 'desc': '', 'value': '#EnumType:D:T1',
        'rationale': '', 'remarks': '', 'implementation': '', 'change_log': '',
        's_link': str(world['etype'].id)})
    assert not form.is_valid()
    assert form.non_field_errors()[0].endswith('is not of kind eval_ref')


def test_clean_returns_early_when_field_errors(world):
    form = build(world, 'add', data=dataitem_post(world, domain='bad domain'))
    assert not form.is_valid()
    assert form.non_field_errors() == []


# --------------------------------------------- do_cat_specific_checks for DataItem
@pytest.fixture
def enum_world(world):
    p = world['project']
    et = world['etype']
    ev = make_spec_item(p, 'EnumValue', 'D', 'v1', status='CNF', s_link=et, value='1')
    et2 = make_spec_item(p, 'EnumType', 'D', 'T2', status='CNF')
    ev2 = make_spec_item(p, 'EnumValue', 'D', 'v2', status='CNF', s_link=et2, value='2')
    return dict(world, ev=ev, et2=et2, ev2=ev2)


ENUM_MSG = 'Data item value must be a reference to an enumerated value of the item type'


def test_dataitem_enum_value_valid_reference(enum_world):
    w = enum_world
    form = build(w, 'add', data=dataitem_post(w, value='#EnumValue:D:v1'))
    assert form.is_valid(), form.errors
    assert form.cleaned_data['value'] == '#iref:%d' % w['ev'].id


def test_dataitem_enum_value_valid_with_surrounding_spaces(enum_world):
    w = enum_world
    form = build(w, 'add', data=dataitem_post(w, value='  #iref:%d  ' % w['ev'].id))
    # CharField strips; direct #iref syntax is accepted too
    assert form.is_valid(), form.errors


@pytest.mark.parametrize('value', ['5', 'text', '#iref:abc', '#iref:1 trailing', 'x #iref:1'])
def test_dataitem_enum_value_not_a_reference(enum_world, value):
    w = enum_world
    form = build(w, 'add', data=dataitem_post(w, value=value))
    assert not form.is_valid()
    assert form.non_field_errors() == [ENUM_MSG]


def test_dataitem_enum_value_nonexistent_reference(enum_world):
    w = enum_world
    form = build(w, 'add', data=dataitem_post(w, value='#iref:99999'))
    assert not form.is_valid()
    assert form.non_field_errors() == [ENUM_MSG + ': The reference is invalid']


def test_dataitem_enum_value_reference_to_non_enum_value(enum_world):
    w = enum_world
    form = build(w, 'add', data=dataitem_post(w, value='#iref:%d' % w['etype'].id))
    assert not form.is_valid()
    assert form.non_field_errors() == [ENUM_MSG + ': The reference is invalid']


def test_dataitem_enum_value_of_other_type(enum_world):
    w = enum_world
    form = build(w, 'add', data=dataitem_post(w, value='#EnumValue:D:v2'))
    assert not form.is_valid()
    assert form.non_field_errors() == [ENUM_MSG]


def test_dataitem_enum_value_with_no_s_link_crashes(enum_world):
    # KNOWN-ISSUE: enum-value-no-type  (EnumValue without s_link: enum_val.s_link.id -> AttributeError)
    w = enum_world
    orphan = make_spec_item(w['project'], 'EnumValue', 'D', 'orphan', status='CNF', value='9')
    form = build(w, 'add', data=dataitem_post(w, value='#EnumValue:D:orphan'))
    with pytest.raises(AttributeError):
        form.is_valid()
    assert orphan.s_link is None


def test_dataitem_non_enum_type_has_no_value_constraint(world, dt):
    form = build(world, 'add', data=dataitem_post(world, p_link=str(dt.id), value='anything'))
    assert form.is_valid(), form.errors


def test_do_cat_specific_checks_other_cats_return_empty(world):
    stub = SimpleNamespace(cat='EnumType', cleaned_data={})
    assert do_cat_specific_checks(stub) == ''


def test_do_cat_specific_checks_dataitem_without_p_link_crashes():
    # KNOWN-ISSUE: dataitem-no-plink  (cd['p_link'] is None -> AttributeError; unreachable through the
    # form today because p_link is required for DataItem, but the function itself is unguarded)
    stub = SimpleNamespace(cat='DataItem', cleaned_data={'p_link': None, 'value': ''})
    with pytest.raises(AttributeError):
        do_cat_specific_checks(stub)


def test_do_cat_specific_checks_dataitem_missing_p_link_key():
    stub = SimpleNamespace(cat='DataItem', cleaned_data={'value': ''})
    with pytest.raises(KeyError):
        do_cat_specific_checks(stub)


def test_dataitem_without_p_link_is_rejected_by_required(world):
    form = build(world, 'add', data=dataitem_post(world, p_link=''))
    assert not form.is_valid()
    assert 'p_link' in form.errors


# ------------------------------------------------------------------ external cats
def test_model_add_mode_uses_ext_item(world, fake_fw_db):
    form = build(world, 'add', 'Model', data={'ext_item': '11', 'title': 'T', 'p_kind': 'SM'})
    assert form.is_valid(), form.errors
    cd = form.cleaned_data
    assert cd['domain'] == 'DomFcp' and cd['name'] == 'mname'
    assert cd['value'] == '<svg>1</svg>'
    assert (cd['n1'], cd['n2'], cd['n3']) == (10, 20, 11)


def test_model_add_ext_item_invalid_choice(world, fake_fw_db):
    form = build(world, 'add', 'Model', data={'ext_item': '12'})
    assert not form.is_valid()
    assert 'ext_item' in form.errors


def test_model_add_duplicate_uses_ext_domain_name(world, fake_fw_db):
    make_spec_item(world['project'], 'Model', 'DomFcp', 'mname', status='CNF', application=None)
    form = build(world, 'add', 'Model', data={'ext_item': '11', 'title': 'T', 'p_kind': 'SM'})
    assert not form.is_valid()
    assert form.errors['name'] == ["Error: Name 'mname' already exists in domain 'DomFcp'"]


def test_model_edit_mode_does_not_load_ext_choices(world):
    # no fake db installed: edit mode must not touch the external DB
    m = make_spec_item(world['project'], 'Model', 'DomFcp', 'mname', status='CNF')
    form = build(world, 'edit', 'Model', item=m)
    assert type(form.fields['ext_item'].widget).__name__ == 'HiddenInput'


# Added in Task 3.4: Django 4.x renders the hidden s_data input of a re-rendered invalid form
# as value="null" (Django 3.2 rendered no value, resubmitted as ''). Both must store the same data.
@pytest.mark.parametrize('posted', ['', 'null'])
def test_s_data_hidden_value_resubmission_is_equivalent(posted):
    from django import forms as django_forms
    field = django_forms.JSONField(required=False)
    assert field.clean(posted) is None   # SpecItemForm.clean_s_data maps None -> '{}'
