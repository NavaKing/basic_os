// Box score: clicking a played game (anything with data-game-id) opens its line score, team stats, top performers
// and scoring plays in a dialog.

import { esc, applyTeamColors, teamLogo, headshot } from './utils.js';

function lineScore(teams) {
    const quarters = Math.max(4, ...teams.map(t => t.quarters.length));
    return '<table class="box-score gm-line"><thead><tr><th></th>' +
        Array.from({ length: quarters }, (_, i) => '<th>' + (i < 4 ? 'Q' + (i + 1) : 'OT') + '</th>').join('') + '<th>T</th></tr></thead><tbody>' +
        teams.map(t => '<tr class="' + (t.won ? 'box-winner' : '') + '"><td class="gm-team">' + teamLogo(t.team) +
            (t.team.rank ? '<span class="team-rank">#' + esc(t.team.rank) + '</span> ' : '') + esc(t.team.name) + '</td>' +
            Array.from({ length: quarters }, (_, i) => '<td class="box-num">' + esc(t.quarters[i] ?? 0) + '</td>').join('') +
            '<td class="box-num box-total">' + esc(t.total) + '</td></tr>').join('') +
        '</tbody></table>';
}

function teamStats(rows, teams) {
    if (!rows.length) return '<p class="muted">The save has no team stats for this game.</p>';
    return '<table class="gm-stats"><thead><tr><th>' + esc(teams[0].team.short) + '</th><th></th><th>' + esc(teams[1].team.short) + '</th></tr></thead><tbody>' +
        rows.map(r => '<tr><td class="' + (r.better === 'away' ? 'gm-better' : '') + '">' + esc(r.away) + '</td>' +
            '<td class="gm-stat-label">' + esc(r.label) + '</td>' +
            '<td class="' + (r.better === 'home' ? 'gm-better' : '') + '">' + esc(r.home) + '</td></tr>').join('') +
        '</tbody></table>';
}

function performers(team) {
    const list = team.performers.length ? team.performers.map(p =>
        '<li>' + headshot(p.portrait) +
            '<div><div class="gm-perf-label">' + esc(p.label) + '</div>' +
            '<div class="gm-perf-name" data-player-id="' + esc(p.id) + '">' + esc(p.name) + ' <span class="muted">' + esc(p.position) + '</span></div>' +
            '<div class="gm-perf-line">' + esc(p.line) + '</div></div></li>').join('')
        : '<li class="muted">Player stats for this week appear once the save moves on to the next week.</li>';
    return '<section class="gm-perf"><h4>' + teamLogo(team.team) + esc(team.team.name) + '</h4><ul>' + list + '</ul></section>';
}

function scoring(plays, note) {
    if (!plays) return '';
    return '<section class="pp-section"><h3>Scoring plays</h3>' + (note ? '<p class="gm-note">' + esc(note) + '</p>' : '') +
        '<ol class="gm-scoring">' + plays.map(p =>
        '<li><span class="gm-when">' + (p.quarter === 5 ? 'OT' : 'Q' + esc(p.quarter)) + ' &middot; ' + esc(p.clock) + '</span>' +
        '<span class="gm-who">' + esc(p.team) + '</span>' + esc(p.text) + '</li>').join('') + '</ol></section>';
}

function render(dialog, g) {
    const [away, home] = g.teams;
    dialog.innerHTML =
        '<div class="gm-head">' +
            '<div class="team-dialog-kicker">' + (g.postseason ? 'Postseason' : 'Week ' + esc(g.week)) + ' &middot; Final</div>' +
            '<h2>' + esc(away.team.name) + ' ' + esc(away.total) + ', ' + esc(home.team.name) + ' ' + esc(home.total) + '</h2>' +
            '<button class="team-dialog-close" type="button" aria-label="Close">&times;</button>' +
        '</div>' +
        '<div class="pp-body">' +
            lineScore(g.teams) +
            '<section class="pp-section"><h3>Team stats</h3>' + teamStats(g.stats, g.teams) + '</section>' +
            '<section class="pp-section"><h3>Top performers</h3><div class="gm-perfs">' + performers(away) + performers(home) + '</div></section>' +
            scoring(g.scoring, g.scoring_note) +
        '</div>';
    applyTeamColors(dialog);
    dialog.querySelector('.team-dialog-close').addEventListener('click', () => dialog.close());
}

async function openGame(dialog, gameId) {
    dialog.innerHTML = '<div class="empty-note">Loading box score...</div>';
    if (!dialog.open) dialog.showModal();
    try {
        const res = await fetch('/game/' + encodeURIComponent(gameId));
        if (!res.ok) throw new Error(res.status === 404 ? 'This game hasn\'t been played yet.' : 'HTTP ' + res.status);
        render(dialog, await res.json());
        dialog.scrollTop = 0;
    } catch (err) {
        dialog.innerHTML = '<div class="empty-note">Could not load this game: ' + esc(String(err.message || err)) + '</div>';
    }
}

export function initGames() {
    const dialog = document.getElementById('game_dialog');
    document.addEventListener('click', event => {
        // A team or player inside a game row opens that instead
        if (event.target.closest('[data-team-id], [data-player-id], a, button')) return;
        const target = event.target.closest('[data-game-id]');
        if (target && target.dataset.gameId) openGame(dialog, target.dataset.gameId);
    });
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    // ?game=<id> opens a box score directly
    const linked = new URLSearchParams(location.search).get('game');
    if (linked) openGame(dialog, linked);
}
