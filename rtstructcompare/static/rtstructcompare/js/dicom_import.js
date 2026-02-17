document.addEventListener('DOMContentLoaded', function () {
    const fileInput = document.getElementById('dicom_archive');
    const selectedLabel = document.getElementById('selected_file_name');
    const statusBanner = document.querySelector('.status-banner[data-status-timeout]');
    const importForm = document.getElementById('dicomImportForm');
    const importOverlay = document.getElementById('importLoadingOverlay');
    const submitButton = document.getElementById('dicomImportSubmit');

    if (!fileInput || !selectedLabel) {
        return;
    }

    fileInput.addEventListener('change', function () {
        const file = this.files && this.files[0];
        if (file) {
            selectedLabel.textContent = `Selected: ${file.name}`;
            selectedLabel.classList.remove('text-slate-400');
            selectedLabel.classList.add('text-emerald-600');
        } else {
            selectedLabel.textContent = 'No file selected yet.';
            selectedLabel.classList.add('text-slate-400');
            selectedLabel.classList.remove('text-emerald-600');
        }
    });

    if (statusBanner) {
        const timeout = parseInt(statusBanner.dataset.statusTimeout, 10);
        if (timeout > 0) {
            setTimeout(() => {
                if (statusBanner && statusBanner.isConnected) {
                    statusBanner.remove();
                }
            }, timeout);
        }
    }

    if (importForm && importOverlay && submitButton) {
        importForm.addEventListener('submit', function () {
            submitButton.disabled = true;
            importOverlay.classList.add('is-visible');
            importOverlay.setAttribute('aria-hidden', 'false');
        });
    }
});