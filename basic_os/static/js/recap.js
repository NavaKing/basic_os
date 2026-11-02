// Weekly Recap: league-wide awards, notable games, polls and races for one week.

import { esc, setStatus, applyTeamColors } from './utils.js';

// ---------- Small building blocks ----------

/** Team logo, or a badge in the team's colour when there's no logo (colour applied after render via data-color). */
function teamChip(team) {
    const id = ' data-team-id="' + esc(team.id) + '"';
    if (team.logo) return '<img class="team-logo recap-logo" src="' + esc(team.logo) + '" alt="' + esc(team.short) + '" loading="lazy"' + id + '>';
    return '<span class="team-chip" data-color="' + esc(team.color || '') + '"' + id + '>' + esc(team.short) + '</span>';
}

/** Player headshot, falling back to initials. */
function avatar(portrait, initials, cls) {
    return portrait
        ? '<div class="' + cls + ' has-photo"><img src="' + esc(portrait) + '" alt="" loading="lazy"></div>'
        : '<div class="' + cls + '">' + esc(initials) + '</div>';
}

function teamName(team, { rank = true } = {}) {
    return teamChip(team) + '<span class="team-name" data-team-id="' + esc(team.id) + '">' + (rank && team.rank ? '<span class="team-rank">#' + esc(team.rank) + '</span> ' : '') + esc(team.name) + '</span>';
}

function card(title, body, { aside = '', extraClass = '' } = {}) {
    return '<div class="panel recap-card ' + extraClass + '">' +
        '<div class="recap-card-head"><h3>' + esc(title) + '</h3>' + (aside ? '<span class="recap-card-aside">' + esc(aside) + '</span>' : '') + '</div>' +
        body +
    '</div>';
}

function emptyNote(text) {
    return '<div class="empty-note empty-note--compact">' + esc(text) + '</div>';
}

// ---------- Player cards ----------

function playerCard(title, player) {
    if (!player) return card(title, emptyNote('No pick this week.'), { extraClass: 'recap-player' });
    const result = player.result;
    const body =
        '<div class="player-hero" data-color="' + esc(player.team.color || '') + '">' +
            avatar(player.portrait, player.first_name.charAt(0) + player.last_name.charAt(0), 'player-avatar') +
            '<div class="player-id">' +
                '<div class="player-first">' + esc(player.first_name) + '</div>' +
                '<div class="player-last">' + esc(player.last_name) + '</div>' +
                '<div class="player-meta">' + esc(player.position) + ' | ' + esc(player.team.name) + ' &middot; ' + esc(player.class) + '</div>' +
                '<div class="player-result">' +
                    '<span class="result-' + (result.outcome === 'W' ? 'win' : 'loss') + '">' + esc(result.outcome) + ' ' + esc(result.score) + '</span> ' +
                    esc(result.venue) + ' ' + teamName(result.opponent) +
                '</div>' +
                (player.note ? '<div class="player-note">' + esc(player.note) + '</div>' : '') +
            '</div>' +
        '</div>' +
        '<div class="stat-boxes">' + player.boxes.map(box =>
            '<div class="stat-box"><div class="stat-box-value">' + esc(box.value) + '</div><div class="stat-box-label">' + esc(box.label) + '</div></div>'
        ).join('') + '</div>';
    return card(title, body, { extraClass: 'recap-player' });
}

// ---------- Box score cards ----------

function boxScore(game) {
    const quarters = game.rows[0].quarters.length;
    let html = '<table class="box-score"><thead><tr><th>Team</th>';
    for (let q = 1; q <= quarters; q++) html += '<th>Q' + q + '</th>';
    html += '<th>T</th></tr></thead><tbody>';
    game.rows.forEach(row => {
        html += '<tr class="' + (row.won ? 'box-winner' : '') + '"><td>' + teamName(row.team) + '</td>' +
            row.quarters.map(points => '<td class="box-num">' + esc(points) + '</td>').join('') +
            '<td class="box-num box-total">' + esc(row.total) + '</td></tr>';
    });
    html += '</tbody></table>';
    if (game.tag || game.detail) {
        html += '<div class="box-footer">' + (game.tag ? '<span class="box-tag">' + esc(game.tag) + '</span>' : '') + esc(game.detail || '') + '</div>';
    }
    return html;
}

function gameCard(title, game, emptyText, aside) {
    return card(title, game ? boxScore(game) : emptyNote(emptyText), { aside });
}

function top25Card(games) {
    const body = games.length ? games.map(boxScore).join('') : emptyNote('No two ranked teams met this week.');
    return card('Top 25 Matchups', body);
}

// ---------- Lists ----------

function cfpCard(rows) {
    const body = '<ol class="cfp-list">' + rows.map(row =>
        '<li><span class="list-seed">' + esc(row.seed) + '</span>' + teamName(row.team, { rank: false }) +
        '<span class="list-record">' + esc(row.record) + '</span><span class="list-value">' + esc(row.chance) + '%</span></li>'
    ).join('') + '</ol>';
    return card('CFP Picture', body, { aside: 'Chance to make the field (est.)' });
}

function pollCard(title, movers, emptyText) {
    if (movers === null) return card(title, emptyNote('Poll movement for this week wasn\'t captured.'));
    const body = movers.length ? '<ul class="recap-list">' + movers.map(m =>
        '<li><div class="list-main">' + teamName(m.team, { rank: false }) + '<div class="list-sub">' + esc(m.line) + '</div></div>' +
        '<span class="poll-move">#' + esc(m.before) + ' &rarr; <strong>#' + esc(m.after) + '</strong></span></li>'
    ).join('') + '</ul>' : emptyNote(emptyText);
    return card(title, body);
}

