/* Category picker for the comma-separated 'cats' field of the project and application forms
 * (editor/forms.py, CatPicker). Two lists: categories not added (left) and added (right, in the stored order),
 * moved with the arrow buttons or by double click. The text input stays the field that is posted: it is
 * hidden and rewritten on every change. Texts are set with textContent only.
 */
document.addEventListener('DOMContentLoaded', function () {
    function h(tag, attrs, children) {
        const el = document.createElement(tag);
        Object.entries(attrs).forEach(function ([key, value]) {
            if (key === 'text') {
                el.textContent = value;
            } else {
                el.setAttribute(key, value);
            }
        });
        (children || []).forEach(function (child) {
            el.appendChild(child);
        });
        return el;
    }

    function splitCats(value) {
        return value.split(',').map(function (cat) { return cat.trim(); }).filter(function (cat) {
            return cat !== '';
        });
    }

    function optionValues(select) {
        const values = [];
        for (let i = 0; i < select.options.length; i++) {
            values.push(select.options[i].value);
        }
        return values;
    }

    function selectedValues(select) {
        const values = [];
        for (let i = 0; i < select.options.length; i++) {
            if (select.options[i].selected) {
                values.push(select.options[i].value);
            }
        }
        return values;
    }

    function init(box) {
        const input = box.querySelector('.cat-picker-input');
        if (!input || box.dataset.ready) {
            return;
        }
        box.dataset.ready = '1';
        let options;
        try {
            options = JSON.parse(box.dataset.options || '[]');
        } catch (error) {
            return;                                   // keep the plain text input
        }
        let added = [];
        splitCats(input.value).forEach(function (cat) {
            if (!added.includes(cat)) {
                added.push(cat);
            }
        });

        function optionOf(id) {
            for (let i = 0; i < options.length; i++) {
                if (options[i].id === id) {
                    return options[i];
                }
            }
            return null;
        }

        // A category with a note (e.g. 'project level') is not offered; if already added it can only be removed
        function noteOf(id) {
            const option = optionOf(id);
            return option !== null && option.note ? option.note : '';
        }

        const listId = input.id + '_available';
        const filter = h('input', {type: 'search', class: 'form-control form-control-sm mb-1',
            placeholder: 'Filter', 'aria-label': 'Filter categories'});
        const left = h('select', {multiple: '', size: '12', class: 'form-select', id: listId,
            'aria-label': 'Categories not added'});
        const right = h('select', {multiple: '', size: '12', class: 'form-select',
            'aria-label': 'Categories added'});
        const leftTitle = h('div', {class: 'fw-bold mb-1'});
        const rightTitle = h('div', {class: 'fw-bold mb-1'});

        function button(text, title, onClick) {
            const b = h('button', {type: 'button', class: 'btn btn-outline-secondary btn-sm fs-5 lh-sm px-3',
                title: title, 'aria-label': title, text: text});
            b.addEventListener('click', onClick);
            return b;
        }

        function label(id) {
            const option = optionOf(id);
            if (option === null) {
                return id + ' (not defined)';
            }
            const text = option.name === id ? id : option.name + ' (' + id + ')';
            return noteOf(id) ? text + ' – ' + noteOf(id) : text;
        }

        function render(keepLeft, keepRight) {
            const query = filter.value.trim().toLowerCase();
            const available = options.map(function (option) { return option.id; }).filter(function (id) {
                return !added.includes(id) && !noteOf(id);
            });
            left.textContent = '';
            available.forEach(function (id) {
                if (query && !label(id).toLowerCase().includes(query)) {
                    return;
                }
                const o = h('option', {value: id, text: label(id)});
                o.selected = keepLeft.includes(id);
                left.appendChild(o);
            });
            right.textContent = '';
            added.forEach(function (id) {
                const o = h('option', {value: id, text: label(id)});
                if (optionOf(id) === null || noteOf(id)) {
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
            ids.forEach(function (id) {
                if (!added.includes(id)) {
                    added.push(id);
                }
            });
            render([], ids);
        }

        function remove(ids) {
            added = added.filter(function (id) { return !ids.includes(id); });
            render(ids, []);
        }

        function move(step) {
            const ids = selectedValues(right);
            const order = step < 0 ? added.slice() : added.slice().reverse();
            for (let i = 1; i < order.length; i++) {
                if (ids.includes(order[i]) && !ids.includes(order[i - 1])) {
                    const id = order[i - 1];
                    order[i - 1] = order[i];
                    order[i] = id;
                }
            }
            added = step < 0 ? order : order.reverse();
            render([], ids);
        }

        const buttons = h('div', {class: 'col-auto d-flex flex-column justify-content-center gap-1'}, [
            button('→', 'Add selected categories', function () { add(selectedValues(left)); }),
            button('⇉', 'Add all shown categories', function () { add(optionValues(left)); }),
            button('←', 'Remove selected categories', function () { remove(selectedValues(right)); }),
            button('⇇', 'Remove all categories', function () { remove(added.slice()); }),
            button('↑', 'Move selected categories up', function () { move(-1); }),
            button('↓', 'Move selected categories down', function () { move(1); })
        ]);
        left.addEventListener('dblclick', function () {
            add(selectedValues(left));
        });
        right.addEventListener('dblclick', function () {
            remove(selectedValues(right));
        });
        filter.addEventListener('input', function () {
            render(selectedValues(left), selectedValues(right));
        });

        // Not added on the left, added on the right. An invisible box as high as the filter puts the list of the
        // added categories at the same height as the other one.
        const grid = h('div', {class: 'row g-2'}, [
            h('div', {class: 'col'}, [leftTitle, filter, left]),
            buttons,
            h('div', {class: 'col'}, [rightTitle, h('div', {class: 'form-control form-control-sm mb-1 invisible'}),
                right])
        ]);
        if (input.disabled) {
            grid.querySelectorAll('select, button, input').forEach(function (el) {
                el.disabled = true;
            });
        }
        // The posted field is now hidden; the server still checks that it is not empty.
        input.required = false;
        input.classList.add('d-none');
        const help = box.querySelector('.cat-picker-help');
        if (help) {
            help.classList.add('d-none');
        }
        const fieldLabel = document.querySelector('label[for="' + input.id + '"]');
        if (fieldLabel) {
            fieldLabel.setAttribute('for', listId);
        }
        box.insertBefore(grid, input);
        render([], []);
    }

    document.querySelectorAll('.cat-picker').forEach(init);
});
