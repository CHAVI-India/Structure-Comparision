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
    let currentSubmitController = null;
    let submitStatusHideTimer = null;

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
        statusEl.textContent = text;

        if (level === 'success') {
            statusEl.className = 'text-sm text-green-600 font-medium';
        } else if (level === 'error') {
            statusEl.className = 'text-sm text-red-600';
        } else if (level === 'warning') {
            statusEl.className = 'text-sm text-yellow-600';
        } else {
            statusEl.className = 'text-sm text-teal-600';
        }

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
                    submitStatusHideTimer = null;
                }, 5000);
            }
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
        // Auto-check the include checkbox if comment was added
        if (comment) {
            const row = document.querySelector(`#roiRatingTable tbody tr[data-roi-name="${activeCommentRoi}"]`);
            const cb = row ? row.querySelector('.roi-rating-include') : null;
            if (cb) cb.checked = true;
        }
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
            include: {},
            r1: {},
            r2: {},
            comments: {},
        };

        document.querySelectorAll('#roiRatingTable tbody tr').forEach((row) => {
            const roiName = row.dataset.roiName;
            if (!roiName) return;

            const includeCb = row.querySelector('.roi-rating-include');
            snapshot.include[roiName] = !!(includeCb && includeCb.checked);

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

        // Restore include + ratings
        document.querySelectorAll('#roiRatingTable tbody tr').forEach((row) => {
            const roiName = row.dataset.roiName;
            if (!roiName) return;

            const includeCb = row.querySelector('.roi-rating-include');
            if (includeCb) includeCb.checked = !!(snapshot.include && snapshot.include[roiName]);

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
        });
    }

    async function submitAllRatings() {
        const btn = document.getElementById('submitAllRatingsBtn');
        const statusEl = document.getElementById('submitRatingStatus');

        const ratings = [];
        const rows = document.querySelectorAll('#roiRatingTable tbody tr');

        rows.forEach((row) => {
            const roiName = row.dataset.roiName;
            const roiId = roiData[roiName];
            if (!roiId) return;

            const includeCb = row.querySelector('.roi-rating-include');
            if (includeCb && !includeCb.checked) return;

            const r1Input = row.querySelector('.roi-rating-r1:checked');
            const r2Input = row.querySelector('.roi-rating-r2:checked');
            const r1Val = r1Input ? parseInt(r1Input.value, 10) : NaN;
            const r2Val = r2Input ? parseInt(r2Input.value, 10) : NaN;
            const r1 = Number.isNaN(r1Val) || r1Val <= 0 ? null : r1Val;
            const r2 = Number.isNaN(r2Val) || r2Val <= 0 ? null : r2Val;
            const comment = roiComments[roiName] || '';

            if (r1 !== null || r2 !== null || comment) {
                const item = { roi_id: roiId, roi_label: roiName };
                if (r1 !== null) item.rt1_rating = r1;
                if (r2 !== null) item.rt2_rating = r2;
                if (comment) item.comment = comment;
                ratings.push(item);
            }
        });

        if (!ratings.length) {
            setStatus(statusEl, 'No ratings to submit.', 'warning');
            return;
        }

        if (btn) btn.disabled = true;
        setStatus(statusEl, 'Submitting...', 'info');

        if (currentSubmitController) {
            currentSubmitController.abort();
        }
        currentSubmitController = new AbortController();
        const timeoutMs = 20000;
        const timeoutId = window.setTimeout(() => {
            if (currentSubmitController) currentSubmitController.abort();
        }, timeoutMs);

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
                    ratings,
                }),
                signal: currentSubmitController.signal,
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || !data.success) {
                setStatus(statusEl, data.error || 'Failed to submit.', 'error');
                return;
            }

            if (statusEl) {
                const msg = `Saved ${data.saved_count} rating(s).`;
                setStatus(
                    statusEl,
                    data.errors && data.errors.length
                        ? `${msg} Errors: ${data.errors.join('; ')}`
                        : msg,
                    data.errors && data.errors.length ? 'warning' : 'success',
                );
            }
        } catch (e) {
            const isAbort = e && (e.name === 'AbortError' || String(e).includes('AbortError'));
            setStatus(
                statusEl,
                isAbort ? 'Request timed out. Please try again.' : 'Network error. Please try again.',
                'error',
            );
        } finally {
            window.clearTimeout(timeoutId);
            if (btn) btn.disabled = false;
            currentSubmitController = null;
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

        // Load existing comments and include state
        if (initialFeedback) {
            Object.keys(initialFeedback).forEach((roiName) => {
                const fb = initialFeedback[roiName];
                if (!fb) return;

                if (fb.comment) {
                    roiComments[roiName] = fb.comment;
                }

                const row = document.querySelector(`#roiRatingTable tbody tr[data-roi-name="${roiName}"]`);
                const cb = row ? row.querySelector('.roi-rating-include') : null;
                if (cb) {
                    cb.checked = !!(fb.include != null ? fb.include : fb.rt1_rating != null || fb.rt2_rating != null || fb.comment);
                }
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
                // Auto-check the include checkbox
                const row = document.querySelector(`#roiRatingTable tbody tr[data-roi-name="${roiName}"]`);
                const cb = row ? row.querySelector('.roi-rating-include') : null;
                if (cb) cb.checked = true;
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

        // Submit button
        const submitBtn = document.getElementById('submitAllRatingsBtn');
        if (submitBtn) {
            submitBtn.addEventListener('click', submitAllRatings);
        }

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
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initRatings);
    } else {
        initRatings();
    }
})();
