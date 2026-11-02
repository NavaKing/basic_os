// Team page: clicking anything with data-team-id (logos, team chips) opens that team's record,
// coaching staff, schedule, top players and poll history in a dialog.

import { esc, applyTeamColors } from './utils.js';

function logo(team, cls) {
    if (team.logo) return '<img class="' + cls + '" src="' + esc(team.logo) + '" alt="">';
    // No logo (FCS placeholder teams): a colour badge like the recap uses
    return '<span class="team-chip" data-color="' + esc(team.color || '') + '">' + esc(team.short || '') + '</span>';
}

function headshot(url) {
    return '<span class="headshot">' + (url ? '<img src="' + esc(url) + '" alt="" loading="lazy">' : '') + '</span>';
}

function staffList(staff) {
    if (!staff.length) return '';
    return '<div class="team-staff">' + staff.map(member =>
        '<div class="team-staff-member">' + headshot(member.portrait) +
            '<div><div class="team-staff-name">' + esc(member.name) + '</div><div class="team-staff-role">' + esc(member.role) + '</div></div>' +
        '</div>').join('') + '</div>';
}

function scheduleTable(games) {
    if (!games.length) return '<div class="empty-note empty-note--compact">No games scheduled.</div>';
    return '<table class="team-schedule"><tbody>' + games.map(g => {
        const result = g.result
            ? '<span class="score ' + (g.result === 'W' ? 'score-win' : g.result === 'L' ? 'score-loss' : '') + '">' + esc(g.result) + ' ' + esc(g.score) + '</span>'
            : '<span class="muted">&mdash;</span>';
        return '<tr><td class="muted">Wk ' + esc(g.week) + '</td><td class="nowrap">' + esc(g.venue) + ' ' +
            '<span class="team-link" data-team-id="' + esc(g.opponent.id) + '">' + logo(g.opponent, 'team-logo team-logo--sm') +
            (g.opponent.rank ? '<span class="team-rank">#' + esc(g.opponent.rank) + '</span> ' : '') + esc(g.opponent.name) + '</span></td>' +
            '<td class="team-schedule-result">' + result + '</td></tr>';
    }).join('') + '</tbody></table>';
}

function playerList(players) {
    if (!players.length) return '<div class="empty-note empty-note--compact">No stats recorded yet.</div>';
    return '<ul class="team-players">' + players.map(p =>
        '<li>' + headshot(p.portrait) +
            '<div class="team-player-id"><div class="team-player-name" data-player-id="' + esc(p.id) + '">' + esc(p.name) + '</div>' +
            '<div class="team-player-meta">#' + esc(p.jersey) + ' &middot; ' + esc(p.position) + ' &middot; ' + esc(p.class) + '</div></div>' +
            '<div class="stat-boxes stat-boxes--inline">' + p.boxes.map(b =>
                '<div class="stat-box"><div class="stat-box-value">' + esc(b.value) + '</div><div class="stat-box-label">' + esc(b.label) + '</div></div>').join('') + '</div>' +
        '</li>').join('') + '</ul>';
}

function pollHistory(polls) {
    if (!polls.length) return '<div class="empty-note empty-note--compact">No polls captured yet.</div>';
    return '<div class="team-polls">' + polls.map(p =>
        '<div class="team-poll"><div class="team-poll-rank">' + (p.rank ? '#' + esc(p.rank) : 'NR') + '</div>' +
        '<div class="team-poll-week">' + (p.week === 0 ? 'Preseason' : 'Wk ' + esc(p.week)) + '</div></div>').join('') + '</div>';
}

function render(dialog, t) {
    dialog.innerHTML =
        '<div class="team-dialog-hero" data-color="' + esc(t.color || '') + '">' +
            logo(t, 'team-dialog-logo') +
            '<div class="team-dialog-title">' +
                '<div class="team-dialog-kicker">' + (t.rank ? 'AP #' + esc(t.rank) + ' &middot; ' : '') + esc(t.record) + (t.is_user ? ' &middot; Your team' : '') + '</div>' +
                '<h2>' + esc(t.full_name) + '</h2>' +
                (t.stadium ? '<div class="team-dialog-stadium">' + esc(t.stadium) + '</div>' : '') +
            '</div>' +
            '<button class="team-dialog-close" type="button" aria-label="Close">&times;</button>' +
        '</div>' +
        staffList(t.staff) +
        '<div class="team-dialog-grid">' +
            '<section><h3>Schedule &amp; Results</h3>' + scheduleTable(t.schedule) + '</section>' +
            '<section><h3>Top Players</h3>' + playerList(t.players) + '<h3 class="team-polls-head">AP Poll History</h3>' + pollHistory(t.polls) + '</section>' +
        '</div>';
    applyTeamColors(dialog);
    dialog.querySelector('.team-dialog-close').addEventListener('click', () => dialog.close());
}

async function openTeam(dialog, teamId) {
    dialog.innerHTML = '<div class="empty-note">Loading team...</div>';
    if (!dialog.open) dialog.showModal();
    try {
        const res = await fetch('/team/' + encodeURIComponent(teamId));
        if (!res.ok) throw new Error('HTTP ' + res.status);
        render(dialog, await res.json());
        dialog.scrollTop = 0;
    } catch (err) {
        dialog.innerHTML = '<div class="empty-note">Could not load this team: ' + esc(String(err)) + '</div>';
    }
}

export function initTeamPages() {
    const dialog = document.getElementById('team_dialog');
    document.addEventListener('click', event => {
        if (event.target.closest('[data-player-id]')) return;  // a player inside a team element opens his profile instead
        const target = event.target.closest('[data-team-id]');
        if (target && target.dataset.teamId) openTeam(dialog, target.dataset.teamId);
    });
    // Click on the backdrop closes the dialog
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    // ?team=<id> opens a team page directly (a shareable link to it)
    const linked = new URLSearchParams(location.search).get('team');
    if (linked) openTeam(dialog, linked);
}
