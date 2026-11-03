// Tab bar. The active tab lives in the URL hash so a refresh keeps it.

const TABS = ['gameday', 'story', 'depth', 'locker', 'recap', 'recruiting', 'season', 'history', 'awards', 'offseason', 'coaches', 'podcast', 'phone'];

export function showTab(name) {
    if (!TABS.includes(name)) name = TABS[0];
    document.querySelectorAll('.tab').forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.tab === name)));
    document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.toggle('active', panel.id === 'tab-' + name));
    if (location.hash !== '#' + name) history.replaceState(null, '', '#' + name);
}

export function initTabs() {
    document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => showTab(tab.dataset.tab)));
    showTab(location.hash.slice(1));
}
