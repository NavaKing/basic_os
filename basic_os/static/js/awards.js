// Awards tab: All-America and All-Conference teams, the Heisman race and column, the playoff bracket and the bowl schedule.

import { esc, setStatus, postJSON, applyTeamColors } from './utils.js';
import { longJob } from './notify.js';

function teamMark(team) {
    if (!team) return '';
    const id = ' data-team-id="' + esc(team.id) + '"';
    return team.logo
        ? '<img class="team-logo" src="' + esc(team.logo) + '" alt="' + esc(team.short) + '" loading="lazy"' + id + '>'
        : '<span class="team-chip" data-color="' + esc(team.color || '') + '"' + id + '>' + esc(team.short) + '</span>';
}

function headshot(url) {
    return '<span class="headshot">' + (url ? '<img src="' + esc(url) + '" alt="" loading="lazy">' : '') + '</span>';
}

function dateText(iso, options = { weekday: 'short', month: 'short', day: 'numeric' }) {
    if (!iso) return 'Date TBD';
    const [y, m, d] = iso.split('-').map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, options);
}

// ---------- All-America ----------

function initAllAmerica(aa) {
    const select = document.getElementById('aa_group');
    const grid = document.getElementById('aa_grid');
    const groups = [];
    if (aa.national) groups.push({ key: 'national', label: 'All-America', ...aa.national });
    aa.conferences.forEach(c => groups.push({ ...c, key: c.name, label: 'All-' + c.label }));
    if (!groups.length) {
        grid.innerHTML = '<div class="empty-note">The game hasn\'t named its All-America teams yet.</div>';
        return;
    }
    select.innerHTML = groups.map((g, i) => '<option value="' + i + '">' + esc(g.label) + '</option>').join('');
    document.getElementById('aa_stage').textContent = aa.stage === 'Final'
        ? 'The game\'s end-of-season teams.'
        : 'Preseason teams, picked by the game before the season. They\'re replaced by the final teams once the season ends.';
    let side = 'first';
    const show = () => {
        const group = groups[Number(select.value) || 0];
        document.querySelectorAll('.aa-side').forEach(b => b.setAttribute('aria-selected', String(b.dataset.side === side)));
        const players = group[side] || [];
        grid.innerHTML = players.length ? players.map(p =>
            '<div class="aa-card' + (p.ours ? ' aa-card--ours' : '') + '">' +
                '<span class="aa-pos">' + esc(p.position) + '</span>' +
                headshot(p.portrait) +
                '<div class="aa-id">' +
                    '<div class="aa-name" data-player-id="' + esc(p.id) + '">' + esc(p.name) + '</div>' +
                    '<div class="aa-meta">' + teamMark(p.team) + '<span>' + esc(p.team ? p.team.short : '') + '</span>' +
                        (p.class ? '<span>' + esc(p.class) + '</span>' : '') + (p.overall ? '<span>' + esc(p.overall) + ' OVR</span>' : '') + '</div>' +
                '</div>' +
            '</div>').join('') : '<div class="empty-note">No picks for this team.</div>';
        applyTeamColors(grid);
    };
    select.addEventListener('change', show);
    document.querySelectorAll('.aa-side').forEach(b => b.addEventListener('click', () => { side = b.dataset.side; show(); }));
    show();
}

// ---------- Heisman ----------

function renderHeisman(rows) {
    const list = document.getElementById('aw_heisman');
    const move = m => m > 0 ? '<span class="swing-up">&#9650;' + m + '</span>' : (m < 0 ? '<span class="swing-down">&#9660;' + (-m) + '</span>' : '');
    list.innerHTML = rows.length ? rows.map(h =>
        '<li class="aw-heisman-row">' +
            '<span class="aw-heisman-rank">' + esc(h.rank) + '</span>' + headshot(h.portrait) +
            '<div class="aw-heisman-id"><div class="aa-name"><span data-player-id="' + esc(h.id) + '">' + esc(h.name) + '</span> ' + move(h.movement) + '</div>' +
                '<div class="aa-meta">' + teamMark(h.team) + '<span>' + esc(h.position) + ' &middot; ' + esc(h.team.name) + '</span></div></div>' +
            '<div class="stat-boxes stat-boxes--inline">' + h.boxes.map(b =>
                '<div class="stat-box"><div class="stat-box-value">' + esc(b.value) + '</div><div class="stat-box-label">' + esc(b.label) + '</div></div>').join('') + '</div>' +
        '</li>').join('') : '<li class="empty-note">The Heisman race starts once games are played.</li>';
    applyTeamColors(list);
}

