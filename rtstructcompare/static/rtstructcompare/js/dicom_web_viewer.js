const dicomViewerData = window.dicomViewerData || {};
const ctData = dicomViewerData.ctData || [];
const rt1Contours = dicomViewerData.rt1Contours || {};
const rt2Contours = dicomViewerData.rt2Contours || {};
const commonStructures = dicomViewerData.commonStructures || [];

const patientId = dicomViewerData.patientId || '';
const rt1Label = dicomViewerData.rt1Label || 'RTSTRUCT 1';
const rt2Label = dicomViewerData.rt2Label || 'RTSTRUCT 2';
const rt1SopUid = dicomViewerData.rt1SopUid || '';
const rt2SopUid = dicomViewerData.rt2SopUid || '';
const studyUid = dicomViewerData.studyUid || dicomViewerData.study_uid || '';
const initialFeedback = dicomViewerData.initialFeedback || null;
const roiData = dicomViewerData.roiData || {};

let currentSliceIndex = 0;
let selectedROIs = new Set();
let isSyncingROIs = false;
let currentWindow = 2000;
let currentLevel = 1000;
let zoomLevel1 = 1.4;
let zoomLevel2 = 1.4;
let panOffset1 = { x: 0, y: 0 };
let panOffset2 = { x: 0, y: 0 };

let _tempCanvas = null;
let _tempCtx = null;

const windowLevelPresets = {
    pan: { window: 400, level: 0 },
    soft_tissue: { window: 400, level: 40 },
    lung: { window: 1500, level: -600 },
    bone: { window: 2000, level: 300 },
    brain: { window: 80, level: 40 },
    liver: { window: 150, level: 60 },
    custom: { window: 400, level: 40 },
};

const colorPalette = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7',
    '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E2',
    '#F8B739', '#52B788', '#E76F51', '#2A9D8F', '#E63946',
];

function initializeViewer() {
    const canvas1 = document.getElementById('ctViewer1');
    const canvas2 = document.getElementById('ctViewer2');

    if (!canvas1 || !canvas2) return;

    canvas1.width = canvas1.offsetWidth;
    canvas1.height = canvas1.offsetHeight;
    canvas2.width = canvas2.offsetWidth;
    canvas2.height = canvas2.offsetHeight;

    const totalSlicesEl = document.getElementById('totalSlices');
    if (totalSlicesEl) totalSlicesEl.textContent = ctData.length;

    const currentSliceEl = document.getElementById('currentSlice');
    if (currentSliceEl) currentSliceEl.textContent = currentSliceIndex + 1;

    const sliceSlider = document.getElementById('sliceSlider');
    if (sliceSlider) {
        sliceSlider.max = Math.max(ctData.length - 1, 0);
        sliceSlider.value = currentSliceIndex;
    }

    // Select-all checkbox for ROI inclusion
    const selectAll = document.getElementById('roiRatingSelectAll');
    const rowCheckboxes = document.querySelectorAll('.roi-rating-include');
    if (selectAll) {
        selectAll.addEventListener('change', () => {
            rowCheckboxes.forEach((cb) => {
                cb.checked = selectAll.checked;
            });
        });
    }
    rowCheckboxes.forEach((cb) => {
        cb.addEventListener('change', () => {
            if (!selectAll) return;
            const allChecked = Array.from(rowCheckboxes).every((c) => c.checked);
            const anyChecked = Array.from(rowCheckboxes).some((c) => c.checked);
            selectAll.indeterminate = !allChecked && anyChecked;
            selectAll.checked = allChecked;
        });
    });
    updateSliceInfo();

    const windowSlider = document.getElementById('windowSlider');
    if (windowSlider) windowSlider.value = currentWindow;
    const levelSlider = document.getElementById('levelSlider');
    if (levelSlider) levelSlider.value = currentLevel;
    const windowValue = document.getElementById('windowValue');
    if (windowValue) windowValue.textContent = currentWindow;
    const levelValue = document.getElementById('levelValue');
    if (levelValue) levelValue.textContent = currentLevel;

    displaySlice();
    setupMouseHandlers();
    updateZoomDisplays();
}

