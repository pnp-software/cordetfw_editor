import csv
import io
import zipfile

import pytest

from editor.cat_validators import check_validator_specs
from editor.config_cleanup import copy_config
from editor.link_rules import check_link_rules, check_trac_settings
from editor.models import SpecItem
from editor.project_config import (SERVER_ONLY_GENERAL_KEYS, filter_template_for_data, get_data_usage,
                                   load_template, split_cats)
from tests.project_config.base import ALL_CATS, TEMPLATE, World, make_application, make_item, make_project

pytestmark = pytest.mark.django_db


def assert_consistent(config):
    """Every reference in the configuration points to a definition that is in the configuration."""
    cats = config['cats']
    for cat, definition in cats.items():
        attrs = definition['attrs']
        assert set(definition['ext_attrs']) <= set(attrs), cat
        for link in ('s_link', 'p_link'):
            assert definition['expand'][link] in ('None', *cats), cat
        for trac in definition['tracs']:
            assert trac['trac_cat'] in cats, cat
        assert check_link_rules(definition['links'], 'links', set(cats)) == [], cat
        assert check_trac_settings(definition['tracs'], 'tracs', set(cats)) == [], cat
        assert check_validator_specs(definition['validators'], 'validators', config, cat) == [], cat
        for key, names in definition['short_desc'].items():
            assert set(names) <= set(attrs), (cat, key)
        for layout in ('disp_def', 'disp_short', 'disp_trac'):
            for column in definition[layout]:
                if 'attrs' in column:
                    assert column['attrs'] and set(column['attrs']) <= set(attrs), (cat, layout, column)
                    if 'order_by' in column:
                        assert column['order_by'] in attrs, (cat, layout, column)
                else:
                    assert column['trac_cat'] in cats, (cat, layout, column)


def make_cats_project(cats, name='P', app_cats=None):
    project, _ = make_project(name, cats=cats)
    if app_cats is not None:
        make_application(project, name + 'App', cats=app_cats)
    return project


def test_load_template_reads_the_shared_file_without_caching():
    first, second = load_template(), load_template()
    assert first == TEMPLATE
    assert first == second
    assert first is not second
    first['cats'].clear()
    assert len(load_template()['cats']) == 30


def test_split_cats():
    assert split_cats(' A, B ,,C') == ['A', 'B', 'C']
    assert split_cats('') == []


def test_template_is_not_modified():
    template = load_template()
    snapshot = copy_config(template)
    project = make_cats_project(['Packet'])
    config = filter_template_for_data(template, project)
    assert template == snapshot
    config['cats']['Packet']['attrs']['title']['label'] = 'Changed'
    assert template == snapshot


def test_all_categories_listed_gives_the_template_without_server_settings():
    project = make_cats_project(ALL_CATS)
    config = filter_template_for_data(load_template(), project)
    assert config['cats'] == TEMPLATE['cats']
    assert list(config['cats']) == list(TEMPLATE['cats'])              # template order
    assert config['general'] == {k: v for k, v in TEMPLATE['general'].items() if k != 'temp_dir'}
    assert 'temp_dir' not in config['general']
    assert SERVER_ONLY_GENERAL_KEYS == ('temp_dir',)
    assert set(config) == {'general', 'cats'}
    assert_consistent(config)


def test_only_listed_categories_are_kept_when_there_is_no_data():
    project = make_cats_project(['InfoItem', 'Requirement', 'VerLink'])
    config = filter_template_for_data(load_template(), project)
    assert list(config['cats']) == ['VerLink', 'Requirement', 'InfoItem']
    for cat in config['cats']:                      # listed categories keep every definition
        # Except that relationship targets which are not in the configuration are removed
        assert {k: v for k, v in config['cats'][cat].items() if k != 'links'} == \
            {k: v for k, v in TEMPLATE['cats'][cat].items() if k != 'links'}
    assert config['cats']['VerLink']['links'] == \
        {'s_link': {'all_except': ['VerLink'], 'order_by': ['cat', 'domain', 'name']}}
    assert_consistent(config)


def test_application_categories_are_kept():
    project = make_cats_project(['InfoItem'], app_cats=['Requirement', 'SysReq'])
    config = filter_template_for_data(load_template(), project)
    assert sorted(config['cats']) == ['InfoItem', 'Requirement', 'SysReq']


def test_listed_category_without_data_keeps_all_its_fields():
    project = make_cats_project(['InfoItem'])
    config = filter_template_for_data(load_template(), project)
    assert list(config['cats']['InfoItem']['attrs']) == list(TEMPLATE['cats']['InfoItem']['attrs'])


