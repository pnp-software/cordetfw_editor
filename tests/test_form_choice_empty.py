"""form-choice-empty-silent-default (Task 7.6b): a REQUIRED choice field whose stored value is empty (or not
a valid choice) renders a selected '---------' option in edit/copy/split mode, so saving fails with
'This field is required' instead of silently storing the first choice."""
import pytest

from editor.configs import configs
from editor.utilities import spec_item_to_edit
from tests.factories import make_spec_item
from tests.test_forms import build, world, ALL_CATS  # noqa: F401  (world is a fixture)

pytestmark = pytest.mark.django_db

BLANK = ('', '---------')


def _required_selects(cat):
    attrs = configs['cats'][cat]['attrs']
    return [f for f in ('p_kind', 's_kind') if f in attrs and attrs[f]['req_in_form']
            and f not in configs['cats'][cat]['ext_attrs']]


def _item(world, cat, **kw):
    return make_spec_item(world['project'], cat, 'D', 'X', status='CNF', **kw)


@pytest.mark.parametrize('mode', ['edit', 'copy', 'split'])
def test_empty_required_choice_gets_blank_option(world, mode):
    # FIXED: form-choice-empty-silent-default (was: no blank option, the first choice was shown and saved)
    item = _item(world, 'Requirement', p_kind='', s_kind='')
    form = build(world, mode, 'Requirement', item=item)
    fields = _required_selects('Requirement')
    assert 's_kind' in fields
    for f in fields:
        assert form.fields[f].choices[0] == BLANK
        assert form.fields[f].choices[1:] == list(configs['cats']['Requirement'][f + '_choices'].items())
        html = str(form[f])
        assert '<option value="" selected>---------</option>' in html
        assert html.count('selected') == 1


@pytest.mark.parametrize('mode', ['edit', 'copy', 'split'])
def test_invalid_stored_choice_gets_blank_option(world, mode):
    item = _item(world, 'Requirement', s_kind='NOPE')
    form = build(world, mode, 'Requirement', item=item)
    assert form.fields['s_kind'].choices[0] == BLANK


@pytest.mark.parametrize('cat', ALL_CATS)
@pytest.mark.parametrize('mode', ['edit', 'copy', 'split'])
def test_valid_stored_choice_unchanged(world, cat, mode):
    attrs = configs['cats'][cat]['attrs']
    vals = {f: list(configs['cats'][cat][f + '_choices'])[-1] for f in ('p_kind', 's_kind') if f in attrs}
    item = _item(world, cat, **vals)
    form = build(world, mode, cat, item=item)
    for f in vals:
        assert form.fields[f].choices == list(configs['cats'][cat][f + '_choices'].items())


def test_add_mode_unchanged(world):
    form = build(world, 'add', 'Requirement')
    assert form.fields['s_kind'].choices == list(configs['cats']['Requirement']['s_kind_choices'].items())


def test_optional_choice_field_unchanged(world):
    for cat in ALL_CATS:
        attrs = configs['cats'][cat]['attrs']
        for f in ('p_kind', 's_kind'):
            if f in attrs and not attrs[f]['req_in_form']:
                form = build(world, 'edit', cat, item=_item(world, cat, **{f: ''}))
                assert form.fields[f].choices == list(configs['cats'][cat][f + '_choices'].items())


def test_post_with_blank_choice_is_rejected_and_good_choice_saves(world):
    item = _item(world, 'Requirement', p_kind='CNS', s_kind='', value='v', desc='d')
    data = spec_item_to_edit(item)
    data['s_kind'] = ''
    data['change_log'] = 'x'
    form = build(world, 'edit', 'Requirement', data=data, item=item)
    assert not form.is_valid()
    assert 's_kind' in form.errors
    data['s_kind'] = 'TST'
    form = build(world, 'edit', 'Requirement', data=data, item=item)
    assert form.is_valid(), form.errors