function displaySlice() {
    const canvas1 = document.getElementById('ctViewer1');
    const canvas2 = document.getElementById('ctViewer2');
    if (!canvas1 || !canvas2) return;
    const ctx1 = canvas1.getContext('2d');
    const ctx2 = canvas2.getContext('2d');

    ctx1.fillStyle = '#000';
    ctx1.fillRect(0, 0, canvas1.width, canvas1.height);
    ctx2.fillStyle = '#000';
    ctx2.fillRect(0, 0, canvas2.width, canvas2.height);

    if (!ctData.length) return;

    const currentSliceEl = document.getElementById('currentSlice');
    if (currentSliceEl) currentSliceEl.textContent = currentSliceIndex + 1;
    const sliceSlider = document.getElementById('sliceSlider');
    if (sliceSlider) sliceSlider.value = currentSliceIndex;
    updateSliceInfo();
    displayCTSlice(ctx1, canvas1.width, canvas1.height, ctData[currentSliceIndex], zoomLevel1, panOffset1);
    displayCTSlice(ctx2, canvas2.width, canvas2.height, ctData[currentSliceIndex], zoomLevel2, panOffset2);

    drawROIOverlays(ctx1, canvas1.width, canvas1.height, rt1Contours, ctData[currentSliceIndex], zoomLevel1, panOffset1);
    drawROIOverlays(ctx2, canvas2.width, canvas2.height, rt2Contours, ctData[currentSliceIndex], zoomLevel2, panOffset2);

    updateZoomDisplays();
}

function updateSliceInfo() {
    const sliceInfo = document.getElementById('sliceInfo');
    if (sliceInfo) {
        sliceInfo.textContent = `Slice ${currentSliceIndex + 1} / ${ctData.length}`;
    }
}

function goToSlice(sliceIndex) {
    currentSliceIndex = parseInt(sliceIndex, 10) || 0;
    displaySlice();
}

function setWindowLevel(preset) {
    const presetValues = windowLevelPresets[preset];
    if (presetValues) {
        currentWindow = presetValues.window;
        currentLevel = presetValues.level;

        const windowSlider = document.getElementById('windowSlider');
        if (windowSlider) windowSlider.value = currentWindow;
        const levelSlider = document.getElementById('levelSlider');
        if (levelSlider) levelSlider.value = currentLevel;
        const windowValue = document.getElementById('windowValue');
        if (windowValue) windowValue.textContent = currentWindow;
        const levelValue = document.getElementById('levelValue');
        if (levelValue) levelValue.textContent = currentLevel;

        displaySlice();
    }
}

function updateWindowLevel() {
    const windowSlider = document.getElementById('windowSlider');
    const levelSlider = document.getElementById('levelSlider');
    currentWindow = windowSlider ? parseInt(windowSlider.value, 10) : currentWindow;
    currentLevel = levelSlider ? parseInt(levelSlider.value, 10) : currentLevel;

    const windowValue = document.getElementById('windowValue');
    if (windowValue) windowValue.textContent = currentWindow;
    const levelValue = document.getElementById('levelValue');
    if (levelValue) levelValue.textContent = currentLevel;

    displaySlice();
}

