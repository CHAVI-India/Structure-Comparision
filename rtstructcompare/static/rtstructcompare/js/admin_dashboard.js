
document.addEventListener('DOMContentLoaded', function () {
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

    const assignmentsCanvas = document.getElementById('assignmentsChart');
    const feedbackCanvas = document.getElementById('feedbackChart');
    const reviewDonutCanvas = document.getElementById('reviewDonut');
    const rangeLabel = document.getElementById('chart-range-label');

    if (!assignmentsCanvas || !feedbackCanvas || !reviewDonutCanvas || typeof Chart === 'undefined') {
        return;
    }

    const getCssVar = (name, fallback) => {
        const value = getComputedStyle(document.documentElement).getPropertyValue(name);
        return (value || '').trim() || fallback;
    };

    const colorInk = getCssVar('--dash-ink', '#0f172a');
    const colorAccent = getCssVar('--dash-accent', '#0f766e');
    const colorAccentStrong = getCssVar('--dash-accent-strong', '#115e59');

    Chart.defaults.color = 'rgba(15, 23, 42, 0.7)';

    const lineOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: { intersect: false, mode: 'index' },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: {
                    maxTicksLimit: 8,
                    color: 'rgba(15, 23, 42, 0.55)',
                },
            },
            y: {
                beginAtZero: true,
                grid: { color: 'rgba(148, 163, 184, 0.35)' },
                ticks: { color: 'rgba(15, 23, 42, 0.55)' },
            },
        },
    };

    const donutOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { position: 'bottom' },
        },
        cutout: '68%',
    };

    const createGradient = (ctx, height, start, end) => {
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, start);
        gradient.addColorStop(1, end);
        return gradient;
    };

    const assignmentsCtx = assignmentsCanvas.getContext('2d');
    const feedbackCtx = feedbackCanvas.getContext('2d');
    const reviewCtx = reviewDonutCanvas.getContext('2d');

    const assignmentsChart = new Chart(assignmentsCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Assignments',
                    data: [],
                    borderColor: colorAccentStrong,
                    backgroundColor: createGradient(assignmentsCtx, 140, 'rgba(15, 118, 110, 0.18)', 'rgba(15, 118, 110, 0.02)'),
                    fill: true,
                    tension: 0.35,
                    borderWidth: 2,
                    pointRadius: 0,
                },
            ],
        },
        options: lineOptions,
    });

    const feedbackChart = new Chart(feedbackCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Feedback updates',
                    data: [],
                    borderColor: 'rgba(14, 116, 144, 0.95)',
                    backgroundColor: createGradient(feedbackCtx, 140, 'rgba(56, 189, 248, 0.18)', 'rgba(56, 189, 248, 0.02)'),
                    fill: true,
                    tension: 0.35,
                    borderWidth: 2,
                    pointRadius: 0,
                },
            ],
        },
        options: lineOptions,
    });

    const reviewDonut = new Chart(reviewCtx, {
        type: 'doughnut',
        data: {
            labels: ['Reviewed', 'Pending'],
            datasets: [
                {
                    data: [0, 0],
                    backgroundColor: ['rgba(34, 197, 94, 0.85)', 'rgba(239, 68, 68, 0.75)'],
                    borderColor: ['rgba(34, 197, 94, 1)', 'rgba(239, 68, 68, 1)'],
                    borderWidth: 1,
                },
            ],
        },
        options: donutOptions,
    });

    const fetchChartData = async () => {
        try {
            const resp = await fetch('/admin/dashboard/charts/?range=30', { headers: { 'Accept': 'application/json' } });
            if (!resp.ok) {
                return;
            }
            const data = await resp.json();

            const labels = (data && data.labels) || [];
            const assignments = (data && data.assignments_by_day) || [];
            const feedback = (data && data.feedback_by_day) || [];
            const breakdown = (data && data.review_breakdown) || {};

            const rangeDays = (data && data.range_days) || 30;
            if (rangeLabel) {
                rangeLabel.textContent = String(rangeDays);
            }

            assignmentsChart.data.labels = labels;
            assignmentsChart.data.datasets[0].data = assignments;
            assignmentsChart.update();

            feedbackChart.data.labels = labels;
            feedbackChart.data.datasets[0].data = feedback;
            feedbackChart.update();

            reviewDonut.data.datasets[0].data = [breakdown.reviewed || 0, breakdown.pending || 0];
            reviewDonut.update();
        } catch (_err) {
            // Fail quietly; dashboard should still be usable without charts.
        }
    };

    fetchChartData();
});
