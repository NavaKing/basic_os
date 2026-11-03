// Player care window (opened from the tab bar): this week's care list, the coach's hours, the leadership council,
// mentorship pairs, the difficulty preset and the simulator. Everything lives in the app; nothing is written to the save.

import { esc, setStatus, headshot } from './utils.js';

function needBars(player, needs, low) {
    return '<div class="care-needs">' + needs.map(n => {
        const value = player.needs[n.key];
        return '<div class="care-need' + (value < low ? ' care-need--low' : '') + '">' +
                   '<span class="care-need-label">' + esc(n.label) + '</span>' +
                   '<span class="care-need-bar"><span data-fill="' + value + '"></span></span>' +
                   '<span class="care-need-value">' + value + '</span>' +
               '</div>';
    }).join('') + '</div>';
}

function playerHead(p) {
    return '<div class="care-player">' + headshot(p.portrait, 'care-headshot') +
               '<div><button type="button" class="care-name" data-player-id="' + esc(p.save_id) + '">' + esc(p.name) + '</button>' +
               '<div class="care-meta">' + esc(p.position) + ' &middot; ' + esc(p.class) + ' &middot; ' + esc(p.overall) + ' OVR &middot; Trust ' + esc(p.trust) + '</div>' +
               (p.flags.length ? '<div class="care-flags">' + p.flags.map(f => '<span class="care-flag">' + esc(f) + '</span>').join('') + '</div>' : '') +
               '</div></div>';
}

function card(p, data) {
    const needOptions = data.needs.map(n => '<option value="' + n.key + '"' + (n.key === p.lowest ? ' selected' : '') + '>' + esc(n.label) + '</option>').join('');
    const actions = data.actions.map(a =>
        '<button type="button" class="btn-secondary care-action" data-act="' + a.key + '"' + (a.hours > data.hours ? ' disabled' : '') + '>' +
            esc(a.label) + ' <span class="care-hours">' + a.hours + 'h</span></button>').join('');
    return '<li class="care-card" data-save-id="' + esc(p.save_id) + '">' + playerHead(p) + needBars(p, data.needs, data.low_need) +
               (p.warnings.length ? '<ul class="care-warnings">' + p.warnings.map(w => '<li>' + esc(w) + '</li>').join('') + '</ul>' : '') +
               (p.mentor ? '<div class="care-meta">Mentor: ' + esc(p.mentor) + '</div>' : '') +
               '<div class="care-act-row"><select class="care-need-pick" aria-label="Need to work on">' + needOptions + '</select>' + actions + '</div>' +
           '</li>';
}

function rosterOptions(roster, placeholder) {
    return '<option value="">' + esc(placeholder) + '</option>' +
        roster.map(p => '<option value="' + esc(p.save_id) + '">' + esc(p.position + ' ' + p.name + ' (' + p.class + ')') + '</option>').join('');
}

function render(body, data) {
    if (!data.started) {
        body.innerHTML = '<p class="empty-note">Player care starts once the schedule has synced from your save.</p>';
        return;
    }
    const byId = Object.fromEntries(data.roster.map(p => [p.save_id, p]));
    const council = data.council.map(p =>
        '<li class="care-pill">' + esc(p.position + ' ' + p.name) + ' <span class="care-meta">morale ' + p.needs.morale + '</span>' +
        '<button type="button" class="care-x" data-council-off="' + esc(p.save_id) + '" aria-label="Remove ' + esc(p.name) + '">&times;</button></li>').join('');
    const suggestions = data.council_suggestions.map(id => byId[id] ?
        '<button type="button" class="btn-secondary care-suggest" data-council-on="' + esc(id) + '">+ ' + esc(byId[id].position + ' ' + byId[id].name) + '</button>' : '').join('');
    const mentors = data.mentors.map(m =>
        '<li class="care-pill">' + esc(m.mentor.name) + ' &rarr; ' + esc(m.mentee.name) +
        '<button type="button" class="care-x" data-mentor-off="' + esc(m.mentee.save_id) + '" aria-label="End this pairing">&times;</button></li>').join('');

    body.innerHTML =
        '<div class="care-top">' +
            '<div class="care-hours-left"><strong>' + data.hours + '</strong> of ' + data.hours_total + ' coach hours left this week</div>' +
            '<label class="care-preset">Difficulty <select id="care_preset">' +
                data.presets.map(p => '<option' + (p === data.preset ? ' selected' : '') + '>' + esc(p) + '</option>').join('') + '</select></label>' +
        '</div>' +
        (data.calendar.length ? '<div class="care-calendar">' + data.calendar.map(c => '<span class="care-flag">' + esc(c) + '</span>').join('') + '</div>' : '') +

        '<h3 class="care-section">This week\'s care list</h3>' +
        '<p class="muted care-note">The players who most need you, lowest needs first. Hours reset when the save moves to the next week.</p>' +
        '<ol class="care-list">' + data.care_list.map(p => card(p, data)).join('') + '</ol>' +

        '<h3 class="care-section">Leadership council</h3>' +
        '<p class="muted care-note">Two to ' + data.council_max + ' captains. "Ask a captain" sends one of them to a teammate for an hour; ' +
            'a captain whose morale sinks drags the whole locker room down.</p>' +
        '<ul class="care-pills">' + (council || '<li class="muted">No captains named yet.</li>') + '</ul>' +
        (data.council.length < data.council_max && suggestions ? '<div class="care-suggestions">' + suggestions + '</div>' : '') +

        '<h3 class="care-section">Mentors</h3>' +
        '<p class="muted care-note">A good mentor slows a younger player\'s morale and focus drain; an undisciplined one makes focus worse.</p>' +
        '<ul class="care-pills">' + (mentors || '<li class="muted">No pairs yet.</li>') + '</ul>' +
        '<form class="care-pair" id="care_pair">' +
            '<select id="care_mentee" aria-label="Younger player">' + rosterOptions(data.roster, 'Younger player') + '</select>' +
            '<select id="care_mentor" aria-label="Mentor">' + rosterOptions(data.roster, 'Mentor') + '</select>' +
            '<button type="submit" class="btn-secondary">Pair</button>' +
        '</form>' +

        '<h3 class="care-section">Simulator</h3>' +
        '<p class="muted care-note">Plays 12 made-up weeks on a copy of the roster: once ignoring everyone, once spending every hour. Nothing is saved.</p>' +
        '<button type="button" class="btn-secondary" id="care_simulate">Run the simulator</button>' +
        '<div id="care_sim"></div>' +

        '<h3 class="care-section">Care log</h3>' +
        '<ol class="care-log">' + (data.log.map(l => '<li><span class="care-meta">Wk ' + esc(l.week) + '</span> ' + esc(l.text) + '</li>').join('') ||
            '<li class="muted">Nothing yet.</li>') + '</ol>';
    // Bar widths are set here, not in the markup: the page's content security policy blocks inline styles
    body.querySelectorAll('[data-fill]').forEach(el => { el.style.width = el.dataset.fill + '%'; });
}

