window.Loader = window.Loader || {
    show: () => {
        const el = document.getElementById('page-loader');
        if (!el) return;
        el.classList.remove('loader-hidden');
    },
    hide: () => {
        const el = document.getElementById('page-loader');
        if (!el) return;
        setTimeout(() => {
            el.classList.add('loader-hidden');
        }, 500);
    }
};

window.addEventListener('load', () => {
    if (window.Loader && typeof window.Loader.hide === 'function') {
        window.Loader.hide();
    }
});
