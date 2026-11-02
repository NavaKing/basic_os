// Rival watch (Game Day): the panel is rendered by the server; this only writes the rivalry-week issue.

import { esc, setStatus, postJSON, applyTeamColors } from './utils.js';
import { longJob } from './notify.js';

export function initRivals() {
    document.querySelectorAll('.rival-watch').forEach(panel => applyTeamColors(panel));
    const button = document.getElementById('rivalry_generate');
    if (!button) return;
    const status = document.getElementById('rivalry_status');
    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, 'Writing the rivalry issue...');
        try {
            const data = await longJob('The rivalry issue', postJSON('/rivals/issue/generate'));
            if (data.error) throw new Error(data.error);
            document.getElementById('rivalry_title').textContent = data.column.title;
            document.getElementById('rivalry_body').innerHTML = data.column.paragraphs
                .map((p, i) => '<p' + (i === 0 ? ' class="mag-dropcap"' : '') + '>' + esc(p) + '</p>').join('');
            button.textContent = 'Rewrite the rivalry issue';
            setStatus(status, '');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            button.disabled = false;
        }
    });
}
