/*
 * Table editor for textareas with class 'table-editor'.
 * Tables are stored in the text as markdown pipe tables:
 *   | Header 1 | Header 2 |
 *   | --- | --- |
 *   | Cell 1 | Cell 2 |
 */
(function () {
    'use strict';

    var MAX_PICK_ROWS = 8;
    var MAX_PICK_COLS = 10;
    var ROW_RE = /^[ \t]*\|.*\|[ \t]*$/;
    var SEP_RE = /^[ \t]*\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*$/;
    var IMPORT_ACCEPT = '.csv,text/csv';
    var CSV_SEPARATORS = ['|', ';', ',', '\t'];     // '|' is the application's csv_sep
    var MAX_IMPORT_BYTES = 2.5 * 1024 * 1024;
    var MAX_IMPORT_ROWS = 500;
    var MAX_IMPORT_COLS = 30;

    var modal = null;       // bootstrap.Modal instance
    var modalEl = null;
    var state = {textarea: null, range: null, caret: null, pending: null, rows: [], focus: {r: 0, c: 0}};

    // ------------------------------------------------------------------
    // Markdown <-> rows conversion
    function splitCells(line) {
        var inner = line.trim().slice(1, -1);
        return inner.split(/(?<!\\)\|/).map(function (c) {
            return c.trim().replace(/\\\|/g, '|');
        });
    }

    function escapeCell(c) {
        return c.replace(/\r?\n/g, ' ').replace(/(?<!\\)\|/g, '\\|').trim();
    }

    function rowsToMarkdown(rows) {
        var n = rows[0].length;
        var lines = [];
        lines.push('| ' + rows[0].map(escapeCell).join(' | ') + ' |');
        lines.push('|' + new Array(n + 1).join(' --- |'));
        for (var r = 1; r < rows.length; r++) {
            lines.push('| ' + rows[r].map(escapeCell).join(' | ') + ' |');
        }
        return lines.join('\n');
    }

    function emptyRows(nRows, nCols) {
        var rows = [];
        for (var r = 0; r < nRows; r++) {
            var row = [];
            for (var c = 0; c < nCols; c++) {
                row.push(r === 0 ? 'Header ' + (c + 1) : '');
            }
            rows.push(row);
        }
        return rows;
    }

    // Return {start, end, rows} of the table containing the caret, or null
    function findTableAtCaret(textarea) {
        var text = textarea.value;
        var caret = textarea.selectionStart;
        var lines = text.split('\n');
        var offsets = [];
        var pos = 0;
        var idx = -1;
        for (var i = 0; i < lines.length; i++) {
            offsets.push(pos);
            if (idx < 0 && caret <= pos + lines[i].length) {
                idx = i;
            }
            pos += lines[i].length + 1;
        }
        if (idx < 0 || !ROW_RE.test(lines[idx])) {
            return null;
        }
        var first = idx;
        var last = idx;
        while (first > 0 && ROW_RE.test(lines[first - 1])) { first--; }
        while (last < lines.length - 1 && ROW_RE.test(lines[last + 1])) { last++; }
        // A block may contain several tables; locate the one holding the caret
        var starts = [];
        for (var j = first; j < last; j++) {
            if (SEP_RE.test(lines[j + 1]) && !SEP_RE.test(lines[j])) {
                starts.push(j);
            }
        }
        var tStart = -1;
        for (var k = 0; k < starts.length; k++) {
            if (starts[k] <= idx) { tStart = starts[k]; }
        }
        if (tStart < 0) {
            return null;
        }
        var tEnd = last;
        for (var m = 0; m < starts.length; m++) {
            if (starts[m] > tStart) { tEnd = starts[m] - 1; break; }
        }
        if (idx > tEnd) {
            return null;
        }
        var rows = [];
        for (var l = tStart; l <= tEnd; l++) {
            if (l !== tStart + 1) {
                rows.push(splitCells(lines[l]));
            }
        }
        var nCols = Math.max.apply(null, rows.map(function (r) { return r.length; }));
        rows = rows.map(function (r) {
            while (r.length < nCols) { r.push(''); }
            return r;
        });
        return {
            start: offsets[tStart],
            end: offsets[tEnd] + lines[tEnd].length,
            rows: rows
        };
    }

    // ------------------------------------------------------------------
    // Text manipulation
    function replaceRange(textarea, start, end, insert) {
        textarea.focus();
        textarea.setSelectionRange(start, end);
        // execCommand keeps the browser undo history (Ctrl+Z) working
        if (!document.execCommand || !document.execCommand('insertText', false, insert)) {
            textarea.setRangeText(insert, start, end, 'end');
        }
        textarea.dispatchEvent(new Event('input', {bubbles: true}));
        autoResize(textarea);
    }

    function insertTable(textarea, md) {
        var text = textarea.value;
        var start = textarea.selectionStart;
        var end = textarea.selectionEnd;
        var before = text.slice(0, start);
        var after = text.slice(end);
        var prefix = (before.length > 0 && !/\n$/.test(before)) ? '\n' : '';
        var suffix = (after.length > 0 && !/^\r?\n/.test(after)) ? '\n' : '';
        replaceRange(textarea, start, end, prefix + md + suffix);
    }

    function removeTable(textarea, range) {
        var text = textarea.value;
        var start = range.start;
        var end = range.end;
        // Also remove the line break following (or preceding) the table
        if (text.charAt(end) === '\n') {
            end++;
        } else if (start > 0 && text.charAt(start - 1) === '\n') {
            start--;
        }
        replaceRange(textarea, start, end, '');
    }

    function autoResize(textarea) {
        var lines = textarea.value.split('\n').length;
        if (lines > textarea.rows) {
            textarea.rows = Math.min(lines, 25);
        }
    }

    // ------------------------------------------------------------------
    // Import from CSV files
    function detectSeparator(text) {
        var line = text.split(/\r?\n/, 1)[0].replace(/"[^"]*"/g, '');
        var best = CSV_SEPARATORS[0];
        var bestCount = 0;
        CSV_SEPARATORS.forEach(function (sep) {
            var count = line.split(sep).length - 1;
            if (count > bestCount) { best = sep; bestCount = count; }
        });
        return best;
    }

    function parseCsv(text, sep) {
        var rows = [];
        var row = [];
        var field = '';
        var quoted = false;
        for (var i = 0; i < text.length; i++) {
            var ch = text.charAt(i);
            if (quoted) {
                if (ch === '"' && text.charAt(i + 1) === '"') { field += '"'; i++; }
                else if (ch === '"') { quoted = false; }
                else { field += ch; }
            } else if (ch === '"' && field === '') {
                quoted = true;
            } else if (ch === sep) {
                row.push(field); field = '';
            } else if (ch === '\n' || ch === '\r') {
                if (ch === '\r' && text.charAt(i + 1) === '\n') { i++; }
                row.push(field); field = '';
                rows.push(row); row = [];
            } else {
                field += ch;
            }
        }
        if (field !== '' || row.length > 0) { row.push(field); rows.push(row); }
        return rows.filter(function (r) { return r.some(function (c) { return c.trim() !== ''; }); });
    }

    async function importFile(file) {
        try {
            if (file.size > MAX_IMPORT_BYTES) {
                throw new Error('file is too big (max 2.5 MB)');
            }
            if (!/\.csv$/i.test(file.name)) {
                throw new Error('unsupported file type, use .csv');
            }
            var info = file.name;
            var text = await file.text();
            text = text.replace(/^\uFEFF/, '');
            var rows = parseCsv(text, detectSeparator(text));
            if (rows.length === 0) { throw new Error('the file contains no data'); }
            var truncated = rows.length > MAX_IMPORT_ROWS;
            rows = rows.slice(0, MAX_IMPORT_ROWS);
            var nCols = Math.max.apply(null, rows.map(function (r) { return r.length; }));
            truncated = truncated || nCols > MAX_IMPORT_COLS;
            nCols = Math.min(nCols, MAX_IMPORT_COLS);
            rows = rows.map(function (r) {
                r = r.slice(0, nCols).map(function (c) { return c.trim(); });
                while (r.length < nCols) { r.push(''); }
                return r;
            });
            if (rows.length < 2) { rows.push(new Array(nCols).fill('')); }
            state.rows = rows;
            state.focus = {r: 0, c: 0};
            renderGrid();
            showMessage('success', 'Imported ' + info + ': ' + rows.length + ' rows x ' + nCols + ' columns' +
                        (truncated ? ' (truncated to ' + MAX_IMPORT_ROWS + ' rows / ' + MAX_IMPORT_COLS + ' columns)' : '') +
                        '. Review the table and press ' + (state.range ? 'Update' : 'Insert') + '.');
        } catch (err) {
            showMessage('danger', 'Unable to import ' + file.name + ': ' + err.message);
        }
    }

    function showMessage(kind, text) {
        var msg = modalEl.querySelector('.te-msg');
        msg.className = 'alert py-1 px-2 small te-msg' + (kind ? ' alert-' + kind : ' d-none');
        msg.textContent = text;
    }

    // ------------------------------------------------------------------
    // Modal
    function el(tag, attrs, children) {
        var e = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === 'text') { e.textContent = attrs[k]; } else { e.setAttribute(k, attrs[k]); }
        });
        (children || []).forEach(function (c) { e.appendChild(c); });
        return e;
    }

    function iconButton(action, icon, label, cls) {
        var b = el('button', {
            'type': 'button',
            'class': 'btn btn-sm ' + (cls || 'btn-outline-secondary'),
            'data-action': action,
            'title': label
        });
        b.appendChild(el('i', {'class': 'bi ' + icon}));
        b.appendChild(document.createTextNode(' ' + label));
        return b;
    }

    function buildModal() {
        modalEl = el('div', {'class': 'modal fade', 'id': 'tableEditorModal', 'tabindex': '-1',
                             'aria-labelledby': 'tableEditorTitle', 'aria-hidden': 'true'});
        modalEl.innerHTML =
            '<div class="modal-dialog modal-xl modal-dialog-scrollable">' +
            ' <div class="modal-content">' +
            '  <div class="modal-header">' +
            '   <h5 class="modal-title" id="tableEditorTitle">Table</h5>' +
            '   <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>' +
            '  </div>' +
            '  <div class="modal-body">' +
            '   <div class="te-size mb-3">' +
            '    <label class="form-label">Table size</label>' +
            '    <div class="d-flex flex-wrap align-items-start gap-4">' +
            '     <div><div class="te-picker"></div><div class="form-text te-picker-label">1 x 1</div></div>' +
            '     <div class="d-flex align-items-end gap-2">' +
            '      <div><label class="form-label small mb-0" for="teRows">Rows</label>' +
            '       <input type="number" id="teRows" class="form-control form-control-sm te-rows" min="2" max="100" value="3" style="width:6rem"></div>' +
            '      <div><label class="form-label small mb-0" for="teCols">Columns</label>' +
            '       <input type="number" id="teCols" class="form-control form-control-sm te-cols" min="1" max="30" value="3" style="width:6rem"></div>' +
            '      <button type="button" class="btn btn-sm btn-outline-primary" data-action="resize">Apply size</button>' +
            '     </div>' +
            '    </div>' +
            '   </div>' +
            '   <div class="te-toolbar btn-toolbar gap-2 mb-2" role="toolbar"></div>' +
            '   <input type="file" class="d-none te-file" accept="' + IMPORT_ACCEPT + '">' +
            '   <div class="alert py-1 px-2 small d-none te-msg" role="status"></div>' +
            '   <div class="te-grid-wrap"><table class="table table-bordered table-sm te-grid mb-1"></table></div>' +
            '   <div class="form-text">The first row is the header row. Cells may contain markdown tags and ' +
            '    references (#cat:domain:name). Line breaks inside cells are not supported.</div>' +
            '  </div>' +
            '  <div class="modal-footer">' +
            '   <button type="button" class="btn btn-outline-danger me-auto" data-action="delete">' +
            '    <i class="bi bi-trash"></i> Delete table</button>' +
            '   <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>' +
            '   <button type="button" class="btn btn-primary" data-action="save">Insert</button>' +
            '  </div>' +
            ' </div>' +
            '</div>';

        var toolbar = modalEl.querySelector('.te-toolbar');
        var g1 = el('div', {'class': 'btn-group', 'role': 'group'}, [
            iconButton('row-above', 'bi-arrow-bar-up', 'Row above'),
            iconButton('row-below', 'bi-arrow-bar-down', 'Row below'),
            iconButton('row-delete', 'bi-x-lg', 'Delete row', 'btn-outline-danger')
        ]);
        var g2 = el('div', {'class': 'btn-group', 'role': 'group'}, [
            iconButton('col-left', 'bi-arrow-bar-left', 'Column left'),
            iconButton('col-right', 'bi-arrow-bar-right', 'Column right'),
            iconButton('col-delete', 'bi-x-lg', 'Delete column', 'btn-outline-danger')
        ]);
        toolbar.appendChild(g1);
        toolbar.appendChild(g2);
        toolbar.appendChild(el('div', {'class': 'btn-group', 'role': 'group'}, [
            iconButton('import', 'bi-upload', 'Import CSV')
        ]));
        modalEl.querySelector('.te-file').addEventListener('change', function (e) {
            var file = e.target.files[0];
            e.target.value = '';
            if (file) { importFile(file); }
        });

        buildPicker();
        modalEl.addEventListener('click', onModalClick);
        modalEl.querySelector('.te-grid').addEventListener('focusin', onCellFocus);
        modalEl.querySelector('.te-grid').addEventListener('input', onCellInput);
        modalEl.querySelector('.te-grid').addEventListener('keydown', onCellKeydown);
        modalEl.addEventListener('shown.bs.modal', function () { focusCell(state.focus.r, state.focus.c); });
        // The modal traps the focus: the textarea is only modified once the modal is hidden
        modalEl.addEventListener('hidden.bs.modal', function () {
            var action = state.pending;
            state.pending = null;
            if (action) {
                action();
            } else {
                state.textarea.focus();
                state.textarea.setSelectionRange(state.caret.start, state.caret.end);
            }
        });
        document.body.appendChild(modalEl);
        modal = new bootstrap.Modal(modalEl);
    }

    function buildPicker() {
        var picker = modalEl.querySelector('.te-picker');
        for (var r = 0; r < MAX_PICK_ROWS; r++) {
            for (var c = 0; c < MAX_PICK_COLS; c++) {
                picker.appendChild(el('div', {'class': 'te-pick-cell', 'data-r': r + 1, 'data-c': c + 1}));
            }
        }
        picker.addEventListener('mouseover', function (e) {
            var t = e.target;
            if (t.classList.contains('te-pick-cell')) { highlightPicker(+t.dataset.r, +t.dataset.c); }
        });
        picker.addEventListener('mouseleave', function () {
            highlightPicker(state.rows.length, state.rows[0].length);
        });
        picker.addEventListener('click', function (e) {
            var t = e.target;
            if (t.classList.contains('te-pick-cell')) {
                resizeRows(Math.max(+t.dataset.r, 2), +t.dataset.c);
            }
        });
    }

    function highlightPicker(nRows, nCols) {
        modalEl.querySelectorAll('.te-pick-cell').forEach(function (cell) {
            cell.classList.toggle('active', +cell.dataset.r <= nRows && +cell.dataset.c <= nCols);
        });
        modalEl.querySelector('.te-picker-label').textContent = nRows + ' x ' + nCols;
    }

    function renderGrid() {
        var grid = modalEl.querySelector('.te-grid');
        grid.innerHTML = '';
        var thead = el('thead');
        var tbody = el('tbody');
        state.rows.forEach(function (row, r) {
            var tr = el('tr');
            row.forEach(function (val, c) {
                var input = el('input', {
                    'type': 'text',
                    'class': 'form-control form-control-sm border-0 te-cell' + (r === 0 ? ' fw-bold' : ''),
                    'data-r': r, 'data-c': c,
                    'aria-label': (r === 0 ? 'Header ' : 'Row ' + r + ' ') + 'column ' + (c + 1)
                });
                input.value = val;
                tr.appendChild(el(r === 0 ? 'th' : 'td', {'class': 'p-0'}, [input]));
            });
            (r === 0 ? thead : tbody).appendChild(tr);
        });
        grid.appendChild(thead);
        grid.appendChild(tbody);
        // Same '#cat:domain:name' suggestions as the text fields (see link_suggest.html)
        if (window.jQuery && jQuery.fn.suggest && window.linkSuggestOptions) {
            jQuery(grid).find('.te-cell').suggest('#', window.linkSuggestOptions)
                .on('suggest.select', syncFromGrid);
        }
        modalEl.querySelector('.te-rows').value = state.rows.length;
        modalEl.querySelector('.te-cols').value = state.rows[0].length;
        highlightPicker(state.rows.length, state.rows[0].length);
        var nRows = state.rows.length;
        var nCols = state.rows[0].length;
        modalEl.querySelector('[data-action="row-delete"]').disabled = nRows <= 2 || state.focus.r === 0;
        modalEl.querySelector('[data-action="row-above"]').disabled = state.focus.r === 0;
        modalEl.querySelector('[data-action="col-delete"]').disabled = nCols <= 1;
    }

    function focusCell(r, c) {
        r = Math.max(0, Math.min(r, state.rows.length - 1));
        c = Math.max(0, Math.min(c, state.rows[0].length - 1));
        var input = modalEl.querySelector('.te-cell[data-r="' + r + '"][data-c="' + c + '"]');
        if (input) { input.focus(); input.select(); }
    }

    function resizeRows(nRows, nCols) {
        nRows = Math.max(2, Math.min(nRows, 100));
        nCols = Math.max(1, Math.min(nCols, 30));
        var rows = state.rows.slice(0, nRows).map(function (row) { return row.slice(0, nCols); });
        rows.forEach(function (row, r) {
            while (row.length < nCols) { row.push(r === 0 ? 'Header ' + (row.length + 1) : ''); }
        });
        while (rows.length < nRows) { rows.push(new Array(nCols).fill('')); }
        state.rows = rows;
        state.focus = {r: Math.min(state.focus.r, nRows - 1), c: Math.min(state.focus.c, nCols - 1)};
        renderGrid();
        focusCell(state.focus.r, state.focus.c);
    }

    function onCellFocus(e) {
        if (e.target.classList.contains('te-cell')) {
            state.focus = {r: +e.target.dataset.r, c: +e.target.dataset.c};
            modalEl.querySelector('[data-action="row-delete"]').disabled =
                state.rows.length <= 2 || state.focus.r === 0;
            modalEl.querySelector('[data-action="row-above"]').disabled = state.focus.r === 0;
        }
    }

    function onCellInput(e) {
        var t = e.target;
        if (t.classList.contains('te-cell')) {
            state.rows[+t.dataset.r][+t.dataset.c] = t.value;
        }
    }

    // The suggest plugin sets the value without firing 'input'
    function syncFromGrid() {
        modalEl.querySelectorAll('.te-grid .te-cell').forEach(function (input) {
            state.rows[+input.dataset.r][+input.dataset.c] = input.value;
        });
    }

    function onCellKeydown(e) {
        var t = e.target;
        if (!t.classList.contains('te-cell')) { return; }
        var suggestions = t.parentNode.querySelector('.suggest .dropdown-menu.show');
        if (e.key === 'Escape' && suggestions) {
            // Close the suggestions, not the modal
            e.stopPropagation();
            suggestions.classList.remove('show');
            return;
        }
        syncFromGrid();
        var r = +t.dataset.r;
        var c = +t.dataset.c;
        if (e.key === 'Enter') {
            e.preventDefault();
            if (r === state.rows.length - 1) {
                state.rows.push(new Array(state.rows[0].length).fill(''));
                renderGrid();
            }
            focusCell(r + 1, c);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            focusCell(r - 1, c);
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            focusCell(r + 1, c);
        }
    }

    function onModalClick(e) {
        var btn = e.target.closest('[data-action]');
        if (!btn || btn.disabled) { return; }
        syncFromGrid();
        var f = state.focus;
        var nCols = state.rows[0].length;
        switch (btn.dataset.action) {
        case 'resize':
            resizeRows(+modalEl.querySelector('.te-rows').value, +modalEl.querySelector('.te-cols').value);
            return;
        case 'row-above':
            state.rows.splice(f.r, 0, new Array(nCols).fill(''));
            break;
        case 'row-below':
            state.rows.splice(f.r + 1, 0, new Array(nCols).fill(''));
            f.r++;
            break;
        case 'row-delete':
            state.rows.splice(f.r, 1);
            break;
        case 'col-left':
            state.rows.forEach(function (row, r) { row.splice(f.c, 0, r === 0 ? 'Header' : ''); });
            break;
        case 'col-right':
            state.rows.forEach(function (row, r) { row.splice(f.c + 1, 0, r === 0 ? 'Header' : ''); });
            f.c++;
            break;
        case 'col-delete':
            state.rows.forEach(function (row) { row.splice(f.c, 1); });
            break;
        case 'import':
            modalEl.querySelector('.te-file').click();
            return;
        case 'save':
            save();
            return;
        case 'delete':
            if (state.range && window.confirm('Delete this table from the text?')) {
                var range = state.range;
                var textarea = state.textarea;
                state.pending = function () { removeTable(textarea, range); };
                modal.hide();
            }
            return;
        default:
            return;
        }
        renderGrid();
        focusCell(f.r, f.c);
    }

    function save() {
        var md = rowsToMarkdown(state.rows);
        var textarea = state.textarea;
        var range = state.range;
        var caret = state.caret;
        state.pending = function () {
            if (range) {
                replaceRange(textarea, range.start, range.end, md);
            } else {
                textarea.focus();
                textarea.setSelectionRange(caret.start, caret.end);
                insertTable(textarea, md);
            }
        };
        modal.hide();
    }

    function openEditor(textarea) {
        if (!modal) { buildModal(); }
        var range = findTableAtCaret(textarea);
        state.textarea = textarea;
        state.range = range;
        state.caret = {start: textarea.selectionStart, end: textarea.selectionEnd};
        state.pending = null;
        state.rows = range ? range.rows : emptyRows(3, 3);
        state.focus = {r: 0, c: 0};
        modalEl.querySelector('.modal-title').textContent = range ? 'Edit table' : 'Insert table';
        modalEl.querySelector('[data-action="save"]').textContent = range ? 'Update' : 'Insert';
        modalEl.querySelector('[data-action="delete"]').classList.toggle('d-none', !range);
        showMessage('', '');
        renderGrid();
        modal.show();
    }

    // ------------------------------------------------------------------
    // Toolbar above each textarea
    function attach(textarea) {
        if (textarea.disabled || textarea.readOnly) { return; }
        var bar = el('div', {'class': 'btn-group btn-group-sm mb-1 te-bar', 'role': 'group',
                             'aria-label': 'Table tools'});
        var btnTable = iconButton('open', 'bi-table', 'Insert table', 'btn-outline-secondary');
        var btnImport = iconButton('import', 'bi-upload', 'Import table', 'btn-outline-secondary');
        btnImport.title = 'Import a table from a CSV file';
        var btnRemove = iconButton('remove', 'bi-trash', 'Remove table', 'btn-outline-danger');
        btnRemove.disabled = true;
        bar.appendChild(btnTable);
        bar.appendChild(btnImport);
        bar.appendChild(btnRemove);
        textarea.parentNode.insertBefore(bar, textarea);

        function refresh() {
            var inTable = findTableAtCaret(textarea) !== null;
            btnTable.lastChild.textContent = inTable ? ' Edit table' : ' Insert table';
            btnRemove.disabled = !inTable;
        }
        ['click', 'keyup', 'input', 'focus', 'select'].forEach(function (ev) {
            textarea.addEventListener(ev, refresh);
        });
        // Keep the caret position when the buttons take the focus
        bar.addEventListener('mousedown', function (e) { e.preventDefault(); });
        btnTable.addEventListener('click', function () { openEditor(textarea); });
        btnImport.addEventListener('click', function () {
            openEditor(textarea);
            modalEl.querySelector('.te-file').click();
        });
        btnRemove.addEventListener('click', function () {
            var range = findTableAtCaret(textarea);
            if (range && window.confirm('Delete this table from the text?')) {
                removeTable(textarea, range);
                refresh();
            }
        });
        autoResize(textarea);
        refresh();
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('textarea.table-editor').forEach(attach);
    });
})();