function displayCTSlice(ctx, canvasWidth, canvasHeight, slice, zoomLevel = 1.0, panOffset = { x: 0, y: 0 }) {
    const imageData = ctx.createImageData(slice.width, slice.height);

    const windowWidth = currentWindow;
    const windowLevel = currentLevel;
    const minValue = windowLevel - windowWidth / 2;
    const maxValue = windowLevel + windowWidth / 2;
    const range = maxValue - minValue;

    for (let i = 0; i < slice.pixels.length; i += 1) {
        const pixelValue = slice.pixels[i];

        let displayValue = ((pixelValue - minValue) / range) * 255;
        displayValue = Math.max(0, Math.min(255, displayValue));

        imageData.data[i * 4] = displayValue;
        imageData.data[i * 4 + 1] = displayValue;
        imageData.data[i * 4 + 2] = displayValue;
        imageData.data[i * 4 + 3] = 255;
    }

    if (!_tempCanvas) {
        _tempCanvas = document.createElement('canvas');
        _tempCtx = _tempCanvas.getContext('2d');
    }
    if (_tempCanvas.width !== slice.width) _tempCanvas.width = slice.width;
    if (_tempCanvas.height !== slice.height) _tempCanvas.height = slice.height;
    _tempCtx.putImageData(imageData, 0, 0);

    const scaledWidth = slice.width * zoomLevel;
    const scaledHeight = slice.height * zoomLevel;
    const x = (canvasWidth - scaledWidth) / 2 + panOffset.x;
    const y = (canvasHeight - scaledHeight) / 2 + panOffset.y;

    ctx.drawImage(_tempCanvas, 0, 0, slice.width, slice.height, x, y, scaledWidth, scaledHeight);
}

function drawROIOverlays(ctx, canvasWidth, canvasHeight, rtstructContours, currentSlice, zoomLevel = 1.0, panOffset = { x: 0, y: 0 }) {
    ctx.globalAlpha = 0.7;

    const selectedROIsArray = Array.from(selectedROIs);

    const pixelSpacing = currentSlice.pixel_spacing || [1.0, 1.0];
    const imagePosition = currentSlice.image_position || [0, 0, 0];

    const scaledWidth = currentSlice.width * zoomLevel;
    const scaledHeight = currentSlice.height * zoomLevel;
    const baseX = (canvasWidth - scaledWidth) / 2 + panOffset.x;
    const baseY = (canvasHeight - scaledHeight) / 2 + panOffset.y;

    selectedROIsArray.forEach((roiName, roiIndex) => {
        const roiContourData = rtstructContours[roiName];
        if (!roiContourData || !roiContourData.contours) return;

        const color = colorPalette[roiIndex % colorPalette.length];
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;

        let sliceZ = 0;
        if (currentSlice.image_position && currentSlice.image_position.length >= 3) {
            sliceZ = parseFloat(currentSlice.image_position[2]);
        } else if (currentSlice.slice_location) {
            sliceZ = parseFloat(currentSlice.slice_location);
        }

        const tolerance = 2.5;

        let minDiff = Infinity;
        const candidates = [];

        roiContourData.contours.forEach((contour) => {
            if (!contour.points || contour.points.length < 3) return;
            const contourZ = parseFloat(contour.points[0][2]);
            const diff = Math.abs(contourZ - sliceZ);
            if (Number.isNaN(diff)) return;
            if (diff <= tolerance) {
                if (diff < minDiff) {
                    minDiff = diff;
                }
                candidates.push({ contour, diff });
            }
        });

        if (!Number.isFinite(minDiff)) return;

        const eps = 1e-3;
        const contoursToDraw = candidates
            .filter(({ diff }) => diff <= minDiff + eps)
            .map(({ contour }) => contour);

        contoursToDraw.forEach((contour) => {
            const points2D = contour.points.map((point) => {
                const x = point[0];
                const y = point[1];

                const pixelX = (x - imagePosition[0]) / pixelSpacing[0];
                const pixelY = (y - imagePosition[1]) / pixelSpacing[1];

                const canvasX = baseX + pixelX * zoomLevel;
                const canvasY = baseY + pixelY * zoomLevel;

                return [canvasX, canvasY];
            });

            const validPoints = points2D.filter((point) =>
                point[0] >= 0 && point[0] <= canvasWidth &&
                point[1] >= 0 && point[1] <= canvasHeight,
            );

            if (validPoints.length >= 3) {
                ctx.beginPath();
                ctx.moveTo(validPoints[0][0], validPoints[0][1]);
                for (let i = 1; i < validPoints.length; i += 1) {
                    ctx.lineTo(validPoints[i][0], validPoints[i][1]);
                }
                ctx.closePath();
                ctx.stroke();

                ctx.fillStyle = color;
                ctx.font = '12px Arial';
                const labelX = validPoints[0][0];
                const labelY = Math.max(10, validPoints[0][1] - 5);
                ctx.fillText(roiName, labelX, labelY);
            }
        });
    });

    ctx.globalAlpha = 1.0;
}

