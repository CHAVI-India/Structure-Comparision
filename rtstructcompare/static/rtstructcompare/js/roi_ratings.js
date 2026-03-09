(() => {
    const viewerData = window.dicomViewerData || {};

    const patientId = viewerData.patientId || '';
    const rt1Label = viewerData.rt1Label || 'RTSTRUCT 1';
    const rt2Label = viewerData.rt2Label || 'RTSTRUCT 2';
    const rt1SopUid = viewerData.rt1SopUid || '';
    const rt2SopUid = viewerData.rt2SopUid || '';
    const studyUid = viewerData.studyUid || viewerData.study_uid || '';
    const initialFeedback = viewerData.initialFeedback || null;
    const roiData = viewerData.roiData || {};

    let initialUiSnapshot = null;

    // In-memory store for comments (keyed by ROI name)
    const roiComments = {};
    let activeCommentRoi = null;
    let initialized = false;
    let submitStatusHideTimer = null;
    const rowStatusHideTimers = new Map();

    function getCookie(name) {
        const cookieValue = document.cookie
            .split(';')
            .map((c) => c.trim())
            .find((c) => c.startsWith(`${name}=`));

        if (!cookieValue) return null;
        return decodeURIComponent(cookieValue.split('=').slice(1).join('='));
    }

    function buildCsrfHeaders() {
        const token = getCookie('csrftoken');
        if (!token) return {};
        return { 'X-CSRFToken': token };
    }

    function setStatus(statusEl, text, level) {
        if (!statusEl) return;
        if (!statusEl.dataset.baseClass) {
            statusEl.dataset.baseClass = statusEl.className || '';
        }
        statusEl.textContent = text;

        const baseClass = statusEl.dataset.baseClass;
        let levelClass = 'text-teal-600';
        if (level === 'success') {
            levelClass = 'text-green-600 font-medium';
        } else if (level === 'error') {
            levelClass = 'text-red-600';
        } else if (level === 'warning') {
            levelClass = 'text-yellow-600';
        }
        statusEl.className = `${baseClass} ${levelClass}`.trim();

        // Auto-hide submit status after a short delay
        if (statusEl.id === 'submitRatingStatus') {
            if (submitStatusHideTimer) {
                window.clearTimeout(submitStatusHideTimer);
                submitStatusHideTimer = null;
            }
            const shouldAutoHide = text && String(text).trim().length;
            if (shouldAutoHide) {
                submitStatusHideTimer = window.setTimeout(() => {
                    statusEl.textContent = '';
                    statusEl.className = baseClass;
                    submitStatusHideTimer = null;
                }, 5000);
            }
            return;
        }

        // Auto-hide row-level statuses
        if (rowStatusHideTimers.has(statusEl)) {
            window.clearTimeout(rowStatusHideTimers.get(statusEl));
            rowStatusHideTimers.delete(statusEl);
        }
        if (text && String(text).trim().length) {
            const timerId = window.setTimeout(() => {
                statusEl.textContent = '';
                statusEl.className = baseClass;
                rowStatusHideTimers.delete(statusEl);
            }, 4000);
            rowStatusHideTimers.set(statusEl, timerId);
        }
    }

    function syncStarSelection(roiName, type, value) {
        const selector = `.roi-rating-${type}[data-roi-name="${roiName}"]`;
        document.querySelectorAll(selector).forEach((input) => {
            input.checked = String(input.value) === String(value);
        });
    }

    function updateStarColors(roiName, type, value) {
        const selector = `.roi-rating-${type}[data-roi-name="${roiName}"]`;
        document.querySelectorAll(selector).forEach((input) => {
            const star = input.parentElement ? input.parentElement.querySelector('.star-icon') : null;
            if (!star) return;
            const starVal = parseInt(input.value, 10);
            if (!Number.isNaN(starVal) && starVal <= value) {
                star.classList.add('star-filled');
            } else {
                star.classList.remove('star-filled');
            }
        });
    }

    function updateRatingDisplayForRoi(roiName, type) {
        const selector = `.roi-rating-${type}[data-roi-name="${roiName}"]`;
        const checked = document.querySelector(`${selector}:checked`);
        const value = checked ? parseInt(checked.value, 10) : 0;
        let displayId = checked ? checked.getAttribute('aria-describedby') : null;
        if (!displayId) {
            const row = document.querySelector(`#roiRatingTable tbody tr[data-roi-name="${roiName}"]`);
            if (row && row.parentElement) {
                const rows = Array.from(row.parentElement.querySelectorAll('tr'));
                const idx = rows.indexOf(row);
                if (idx >= 0) displayId = `rating-display-${idx}-${type}`;
            }
        }
        const displayEl = displayId ? document.getElementById(displayId) : null;
        if (displayEl) displayEl.textContent = value > 0 ? `${value}/10` : 'Not rated';
        updateStarColors(roiName, type, value);
    }

    function updateCommentButtons() {
        document.querySelectorAll('.roi-comment-btn').forEach((btn) => {
            const roiName = btn.dataset.roiName;
            if (roiComments[roiName]) {
                btn.classList.add('bg-indigo-100', 'border-indigo-300');
                btn.title = 'Edit comment';
            } else {
                btn.classList.remove('bg-indigo-100', 'border-indigo-300');
                btn.title = 'Add comment';
            }
        });
    }

    function setSubmitButtonMode(roiName, mode = 'submit') {
        const btn = document.querySelector(`.roi-submit-btn[data-roi-name="${roiName}"]`);
        if (!btn) return;
        const label = mode === 'edit' ? 'Edit' : 'Submit';
        btn.textContent = label;
        btn.setAttribute('aria-label', `${label} rating for ${roiName}`);
        btn.dataset.mode = mode;

        const submitClasses = ['bg-indigo-600', 'hover:bg-indigo-700'];
        const editClasses = ['bg-amber-600', 'hover:bg-amber-700'];
        btn.classList.remove(...submitClasses, ...editClasses);
        btn.classList.add(...(mode === 'edit' ? editClasses : submitClasses));
    }

    function updateSubmitButtonState(roiName, r1Val, r2Val, commentVal) {
        const hasRating = (typeof r1Val === 'number' && r1Val > 0)
            || (typeof r2Val === 'number' && r2Val > 0);
        const hasComment = Boolean(commentVal);
        setSubmitButtonMode(roiName, hasRating || hasComment ? 'edit' : 'submit');
    }

    function openCommentModal(roiName) {
        activeCommentRoi = roiName;
        const modal = document.getElementById('commentModal');
        const nameEl = document.getElementById('commentModalRoiName');
        const textEl = document.getElementById('commentModalText');

        if (nameEl) nameEl.textContent = roiName;
        if (textEl) textEl.value = roiComments[roiName] || '';
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
        if (textEl) textEl.focus();
    }

    function closeCommentModal() {
        activeCommentRoi = null;
        const modal = document.getElementById('commentModal');
        if (modal) {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
        }
    }

    function saveComment() {
        if (!activeCommentRoi) return;
        const textEl = document.getElementById('commentModalText');
        const comment = (textEl ? textEl.value : '').trim();
        if (comment) {
            roiComments[activeCommentRoi] = comment;
        } else {
            delete roiComments[activeCommentRoi];
        }
        updateCommentButtons();
        closeCommentModal();
    }

    function filterRoiRows(query) {
        const q = String(query || '').trim().toLowerCase();
        const rows = document.querySelectorAll('#roiRatingTable tbody tr');
        rows.forEach((row) => {
            const roiName = (row.dataset.roiName || '').toLowerCase();
            row.style.display = !q || roiName.includes(q) ? '' : 'none';
        });
    }

    function captureInitialUiSnapshot() {
        const snapshot = {
            r1: {},
            r2: {},
            comments: {},
        };

        document.querySelectorAll('#roiRatingTable tbody tr').forEach((row) => {
            const roiName = row.dataset.roiName;
            if (!roiName) return;

            const r1Input = row.querySelector('.roi-rating-r1:checked');
            const r2Input = row.querySelector('.roi-rating-r2:checked');
            snapshot.r1[roiName] = r1Input ? parseInt(r1Input.value, 10) : null;
            snapshot.r2[roiName] = r2Input ? parseInt(r2Input.value, 10) : null;
        });

        Object.keys(roiComments).forEach((k) => {
            snapshot.comments[k] = roiComments[k];
        });

        return snapshot;
    }

    function restoreUiSnapshot(snapshot) {
        if (!snapshot) return;

        // Restore comments
        Object.keys(roiComments).forEach((k) => delete roiComments[k]);
        Object.keys(snapshot.comments || {}).forEach((k) => {
            roiComments[k] = snapshot.comments[k];
        });
        updateCommentButtons();

        // Restore ratings
        document.querySelectorAll('#roiRatingTable tbody tr').forEach((row) => {
            const roiName = row.dataset.roiName;
            if (!roiName) return;

            const r1Val = snapshot.r1 ? snapshot.r1[roiName] : null;
            const r2Val = snapshot.r2 ? snapshot.r2[roiName] : null;

            row.querySelectorAll('.roi-rating-r1').forEach((input) => {
                input.checked = r1Val != null && String(input.value) === String(r1Val);
            });
            row.querySelectorAll('.roi-rating-r2').forEach((input) => {
                input.checked = r2Val != null && String(input.value) === String(r2Val);
            });

            updateRatingDisplayForRoi(roiName, 'r1');
            updateRatingDisplayForRoi(roiName, 'r2');
            const commentVal = snapshot.comments ? snapshot.comments[roiName] : null;
            updateSubmitButtonState(roiName, r1Val, r2Val, commentVal);
        });
    }

    async function submitRoiRating(roiName) {
        const row = document.querySelector(`#roiRatingTable tbody tr[data-roi-name="${roiName}"]`);
        if (!row) return;

        const submitBtn = row.querySelector('.roi-submit-btn');
        const rowStatus = row.querySelector('.roi-submit-status');
        const roiId = roiData[roiName];
        if (!roiId) {
            setStatus(rowStatus, 'ROI not linked to feedback record.', 'error');
            return;
        }

        const r1Input = row.querySelector('.roi-rating-r1:checked');
        const r2Input = row.querySelector('.roi-rating-r2:checked');
        const r1Val = r1Input ? parseInt(r1Input.value, 10) : NaN;
        const r2Val = r2Input ? parseInt(r2Input.value, 10) : NaN;
        const r1 = Number.isNaN(r1Val) || r1Val <= 0 ? null : r1Val;
        const r2 = Number.isNaN(r2Val) || r2Val <= 0 ? null : r2Val;
        const comment = roiComments[roiName] || '';

        if (r1 === null && r2 === null && !comment) {
            setStatus(rowStatus, 'Please rate or comment before submitting.', 'warning');
            return;
        }

        if (submitBtn) submitBtn.disabled = true;
        setStatus(rowStatus, 'Submitting...', 'info');

        const controller = new AbortController();
        const timeoutId = window.setTimeout(() => controller.abort(), 20000);

        try {
            const res = await fetch('/api/submit-feedback/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...buildCsrfHeaders(),
                },
                body: JSON.stringify({
                    patient_id: patientId,
                    rt1_label: rt1Label,
                    rt2_label: rt2Label,
                    rt1_sop_uid: rt1SopUid,
                    rt2_sop_uid: rt2SopUid,
                    study_uid: studyUid,
                    ratings: [{
                        roi_id: roiId,
                        roi_label: roiName,
                        ...(r1 !== null ? { rt1_rating: r1 } : {}),
                        ...(r2 !== null ? { rt2_rating: r2 } : {}),
                        ...(comment ? { comment } : {}),
                    }],
                }),
                signal: controller.signal,
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || !data.success) {
                setStatus(rowStatus, data.error || 'Failed to submit.', 'error');
                return;
            }

            setStatus(
                rowStatus,
                data.errors && data.errors.length
                    ? `Saved with warnings: ${data.errors.join('; ')}`
                    : 'Saved.',
                data.errors && data.errors.length ? 'warning' : 'success',
            );

            const globalStatus = document.getElementById('submitRatingStatus');
            setStatus(globalStatus, `Saved rating for ${roiName}.`, 'success');
            initialUiSnapshot = captureInitialUiSnapshot();
            setSubmitButtonMode(roiName, 'edit');
        } catch (e) {
            const isAbort = e && (e.name === 'AbortError' || String(e).includes('AbortError'));
            setStatus(
                rowStatus,
                isAbort ? 'Request timed out. Please try again.' : 'Network error. Please try again.',
                'error',
            );
        } finally {
            window.clearTimeout(timeoutId);
            if (submitBtn) submitBtn.disabled = false;
        }
    }

    function initRatings() {
        if (initialized) return;

        const table = document.getElementById('roiRatingTable');
        if (!table) return;

        initialized = true;

        // Load existing ratings and comments into inputs
        if (initialFeedback) {
            document.querySelectorAll('.roi-rating-r1').forEach((input) => {
                const roiName = input.dataset.roiName;
                const fb = initialFeedback[roiName];
                if (fb && fb.rt1_rating != null && String(input.value) === String(fb.rt1_rating)) {
                    input.checked = true;
                }
            });
            document.querySelectorAll('.roi-rating-r2').forEach((input) => {
                const roiName = input.dataset.roiName;
                const fb = initialFeedback[roiName];
                if (fb && fb.rt2_rating != null && String(input.value) === String(fb.rt2_rating)) {
                    input.checked = true;
                }
            });
            // After selection, paint stars and displays
            Object.keys(initialFeedback).forEach((roiName) => {
                updateRatingDisplayForRoi(roiName, 'r1');
                updateRatingDisplayForRoi(roiName, 'r2');
            });
        }

        // Load existing comments
        if (initialFeedback) {
            Object.keys(initialFeedback).forEach((roiName) => {
                const fb = initialFeedback[roiName];
                if (!fb) return;

                if (fb.comment) {
                    roiComments[roiName] = fb.comment;
                }

                 updateSubmitButtonState(
                    roiName,
                    fb.rt1_rating != null ? parseInt(fb.rt1_rating, 10) : null,
                    fb.rt2_rating != null ? parseInt(fb.rt2_rating, 10) : null,
                    fb.comment,
                );
            });
        }

        // Initialize displays for rows without initial feedback
        document.querySelectorAll('.roi-rating-r1').forEach((input) => {
            updateRatingDisplayForRoi(input.dataset.roiName, 'r1');
        });
        document.querySelectorAll('.roi-rating-r2').forEach((input) => {
            updateRatingDisplayForRoi(input.dataset.roiName, 'r2');
        });

        // Live updates for rating displays
        document.querySelectorAll('.roi-rating-r1, .roi-rating-r2').forEach((input) => {
            input.addEventListener('change', () => {
                const roiName = input.dataset.roiName;
                const type = input.classList.contains('roi-rating-r1') ? 'r1' : 'r2';
                syncStarSelection(roiName, type, input.value);
                updateRatingDisplayForRoi(roiName, type);
            });
        });

        // Update comment button indicators
        updateCommentButtons();

        // Capture the initial UI state (after applying initial feedback)
        initialUiSnapshot = captureInitialUiSnapshot();

        // ROI search filter
        const roiSearch = document.getElementById('roiSearchFilter');
        if (roiSearch) {
            roiSearch.addEventListener('input', () => {
                filterRoiRows(roiSearch.value);
            });
        }

        const roiSearchClearBtn = document.getElementById('roiSearchClearBtn');
        if (roiSearchClearBtn && roiSearch) {
            roiSearchClearBtn.addEventListener('click', () => {
                roiSearch.value = '';
                filterRoiRows('');
                roiSearch.focus();
            });
        }

        // Reset modified ratings (reset to initial state)
        const clearBtn = document.getElementById('clearAllRatingsBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                const statusEl = document.getElementById('submitRatingStatus');
                restoreUiSnapshot(initialUiSnapshot);
                if (roiSearch) {
                    roiSearch.value = '';
                    filterRoiRows('');
                }
                setStatus(statusEl, 'Reset to previously saved ratings.', 'info');
            });
        }

        // Per-row submit buttons
        document.querySelectorAll('.roi-submit-btn').forEach((btn) => {
            btn.addEventListener('click', () => submitRoiRating(btn.dataset.roiName));
        });

        // Comment modal buttons
        document.querySelectorAll('.roi-comment-btn').forEach((btn) => {
            btn.addEventListener('click', () => openCommentModal(btn.dataset.roiName));
        });

        const cancelBtn = document.getElementById('commentModalCancel');
        if (cancelBtn) cancelBtn.addEventListener('click', closeCommentModal);

        const saveBtn = document.getElementById('commentModalSave');
        if (saveBtn) saveBtn.addEventListener('click', saveComment);

        // Close modal on backdrop click
        const modal = document.getElementById('commentModal');
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) closeCommentModal();
            });
        }
    }

    window.RoiRatings = {
        initRatings,
        submitRoiRating,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initRatings);
    } else {
        initRatings();
    }
})();