function simTable(result) {
    const rows = [['Warning signs', 'warning_signs'], ['Player-weeks with a low need', 'player_weeks_with_a_low_need'],
                  ['Players low at the end', 'players_with_a_low_need'], ['Average need', 'average_need'], ['Average trust', 'average_trust']];
    return '<table class="care-sim"><thead><tr><th>' + esc(result.ignore.preset) + '</th><th>Ignore</th><th>Care</th></tr></thead><tbody>' +
        rows.map(([label, key]) => '<tr><td>' + label + '</td><td>' + esc(result.ignore[key]) + '</td><td>' + esc(result.care[key]) + '</td></tr>').join('') +
        '</tbody></table>';
}

async function call(url, body, status) {
    const res = await fetch(url, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({ error: 'HTTP ' + res.status }));
    if (data.error) setStatus(status, data.error, true);
    return data;
}

export function initCare() {
    const dialog = document.getElementById('care_dialog');
    const body = document.getElementById('care_body');
    const status = document.getElementById('care_status');
    let data = null;
    const show = next => {
        if (next.error) return;
        data = next;
        document.getElementById('care_kicker').textContent = data.started ? 'Player care · Week ' + data.week : 'Player care';
        render(body, data);
    };
    const post = async (action, payload, done) => {
        setStatus(status, '');
        const next = await call('/care/' + action, payload, status);
        show(next);
        if (!next.error && done) setStatus(status, done);
    };

    const open = async () => {
        setStatus(status, '');
        if (!dialog.open) dialog.showModal();
        show(await call('/care', undefined, status));
    };
    document.getElementById('care_open').addEventListener('click', open);
    // ?care opens the window directly
    if (new URLSearchParams(location.search).has('care')) open();
    document.getElementById('care_close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

    body.addEventListener('click', async event => {
        const act = event.target.closest('[data-act]');
        const on = event.target.closest('[data-council-on]');
        const off = event.target.closest('[data-council-off]');
        const unpair = event.target.closest('[data-mentor-off]');
        if (act) {
            const cardEl = act.closest('.care-card');
            await post('act', { save_id: cardEl.dataset.saveId, action: act.dataset.act, need: cardEl.querySelector('.care-need-pick').value });
        } else if (on) {
            await post('council', { save_id: on.dataset.councilOn, on: true });
        } else if (off) {
            await post('council', { save_id: off.dataset.councilOff, on: false });
        } else if (unpair) {
            await post('mentor', { mentee: unpair.dataset.mentorOff, mentor: null });
        } else if (event.target.id === 'care_simulate') {
            setStatus(status, 'Simulating...');
            const result = await call('/care/simulate', { preset: data.preset }, status);
            if (!result.error) {
                setStatus(status, '');
                document.getElementById('care_sim').innerHTML = simTable(result);
            }
        }
    });
    body.addEventListener('change', event => {
        if (event.target.id === 'care_preset') post('preset', { preset: event.target.value }, 'Difficulty set to ' + event.target.value + '.');
    });
    body.addEventListener('submit', event => {
        if (event.target.id !== 'care_pair') return;
        event.preventDefault();
        const mentee = document.getElementById('care_mentee').value;
        const mentor = document.getElementById('care_mentor').value;
        if (!mentee || !mentor) return setStatus(status, 'Pick both players.', true);
        post('mentor', { mentee, mentor }, 'Paired.');
    });
}
