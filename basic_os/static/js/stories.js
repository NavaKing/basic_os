// Story Column: hero banner, lead dispatch and the archive of earlier weeks.

import { esc, staticUrl } from './utils.js';

function renderHero(lead, game, teamName) {
    const image = document.getElementById('hero_image');
    if (lead && lead.image_path) {
        image.src = staticUrl(lead.image_path);
        image.hidden = false;
    } else {
        image.removeAttribute('src');
        image.hidden = true;
    }
    const week = lead ? lead.week_num : (game ? game.week_id : null);
    document.getElementById('hero_kicker').textContent = week ? 'Week ' + week + ' Dispatch' : 'The Dispatch';
    document.getElementById('hero_title').textContent = teamName + ' vs ' + (lead ? lead.opponent_name : (game ? game.opponent_name : 'TBD'));
    document.getElementById('hero_note').textContent = lead && lead.image_path ? '' : 'The banner photo renders with the next hub generation.';
}

function archiveEntry(story) {
    return '<div class="history-box">' +
        (story.image_path ? '<img class="history-thumb" src="' + esc(staticUrl(story.image_path)) + '" alt="">' : '') +
        '<div><div class="section-label">Week ' + esc(story.week_num) + ' vs ' + esc(story.opponent_name) + '</div>' + esc(story.generated_text) + '</div>' +
    '</div>';
}

/** stories are newest first; the first one is the lead. */
export function renderStories(stories, game, teamName = 'Our team') {
    const lead = stories && stories.length ? stories[0] : null;
    renderHero(lead, game, teamName);

    document.getElementById('lead_story').innerHTML = lead
        ? '<p>' + esc(lead.generated_text) + '</p>'
        : '<div class="empty-note">No dispatch yet. Click Execute Hub Generator to write this week\'s story.</div>';

    const older = (stories || []).slice(1);
    document.getElementById('history_feed_list').innerHTML = older.length
        ? older.map(archiveEntry).join('')
        : '<div class="empty-note empty-note--compact">Earlier weeks\' stories will collect here.</div>';
}