function renderColumn(column, ceremony) {
    const kind = ceremony ? 'ceremony story' : 'Heisman Watch';
    document.getElementById('aw_column_generate').textContent = column ? 'Rewrite the ' + kind : 'Write the ' + kind;
    document.getElementById('aw_column_week').textContent = column
        ? (column.kind === 'heisman_ceremony' ? 'Ceremony Edition' : 'After Week ' + column.week) : (ceremony ? 'Ceremony Edition' : 'Heisman Watch');
    document.getElementById('aw_column_title').textContent = column ? column.title : (ceremony ? 'And the Heisman goes to...' : 'The Heisman Watch');
    document.getElementById('aw_column_body').innerHTML = column
        ? column.paragraphs.map((p, i) => '<p' + (i === 0 ? ' class="mag-dropcap"' : '') + '>' + esc(p) + '</p>').join('')
        : '<p class="mag-empty">' + (ceremony
            ? 'The regular season is over. Write the story of the ceremony, built from the finalists\' numbers.'
            : 'Write a column on the race so far, built from the contenders\' numbers.') + '</p>';
}

function initColumn(column, ceremony) {
    renderColumn(column, ceremony);
    const button = document.getElementById('aw_column_generate');
    const status = document.getElementById('aw_column_status');
    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, 'Writing the column...');
        try {
            const data = await longJob('The Heisman column', postJSON('/awards/heisman/generate'));
            if (data.error) throw new Error(data.error);
            renderColumn(data.column, ceremony);
            setStatus(status, '');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            button.disabled = false;
        }
    });
}

// ---------- Bowl season ----------

function slot(s) {
    if (s.team) {
        return '<div class="cfp-slot' + (s.won ? ' is-winner' : '') + '">' + (s.seed ? '<span class="cfp-seed">' + esc(s.seed) + '</span>' : '') +
            teamMark(s.team) + '<span class="cfp-team">' + esc(s.team.name) + '</span>' +
            (s.score !== undefined && s.score !== null ? '<span class="cfp-score">' + esc(s.score) + '</span>' : (s.record ? '<span class="cfp-record">' + esc(s.record) + '</span>' : '')) + '</div>';
    }
    return '<div class="cfp-slot cfp-slot--open">' + (s.seed ? '<span class="cfp-seed">' + esc(s.seed) + '</span>' : '') + esc(s.label || 'TBD') + '</div>';
}

function renderBracket(post) {
    document.getElementById('cfp_note').textContent = post.field_set
        ? 'The field as set by the game.'
        : 'Projected: if the playoff started today, seeded by the app\'s playoff odds (the Weekly Recap\'s CFP picture). ' +
          'The real field, with automatic bids for the top conference champions, is set by the game after the conference title games.';
    const bracket = document.getElementById('cfp_bracket');
    bracket.innerHTML = post.bracket.map(round =>
        '<div class="cfp-round"><div class="cfp-round-name">' + esc(round.name) + '</div>' +
            round.games.map(g =>
                '<div class="cfp-game">' + slot(g.top) + slot(g.bottom) +
                    '<div class="cfp-date">' + esc(dateText(g.date)) + (g.note ? ' &middot; ' + esc(g.note) : '') + '</div></div>').join('') +
        '</div>').join('');
    applyTeamColors(bracket);
}

function renderBowls(post) {
    document.getElementById('bowls_note').textContent = post.bowls_set
        ? post.bowls_set + ' of ' + post.bowls.length + ' bowls have their matchups.'
        : post.bowls.length + ' bowls on the schedule. Matchups are filled in by the game once the regular season ends.';
    const days = {};
    post.bowls.forEach(b => (days[b.date || ''] = days[b.date || ''] || []).push(b));
    const box = document.getElementById('bowl_days');
    box.innerHTML = Object.keys(days).sort().map(day =>
        '<div class="bowl-day"><div class="bowl-day-date">' + esc(dateText(day, { weekday: 'long', month: 'long', day: 'numeric' })) + '</div>' +
            days[day].map(b =>
                '<div class="bowl-game"><div class="bowl-name">' + esc(b.name) + '</div>' +
                    (b.home || b.away
                        ? '<div class="bowl-matchup">' + slot(b.away || { label: 'TBD' }) + slot(b.home || { label: 'TBD' }) + '</div>'
                        : '<div class="bowl-tbd">Matchup to be set</div>') +
                '</div>').join('') +
        '</div>').join('');
    applyTeamColors(box);
}

export function initAwards(data) {
    if (!data) return;
    initAllAmerica(data.all_america);
    renderHeisman(data.heisman);
    initColumn(data.column, data.ceremony);
    renderBracket(data.postseason);
    renderBowls(data.postseason);
}