function swingsCard(swings) {
    const body = swings.length ? '<ul class="recap-list">' + swings.map(s =>
        '<li><div class="list-main">' + teamName(s.team) + '<div class="list-sub">' + esc(s.line) + '</div></div>' +
        '<span class="swing-now">now ' + esc(s.now) + '%</span>' +
        '<span class="swing ' + (s.delta >= 0 ? 'swing-up' : 'swing-down') + '">' + (s.delta >= 0 ? '+' : '') + esc(s.delta) + '%</span></li>'
    ).join('') + '</ul>' : emptyNote('No big swings this week.');
    return card('Biggest Swings', body, { aside: 'Playoff odds this week (est.)' });
}

function streaksCard(streaks) {
    const column = (label, rows, cls) => '<div><div class="streak-label ' + cls + '">' + label + '</div><ul class="recap-list">' + rows.map(s =>
        '<li><div class="list-main">' + teamName(s.team) + '</div><span class="streak ' + cls + '">' + esc(s.streak) + '</span></li>'
    ).join('') + '</ul></div>';
    return card('Longest Active Streaks', '<div class="streak-columns">' + column('Winning', streaks.winning, 'streak-win') + column('Losing', streaks.losing, 'streak-loss') + '</div>');
}

function heismanCard(rows) {
    const movement = m => m > 0 ? '<span class="swing-up">&#9650;' + m + '</span>' : (m < 0 ? '<span class="swing-down">&#9660;' + (-m) + '</span>' : '<span class="muted">&mdash;</span>');
    const body = rows.length ? '<ol class="heisman-list">' + rows.map(h =>
        '<li><span class="list-seed">' + esc(h.rank) + '</span>' +
        '<div class="list-main">' + avatar(h.portrait, '', 'heisman-avatar') + teamChip(h.team) + '<div><div class="heisman-name">' + esc(h.name) + '</div><div class="list-sub">' + esc(h.position) + ' | ' + esc(h.team.name) + '</div></div></div>' +
        '<div class="stat-boxes stat-boxes--inline">' + h.boxes.map(b =>
            '<div class="stat-box"><div class="stat-box-value">' + esc(b.value) + '</div><div class="stat-box-label">' + esc(b.label) + '</div></div>').join('') + '</div>' +
        '<span class="heisman-move">' + movement(h.movement) + '</span></li>'
    ).join('') + '</ol>' : emptyNote('The Heisman watch list appears once the season gets going.');
    return card('Heisman Race', body, { aside: 'Season stats', extraClass: 'recap-wide' });
}

// ---------- Page ----------

function render(recap, weeks) {
    const week = weeks.find(w => w.week === recap.week);
    document.getElementById('recap_subtitle').textContent =
        'Week ' + recap.week + ' · ' + recap.game_count + ' games' + (week && week.in_progress ? ' · still in progress' : '');

    const body = document.getElementById('recap_body');
    body.innerHTML =
        '<div class="recap-row recap-row--4">' +
            playerCard('Offensive Player of the Week', recap.players.offense) +
            playerCard('Defensive Player of the Week', recap.players.defense) +
            playerCard('Freshman of the Week', recap.players.freshman) +
            playerCard('Bummer of the Week', recap.players.bummer) +
        '</div>' +
        '<div class="recap-row recap-row--3">' +
            gameCard('Game of the Week', recap.games.game_of_the_week, 'No one-score games this week.') +
            gameCard('Biggest Comeback', recap.games.comeback, 'Every winner led wire to wire.') +
            gameCard('Blowout of the Week', recap.games.blowout, 'No games this week.') +
        '</div>' +
        '<div class="recap-row recap-row--3">' +
            gameCard('Upset of the Week', recap.games.upset, 'No ranked team lost this week.', 'Vs the AP poll') +
            top25Card(recap.top25) +
            cfpCard(recap.cfp) +
        '</div>' +
        '<div class="recap-row recap-row--4">' +
            pollCard('Poll Risers', recap.risers, 'Nobody moved up this week.') +
            pollCard('Poll Fallers', recap.fallers, 'Nobody dropped this week.') +
            swingsCard(recap.swings) +
            streaksCard(recap.streaks) +
        '</div>' +
        '<div class="recap-row">' + heismanCard(recap.heisman) + '</div>';
    applyTeamColors(body);
}

export function initRecap(weeks, initialRecap) {
    const select = document.getElementById('recap_week');
    const status = document.getElementById('recap_status');
    if (!weeks || !weeks.length || !initialRecap) {
        document.getElementById('recap_body').innerHTML = emptyNote('The recap appears once the first week of games is played.');
        return;
    }
    select.innerHTML = weeks.map(w =>
        '<option value="' + w.week + '">Week ' + w.week + ' &middot; ' + w.games + ' games' + (w.in_progress ? ' (in progress)' : '') + '</option>'
    ).join('');

    const prev = document.getElementById('recap_prev');
    const next = document.getElementById('recap_next');
    const updateArrows = () => {
        prev.disabled = select.selectedIndex <= 0;
        next.disabled = select.selectedIndex >= select.options.length - 1;
    };

    async function load(week) {
        setStatus(status, 'Loading week ' + week + '...');
        try {
            const res = await fetch('/recap/' + week);
            render(await res.json(), weeks);
            setStatus(status, '');
        } catch (err) {
            setStatus(status, 'Could not load the recap: ' + err, true);
        }
        updateArrows();
    }

    select.addEventListener('change', () => load(select.value));
    prev.addEventListener('click', () => { select.selectedIndex -= 1; load(select.value); });
    next.addEventListener('click', () => { select.selectedIndex += 1; load(select.value); });

    select.value = String(initialRecap.week);
    render(initialRecap, weeks);
    updateArrows();
}