function toggleROI(roiName) {
    const next = new Set(selectedROIs);

    if (next.has(roiName)) {
        next.delete(roiName);
    } else {
        next.add(roiName);
    }

    syncROIs(next);
}

function selectAllROIs() {
    syncROIs(commonStructures);
}

function clearAllROIs() {
    syncROIs([]);
}

function previousSlice() {
    if (currentSliceIndex > 0) {
        currentSliceIndex -= 1;
        displaySlice();
    }
}

function nextSlice() {
    if (currentSliceIndex < ctData.length - 1) {
        currentSliceIndex += 1;
        displaySlice();
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowUp') previousSlice();
    if (e.key === 'ArrowDown') nextSlice();
});

function updateZoomLevel(viewer, newLevel) {
    if (viewer === 1) {
        zoomLevel1 = Math.max(0.1, Math.min(5.0, newLevel));
    } else {
        zoomLevel2 = Math.max(0.1, Math.min(5.0, newLevel));
    }
    displaySlice();
}

function zoomIn(viewer) {
    updateZoomLevel(viewer, (viewer === 1 ? zoomLevel1 : zoomLevel2) * 1.25);
}

function zoomOut(viewer) {
    updateZoomLevel(viewer, (viewer === 1 ? zoomLevel1 : zoomLevel2) / 1.25);
}

function resetZoom(viewer) {
    if (viewer === 1) {
        zoomLevel1 = 1.4;
        panOffset1 = { x: 0, y: 0 };
    } else {
        zoomLevel2 = 1.4;
        panOffset2 = { x: 0, y: 0 };
    }
    displaySlice();
}

function zoomBoth(direction) {
    const multiplier = direction === 'in' ? 1.25 : 1 / 1.25;
    updateZoomLevel(1, zoomLevel1 * multiplier);
    updateZoomLevel(2, zoomLevel2 * multiplier);
}

function resetBothZoom() {
    zoomLevel1 = 1.4;
    zoomLevel2 = 1.4;
    panOffset1 = { x: 0, y: 0 };
    panOffset2 = { x: 0, y: 0 };
    displaySlice();
}

function updateZoomDisplays() {
    const zoom1 = document.getElementById('zoom1');
    if (zoom1) zoom1.textContent = `${Math.round(zoomLevel1 * 100)}%`;
    const zoom2 = document.getElementById('zoom2');
    if (zoom2) zoom2.textContent = `${Math.round(zoomLevel2 * 100)}%`;
}

