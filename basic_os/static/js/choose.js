// The dynasty chooser: shown every time the app opens. The pick is remembered for this browser tab, so the main page
// knows it was chosen here (see dynastyChosen in main.js).

import { TAB_KEY } from './choose-key.js';

function remember(name) {
    try { sessionStorage.setItem(TAB_KEY, name); } catch (err) { /* private window: the server still knows */ }
}

async function pick(body, button) {
    const error = document.getElementById('choose_error');
    if (button) { button.disabled = true; button.textContent = 'Loading...'; }
    try {
        const response = await fetch('/choose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not load that dynasty.');
        remember(data.current.name);
        location.replace('/');
    } catch (err) {
        if (error) { error.textContent = err.message; error.hidden = false; }
        if (button) { button.disabled = false; button.textContent = 'Load dynasty'; }
    }
}

const form = document.getElementById('choose_form');
if (form) {
    form.addEventListener('submit', event => {
        event.preventDefault();
        const chosen = form.querySelector('input[name="save"]:checked');
        if (chosen) pick({ name: chosen.value }, document.getElementById('choose_load'));
    });
    form.addEventListener('change', () => {
        form.querySelectorAll('.choose-save').forEach(label => label.classList.toggle('is-picked', label.querySelector('input').checked));
    });
    form.dispatchEvent(new Event('change'));
}
const keep = document.getElementById('choose_keep');
if (keep) keep.addEventListener('click', () => pick({ keep: true }, keep));
