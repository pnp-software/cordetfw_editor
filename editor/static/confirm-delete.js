document.addEventListener('DOMContentLoaded', function () {
    const modalElement = document.getElementById('deleteConfirmModal');
    const messageElement = document.getElementById('deleteConfirmMessage');
    const submitButton = document.getElementById('deleteConfirmSubmit');
    const cancelButton = modalElement.querySelector('.modal-footer [data-bs-dismiss="modal"]');
    const modal = new bootstrap.Modal(modalElement);
    let pendingForm = null;

    document.addEventListener('submit', function (event) {
        const form = event.target;
        if (!form.matches('form[data-confirm-message]')) {
            return;
        }
        if (form.dataset.confirmed === 'true') {
            delete form.dataset.confirmed;
            return;
        }

        event.preventDefault();
        pendingForm = form;
        messageElement.textContent = form.dataset.confirmMessage;
        modal.show();
    });

    submitButton.addEventListener('click', function () {
        if (!pendingForm) {
            return;
        }

        const form = pendingForm;
        pendingForm = null;
        form.dataset.confirmed = 'true';
        modal.hide();
        form.requestSubmit();
    });

    modalElement.addEventListener('shown.bs.modal', function () {
        cancelButton.focus();
    });

    modalElement.addEventListener('hidden.bs.modal', function () {
        pendingForm = null;
    });
});