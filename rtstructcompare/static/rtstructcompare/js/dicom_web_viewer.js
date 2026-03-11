const dicomViewerData = window.dicomViewerData || {};
const ctData = dicomViewerData.ctData || [];
const rt1Contours = dicomViewerData.rt1Contours || {};
const rt2Contours = dicomViewerData.rt2Contours || {};
const commonStructures = dicomViewerData.commonStructures || [];

let currentSliceIndex = 0;
let selectedROIs = new Set();
let isSyncingROIs = false;
let currentWindow = 400;
let currentLevel = 40;
let zoomLevel1 = 1;
let zoomLevel2 = 1;
let panOffset1 = { x: 0, y: 0 };
let panOffset2 = { x: 0, y: 0 };

let _tempCanvas = null;
let _tempCtx = null;

function syncCanvasSize(canvas) {
    if (!canvas) return false;
    const dpr = window.devicePixelRatio || 1;
    const displayWidth = Math.max(1, Math.floor(canvas.offsetWidth));
    const displayHeight = Math.max(1, Math.floor(canvas.offsetHeight));
    const neededWidth = Math.floor(displayWidth * dpr);
    const neededHeight = Math.floor(displayHeight * dpr);
    if (canvas.width !== neededWidth || canvas.height !== neededHeight) {
        canvas.width = neededWidth;
        canvas.height = neededHeight;
        const ctx = canvas.getContext('2d');
        if (ctx) {
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        return true;
    }
    return false;
}

function prefetchSlice(sliceIndex) {
    if (sliceIndex < 0 || sliceIndex >= ctData.length) return;
    const slice = ctData[sliceIndex];
    if (!slice) return;
    if (pixelCache.has(slice.index) || loadingSlices.has(slice.index)) return;

    ensureSlicePixels(slice).catch((err) => {
        console.warn('Slice prefetch failed', slice.index, err);
    });
}

function prefetchSliceWindow(centerIndex) {
    if (!ctData.length || PREFETCH_WINDOW_SIZE <= 0) return;

    const halfWindow = Math.floor(PREFETCH_WINDOW_SIZE / 2);
    const start = Math.max(0, centerIndex - halfWindow);
    const end = Math.min(ctData.length - 1, centerIndex + halfWindow);

    for (let idx = start; idx <= end; idx += 1) {
        prefetchSlice(idx);
    }
    prefetchSlice(centerIndex);
}

function getCoverTransform(canvasWidth, canvasHeight, sliceWidth, sliceHeight, zoomLevel, panOffset) {
    const baseScale = Math.max(canvasWidth / sliceWidth, canvasHeight / sliceHeight);
    const scale = baseScale * zoomLevel;
    const scaledWidth = sliceWidth * scale;
    const scaledHeight = sliceHeight * scale;
    const x = (canvasWidth - scaledWidth) / 2 + panOffset.x;
    const y = (canvasHeight - scaledHeight) / 2 + panOffset.y;
    return { scale, scaledWidth, scaledHeight, x, y };
}

const windowLevelPresets = {
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

    syncCanvasSize(canvas1);
    syncCanvasSize(canvas2);

    const totalSlicesEl = document.getElementById('totalSlices');
    if (totalSlicesEl) totalSlicesEl.textContent = ctData.length;

    const currentSliceEl = document.getElementById('currentSlice');
    if (currentSliceEl) currentSliceEl.textContent = currentSliceIndex + 1;

    const sliceSlider = document.getElementById('sliceSlider');
    if (sliceSlider) {
        sliceSlider.max = Math.max(ctData.length - 1, 0);
        sliceSlider.value = currentSliceIndex;
    }

    const rowCheckboxes = document.querySelectorAll('.roi-rating-include');
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
    prefetchSliceWindow(currentSliceIndex);
    setupMouseHandlers();
    updateZoomDisplays();

    window.addEventListener('resize', () => {
        const changed1 = syncCanvasSize(canvas1);
        const changed2 = syncCanvasSize(canvas2);
        if (changed1 || changed2) {
            displaySlice();
        }
    });
}

async function displaySlice() {
    const canvas1 = document.getElementById('ctViewer1');
    const canvas2 = document.getElementById('ctViewer2');
    if (!canvas1 || !canvas2) return;
    const ctx1 = canvas1.getContext('2d');
    const ctx2 = canvas2.getContext('2d');

    syncCanvasSize(canvas1);
    syncCanvasSize(canvas2);

    const canvas1CssWidth = Math.max(1, Math.floor(canvas1.offsetWidth));
    const canvas1CssHeight = Math.max(1, Math.floor(canvas1.offsetHeight));
    const canvas2CssWidth = Math.max(1, Math.floor(canvas2.offsetWidth));
    const canvas2CssHeight = Math.max(1, Math.floor(canvas2.offsetHeight));

    ctx1.save();
    ctx1.setTransform(1, 0, 0, 1, 0, 0);
    ctx1.clearRect(0, 0, canvas1.width, canvas1.height);
    ctx1.fillStyle = '#000';
    ctx1.fillRect(0, 0, canvas1.width, canvas1.height);
    ctx1.restore();

    ctx2.save();
    ctx2.setTransform(1, 0, 0, 1, 0, 0);
    ctx2.clearRect(0, 0, canvas2.width, canvas2.height);
    ctx2.fillStyle = '#000';
    ctx2.fillRect(0, 0, canvas2.width, canvas2.height);
    ctx2.restore();

    if (!ctData.length) return;

    const currentSliceEl = document.getElementById('currentSlice');
    if (currentSliceEl) currentSliceEl.textContent = currentSliceIndex + 1;
    const sliceSlider = document.getElementById('sliceSlider');
    if (sliceSlider) sliceSlider.value = currentSliceIndex;
    updateSliceInfo();
    await Promise.all([
        displayCTSlice(ctx1, canvas1CssWidth, canvas1CssHeight, ctData[currentSliceIndex], zoomLevel1, panOffset1),
        displayCTSlice(ctx2, canvas2CssWidth, canvas2CssHeight, ctData[currentSliceIndex], zoomLevel2, panOffset2)
    ]);

    drawROIOverlays(ctx1, canvas1CssWidth, canvas1CssHeight, rt1Contours, ctData[currentSliceIndex], zoomLevel1, panOffset1);
    drawROIOverlays(ctx2, canvas2CssWidth, canvas2CssHeight, rt2Contours, ctData[currentSliceIndex], zoomLevel2, panOffset2);

    updateZoomDisplays();
    prefetchSliceWindow(currentSliceIndex);
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

const pixelCache = new Map();
const loadingSlices = new Map();
const PIXEL_CACHE_LIMIT = 64;
const PREFETCH_WINDOW_SIZE = 10;

function cachePixels(sliceIndex, pixels) {
    if (pixelCache.has(sliceIndex)) {
        pixelCache.set(sliceIndex, pixels);
        return;
    }
    if (pixelCache.size >= PIXEL_CACHE_LIMIT) {
        const oldestKey = pixelCache.keys().next().value;
        if (oldestKey !== undefined) {
            pixelCache.delete(oldestKey);
        }
    }
    pixelCache.set(sliceIndex, pixels);
}

function extractRawPixels(dataSet) {
    const pixelDataElement = dataSet.elements.x7fe00010;
    if (!pixelDataElement) {
        throw new Error('Pixel data element (7FE0,0010) missing');
    }
    if (pixelDataElement.encapsulatedPixelData) {
        throw new Error('Encapsulated (compressed) pixel data is not supported yet');
    }
    const bytesPerSample = 2;
    const numPixels = pixelDataElement.length / bytesPerSample;
    const byteArray = dataSet.byteArray;
    const offset = pixelDataElement.dataOffset;
    const rawPixels = new Uint16Array(numPixels);
    const source = new DataView(byteArray.buffer, offset, pixelDataElement.length);

    for (let i = 0; i < numPixels; i += 1) {
        rawPixels[i] = source.getUint16(i * bytesPerSample, true);
    }
    return rawPixels;
}

async function fetchAndDecodeSlice(slice) {
    const response = await fetch(slice.url);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

    const arrayBuffer = await response.arrayBuffer();
    const byteArray = new Uint8Array(arrayBuffer);
    const dataSet = dicomParser.parseDicom(byteArray);
    const rawPixels = extractRawPixels(dataSet);

    const pixels = new Float32Array(rawPixels.length);
    const slope = slice.slope || 1;
    const intercept = slice.intercept || 0;

    for (let i = 0; i < rawPixels.length; i += 1) {
        pixels[i] = (rawPixels[i] * slope) + intercept;
    }

    return pixels;
}

async function ensureSlicePixels(slice) {
    const cached = pixelCache.get(slice.index);
    if (cached) return cached;

    let inflight = loadingSlices.get(slice.index);
    if (!inflight) {
        inflight = (async () => {
            const decoded = await fetchAndDecodeSlice(slice);
            cachePixels(slice.index, decoded);
        })();
        loadingSlices.set(slice.index, inflight);
    }

    try {
        await inflight;
    } finally {
        if (loadingSlices.get(slice.index) === inflight) {
            loadingSlices.delete(slice.index);
        }
    }

    return pixelCache.get(slice.index);
}

async function displayCTSlice(ctx, canvasWidth, canvasHeight, slice, zoomLevel = 1.0, panOffset = { x: 0, y: 0 }) {
    if (!slice || !slice.url) {
        console.warn("Invalid slice or missing URL");
        return;
    }

    let pixels;
    try {
        pixels = await ensureSlicePixels(slice);
    } catch (err) {
        console.error("DICOM Fetch Error:", err);
        return;
    }

    const imageData = ctx.createImageData(slice.width, slice.height);
    const windowWidth = currentWindow;
    const windowLevel = currentLevel;
    const minValue = windowLevel - windowWidth / 2;
    const maxValue = windowLevel + windowWidth / 2;
    const range = maxValue - minValue || 1;

    for (let i = 0; i < pixels.length; i++) {
        const val = pixels[i];
        let displayValue = ((val - minValue) / range) * 255;
        displayValue = Math.max(0, Math.min(255, displayValue));
        const idx = i * 4;
        imageData.data[idx] = displayValue;     // R
        imageData.data[idx + 1] = displayValue; // G
        imageData.data[idx + 2] = displayValue; // B
        imageData.data[idx + 3] = 255;          // A
    }

    if (!_tempCanvas) {
        _tempCanvas = document.createElement('canvas');
        _tempCtx = _tempCanvas.getContext('2d');
    }
    _tempCanvas.width = slice.width;
    _tempCanvas.height = slice.height;
    _tempCtx.putImageData(imageData, 0, 0);

    const t = getCoverTransform(canvasWidth, canvasHeight, slice.width, slice.height, zoomLevel, panOffset);
    ctx.drawImage(_tempCanvas, 0, 0, slice.width, slice.height, t.x, t.y, t.scaledWidth, t.scaledHeight);
}

function drawROIOverlays(ctx, canvasWidth, canvasHeight, rtstructContours, currentSlice, zoomLevel = 1.0, panOffset = { x: 0, y: 0 }) {
    ctx.globalAlpha = 0.7;

    const selectedROIsArray = Array.from(selectedROIs);

    const pixelSpacing = currentSlice.pixel_spacing || [1.0, 1.0];
    const imagePosition = currentSlice.image_position || [0, 0, 0];

    const t = getCoverTransform(
        canvasWidth,
        canvasHeight,
        currentSlice.width,
        currentSlice.height,
        zoomLevel,
        panOffset,
    );
    const baseX = t.x;
    const baseY = t.y;
    const scale = t.scale;

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

                const pixelX = (x - imagePosition[0]) / pixelSpacing[1];
                const pixelY = (y - imagePosition[1]) / pixelSpacing[0];

                const screenX = baseX + (pixelX * scale);
                const screenY = baseY + (pixelY * scale);
                return [screenX, screenY];
            });

            if (points2D.length >= 3) {
                ctx.beginPath();
                ctx.moveTo(points2D[0][0], points2D[0][1]);
                for (let i = 1; i < points2D.length; i += 1) {
                    ctx.lineTo(points2D[i][0], points2D[i][1]);
                }
                ctx.closePath();
                ctx.stroke();

                ctx.fillStyle = color;
                ctx.font = '12px Arial';
                const labelX = points2D[0][0];
                const labelY = Math.max(10, points2D[0][1] - 5);
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
        zoomLevel1 = Math.max(0.5, Math.min(5.0, newLevel));
    } else {
        zoomLevel2 = Math.max(0.5, Math.min(5.0, newLevel));
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
        zoomLevel1 = 1;
        panOffset1 = { x: 0, y: 0 };
    } else {
        zoomLevel2 = 1;
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
    zoomLevel1 = 1;
    zoomLevel2 = 1;
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

const initializePage = () => {
    initializeViewer();
    if (window.Loader && typeof window.Loader.hide === 'function') {
        window.Loader.hide();
    }
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializePage);
} else {
    initializePage();
}

