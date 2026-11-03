// Offseason tab: the page is rendered by the server; this only writes the Signing Day / class report story.

import { wireColumn } from './columns.js';

export function initOffseason() {
    wireColumn({ buttonId: 'sd_generate', statusId: 'sd_status', titleId: 'sd_title', bodyId: 'sd_body',
                 url: '/offseason/signing-day/generate', label: 'The recruiting story', working: 'Writing the story...' });
}
