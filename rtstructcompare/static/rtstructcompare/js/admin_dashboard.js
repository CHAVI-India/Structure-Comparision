
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
    const groupModal = document.getElementById('groupModal');
    const openGroupModalPrimary = document.getElementById('openGroupModal');
    const openGroupModalSecondary = document.getElementById('openGroupModalGroup');
    const openGroupModalEmpty = document.getElementById('openGroupModalGroupEmpty');
    const closeGroupModal = document.getElementById('closeGroupModal');
    const cancelGroupModal = document.getElementById('cancelGroupModal');
    const editGroupButtons = document.querySelectorAll('.edit-group');
    const deleteGroupButtons = document.querySelectorAll('.delete-group-btn');
    const deleteGroupForm = document.getElementById('deleteGroupForm');
    const deleteGroupIdInput = document.getElementById('delete_group_id');
    const modalActionInput = document.getElementById('modal_action');
    const modalGroupIdInput = document.getElementById('modal_group_id');
    const modalTitle = document.getElementById('groupModalTitle');
    const groupNameInput = document.getElementById('group_name');
    const groupDescriptionInput = document.getElementById('group_description');
    const modalSubmitBtn = document.getElementById('modal_submit_btn');
    const groupUserSelectModal = document.getElementById('group_user_ids');
    const userBtn = document.getElementById('userBtn');
    const groupBtn = document.getElementById('groupBtn');
    const userAssignment = document.getElementById('userAssignment');
    const groupAssignment = document.getElementById('groupAssignment');
    const assignActionBtn = document.getElementById('assignActionBtn');
    const unassignActionBtn = document.getElementById('unassignActionBtn');
    const inlineUnassignForm = document.getElementById('inlineUnassignForm');
    const inlineUnassignPatientInput = document.getElementById('inline_unassign_patient_id');
    const inlineUnassignGroupInput = document.getElementById('inline_unassign_group_id');
    const unassignPatientButtons = document.querySelectorAll('.unassign-patient-btn');

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
                updatePatientIndicators();
            });
        });
    }

    if (clearGroupSelection && groupIdInput && selectedGroupLabel && groupDropdown) {
        clearGroupSelection.addEventListener('click', function () {
            groupIdInput.value = '';
            selectedGroupLabel.textContent = 'No group';
            groupDropdown.classList.remove('show');
            updatePatientIndicators();
        });
    }

    document.addEventListener('click', function (event) {
        if (groupDropdown && groupDropdown.classList.contains('show')) {
            if (!groupToolbar || !groupToolbar.contains(event.target)) {
                groupDropdown.classList.remove('show');
            }
        }
    });

    const showGroupModal = () => {
        if (!groupModal) return;
        groupModal.classList.add('show');
        groupModal.setAttribute('aria-hidden', 'false');
    };

    const hideGroupModal = () => {
        if (!groupModal) return;
        groupModal.classList.remove('show');
        groupModal.setAttribute('aria-hidden', 'true');
    };

    const resetGroupModal = () => {
        if (!modalActionInput || !modalGroupIdInput || !groupNameInput || !groupDescriptionInput) return;
        modalTitle.textContent = 'Create Assignment Group';
        modalActionInput.value = 'create_group';
        modalGroupIdInput.value = '';
        groupNameInput.value = '';
        groupDescriptionInput.value = '';
        modalSubmitBtn.textContent = 'Create Group';
        if (groupUserSelectModal) {
            Array.from(groupUserSelectModal.options).forEach(option => {
                option.selected = false;
            });
        }
    };

    const openModalForCreate = () => {
        resetGroupModal();
        showGroupModal();
    };

    [openGroupModalPrimary, openGroupModalSecondary, openGroupModalEmpty].forEach((btn) => {
        if (btn) {
            btn.addEventListener('click', openModalForCreate);
        }
    });

    if (closeGroupModal) {
        closeGroupModal.addEventListener('click', hideGroupModal);
    }
    if (cancelGroupModal) {
        cancelGroupModal.addEventListener('click', hideGroupModal);
    }
    if (groupModal) {
        groupModal.addEventListener('click', function (event) {
            if (event.target === groupModal) {
                hideGroupModal();
            }
        });
    }

    editGroupButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const groupId = btn.dataset.groupId;
            const groupName = btn.dataset.groupName;
            const groupDescription = btn.dataset.groupDescription;
            const groupUsers = (btn.dataset.groupUsers || '')
                .split(',')
                .map((id) => id.trim())
                .filter((id) => id.length);

            if (!modalActionInput || !modalGroupIdInput) return;
            modalTitle.textContent = 'Edit Assignment Group';
            modalActionInput.value = 'edit_group';
            modalGroupIdInput.value = groupId;
            groupNameInput.value = groupName || '';
            groupDescriptionInput.value = groupDescription || '';
            modalSubmitBtn.textContent = 'Update Group';

            if (groupUserSelectModal) {
                Array.from(groupUserSelectModal.options).forEach((option) => {
                    option.selected = groupUsers.includes(option.value);
                });
            }

            showGroupModal();
        });
    });

    deleteGroupButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const groupId = btn.dataset.groupId;
            const groupName = btn.dataset.groupName || 'this group';
            if (!groupId || !deleteGroupForm || !deleteGroupIdInput) return;
            const confirmed = window.confirm(`Delete "${groupName}"? This will remove all assignments for this group.`);
            if (!confirmed) return;
            deleteGroupIdInput.value = groupId;
            deleteGroupForm.submit();
        });
    });

    const setAssignmentView = (target) => {
        if (!userAssignment || !groupAssignment || !userBtn || !groupBtn) {
            return;
        }
        const showGroup = target === 'group';
        userAssignment.classList.toggle('is-active', !showGroup);
        groupAssignment.classList.toggle('is-active', showGroup);
        userAssignment.hidden = showGroup;
        groupAssignment.hidden = !showGroup;

        userBtn.classList.toggle('is-active', !showGroup);
        groupBtn.classList.toggle('is-active', showGroup);
        userBtn.setAttribute('aria-selected', (!showGroup).toString());
        groupBtn.setAttribute('aria-selected', showGroup.toString());
    };

    if (userBtn && groupBtn) {
        userBtn.addEventListener('click', () => setAssignmentView('user'));
        groupBtn.addEventListener('click', () => setAssignmentView('group'));
        setAssignmentView('group');
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

    const patientAssignmentsScript = document.getElementById('patient-assignments-data');
    const patientAssignmentsData = patientAssignmentsScript ? JSON.parse(patientAssignmentsScript.textContent || '{}') : {};
    const patientCards = document.querySelectorAll('.patient-card');

    const getCheckedValues = (selector) =>
        Array.from(document.querySelectorAll(selector))
            .filter((input) => input.checked)
            .map((input) => input.value)
            .filter((value) => value !== undefined && value !== null && value !== '');

    const getSelectedBulkGroupIds = () => getCheckedValues('input[name="bulk_group_ids"]');

    const resolveInlineGroupContext = () => {
        const bulkGroupIds = getSelectedBulkGroupIds();
        if (bulkGroupIds.length > 1) {
            return { error: 'multiple' };
        }
        if (bulkGroupIds.length === 1) {
            return { groupId: bulkGroupIds[0] };
        }
        if (groupIdInput && groupIdInput.value) {
            return { groupId: groupIdInput.value };
        }
        return { error: 'none' };
    };

    const submitInlineUnassign = (patientId) => {
        if (!inlineUnassignForm || !inlineUnassignPatientInput || !inlineUnassignGroupInput) {
            return;
        }

        const { groupId, error } = resolveInlineGroupContext();
        if (error === 'multiple') {
            window.alert('Select only one group before unassigning a patient.');
            return;
        }
        if (!groupId) {
            window.alert('Select a group to unassign this patient from.');
            return;
        }

        inlineUnassignPatientInput.value = patientId;
        inlineUnassignGroupInput.value = groupId;
        inlineUnassignForm.submit();
    };

    unassignPatientButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const patientId = btn.dataset.patientId;
            if (!patientId) {
                return;
            }
            submitInlineUnassign(patientId);
        });
    });

    const updateActionButtons = () => {
        if (!assignActionBtn || !unassignActionBtn) {
            return;
        }

        const selectedPatientCheckboxes = Array.from(document.querySelectorAll('input[name="patient_ids"]:checked'));
        if (!selectedPatientCheckboxes.length) {
            assignActionBtn.disabled = true;
            unassignActionBtn.disabled = true;
            return;
        }

        const assignedStates = selectedPatientCheckboxes.map((checkbox) => {
            const card = checkbox.closest('.patient-card');
            return card ? card.classList.contains('is-assigned') : false;
        });

        const hasAssigned = assignedStates.some(Boolean);
        const hasUnassigned = assignedStates.some((state) => !state);

        if (hasAssigned && !hasUnassigned) {
            assignActionBtn.disabled = true;
            unassignActionBtn.disabled = false;
        } else if (!hasAssigned && hasUnassigned) {
            assignActionBtn.disabled = false;
            unassignActionBtn.disabled = true;
        } else {
            assignActionBtn.disabled = false;
            unassignActionBtn.disabled = false;
        }
    };

    const updatePatientIndicators = () => {
        if (!patientCards.length) {
            updateActionButtons();
            return;
        }

        const selectedGroupIds = new Set(getCheckedValues('input[name="bulk_group_ids"]'));
        const dropdownGroupId = groupIdInput && groupIdInput.value ? groupIdInput.value : null;
        if (dropdownGroupId) {
            selectedGroupIds.add(dropdownGroupId);
        }

        const selectedUserIds = new Set(getCheckedValues('input[name="user_ids"]'));
        const { groupId: inlineGroupId, error: inlineGroupError } = resolveInlineGroupContext();
        const activeInlineGroupId = inlineGroupError ? null : inlineGroupId;

        patientCards.forEach((card) => {
            const patientId = card.dataset.patientId;
            const assignment = patientAssignmentsData[patientId];
            let isAssigned = false;
            let assignedToInlineGroup = false;

            if (assignment) {
                const assignmentUserIds = assignment.user_ids || [];
                const assignmentGroupIds = assignment.group_ids || [];

                isAssigned = assignmentUserIds.some((id) => selectedUserIds.has(id)) ||
                    assignmentGroupIds.some((id) => selectedGroupIds.has(id));

                if (activeInlineGroupId) {
                    assignedToInlineGroup = assignmentGroupIds.includes(activeInlineGroupId);
                }
            }

            card.classList.toggle('is-assigned', Boolean(isAssigned));

            const inlineButton = card.querySelector('.unassign-patient-btn');
            if (inlineButton) {
                inlineButton.hidden = !assignedToInlineGroup;
            }
        });

        updateActionButtons();
    };

    document.querySelectorAll('input[name="bulk_group_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', updatePatientIndicators);
    });

    document.querySelectorAll('input[name="user_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', updatePatientIndicators);
    });

    document.querySelectorAll('input[name="patient_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', updateActionButtons);
    });

    if (groupIdInput) {
        groupIdInput.addEventListener('change', updatePatientIndicators);
    }

    updatePatientIndicators();
    updateActionButtons();
});
