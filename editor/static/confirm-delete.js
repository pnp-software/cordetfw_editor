document.addEventListener('DOMContentLoaded', function () {
    const modalElement = document.getElementById('deleteConfirmModal');
    const messageElement = document.getElementById('deleteConfirmMessage');
    const submitButton = document.getElementById('deleteConfirmSubmit');
    const cancelButton = modalElement ? modalElement.querySelector('.modal-footer [data-bs-dismiss="modal"]') : null;
    // Bootstrap comes from a CDN: if it failed to load, fall back to the browser's own dialog
    // so that a confirmation is never skipped.
    const modal = (typeof bootstrap !== 'undefined' && modalElement) ? new bootstrap.Modal(modalElement) : null;
    let pendingForm = null;
    let confirmedForm = null;

    // Registered first, so no code below can leave a confirm form without its guard.
    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!form.matches('form[data-confirm-message]')) {
            return;
        }
        if (confirmedForm === form) {
            confirmedForm = null;
            return;
        }

        event.preventDefault();
        if (modal === null) {
            if (window.confirm(form.dataset.confirmMessage)) {
                confirmedForm = form;
                submitForm(form);
            }
            return;
        }
        pendingForm = form;
        messageElement.textContent = form.dataset.confirmMessage;
        modal.show();
    });

    function submitForm(form) {
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
        } else {
            // submit() fires no submit event, so the listener is not re-entered.
            confirmedForm = null;
            HTMLFormElement.prototype.submit.call(form);
        }
    }

    if (modal === null) {
        return;
    }

    submitButton.addEventListener('click', function () {
        if (!pendingForm) {
            return;
        }

        const form = pendingForm;
        pendingForm = null;
        confirmedForm = form;
        modal.hide();
        submitForm(form);
    });

    modalElement.addEventListener('shown.bs.modal', function () {
        if (cancelButton) {
            cancelButton.focus();
        }
    });

    modalElement.addEventListener('hidden.bs.modal', function () {
        pendingForm = null;
    });
});
