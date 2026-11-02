// Locker Room: storyline tracker cards and their buttons.

import { esc, postJSON, setStatus } from './utils.js';

const TYPE_LABELS = { battle: 'Position Battle', pressure: 'Under Pressure', hype: 'Hype', comeback: 'Comeback', recruit: 'Recruit Pressure' };

function castRow(member) {
    const injured = member.health_status && member.health_status !== 'Healthy';
    let html =
        '<div class="cast-head">' +
            '<span><span class="cast-role">' + esc(member.role) + '</span>' +
            '<span class="cast-name">' + (member.jersey !== null ? '#' + esc(member.jersey) + ' ' : '') + esc(member.name) + '</span></span>' +
            '<span class="cast-slot">' + esc(member.slot) +
                (member.health_status ? ' &middot; <span class="' + (injured ? 'health-injured' : '') + '">' + esc(member.health_status) + '</span>' : '') +
            '</span>' +
        '</div>';
    if (member.stat_line) {
        html += '<div class="cast-stats">Wk ' + esc(member.stat_week) + ': ' + esc(member.stat_line) + '</div>';
    }
    return '<div class="cast-row">' + html + '</div>';
}

function makeButton(label, onClick) {
    const button = document.createElement('button');
    button.textContent = label;
    button.addEventListener('click', onClick);
    return button;
}

function storylineCard(storyline, isActive) {
    const card = document.createElement('div');
    card.className = 'storyline-card type-' + storyline.storyline_type + (isActive ? '' : ' resolved');
    const span = isActive ? 'Since Week ' + esc(storyline.start_week) : 'Week ' + esc(storyline.start_week) + '&ndash;' + esc(storyline.end_week);
    let html =
        '<div class="storyline-topline"><span class="type-badge">' + esc(TYPE_LABELS[storyline.storyline_type] || storyline.storyline_type) + '</span><span>' + span + '</span></div>' +
        '<div class="storyline-title">' + esc(storyline.title) + '</div>';
    if (storyline.trigger_text) {
        html += '<div class="storyline-trigger">Sparked by Week ' + esc(storyline.source_week) + ': ' + esc(storyline.trigger_text) + '</div>';
    }
    storyline.cast.forEach(member => { html += castRow(member); });

    html += '<div class="storyline-timeline">';
    storyline.chapters.forEach(chapter => {
        html += '<div class="storyline-chapter"><span class="storyline-chapter-week">Week ' + esc(chapter.week_num) + '</span>' + esc(chapter.chapter_text) + '</div>';
    });
    if (!isActive) {
        html += '<div class="storyline-chapter final"><span class="storyline-chapter-week">Final</span>' + esc(storyline.finale_text || storyline.resolution) + '</div>';
    }
    html += '</div>';
    card.innerHTML = html;

    if (isActive) {
        const actions = document.createElement('div');
        actions.className = 'storyline-actions';
        if (storyline.depth_action_label) {
            actions.appendChild(makeButton(storyline.depth_action_label, () => resolveStoryline(storyline.storyline_id, 'depth_change')));
        }
        actions.appendChild(makeButton('End Storyline', () => resolveStoryline(storyline.storyline_id, 'end')));
        card.appendChild(actions);
    }
    return card;
}

function grid(storylines, isActive) {
    const element = document.createElement('div');
    element.className = 'tracker-grid';
    storylines.forEach(storyline => element.appendChild(storylineCard(storyline, isActive)));
    return element;
}

export function renderStorylines(data) {
    const list = document.getElementById('storyline_list');
    list.innerHTML = '';
    if (data.active.length === 0) {
        list.innerHTML = '<div class="storyline-empty">No active storylines. Build them from the last game, or start a random one.</div>';
    } else {
        list.appendChild(grid(data.active, true));
    }
    if (data.resolved.length > 0) {
        const concluded = document.createElement('details');
        concluded.className = 'storyline-concluded';
        concluded.innerHTML = '<summary>Concluded storylines (' + data.resolved.length + ')</summary>';
        concluded.appendChild(grid(data.resolved, false));
        list.appendChild(concluded);
    }
}

/** Sends a storyline request with every tracker button disabled, then re-renders the tracker. */
async function storylineRequest(url, body, pendingText) {
    const status = document.getElementById('storyline_status');
    const buttons = () => document.querySelectorAll('.tracker button');
    buttons().forEach(button => { button.disabled = true; });
    setStatus(status, pendingText);
    try {
        const data = await postJSON(url, body);
        setStatus(status, data.error || data.message, Boolean(data.error));
        if (data.storylines) renderStorylines(data.storylines);
    } catch (err) {
        setStatus(status, 'Request failed: ' + err, true);
    } finally {
        buttons().forEach(button => { button.disabled = false; });
    }
}

function resolveStoryline(storylineId, action) {
    storylineRequest('/storylines/' + storylineId + '/resolve', { action }, 'Writing the final chapter...');
}

export function initStorylines(data) {
    document.getElementById('game_storyline_btn')?.addEventListener('click',
        () => storylineRequest('/storylines/from-game', {}, 'Reading the game and writing storylines (one AI call each)...'));
    document.getElementById('new_storyline_btn').addEventListener('click',
        () => storylineRequest('/storylines', {}, 'Writing a new storyline...'));
    renderStorylines(data);
}
