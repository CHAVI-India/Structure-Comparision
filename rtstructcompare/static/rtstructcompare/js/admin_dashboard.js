
document.addEventListener('DOMContentLoaded', function () {
    const userSearchInput = document.getElementById('user_search');
    const userSelect = document.getElementById('user_ids');
    const searchInput = document.getElementById('patient_search');
    const patientSelect = document.getElementById('patient_ids');
    const groupUserSearchInput = document.getElementById('group_user_search');
    const groupUserSelect = document.getElementById('group_user_ids');
    const groupTrigger = document.getElementById('groupTrigger');
    const groupDropdown = document.getElementById('groupDropdown');
    const groupToolbar = document.getElementById('groupToolbar');
    const groupIdInput = document.getElementById('group_id');
    const selectedGroupLabel = document.getElementById('selectedGroupLabel');
    const clearGroupSelection = document.getElementById('clearGroupSelection');
    const groupOptions = document.querySelectorAll('[data-group-id]');
    const openGroupModal = document.getElementById('openGroupModal');
    const groupModal = document.getElementById('groupModal');
    const closeGroupModal = document.getElementById('closeGroupModal');
    const cancelGroupModal = document.getElementById('cancelGroupModal');

    const attachFilter = (input, select) => {
        if (!input || !select) {
            return;
        }
        const options = Array.from(select.options);
        input.addEventListener('input', function () {
            const term = input.value.trim().toLowerCase();
            options.forEach(function (option) {
                if (!option.value) {
                    option.hidden = false;
                    return;
                }
                const matches = option.textContent.toLowerCase().includes(term);
                option.hidden = term ? !matches : false;
            });
        });
    };

    attachFilter(userSearchInput, userSelect);
    attachFilter(searchInput, patientSelect);
    attachFilter(groupUserSearchInput, groupUserSelect);

    if (groupTrigger && groupDropdown) {
        groupTrigger.addEventListener('click', function (event) {
            event.preventDefault();
            event.stopPropagation();
            groupDropdown.classList.toggle('show');
        });
    }

    if (groupOptions.length && groupIdInput && selectedGroupLabel && groupDropdown) {
        groupOptions.forEach(function (option) {
            option.addEventListener('click', function () {
                const groupId = option.dataset.groupId;
                const groupName = option.dataset.groupName || 'Selected group';
                groupIdInput.value = groupId;
                selectedGroupLabel.textContent = groupName;
                groupDropdown.classList.remove('show');
            });
        });
    }

    if (clearGroupSelection && groupIdInput && selectedGroupLabel && groupDropdown) {
        clearGroupSelection.addEventListener('click', function () {
            groupIdInput.value = '';
            selectedGroupLabel.textContent = 'No group';
            groupDropdown.classList.remove('show');
        });
    }

    document.addEventListener('click', function (event) {
        if (groupDropdown && groupDropdown.classList.contains('show')) {
            if (!groupToolbar || !groupToolbar.contains(event.target)) {
                groupDropdown.classList.remove('show');
            }
        }
    });

    const openModal = () => {
        if (groupModal) {
            groupModal.classList.add('show');
        }
    };

    const closeModal = () => {
        if (groupModal) {
            groupModal.classList.remove('show');
        }
    };

    if (openGroupModal) {
        openGroupModal.addEventListener('click', openModal);
    }
    if (closeGroupModal) {
        closeGroupModal.addEventListener('click', closeModal);
    }
    if (cancelGroupModal) {
        cancelGroupModal.addEventListener('click', closeModal);
    }
    if (groupModal) {
        groupModal.addEventListener('click', function (event) {
            if (event.target === groupModal) {
                closeModal();
            }
        });
    }

    const statusMessage = document.querySelector('.status');
    if (statusMessage) {
        const closeStatus = statusMessage.querySelector('.status-close');
        const dismissStatus = () => {
            if (statusMessage && statusMessage.isConnected) {
                statusMessage.remove();
            }
        };
        if (closeStatus) {
            closeStatus.addEventListener('click', dismissStatus);
        }
        setTimeout(dismissStatus, 10000);
    }
});
