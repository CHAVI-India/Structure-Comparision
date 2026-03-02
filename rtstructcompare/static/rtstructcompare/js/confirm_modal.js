(function () {
    var modal = document.getElementById('appConfirmModal');
    var titleEl = document.getElementById('appConfirmTitle');
    var messageEl = document.getElementById('appConfirmMessage');
    var cancelBtn = document.getElementById('appConfirmCancel');
    var footerCancelBtn = document.querySelector('.js-app-confirm-cancel');
    var okBtn = document.getElementById('appConfirmOk');

    if (!modal || !titleEl || !messageEl || !cancelBtn || !okBtn) {
        return;
    }

    var onConfirm = null;

    var close = function () {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        modal.setAttribute('aria-hidden', 'true');
        onConfirm = null;
    };

    var open = function (opts) {
        opts = opts || {};
        titleEl.textContent = opts.title || 'Confirm';
        messageEl.textContent = opts.message || 'Are you sure?';
        onConfirm = typeof opts.onConfirm === 'function' ? opts.onConfirm : null;
        okBtn.textContent = opts.confirmText || 'Confirm';

        modal.classList.remove('hidden');
        modal.classList.add('flex');
        modal.setAttribute('aria-hidden', 'false');
    };

    cancelBtn.addEventListener('click', close);
    if (footerCancelBtn) {
        footerCancelBtn.addEventListener('click', close);
    }
    modal.addEventListener('click', function (e) {
        if (e.target === modal) close();
    });
    okBtn.addEventListener('click', function () {
        var fn = onConfirm;
        close();
        if (fn) fn();
    });

    window.AppConfirm = { open: open, close: close };
})();
