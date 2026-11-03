// Magazine columns (Heisman Watch, recruiting story, rivalry issue): one "Write / Rewrite" button flow for all of them.

import { esc, setStatus, postJSON } from './utils.js';
import { longJob } from './notify.js';

/** A column's paragraphs as magazine copy, the first with a drop cap. */
export function columnParagraphs(paragraphs) {
    return paragraphs.map((p, i) => '<p' + (i === 0 ? ' class="mag-dropcap"' : '') + '>' + esc(p) + '</p>').join('');
}

/**
 * Wires a column's button: posts to `url`, announces the finish as `label`, and shows the column in `titleId` /
 * `bodyId` (or hands it to `render` when the page needs more than that).
 */
export function wireColumn({ buttonId, statusId, titleId, bodyId, url, label, working, render }) {
    const button = document.getElementById(buttonId);
    if (!button) return;
    const status = document.getElementById(statusId);
    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, working);
        try {
            const data = await longJob(label, postJSON(url));
            if (data.error) throw new Error(data.error);
            if (render) {
                render(data.column);
            } else {
                document.getElementById(titleId).textContent = data.column.title;
                document.getElementById(bodyId).innerHTML = columnParagraphs(data.column.paragraphs);
                button.textContent = button.textContent.replace(/^Write/, 'Rewrite');
            }
            setStatus(status, '');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            button.disabled = false;
        }
    });
}
