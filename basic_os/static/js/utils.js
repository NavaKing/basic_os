// Shared helpers for the page modules.

/** Escapes a value for safe insertion into HTML. */
export function esc(value) {
    const div = document.createElement('div');
    div.textContent = (value === null || value === undefined) ? '' : value;
    return div.innerHTML;
}

/** URL of a file under Flask's static folder (generated photos are stored as paths relative to it). */
export function staticUrl(path) {
    return '/static/' + encodeURI(path);
}

/** The AI model picked in the header. */
export function selectedModel() {
    return document.getElementById('model_select').value;
}

/** POSTs JSON (with the selected model added) and returns the parsed JSON response. */
export async function postJSON(url, body = {}) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: selectedModel(), ...body })
    });
    return res.json();
}

/** Shows a message in a .status-text element, red when it's an error. */
export function setStatus(element, text, isError = false) {
    element.textContent = text || '';
    element.classList.toggle('is-error', isError);
}

/** Sets --team-color from each element's data-color, so team colours need no inline styles in the markup. */
export function applyTeamColors(root = document) {
    root.querySelectorAll('[data-color]').forEach(el => {
        if (el.dataset.color) el.style.setProperty('--team-color', el.dataset.color);
    });
}
