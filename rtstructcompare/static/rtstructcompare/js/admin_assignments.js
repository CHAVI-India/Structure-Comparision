document.addEventListener('DOMContentLoaded', function () {
    const userSearchInput = document.getElementById('user_search');
    const searchInput = document.getElementById('patient_search');
    const bulkGroupSearchInput = document.getElementById('bulk_group_search');
    const bulkPatientSearchInput = document.getElementById('bulk_patient_search');
    const groupUserSearchInput = document.getElementById('group_user_search');
    const groupUserSelect = document.getElementById('group_user_ids');
    const groupModal = document.getElementById('groupModal');
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
    const unassignPatientUserButtons = document.querySelectorAll('.unassign-patient-user-btn');

    const deactivateUserButtons = document.querySelectorAll('.deactivate-user-btn');
    const deactivateUserForm = document.getElementById('deactivateUserForm');
    const deactivateUserIdInput = document.getElementById('deactivate_user_id');

    const inlineUnassignUserForm = document.getElementById('inlineUnassignUserForm');
    const inlineUnassignUserPatientInput = document.getElementById('inline_unassign_user_patient_id');

    const selectAssignedPatientsUserBtn = document.getElementById('selectAssignedPatientsUser');
    const selectAssignedPatientsGroupBtn = document.getElementById('selectAssignedPatientsGroup');

    const bulkAssignGroupBtn = document.getElementById('bulkAssignGroupBtn');
    const bulkUnassignGroupBtn = document.getElementById('bulkUnassignGroupBtn');

    const bulkGroupAssignmentForm = document.getElementById('bulkGroupAssignmentForm');
    const bulkGroupActionInput = bulkGroupAssignmentForm ? bulkGroupAssignmentForm.querySelector('input[name="action"]') : null;

    const assignmentUnassignButtons = document.querySelectorAll('.assignment-unassign-btn');

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

    const attachCardFilter = (input, itemsSelector) => {
        if (!input) return;
        input.addEventListener('input', function () {
            const term = input.value.trim().toLowerCase();
            document.querySelectorAll(itemsSelector).forEach((card) => {
                const label = (card.dataset.label || '').toLowerCase();
                const matches = label.includes(term);
                if (term) {
                    card.style.display = matches ? '' : 'none';
                    card.hidden = !matches;
                } else {
                    card.style.display = '';
                    card.hidden = false;
                }
            });
        });
    };

    const submitInlineUnassignPatientOnly = (patientId) => {
        if (!inlineUnassignForm || !inlineUnassignPatientInput || !inlineUnassignGroupInput) {
            return;
        }
        if (!patientId) {
            return;
        }
        submitInlineUnassign({ patientId });
    };

    const submitInlineUnassign = ({ patientId, groupId, patientLabel }) => {
        if (!inlineUnassignForm || !inlineUnassignPatientInput) {
            return;
        }
        const ok = window.confirm(
            `Unassign all reviewers for patient ${patientLabel || ''}?`
        );
        if (!ok) {
            return;
        }
        inlineUnassignPatientInput.value = patientId;
        if (inlineUnassignGroupInput) {
            inlineUnassignGroupInput.value = groupId || '';
        }
        inlineUnassignForm.submit();
    };

    attachCardFilter(userSearchInput, '#userList .user-card, #userList [data-user-id]');
    attachCardFilter(searchInput, '#patientList .patient-card');
    attachCardFilter(bulkGroupSearchInput, '#bulkGroupList .group-card');
    attachCardFilter(bulkPatientSearchInput, '#bulkPatientList .patient-card');
    attachFilter(groupUserSearchInput, groupUserSelect);

    if (unassignPatientButtons && unassignPatientButtons.length) {
        unassignPatientButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const patientId = btn.dataset.patientId || (btn.closest('.patient-card') ? btn.closest('.patient-card').dataset.patientId : null);
                const patientLabel = btn.closest('.patient-card')
                    ? (btn.closest('.patient-card').querySelector('.group-bulk-name') || {}).textContent
                    : '';

                if (!patientId) {
                    // eslint-disable-next-line no-console
                    console.warn('Unassign click: missing patientId');
                    return;
                }

                const { groupId, error } = resolveInlineGroupContext();
                if (error === 'multiple') {
                    window.alert('Select only one group before unassigning a patient.');
                    return;
                }
                if (!groupId) {
                    window.alert('Select a group before unassigning a patient.');
                    return;
                }

                if (!inlineUnassignForm || !inlineUnassignPatientInput || !inlineUnassignGroupInput) {
                    // eslint-disable-next-line no-console
                    console.warn('Unassign click: inline unassign form elements missing');
                    return;
                }

                const doSubmit = () => {
                    inlineUnassignPatientInput.value = patientId;
                    inlineUnassignGroupInput.value = groupId;
                    inlineUnassignForm.submit();
                };

                if (window.AppConfirm && typeof window.AppConfirm.open === 'function') {
                    window.AppConfirm.open({
                        title: 'Unassign patient',
                        message: `Unassign ${patientLabel || 'this patient'} from the selected group?`,
                        confirmText: 'Unassign',
                        onConfirm: doSubmit,
                    });
                    return;
                }

                if (window.confirm(`Unassign ${patientLabel || 'this patient'} from the selected group?`)) {
                    doSubmit();
                }
            });
        });
    }

    if (assignmentUnassignButtons && assignmentUnassignButtons.length) {
        assignmentUnassignButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                const patientId = btn.dataset.patientId;
                const groupId = btn.dataset.groupId;
                const patientLabel = btn.dataset.patientLabel;
                if (!patientId) {
                    return;
                }
                if (window.AppConfirm && typeof window.AppConfirm.open === 'function') {
                    window.AppConfirm.open({
                        title: 'Unassign patient',
                        message: `Unassign all reviewers for patient ${patientLabel || ''}?`,
                        confirmText: 'Unassign',
                        onConfirm: function () {
                            inlineUnassignPatientInput.value = patientId;
                            if (inlineUnassignGroupInput) {
                                inlineUnassignGroupInput.value = groupId || '';
                            }
                            inlineUnassignForm.submit();
                        },
                    });
                    return;
                }

                submitInlineUnassign({ patientId, groupId, patientLabel });
            });
        });
    }

    if (bulkAssignGroupBtn && bulkGroupAssignmentForm) {
        bulkAssignGroupBtn.addEventListener('click', () => {
            const selectedBulkPatients = Array.from(document.querySelectorAll('input[name="bulk_patient_ids"]:checked'));
            if (!selectedBulkPatients.length) {
                return;
            }
            if (bulkGroupActionInput) {
                bulkGroupActionInput.value = 'assign_groups';
            }
            bulkGroupAssignmentForm.submit();
        });
    }

    if (assignActionBtn) {
        assignActionBtn.addEventListener('click', () => {
            const selectedUserIdsNow = getSelectedUserIds();
            if (!selectedUserIdsNow.length) {
                window.alert('Select at least one user.');
                return;
            }
            const selectedPatients = Array.from(document.querySelectorAll('input[name="patient_ids"]:checked'));
            if (!selectedPatients.length) {
                window.alert('Select at least one patient.');
                return;
            }
            const actionInput = document.getElementById('action');
            const form = document.getElementById('assignmentForm');
            if (actionInput) {
                actionInput.value = 'assign';
            }
            if (form) {
                form.submit();
            }
        });
    }

    if (unassignActionBtn) {
        unassignActionBtn.addEventListener('click', () => {
            const selectedUserIdsNow = getSelectedUserIds();
            if (!selectedUserIdsNow.length) {
                window.alert('Select at least one user.');
                return;
            }
            const selectedPatients = Array.from(document.querySelectorAll('input[name="patient_ids"]:checked'));
            if (!selectedPatients.length) {
                window.alert('Select at least one patient.');
                return;
            }
            const doSubmit = () => {
                const actionInput = document.getElementById('action');
                const form = document.getElementById('assignmentForm');
                if (actionInput) {
                    actionInput.value = 'unassign';
                }
                if (form) {
                    form.submit();
                }
            };

            if (window.AppConfirm && typeof window.AppConfirm.open === 'function') {
                window.AppConfirm.open({
                    title: 'Unassign patients',
                    message: 'Unassign selected patients from the selected user(s)?',
                    confirmText: 'Unassign',
                    onConfirm: doSubmit,
                });
                return;
            }

            if (window.confirm('Unassign selected patients from the selected user(s)?')) {
                doSubmit();
            }
        });
    }

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
            Array.from(groupUserSelectModal.options).forEach((option) => {
                option.selected = false;
            });
        }
    };

    const openModalForCreate = () => {
        resetGroupModal();
        showGroupModal();
    };

    [openGroupModalSecondary, openGroupModalEmpty].forEach((btn) => {
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

            const submitDelete = () => {
                deleteGroupIdInput.value = groupId;
                deleteGroupForm.submit();
            };

            if (!(window.AppConfirm && typeof window.AppConfirm.open === 'function')) {
                return;
            }

            window.AppConfirm.open({
                title: 'Delete group',
                message: `Delete "${groupName}"? This will remove all assignments for this group.`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                onConfirm: submitDelete,
            });
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
    const getSelectedUserIds = () => getCheckedValues('input[name="user_ids"]');

    const resolveInlineUserContext = () => {
        const selectedUserIds = getSelectedUserIds();
        if (selectedUserIds.length < 1) {
            return { error: 'none' };
        }
        return { userIds: selectedUserIds };
    };

    const resolveInlineGroupContext = () => {
        const bulkGroupIds = getSelectedBulkGroupIds();
        if (bulkGroupIds.length > 1) {
            return { error: 'multiple' };
        }
        if (bulkGroupIds.length === 1) {
            return { groupId: bulkGroupIds[0] };
        }
        return { error: 'none' };
    };

    const submitInlineUnassignUsers = (patientId, userIds) => {
        if (!inlineUnassignUserForm || !inlineUnassignUserPatientInput) {
            return;
        }

        inlineUnassignUserPatientInput.value = patientId;

        Array.from(inlineUnassignUserForm.querySelectorAll('input[name="user_ids"]')).forEach((node) => {
            node.remove();
        });
        userIds.forEach((uid) => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'user_ids';
            input.value = uid;
            inlineUnassignUserForm.appendChild(input);
        });

        inlineUnassignUserForm.submit();
    };

    const submitInlineUnassignLegacy = (patientId) => {
        if (!inlineUnassignForm || !inlineUnassignPatientInput || !inlineUnassignGroupInput) {
            return;
        }

        const { groupId, error } = resolveInlineGroupContext();
        if (error === 'multiple') {
            window.alert('Select only one group before unassigning a patient.');
            return;
        }

        if (!groupId) {
            window.alert('Select a group before unassigning a patient.');
            return;
        }

        inlineUnassignPatientInput.value = patientId;
        inlineUnassignGroupInput.value = groupId;
        inlineUnassignForm.submit();
    };

    deactivateUserButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const userId = btn.dataset.userId;
            const username = btn.dataset.username || 'this user';
            if (!userId || !deactivateUserForm || !deactivateUserIdInput) return;
            if (!(window.AppConfirm && typeof window.AppConfirm.open === 'function')) return;

            window.AppConfirm.open({
                title: 'Deactivate user',
                message: `Deactivate "${username}"? This will remove all assigned patients for this user.`,
                confirmText: 'Deactivate',
                onConfirm: function () {
                    deactivateUserIdInput.value = userId;
                    deactivateUserForm.submit();
                },
            });
        });
    });

    const updateActionButtons = () => {
        if (!assignActionBtn || !unassignActionBtn) {
            return;
        }

        const selectedUserIds = getSelectedUserIds();
        if (!selectedUserIds.length) {
            assignActionBtn.disabled = true;
            unassignActionBtn.disabled = true;
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
            assignActionBtn.disabled = true;
            unassignActionBtn.disabled = true;
        }
    };

    const updateGroupBulkActionButtons = () => {
        if (!bulkAssignGroupBtn || !bulkUnassignGroupBtn) {
            return;
        }
        const selectedBulkPatients = Array.from(document.querySelectorAll('input[name="bulk_patient_ids"]:checked'));
        if (!selectedBulkPatients.length) {
            bulkAssignGroupBtn.disabled = true;
            bulkUnassignGroupBtn.disabled = true;
            return;
        }

        const assignedStates = selectedBulkPatients.map((checkbox) => {
            const card = checkbox.closest('.patient-card');
            return card ? card.classList.contains('is-assigned') : false;
        });

        const hasAssigned = assignedStates.some(Boolean);
        const hasUnassigned = assignedStates.some((state) => !state);

        if (hasAssigned && hasUnassigned) {
            bulkAssignGroupBtn.disabled = true;
            bulkUnassignGroupBtn.disabled = true;
            return;
        }

        bulkAssignGroupBtn.disabled = hasAssigned;
        bulkUnassignGroupBtn.disabled = hasUnassigned;
    };

    const updateSelectAssignedGroupButtonLabel = () => {
        if (!selectAssignedPatientsGroupBtn) {
            return;
        }

        const patientCheckboxes = Array.from(document.querySelectorAll('input[name="bulk_patient_ids"]'));
        if (!patientCheckboxes.length) {
            selectAssignedPatientsGroupBtn.textContent = 'Select assigned';
            return;
        }

        const assignedCheckboxes = patientCheckboxes.filter((cb) => {
            const card = cb.closest('.patient-card');
            return card ? card.classList.contains('is-assigned') : false;
        });

        if (!assignedCheckboxes.length) {
            selectAssignedPatientsGroupBtn.textContent = 'Select assigned';
            return;
        }

        const allAssignedSelected = assignedCheckboxes.every((cb) => cb.checked);
        selectAssignedPatientsGroupBtn.textContent = allAssignedSelected ? 'Unselect all' : 'Select assigned';
    };

    const clearBulkPatientSelections = () => {
        document.querySelectorAll('input[name="bulk_patient_ids"]').forEach((cb) => {
            cb.checked = false;
        });
        updatePatientIndicators();
        updateGroupBulkActionButtons();
        updateSelectAssignedGroupButtonLabel();
    };

    const updateSelectAssignedUserButtonLabel = () => {
        if (!selectAssignedPatientsUserBtn) {
            return;
        }

        const patientCheckboxes = Array.from(document.querySelectorAll('input[name="patient_ids"]'));
        if (!patientCheckboxes.length) {
            selectAssignedPatientsUserBtn.textContent = 'Select assigned';
            return;
        }

        const assignedCheckboxes = patientCheckboxes.filter((cb) => {
            const card = cb.closest('.patient-card');
            return card ? card.classList.contains('is-assigned') : false;
        });

        if (!assignedCheckboxes.length) {
            selectAssignedPatientsUserBtn.textContent = 'Select assigned';
            return;
        }

        const allAssignedSelected = assignedCheckboxes.every((cb) => cb.checked);
        selectAssignedPatientsUserBtn.textContent = allAssignedSelected ? 'Unselect all' : 'Select assigned';
    };

    const clearUserPatientSelections = () => {
        document.querySelectorAll('input[name="patient_ids"]').forEach((cb) => {
            cb.checked = false;
        });
        updatePatientIndicators();
        updateActionButtons();
        updateSelectAssignedUserButtonLabel();
    };

    const updatePatientIndicators = () => {
        if (!patientCards.length) {
            updateActionButtons();
            updateGroupBulkActionButtons();
            updateSelectAssignedGroupButtonLabel();
            updateSelectAssignedUserButtonLabel();
            return;
        }

        const selectedGroupIds = new Set(getCheckedValues('input[name="bulk_group_ids"]'));

        const selectedUserIds = new Set(getCheckedValues('input[name="user_ids"]'));
        const { groupId: inlineGroupId, error: inlineGroupError } = resolveInlineGroupContext();
        const activeInlineGroupId = inlineGroupError ? null : inlineGroupId;

        patientCards.forEach((card) => {
            const patientId = card.dataset.patientId;
            const assignment = patientAssignmentsData[patientId];
            let isAssigned = false;
            let assignedToInlineGroup = false;

            if (assignment) {
                const groupIds = assignment.group_ids || [];
                const userIds = assignment.user_ids || [];
                if (groupIds.some((gid) => selectedGroupIds.has(gid))) {
                    isAssigned = true;
                }
                if (userIds.some((uid) => selectedUserIds.has(uid))) {
                    isAssigned = true;
                }
                if (activeInlineGroupId && groupIds.includes(activeInlineGroupId)) {
                    assignedToInlineGroup = true;
                }
            }

            card.classList.toggle('is-assigned', Boolean(isAssigned));

            const inlineButton = card.querySelector('.unassign-patient-btn');
            if (inlineButton) {
                inlineButton.hidden = !assignedToInlineGroup;
            }

            const userInlineButton = card.querySelector('.unassign-patient-user-btn');
            if (userInlineButton) {
                const assignedToSelectedUser = assignment ? (assignment.user_ids || []).some((id) => selectedUserIds.has(id)) : false;
                userInlineButton.hidden = !assignedToSelectedUser;
            }
        });

        updateActionButtons();
        updateGroupBulkActionButtons();
        updateSelectAssignedGroupButtonLabel();
        updateSelectAssignedUserButtonLabel();
    };

    document.querySelectorAll('input[name="bulk_group_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', updatePatientIndicators);
    });

    document.querySelectorAll('input[name="bulk_patient_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
            updateGroupBulkActionButtons();
            updateSelectAssignedGroupButtonLabel();
        });
    });

    document.querySelectorAll('input[name="user_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
            updatePatientIndicators();
            updateActionButtons();
            updateSelectAssignedUserButtonLabel();
        });
    });

    document.querySelectorAll('input[name="patient_ids"]').forEach((checkbox) => {
        checkbox.addEventListener('change', () => {
            updateActionButtons();
            updateSelectAssignedUserButtonLabel();
        });
    });

    const selectAssignedPatients = (scope) => {
        const patientCheckboxes = Array.from(document.querySelectorAll('input[name="bulk_patient_ids"], input[name="patient_ids"]'));
        const patientCardsById = {};
        document.querySelectorAll('.patient-card[data-patient-id]').forEach((card) => {
            patientCardsById[card.dataset.patientId] = card;
        });

        let assignedPatientIds = new Set();
        if (scope === 'group') {
            const selectedGroupIds = new Set(getSelectedBulkGroupIds());
            Object.entries(patientAssignmentsData).forEach(([pid, assignment]) => {
                const groupIds = assignment.group_ids || [];
                if (groupIds.some((gid) => selectedGroupIds.has(gid))) {
                    assignedPatientIds.add(pid);
                }
            });
        } else if (scope === 'user') {
            const selectedUserIds = new Set(getSelectedUserIds());
            Object.entries(patientAssignmentsData).forEach(([pid, assignment]) => {
                const userIds = assignment.user_ids || [];
                if (userIds.some((uid) => selectedUserIds.has(uid))) {
                    assignedPatientIds.add(pid);
                }
            });
        }

        patientCheckboxes.forEach((cb) => {
            if (!cb.value) return;
            cb.checked = assignedPatientIds.has(cb.value);
        });
        updateActionButtons();
        updateGroupBulkActionButtons();
    };

    if (selectAssignedPatientsGroupBtn) {
        selectAssignedPatientsGroupBtn.addEventListener('click', () => {
            if (selectAssignedPatientsGroupBtn.textContent.trim().toLowerCase() === 'unselect all') {
                clearBulkPatientSelections();
                return;
            }
            selectAssignedPatients('group');
            updateSelectAssignedGroupButtonLabel();
        });
    }
    if (selectAssignedPatientsUserBtn) {
        selectAssignedPatientsUserBtn.addEventListener('click', () => {
            if (selectAssignedPatientsUserBtn.textContent.trim().toLowerCase() === 'unselect all') {
                clearUserPatientSelections();
                return;
            }
            selectAssignedPatients('user');
            updateSelectAssignedUserButtonLabel();
        });
    }

    if (bulkUnassignGroupBtn && bulkGroupAssignmentForm) {
        bulkUnassignGroupBtn.addEventListener('click', () => {
            const selectedBulkPatients = Array.from(document.querySelectorAll('input[name="bulk_patient_ids"]:checked'));
            if (!selectedBulkPatients.length) {
                return;
            }
            const selectedBulkGroups = getSelectedBulkGroupIds();
            if (!selectedBulkGroups.length) {
                window.alert('Select at least one group before unassigning.');
                return;
            }
            if (selectedBulkGroups.length > 1) {
                window.alert('Select only one group to unassign patients.');
                return;
            }
            if (!(window.AppConfirm && typeof window.AppConfirm.open === 'function')) {
                return;
            }

            window.AppConfirm.open({
                title: 'Unassign patients',
                message: 'Unassign selected patients from the selected group(s)?',
                confirmText: 'Unassign',
                onConfirm: function () {
                    if (bulkGroupActionInput) {
                        bulkGroupActionInput.value = 'unassign_all';
                    }

                    const existingGroupIdInput = bulkGroupAssignmentForm.querySelector('input[name="group_id"]');
                    if (existingGroupIdInput) {
                        existingGroupIdInput.value = selectedBulkGroups[0];
                    } else {
                        const groupIdInput = document.createElement('input');
                        groupIdInput.type = 'hidden';
                        groupIdInput.name = 'group_id';
                        groupIdInput.value = selectedBulkGroups[0];
                        bulkGroupAssignmentForm.appendChild(groupIdInput);
                    }
                    bulkGroupAssignmentForm.submit();
                },
            });
        });
    }

    updatePatientIndicators();
    updateActionButtons();
    updateGroupBulkActionButtons();
    updateSelectAssignedGroupButtonLabel();
    updateSelectAssignedUserButtonLabel();
});
