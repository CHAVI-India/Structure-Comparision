document.addEventListener('DOMContentLoaded', function () {
    const fileInput = document.getElementById('dicom_files');
    const selectedLabel = document.getElementById('selected_file_name');
    const statusBanner = document.querySelector('.status-banner[data-status-timeout]');
    const importForm = document.getElementById('dicomImportForm');
    const importOverlay = document.getElementById('importLoadingOverlay');
    const submitButton = document.getElementById('dicomImportSubmit');

    if (!fileInput || !selectedLabel) {
        return;
    }

    const resetLabel = () => {
        selectedLabel.textContent = 'No file selected yet.';
        selectedLabel.classList.add('text-slate-400');
        selectedLabel.classList.remove('text-emerald-600', 'text-rose-600');
        if (submitButton) {
            submitButton.disabled = true;
        }
    };

    resetLabel();

    fileInput.addEventListener('change', function () {
        const fileList = this.files || [];
        const firstFile = fileList[0];

        if (!firstFile) {
            resetLabel();
            return;
        }

        const relativePath = firstFile.webkitRelativePath || '';
        const folderName = relativePath.split('/').filter(Boolean)[0];
        const isFolderSelection = fileList.length > 1 || relativePath.includes('/') || (firstFile.name || '').includes('/');

        if (!isFolderSelection) {
            selectedLabel.textContent = 'Please select a folder (not a single .dcm file).';
            selectedLabel.classList.remove('text-slate-400', 'text-emerald-600');
            selectedLabel.classList.add('text-rose-600');
            if (submitButton) {
                submitButton.disabled = true;
            }
            return;
        }

        const labelText = folderName
            ? `Selected folder: ${folderName}`
            : `Selected: ${firstFile.name}`;

        selectedLabel.textContent = labelText;
        selectedLabel.classList.remove('text-slate-400', 'text-rose-600');
        selectedLabel.classList.add('text-emerald-600');
        if (submitButton) {
            submitButton.disabled = false;
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