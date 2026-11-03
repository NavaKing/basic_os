// Player care window (opened from the tab bar). Four tabs: This week (who needs the coach, grouped by urgency; a row
// opens to show every need and the actions), Captains & mentors, Log, and Balance (difficulty and the simulator).
// Everything lives in the app; nothing is written to the save.

import { esc, setStatus, headshot } from './utils.js';

const TABS = [['week', 'This week'], ['phone', 'Phone'], ['inbox', 'Inbox'], ['team', 'Captains & mentors'], ['log', 'Log'], ['balance', 'Balance']];

// What the window remembers between refreshes (each action re-renders it)
const ui = { tab: 'week', open: new Set(), need: {}, sim: null };

function level(value, data) {
    return value < data.low_need ? 'low' : value < data.watch_need ? 'watch' : 'ok';
}

function changeText(change) {
    if (!change) return '';
    return change < 0 ? '<span class="care-down">&#9660;' + -change + '</span>' : '<span class="care-up">&#9650;' + change + '</span>';
}

function needLabel(data, key) {
    return data.needs.find(n => n.key === key).label;
}

// The one-line reason a player is listed: their worst need, how the week moved it, and any warning sign
function summary(p, data) {
    const worst = p.lowest;
    const value = p.needs[worst];
    return '<span class="care-worst care-level--' + level(value, data) + '">' + esc(needLabel(data, worst)) + ' ' + value + '</span>' +
           (p.change ? ' ' + changeText(p.change[worst]) : '') +
           (p.warnings.length ? ' <span class="care-warning-text">&ldquo;' + esc(p.warnings[p.warnings.length - 1]) + '&rdquo;</span>' : '') +
           p.flags.map(f => ' <span class="care-flag">' + esc(f) + '</span>').join('');
}

function actionButton(a, p, need, data) {
    const hasCaptain = data.council.some(c => c.save_id !== p.save_id);
    const fills = a.fills ? a.fills.map(k => needLabel(data, k)).join(' & ') : needLabel(data, need);
    let effect = fills + ' +' + a.fill;
    if (a.clears_warnings && p.warnings.length) effect += ', clears warning';
    let why = '';
    if (a.hours > data.hours) why = 'Not enough hours left this week';
    else if (a.key === 'council' && !hasCaptain) why = 'Name captains first (Captains & mentors tab)';
    return '<button type="button" class="btn-secondary care-action" data-act="' + a.key + '"' + (why ? ' disabled title="' + esc(why) + '"' : '') + '>' +
               '<span class="care-action-name">' + esc(a.label) + '</span>' +
               '<span class="care-action-effect">' + esc(effect) + ' &middot; ' + a.hours + 'h</span>' +
           '</button>';
}

function row(p, data) {
    const isOpen = ui.open.has(p.save_id);
    const need = ui.need[p.save_id] || p.lowest;
    const head =
        '<button type="button" class="care-row-head" data-toggle="' + esc(p.save_id) + '" aria-expanded="' + isOpen + '">' +
            headshot(p.portrait, 'care-headshot') +
            '<span class="care-row-name">' + esc(p.name) + ' <span class="care-meta">' + esc(p.position) + ' &middot; ' + esc(p.class) + '</span></span>' +
            '<span class="care-row-why">' + summary(p, data) + '</span>' +
            '<span class="care-chevron" aria-hidden="true">' + (isOpen ? '&#9662;' : '&#9656;') + '</span>' +
        '</button>';
    if (!isOpen) return '<li class="care-row" data-save-id="' + esc(p.save_id) + '">' + head + '</li>';

    const bars = data.needs.map(n => {
        const value = p.needs[n.key];
        return '<button type="button" class="care-need care-level--' + level(value, data) + (n.key === need ? ' is-picked' : '') + '" data-need="' + n.key + '">' +
                   '<span class="care-need-label">' + esc(n.label) + '</span>' +
                   '<span class="care-need-bar"><span data-fill="' + value + '"></span></span>' +
                   '<span class="care-need-value">' + value + '</span>' +
                   '<span class="care-need-change">' + (p.change ? changeText(p.change[n.key]) : '') + '</span>' +
               '</button>';
    }).join('');
    return '<li class="care-row is-open" data-save-id="' + esc(p.save_id) + '">' + head +
               '<div class="care-row-body">' +
                   '<div class="care-meta">' + esc(p.overall) + ' OVR &middot; Trust ' + esc(p.trust) + (p.mentor ? ' &middot; Mentor: ' + esc(p.mentor) : '') +
                       ' &middot; <button type="button" class="care-link" data-player-id="' + esc(p.save_id) + '">Profile</button></div>' +
                   (p.warnings.length ? '<ul class="care-warnings">' + p.warnings.map(w => '<li>' + esc(w) + '</li>').join('') + '</ul>' : '') +
                   '<div class="care-needs">' + bars + '</div>' +
                   '<div class="care-help">Help with <strong>' + esc(needLabel(data, need)) + '</strong> <span class="muted">(click a bar to pick another need)</span></div>' +
                   '<div class="care-act-row">' + data.actions.map(a => actionButton(a, p, need, data)).join('') + '</div>' +
               '</div>' +
           '</li>';
}

