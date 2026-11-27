/* Category picker for the comma-separated 'cats' field of the project and application forms
 * (editor/forms.py, CatPicker). Two lists: categories not added (left) and added (right, in the stored order),
 * moved with the arrow buttons or by double click. The text input stays the field that is posted: it is
 * hidden and rewritten on every change. Texts are set with textContent only.
 */
(function () {
    'use strict';

    function h(tag, attrs, children) {
        const el = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([k, v]) => {
            if (k === 'text') {
                el.textContent = v;
            } else {
                el.setAttribute(k, v);
            }
        });
        (children || []).forEach((c) => el.appendChild(c));
        return el;
    }

    // The layout is part of this file (not style.css), so a browser with an older cached style.css still shows
    // the lists side by side: not added on the left, added on the right.
    const CSS = [
        '.cat-picker-grid{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:.5rem;' +
            'align-items:stretch}',
        '.cat-picker-col{display:flex;flex-direction:column;min-width:0}',
        '.cat-picker-col select{flex:1;min-height:16rem}',
        '.cat-picker-title{font-weight:600;margin-bottom:.25rem}',
        '.cat-picker-spacer{height:calc(1.5em + .5rem + 2px);margin-bottom:.25rem}',
        '.cat-picker-buttons{display:flex;flex-direction:column;justify-content:center;gap:.25rem}',
        '.cat-picker-buttons .btn{font-size:1.15rem;line-height:1.2;min-width:2.75rem}',
    ].join('\n');

    function addStyle() {
        if (!document.getElementById('cat-picker-style')) {
            document.head.appendChild(h('style', {id: 'cat-picker-style', text: CSS}));
        }
    }

    function splitCats(value) {
        return value.split(',').map((c) => c.trim()).filter((c) => c !== '');
    }

    function init(box) {
        const input = box.querySelector('.cat-picker-input');
        if (!input || box.dataset.ready) {
            return;
        }
        box.dataset.ready = '1';
        addStyle();
        let options;
        try {
            options = JSON.parse(box.dataset.options || '[]');
        } catch (e) {
            return;                                   // keep the plain text input
        }
        const names = new Map(options.map((o) => [o.id, o.name]));
        // a category with a note (e.g. 'project level') is not offered; if already added it can only be removed
        const notes = new Map(options.filter((o) => o.note).map((o) => [o.id, o.note]));
        let added = [];
        splitCats(input.value).forEach((c) => {
            if (!added.includes(c)) {
                added.push(c);
            }
        });

        const listId = input.id + '_available';
        const filter = h('input', {type: 'search', class: 'form-control form-control-sm mb-1',
            placeholder: 'Filter', 'aria-label': 'Filter categories'});
        const left = h('select', {multiple: '', size: '12', class: 'form-select', id: listId,
            'aria-label': 'Categories not added'});
        const right = h('select', {multiple: '', size: '12', class: 'form-select',
            'aria-label': 'Categories added'});
        const leftTitle = h('div', {class: 'cat-picker-title'});
        const rightTitle = h('div', {class: 'cat-picker-title'});

        function button(text, title, onClick) {
            const b = h('button', {type: 'button', class: 'btn btn-outline-secondary btn-sm', title: title,
                'aria-label': title, text: text});
            b.addEventListener('click', onClick);
            return b;
        }

        function label(id) {
            const name = names.get(id);
            if (name === undefined) {
                return id + ' (not defined)';
            }
            const text = name === id ? id : name + ' (' + id + ')';
            return notes.has(id) ? text + ' – ' + notes.get(id) : text;
        }

        function selectedValues(select) {
            return Array.from(select.selectedOptions).map((o) => o.value);
        }

        function render(keepLeft, keepRight) {
            const query = filter.value.trim().toLowerCase();
            const available = options.map((o) => o.id).filter((id) => !added.includes(id) && !notes.has(id));
            left.replaceChildren();
            available.filter((id) => !query || label(id).toLowerCase().includes(query)).forEach((id) => {
                const o = h('option', {value: id, text: label(id)});
                o.selected = keepLeft.includes(id);
                left.appendChild(o);
            });
            right.replaceChildren();
            added.forEach((id) => {
                const o = h('option', {value: id, text: label(id)});
                if (!names.has(id) || notes.has(id)) {
                    o.className = 'text-danger';
                }
                o.selected = keepRight.includes(id);
                right.appendChild(o);
            });
            leftTitle.textContent = 'Not added (' + available.length + ')';
            rightTitle.textContent = 'Added (' + added.length + ')';
            input.value = added.join(',');
        }

        function add(ids) {
            ids.forEach((id) => {
                if (!added.includes(id)) {
                    added.push(id);
                }
            });
            render([], ids);
        }

        function remove(ids) {
            added = added.filter((id) => !ids.includes(id));
            render(ids, []);
        }

        function move(step) {
            const ids = selectedValues(right);
            const order = step < 0 ? added.slice() : added.slice().reverse();
            for (let i = 1; i < order.length; i++) {
                if (ids.includes(order[i]) && !ids.includes(order[i - 1])) {
                    [order[i - 1], order[i]] = [order[i], order[i - 1]];
                }
            }
            added = step < 0 ? order : order.reverse();
            render([], ids);
        }

        const buttons = h('div', {class: 'cat-picker-buttons'}, [
            button('→', 'Add selected categories', () => add(selectedValues(left))),
            button('⇉', 'Add all shown categories', () => add(Array.from(left.options).map((o) => o.value))),
            button('←', 'Remove selected categories', () => remove(selectedValues(right))),
            button('⇇', 'Remove all categories', () => remove(added.slice())),
            button('↑', 'Move selected categories up', () => move(-1)),
            button('↓', 'Move selected categories down', () => move(1)),
        ]);
        left.addEventListener('dblclick', () => add(selectedValues(left)));
        right.addEventListener('dblclick', () => remove(selectedValues(right)));
        filter.addEventListener('input', () => render(selectedValues(left), selectedValues(right)));

        const grid = h('div', {class: 'cat-picker-grid'}, [
            h('div', {class: 'cat-picker-col'}, [leftTitle, filter, left]),
            buttons,
            h('div', {class: 'cat-picker-col'}, [rightTitle, h('div', {class: 'cat-picker-spacer'}), right]),
        ]);
        if (input.disabled) {
            grid.querySelectorAll('select, button, input').forEach((el) => { el.disabled = true; });
        }
        // The posted field is now hidden; the server still checks that it is not empty.
        input.required = false;
        input.hidden = true;
        const help = box.querySelector('.cat-picker-help');
        if (help) {
            help.hidden = true;
        }
        const label_ = document.querySelector('label[for="' + input.id + '"]');
        if (label_) {
            label_.setAttribute('for', listId);
        }
        box.insertBefore(grid, input);
        render([], []);
    }

    function initAll() {
        document.querySelectorAll('.cat-picker').forEach(init);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAll);
    } else {
        initAll();
    }
})();
