// Finish notifications: a long job (hub generator, podcast, coach quotes, columns...) announces when it's done, so you
// can work in another tab or window meanwhile. There's always a toast in the page; when the page isn't visible, a
// desktop notification too (once you've allowed them) and a note in the browser tab's title.

const TOAST_MS = 8000;
const baseTitle = document.title;

function toastBox() {
    let box = document.getElementById('toasts');
    if (!box) {
        box = document.createElement('div');
        box.id = 'toasts';
        box.className = 'toasts';
        box.setAttribute('role', 'status');
        box.setAttribute('aria-live', 'polite');
        document.body.appendChild(box);
    }
    return box;
}

function toast(message, isError) {
    const item = document.createElement('div');
    item.className = 'toast' + (isError ? ' toast--error' : '');
    item.textContent = message;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.addEventListener('click', () => item.remove());
    item.appendChild(close);
    toastBox().appendChild(item);
    setTimeout(() => item.remove(), TOAST_MS);
}

function desktop(title, body) {
    if (!('Notification' in window) || Notification.permission !== 'granted' || !document.hidden) return;
    const note = new Notification(title, { body, tag: 'basic-os' });
    note.addEventListener('click', () => { window.focus(); note.close(); });
}

function flagTitle(word) {
    if (!document.hidden) return;
    document.title = '(' + word + ') ' + baseTitle;
    document.addEventListener('visibilitychange', () => { document.title = baseTitle; }, { once: true });
}

function finish(label, error) {
    toast(error ? label + ' failed: ' + error : label + ' is ready.', Boolean(error));
    desktop(error ? label + ' failed' : label + ' is ready', error || 'Switch back to BASIC_OS to see it.');
    flagTitle(error ? 'Failed' : 'Ready');
}

/** A quick notification (a new chat message): a toast, plus a desktop notification when the page isn't visible. */
export function notify(title, body) {
    toast(title + ': ' + body, false);
    desktop(title, body);
}

/**
 * Awaits a long job's request and announces the outcome. Call it straight from the click handler, so the browser
 * can ask (once) whether desktop notifications are allowed. Returns the job's data, or rethrows its error.
 */
export async function longJob(label, request) {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => { /* no notifications: the toast still shows */ });
    }
    try {
        const data = await request;
        finish(label, data && data.error ? String(data.error) : null);
        return data;
    } catch (err) {
        finish(label, String(err.message || err));
        throw err;
    }
}
