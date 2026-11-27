"""Owner-only endpoints for the project configuration. The Configuration page (project_config.html, project_config.js) is built on them.

All endpoints are below `<project_id>/config`. Access: anonymous users are redirected to the login page; every
other user who is not the project's owner (RO/RW members, staff, owners of other projects) gets 403, also for a
project which does not exist (the status does not reveal which ids exist). Ownership is checked before the HTTP
method, so a non-owner never learns anything from a 405.

  GET  config            HTML page (current configuration and token)
  GET  config/download   the configuration as a JSON file (re-uploadable)
  GET  config/reload     JSON {"config": ..., "token": ...} read from the database; changes nothing
  POST config/validate   body: the configuration as JSON (application/json); validates/previews, stores nothing
  POST config/upload     multipart, file field `upload_file`; validates, stores nothing, returns the content
  POST config/save       body as validate, header `X-Config-Token`; validates and stores
  POST config/preview    body as validate; returns the rendered preview (HTML fragment) of a valid configuration
  POST config/remove     body {"config": ..., "cat": ..., "attr": ... (optional)}; returns the configuration without
                         that definition and without the references to it; stores nothing (the trash icon;
                         hiding a field is the `hidden` setting of its definition and needs no request)

Responses are JSON: {"valid": bool, "errors": [{"path", "message"}], "config": parsed config or null} for
validate/upload, {"valid": true, "html": ...} for preview, {"config": ..., "errors": [...]} for remove,
{"saved": true, "token": ...} for save, {"errors": [...]} for refusals. Messages contain
submitted names and must be escaped by whatever displays them.
"""
import json
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache

from editor.access import user_is_project_owner
from editor.cat_validators import VALIDATORS
from editor.config_cleanup import remove_attribute, remove_category
from editor.config_preview import build_preview
from editor.config_store import InvalidConfigError, StaleConfigError, config_token, read_stored_config, \
    save_project_config
from editor.config_validation import ALLOWED_KINDS, MAX_JSON_BYTES, ConfigError, _external_cats, validate_config, \
    validate_config_file, validate_config_json
from editor.models import Project
from editor.project_config import resolve_config

TOKEN_HEADER = 'X-Config-Token'
UPLOAD_FIELD = 'upload_file'


def config_endpoint(*methods):
    """Login, ownership and method check (in this order); the view gets the Project instead of its id."""
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, project_id, *args, **kwargs):
            project = Project.objects.filter(id=project_id).first()
            if project is None or not user_is_project_owner(request.user, project):
                raise PermissionDenied
            if request.method not in methods:
                return HttpResponseNotAllowed(methods)
            return view(request, project, *args, **kwargs)
        return wrapper
    return decorator


def refusal(status, message):
    return JsonResponse({'errors': [ConfigError('', message).as_dict()]}, status=status)


def check_result(config, errors):
    """Response of validate/upload: 200 if valid, 422 with the errors otherwise."""
    return JsonResponse({'valid': not errors, 'errors': [error.as_dict() for error in errors], 'config': config},
                        status=200 if not errors else 422)


def read_json_body(request):
    """(body bytes, None) or (None, error response) for a JSON request body."""
    if request.content_type != 'application/json':
        return None, refusal(415, 'the request must have the content type application/json')
    try:
        length = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    if length > MAX_JSON_BYTES:
        return None, refusal(413, 'the configuration is larger than %d bytes' % MAX_JSON_BYTES)
    try:
        return request.body, None
    except RequestDataTooBig:
        return None, refusal(413, 'the configuration is larger than %d bytes' % MAX_JSON_BYTES)


@config_endpoint('GET', 'HEAD')
@never_cache
def config_page(request, project):
    stored = read_stored_config(project.id)
    config = resolve_config(stored)
    # Not named `config`: base_generic.html reads `config.name` for the breadcrumb of the item pages.
    context = {'project': project, 'title': 'Configuration', 'initial_config': config,
               'config_token': config_token(stored), 'editor_meta': editor_meta()}
    return render(request, 'project_config.html', context)