def test_category_with_data_is_kept_with_the_definitions_that_hold_data():
    project = make_cats_project(['InfoItem'])
    make_item(project, 'Requirement', 'D', 'r1', title='T', value='v', t1='x', p_kind='STD', status='CNF')
    make_item(project, 'Requirement', 'D', 'r2', status='DEL', rationale='why')       # statuses are all data
    make_item(project, 'DataItemType', 'D', 'n', n1=4)
    config = filter_template_for_data(load_template(), project)
    assert sorted(config['cats']) == ['DataItemType', 'InfoItem', 'Requirement']
    requirement = config['cats']['Requirement']
    assert set(requirement['attrs']) == {'domain', 'name', 'title', 'value', 'rationale', 't1', 'p_kind', 'val_set',
                                         'owner'}
    for name, definition in requirement['attrs'].items():                          # definitions are unchanged
        assert definition == TEMPLATE['cats']['Requirement']['attrs'][name]
    assert set(config['cats']['DataItemType']['attrs']) == {'domain', 'name', 'n1', 'val_set', 'owner'}
    names = {a for layout in ('disp_def', 'disp_short', 'disp_trac') for c in requirement[layout]
             for a in c.get('attrs', [])}
    assert names <= set(requirement['attrs'])
    assert set(requirement['short_desc']['expand_text']) <= set(requirement['attrs'])
    assert_consistent(config)


def test_data_of_other_projects_is_ignored():
    project = make_cats_project(['InfoItem'])
    other = make_cats_project(['InfoItem', 'Requirement', 'VerLink'], name='Other')
    make_item(other, 'Requirement', 'D', 'r1', title='T')
    make_item(other, 'EnumType', 'D', 'e1', n1=2)
    config = filter_template_for_data(load_template(), project)
    assert list(config['cats']) == ['InfoItem']


def test_references_to_removed_categories_and_fields_are_removed():
    project = make_cats_project(['Packet'])
    config = filter_template_for_data(load_template(), project)
    packet = config['cats']['Packet']
    assert packet['expand']['s_link'] == 'None'              # DerPacket removed
    assert packet['expand']['p_link'] == 'None'              # PacketPar removed
    assert (packet['expand']['s_label'], packet['expand']['p_label']) == \
        (TEMPLATE['cats']['Packet']['expand']['s_label'], TEMPLATE['cats']['Packet']['expand']['p_label'])
    assert packet['tracs'] == []                              # VerLink removed
    for layout in ('disp_def', 'disp_short', 'disp_trac'):
        assert [c for c in packet[layout] if 'trac_cat' in c] == [], layout
    assert len(packet['disp_trac']) == len(TEMPLATE['cats']['Packet']['disp_trac']) - 1
    assert_consistent(config)


def test_references_between_kept_categories_are_preserved():
    project = make_cats_project(['Packet', 'DerPacket', 'PacketPar', 'VerLink'])
    config = filter_template_for_data(load_template(), project)
    packet = config['cats']['Packet']
    assert (packet['expand']['s_link'], packet['expand']['p_link']) == ('DerPacket', 'PacketPar')
    assert packet['tracs'] == [{'trac_cat': 'VerLink', 'trac_link': 's_link'}]
    assert_consistent(config)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_every_single_category_gives_a_consistent_configuration(cat):
    project = make_cats_project([cat], name='P_' + cat)
    config = filter_template_for_data(load_template(), project)
    assert list(config['cats']) == [cat]
    assert_consistent(config)


@pytest.mark.parametrize('cat', ALL_CATS)
def test_data_only_category_with_the_fewest_fields_is_consistent(cat):
    project = make_cats_project([], name='D_' + cat)
    make_item(project, cat, 'D', 'only')
    config = filter_template_for_data(load_template(), project)
    assert list(config['cats']) == [cat]
    assert set(config['cats'][cat]['attrs']) == \
        {'domain', 'name', 'val_set', 'owner'} & set(TEMPLATE['cats'][cat]['attrs'])
    assert_consistent(config)


def test_unknown_categories_are_not_copied():
    project = make_cats_project(['InfoItem', 'Bogus'])
    SpecItem.objects.create(cat='Ghost', domain='D', name='g', project=project, val_set=project.val_sets.first(),
                            owner=project.owner, status='NEW', updated_at=project.updated_at,
                            created_at=project.updated_at)
    config = filter_template_for_data(load_template(), project)
    assert list(config['cats']) == ['InfoItem']


def test_data_usage():
    project = make_cats_project(['InfoItem'])
    make_item(project, 'Requirement', 'D', 'a', title='T', n1=0, t3='x')
    make_item(project, 'Requirement', 'D', 'b', desc='d')
    parent = make_item(project, 'Service', 'D', 'p')
    make_item(project, 'Packet', 'D', 'c', p_link=parent)
    usage = get_data_usage(project)
    assert usage['Requirement'] == {'domain', 'name', 'val_set', 'owner', 'title', 't3', 'desc'}
    assert usage['Packet'] == {'domain', 'name', 'val_set', 'owner', 'p_link'}
    assert usage['Service'] == {'domain', 'name', 'val_set', 'owner'}


def test_archive_project_csv_keeps_its_columns(client, settings, tmp_path):
    # The configuration travels in config.json, so project.csv is unchanged
    w = World(client)
    settings.TEMP_DIR = str(tmp_path)
    response = client.get(w.url('export_project', w.project.id))
    archive = zipfile.ZipFile(io.BytesIO(b''.join(response.streaming_content)))
    header = csv.DictReader(io.StringIO(archive.read('project.csv').decode('utf-8'))).fieldnames
    assert header == ['id', 'name', 'desc', 'cats', 'updated_at', 'owner', 'release']