function weekTab(data) {
    const g = data.groups;
    const warnings = [...g.now, ...g.close, ...g.fine].reduce((n, p) => n + p.warnings.length, 0);
    const chips = [];
    if (warnings) chips.push('<span class="care-chip care-chip--low">&#9888; ' + warnings + ' warning sign' + (warnings > 1 ? 's' : '') + '</span>');
    chips.push('<span class="care-chip' + (g.now.length ? ' care-chip--low' : '') + '">' + g.now.length + ' need you now</span>');
    chips.push('<span class="care-chip' + (g.close.length ? ' care-chip--watch' : '') + '">' + g.close.length + ' getting close</span>');
    data.calendar.forEach(c => chips.push('<span class="care-chip">' + esc(c) + '</span>'));
    const list = (players, empty) => players.length ? '<ol class="care-rows">' + players.map(p => row(p, data)).join('') + '</ol>' : '<p class="muted care-note">' + empty + '</p>';
    return '<div class="care-summary">' +
               '<div class="care-hours-left"><strong>' + data.hours + '</strong> of ' + data.hours_total + ' coach hours left</div>' +
               '<div class="care-chips">' + chips.join('') + '</div>' +
           '</div>' +
           '<p class="muted care-note">Click a player to see all five needs and help. Hours refill when the save moves to the next week. ' +
               '&#9660; and &#9650; show how the last weekly update moved a need: the weekly drain, plus any lift from a big game.</p>' +
           '<h3 class="care-section care-section--low">Needs you now</h3>' +
           '<p class="muted care-note">A need under ' + data.low_need + ', or a warning sign.</p>' +
           list(g.now, 'Nobody is in the red.') +
           '<h3 class="care-section care-section--watch">Getting close</h3>' +
           '<p class="muted care-note">Lowest need under ' + data.watch_need + '.</p>' +
           list(g.close, 'Nobody is slipping.') +
           '<details class="care-rest"' + (g.now.length + g.close.length === 0 ? ' open' : '') + '><summary>Everyone else (' + g.fine.length + ')</summary>' +
               list(g.fine, 'No one else.') + '</details>';
}

function rosterOptions(roster, placeholder) {
    return '<option value="">' + esc(placeholder) + '</option>' +
        roster.map(p => '<option value="' + esc(p.save_id) + '">' + esc(p.position + ' ' + p.name + ' (' + p.class + ')') + '</option>').join('');
}

