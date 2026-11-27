/* Project configuration editor (owner only). The page is built on the endpoints of editor/config_views.py.
 *
 * State lives in this browser tab only: `state.config` is the one object edited by the forms and by the JSON
 * editor, so both always show the same thing. Nothing is stored until "Save". Every text taken from the
 * configuration is put into the page with textContent / setAttribute (never as HTML); the single innerHTML is
 * the preview fragment, which the server renders with escaping.
 */
(function () {
    'use strict';

    const app = document.getElementById('project-config-app');
    if (!app) {
        return;
    }
    const urls = {
        reload: app.dataset.reloadUrl, validate: app.dataset.validateUrl, save: app.dataset.saveUrl,
        upload: app.dataset.uploadUrl, preview: app.dataset.previewUrl, remove: app.dataset.removeUrl,
    };
    const projectId = app.dataset.projectId;
    const meta = JSON.parse(document.getElementById('project-config-meta').textContent);
    const csrfToken = app.querySelector('input[name="csrfmiddlewaretoken"]').value;
    const $ = (id) => document.getElementById(id);

    const LINKS = ['p_link', 's_link'];
    const ORDER_FIELDS = ['cat', 'domain', 'name'];
    const SECTIONS = ['basics', 'fields', 'choices', 'relations', 'validators', 'layouts', 'short'];

    const state = {
        config: null, token: '', baseline: '', conflict: false, jsonError: '', selected: null, tab: 'forms',
        errors: [], busy: false, previewRun: 0, openSections: new Set(['basics', 'fields']),
    };

    // ------------------------------------------------------------------ small helpers
    const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
    const asObj = (v) => (isObj(v) ? v : {});
    const asArr = (v) => (Array.isArray(v) ? v : []);

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

    function append(el, children) {
        for (const child of children.flat(Infinity)) {
            if (child === null || child === undefined || child === false) {
                continue;
            }
            el.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
    }

    function h(tag, props, ...children) {
        const el = document.createElement(tag);
        for (const [key, value] of Object.entries(props || {})) {
            if (value === undefined || value === null || value === false) {
                continue;
            }
            if (key === 'class') {
                el.className = value;
            } else if (key.startsWith('on')) {
                el.addEventListener(key.slice(2), value);
            } else if (key === 'value' || key === 'checked' || key === 'disabled' || key === 'selected') {
                el[key] = value;
            } else {
                el.setAttribute(key, value === true ? '' : String(value));
            }
        }
        append(el, children);
        return el;
    }

    function disposeTooltips(root) {
        if (typeof bootstrap === 'undefined') {
            return;
        }
        root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
            const tip = bootstrap.Tooltip.getInstance(el);
            if (tip) {
                tip.dispose();
            }
        });
    }

    function clear(el) {
        disposeTooltips(el);
        el.replaceChildren();
    }

    function initTooltips(root) {
        if (typeof bootstrap === 'undefined') {
            return;                                   // the title attribute still works on hover
        }
        root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
            if (!bootstrap.Tooltip.getInstance(el)) {
                new bootstrap.Tooltip(el, {trigger: 'hover focus'});
            }
        });
    }

    // JSON paths in the format of the server's key_path(): .key for plain names, ["key"] otherwise.
    const PLAIN_KEY = /^[A-Za-z0-9_-]+$/;
    function keyPath(base, key) {
        if (PLAIN_KEY.test(key)) {
            return base ? base + '.' + key : key;
        }
        const quoted = JSON.stringify(key).replace(/[\u0080-\uffff]/g,
            (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
        return base + '[' + quoted + ']';
    }
    const indexPath = (base, i) => base + '[' + i + ']';

    function humanize(id) {
        return id.split('_').map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    }

    const cats = () => asObj(asObj(state.config).cats);
    const attrsOf = (def) => asObj(asObj(def).attrs);
    const attrLabel = (def, id) => {
        const attr = attrsOf(def)[id];
        return isObj(attr) && typeof attr.label === 'string' ? attr.label : id;
    };
    const isHiddenAttr = (def, id) => isObj(attrsOf(def)[id]) && attrsOf(def)[id].hidden === true;
    const catName = (id) => {
        const def = cats()[id];
        return isObj(def) && typeof def.name === 'string' && def.name ? def.name : id;
    };
    const isDirty = () => state.jsonError !== '' || JSON.stringify(state.config) !== state.baseline;

    // ------------------------------------------------------------------ form controls
    let uid = 0;
    function nextId() {
        uid += 1;
        return 'cfg-' + uid;
    }

    function fieldEdited(el) {
        el.classList.remove('is-invalid');
        const feedback = el.parentElement && el.parentElement.querySelector(':scope > .invalid-feedback');
        if (feedback) {
            feedback.remove();
        }
        changed();
    }

    function labelled(label, control, help) {
        const id = nextId();
        control.id = id;
        return h('div', {class: 'mb-2'},
            h('label', {class: 'form-label mb-1', for: id}, label), control,
            help ? h('div', {class: 'form-text'}, help) : null);
    }

    function textInput(path, value, onSet, extra) {
        const el = h('input', Object.assign({
            type: 'text', class: 'form-control', autocomplete: 'off', 'data-path': path,
            value: value === undefined || value === null ? '' : String(value),
        }, extra || {}));
        el.addEventListener('input', () => {
            onSet(el.value);
            fieldEdited(el);
        });
        return el;
    }

    function numberInput(path, value, onSet) {
        const el = h('input', {
            type: 'number', class: 'form-control', 'data-path': path,
            value: value === undefined || value === null ? '' : String(value),
        });
        el.addEventListener('input', () => {
            onSet(el.value === '' ? '' : Number(el.value));
            fieldEdited(el);
        });
        return el;
    }

    function selectInput(path, value, options, onSet, extra) {
        const el = h('select', Object.assign({class: 'form-select', 'data-path': path}, extra || {}),
            options.map(([v, label]) => h('option', {value: v}, label)));
        const current = value === undefined || value === null ? '' : String(value);
        if (!options.some(([v]) => v === current)) {
            el.prepend(h('option', {value: current}, (current || '(empty)') + ' (not allowed)'));
        }
        el.value = current;
        el.addEventListener('change', () => {
            onSet(el.value);
            fieldEdited(el);
        });
        return el;
    }

    function checkInput(path, checked, label, onSet, extra) {
        const id = nextId();
        const el = h('input', Object.assign({
            type: 'checkbox', class: 'form-check-input', id, checked: checked === true, 'data-path': path || null,
        }, extra || {}));
        el.addEventListener('change', () => {
            onSet(el.checked);
            fieldEdited(el);
        });
        return h('div', {class: 'form-check'}, el, h('label', {class: 'form-check-label small', for: id}, label));
    }

    function iconButton(icon, label, onClick, disabled) {
        return h('button', {
            type: 'button', class: 'btn btn-outline-secondary', title: label, disabled: disabled === true,
            'aria-label': label, onclick: onClick,
        }, h('i', {class: 'bi ' + icon, 'aria-hidden': 'true'}));
    }

    // Row for a list entry which is not an object: it cannot be edited with forms, only removed.
    function invalidRow(what, onRemove) {
        return h('div', {class: 'd-flex align-items-center gap-2 border rounded p-2 mb-2 text-danger small'},
            h('span', {class: 'flex-grow-1'}, what + ' is not an object: fix it in the JSON editor or remove it.'),
            iconButton('bi-x-lg', 'Remove', onRemove));
    }

    // The hide and delete icons: tooltip on hover and keyboard focus. A reason makes the icon inert but still
    // focusable, so the tooltip can explain why.
    function actionButton(icon, tip, onClick, inertReason, extra) {
        const text = inertReason || tip;
        const el = h('button', Object.assign({
            type: 'button', class: 'btn btn-outline-secondary config-action' + (inertReason ? ' disabled' : ''),
            title: text, 'aria-label': text, 'aria-disabled': inertReason ? 'true' : null,
            'data-bs-toggle': 'tooltip', 'data-bs-trigger': 'hover focus',
        }, extra || {}), h('i', {class: 'bi ' + icon, 'aria-hidden': 'true'}));
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
        for (const id of ['config-validate', 'config-reload', 'config-upload-button']) {
            $(id).disabled = state.busy;
        }
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
        box.append(h('div', {class: 'alert alert-' + level + ' alert-dismissible fade show', role: 'alert'},
            message, h('button', {type: 'button', class: 'btn-close', 'data-bs-dismiss': 'alert', 'aria-label': 'Close'})));
    }

    function showErrors(errors) {
        state.errors = errors || [];
        const box = $('config-errors');
        clear(box);
        if (state.errors.length === 0) {
            return;
        }
        const showLinks = state.tab === 'forms' && state.jsonError === '';
        const items = state.errors.map((error) => h('li', {class: 'mb-1'},
            error.path ? h('code', {class: 'me-1'}, error.path) : h('em', {class: 'me-1'}, '(whole configuration)'),
            error.message,
            error.path && showLinks ? h('button', {
                type: 'button', class: 'btn btn-link py-0 ms-1', onclick: () => goToPath(error.path),
            }, 'Show') : null));
        box.append(h('div', {class: 'alert alert-danger', role: 'alert'},
            h('strong', {}, state.errors.length === 1 ? '1 problem' : state.errors.length + ' problems'),
            ' in the configuration. Nothing was saved.', h('ul', {class: 'mb-0 mt-2'}, items)));
        markErrors();
    }

    function markErrors() {
        app.querySelectorAll('[data-path].is-invalid').forEach((el) => el.classList.remove('is-invalid'));
        app.querySelectorAll('.invalid-feedback').forEach((el) => el.remove());
        for (const error of state.errors) {
            for (const el of app.querySelectorAll('#panel-forms [data-path]')) {
                if (el.dataset.path === error.path && !el.classList.contains('is-invalid')) {
                    el.classList.add('is-invalid');
                    el.setAttribute('aria-invalid', 'true');
                    el.after(h('div', {class: 'invalid-feedback'}, error.message));
                }
            }
        }
    }

    function goToPath(path) {
        if (state.tab !== 'forms') {
            return;
        }
        const found = /^cats(?:\.([A-Za-z0-9_-]+)|\[("(?:[^"\\]|\\.)*")\])/.exec(path);
        if (found) {
            const id = found[1] !== undefined ? found[1] : JSON.parse(found[2]);
            if (id in cats() && state.selected !== id) {
                state.selected = id;
                refresh();
            }
        }
        let probe = path;
        while (probe) {
            for (const el of app.querySelectorAll('#panel-forms [data-path]')) {
                if (el.dataset.path === probe) {
                    const details = el.closest('details');
                    if (details) {
                        details.open = true;
                    }
                    el.scrollIntoView({block: 'center'});
                    el.focus();
                    return;
                }
            }
            probe = probe.replace(/(\.[A-Za-z0-9_-]+|\[[^\]]*\])$/, '');
            if (probe === path) {
                break;
            }
        }
    }

    // ------------------------------------------------------------------ confirmation dialog
    const modalEl = $('configConfirmModal');
    const modal = (typeof bootstrap !== 'undefined' && modalEl) ? new bootstrap.Modal(modalEl) : null;
    let pending = null;                  // resolver of the dialog being shown
    let closing = null;                  // set while a dialog is fading out; a new one waits for it
    let returnFocus = null;

    async function confirmDialog(title, bodyNodes, confirmText, icon) {
        if (modal === null) {                        // Bootstrap did not load: never skip the confirmation
            const text = bodyNodes.map((n) => (n instanceof Node ? n.textContent : String(n))).join('\n\n');
            return window.confirm(title + '\n\n' + text);
        }
        if (closing) {
            await closing.done;
        }
        return new Promise((resolve) => {
            $('configConfirmTitle').textContent = title;
            $('configConfirmIcon').className = 'bi ' + (icon || 'bi-exclamation-triangle-fill');
            const body = $('configConfirmBody');
            clear(body);
            append(body, bodyNodes);
            $('configConfirmSubmit').textContent = confirmText;
            returnFocus = document.activeElement;
            pending = resolve;
            modal.show();
        });
    }

    if (modal !== null) {
        $('configConfirmSubmit').addEventListener('click', () => {
            const resolve = pending;
            pending = null;
            modal.hide();
            if (resolve) {
                resolve(true);
            }
        });
        modalEl.addEventListener('shown.bs.modal', () => $('configConfirmCancel').focus());
        modalEl.addEventListener('hide.bs.modal', () => {        // Cancel, close button, Escape, backdrop
            let finish;
            closing = {done: new Promise((resolve) => { finish = resolve; }), finish};
            const resolve = pending;
            pending = null;
            if (resolve) {
                resolve(false);
            }
        });
        modalEl.addEventListener('hidden.bs.modal', () => {
            if (closing) {
                closing.finish();
                closing = null;
            }
            if (returnFocus && document.contains(returnFocus)) {
                returnFocus.focus();
            }
        });
    }

    // ------------------------------------------------------------------ server requests
    async function request(url, options) {
        const settings = Object.assign({method: 'GET', credentials: 'same-origin', redirect: 'manual'}, options);
        settings.headers = Object.assign({'X-CSRFToken': csrfToken, Accept: 'application/json'}, settings.headers);
        let response;
        try {
            response = await fetch(url, settings);
        } catch (error) {
            return {status: 0, data: null,
                error: 'The server cannot be reached. Your changes are still in the editor.'};
        }
        if (response.type === 'opaqueredirect' || response.redirected) {
            return {status: 302, data: null,
                error: 'You are no longer logged in. Log in again in another tab; your changes are still in the editor.'};
        }
        let data = null;
        try {
            data = await response.json();
        } catch (error) {
            data = null;
        }
        const refusal = data && Array.isArray(data.errors) && data.errors.length ? data.errors[0].message : '';
        return {status: response.status, ok: response.ok, data,
            error: response.ok ? '' : (refusal || 'The server answered with status ' + response.status + '.')};
    }

    function postJson(url, payload, headers) {
        return request(url, {method: 'POST', body: typeof payload === 'string' ? payload : JSON.stringify(payload),
            headers: Object.assign({'Content-Type': 'application/json'}, headers)});
    }

    async function withBusy(work) {
        state.busy = true;
        updateStatus();
        try {
            return await work();
        } finally {
            state.busy = false;
            updateStatus();
        }
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
        $('config-conflict').replaceChildren();
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

    // Parses the JSON text; on success it becomes the state, on failure the state is left alone.
    function commitJson() {
        const text = $('config-json').value;
        let parsed;
        try {
            parsed = JSON.parse(text);
        } catch (error) {
            state.jsonError = String(error.message);
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
        for (const name of ['forms', 'json', 'preview']) {
            $('panel-' + name).classList.toggle('d-none', name !== tab);
            const button = $('tab-' + name);
            button.classList.toggle('active', name === tab);
            button.setAttribute('aria-selected', String(name === tab));
        }
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
        const set = (key) => (v) => {
            ensureObj(state.config, 'general')[key] = v;
        };
        box.append(
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('CSV separator',
                textInput('general.csv_sep', general.csv_sep, set('csv_sep'), {maxlength: 1}),
                'One character, used in CSV exports and imports.')),
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('Line ending',
                selectInput('general.eol_sep', general.eol_sep, [['\n', 'LF (\\n)'], ['\r\n', 'CRLF (\\r\\n)']],
                    set('eol_sep')))),
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('Short description length',
                numberInput('general.short_desc_len', general.short_desc_len, set('short_desc_len')),
                'Characters, 10 to 1000.')),
            h('div', {class: 'col-sm-6 col-xl-3'}, labelled('Maximum depth',
                numberInput('general.max_depth', general.max_depth, set('max_depth')),
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
        for (const id of ids) {
            const active = id === state.selected;
            list.append(h('li', {class: 'list-group-item d-flex align-items-center p-0' + (active ? ' active' : '')},
                h('button', {
                    type: 'button', class: 'btn btn-link text-start flex-grow-1 text-decoration-none py-2'
                        + (active ? ' text-white' : ''),
                    'aria-current': active ? 'true' : null,
                    onclick: () => {
                        state.selected = id;
                        refresh();
                    },
                }, h('span', {class: 'fw-bold'}, catName(id)), ' ', h('span', {class: 'small opacity-75'}, id)),
                h('span', {class: 'pe-2'}, actionButton('bi-trash',
                    'Delete category ' + catName(id) + ' from the configuration: its settings are lost. Its saved items are kept.',
                    () => removeDefinition(id, null)))));
        }
        initTooltips(list);
    }

    function newCategory(level, abbr, name) {
        const column = (header, attr) => ({header, attrs: [attr]});
        const layout = () => [column('Domain', 'domain'), column('Name', 'name'), column('Title', 'title'),
            column('Text', 'value')];
        return {
            name, level, abbr, page_size: 100, ext_attrs: [], expand: {s_link: 'None', p_link: 'None'},
            short_desc: {expand_text: ['name'], href_tip: ['name'], expand_tip: ['name']},
            tracs: [], links: {}, validators: [],
            access_from_index: {level: level === 'application' ? 'Application' : 'Project'},
            attrs: {
                domain: {label: 'Domain', req_in_form: true, kind: 'plain_text'},
                name: {label: 'Name', req_in_form: true, kind: 'plain_text'},
                title: {label: 'Title', req_in_form: false, kind: 'plain_text'},
                value: {label: 'Text', req_in_form: false, kind: 'ref_text'},
            },
            p_kind_choices: {}, s_kind_choices: {}, disp_def: layout(), disp_short: layout(), disp_trac: layout(),
        };
    }

    function setupAddCategory() {
        const form = $('add-category-form');
        $('add-category-open').addEventListener('click', () => {
            form.classList.remove('d-none');
            $('new-cat-id').focus();
        });
        $('add-category-cancel').addEventListener('click', () => {
            form.classList.add('d-none');
            form.reset();
            $('add-category-error').textContent = '';
        });
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            const id = $('new-cat-id').value.trim();
            const problem = $('add-category-error');
            if (!/^[A-Za-z][A-Za-z0-9_]{0,23}$/.test(id)) {
                problem.textContent = 'The identifier must be 1-24 letters, digits or underscores and start with a letter.';
                return;
            }
            if (Object.keys(cats()).some((existing) => existing.toLowerCase() === id.toLowerCase())) {
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
    // the stored data is kept). Hiding a field only sets `hidden` on its definition: everything is kept.
    async function removeDefinition(catId, attrId) {
        const def = asObj(cats()[catId]);
        let title;
        let body;
        if (attrId === null) {
            title = 'Delete category "' + catName(catId) + '"?';
            body = [
                h('p', {}, 'The definition of category ', h('strong', {}, catName(catId)), ' (identifier ',
                    h('code', {}, catId), ') will be deleted from the configuration: the category is no longer shown '
                    + 'in the menus, lists and forms of this project, and the references to it in other categories '
                    + '(expansions, traceability, relationship rules, validators, table columns) are removed.'),
                h('p', {}, 'Its saved data will not be deleted: items, history, releases, relationships and '
                    + 'assignments stay as they are and are still exported with the project. Adding a category with '
                    + 'the same identifier shows them again, but its settings and the references to it have to be '
                    + 'set up again.'),
                h('p', {class: 'mb-0'}, 'Nothing is stored until you save.'),
            ];
        } else {
            title = 'Delete field "' + attrLabel(def, attrId) + '"?';
            body = [
                h('p', {}, 'The definition of field ', h('strong', {}, attrLabel(def, attrId)), ' (', h('code', {}, attrId),
                    ') of category ', h('strong', {}, catName(catId)), ' (', h('code', {}, catId),
                    ') will be deleted from the configuration: it is no longer shown in its forms, lists and CSV '
                    + 'exports, and the references to it in the table layouts, short descriptions and validators of '
                    + 'this category are removed.'),
                h('p', {}, 'Its saved data will not be deleted: the values stay with the items, survive editing and '
                    + 'are still exported with the project. Adding the field again shows them in the forms again, but '
                    + 'its settings, table columns and short descriptions have to be set up again.'),
                h('p', {class: 'mb-0'}, 'To keep them, hide the field instead (',
                    h('i', {class: 'bi bi-eye-slash', 'aria-hidden': 'true'}), ' Hide). Nothing is stored until you save.'),
            ];
        }
        if (!await confirmDialog(title, body, 'Delete', 'bi-trash-fill')) {
            return;
        }
        const payload = {config: state.config, cat: catId};
        if (attrId !== null) {
            payload.attr = attrId;
        }
        const result = await withBusy(() => postJson(urls.remove, payload));
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

    // Hide or show a field: only its `hidden` setting changes, so showing it again restores everything.
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
        const again = $('category-editor').querySelector('[data-toggle-hidden="' + CSS.escape(attrId) + '"]');
        if (again) {
            again.focus();
        }
    }

    // ------------------------------------------------------------------ editor: one category
    function section(id, title, summary, content) {
        const el = h('details', {class: 'config-section card mb-3', 'data-section': id},
            h('summary', {class: 'card-header fw-bold'}, title, ' ', h('span', {class: 'text-muted small fw-normal'}, summary || '')),
            h('div', {class: 'card-body'}, content));
        el.open = state.openSections.has(id);
        el.addEventListener('toggle', () => {
            if (el.open) {
                state.openSections.add(id);
            } else {
                state.openSections.delete(id);
            }
        });
        return el;
    }

    function renderCatEditor() {
        const box = $('category-editor');
        clear(box);
        const id = state.selected;
        const def = id === null ? null : cats()[id];
        if (!isObj(def)) {
            box.append(h('p', {class: 'text-muted'}, id === null
                ? 'Select a category, or add one.'
                : 'This category definition is not an object and cannot be edited with the forms. Fix it in the JSON editor or delete it.'));
            return;
        }
        const parts = [sectionBasics, sectionFields, sectionChoices, sectionRelations, sectionValidators,
            sectionLayouts, sectionShort];
        box.append(h('h3', {class: 'fs-5 mb-3'}, catName(id), ' ', h('code', {class: 'small'}, id)));
        for (const build of parts) {
            try {
                box.append(build(id, def));
            } catch (error) {
                box.append(h('div', {class: 'alert alert-warning'},
                    'A part of this category cannot be shown because its structure is invalid. Fix it in the JSON editor.'));
            }
        }
        initTooltips(box);
    }

    const col = (child) => h('div', {class: 'col-sm-6 col-xl-4'}, child);

    function sectionBasics(id, def) {
        const base = keyPath('cats', id);
        const accessPath = keyPath(keyPath(base, 'access_from_index'), 'level');
        const access = selectInput(accessPath, asObj(def.access_from_index).level,
            [['Project', 'Project index'], ['Application', 'Application index'], ['None', 'Not offered']],
            (v) => {
                ensureObj(def, 'access_from_index').level = v;
            });
        const level = selectInput(keyPath(base, 'level'), def.level,
            [['project', 'Project'], ['application', 'Application']], (v) => {
                def.level = v;
                if (asObj(def.access_from_index).level !== 'None') {
                    ensureObj(def, 'access_from_index').level = v === 'application' ? 'Application' : 'Project';
                    access.value = def.access_from_index.level;
                }
            });
        const identifier = h('input', {type: 'text', class: 'form-control', value: id, readonly: true});
        return section('basics', 'Basics', 'name, level, page size', h('div', {class: 'row g-2'},
            col(labelled('Identifier', identifier, 'Fixed: it is stored with every item.')),
            col(labelled('Name', textInput(keyPath(base, 'name'), def.name, (v) => {
                def.name = v;
                renderCatList();
            }))),
            col(labelled('Abbreviation', textInput(keyPath(base, 'abbr'), def.abbr, (v) => {
                def.abbr = v;
            }))),
            col(labelled('Level', level)),
            col(labelled('Offered from', access)),
            col(labelled('Page size', numberInput(keyPath(base, 'page_size'), def.page_size, (v) => {
                def.page_size = v;
            }), 'Items per list page, 1 to 1000.'))));
    }

    function uniqueLabel(def, wanted) {
        const used = new Set(Object.values(attrsOf(def)).map((a) => String(asObj(a).label).replace(/ /g, '').toLowerCase()));
        let label = wanted;
        let n = 2;
        while (used.has(label.replace(/ /g, '').toLowerCase())) {
            label = wanted + ' ' + n;
            n += 1;
        }
        return label;
    }

    function sectionFields(id, def) {
        const base = keyPath(keyPath('cats', id), 'attrs');
        const attrs = attrsOf(def);
        const mandatory = ['domain', 'name'];
        const allKinds = [...new Set(Object.values(meta.allowed_kinds).flat())];
        const rows = Object.keys(attrs).map((attrId) => {
            const path = keyPath(base, attrId);
            const attr = attrs[attrId];
            const hidden = isHiddenAttr(def, attrId);
            const required = mandatory.includes(attrId)
                ? (what) => 'Required: items are identified by ' + attrId + ', so it cannot be ' + what : () => null;
            const label = attrLabel(def, attrId);
            const toggleTip = hidden
                ? 'Show field ' + label + ' again: its forms, lists and CSV exports show it with its table columns and short descriptions.'
                : 'Hide field ' + label + ': it is no longer shown in forms, lists and CSV exports. Its values and settings are kept.';
            const toggle = isObj(attr) ? actionButton(hidden ? 'bi-eye' : 'bi-eye-slash', toggleTip,
                () => toggleHidden(id, attrId), required('hidden'), {'data-toggle-hidden': attrId}) : null;
            const remove = actionButton('bi-trash',
                'Delete field ' + label + ' from the configuration: its settings, table columns and short descriptions are lost. Its saved values are kept.',
                () => removeDefinition(id, attrId), required('deleted'));
            const actions = h('td', {class: 'text-end text-nowrap'}, toggle, toggle ? ' ' : null, remove);
            const known = attrId in meta.allowed_kinds;
            const name = h('td', {}, h('code', {}, attrId),
                hidden ? h('span', {class: 'badge bg-secondary ms-1'}, 'hidden') : null,
                known ? null : h('div', {class: 'text-danger small'}, 'unknown field'));
            if (!isObj(attr)) {
                return h('tr', {}, name, h('td', {colspan: 3, class: 'text-danger small'},
                    'Invalid definition: fix it in the JSON editor or delete it.'), actions);
            }
            return h('tr', {class: hidden ? 'config-hidden-row' : null}, name,
                h('td', {}, textInput(keyPath(path, 'label'), attr.label, (v) => {
                    attr.label = v;
                }, {'aria-label': 'Label of ' + attrId})),
                h('td', {}, selectInput(keyPath(path, 'kind'), attr.kind,
                    (meta.allowed_kinds[attrId] || allKinds).map((k) => [k, k]), (v) => {
                        attr.kind = v;
                    }, {'aria-label': 'Kind of ' + attrId})),
                h('td', {}, checkInput(keyPath(path, 'req_in_form'), attr.req_in_form, 'Required in form', (v) => {
                    attr.req_in_form = v;
                }, attr.req_in_form === true && mandatory.includes(attrId) ? {disabled: true} : {})),
                actions);
        });
        const free = Object.keys(meta.allowed_kinds).filter((name) => !(name in attrs));
        const picker = h('select', {class: 'form-select', 'aria-label': 'Field to add'},
            free.map((name) => h('option', {value: name}, name)));
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', disabled: free.length === 0,
            onclick: () => {
                const attrId = picker.value;
                ensureObj(def, 'attrs')[attrId] = {
                    label: uniqueLabel(def, humanize(attrId)), req_in_form: false, kind: meta.allowed_kinds[attrId][0],
                };
                changed();
                renderCatEditor();
            },
        }, h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add field');
        const hiddenCount = Object.keys(attrs).filter((attrId) => isHiddenAttr(def, attrId)).length;
        return section('fields', 'Fields', Object.keys(attrs).length + ' defined'
            + (hiddenCount ? ', ' + hiddenCount + ' hidden' : ''), [
            h('div', {class: 'table-responsive'}, h('table', {class: 'table table-hover table-sm align-middle config-table'},
                h('thead', {}, h('tr', {class: 'table-primary'}, h('th', {}, 'Field'), h('th', {}, 'Label'), h('th', {}, 'Kind'),
                    h('th', {}, 'Required'), h('th', {}))),
                h('tbody', {}, rows))),
            h('div', {class: 'input-group config-add-row'}, picker, add)]);
    }

    function renameKey(obj, oldKey, newKey) {
        const entries = Object.entries(obj);
        for (const [key] of entries) {
            delete obj[key];
        }
        for (const [key, value] of entries) {
            obj[key === oldKey ? newKey : key] = value;
        }
    }

    function choiceEditor(id, def, kind) {
        const key = kind + '_choices';
        const base = keyPath(keyPath('cats', id), key);
        const choices = asObj(def[key]);
        const rows = Object.keys(choices).map((value) => {
            const valueInput = h('input', {
                type: 'text', class: 'form-control', value, 'data-path': keyPath(base, value),
                'aria-label': 'Stored value',
            });
            valueInput.addEventListener('change', () => {
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
                type: 'text', class: 'form-control', value: String(choices[value]),
                'aria-label': 'Label of ' + value,
            });
            label.addEventListener('input', () => {
                ensureObj(def, key)[value] = label.value;
                changed();
            });
            return h('tr', {}, h('td', {}, valueInput), h('td', {}, label), h('td', {class: 'text-end'},
                iconButton('bi-x-lg', 'Remove choice ' + value, () => {
                    delete ensureObj(def, key)[value];
                    changed();
                    renderCatEditor();
                })));
        });
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', onclick: () => {
                const list = ensureObj(def, key);
                let n = Object.keys(list).length + 1;
                while (('NEW' + n) in list) {
                    n += 1;
                }
                list['NEW' + n] = 'New choice';
                changed();
                renderCatEditor();
            },
        }, h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add choice');
        return h('div', {class: 'mb-3'}, h('h4', {class: 'fs-6'}, kind + ' choices'),
            h('div', {class: 'table-responsive'}, h('table', {class: 'table table-hover table-sm align-middle config-table'},
                h('thead', {}, h('tr', {class: 'table-primary'}, h('th', {}, 'Stored value'), h('th', {}, 'Label'), h('th', {}))),
                h('tbody', {}, rows))), add);
    }

    function sectionChoices(id, def) {
        return section('choices', 'Choice lists', 'p_kind, s_kind', [
            h('p', {class: 'small text-muted'}, 'Values already stored with items must stay in the list; saving checks this.'),
            choiceEditor(id, def, 'p_kind'), choiceEditor(id, def, 's_kind')]);
    }

    // A small icon button for the entries of a list (move, remove); `light` for use on a dark chip.
    function miniButton(icon, label, onClick, disabled, light) {
        return h('button', {
            type: 'button', class: 'btn btn-sm config-mini' + (light ? ' text-white' : ''), title: label,
            'aria-label': label, disabled: disabled === true, onclick: onClick,
        }, h('i', {class: 'bi ' + icon, 'aria-hidden': 'true'}));
    }

    // A list of attribute names, in order, with buttons to move and remove each one and a picker for the unused
    // ones. The order is the order of the JSON list. `read` is the object holding the list (possibly a stand-in),
    // `write()` returns the real object, created only when edited. `vertical`: one entry per line (a table cell),
    // otherwise chips in a row.
    function attrListEditor(path, read, write, key, attrIds, def, vertical) {
        const names = asArr(read[key]);
        const edit = (change) => {
            change(ensureArr(write(), key));
            changed();
            renderCatEditor();
        };
        const swap = (i, j) => edit((list) => {
            [list[i], list[j]] = [list[j], list[i]];
        });
        const box = h(vertical ? 'ol' : 'div', {
            class: vertical ? 'list-unstyled mb-2 config-attr-list' : 'd-flex flex-wrap gap-1 align-items-center',
            'data-path': path, tabindex: '-1',
        });
        for (const [i, name] of names.entries()) {
            const text = typeof name === 'string'
                ? attrLabel(def, name) + ' (' + name + (isHiddenAttr(def, name) ? ', hidden' : '') + ')' : String(name);
            const tools = [
                miniButton(vertical ? 'bi-arrow-up' : 'bi-chevron-left', 'Move ' + text + (vertical ? ' up' : ' left'),
                    () => swap(i, i - 1), i === 0, !vertical),
                miniButton(vertical ? 'bi-arrow-down' : 'bi-chevron-right', 'Move ' + text + (vertical ? ' down' : ' right'),
                    () => swap(i, i + 1), i === names.length - 1, !vertical),
                miniButton('bi-x-lg', 'Remove ' + text, () => edit((list) => list.splice(i, 1)), false, !vertical),
            ];
            const itemPath = indexPath(path, i);
            box.append(vertical
                ? h('li', {class: 'd-flex align-items-center gap-1 config-attr-item', 'data-path': itemPath},
                    h('span', {class: 'flex-grow-1' + (isHiddenAttr(def, name) ? ' text-muted' : '')},
                        typeof name === 'string' ? h('strong', {}, attrLabel(def, name)) : String(name),
                        typeof name === 'string' ? h('span', {class: 'small text-muted ms-1'}, name) : null,
                        isHiddenAttr(def, name) ? h('span', {class: 'badge bg-secondary ms-1'}, 'hidden') : null),
                    tools)
                : h('span', {class: 'badge bg-secondary config-chip d-inline-flex align-items-center', 'data-path': itemPath},
                    h('span', {class: 'me-1'}, text), tools));
        }
        const free = attrIds.filter((name) => !names.includes(name));
        if (free.length) {
            const picker = h('select', {
                class: 'form-select ' + (vertical ? 'form-select-sm' : 'w-auto'), 'aria-label': 'Add attribute to ' + key,
            }, h('option', {value: ''}, vertical ? '+ add attribute...' : 'add attribute...'),
            free.map((name) => h('option', {value: name}, attrLabel(def, name) + ' (' + name + ')')));
            picker.addEventListener('change', () => {
                if (picker.value) {
                    edit((list) => list.push(picker.value));
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
        const links = () => ensureObj(def, 'links');
        const modeSelect = selectInput(base, mode, [['none', 'No rule: no choices are offered'],
            ['targets', 'Items of these categories only'], ['all_except', 'Items of every category except these']], (v) => {
            if (v === 'none') {
                delete links()[link];
            } else {
                const current = ensureObj(links(), link);
                const names = asArr(current.targets || current.all_except);
                delete current.targets;
                delete current.all_except;
                current[v] = [...names];
            }
            changed();
            renderCatEditor();
        });
        box.append(h('div', {class: 'fw-bold mb-2'}, link + ' (' + attrLabel(def, link) + ')'),
            labelled('Allowed targets', modeSelect));
        if (mode !== 'none') {
            const listed = asArr(rule[mode]);
            const checks = Object.keys(cats()).map((cat) => checkInput(
                listed.includes(cat) ? indexPath(keyPath(base, mode), listed.indexOf(cat)) : null,
                listed.includes(cat), catName(cat) + ' (' + cat + ')', (on) => {
                    const names = ensureArr(links()[link], mode);
                    const at = names.indexOf(cat);
                    if (on && at < 0) {
                        names.push(cat);
                    } else if (!on && at >= 0) {
                        names.splice(at, 1);
                    }
                }));
            // Targets which are not categories of the configuration stay visible so they can be removed
            for (const name of listed.filter((n) => !(n in cats()))) {
                checks.push(checkInput(indexPath(keyPath(base, mode), listed.indexOf(name)), true,
                    String(name) + ' (undefined category)', (on) => {
                        if (!on) {
                            const names = ensureArr(links()[link], mode);
                            names.splice(names.indexOf(name), 1);
                        }
                    }));
            }
            box.append(h('div', {class: 'config-check-grid mb-2', 'data-path': keyPath(base, mode)}, checks));
            box.append(h('div', {class: 'row g-2'},
                col(labelled('Scope', selectInput(keyPath(base, 'scope'), rule.scope || 'project',
                    [['project', 'Whole project'], ['application', 'Same application only']], (v) => {
                        links()[link].scope = v;
                    }))),
                col(h('div', {class: 'mb-2'}, h('div', {class: 'form-label mb-1'}, 'Order by'),
                    h('div', {class: 'd-flex gap-3', 'data-path': keyPath(base, 'order_by')}, ORDER_FIELDS.map((field) => {
                        const current = Array.isArray(rule.order_by) ? rule.order_by : ['domain', 'name'];
                        return checkInput(keyPath(base, 'order_by'), current.includes(field), field, (on) => {
                            const now = new Set(Array.isArray(links()[link].order_by) ? links()[link].order_by : ['domain', 'name']);
                            if (on) {
                                now.add(field);
                            } else {
                                now.delete(field);
                            }
                            links()[link].order_by = ORDER_FIELDS.filter((f) => now.has(f));
                        });
                    }))))));
            const narrow = isObj(rule.narrow_by_other_parent);
            const narrowBox = h('div', {class: 'row g-2 mt-1' + (narrow ? '' : ' d-none')},
                col(labelled('Target field', selectInput(keyPath(keyPath(base, 'narrow_by_other_parent'), 'target_field'),
                    asObj(rule.narrow_by_other_parent).target_field, LINKS.map((l) => [l, l]), (v) => {
                        ensureObj(links()[link], 'narrow_by_other_parent').target_field = v;
                    }))),
                col(labelled('Parent field', selectInput(keyPath(keyPath(base, 'narrow_by_other_parent'), 'parent_field'),
                    asObj(rule.narrow_by_other_parent).parent_field, LINKS.map((l) => [l, l]), (v) => {
                        ensureObj(links()[link], 'narrow_by_other_parent').parent_field = v;
                    }))));
            box.append(checkInput(keyPath(base, 'narrow_by_other_parent'), narrow,
                'Narrow by the other parent (only targets whose target field equals the parent field of the other parent item)',
                (on) => {
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
        const options = [['None', 'None']].concat(Object.keys(cats()).map((c) => [c, catName(c) + ' (' + c + ')']));
        const set = (key, v) => {
            ensureObj(def, 'expand')[key] = v;
        };
        return h('div', {class: 'mb-3'}, h('h4', {class: 'fs-6'}, 'Expansion of linked items'),
            h('div', {class: 'row g-2'}, LINKS.flatMap((link) => [
                col(labelled(link + ' expands to', selectInput(keyPath(base, link), expand[link], options, (v) => set(link, v)))),
                col(labelled(link + ' label', textInput(keyPath(base, link[0] + '_label'), expand[link[0] + '_label'],
                    (v) => set(link[0] + '_label', v)))),
            ])));
    }

    function tracsEditor(id, def) {
        const base = keyPath(keyPath('cats', id), 'tracs');
        const tracs = asArr(def.tracs);
        const options = Object.keys(cats()).map((c) => [c, catName(c) + ' (' + c + ')']);
        const rows = tracs.map((trac, i) => {
            const path = indexPath(base, i);
            const entry = asObj(trac);
            if (!isObj(trac)) {
                return invalidRow('The traceability link', () => {
                    def.tracs.splice(i, 1);
                    changed();
                    renderCatEditor();
                });
            }
            return h('div', {class: 'row g-2 align-items-end'},
                col(labelled('Link category', selectInput(path + '.trac_cat', entry.trac_cat, options, (v) => {
                    def.tracs[i].trac_cat = v;
                }))),
                col(labelled('Endpoint pointing here', selectInput(path + '.trac_link', entry.trac_link,
                    LINKS.map((l) => [l, l]), (v) => {
                        def.tracs[i].trac_link = v;
                    }))),
                h('div', {class: 'col-auto mb-2'}, iconButton('bi-x-lg', 'Remove traceability link', () => {
                    def.tracs.splice(i, 1);
                    changed();
                    renderCatEditor();
                })));
        });
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', disabled: options.length === 0, onclick: () => {
                ensureArr(def, 'tracs').push({trac_cat: options[0][0], trac_link: 'p_link'});
                changed();
                renderCatEditor();
            },
        }, h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add traceability link');
        return h('div', {class: 'mb-2'}, h('h4', {class: 'fs-6'}, 'Traceability'), rows, add);
    }

    function sectionRelations(id, def) {
        return section('relations', 'Relationships', 'p_link, s_link, expansion, traceability', [
            ruleEditor(id, def, 'p_link'), ruleEditor(id, def, 's_link'), expandEditor(id, def), tracsEditor(id, def)]);
    }

    function validatorEditor(id, def) {
        const base = keyPath(keyPath('cats', id), 'validators');
        const specs = asArr(def.validators);
        const catOptions = Object.keys(cats()).map((c) => [c, catName(c) + ' (' + c + ')']);
        const attrOptions = Object.keys(attrsOf(def)).map((a) => [a, attrLabel(def, a) + ' (' + a + ')']);
        const names = Object.keys(meta.validators);
        const rows = specs.map((spec, i) => {
            const path = indexPath(base, i);
            const entry = asObj(spec);
            const params = asObj(entry.params);
            if (!isObj(spec)) {
                return invalidRow('The validator', () => {
                    def.validators.splice(i, 1);
                    changed();
                    renderCatEditor();
                });
            }
            const kinds = meta.validators[entry.name];
            const head = h('div', {class: 'd-flex align-items-center gap-2 mb-2'},
                h('div', {class: 'flex-grow-1'}, selectInput(path + '.name', entry.name, names.map((n) => [n, n]), (v) => {
                    def.validators[i] = {name: v, params: defaultParams(meta.validators[v], def)};
                    changed();
                    renderCatEditor();
                })),
                iconButton('bi-x-lg', 'Remove validator', () => {
                    def.validators.splice(i, 1);
                    changed();
                    renderCatEditor();
                }));
            const fields = kinds === undefined
                ? h('p', {class: 'text-danger small mb-0'}, 'This validator is not supported; saving will be refused. Remove it or choose another one.')
                : h('div', {class: 'row g-2'}, Object.entries(kinds).map(([param, kind]) => {
                    const set = (v) => {
                        ensureObj(def.validators[i], 'params')[param] = v;
                    };
                    const ppath = path + '.params.' + param;
                    let control;
                    if (kind === 'link') {
                        control = selectInput(ppath, params[param], LINKS.map((l) => [l, l]), set);
                    } else if (kind === 'cat') {
                        control = selectInput(ppath, params[param], catOptions, set);
                    } else if (kind === 'attr') {
                        control = selectInput(ppath, params[param], attrOptions, set);
                    } else {
                        control = textInput(ppath, params[param], set, {maxlength: 300});
                    }
                    return col(labelled(param, control));
                }));
            return h('div', {class: 'border rounded p-2 mb-2'}, head, fields);
        });
        const picker = h('select', {class: 'form-select', 'aria-label': 'Validator to add'},
            names.map((n) => h('option', {value: n}, n)));
        const add = h('button', {
            type: 'button', class: 'btn btn-outline-primary', onclick: () => {
                ensureArr(def, 'validators').push({name: picker.value, params: defaultParams(meta.validators[picker.value], def)});
                changed();
                renderCatEditor();
            },
        }, h('i', {class: 'bi bi-plus-circle me-1', 'aria-hidden': 'true'}), 'Add validator');
        return [h('p', {class: 'small text-muted'},
            'Validators are chosen from the list the server supports; the configuration never contains code.'),
            rows, h('div', {class: 'input-group config-add-row'}, picker, add)];
    }

    function defaultParams(kinds, def) {
        const params = {};
        for (const [param, kind] of Object.entries(kinds || {})) {
            if (kind === 'link') {
                params[param] = 'p_link';
            } else if (kind === 'cat') {
                params[param] = Object.keys(cats())[0] || '';
            } else if (kind === 'attr') {
                params[param] = Object.keys(attrsOf(def))[0] || '';
            } else {
                params[param] = '';
            }
        }
        return params;
    }

    function sectionValidators(id, def) {
        return section('validators', 'Validators', asArr(def.validators).length + ' defined', validatorEditor(id, def));
    }

    // Focus the control with the JSON path `path` after the editor was drawn again.
    function focusPath(path) {
        const el = Array.from($('category-editor').querySelectorAll('[data-path]')).find((e) => e.dataset.path === path);
        if (el) {
            const details = el.closest('details');
            if (details) {
                details.open = true;
            }
            el.focus();
        }
    }

    // A table layout drawn as the list it produces: one table column per layout column. Above the header row are
    // the column tools (move, remove), the header row holds the column headers as in the list, the body the
    // attributes of each column in the order the list shows them (or the link of a traceability column), the last
    // row the sorting. The buttons next to the title add columns at the end.
    function layoutEditor(id, def, key, title) {
        const base = keyPath(keyPath('cats', id), key);
        const columns = asArr(def[key]);
        const attrIds = Object.keys(attrsOf(def));
        const edit = (change, focus) => {
            change(ensureArr(def, key));
            changed();
            renderCatEditor();
            if (focus) {
                focusPath(focus);
            }
        };
        const move = (i, by) => edit((list) => {
            [list[i], list[i + by]] = [list[i + by], list[i]];
        });
        const tools = [];
        const heads = [];
        const cells = [];
        const sorts = [];
        for (const [i, column] of columns.entries()) {
            const path = indexPath(base, i);
            const name = isObj(column) && typeof column.header === 'string' && column.header ? column.header : 'column ' + (i + 1);
            tools.push(h('td', {class: 'text-center text-nowrap config-layout-tools', 'data-path': path, tabindex: '-1'},
                h('div', {class: 'btn-group btn-group-sm', role: 'group', 'aria-label': 'Column ' + name},
                    iconButton('bi-arrow-left', 'Move column ' + name + ' left', () => move(i, -1), i === 0),
                    iconButton('bi-arrow-right', 'Move column ' + name + ' right', () => move(i, 1), i === columns.length - 1),
                    iconButton('bi-x-lg', 'Remove column ' + name, () => edit((list) => list.splice(i, 1))))));
            if (!isObj(column)) {
                heads.push(h('th', {class: 'config-layout-col text-danger'}, 'Invalid column'));
                cells.push(h('td', {class: 'text-danger small'}, 'The column is not an object: fix it in the JSON editor or remove it.'));
                sorts.push(h('td', {}));
                continue;
            }
            heads.push(h('th', {class: 'config-layout-col'}, textInput(path + '.header', column.header, (v) => {
                column.header = v;
            }, {class: 'form-control form-control-sm fw-bold', 'aria-label': 'Header of column ' + (i + 1)})));
            if ('trac_cat' in column) {
                cells.push(h('td', {},
                    h('div', {class: 'small text-muted mb-1'}, 'Traceability: items linked through'),
                    selectInput(path + '.trac_cat', column.trac_cat, Object.keys(cats()).map((c) => [c, catName(c) + ' (' + c + ')']),
                        (v) => {
                            column.trac_cat = v;
                        }, {class: 'form-select form-select-sm mb-1', 'aria-label': 'Link category of column ' + (i + 1)}),
                    selectInput(path + '.trac_link', column.trac_link, LINKS.map((l) => [l, l]), (v) => {
                        column.trac_link = v;
                    }, {class: 'form-select form-select-sm', 'aria-label': 'Endpoint of column ' + (i + 1)})));
                sorts.push(h('td', {class: 'small text-muted'}, 'not sortable'));
            } else {
                cells.push(h('td', {}, attrListEditor(path + '.attrs', column, () => column, 'attrs', attrIds, def, true)));
                sorts.push(h('td', {}, selectInput(path + '.order_by', column.order_by || '',
                    [['', 'not sortable']].concat(attrIds.map((a) => [a, 'sort by ' + attrLabel(def, a)])), (v) => {
                        if (v) {
                            column.order_by = v;
                        } else {
                            delete column.order_by;
                        }
                    }, {class: 'form-select form-select-sm', 'aria-label': 'Sorting of column ' + (i + 1)})));
            }
        }
        const unused = attrIds.find((a) => !columns.some((c) => isObj(c) && asArr(c.attrs).includes(a))) || attrIds[0];
        const addColumn = h('button', {
            type: 'button', class: 'btn btn-sm btn-outline-primary text-nowrap', disabled: attrIds.length === 0, onclick: () => {
                edit((list) => list.push({header: attrLabel(def, unused), attrs: [unused]}), indexPath(base, columns.length) + '.header');
            },
        }, h('i', {class: 'bi bi-plus-lg me-1', 'aria-hidden': 'true'}), 'Add column');
        const addTrac = key === 'disp_trac' ? h('button', {
            type: 'button', class: 'btn btn-sm btn-outline-primary text-nowrap', disabled: Object.keys(cats()).length === 0,
            onclick: () => {
                edit((list) => list.push({header: 'Links', trac_cat: Object.keys(cats())[0], trac_link: 'p_link'}),
                    indexPath(base, columns.length) + '.header');
            },
        }, h('i', {class: 'bi bi-plus-lg me-1', 'aria-hidden': 'true'}), 'Add traceability column') : null;
        const table = h('table', {class: 'table table-bordered table-sm align-top mb-0 config-layout'},
            h('thead', {},
                h('tr', {class: 'config-layout-toolrow'}, tools),
                h('tr', {class: 'table-primary'}, heads)),
            h('tbody', {},
                h('tr', {}, cells),
                h('tr', {class: 'config-layout-sortrow'}, sorts)));
        return h('div', {class: 'mb-4', 'data-path': base, tabindex: '-1'},
            h('div', {class: 'd-flex flex-wrap align-items-center gap-2 mb-2'},
                h('h4', {class: 'fs-6 mb-0 me-auto'}, title, ' ', h('span', {class: 'text-muted small fw-normal'},
                    columns.length === 1 ? '1 column' : columns.length + ' columns')),
                addColumn, addTrac),
            columns.length
                ? h('div', {class: 'table-responsive'}, table)
                : h('p', {class: 'small text-muted border rounded p-2 mb-0'}, 'No column: the list shows only the item buttons.'));
    }

    function sectionLayouts(id, def) {
        return section('layouts', 'Table layouts', 'default, short and traceability lists', [
            layoutEditor(id, def, 'disp_def', 'Default list'), layoutEditor(id, def, 'disp_short', 'Short list'),
            layoutEditor(id, def, 'disp_trac', 'Traceability list')]);
    }

    function sectionShort(id, def) {
        const base = keyPath('cats', id);
        const attrIds = Object.keys(attrsOf(def));
        const parts = [['expand_text', 'Expanded text'], ['href_tip', 'Link tooltip'], ['expand_tip', 'Expansion tooltip']];
        const content = parts.map(([key, title]) => h('div', {class: 'mb-3'}, h('div', {class: 'form-label mb-1'}, title),
            attrListEditor(keyPath(keyPath(base, 'short_desc'), key), asObj(def.short_desc),
                () => ensureObj(def, 'short_desc'), key, attrIds, def)));
        if (meta.external_cats.includes(id.toLowerCase()) || asArr(def.ext_attrs).length) {
            content.push(h('div', {class: 'mb-2'}, h('div', {class: 'form-label mb-1'}, 'Attributes taken from the external repository'),
                attrListEditor(keyPath(base, 'ext_attrs'), def, () => def, 'ext_attrs', attrIds, def)));
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
        const result = await withBusy(() => postJson(urls.validate, state.config));
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
        const result = await withBusy(() => postJson(urls.save, sent, {'X-Config-Token': state.token}));
        if (result.status === 200 && result.data && result.data.saved) {
            state.token = result.data.token;
            state.baseline = sent;
            showErrors([]);
            $('config-conflict').replaceChildren();
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
        box.replaceChildren(h('div', {class: 'alert alert-danger', role: 'alert'},
            h('strong', {}, 'Conflict: not saved. '),
            'The saved configuration was changed (by someone else or in another window) after you loaded it. ',
            'Your changes are still in this editor and were not saved. Download them if you want a copy, then reload ',
            'the saved configuration; saving is blocked until you do.',
            h('div', {class: 'mt-2'},
                h('button', {type: 'button', class: 'btn btn-outline-secondary me-2', onclick: downloadLocal},
                    'Download my changes'),
                h('button', {type: 'button', class: 'btn btn-danger', onclick: reload}, 'Reload saved configuration'))));
        updateStatus();
    }

    function downloadLocal() {
        const text = state.tab === 'json' ? $('config-json').value : JSON.stringify(state.config, null, 2) + '\n';
        const link = h('a', {
            href: URL.createObjectURL(new Blob([text], {type: 'application/json'})),
            download: 'cordetfw_project_' + projectId + '_config_unsaved.json',
        });
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }

    async function reload() {
        if (isDirty()) {
            const ok = await confirmDialog('Discard unsaved changes?', [
                h('p', {class: 'mb-0'}, 'The editor contains changes which are not saved. Reloading replaces them with the '
                    + 'configuration saved in the database; the changes will be lost.')], 'Discard and reload');
            if (!ok) {
                return;
            }
        }
        const result = await withBusy(() => request(urls.reload));
        if (result.ok && result.data && isObj(result.data.config)) {
            loadConfig(result.data.config, result.data.token);
            flash('info', 'Reloaded the saved configuration.');
        } else {
            flash('danger', 'The configuration could not be reloaded; the editor was not changed. ' + result.error);
        }
    }

    async function upload(file) {
        if (isDirty()) {
            const ok = await confirmDialog('Replace the editor contents?', [
                h('p', {class: 'mb-0'}, 'Loading the file replaces the changes in the editor which are not saved. '
                    + 'The file is not saved to the database either: use Save afterwards.')], 'Load file');
            if (!ok) {
                return;
            }
        }
        const form = new FormData();
        form.append('upload_file', file);
        const result = await withBusy(() => request(urls.upload, {method: 'POST', body: form}));
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

    // Categories opened or closed in the preview by the owner (identifier -> open); the others are closed, except
    // the category selected in the forms. Kept while the page is open, also when the preview is rendered again.
    const previewOpen = new Map();

    function setupPreviewCategories(target) {
        for (const details of target.querySelectorAll('details[data-cat]')) {
            const cat = details.dataset.cat;
            details.open = previewOpen.has(cat) ? previewOpen.get(cat) : cat === state.selected;
            // click (also Enter/Space on the summary) comes before the toggle: the new state is the opposite one
            details.querySelector('summary').addEventListener('click', () => previewOpen.set(cat, !details.open));
        }
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
        const result = await withBusy(() => postJson(urls.preview, state.config));
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
            target.append(h('p', {class: 'text-muted'}, 'The preview is shown when the configuration is valid. Fix the problems listed above.'));
        } else {
            target.append(h('p', {class: 'text-danger'}, result.error));
        }
    }

    // ------------------------------------------------------------------ start
    function start() {
        loadConfig(JSON.parse(document.getElementById('project-config-initial').textContent), app.dataset.token);
        setupAddCategory();
        for (const tab of ['forms', 'json', 'preview']) {
            $('tab-' + tab).addEventListener('click', () => switchTab(tab));
        }
        $('config-json').addEventListener('input', commitJson);
        $('config-save').addEventListener('click', save);
        $('config-validate').addEventListener('click', validate);
        $('config-reload').addEventListener('click', reload);
        $('preview-refresh').addEventListener('click', runPreview);
        $('config-upload-button').addEventListener('click', () => $('config-upload-file').click());
        $('config-upload-file').addEventListener('change', (event) => {
            const file = event.target.files[0];
            event.target.value = '';
            if (file) {
                upload(file);
            }
        });
        window.addEventListener('beforeunload', (event) => {
            if (isDirty()) {
                event.preventDefault();
                event.returnValue = '';
            }
        });
    }

    start();
}());