function setupMouseHandlers() {
    const canvas1 = document.getElementById('ctViewer1');
    const canvas2 = document.getElementById('ctViewer2');
    if (!canvas1 || !canvas2) return;

    function handleWheel(e) {
        e.preventDefault();
        e.deltaY > 0 ? nextSlice() : previousSlice();
    }

    let isDragging = false;
    let dragStart = { x: 0, y: 0 };
    let initialPanOffset1 = { x: 0, y: 0 };
    let initialPanOffset2 = { x: 0, y: 0 };

    function startDrag(e) {
        isDragging = true;
        dragStart = { x: e.clientX, y: e.clientY };
        initialPanOffset1 = { x: panOffset1.x, y: panOffset1.y };
        initialPanOffset2 = { x: panOffset2.x, y: panOffset2.y };
        canvas1.style.cursor = 'grabbing';
        canvas2.style.cursor = 'grabbing';
    }

    function handleDrag(e) {
        if (!isDragging) return;
        const deltaX = e.clientX - dragStart.x;
        const deltaY = e.clientY - dragStart.y;
        panOffset1.x = initialPanOffset1.x + deltaX;
        panOffset1.y = initialPanOffset1.y + deltaY;
        panOffset2.x = initialPanOffset2.x + deltaX;
        panOffset2.y = initialPanOffset2.y + deltaY;
        displaySlice();
    }

    function stopDrag() {
        if (!isDragging) return;
        isDragging = false;
        canvas1.style.cursor = 'grab';
        canvas2.style.cursor = 'grab';
    }

    canvas1.addEventListener('wheel', handleWheel);
    canvas2.addEventListener('wheel', handleWheel);

    canvas1.addEventListener('mousedown', startDrag);
    canvas2.addEventListener('mousedown', startDrag);
    window.addEventListener('mousemove', handleDrag);
    window.addEventListener('mouseup', stopDrag);
    canvas1.style.cursor = 'grab';
    canvas2.style.cursor = 'grab';
}

function dismissComparisonBanner() {
    const el = document.getElementById('comparisonBanner');
    if (el) el.style.display = 'none';
}

function onROISelect() {
    if (isSyncingROIs) return;
    const select = document.getElementById('roiSelect');
    if (!select) return;
    const values = Array.from(select.selectedOptions).map((option) => option.value);
    syncROIs(values, 'select');
}

function syncROIs(newSelection, source = 'external') {
    if (isSyncingROIs) return;
    isSyncingROIs = true;

    try {
        const nextSelection = Array.from(newSelection);
        selectedROIs = new Set(nextSelection);
        commonStructures.forEach((roi, i) => {
            const cb = document.getElementById(`roi_${i}`);
            if (cb) cb.checked = selectedROIs.has(roi);
        });

        displaySlice();
    } finally {
        isSyncingROIs = false;
    }
}

// In-memory store for comments (keyed by ROI name)
const roiComments = {};
let activeCommentRoi = null;

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
    const displayId = checked ? checked.getAttribute('aria-describedby') : null;
    const displayEl = displayId ? document.getElementById(displayId) : null;
    if (displayEl) displayEl.textContent = value > 0 ? `${value}/10` : 'Not rated';
    updateStarColors(roiName, type, value);
}

function initRatings() {
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
        if (statusEl) {
            statusEl.textContent = 'No ratings to submit.';
            statusEl.className = 'text-sm text-yellow-600';
        }
        return;
    }

    if (btn) btn.disabled = true;
    if (statusEl) {
        statusEl.textContent = 'Submitting...';
        statusEl.className = 'text-sm text-gray-600';
    }

    try {
        const res = await fetch('/api/submit-feedback/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                patient_id: patientId,
                rt1_label: rt1Label,
                rt2_label: rt2Label,
                rt1_sop_uid: rt1SopUid,
                rt2_sop_uid: rt2SopUid,
                study_uid: studyUid,
                ratings,
            }),
        });
        const data = await res.json().catch(() => ({}));

        if (!res.ok || !data.success) {
            if (statusEl) {
                statusEl.textContent = data.error || 'Failed to submit.';
                statusEl.className = 'text-sm text-red-600';
            }
            return;
        }

        if (statusEl) {
            const msg = `Saved ${data.saved_count} rating(s).`;
            statusEl.textContent = data.errors && data.errors.length
                ? `${msg} Errors: ${data.errors.join('; ')}`
                : msg;
            statusEl.className = 'text-sm text-green-600 font-medium';
        }
    } catch (e) {
        if (statusEl) {
            statusEl.textContent = 'Network error. Please try again.';
            statusEl.className = 'text-sm text-red-600';
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}

const initializePage = () => {
    initializeViewer();
    initRatings();
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializePage);
} else {
    initializePage();
}
