// Rival watch (Game Day): the panel is rendered by the server; this only writes the rivalry-week issue.

import { applyTeamColors } from './utils.js';
import { wireColumn } from './columns.js';

export function initRivals() {
    document.querySelectorAll('.rival-watch').forEach(panel => applyTeamColors(panel));
    wireColumn({ buttonId: 'rivalry_generate', statusId: 'rivalry_status', titleId: 'rivalry_title', bodyId: 'rivalry_body',
                 url: '/rivals/issue/generate', label: 'The rivalry issue', working: 'Writing the rivalry issue...' });
}
