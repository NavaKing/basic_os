// Offseason tab: the page is rendered by the server; this only writes the Signing Day / class report story.

import { esc, setStatus, postJSON } from './utils.js';
import { longJob } from './notify.js';

export function initOffseason() {
    const button = document.getElementById('sd_generate');
    if (!button) return;
    const status = document.getElementById('sd_status');
    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, 'Writing the story...');
        try {
            const data = await longJob('The recruiting story', postJSON('/offseason/signing-day/generate'));
            if (data.error) throw new Error(data.error);
            document.getElementById('sd_title').textContent = data.column.title;
            document.getElementById('sd_body').innerHTML = data.column.paragraphs
                .map((p, i) => '<p' + (i === 0 ? ' class="mag-dropcap"' : '') + '>' + esc(p) + '</p>').join('');
            button.textContent = button.textContent.replace(/^Write/, 'Rewrite');
            setStatus(status, '');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            button.disabled = false;
        }
    });
}
