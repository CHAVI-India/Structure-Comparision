document.addEventListener('DOMContentLoaded', function () {
    const filterForm = document.querySelector('.filter-bar');
    const resultsContainer = document.getElementById('patients-results');
    const headerStats = document.getElementById('header_stats');
    const groupFilter = document.getElementById('group_filter');
    const feedbackFilter = document.getElementById('feedback_status_filter');
    const searchInput = document.getElementById('patient_search');
    const clearButton = document.getElementById('clear_search');
    let searchTimeout = null;
    let activeController = null;

    const toggleClearButton = () => {
        if (!clearButton || !searchInput) return;
        clearButton.style.display = searchInput.value ? 'flex' : 'none';
    };

    const buildQueryString = (pageNumber = null) => {
        const params = new URLSearchParams();
        if (filterForm) {
            const formData = new FormData(filterForm);
            formData.forEach((value, key) => {
                if (value) {
                    params.append(key, value);
                }
            });
        }
        if (pageNumber) {
            params.set('page', pageNumber);
        }
        return params.toString();
    };

    const updateFromResponse = (html) => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        const nextResults = doc.getElementById('patients-results');
        const nextHeaderStats = doc.getElementById('header_stats');

        if (nextResults && resultsContainer) {
            resultsContainer.innerHTML = nextResults.innerHTML;
        }
        if (nextHeaderStats && headerStats) {
            headerStats.innerHTML = nextHeaderStats.innerHTML;
        }
    };

    const runSearch = (pageNumber = null) => {
        if (!filterForm) return;
        const queryString = buildQueryString(pageNumber);
        const baseUrl = filterForm.getAttribute('action') || window.location.pathname;
        const targetUrl = queryString ? `${baseUrl}?${queryString}` : baseUrl;
        const shouldRestoreFocus = document.activeElement === searchInput;
        const selection = searchInput
            ? { start: searchInput.selectionStart, end: searchInput.selectionEnd }
            : null;

        if (activeController) {
            activeController.abort();
        }
        activeController = new AbortController();

        fetch(targetUrl, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            signal: activeController.signal,
        })
            .then((response) => response.text())
            .then((html) => {
                updateFromResponse(html);
                window.history.replaceState(null, '', targetUrl);
                if (shouldRestoreFocus && searchInput) {
                    searchInput.focus({ preventScroll: true });
                    if (selection && typeof selection.start === 'number') {
                        searchInput.setSelectionRange(selection.start, selection.end);
                    }
                }
            })
            .catch((error) => {
                if (error.name !== 'AbortError') {
                    console.warn('Search update failed', error);
                }
            });
    };

    if (filterForm) {
        filterForm.addEventListener('submit', function (event) {
            event.preventDefault();
            runSearch();
        });
    }

    if (groupFilter) {
        groupFilter.addEventListener('change', function () {
            runSearch();
        });
    }

    if (feedbackFilter) {
        feedbackFilter.addEventListener('change', function () {
            runSearch();
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', function () {
            toggleClearButton();
            if (searchTimeout) {
                clearTimeout(searchTimeout);
            }
            searchTimeout = setTimeout(() => runSearch(), 400);
        });
    }

    if (clearButton && searchInput) {
        clearButton.addEventListener('click', function () {
            searchInput.value = '';
            toggleClearButton();
            searchInput.focus();
            runSearch();
        });
    }

    if (resultsContainer) {
        resultsContainer.addEventListener('click', function (event) {
            const link = event.target.closest('.pagination a.page-link');
            if (!link) return;
            event.preventDefault();
            const url = new URL(link.href);
            const page = url.searchParams.get('page');
            runSearch(page);
        });
    }

    toggleClearButton();
});