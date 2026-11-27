import re

import pytest
from django.db import connection
from django.http import JsonResponse
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import path

from editor import configs as configs_module
from editor import convert as convert_module
from editor import markdown as markdown_module
from editor.configs import get_attr_config, get_cat_config, get_general_setting, has_cat
from editor.models import Project
from editor.project_config import (SERVER_ONLY_GENERAL_KEYS, get_project_config, get_request_config, load_template,
                                   resolve_config)
from tests.project_config.base import TEMPLATE, World, make_project

pytestmark = pytest.mark.django_db

CONFIG_ONLY_QUERY = re.compile(r'^SELECT [`"]editor_project[`"]\.[`"]config[`"](?: AS [`"]config[`"])? FROM')


def project_config_queries(queries):
    """Single-column reads of Project.config (what get_request_config issues)."""
    return [q['sql'] for q in queries if CONFIG_ONLY_QUERY.match(q['sql'])]


def probe_view(request, first_id, second_id):
    """Reads the configuration of two projects twice each, as a view with several helpers would."""
    first, second = Project.objects.get(id=first_id), Project.objects.get(id=second_id)
    result = {}
    for _ in range(2):
        result['first'] = get_request_config(request, first)['cats']['Packet']['name']
        result['second'] = get_request_config(request, second)['cats']['Packet']['name']
    result['same_object'] = get_request_config(request, first) is get_request_config(request, first)
    return JsonResponse(result)


urlpatterns = [path('probe/<int:first_id>/<int:second_id>/', probe_view, name='probe')]


def new_request():
    return RequestFactory().get('/')


def store(project, mutate=None):
    config = load_template()
    if mutate:
        mutate(config)
    Project.objects.filter(id=project.id).update(config=config)
    project.refresh_from_db()
    return config


@pytest.fixture
def w(client):
    return World(client)


@pytest.fixture
def other(w):
    return make_project('Other', owner=w.owner)[0]


@pytest.fixture
def projects(w, other):
    """'Proj' and 'Other', whose Packet categories are called 'Packet A' and 'Packet B'."""
    store(w.project, lambda c: c['cats']['Packet'].update(name='Packet A'))
    store(other, lambda c: c['cats']['Packet'].update(name='Packet B'))
    return w.project, other


# ------------------------------------------------------------------ get_project_config

def test_a_new_project_has_the_template_without_server_settings(w):
    expected = load_template()
    for key in SERVER_ONLY_GENERAL_KEYS:
        del expected['general'][key]
    assert get_project_config(w.project) == expected


def test_the_result_is_a_new_object_each_time(w):
    first, second = get_project_config(w.project), get_project_config(w.project)
    assert first is not second
    first['cats']['Packet']['name'] = 'Changed'
    assert get_project_config(w.project)['cats']['Packet']['name'] == TEMPLATE['cats']['Packet']['name']
    assert load_template() == TEMPLATE


def test_stored_configuration_is_returned(w):
    store(w.project, lambda c: c['cats']['Packet'].update(name='Telemetry Packet'))
    config = get_project_config(w.project)
    assert config['cats']['Packet']['name'] == 'Telemetry Packet'
    assert config['cats']['Service'] == TEMPLATE['cats']['Service']


def test_stored_configuration_is_not_replaced_by_the_template(w):
    stored = {'general': {'csv_sep': ';'}, 'cats': {'Custom': {'name': 'Custom'}}}
    Project.objects.filter(id=w.project.id).update(config=stored)
    w.project.refresh_from_db()
    assert get_project_config(w.project) == stored


def test_server_settings_are_never_part_of_the_result(w):
    assert 'temp_dir' not in get_project_config(w.project)['general']
    Project.objects.filter(id=w.project.id).update(config=load_template())
    w.project.refresh_from_db()
    assert 'temp_dir' in w.project.config['general']
    assert 'temp_dir' not in get_project_config(w.project)['general']
    assert 'temp_dir' in Project.objects.get(id=w.project.id).config['general']


def test_two_projects_with_different_settings_for_the_same_category(w, other):
    store(w.project, lambda c: c['cats']['Packet'].update(name='Packet A', page_size=5))
    store(other, lambda c: c['cats']['Packet']['attrs']['t1'].update(label='Other label'))
    first, second = get_project_config(w.project), get_project_config(other)
    assert first['cats']['Packet']['name'] == 'Packet A'
    assert first['cats']['Packet']['page_size'] == 5
    assert first['cats']['Packet']['attrs']['t1'] == TEMPLATE['cats']['Packet']['attrs']['t1']
    assert second['cats']['Packet']['name'] == TEMPLATE['cats']['Packet']['name']
    assert second['cats']['Packet']['page_size'] == TEMPLATE['cats']['Packet']['page_size']
    assert second['cats']['Packet']['attrs']['t1']['label'] == 'Other label'