function teamTab(data) {
    const byId = Object.fromEntries(data.roster.map(p => [p.save_id, p]));
    const council = data.council.map(p =>
        '<li class="care-pill">' + esc(p.position + ' ' + p.name) + ' <span class="care-meta">morale ' + p.needs.morale + '</span>' +
        '<button type="button" class="care-x" data-council-off="' + esc(p.save_id) + '" aria-label="Remove ' + esc(p.name) + '">&times;</button></li>').join('');
    const suggestions = data.council_suggestions.map(id => byId[id] ?
        '<button type="button" class="btn-secondary care-suggest" data-council-on="' + esc(id) + '">+ ' + esc(byId[id].position + ' ' + byId[id].name) + '</button>' : '').join('');
    const mentors = data.mentors.map(m =>
        '<li class="care-pill">' + esc(m.mentor.name) + ' &rarr; ' + esc(m.mentee.name) +
        '<button type="button" class="care-x" data-mentor-off="' + esc(m.mentee.save_id) + '" aria-label="End this pairing">&times;</button></li>').join('');
    return '<p class="muted care-note">Set these up once; they keep working every week without spending your hours.</p>' +
        '<h3 class="care-section">Leadership council</h3>' +
        '<p class="muted care-note">Name 2 to ' + data.council_max + ' captains. Each one unlocks "Ask a captain" (1 hour) on every player. ' +
            'Watch their morale: if a captain drops under 30, the whole locker room\'s morale drains faster.</p>' +
        '<ul class="care-pills">' + (council || '<li class="muted">No captains yet.</li>') + '</ul>' +
        (data.council.length < data.council_max && suggestions ? '<div class="care-suggestions"><span class="care-meta">Suggested:</span>' + suggestions + '</div>' : '') +
        '<h3 class="care-section">Mentors</h3>' +
        '<p class="muted care-note">Pair a younger player with a veteran. A good mentor slows the younger player\'s morale and focus drop every week; ' +
            'an undisciplined or unfocused one makes focus worse.</p>' +
        '<ul class="care-pills">' + (mentors || '<li class="muted">No pairs yet.</li>') + '</ul>' +
        '<form class="care-pair" id="care_pair">' +
            '<select id="care_mentee" aria-label="Younger player">' + rosterOptions(data.roster, 'Younger player') + '</select>' +
            '<select id="care_mentor" aria-label="Mentor">' + rosterOptions(data.roster, 'Mentor') + '</select>' +
            '<button type="submit" class="btn-secondary">Pair</button>' +
        '</form>';
}

function phoneTab(data) {
    if (!data.phone.length) return '<p class="muted care-note">No texts yet. Players text you when a need starts slipping; new texts arrive when the save moves to the next week.</p>';
    return '<p class="muted care-note">Answer before the next game: a text still waiting when the week moves on drains that need and costs trust. ' +
        'A reply costs the same hours as the matching care action.</p>' +
        '<ol class="care-threads">' + data.phone.map(t =>
            '<li class="care-thread' + (t.waiting ? ' is-waiting' : '') + '">' +
                '<div class="care-thread-head">' + headshot(t.portrait, 'care-headshot') +
                    '<button type="button" class="care-name" data-player-id="' + esc(t.save_id) + '">' + esc(t.name) + '</button>' +
                    '<span class="care-meta">' + esc(t.position) + '</span>' + (t.waiting ? '<span class="care-chip care-chip--low">Waiting</span>' : '') + '</div>' +
                '<div class="care-bubbles">' + t.messages.map(m =>
                    '<div class="care-bubble care-bubble--them"><span class="care-meta">Week ' + esc(m.week) + '</span> ' + esc(m.text) + '</div>' +
                    (m.reply ? '<div class="care-bubble care-bubble--me">' + esc(m.reply) + '</div>' :
                     m.status === 'missed' ? '<div class="care-meta care-missed">Left on read</div>' : '')).join('') + '</div>' +
                (t.waiting ? '<div class="care-act-row">' + t.waiting.replies.map(r => {
                    const action = data.actions.find(a => a.key === r.key);
                    const hours = action ? action.hours : 0;
                    return '<button type="button" class="btn-secondary care-action" data-reply="' + t.waiting.message_id + '" data-choice="' + r.key + '"' +
                        (hours > data.hours ? ' disabled title="Not enough hours left this week"' : '') + '>' +
                        '<span class="care-action-name">' + esc(r.label) + '</span><span class="care-action-effect">' + (hours ? hours + 'h' : 'free, trust -1') + '</span></button>';
                }).join('') + '</div>' : '') +
            '</li>').join('') + '</ol>';
}