def editor_meta():
    """What the editor forms need to know about the supported settings (the server stays the authority)."""
    return {'allowed_kinds': {name: list(kinds) for name, kinds in ALLOWED_KINDS.items()},
            'validators': {name: params for name, (_function, params) in VALIDATORS.items()},
            'external_cats': _external_cats()}


@config_endpoint('GET', 'HEAD')
@never_cache
def config_download(request, project):
    config = resolve_config(read_stored_config(project.id))
    response = HttpResponse(json.dumps(config, indent=2, ensure_ascii=False) + '\n',
                            content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="cordetfw_project_%d_config.json"' % project.id
    return response


@config_endpoint('GET', 'HEAD')
@never_cache
def config_reload(request, project):
    stored = read_stored_config(project.id)           # one read: configuration and token belong together
    return JsonResponse({'config': resolve_config(stored), 'token': config_token(stored)})


@config_endpoint('POST')
def config_validate(request, project):
    body, error = read_json_body(request)
    if error:
        return error
    config, errors = validate_config_json(body, project)
    return check_result(config, errors)


@config_endpoint('POST')
def config_preview(request, project):
    body, error = read_json_body(request)
    if error:
        return error
    config, errors = validate_config_json(body, project)
    if errors:
        return check_result(config, errors)
    html = render_to_string('project_config_preview.html', build_preview(config, project), request=request)
    return JsonResponse({'valid': True, 'errors': [], 'html': html})


@config_endpoint('POST')
def config_remove(request, project):
    body, error = read_json_body(request)
    if error:
        return error
    try:
        payload = json.loads(body)
    except (ValueError, RecursionError):
        return refusal(400, 'the request body is not valid JSON')
    config = payload.get('config') if isinstance(payload, dict) else None
    cat, attr = (payload.get('cat'), payload.get('attr')) if isinstance(payload, dict) else (None, None)
    cats = config.get('cats') if isinstance(config, dict) else None
    if not isinstance(cats, dict) or not isinstance(cat, str) or cat not in cats:
        return refusal(422, 'the request needs a configuration and the identifier of one of its categories')
    if attr is None:
        cleaned = remove_category(config, cat)
    else:
        attrs = cats[cat].get('attrs') if isinstance(cats[cat], dict) else None
        if not isinstance(attr, str) or not isinstance(attrs, dict) or attr not in attrs:
            return refusal(422, 'the category has no field "%s"' % attr if isinstance(attr, str) else
                           'the field must be given as a text')
        cleaned = remove_attribute(config, cat, attr)
    # The result may be invalid (removing a mandatory field); the editor shows the errors, nothing is stored.
    return JsonResponse({'config': cleaned, 'errors': [e.as_dict() for e in validate_config(cleaned, project)]})


@config_endpoint('POST')
def config_upload(request, project):
    uploaded = request.FILES.get(UPLOAD_FIELD)
    if uploaded is None:
        return refusal(400, 'no file was uploaded in the field "%s"' % UPLOAD_FIELD)
    if uploaded.size > MAX_JSON_BYTES:
        return refusal(413, 'the configuration is larger than %d bytes' % MAX_JSON_BYTES)
    config, errors = validate_config_file(uploaded, project)
    return check_result(config, errors)


@config_endpoint('POST')
def config_save(request, project):
    body, error = read_json_body(request)
    if error:
        return error
    token = request.headers.get(TOKEN_HEADER)
    if not token:
        return refusal(428, 'the header %s with the token of the configuration the editor was based on is '
                            'required' % TOKEN_HEADER)
    try:
        new_token = save_project_config(project.id, body, token)
    except StaleConfigError:
        return refusal(409, 'the stored configuration has changed since it was loaded; reload it before saving')
    except InvalidConfigError as invalid:
        return JsonResponse({'saved': False, 'errors': [error.as_dict() for error in invalid.errors]}, status=422)
    return JsonResponse({'saved': True, 'token': new_token})
