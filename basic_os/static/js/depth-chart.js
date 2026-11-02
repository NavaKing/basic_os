// Depth Chart: the full roster, filtered by the position combo box.

import { esc } from './utils.js';

const STATUS_CLASSES = { Out: 'status-out', Doubtful: 'status-out', Questionable: 'status-questionable', Probable: 'status-probable' };
const COLUMN_COUNT = 8;

function statusChip(status) {
    const cls = STATUS_CLASSES[status];
    return cls
        ? '<span class="status-chip ' + cls + '">' + esc(status) + '</span>'
        : '<span class="status-healthy">' + esc(status || 'Healthy') + '</span>';
}

function sizeText(player) {
    if (!player.height_in) return '';
    return Math.floor(player.height_in / 12) + "'" + (player.height_in % 12) + '" / ' + esc(player.weight_lb);
}

function playerRow(player) {
    const starter = /^[A-Z]+1$/.test(player.depth_slot || '');
    return '<tr class="' + (starter ? 'starter-row' : '') + '">' +
        '<td class="slot-cell">' + esc(player.depth_slot) + '</td>' +
        '<td>' + esc(player.jersey_num) + '</td>' +
        '<td class="name-cell">' + (player.portrait ? '<span class="headshot"><img src="' + esc(player.portrait) + '" alt="" loading="lazy"></span>' : '') +
            '<strong>' + esc(player.player_name) + '</strong></td>' +
        '<td>' + esc(player.class_year) + '</td>' +
        '<td class="muted nowrap">' + sizeText(player) + '</td>' +
        '<td class="ovr">' + esc(player.overall) + '</td>' +
        '<td>' + statusChip(player.health_status) + '</td>' +
        '<td class="stat-cell">' + (esc(player.stat_line) || '<span class="muted">&mdash;</span>') + '</td>' +
    '</tr>';
}

function render(players, position) {
    const shown = players.filter(p => position === 'ALL' || p.position === position);
    let html = '';
    let currentGroup = null;
    shown.forEach(player => {
        // "All positions" gets a heading row per position group
        if (position === 'ALL' && player.position !== currentGroup) {
            currentGroup = player.position;
            html += '<tr class="group-row"><td colspan="' + COLUMN_COUNT + '">' + esc(player.position) + ' &middot; ' + esc(player.position_name) + '</td></tr>';
        }
        html += playerRow(player);
    });
    document.getElementById('depth_chart_body').innerHTML = html || '<tr><td colspan="' + COLUMN_COUNT + '" class="empty-note">No players at this position.</td></tr>';
    document.getElementById('depth_count').textContent = shown.length + ' player' + (shown.length === 1 ? '' : 's');
}

export function initDepthChart(players, defaultPosition = 'QB') {
    const select = document.getElementById('position_select');
    if ([...select.options].some(option => option.value === defaultPosition)) select.value = defaultPosition;
    select.addEventListener('change', () => render(players, select.value));
    render(players, select.value);
}