function inboxTab(data) {
    if (!data.inbox.length) return '<p class="muted care-note">No email yet. The staff write when the save moves to the next week.</p>';
    return '<p class="muted care-note">Emails from the school staff. Actions cost coach hours; an email left open expires when the week moves on.</p>' +
        '<ol class="care-emails">' + data.inbox.map(e =>
            '<li class="care-email' + (e.status === 'open' ? ' is-open' : '') + '">' +
                '<div class="care-email-head"><strong>' + esc(e.subject) + '</strong><span class="care-meta">' + esc(e.sender) + ' &middot; Week ' + esc(e.week) +
                    (e.status !== 'open' ? ' &middot; ' + esc(e.status) : '') + '</span></div>' +
                '<p class="care-email-body">' + esc(e.body) + '</p>' +
                (e.result ? '<p class="care-meta">Done: ' + esc(e.result) + '</p>' : '') +
                (e.status === 'open' ? '<div class="care-act-row">' + e.actions.map(a =>
                    '<button type="button" class="btn-secondary care-action" data-email="' + e.email_id + '" data-email-act="' + esc(a.key) + '"' +
                        (a.hours > data.hours ? ' disabled title="Not enough hours left this week"' : '') + '>' +
                        '<span class="care-action-name">' + esc(a.label) + '</span><span class="care-action-effect">' + esc(a.effect) + ' &middot; ' + (a.hours ? a.hours + 'h' : 'free') + '</span></button>').join('') +
                    '<button type="button" class="btn-secondary care-action" data-email="' + e.email_id + '" data-email-act="read"><span class="care-action-name">' +
                        (e.actions.length ? 'Done' : 'Mark read') + '</span></button></div>' : '') +
            '</li>').join('') + '</ol>';
}

function logTab(data) {
    return '<ol class="care-log">' + (data.log.map(l => '<li><span class="care-meta">Week ' + esc(l.week) + '</span> ' + esc(l.text) + '</li>').join('') ||
        '<li class="muted">Nothing yet.</li>') + '</ol>';
}

function verdict(r) {
    const i = r.ignore, c = r.care;
    return '<p class="care-verdict">Over 12 made-up weeks on <strong>' + esc(i.preset) + '</strong>: ignoring everyone, players spent <strong>' +
        i.player_weeks_with_a_low_need + '</strong> weeks in the red (added up) and showed <strong>' + i.warning_signs + '</strong> warning signs. ' +
        'Spending every hour cut that to <strong>' + c.player_weeks_with_a_low_need + '</strong> weeks and <strong>' + c.warning_signs + '</strong> warning signs, and the <strong>' +
        c.players_cared_for + '</strong> players you reached ended at trust <strong>' + c.trust_of_players_cared_for + '</strong> (everyone starts at 30).</p>';
}

function simTable(r) {
    const rows = [['Warning signs shown', 'warning_signs'], ['Weeks players spent in the red, added up', 'player_weeks_with_a_low_need'],
                  ['Players in the red at the end', 'players_with_a_low_need'], ['Average need', 'average_need'],
                  ['Players you cared for', 'players_cared_for'], ['Their average trust', 'trust_of_players_cared_for']];
    return '<table class="care-sim"><thead><tr><th></th><th>Ignore</th><th>Care</th></tr></thead><tbody>' +
        rows.map(([label, key]) => '<tr><td>' + label + '</td><td>' + esc(r.ignore[key] ?? '-') + '</td><td>' + esc(r.care[key] ?? '-') + '</td></tr>').join('') +
        '</tbody></table>';
}

function balanceTab(data) {
    return '<h3 class="care-section">Difficulty</h3>' +
        '<p class="muted care-note">Sets your weekly hours and how fast needs drop. Takes effect right away.</p>' +
        '<select id="care_preset" class="care-preset">' + data.presets.map(p => '<option' + (p === data.preset ? ' selected' : '') + '>' + esc(p) + '</option>').join('') + '</select>' +
        '<h3 class="care-section">Simulator</h3>' +
        '<p class="muted care-note">Plays 12 made-up weeks on a copy of your roster twice: once ignoring everyone, once spending every hour. ' +
            'It shows whether this difficulty feels right. Nothing is saved.</p>' +
        '<button type="button" class="btn-secondary" id="care_simulate">Run the simulator</button>' +
        (ui.sim ? verdict(ui.sim) + simTable(ui.sim) : '');
}