def test_mutating_the_result_changes_neither_the_other_project_nor_the_stored_value(w, other):
    store(w.project)
    store(other)
    config = get_project_config(w.project)
    config['cats']['Packet']['name'] = 'Mutated'
    config['cats']['Packet']['attrs']['t1']['label'] = 'Mutated'
    config['general']['csv_sep'] = '|'
    del config['cats']['Service']
    assert w.project.config['cats']['Packet']['name'] == TEMPLATE['cats']['Packet']['name']
    for project in (w.project, other):
        fresh = get_project_config(Project.objects.get(id=project.id))
        assert fresh['cats']['Packet'] == TEMPLATE['cats']['Packet']
        assert 'Service' in fresh['cats']
        assert fresh['general']['csv_sep'] == TEMPLATE['general']['csv_sep']
    assert load_template() == TEMPLATE


def test_the_template_is_not_touched(w):
    config = get_project_config(w.project)
    config['cats'].clear()
    resolve_config(w.project.config)['general'].clear()
    assert load_template() == TEMPLATE


# ------------------------------------------------------------------ get_request_config

def test_one_read_per_project_and_request(projects):
    project, _ = projects
    request = new_request()
    with CaptureQueriesContext(connection) as queries:
        for _ in range(5):
            get_request_config(request, project)
    assert len(project_config_queries(queries)) == 1


def test_all_calls_in_a_request_see_the_same_configuration_even_if_it_changes_meanwhile(projects):
    project, _ = projects
    request = new_request()
    first = get_request_config(request, project)
    Project.objects.filter(id=project.id).update(config={'general': {}, 'cats': {}})
    assert get_request_config(request, project) is first
    assert first['cats']['Packet']['name'] == 'Packet A'


def test_a_stale_instance_does_not_provide_the_value(projects):
    project, _ = projects
    stale = Project.objects.get(id=project.id)
    store(project, lambda c: c['cats']['Packet'].update(name='Newer'))
    assert stale.config['cats']['Packet']['name'] == 'Packet A'
    assert get_request_config(new_request(), stale)['cats']['Packet']['name'] == 'Newer'


def test_two_projects_in_one_request_are_isolated(projects):
    project, other = projects
    request = new_request()
    with CaptureQueriesContext(connection) as queries:
        first = get_request_config(request, project)
        second = get_request_config(request, other)
        get_request_config(request, project)
        get_request_config(request, other)
    assert len(project_config_queries(queries)) == 2
    assert first['cats']['Packet']['name'] == 'Packet A'
    assert second['cats']['Packet']['name'] == 'Packet B'
    assert first is not second
    first['cats']['Packet']['name'] = 'Mutated in the request'
    assert second['cats']['Packet']['name'] == 'Packet B'
    assert Project.objects.get(id=other.id).config['cats']['Packet']['name'] == 'Packet B'


def test_requests_do_not_share_state(projects):
    project, _ = projects
    first = get_request_config(new_request(), project)
    first['cats']['Packet']['name'] = 'Mutated'
    assert get_request_config(new_request(), project)['cats']['Packet']['name'] == 'Packet A'


def test_a_new_project_in_a_request_has_the_template(w):
    project, _ = make_project('Fresh', owner=w.owner)
    assert get_request_config(new_request(), project)['cats']['Packet'] == TEMPLATE['cats']['Packet']


def test_a_view_reads_each_project_once_and_a_new_request_sees_saved_changes(w, projects, settings):
    project, other = projects
    settings.ROOT_URLCONF = __name__
    url = '/probe/%d/%d/' % (project.id, other.id)
    with CaptureQueriesContext(connection) as queries:
        first = w.client.get(url).json()
    assert len(project_config_queries(queries)) == 2
    assert first == {'first': 'Packet A', 'second': 'Packet B', 'same_object': True}
    store(project, lambda c: c['cats']['Packet'].update(name='Saved'))
    second = w.client.get(url).json()
    assert second['first'] == 'Saved'
    assert second['second'] == 'Packet B'


# ------------------------------------------------------------------ accessors

def test_accessors_use_only_the_given_configuration(w, other):
    first = get_project_config(w.project)
    second = get_project_config(other)
    first['cats']['Packet']['name'] = 'Packet A'
    first['cats']['Packet']['attrs']['t1']['label'] = 'Label A'
    first['general']['csv_sep'] = '|'
    del second['cats']['Service']
    assert get_cat_config(first, 'Packet')['name'] == 'Packet A'
    assert get_cat_config(second, 'Packet')['name'] == TEMPLATE['cats']['Packet']['name']
    assert get_attr_config(first, 'Packet', 't1')['label'] == 'Label A'
    assert get_attr_config(second, 'Packet', 't1') == TEMPLATE['cats']['Packet']['attrs']['t1']
    assert get_general_setting(first, 'csv_sep') == '|'
    assert get_general_setting(second, 'csv_sep') == TEMPLATE['general']['csv_sep']
    assert has_cat(first, 'Service')
    assert not has_cat(second, 'Service')
    with pytest.raises(KeyError):
        get_cat_config(second, 'Service')
    with pytest.raises(KeyError):
        get_attr_config(first, 'Packet', 'nope')
    with pytest.raises(KeyError):
        get_general_setting(first, 'temp_dir')


def test_there_is_no_global_dictionary_any_more():
    assert not hasattr(configs_module, 'configs')
    assert not hasattr(convert_module, 'configs')
    assert not hasattr(markdown_module, 'configs')
