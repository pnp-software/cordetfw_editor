/* Project configuration editor (owner only), on the configuration endpoints of editor/views.py.
 *
 * State lives in this browser tab only: state.config is the one object edited by the forms and by the JSON editor,
 * so both always show the same thing. Nothing is stored until "Save". Every text taken from the configuration is
 * put into the page as text (append, textContent, setAttribute), never as HTML; the single innerHTML is the preview
 * fragment, which the server renders with escaping.
 */
document.addEventListener('DOMContentLoaded', function () {
    const app = document.getElementById('project-config-app');
    if (!app) {
        return;
    }
    const urls = {
        reload: app.dataset.reloadUrl, validate: app.dataset.validateUrl, save: app.dataset.saveUrl,
        upload: app.dataset.uploadUrl, preview: app.dataset.previewUrl, remove: app.dataset.removeUrl
    };
    const projectId = app.dataset.projectId;
    const meta = JSON.parse(app.dataset.meta);
    const pageCsrfToken = app.querySelector('input[name="csrfmiddlewaretoken"]').value;
    // Bootstrap comes from a CDN. Without it the sections cannot be opened or closed (they are shown open), the
    // confirmations use the browser's own dialog and the tooltips are the plain title attributes.
    const hasBootstrap = typeof bootstrap !== 'undefined';

    const LINKS = ['p_link', 's_link'];
    const ORDER_FIELDS = ['cat', 'domain', 'name'];
    const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';
    const DIGITS = '0123456789';

    const state = {
        config: null, token: '', baseline: '', conflict: false, jsonError: '', selected: null, tab: 'forms',
        errors: [], busy: false, previewRun: 0, openSections: {basics: true, fields: true}
    };

    // ------------------------------------------------------------------ small helpers
    function $(id) {
        return document.getElementById(id);
    }

    // Read at every request: logging in again (e.g. in another tab) replaces the token in the cookie
    function csrfToken() {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.startsWith('csrftoken=') && cookie.length > 'csrftoken='.length) {
                return cookie.substring('csrftoken='.length);
            }
        }
        return pageCsrfToken;
    }

    function isObj(value) {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    function asObj(value) {
        return isObj(value) ? value : {};
    }

    function asArr(value) {
        return Array.isArray(value) ? value : [];
    }

    function ensureObj(parent, key) {
        if (!isObj(parent[key])) {
            parent[key] = {};
        }
        return parent[key];
    }

    function ensureArr(parent, key) {
        if (!Array.isArray(parent[key])) {
            parent[key] = [];
        }
        return parent[key];
    }

    // Adds nodes, texts (as text, never as markup) and lists of them to el; null, undefined and false are skipped.
    function addChildren(el, children) {
        if (Array.isArray(children)) {
            children.forEach(function (child) {
                addChildren(el, child);
            });
        } else if (children !== null && children !== undefined && children !== false) {
            el.append(children);
        }
    }

    // An 'on...' key adds an event listener; null, undefined and false values are skipped.
    function setAttrs(el, attrs) {
        Object.entries(attrs || {}).forEach(function ([key, value]) {
            if (value === undefined || value === null || value === false) {
                return;
            }
            if (key === 'class') {
                el.className = value;
            } else if (key.startsWith('on')) {
                el.addEventListener(key.slice(2), value);
            } else if (key === 'value' || key === 'checked' || key === 'disabled' || key === 'selected') {
                el[key] = value;
            } else {
                el.setAttribute(key, value === true ? '' : value);
            }
        });
    }

    function h(tag, attrs, children) {
        const el = document.createElement(tag);
        setAttrs(el, attrs);
        addChildren(el, children);
        return el;
    }

    function disposeTooltips(root) {
        if (!hasBootstrap) {
            return;
        }
        root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
            const tooltip = bootstrap.Tooltip.getInstance(el);
            if (tooltip) {
                tooltip.dispose();
            }
        });
    }

    function clear(el) {
        disposeTooltips(el);
        el.textContent = '';
    }

    function initTooltips(root) {
        if (!hasBootstrap) {
            return;
        }
        root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
            if (!bootstrap.Tooltip.getInstance(el)) {
                new bootstrap.Tooltip(el, {trigger: 'hover focus'});
            }
        });
    }

    // Opens or closes a collapsible section at once (without animation).
    function setSectionOpen(collapse, open) {
        const toggle = app.querySelector('[data-bs-target="#' + collapse.id + '"]');
        collapse.classList.toggle('show', open);
        if (toggle) {
            toggle.classList.toggle('collapsed', !open);
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
        if (collapse.dataset.section) {
            state.openSections[collapse.dataset.section] = open;
        }
    }

    function openSectionsAround(el) {
        for (let parent = el.parentElement; parent !== null; parent = parent.parentElement) {
            if (parent.classList.contains('collapse')) {
                setSectionOpen(parent, true);
            }
        }
    }

    function hasOnly(text, allowed) {
        for (let i = 0; i < text.length; i++) {
            if (!allowed.includes(text[i])) {
                return false;
            }
        }
        return true;
    }

    // JSON paths in the format of the server's key_path(): .key for plain names, ["key"] otherwise.
    function keyPath(base, key) {
        if (key !== '' && hasOnly(key, LETTERS + DIGITS + '_-')) {
            return base ? base + '.' + key : key;
        }
        // quoted like Python's json.dumps(): the characters outside ASCII as \uXXXX
        const text = JSON.stringify(key);
        let quoted = '';
        for (let i = 0; i < text.length; i++) {
            const code = text.charCodeAt(i);
            quoted += code < 128 ? text[i] : '\\u' + ('000' + code.toString(16)).slice(-4);
        }
        return base + '[' + quoted + ']';
    }

    function indexPath(base, i) {
        return base + '[' + i + ']';
    }

    // True if path is base or lies within it (base followed by .key, ["key"] or [index])
    function isPathWithin(path, base) {
        const next = path.charAt(base.length);
        return path.substring(0, base.length) === base && (next === '' || next === '.' || next === '[');
    }

    function humanize(id) {
        return id.split('_').map(function (word) {
            return word.charAt(0).toUpperCase() + word.slice(1);
        }).join(' ');
    }

    function cats() {
        return asObj(asObj(state.config).cats);
    }

    function attrsOf(def) {
        return asObj(asObj(def).attrs);
    }

    function attrLabel(def, id) {
        const attr = attrsOf(def)[id];
        return isObj(attr) && typeof attr.label === 'string' ? attr.label : id;
    }

    function isHiddenAttr(def, id) {
        return isObj(attrsOf(def)[id]) && attrsOf(def)[id].hidden === true;
    }

    function catName(id) {
        const def = cats()[id];
        return isObj(def) && typeof def.name === 'string' && def.name ? def.name : id;
    }

    function isDirty() {
        return state.jsonError !== '' || JSON.stringify(state.config) !== state.baseline;
    }

    // ------------------------------------------------------------------ form controls
    let uid = 0;
    function nextId() {
        uid += 1;
        return 'cfg-' + uid;
    }

    function fieldEdited(el) {
        el.classList.remove('is-invalid', 'border', 'border-danger');
        const feedback = el.parentElement && el.parentElement.querySelector(':scope > .invalid-feedback');
        if (feedback) {
            feedback.remove();
        }
        changed();
    }

    function labelled(label, control, help) {
        const id = nextId();
        control.id = id;
        return h('div', {class: 'mb-2'}, [
            h('label', {class: 'form-label mb-1', for: id}, label), control,
            help ? h('div', {class: 'form-text'}, help) : null
        ]);
    }

    function textInput(path, value, onSet, extra) {
        const el = h('input', {
            type: 'text', class: 'form-control', 'data-path': path,
            value: value === undefined || value === null ? '' : String(value)
        });
        setAttrs(el, extra);
        el.addEventListener('input', function () {
            onSet(el.value);
            fieldEdited(el);
        });
        return el;
    }

    function numberInput(path, value, onSet) {
        const el = h('input', {
            type: 'number', class: 'form-control', 'data-path': path,
            value: value === undefined || value === null ? '' : String(value)
        });
        el.addEventListener('input', function () {
            onSet(el.value === '' ? '' : Number(el.value));
            fieldEdited(el);
        });
        return el;
    }

    function selectInput(path, value, options, onSet, extra) {
        const el = h('select', {class: 'form-select', 'data-path': path}, options.map(function ([optionValue, label]) {
            return h('option', {value: optionValue}, label);
        }));
        setAttrs(el, extra);
        const current = value === undefined || value === null ? '' : String(value);
        if (!options.some(function ([optionValue]) { return optionValue === current; })) {
            el.prepend(h('option', {value: current}, (current || '(empty)') + ' (not allowed)'));
        }
        el.value = current;
        el.addEventListener('change', function () {
            onSet(el.value);
            fieldEdited(el);
        });
        return el;
    }

    function checkInput(path, checked, label, onSet, extra) {
        const id = nextId();
        const el = h('input', {
            type: 'checkbox', class: 'form-check-input', id: id, checked: checked === true, 'data-path': path || null
        });
        setAttrs(el, extra);
        el.addEventListener('change', function () {
            onSet(el.checked);
            fieldEdited(el);
        });
        return h('div', {class: 'form-check'}, [el, h('label', {class: 'form-check-label small', for: id}, label)]);
    }

    function iconButton(icon, label, onClick, disabled) {
        return h('button', {
            type: 'button', class: 'btn btn-outline-secondary', title: label, disabled: disabled === true,
            'aria-label': label, onclick: onClick
        }, h('i', {class: 'bi ' + icon, 'aria-hidden': 'true'}));
    }

    // A picker with the button which adds the picked entry
    function addRow(picker, button) {
        return h('div', {class: 'row'},
            h('div', {class: 'col-md-8 col-xl-6'}, h('div', {class: 'input-group'}, [picker, button])));
    }

    // Row for a list entry which is not an object: it cannot be edited with forms, only removed.
    function invalidRow(what, onRemove) {
        return h('div', {class: 'd-flex align-items-center gap-2 border rounded p-2 mb-2 text-danger small'}, [
            h('span', {class: 'flex-grow-1'}, what + ' is not an object: fix it in the JSON editor or remove it.'),
            iconButton('bi-x-lg', 'Remove', onRemove)
        ]);
    }

    // The hide and delete icons: tooltip on hover and keyboard focus. A reason makes the icon inert but still
    // focusable (not disabled), so the tooltip can explain why.
    function actionButton(icon, tip, onClick, inertReason, extra) {
        const text = inertReason || tip;
        const el = h('button', {
            type: 'button', class: 'btn btn-outline-secondary' + (inertReason ? ' opacity-50' : ''),
            title: text, 'aria-label': text, 'aria-disabled': inertReason ? 'true' : null,
            'data-bs-toggle': 'tooltip', 'data-bs-trigger': 'hover focus'
        }, h('i', {class: 'bi ' + icon, 'aria-hidden': 'true'}));
        setAttrs(el, extra);
        if (!inertReason) {
            el.addEventListener('click', onClick);
        }
        return el;
    }

    // ------------------------------------------------------------------ status, alerts, errors
    function updateStatus() {
        const dirty = isDirty();
        const badge = $('config-status');
        badge.textContent = state.conflict ? 'Conflict: reload before saving'
            : (dirty ? 'Unsaved changes' : 'No unsaved changes');
        badge.className = 'badge ' + (state.conflict ? 'bg-danger' : (dirty ? 'bg-warning text-dark' : 'bg-success'));
        $('config-save').disabled = state.busy || state.conflict;
        $('config-save').title = state.conflict ? 'The stored configuration changed: reload it first' : '';
        ['config-validate', 'config-reload', 'config-upload-button'].forEach(function (id) {
            $(id).disabled = state.busy;
        });
    }

    function changed() {
        const stale = $('config-message').querySelector('.alert-success');
        if (stale) {
            clear($('config-message'));
        }
        updateStatus();
    }

    function flash(level, message) {
        const box = $('config-message');
        clear(box);
        if (!message) {
            return;
        }
        box.append(h('div', {class: 'alert alert-' + level + ' alert-dismissible fade show', role: 'alert'}, [
            message,
            h('button', {type: 'button', class: 'btn-close', 'data-bs-dismiss': 'alert', 'aria-label': 'Close'})
        ]));
    }

    function showErrors(errors) {
        state.errors = errors || [];
        const box = $('config-errors');
        clear(box);
        if (state.errors.length === 0) {
            return;
        }
        const showLinks = state.tab === 'forms' && state.jsonError === '';
        const items = state.errors.map(function (error) {
            return h('li', {class: 'mb-1'}, [
                error.path
                    ? h('code', {class: 'me-1'}, error.path)
                    : h('span', {class: 'fst-italic me-1'}, '(whole configuration)'),
                error.message,
                error.path && showLinks ? h('button', {
                    type: 'button', class: 'btn btn-link py-0 ms-1', onclick: function () {
                        goToPath(error.path);
                    }
                }, 'Show') : null
            ]);
        });
        box.append(h('div', {class: 'alert alert-danger', role: 'alert'}, [
            h('strong', {}, state.errors.length === 1 ? '1 problem' : state.errors.length + ' problems'),
            ' in the configuration. Nothing was saved.', h('ul', {class: 'mb-0 mt-2'}, items)
        ]));
        markErrors();
    }

    // The border also marks the settings which are not form controls (lists, table cells).
    function markErrors() {
        app.querySelectorAll('[data-path].is-invalid').forEach(function (el) {
            el.classList.remove('is-invalid', 'border', 'border-danger');
        });
        app.querySelectorAll('.invalid-feedback').forEach(function (el) {
            el.remove();
        });
        const elements = app.querySelectorAll('#panel-forms [data-path]');
        state.errors.forEach(function (error) {
            elements.forEach(function (el) {
                if (el.dataset.path === error.path && !el.classList.contains('is-invalid')) {
                    el.classList.add('is-invalid', 'border', 'border-danger');
                    el.setAttribute('aria-invalid', 'true');
                    el.after(h('div', {class: 'invalid-feedback'}, error.message));
                }
            });
        });
    }

    // Focuses the setting of path, or else the nearest setting containing it.
    function goToPath(path) {
        if (state.tab !== 'forms') {
            return;
        }
        const ids = Object.keys(cats());
        for (let i = 0; i < ids.length; i++) {
            if (isPathWithin(path, keyPath('cats', ids[i]))) {
                if (state.selected !== ids[i]) {
                    state.selected = ids[i];
                    refresh();
                }
                break;
            }
        }
        let target = null;
        app.querySelectorAll('#panel-forms [data-path]').forEach(function (el) {
            if (isPathWithin(path, el.dataset.path)
                    && (target === null || el.dataset.path.length > target.dataset.path.length)) {
                target = el;
            }
        });
        if (target !== null) {
            openSectionsAround(target);
            target.scrollIntoView({block: 'center'});
            target.focus();
        }
    }

    // ------------------------------------------------------------------ confirmation dialog
    const modalElement = $('configConfirmModal');
    const modal = (hasBootstrap && modalElement) ? new bootstrap.Modal(modalElement) : null;
    let pendingAction = null;            // run when the dialog being shown is confirmed
    let closing = false;                 // set while a dialog is fading out: a new one waits for it
    let waitingDialog = null;
    let returnFocus = null;

    // Runs action only if the owner confirms.
    function confirmDialog(title, bodyNodes, confirmText, icon, action) {
        if (modal === null) {
            // never skip the confirmation
            const texts = bodyNodes.map(function (node) { return node.textContent; });
            if (window.confirm(title + '\n\n' + texts.join('\n\n'))) {
                action();
            }
            return;
        }
        if (closing) {
            waitingDialog = function () {
                confirmDialog(title, bodyNodes, confirmText, icon, action);
            };
            return;
        }
        $('configConfirmTitle').textContent = title;
        $('configConfirmIcon').className = 'bi ' + icon;
        const body = $('configConfirmBody');
        clear(body);
        addChildren(body, bodyNodes);
        $('configConfirmSubmit').textContent = confirmText;
        returnFocus = document.activeElement;
        pendingAction = action;
        modal.show();
    }

    if (modal !== null) {
        $('configConfirmSubmit').addEventListener('click', function () {
            const action = pendingAction;
            pendingAction = null;
            modal.hide();
            if (action) {
                action();
            }
        });

        modalElement.addEventListener('shown.bs.modal', function () {
            $('configConfirmCancel').focus();
        });

        // Cancel, the close button, Escape and the backdrop as well as the confirmation
        modalElement.addEventListener('hide.bs.modal', function () {
            pendingAction = null;
            closing = true;
        });

        modalElement.addEventListener('hidden.bs.modal', function () {
            closing = false;
            if (returnFocus && document.contains(returnFocus)) {
                returnFocus.focus();
            }
            if (waitingDialog) {
                const show = waitingDialog;
                waitingDialog = null;
                show();
            }
        });
    }

    // ------------------------------------------------------------------ server requests
    // The answer as {status, ok, data: the JSON answer or null, error: a message for the owner}
    async function request(url, method, body, headers) {
        const allHeaders = {'X-CSRFToken': csrfToken(), 'Accept': 'application/json'};
        Object.entries(headers || {}).forEach(function ([name, value]) {
            allHeaders[name] = value;
        });
        state.busy = true;
        updateStatus();
        try {
            const response = await fetch(url, {
                method: method, body: body, headers: allHeaders, credentials: 'same-origin', redirect: 'manual'
            });
            if (response.type === 'opaqueredirect' || response.redirected) {
                return {status: 302, ok: false, data: null,
                    error: 'You are no longer logged in, or no longer the owner of this project. Log in again in '
                        + 'another tab; your changes are still in the editor.'};
            }
            let data = null;
            try {
                data = await response.json();
            } catch (error) {
                data = null;
            }
            const refusal = data && Array.isArray(data.errors) && data.errors.length ? data.errors[0].message : '';
            return {status: response.status, ok: response.ok, data: data,
                error: response.ok ? '' : (refusal || 'The server answered with status ' + response.status + '.')};
        } catch (error) {
            return {status: 0, ok: false, data: null,
                error: 'The server cannot be reached. Your changes are still in the editor.'};
        } finally {
            state.busy = false;
            updateStatus();
        }
    }

    function postJson(url, payload, headers) {
        const jsonHeaders = headers || {};
        jsonHeaders['Content-Type'] = 'application/json';
        return request(url, 'POST', typeof payload === 'string' ? payload : JSON.stringify(payload), jsonHeaders);
    }

    // ------------------------------------------------------------------ loading, JSON editor
    function loadConfig(config, token) {
        state.config = config;
        state.token = token;
        state.baseline = JSON.stringify(config);
        state.conflict = false;
        state.jsonError = '';
        showJsonStatus('');
        showErrors([]);
        flash(null, '');
        clear($('config-conflict'));
        if (!(state.selected in cats())) {
            state.selected = Object.keys(cats())[0] || null;
        }
        refresh();
        if (state.tab === 'json') {
            fillJson();
        }
        updateStatus();
    }

    function fillJson() {
        $('config-json').value = JSON.stringify(state.config, null, 2);
    }

    function showJsonStatus(message) {
        const box = $('json-status');
        box.textContent = message;
        box.classList.toggle('d-none', !message);
    }

    // First key that occurs twice in one object of valid JSON text, or null. JSON.parse silently keeps the last
    // one, so without this check the editor would drop a value which the server rejects for uploaded files.
    function duplicateKey(text) {
        const objects = [];                 // per open object the list of its keys, per open array null
        let expectKey = false;
        for (let i = 0; i < text.length; i++) {
            const c = text[i];
            if (c === '"') {
                let end = i + 1;
                while (text[end] !== '"') {
                    end += text[end] === '\\' ? 2 : 1;
                }
                const keys = objects[objects.length - 1];
                if (expectKey && keys) {
                    const key = JSON.parse(text.slice(i, end + 1));
                    if (keys.includes(key)) {
                        return key;
                    }
                    keys.push(key);
                }
                expectKey = false;
                i = end;
            } else if (c === '{' || c === '[') {
                objects.push(c === '{' ? [] : null);
                expectKey = c === '{';
            } else if (c === '}' || c === ']') {
                objects.pop();
            } else if (c === ',') {
                expectKey = objects.length > 0 && objects[objects.length - 1] !== null;
            }
        }
        return null;
    }

    // Parses the JSON text; on success it becomes the state, on failure the state is left alone.
    function commitJson() {
        const text = $('config-json').value;
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (error) {
            state.jsonError = error.message;
            showJsonStatus('Syntax error: ' + state.jsonError + '. Fix it to continue; nothing was lost.');
            updateStatus();
            return false;
        }
        if (!isObj(parsed)) {
            state.jsonError = 'the configuration must be a JSON object';
            showJsonStatus('The configuration must be a JSON object.');
            updateStatus();
            return false;
        }
        const duplicate = duplicateKey(text);
        if (duplicate !== null) {
            state.jsonError = 'the key "' + duplicate + '" occurs twice in one object';
            showJsonStatus('Error: ' + state.jsonError + '. Fix it to continue; nothing was lost.');
            updateStatus();
            return false;
        }
        state.config = parsed;
        state.jsonError = '';
        showJsonStatus('');
        if (!(state.selected in cats())) {
            state.selected = Object.keys(cats())[0] || null;
        }
        updateStatus();
        return true;
    }

    // ------------------------------------------------------------------ tabs
    function switchTab(tab) {
        if (tab === state.tab) {
            return;
        }
        if (state.tab === 'json' && !commitJson()) {
            return;
        }
        state.tab = tab;
        ['forms', 'json', 'preview'].forEach(function (name) {
            $('panel-' + name).classList.toggle('d-none', name !== tab);
            const button = $('tab-' + name);
            button.classList.toggle('active', name === tab);
            button.setAttribute('aria-selected', name === tab ? 'true' : 'false');
        });
        if (tab === 'json') {
            fillJson();
        } else if (tab === 'forms') {
            refresh();
        } else {
            runPreview();
        }
        showErrors(state.errors);
    }

    // ------------------------------------------------------------------ editor: general settings
    function renderGeneral() {
        const box = $('general-settings');
        clear(box);
        const general = asObj(state.config.general);
        function setter(key) {
            return function (value) {
                ensureObj(state.config, 'general')[key] = value;
            };
        }
        box.append(
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('CSV separator',
                textInput('general.csv_sep', general.csv_sep, setter('csv_sep'), {maxlength: 1}),
                'One character, used in CSV exports and imports.')),
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('Line ending',
                selectInput('general.eol_sep', general.eol_sep, [['\n', 'LF (\\n)'], ['\r\n', 'CRLF (\\r\\n)']],
                    setter('eol_sep')))),
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('Short description length',
                numberInput('general.short_desc_len', general.short_desc_len, setter('short_desc_len')),
                'Characters, 10 to 1000.')),
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('Maximum depth',
                numberInput('general.max_depth', general.max_depth, setter('max_depth')),
                'Recursion limit, 1 to 500.')));
    }

    // ------------------------------------------------------------------ editor: category list
    function renderCatList() {
        const list = $('category-list');
        clear(list);
        const ids = Object.keys(cats());
        if (ids.length === 0) {
            list.append(h('li', {class: 'list-group-item text-muted'}, 'No category is defined.'));
        }
        ids.forEach(function (id) {
            const active = id === state.selected;
            const remove = actionButton('bi-trash', 'Delete category ' + catName(id) + ' from the configuration: '
                + 'its settings are lost. Its saved items are kept.', function () {
                removeDefinition(id, null);
            });
            if (active) {
                remove.classList.add('bg-white');
            }
            list.append(h('li', {class: 'list-group-item d-flex align-items-center p-0' + (active ? ' active' : '')}, [
                h('button', {
                    type: 'button', class: 'btn btn-link text-start flex-grow-1 text-decoration-none py-2'
                        + (active ? ' text-white' : ''),
                    'aria-current': active ? 'true' : null,
                    onclick: function () {
                        state.selected = id;
                        refresh();
                    }
                }, [h('span', {class: 'fw-bold'}, catName(id)), ' ', h('span', {class: 'small opacity-75'}, id)]),
                h('span', {class: 'pe-2'}, remove)
            ]));
        });
        initTooltips(list);
    }

    function newCategory(level, abbr, name) {
        function column(header, attr) {
            return {header: header, attrs: [attr]};
        }
        function layout() {
            return [column('Domain', 'domain'), column('Name', 'name'), column('Title', 'title'),
                column('Text', 'value')];
        }
        return {
            name: name, level: level, abbr: abbr, page_size: 100, ext_attrs: [],
            expand: {s_link: 'None', p_link: 'None'},
            short_desc: {expand_text: ['name'], href_tip: ['name'], expand_tip: ['name']},
            tracs: [], links: {}, validators: [],
            access_from_index: {level: level === 'application' ? 'Application' : 'Project'},
            attrs: {
                domain: {label: 'Domain', req_in_form: true, kind: 'plain_text'},
                name: {label: 'Name', req_in_form: true, kind: 'plain_text'},
                title: {label: 'Title', req_in_form: false, kind: 'plain_text'},
                value: {label: 'Text', req_in_form: false, kind: 'ref_text'}
            },
            p_kind_choices: {}, s_kind_choices: {}, disp_def: layout(), disp_short: layout(), disp_trac: layout()
        };
    }

    // 1-24 letters, digits or underscores, starting with a letter
    function isCategoryId(id) {
        return id.length > 0 && id.length <= 24 && LETTERS.includes(id[0]) && hasOnly(id, LETTERS + DIGITS + '_');
    }

    function setupAddCategory() {
        const form = $('add-category-form');
        $('add-category-open').addEventListener('click', function () {
            form.classList.remove('d-none');
            $('new-cat-id').focus();
        });
        $('add-category-cancel').addEventListener('click', function () {
            form.classList.add('d-none');
            form.reset();
            $('add-category-error').textContent = '';
        });
        form.addEventListener('submit', function (event) {
            event.preventDefault();
            const id = $('new-cat-id').value.trim();
            const problem = $('add-category-error');
            if (!isCategoryId(id)) {
                problem.textContent = 'The identifier must be 1-24 letters, digits or underscores and start with a '
                    + 'letter.';
                return;
            }
            if (Object.keys(cats()).some(function (existing) { return existing.toLowerCase() === id.toLowerCase(); })) {
                problem.textContent = 'A category with this identifier (ignoring case) already exists.';
                return;
            }
            const name = $('new-cat-name').value.trim() || id;
            const abbr = $('new-cat-abbr').value.trim() || id.slice(0, 4);
            ensureObj(state.config, 'cats')[id] = newCategory($('new-cat-level').value, abbr, name);
            state.selected = id;
            problem.textContent = '';
            form.reset();
            form.classList.add('d-none');
            changed();
            refresh();
        });
    }

    // ------------------------------------------------------------------ deleting and hiding definitions
    // Deleting removes the definition and the references to it from the configuration (the settings are lost,
    // the stored data is kept). Hiding a field only sets "hidden" on its definition: everything is kept.
    function removeDefinition(catId, attrId) {
        const def = asObj(cats()[catId]);
        let title;
        let body;
        if (attrId === null) {
            title = 'Delete category "' + catName(catId) + '"?';
            body = [
                h('p', {}, ['The definition of category ', h('strong', {}, catName(catId)), ' (identifier ',
                    h('code', {}, catId), ') will be deleted from the configuration: the category is no longer shown '
                    + 'in the menus, lists and forms of this project, and the references to it in other categories '
                    + '(expansions, traceability, relationship rules, validators, table columns) are removed.']),
                h('p', {}, 'Its saved data will not be deleted: items, history, releases, relationships and '
                    + 'assignments stay as they are and are still exported with the project. Adding a category with '
                    + 'the same identifier shows them again, but its settings and the references to it have to be '
                    + 'set up again.'),
                h('p', {class: 'mb-0'}, 'Nothing is stored until you save.')
            ];
        } else {
            title = 'Delete field "' + attrLabel(def, attrId) + '"?';
            body = [
                h('p', {}, ['The definition of field ', h('strong', {}, attrLabel(def, attrId)), ' (',
                    h('code', {}, attrId), ') of category ', h('strong', {}, catName(catId)), ' (',
                    h('code', {}, catId), ') will be deleted from the configuration: it is no longer shown in its '
                    + 'forms, lists and CSV exports, and the references to it in the table layouts, short '
                    + 'descriptions and validators of this category are removed.']),
                h('p', {}, 'Its saved data will not be deleted: the values stay with the items, survive editing and '
                    + 'are still exported with the project. Adding the field again shows them in the forms again, but '
                    + 'its settings, table columns and short descriptions have to be set up again.'),
                h('p', {class: 'mb-0'}, ['To keep them, hide the field instead (',
                    h('i', {class: 'bi bi-eye-slash', 'aria-hidden': 'true'}),
                    ' Hide). Nothing is stored until you save.'])
            ];
        }
        confirmDialog(title, body, 'Delete', 'bi-trash-fill', function () {
            deleteDefinition(catId, attrId);
        });
    }

    async function deleteDefinition(catId, attrId) {
        const payload = {config: state.config, cat: catId};
        if (attrId !== null) {
            payload.attr = attrId;
        }
        const result = await postJson(urls.remove, payload);
        if (!result.data || !isObj(result.data.config)) {
            flash('danger', result.error || 'The definition could not be deleted. Nothing was changed.');
            return;
        }
        state.config = result.data.config;
        if (!(state.selected in cats())) {
            state.selected = Object.keys(cats())[0] || null;
        }
        changed();
        refresh();
        showErrors(result.data.errors);
        flash('info', (attrId === null ? 'Category ' : 'Field ') + (attrId === null ? catId : attrId)
            + ' is deleted from the configuration in the editor; its saved data is untouched. Save to apply the '
            + 'change, or Reload to undo it.');
        const editor = $('category-editor');
        editor.setAttribute('tabindex', '-1');
        editor.focus();
    }

    function toggleHidden(catId, attrId) {
        const attr = attrsOf(cats()[catId])[attrId];
        if (!isObj(attr)) {
            return;
        }
        const hiding = attr.hidden !== true;
        if (hiding) {
            attr.hidden = true;
        } else {
            delete attr.hidden;
        }
        changed();
        renderCatEditor();
        flash('info', 'Field ' + attrId + (hiding
            ? ' is hidden: the forms, lists and CSV exports of the category no longer show it and validators which '
              + 'use it are not applied. Its values, settings, table columns and short descriptions are kept. Save '
              + 'to apply the change.'
            : ' is shown again, with its settings, table columns and short descriptions. Save to apply the change.'));
        $('category-editor').querySelectorAll('[data-toggle-hidden]').forEach(function (button) {
            if (button.dataset.toggleHidden === attrId) {
                button.focus();
            }
        });
    }

    // ------------------------------------------------------------------ editor: one category
    function section(id, title, summary, content) {
        const open = state.openSections[id] === true || !hasBootstrap;
        const bodyId = 'config-section-' + id;
        const body = h('div', {
            id: bodyId, class: 'accordion-collapse collapse' + (open ? ' show' : ''),
            'aria-labelledby': bodyId + '-heading', 'data-section': id
        }, h('div', {class: 'accordion-body'}, content));
        body.addEventListener('show.bs.collapse', function () {
            state.openSections[id] = true;
        });
        body.addEventListener('hide.bs.collapse', function () {
            state.openSections[id] = false;
        });
        return h('div', {class: 'accordion-item'}, [
            h('h4', {class: 'accordion-header', id: bodyId + '-heading'}, h('button', {
                type: 'button', class: 'accordion-button fw-bold' + (open ? '' : ' collapsed'),
                'data-bs-toggle': 'collapse', 'data-bs-target': '#' + bodyId, 'aria-controls': bodyId,
                'aria-expanded': open ? 'true' : 'false'
            }, [title, h('span', {class: 'text-muted small fw-normal ms-2'}, summary)])),
            body
        ]);
    }

    function renderCatEditor() {
        const box = $('category-editor');
        clear(box);
        const id = state.selected;
        const def = id === null ? null : cats()[id];
        if (!isObj(def)) {
            box.append(h('p', {class: 'text-muted'}, id === null
                ? 'Select a category, or add one.'
                : 'This category definition is not an object and cannot be edited with the forms. Fix it in the JSON '
                  + 'editor or delete it.'));
            return;
        }
        const parts = [sectionBasics, sectionFields, sectionChoices, sectionRelations, sectionValidators,
            sectionLayouts, sectionShort];
        const sections = h('div', {class: 'accordion mb-3'});
        parts.forEach(function (build) {
            try {
                sections.append(build(id, def));
            } catch (error) {
                sections.append(h('div', {class: 'alert alert-warning'}, 'A part of this category cannot be shown '
                    + 'because its structure is invalid. Fix it in the JSON editor.'));
            }
        });
        box.append(h('h3', {class: 'fs-5 mb-3'}, [catName(id), ' ', h('code', {class: 'small'}, id)]), sections);
        initTooltips(box);
        markErrors();
    }

    function col(child) {
        return h('div', {class: 'col-sm-6 col-xl-4'}, child);
    }

    function sectionBasics(id, def) {
        const base = keyPath('cats', id);
        const accessPath = keyPath(keyPath(base, 'access_from_index'), 'level');
        const access = selectInput(accessPath, asObj(def.access_from_index).level,
            [['Project', 'Project index'], ['Application', 'Application index'], ['None', 'Not offered']],
            function (value) {
                ensureObj(def, 'access_from_index').level = value;
            });
        const level = selectInput(keyPath(base, 'level'), def.level,
            [['project', 'Project'], ['application', 'Application']], function (value) {
                def.level = value;
                if (asObj(def.access_from_index).level !== 'None') {
                    ensureObj(def, 'access_from_index').level = value === 'application' ? 'Application' : 'Project';
                    access.value = def.access_from_index.level;
                }
            });
        const identifier = h('input', {type: 'text', class: 'form-control', value: id, disabled: true});
        return section('basics', 'Basics', 'name, level, page size', h('div', {class: 'row g-2'}, [
            col(labelled('Identifier', identifier, 'Fixed: it is stored with every item.')),
            col(labelled('Name', textInput(keyPath(base, 'name'), def.name, function (value) {
                def.name = value;
                renderCatList();
            }))),
            col(labelled('Abbreviation', textInput(keyPath(base, 'abbr'), def.abbr, function (value) {
                def.abbr = value;
            }))),
            col(labelled('Level', level)),
            col(labelled('Offered from', access)),
            col(labelled('Page size', numberInput(keyPath(base, 'page_size'), def.page_size, function (value) {
                def.page_size = value;
            }), 'Items per list page, 1 to 1000.'))
        ]));
    }

    function uniqueLabel(def, wanted) {
        function squeezed(label) {
            return label.split(' ').join('').toLowerCase();
        }
        const used = Object.values(attrsOf(def)).map(function (attr) {
            return squeezed(String(asObj(attr).label));
        });
        let label = wanted;
        let n = 2;
        while (used.includes(squeezed(label))) {
            label = wanted + ' ' + n;
            n += 1;
        }
        return label;
    }

    function sectionFields(id, def) {
        const base = keyPath(keyPath('cats', id), 'attrs');
        const attrs = attrsOf(def);
        const mandatory = ['domain', 'name'];
        const allKinds = [];
        Object.values(meta.allowed_kinds).forEach(function (kinds) {
            kinds.forEach(function (kind) {
                if (!allKinds.includes(kind)) {
                    allKinds.push(kind);
                }
            });
        });
        const rows = Object.keys(attrs).map(function (attrId) {
            const path = keyPath(base, attrId);
            const attr = attrs[attrId];
            const hidden = isHiddenAttr(def, attrId);
            function required(what) {
                return mandatory.includes(attrId)
                    ? 'Required: items are identified by ' + attrId + ', so it cannot be ' + what : null;
            }
            const label = attrLabel(def, attrId);
            const toggleTip = hidden
                ? 'Show field ' + label + ' again: its forms, lists and CSV exports show it with its table columns '
                  + 'and short descriptions.'
                : 'Hide field ' + label + ': it is no longer shown in forms, lists and CSV exports. Its values and '
                  + 'settings are kept.';
            const toggle = isObj(attr) ? actionButton(hidden ? 'bi-eye' : 'bi-eye-slash', toggleTip, function () {
                toggleHidden(id, attrId);
            }, required('hidden'), {'data-toggle-hidden': attrId}) : null;
            const remove = actionButton('bi-trash', 'Delete field ' + label + ' from the configuration: its settings, '
                + 'table columns and short descriptions are lost. Its saved values are kept.', function () {
                removeDefinition(id, attrId);
            }, required('deleted'));
            const actions = h('td', {class: 'text-end text-nowrap'}, [toggle, toggle ? ' ' : null, remove]);
            const known = attrId in meta.allowed_kinds;
            const dimmed = hidden ? 'opacity-50' : null;
            const name = h('td', {class: dimmed}, [
                h('code', {}, attrId),
                hidden ? h('span', {class: 'badge bg-secondary ms-1'}, 'hidden') : null,
                known ? null : h('div', {class: 'text-danger small'}, 'unknown field')
            ]);
            if (!isObj(attr)) {
                return h('tr', {}, [name, h('td', {colspan: 3, class: 'text-danger small'},
                    'Invalid definition: fix it in the JSON editor or delete it.'), actions]);
            }
            return h('tr', {}, [
                name,
                h('td', {class: dimmed}, textInput(keyPath(path, 'label'), attr.label, function (value) {
                    attr.label = value;
                }, {'aria-label': 'Label of ' + attrId})),
                h('td', {class: dimmed}, selectInput(keyPath(path, 'kind'), attr.kind,
                    (meta.allowed_kinds[attrId] || allKinds).map(function (kind) { return [kind, kind]; }),
                    function (value) {
                        attr.kind = value;
                    }, {'aria-label': 'Kind of ' + attrId})),
                h('td', {class: dimmed}, checkInput(keyPath(path, 'req_in_form'), attr.req_in_form, 'Required in form',
                    function (value) {
                        attr.req_in_form = value;
                    }, attr.req_in_form === true && mandatory.includes(attrId) ? {disabled: true} : {})),
                actions
            ]);
        });
        const free = Object.keys(meta.allowed_kinds).filter(function (name) { return !(name in attrs); });
        const picker = h('select', {class: 'form-select', 'aria-label': 'Field to add'}, free.map(function (name) {
            return h('option', {value: name}, name);
        }));
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', disabled: free.length === 0,
            onclick: function () {
                const attrId = picker.value;
                ensureObj(def, 'attrs')[attrId] = {
                    label: uniqueLabel(def, humanize(attrId)), req_in_form: false, kind: meta.allowed_kinds[attrId][0]
                };
                changed();
                renderCatEditor();
            }
        }, [h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add field']);
        const hiddenCount = Object.keys(attrs).filter(function (attrId) { return isHiddenAttr(def, attrId); }).length;
        return section('fields', 'Fields', Object.keys(attrs).length + ' defined'
            + (hiddenCount ? ', ' + hiddenCount + ' hidden' : ''), [
            h('div', {class: 'table-responsive'}, h('table', {class: 'table table-hover table-sm align-middle'}, [
                h('thead', {}, h('tr', {class: 'table-primary text-nowrap small'}, [
                    h('th', {}, 'Field'), h('th', {}, 'Label'), h('th', {}, 'Kind'), h('th', {}, 'Required'),
                    h('th', {})
                ])),
                h('tbody', {}, rows)
            ])),
            addRow(picker, add)
        ]);
    }

    function renameKey(obj, oldKey, newKey) {
        const entries = Object.entries(obj);
        entries.forEach(function ([key]) {
            delete obj[key];
        });
        entries.forEach(function ([key, value]) {
            obj[key === oldKey ? newKey : key] = value;
        });
    }

    function choiceEditor(id, def, kind) {
        const key = kind + '_choices';
        const base = keyPath(keyPath('cats', id), key);
        const choices = asObj(def[key]);
        const rows = Object.keys(choices).map(function (value) {
            const valueInput = h('input', {
                type: 'text', class: 'form-control', value: value, 'data-path': keyPath(base, value),
                'aria-label': 'Stored value'
            });
            valueInput.addEventListener('change', function () {
                const list = ensureObj(def, key);
                if (valueInput.value !== value && valueInput.value in list) {
                    flash('danger', 'The value "' + valueInput.value + '" is already used in this list.');
                    valueInput.value = value;
                    return;
                }
                renameKey(list, value, valueInput.value);
                changed();
                renderCatEditor();
            });
            const label = h('input', {
                type: 'text', class: 'form-control', value: String(choices[value]), 'aria-label': 'Label of ' + value
            });
            label.addEventListener('input', function () {
                ensureObj(def, key)[value] = label.value;
                changed();
            });
            return h('tr', {}, [h('td', {}, valueInput), h('td', {}, label), h('td', {class: 'text-end'},
                iconButton('bi-x-lg', 'Remove choice ' + value, function () {
                    delete ensureObj(def, key)[value];
                    changed();
                    renderCatEditor();
                }))]);
        });
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', onclick: function () {
                const list = ensureObj(def, key);
                let n = Object.keys(list).length + 1;
                while (('NEW' + n) in list) {
                    n += 1;
                }
                list['NEW' + n] = 'New choice';
                changed();
                renderCatEditor();
            }
        }, [h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add choice']);
        return h('div', {class: 'mb-3'}, [
            h('h5', {class: 'fs-6'}, kind + ' choices'),
            h('div', {class: 'table-responsive'}, h('table', {class: 'table table-hover table-sm align-middle'}, [
                h('thead', {}, h('tr', {class: 'table-primary text-nowrap small'}, [
                    h('th', {}, 'Stored value'), h('th', {}, 'Label'), h('th', {})
                ])),
                h('tbody', {}, rows)
            ])),
            add
        ]);
    }

    function sectionChoices(id, def) {
        return section('choices', 'Choice lists', 'p_kind, s_kind', [
            h('p', {class: 'small text-muted'}, 'Values already stored with items must stay in the list; saving checks '
                + 'this.'),
            choiceEditor(id, def, 'p_kind'), choiceEditor(id, def, 's_kind')
        ]);
    }

    function miniButton(icon, label, onClick, disabled, light) {
        return h('button', {
            type: 'button', class: 'btn btn-sm py-0 px-1 border-0 lh-1' + (light ? ' text-white' : ''), title: label,
            'aria-label': label, disabled: disabled === true, onclick: onClick
        }, h('i', {class: 'bi ' + icon, 'aria-hidden': 'true'}));
    }

    // Ordered list of attribute names with move/remove buttons and a picker for the unused ones. read holds the
    // list (possibly a stand-in), write() returns the real object, created only when edited. vertical: one entry
    // per line (a table cell), otherwise chips in a row.
    function attrListEditor(path, read, write, key, attrIds, def, vertical) {
        const names = asArr(read[key]);
        function edit(change) {
            change(ensureArr(write(), key));
            changed();
            renderCatEditor();
        }
        function swap(i, j) {
            edit(function (list) {
                const name = list[i];
                list[i] = list[j];
                list[j] = name;
            });
        }
        const box = h(vertical ? 'ol' : 'div', {
            class: vertical ? 'list-unstyled mb-2' : 'd-flex flex-wrap gap-1 align-items-center',
            'data-path': path, tabindex: '-1'
        });
        names.forEach(function (name, i) {
            const text = typeof name === 'string'
                ? attrLabel(def, name) + ' (' + name + (isHiddenAttr(def, name) ? ', hidden' : '') + ')' : String(name);
            const tools = [
                miniButton(vertical ? 'bi-arrow-up' : 'bi-chevron-left', 'Move ' + text + (vertical ? ' up' : ' left'),
                    function () { swap(i, i - 1); }, i === 0, !vertical),
                miniButton(vertical ? 'bi-arrow-down' : 'bi-chevron-right',
                    'Move ' + text + (vertical ? ' down' : ' right'),
                    function () { swap(i, i + 1); }, i === names.length - 1, !vertical),
                miniButton('bi-x-lg', 'Remove ' + text, function () {
                    edit(function (list) { list.splice(i, 1); });
                }, false, !vertical)
            ];
            const itemPath = indexPath(path, i);
            box.append(vertical
                ? h('li', {class: 'd-flex align-items-center gap-1 py-1 border-bottom', 'data-path': itemPath}, [
                    h('span', {class: 'flex-grow-1' + (isHiddenAttr(def, name) ? ' text-muted' : '')}, [
                        typeof name === 'string' ? h('strong', {}, attrLabel(def, name)) : text,
                        typeof name === 'string' ? h('span', {class: 'small text-muted ms-1'}, name) : null,
                        isHiddenAttr(def, name) ? h('span', {class: 'badge bg-secondary ms-1'}, 'hidden') : null
                    ]),
                    tools
                ])
                : h('span', {
                    class: 'badge bg-secondary fw-normal d-inline-flex align-items-center', 'data-path': itemPath
                }, [h('span', {class: 'me-1'}, text), tools]));
        });
        const free = attrIds.filter(function (name) { return !names.includes(name); });
        if (free.length) {
            const picker = h('select', {
                class: 'form-select ' + (vertical ? 'form-select-sm' : 'w-auto'),
                'aria-label': 'Add attribute to ' + key
            }, [
                h('option', {value: ''}, vertical ? '+ add attribute...' : 'add attribute...'),
                free.map(function (name) {
                    return h('option', {value: name}, attrLabel(def, name) + ' (' + name + ')');
                })
            ]);
            picker.addEventListener('change', function () {
                if (picker.value) {
                    edit(function (list) { list.push(picker.value); });
                }
            });
            box.append(vertical ? h('li', {}, picker) : picker);
        }
        return box;
    }

    function ruleEditor(id, def, link) {
        const base = keyPath(keyPath(keyPath('cats', id), 'links'), link);
        const rule = asObj(asObj(def.links)[link]);
        const hasRule = isObj(asObj(def.links)[link]);
        const mode = !hasRule ? 'none' : ('all_except' in rule ? 'all_except' : 'targets');
        const box = h('div', {class: 'border rounded p-2 mb-3'});
        function links() {
            return ensureObj(def, 'links');
        }
        function setMode(value) {
            if (value === 'none') {
                delete links()[link];
            } else {
                const current = ensureObj(links(), link);
                const names = asArr(current.targets || current.all_except);
                delete current.targets;
                delete current.all_except;
                current[value] = names.slice();
            }
            changed();
            renderCatEditor();
        }
        const modeSelect = selectInput(base, mode, [['none', 'No rule: no choices are offered'],
            ['targets', 'Items of these categories only'], ['all_except', 'Items of every category except these']],
            setMode);
        box.append(h('div', {class: 'fw-bold mb-2'}, link + ' (' + attrLabel(def, link) + ')'),
            labelled('Allowed targets', modeSelect));
        if (mode !== 'none') {
            const listed = asArr(rule[mode]);
            const checks = Object.keys(cats()).map(function (cat) {
                return checkInput(listed.includes(cat) ? indexPath(keyPath(base, mode), listed.indexOf(cat)) : null,
                    listed.includes(cat), catName(cat) + ' (' + cat + ')', function (on) {
                        const names = ensureArr(links()[link], mode);
                        const at = names.indexOf(cat);
                        if (on && at < 0) {
                            names.push(cat);
                        } else if (!on && at >= 0) {
                            names.splice(at, 1);
                        }
                    });
            });
            // Targets which are not categories of the configuration stay visible so they can be removed
            listed.filter(function (name) { return !(name in cats()); }).forEach(function (name) {
                checks.push(checkInput(indexPath(keyPath(base, mode), listed.indexOf(name)), true,
                    name + ' (undefined category)', function (on) {
                        if (!on) {
                            const names = ensureArr(links()[link], mode);
                            names.splice(names.indexOf(name), 1);
                        }
                    }));
            });
            box.append(h('div', {
                class: 'row row-cols-1 row-cols-sm-2 row-cols-xl-3 gx-3 gy-1 mb-2', 'data-path': keyPath(base, mode)
            }, checks.map(function (check) { return h('div', {class: 'col'}, check); })));
            box.append(h('div', {class: 'row g-2'}, [
                col(labelled('Scope', selectInput(keyPath(base, 'scope'), rule.scope || 'project',
                    [['project', 'Whole project'], ['application', 'Same application only']], function (value) {
                        links()[link].scope = value;
                    }))),
                col(h('div', {class: 'mb-2'}, [
                    h('div', {class: 'form-label mb-1'}, 'Order by'),
                    h('div', {class: 'd-flex gap-3', 'data-path': keyPath(base, 'order_by')},
                        ORDER_FIELDS.map(function (field) {
                            const current = Array.isArray(rule.order_by) ? rule.order_by : ['domain', 'name'];
                            return checkInput(keyPath(base, 'order_by'), current.includes(field), field, function (on) {
                                const before = Array.isArray(links()[link].order_by)
                                    ? links()[link].order_by : ['domain', 'name'];
                                links()[link].order_by = ORDER_FIELDS.filter(function (name) {
                                    return name === field ? on : before.includes(name);
                                });
                            });
                        }))
                ]))
            ]));
            const narrow = isObj(rule.narrow_by_other_parent);
            const narrowPath = keyPath(base, 'narrow_by_other_parent');
            const linkOptions = LINKS.map(function (name) { return [name, name]; });
            const narrowBox = h('div', {class: 'row g-2 mt-1' + (narrow ? '' : ' d-none')}, [
                col(labelled('Target field', selectInput(keyPath(narrowPath, 'target_field'),
                    asObj(rule.narrow_by_other_parent).target_field, linkOptions, function (value) {
                        ensureObj(links()[link], 'narrow_by_other_parent').target_field = value;
                    }))),
                col(labelled('Parent field', selectInput(keyPath(narrowPath, 'parent_field'),
                    asObj(rule.narrow_by_other_parent).parent_field, linkOptions, function (value) {
                        ensureObj(links()[link], 'narrow_by_other_parent').parent_field = value;
                    })))
            ]);
            box.append(checkInput(narrowPath, narrow, 'Narrow by the other parent (only targets whose target field '
                + 'equals the parent field of the other parent item)', function (on) {
                if (on) {
                    links()[link].narrow_by_other_parent = {target_field: 's_link', parent_field: 's_link'};
                } else {
                    delete links()[link].narrow_by_other_parent;
                }
                renderCatEditor();
            }), narrowBox);
        }
        return box;
    }

    function expandEditor(id, def) {
        const base = keyPath(keyPath('cats', id), 'expand');
        const expand = asObj(def.expand);
        const options = [['None', 'None']].concat(Object.keys(cats()).map(function (cat) {
            return [cat, catName(cat) + ' (' + cat + ')'];
        }));
        function set(key, value) {
            ensureObj(def, 'expand')[key] = value;
        }
        const fields = [];
        LINKS.forEach(function (link) {
            const labelKey = link[0] + '_label';
            fields.push(col(labelled(link + ' expands to', selectInput(keyPath(base, link), expand[link], options,
                function (value) {
                    set(link, value);
                }))));
            fields.push(col(labelled(link + ' label', textInput(keyPath(base, labelKey), expand[labelKey],
                function (value) {
                    set(labelKey, value);
                }))));
        });
        return h('div', {class: 'mb-3'}, [
            h('h5', {class: 'fs-6'}, 'Expansion of linked items'), h('div', {class: 'row g-2'}, fields)
        ]);
    }

    function tracsEditor(id, def) {
        const base = keyPath(keyPath('cats', id), 'tracs');
        const tracs = asArr(def.tracs);
        const options = Object.keys(cats()).map(function (cat) { return [cat, catName(cat) + ' (' + cat + ')']; });
        function removeTrac(i) {
            def.tracs.splice(i, 1);
            changed();
            renderCatEditor();
        }
        const rows = tracs.map(function (trac, i) {
            const path = indexPath(base, i);
            const entry = asObj(trac);
            if (!isObj(trac)) {
                return invalidRow('The traceability link', function () {
                    removeTrac(i);
                });
            }
            return h('div', {class: 'row g-2 align-items-end'}, [
                col(labelled('Link category', selectInput(path + '.trac_cat', entry.trac_cat, options,
                    function (value) {
                        def.tracs[i].trac_cat = value;
                    }))),
                col(labelled('Endpoint pointing here', selectInput(path + '.trac_link', entry.trac_link,
                    LINKS.map(function (name) { return [name, name]; }), function (value) {
                        def.tracs[i].trac_link = value;
                    }))),
                h('div', {class: 'col-auto mb-2'}, iconButton('bi-x-lg', 'Remove traceability link', function () {
                    removeTrac(i);
                }))
            ]);
        });
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', disabled: options.length === 0, onclick: function () {
                ensureArr(def, 'tracs').push({trac_cat: options[0][0], trac_link: 'p_link'});
                changed();
                renderCatEditor();
            }
        }, [h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add traceability link']);
        return h('div', {class: 'mb-2'}, [h('h5', {class: 'fs-6'}, 'Traceability'), rows, add]);
    }

    function sectionRelations(id, def) {
        return section('relations', 'Relationships', 'p_link, s_link, expansion, traceability', [
            ruleEditor(id, def, 'p_link'), ruleEditor(id, def, 's_link'), expandEditor(id, def), tracsEditor(id, def)
        ]);
    }

    function validatorEditor(id, def) {
        const base = keyPath(keyPath('cats', id), 'validators');
        const specs = asArr(def.validators);
        const catOptions = Object.keys(cats()).map(function (cat) { return [cat, catName(cat) + ' (' + cat + ')']; });
        const attrOptions = Object.keys(attrsOf(def)).map(function (attr) {
            return [attr, attrLabel(def, attr) + ' (' + attr + ')'];
        });
        const names = Object.keys(meta.validators);
        function removeValidator(i) {
            def.validators.splice(i, 1);
            changed();
            renderCatEditor();
        }
        const rows = specs.map(function (spec, i) {
            const path = indexPath(base, i);
            const entry = asObj(spec);
            const params = asObj(entry.params);
            if (!isObj(spec)) {
                return invalidRow('The validator', function () {
                    removeValidator(i);
                });
            }
            const kinds = meta.validators[entry.name];
            const head = h('div', {class: 'd-flex align-items-center gap-2 mb-2'}, [
                h('div', {class: 'flex-grow-1'}, selectInput(path + '.name', entry.name,
                    names.map(function (name) { return [name, name]; }), function (value) {
                        def.validators[i] = {name: value, params: defaultParams(meta.validators[value], def)};
                        changed();
                        renderCatEditor();
                    })),
                iconButton('bi-x-lg', 'Remove validator', function () {
                    removeValidator(i);
                })
            ]);
            const fields = kinds === undefined
                ? h('p', {class: 'text-danger small mb-0'}, 'This validator is not supported; saving will be refused. '
                    + 'Remove it or choose another one.')
                : h('div', {class: 'row g-2'}, Object.entries(kinds).map(function ([param, kind]) {
                    function set(value) {
                        ensureObj(def.validators[i], 'params')[param] = value;
                    }
                    const paramPath = path + '.params.' + param;
                    let control;
                    if (kind === 'link') {
                        control = selectInput(paramPath, params[param], LINKS.map(function (name) {
                            return [name, name];
                        }), set);
                    } else if (kind === 'cat') {
                        control = selectInput(paramPath, params[param], catOptions, set);
                    } else if (kind === 'attr') {
                        control = selectInput(paramPath, params[param], attrOptions, set);
                    } else {
                        control = textInput(paramPath, params[param], set, {maxlength: 300});
                    }
                    return col(labelled(param, control));
                }));
            return h('div', {class: 'border rounded p-2 mb-2'}, [head, fields]);
        });
        const picker = h('select', {class: 'form-select', 'aria-label': 'Validator to add'}, names.map(function (name) {
            return h('option', {value: name}, name);
        }));
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', onclick: function () {
                ensureArr(def, 'validators').push({
                    name: picker.value, params: defaultParams(meta.validators[picker.value], def)
                });
                changed();
                renderCatEditor();
            }
        }, [h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add validator']);
        return [
            h('p', {class: 'small text-muted'}, 'Validators are chosen from the list the server supports; the '
                + 'configuration never contains code.'),
            rows, addRow(picker, add)
        ];
    }

    function defaultParams(kinds, def) {
        const params = {};
        Object.entries(kinds || {}).forEach(function ([param, kind]) {
            if (kind === 'link') {
                params[param] = 'p_link';
            } else if (kind === 'cat') {
                params[param] = Object.keys(cats())[0] || '';
            } else if (kind === 'attr') {
                params[param] = Object.keys(attrsOf(def))[0] || '';
            } else {
                params[param] = '';
            }
        });
        return params;
    }

    function sectionValidators(id, def) {
        return section('validators', 'Validators', asArr(def.validators).length + ' defined', validatorEditor(id, def));
    }

    function focusPath(path) {
        let target = null;
        $('category-editor').querySelectorAll('[data-path]').forEach(function (el) {
            if (target === null && el.dataset.path === path) {
                target = el;
            }
        });
        if (target !== null) {
            openSectionsAround(target);
            target.focus();
        }
    }

    // A table layout drawn as the list it produces, one table column per layout column: column tools (move,
    // remove), headers, the attributes of each column (or the link of a traceability column) and the sorting.
    function layoutEditor(id, def, key, title) {
        const base = keyPath(keyPath('cats', id), key);
        const columns = asArr(def[key]);
        const attrIds = Object.keys(attrsOf(def));
        function edit(change, focus) {
            change(ensureArr(def, key));
            changed();
            renderCatEditor();
            if (focus) {
                focusPath(focus);
            }
        }
        function move(i, by) {
            edit(function (list) {
                const column = list[i];
                list[i] = list[i + by];
                list[i + by] = column;
            });
        }
        const tools = [];
        const heads = [];
        const cells = [];
        const sorts = [];
        columns.forEach(function (column, i) {
            const path = indexPath(base, i);
            const name = isObj(column) && typeof column.header === 'string' && column.header
                ? column.header : 'column ' + (i + 1);
            tools.push(h('td', {class: 'text-center text-nowrap', 'data-path': path, tabindex: '-1'},
                h('div', {class: 'btn-group btn-group-sm', role: 'group', 'aria-label': 'Column ' + name}, [
                    iconButton('bi-arrow-left', 'Move column ' + name + ' left', function () {
                        move(i, -1);
                    }, i === 0),
                    iconButton('bi-arrow-right', 'Move column ' + name + ' right', function () {
                        move(i, 1);
                    }, i === columns.length - 1),
                    iconButton('bi-x-lg', 'Remove column ' + name, function () {
                        edit(function (list) { list.splice(i, 1); });
                    })
                ])));
            if (!isObj(column)) {
                heads.push(h('th', {class: 'text-danger'}, 'Invalid column'));
                cells.push(h('td', {class: 'text-danger small'}, 'The column is not an object: fix it in the JSON '
                    + 'editor or remove it.'));
                sorts.push(h('td', {}));
                return;
            }
            heads.push(h('th', {}, textInput(path + '.header', column.header, function (value) {
                column.header = value;
            }, {class: 'form-control form-control-sm fw-bold', 'aria-label': 'Header of column ' + (i + 1)})));
            if ('trac_cat' in column) {
                cells.push(h('td', {}, [
                    h('div', {class: 'small text-muted mb-1'}, 'Traceability: items linked through'),
                    selectInput(path + '.trac_cat', column.trac_cat, Object.keys(cats()).map(function (cat) {
                        return [cat, catName(cat) + ' (' + cat + ')'];
                    }), function (value) {
                        column.trac_cat = value;
                    }, {class: 'form-select form-select-sm mb-1', 'aria-label': 'Link category of column ' + (i + 1)}),
                    selectInput(path + '.trac_link', column.trac_link, LINKS.map(function (link) {
                        return [link, link];
                    }), function (value) {
                        column.trac_link = value;
                    }, {class: 'form-select form-select-sm', 'aria-label': 'Endpoint of column ' + (i + 1)})
                ]));
                sorts.push(h('td', {class: 'small text-muted'}, 'not sortable'));
            } else {
                cells.push(h('td', {}, attrListEditor(path + '.attrs', column, function () {
                    return column;
                }, 'attrs', attrIds, def, true)));
                sorts.push(h('td', {}, selectInput(path + '.order_by', column.order_by || '',
                    [['', 'not sortable']].concat(attrIds.map(function (attr) {
                        return [attr, 'sort by ' + attrLabel(def, attr)];
                    })), function (value) {
                        if (value) {
                            column.order_by = value;
                        } else {
                            delete column.order_by;
                        }
                    }, {class: 'form-select form-select-sm', 'aria-label': 'Sorting of column ' + (i + 1)})));
            }
        });
        const unused = attrIds.find(function (attr) {
            return !columns.some(function (column) { return isObj(column) && asArr(column.attrs).includes(attr); });
        }) || attrIds[0];
        const addColumn = h('button', {
            type: 'button', class: 'btn btn-sm btn-outline-primary text-nowrap', disabled: attrIds.length === 0,
            onclick: function () {
                edit(function (list) {
                    list.push({header: attrLabel(def, unused), attrs: [unused]});
                }, indexPath(base, columns.length) + '.header');
            }
        }, [h('i', {class: 'bi bi-plus-lg me-1', 'aria-hidden': 'true'}), 'Add column']);
        const addTrac = key === 'disp_trac' ? h('button', {
            type: 'button', class: 'btn btn-sm btn-outline-primary text-nowrap',
            disabled: Object.keys(cats()).length === 0, onclick: function () {
                edit(function (list) {
                    list.push({header: 'Links', trac_cat: Object.keys(cats())[0], trac_link: 'p_link'});
                }, indexPath(base, columns.length) + '.header');
            }
        }, [h('i', {class: 'bi bi-plus-lg me-1', 'aria-hidden': 'true'}), 'Add traceability column']) : null;
        const table = h('table', {class: 'table table-bordered table-sm align-top mb-0'}, [
            h('thead', {}, [h('tr', {}, tools), h('tr', {class: 'table-primary'}, heads)]),
            h('tbody', {}, [h('tr', {}, cells), h('tr', {}, sorts)])
        ]);
        return h('div', {class: 'mb-4', 'data-path': base, tabindex: '-1'}, [
            h('div', {class: 'd-flex flex-wrap align-items-center gap-2 mb-2'}, [
                h('h5', {class: 'fs-6 mb-0 me-auto'}, [title, ' ', h('span', {class: 'text-muted small fw-normal'},
                    columns.length === 1 ? '1 column' : columns.length + ' columns')]),
                addColumn, addTrac
            ]),
            columns.length
                ? h('div', {class: 'table-responsive'}, table)
                : h('p', {class: 'small text-muted border rounded p-2 mb-0'}, 'No column: the list shows only the item '
                    + 'buttons.')
        ]);
    }

    function sectionLayouts(id, def) {
        return section('layouts', 'Table layouts', 'default, short and traceability lists', [
            layoutEditor(id, def, 'disp_def', 'Default list'), layoutEditor(id, def, 'disp_short', 'Short list'),
            layoutEditor(id, def, 'disp_trac', 'Traceability list')
        ]);
    }

    function sectionShort(id, def) {
        const base = keyPath('cats', id);
        const attrIds = Object.keys(attrsOf(def));
        const parts = [['expand_text', 'Expanded text'], ['href_tip', 'Link tooltip'],
            ['expand_tip', 'Expansion tooltip']];
        const content = parts.map(function ([key, title]) {
            return h('div', {class: 'mb-3'}, [
                h('div', {class: 'form-label mb-1'}, title),
                attrListEditor(keyPath(keyPath(base, 'short_desc'), key), asObj(def.short_desc), function () {
                    return ensureObj(def, 'short_desc');
                }, key, attrIds, def)
            ]);
        });
        if (meta.external_cats.includes(id) || asArr(def.ext_attrs).length) {
            content.push(h('div', {class: 'mb-2'}, [
                h('div', {class: 'form-label mb-1'}, 'Attributes taken from the external repository'),
                attrListEditor(keyPath(base, 'ext_attrs'), def, function () {
                    return def;
                }, 'ext_attrs', attrIds, def)
            ]));
        }
        return section('short', 'Short descriptions', 'text shown for references', content);
    }

    function refresh() {
        renderGeneral();
        renderCatList();
        renderCatEditor();
        markErrors();
    }

    // ------------------------------------------------------------------ actions
    function guardJson() {
        if (state.jsonError !== '') {
            flash('danger', 'The JSON has a syntax error (' + state.jsonError + '). Fix it first.');
            return false;
        }
        return true;
    }

    async function validate() {
        if (!guardJson()) {
            return;
        }
        const result = await postJson(urls.validate, state.config);
        if (result.data && Array.isArray(result.data.errors) && (result.status === 200 || result.status === 422)) {
            showErrors(result.data.errors);
            flash(result.data.valid ? 'success' : null, result.data.valid ? 'The configuration is valid.' : '');
        } else {
            flash('danger', result.error);
        }
    }

    async function save() {
        if (state.conflict) {
            flash('danger', 'The stored configuration changed after it was loaded. Reload it before saving again.');
            return;
        }
        if (!guardJson()) {
            return;
        }
        const sent = JSON.stringify(state.config);
        const result = await postJson(urls.save, sent, {'X-Config-Token': state.token});
        if (result.status === 200 && result.data && result.data.saved) {
            state.token = result.data.token;
            state.baseline = sent;
            showErrors([]);
            clear($('config-conflict'));
            flash('success', 'Saved. The configuration applies to the next request.');
        } else if (result.status === 409) {
            showConflict();
        } else if (result.status === 422 && result.data && Array.isArray(result.data.errors)) {
            showErrors(result.data.errors);
            flash('danger', 'The configuration was not saved: it has problems. Your changes are kept.');
        } else {
            flash('danger', 'The configuration was not saved. ' + result.error);
        }
        updateStatus();
    }

    function showConflict() {
        state.conflict = true;
        const box = $('config-conflict');
        clear(box);
        box.append(h('div', {class: 'alert alert-danger', role: 'alert'}, [
            h('strong', {}, 'Conflict: not saved. '),
            'The saved configuration was changed (by someone else or in another window) after you loaded it. ',
            'Your changes are still in this editor and were not saved. Download them if you want a copy, then reload ',
            'the saved configuration; saving is blocked until you do.',
            h('div', {class: 'mt-2'}, [
                h('button', {type: 'button', class: 'btn btn-outline-secondary me-2', onclick: downloadLocal},
                    'Download my changes'),
                h('button', {type: 'button', class: 'btn btn-danger', onclick: reload}, 'Reload saved configuration')
            ])
        ]));
        updateStatus();
    }

    function downloadLocal() {
        const text = state.tab === 'json' ? $('config-json').value : JSON.stringify(state.config, null, 2) + '\n';
        const link = h('a', {
            href: URL.createObjectURL(new Blob([text], {type: 'application/json'})),
            download: 'cordetfw_project_' + projectId + '_config_unsaved.json'
        });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(function () {
            URL.revokeObjectURL(link.href);
        }, 1000);
    }

    function reload() {
        if (!isDirty()) {
            loadSaved();
            return;
        }
        confirmDialog('Discard unsaved changes?', [
            h('p', {class: 'mb-0'}, 'The editor contains changes which are not saved. Reloading replaces them with the '
                + 'configuration saved in the database; the changes will be lost.')
        ], 'Discard and reload', 'bi-exclamation-triangle-fill', loadSaved);
    }

    async function loadSaved() {
        const result = await request(urls.reload, 'GET');
        if (result.ok && result.data && isObj(result.data.config)) {
            loadConfig(result.data.config, result.data.token);
            flash('info', 'Reloaded the saved configuration.');
        } else {
            flash('danger', 'The configuration could not be reloaded; the editor was not changed. ' + result.error);
        }
    }

    function upload(file) {
        if (!isDirty()) {
            loadFile(file);
            return;
        }
        confirmDialog('Replace the editor contents?', [
            h('p', {class: 'mb-0'}, 'Loading the file replaces the changes in the editor which are not saved. '
                + 'The file is not saved to the database either: use Save afterwards.')
        ], 'Load file', 'bi-exclamation-triangle-fill', function () {
            loadFile(file);
        });
    }

    async function loadFile(file) {
        const form = new FormData();
        form.append('upload_file', file);
        const result = await request(urls.upload, 'POST', form);
        const data = result.data;
        if (data && isObj(data.config) && (result.status === 200 || result.status === 422)) {
            state.config = data.config;
            state.jsonError = '';
            showJsonStatus('');
            if (!(state.selected in cats())) {
                state.selected = Object.keys(cats())[0] || null;
            }
            refresh();
            if (state.tab === 'json') {
                fillJson();
            }
            showErrors(data.errors);
            flash(data.valid ? 'success' : 'warning', data.valid
                ? 'The file was loaded into the editor. It is not saved yet.'
                : 'The file was loaded into the editor, but it has problems. It is not saved.');
        } else if (data && Array.isArray(data.errors)) {
            showErrors(data.errors);
            flash('danger', 'The file was not loaded. The editor was not changed.');
        } else {
            flash('danger', 'The file was not loaded. ' + result.error);
        }
        updateStatus();
    }

    // Categories opened (true) or closed (false) in the preview by the owner, by identifier; the others are closed,
    // except the category selected in the forms. Kept while the page is open, also when the preview is rendered again.
    const previewOpen = {};

    function setupPreviewCategories(target) {
        target.querySelectorAll('[data-cat]').forEach(function (body) {
            const cat = body.dataset.cat;
            const open = typeof previewOpen[cat] === 'boolean' ? previewOpen[cat] : cat === state.selected;
            setSectionOpen(body, open || !hasBootstrap);
            body.addEventListener('show.bs.collapse', function () {
                previewOpen[cat] = true;
            });
            body.addEventListener('hide.bs.collapse', function () {
                previewOpen[cat] = false;
            });
        });
    }

    async function runPreview() {
        const target = $('preview-content');
        if (!guardJson()) {
            clear(target);
            return;
        }
        state.previewRun += 1;
        const run = state.previewRun;
        clear(target);
        target.append(h('p', {class: 'text-muted'}, 'Rendering the preview...'));
        const result = await postJson(urls.preview, state.config);
        if (run !== state.previewRun || state.tab !== 'preview') {
            return;
        }
        clear(target);
        if (result.status === 200 && result.data && result.data.valid) {
            showErrors([]);
            target.innerHTML = result.data.html;       // fragment rendered and escaped by the server
            setupPreviewCategories(target);
        } else if (result.data && Array.isArray(result.data.errors)) {
            showErrors(result.data.errors);
            target.append(h('p', {class: 'text-muted'}, 'The preview is shown when the configuration is valid. Fix the '
                + 'problems listed above.'));
        } else {
            target.append(h('p', {class: 'text-danger'}, result.error));
        }
    }

    // ------------------------------------------------------------------ start
    loadConfig(JSON.parse(app.dataset.config), app.dataset.token);
    if (!hasBootstrap) {
        setSectionOpen($('general-body'), true);
    }
    setupAddCategory();
    ['forms', 'json', 'preview'].forEach(function (tab) {
        $('tab-' + tab).addEventListener('click', function () {
            switchTab(tab);
        });
    });
    $('config-json').addEventListener('input', commitJson);
    $('config-save').addEventListener('click', save);
    $('config-validate').addEventListener('click', validate);
    $('config-reload').addEventListener('click', reload);
    $('preview-refresh').addEventListener('click', runPreview);
    $('config-upload-button').addEventListener('click', function () {
        $('config-upload-file').click();
    });
    $('config-upload-file').addEventListener('change', function (event) {
        const file = event.target.files[0];
        event.target.value = '';
        if (file) {
            upload(file);
        }
    });
    window.addEventListener('beforeunload', function (event) {
        if (isDirty()) {
            event.preventDefault();
            event.returnValue = '';
        }
    });
});