function render(body, data) {
    if (!data.started) {
        body.innerHTML = '<p class="empty-note">Player care starts once the schedule has synced from your save.</p>';
        return;
    }
    const count = data.groups.now.length;
    const badges = { week: count, phone: data.unread.texts, inbox: data.unread.emails };
    const tabs = '<div class="care-tabs" role="tablist">' + TABS.map(([key, label]) =>
        '<button type="button" role="tab" class="care-tab' + (ui.tab === key ? ' is-active' : '') + '" data-care-tab="' + key + '" aria-selected="' + (ui.tab === key) + '">' +
            esc(label) + (badges[key] ? ' <span class="care-badge">' + badges[key] + '</span>' : '') + '</button>').join('') + '</div>';
    const content = { week: weekTab, phone: phoneTab, inbox: inboxTab, team: teamTab, log: logTab, balance: balanceTab }[ui.tab](data);
    body.innerHTML = tabs + '<div class="care-panel">' + content + '</div>';
    // Bar widths are set here, not in the markup: the page's content security policy blocks inline styles
    body.querySelectorAll('[data-fill]').forEach(el => { el.style.width = el.dataset.fill + '%'; });
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
    const button = document.getElementById('care_open');
    // Texts and emails waiting, on the tab bar's Care button
    const badge = unread => {
        const total = unread.texts + unread.emails;
        button.innerHTML = 'Care' + (total ? ' <span class="care-badge">' + total + '</span>' : '');
        button.title = total ? unread.texts + ' text(s) and ' + unread.emails + ' email(s) waiting' : '';
    };
    fetch('/care/unread').then(res => res.json()).then(badge).catch(() => {});
    const show = next => {
        if (next.error) return;
        data = next;
        if (data.unread) badge(data.unread);
        document.getElementById('care_kicker').textContent = data.started ? 'Player care · Week ' + data.week + ' · ' + data.preset : 'Player care';
        render(body, data);
    };
    const redraw = () => data && render(body, data);
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
    // ?care opens the window directly; ?care=phone (or another tab) opens it on that tab
    const linked = new URLSearchParams(location.search).get('care');
    if (linked !== null) {
        if (TABS.some(([key]) => key === linked)) ui.tab = linked;
        open();
    }
    document.getElementById('care_close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });

    body.addEventListener('click', async event => {
        const tab = event.target.closest('[data-care-tab]');
        const toggle = event.target.closest('[data-toggle]');
        const pick = event.target.closest('[data-need]');
        const act = event.target.closest('[data-act]');
        const on = event.target.closest('[data-council-on]');
        const off = event.target.closest('[data-council-off]');
        const unpair = event.target.closest('[data-mentor-off]');
        const answer = event.target.closest('[data-reply]');
        const email = event.target.closest('[data-email]');
        if (tab) {
            ui.tab = tab.dataset.careTab;
            setStatus(status, '');
            redraw();
        } else if (toggle) {
            const id = toggle.dataset.toggle;
            ui.open.has(id) ? ui.open.delete(id) : ui.open.add(id);
            redraw();
        } else if (pick) {
            ui.need[pick.closest('.care-row').dataset.saveId] = pick.dataset.need;
            redraw();
        } else if (act) {
            const id = act.closest('.care-row').dataset.saveId;
            const player = Object.values(data.groups).flat().find(p => p.save_id === id);
            await post('act', { save_id: id, action: act.dataset.act, need: ui.need[id] || player.lowest });
        } else if (on) {
            await post('council', { save_id: on.dataset.councilOn, on: true });
        } else if (off) {
            await post('council', { save_id: off.dataset.councilOff, on: false });
        } else if (answer) {
            await post('reply', { message_id: Number(answer.dataset.reply), choice: answer.dataset.choice });
        } else if (email) {
            await post('email', { email_id: Number(email.dataset.email), action: email.dataset.emailAct });
        } else if (unpair) {
            await post('mentor', { mentee: unpair.dataset.mentorOff, mentor: null });
        } else if (event.target.id === 'care_simulate') {
            setStatus(status, 'Simulating...');
            const result = await call('/care/simulate', { preset: data.preset }, status);
            if (!result.error) {
                setStatus(status, '');
                ui.sim = result;
                redraw();
            }
        }
    });
    body.addEventListener('change', event => {
        if (event.target.id === 'care_preset') {
            ui.sim = null;
            post('preset', { preset: event.target.value }, 'Difficulty set to ' + event.target.value + '.');
        }
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
