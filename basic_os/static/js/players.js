// Player profiles: clicking anything with data-player-id opens that player's season, honors, background and
// (for our players) storylines and campus photos in a dialog.

import { esc, applyTeamColors } from './utils.js';

function teamMark(team) {
    if (!team) return '';
    return team.logo
        ? '<img class="team-logo" src="' + esc(team.logo) + '" alt="" data-team-id="' + esc(team.id) + '">'
        : '<span class="team-chip" data-color="' + esc(team.color || '') + '">' + esc(team.short) + '</span>';
}

function section(title, body) {
    return body ? '<section class="pp-section"><h3>' + esc(title) + '</h3>' + body + '</section>' : '';
}

function render(dialog, p) {
    const sub = ['#' + (p.jersey ?? ''), p.position_name, p.class].filter(Boolean).map(esc).join(' &middot; ');
    const origin = [p.hometown, p.recruit].filter(Boolean).map(esc).join(' &middot; ');
    const facts = p.facts.length ? '<div class="pp-facts">' + p.facts.map(f =>
        '<div class="pp-fact"><div class="pp-fact-value">' + esc(f.value) + '</div><div class="pp-fact-label">' + esc(f.label) + '</div></div>').join('') + '</div>' : '';
    const season = p.boxes.length
        ? '<div class="stat-boxes">' + p.boxes.map(b => '<div class="stat-box"><div class="stat-box-value">' + esc(b.value) + '</div><div class="stat-box-label">' + esc(b.label) + '</div></div>').join('') + '</div>' +
          (p.season_line ? '<p class="pp-line">' + esc(p.season_line) + '</p>' : '')
        : '<p class="muted">No stats recorded this season.</p>';
    const games = p.games.length ? '<table class="pp-games"><tbody>' + p.games.map(g =>
        '<tr><td class="muted">Wk ' + esc(g.week) + '</td>' +
            '<td class="nowrap">' + esc(g.venue) + ' ' + teamMark(g.opponent) + ' ' + esc(g.opponent ? g.opponent.short : '') + '</td>' +
            '<td><span class="score ' + (g.outcome === 'W' ? 'score-win' : g.outcome === 'L' ? 'score-loss' : '') + '">' + esc(g.outcome) + ' ' + esc(g.score) + '</span></td>' +
            '<td class="pp-game-line">' + esc(g.line) + '</td></tr>').join('') + '</tbody></table>' : '';
    const honors = p.honors.length ? '<ul class="pp-honors">' + p.honors.map(h => '<li>' + esc(h) + '</li>').join('') + '</ul>' : '';
    const stories = p.storylines.length ? '<ul class="pp-stories">' + p.storylines.map(s =>
        '<li><div class="pp-story-head"><strong>' + esc(s.title) + '</strong><span class="muted">' + esc(s.status) + ' &middot; ' + esc(s.weeks) + '</span></div>' +
        '<p>' + esc(s.text) + '</p></li>').join('') + '</ul>' : '';
    const photos = p.photos.length ? '<div class="pp-photos">' + p.photos.map(ph =>
        '<figure><img src="' + esc(ph.image) + '" alt="" loading="lazy"><figcaption>' + esc(ph.caption) + '</figcaption></figure>').join('') + '</div>' : '';

    dialog.innerHTML =
        '<div class="team-dialog-hero pp-hero" data-color="' + esc(p.team ? p.team.color || '' : '') + '">' +
            '<span class="headshot pp-headshot">' + (p.portrait ? '<img src="' + esc(p.portrait) + '" alt="">' : '') + '</span>' +
            '<div class="team-dialog-title">' +
                '<div class="team-dialog-kicker">' + sub + '</div>' +
                '<h2>' + esc(p.name) + '</h2>' +
                (p.team ? '<div class="pp-team">' + teamMark(p.team) + ' ' + esc(p.team.name) + '</div>' : '') +
                (origin ? '<div class="team-dialog-stadium">' + origin + '</div>' : '') +
            '</div>' +
            '<button class="team-dialog-close" type="button" aria-label="Close">&times;</button>' +
        '</div>' +
        '<div class="pp-body">' +
            facts +
            section('Season', season) +
            section('Honors', honors) +
            section('Game by game', games) +
            section('Storylines', stories) +
            section('On the campus feed', photos) +
        '</div>';
    applyTeamColors(dialog);
    dialog.querySelector('.team-dialog-close').addEventListener('click', () => dialog.close());
}

async function openPlayer(dialog, playerId) {
    dialog.innerHTML = '<div class="empty-note">Loading player...</div>';
    if (!dialog.open) dialog.showModal();
    try {
        const res = await fetch('/player/' + encodeURIComponent(playerId));
        if (!res.ok) throw new Error(res.status === 404 ? 'This player isn\'t in the synced data.' : 'HTTP ' + res.status);
        render(dialog, await res.json());
        dialog.scrollTop = 0;
    } catch (err) {
        dialog.innerHTML = '<div class="empty-note">Could not load this player: ' + esc(String(err.message || err)) + '</div>';
    }
}

export function initPlayerPages() {
    const dialog = document.getElementById('player_dialog');
    document.addEventListener('click', event => {
        const target = event.target.closest('[data-player-id]');
        if (target && target.dataset.playerId) openPlayer(dialog, target.dataset.playerId);
    });
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    // ?player=<id> opens a profile directly
    const linked = new URLSearchParams(location.search).get('player');
    if (linked) openPlayer(dialog, linked);
}
