// Phone tab: a home screen with three apps. Messages holds the one-on-one texts from players (player care) and, from
// static/js/group-chat.js, the WYO Group Chat; Care is player care itself (rendered by static/js/care.js); Mail holds the
// staff emails. Player care data travels as a 'care:update' event, so every app (and the badges) stays in step.

import { esc, setStatus, headshot } from './utils.js';
import { showTab } from './tabs.js';

const ui = { app: 'home', thread: null, email: null };
let care = null;
const extraThreads = [];   // conversation rows other modules add to the Messages list (the group chat)

export function openApp(name) {
    ui.app = name;
    document.querySelectorAll('#phone .phone-app').forEach(app => app.classList.toggle('is-active', app.dataset.app === name));
    if (name === 'messages') renderMessages();
    if (name === 'mail') renderMail();
}

/** Opens the Phone tab on an app (the tab bar's Care button opens Care). */
export function showPhone(app = 'home') {
    showTab('phone');
    openApp(app);
    if (!care) loadCare();
}

export async function loadCare() {
    try {
        const res = await fetch('/care');
        const data = await res.json();
        if (!data.error) document.dispatchEvent(new CustomEvent('care:update', { detail: data }));
    } catch (err) {
        console.error('BASIC_OS: player care failed to load', err);
    }
}

export async function careAction(action, payload) {
    const res = await fetch('/care/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json().catch(() => ({ error: 'HTTP ' + res.status }));
    if (!data.error) document.dispatchEvent(new CustomEvent('care:update', { detail: data }));
    return data;
}

/** Lets another module list a conversation in Messages: {id, title, preview, time, unread, portrait, render(root)}. */
export function addThread(thread) {
    extraThreads.push(thread);
}

export function refreshMessages() {
    if (ui.app === 'messages') renderMessages();
    updateBadges();
}

// ---------- Badges and widgets ----------

function counts() {
    const extra = extraThreads.reduce((n, t) => n + (t.unread() || 0), 0);
    const texts = care && care.unread ? care.unread.texts : 0;
    return { messages: texts + extra, mail: care && care.unread ? care.unread.emails : 0,
             care: care && care.started ? care.groups.now.length + care.incidents.length : 0 };
}

function updateBadges() {
    const c = counts();
    document.querySelectorAll('#phone [data-badge]').forEach(b => {
        const n = c[b.dataset.badge] || 0;
        b.textContent = n || '';
        b.classList.toggle('is-shown', n > 0);
    });
    const total = c.messages + c.mail + c.care;
    const careButton = document.getElementById('care_open');
    if (careButton) careButton.innerHTML = 'Care' + (c.care ? ' <span class="care-badge">' + c.care + '</span>' : '');
    const tab = document.querySelector('.tab[data-tab="phone"]');
    if (tab) tab.innerHTML = 'Phone' + (total ? ' <span class="care-badge">' + total + '</span>' : '');
}

function renderWidgets(game) {
    const root = document.getElementById('phone_widgets');
    const next = game && !game.is_played
        ? '<div class="phone-widget"><div class="widget-kicker">Next game · Week ' + esc(game.week_id) + '</div>' +
              '<div class="widget-big">' + (game.site === 'Away' ? '@ ' : 'vs ') + esc(game.opponent_name) + '</div>' +
              '<div class="widget-small">' + esc([game.date_text, game.kickoff_text].filter(Boolean).join(' · ')) + '</div></div>'
        : '<div class="phone-widget"><div class="widget-kicker">Next game</div><div class="widget-small">Nothing scheduled</div></div>';
    const c = counts();
    const careWidget = care && care.started
        ? '<button type="button" class="phone-widget phone-widget--care" data-open-app="care"><div class="widget-kicker">Care · Week ' + esc(care.week) + '</div>' +
              '<div class="widget-big">' + esc(care.hours) + '<span class="widget-unit"> of ' + esc(care.hours_total) + ' hrs</span></div>' +
              '<div class="widget-small">' + c.care + ' need you · ' + c.messages + ' texts · ' + c.mail + ' emails</div></button>'
        : '<div class="phone-widget"><div class="widget-kicker">Care</div><div class="widget-small">Starts once the schedule syncs</div></div>';
    root.innerHTML = next + careWidget;
}

// ---------- Messages ----------

function careThreads() {
    return (care && care.phone || []).map(t => ({
        id: 'dm-' + t.save_id, title: t.name, portrait: t.portrait,
        preview: t.messages.length ? (t.messages[t.messages.length - 1].reply || t.messages[t.messages.length - 1].text) : '',
        time: t.messages.length ? 'Week ' + t.messages[t.messages.length - 1].week : '',
        unread: () => (t.waiting ? 1 : 0), render: root => renderDm(root, t)
    }));
}

function renderMessages() {
    const root = document.getElementById('phone_messages');
    const threads = [...extraThreads, ...careThreads()];
    const open = threads.find(t => t.id === ui.thread);
    if (open) {
        open.render(root);
        return;
    }
    ui.thread = null;
    root.innerHTML = '<div class="phone-nav"><button type="button" class="phone-back" data-open-app="home">&#8249; Home</button><span class="phone-nav-title">Messages</span></div>' +
        '<div class="phone-scroll"><ol class="thread-list">' + (threads.map(t =>
            '<li><button type="button" class="thread-row" data-thread="' + esc(t.id) + '">' +
                (t.unread() ? '<span class="thread-dot" aria-label="Unread"></span>' : '<span class="thread-dot-space"></span>') +
                (t.icon || headshot(t.portrait, 'thread-avatar')) +
                '<span class="thread-text"><span class="thread-top"><strong>' + esc(t.title) + '</strong><span class="thread-time">' + esc(t.time || '') + '</span></span>' +
                '<span class="thread-preview">' + esc(t.preview || '') + '</span></span>' +
            '</button></li>').join('') || '<li class="phone-empty">No messages yet.</li>') + '</ol></div>';
}

/** The top bar of an open thread (shared with the group chat). */
export function threadHeader(title, avatar) {
    return '<div class="phone-nav phone-nav--thread"><button type="button" class="phone-back" data-thread-back>&#8249;</button>' +
               '<span class="thread-head">' + avatar + '<span class="thread-head-name">' + esc(title) + '</span></span></div>';
}

function renderDm(root, t) {
    const actions = care.actions;
    let bubbles = '';
    let lastWeek = null;
    t.messages.forEach(m => {
        if (m.week !== lastWeek) bubbles += '<div class="chat-time">Week ' + esc(m.week) + '</div>';
        lastWeek = m.week;
        bubbles += '<div class="bubble bubble--them">' + esc(m.text) + '</div>';
        if (m.reply) bubbles += '<div class="bubble bubble--me">' + esc(m.reply) + '</div><div class="bubble-receipt">Delivered</div>';
        else if (m.status === 'missed') bubbles += '<div class="bubble-receipt bubble-receipt--missed">Left on read</div>';
    });
    const quick = t.waiting
        ? '<div class="quick-replies"><div class="quick-label">' + esc(care.hours) + ' coach hours left</div>' + t.waiting.replies.map(r => {
              const a = actions.find(x => x.key === r.key);
              const hours = a ? a.hours : 0;
              return '<button type="button" class="quick-reply" data-reply="' + t.waiting.message_id + '" data-choice="' + r.key + '"' +
                  (hours > care.hours ? ' disabled title="Not enough hours left this week"' : '') + '>' + esc(r.label) +
                  '<span>' + (hours ? hours + 'h' : 'free, trust -1') + '</span></button>';
          }).join('') + '</div>'
        : '<div class="chat-compose chat-compose--off">He hasn\'t texted this week</div>';
    root.innerHTML = threadHeader(t.name, headshot(t.portrait, 'thread-avatar thread-avatar--small')) +
        '<div class="phone-scroll chat-scroll"><div class="chat">' + bubbles + '</div><div class="status-text phone-status-text" id="dm_status"></div></div>' + quick;
    const scroll = root.querySelector('.chat-scroll');
    scroll.scrollTop = scroll.scrollHeight;
}

// ---------- Mail ----------

function renderMail() {
    const root = document.getElementById('phone_mail');
    const inbox = care && care.inbox || [];
    const email = inbox.find(e => e.email_id === ui.email);
    if (email) {
        root.innerHTML = '<div class="phone-nav"><button type="button" class="phone-back" data-mail-back>&#8249; Inbox</button></div>' +
            '<div class="phone-scroll mail-detail"><h3 class="mail-subject">' + esc(email.subject) + '</h3>' +
                '<div class="mail-from">' + esc(email.sender) + ' · Week ' + esc(email.week) + (email.status !== 'open' ? ' · ' + esc(email.status) : '') + '</div>' +
                '<p class="mail-body">' + esc(email.body) + '</p>' +
                (email.result ? '<p class="mail-done">Done: ' + esc(email.result) + '</p>' : '') +
                (email.status === 'open' ? '<div class="mail-actions"><div class="quick-label">' + esc(care.hours) + ' coach hours left</div>' + email.actions.map(a =>
                    '<button type="button" class="quick-reply" data-email="' + email.email_id + '" data-email-act="' + esc(a.key) + '"' +
                        (a.hours > care.hours ? ' disabled title="Not enough hours left this week"' : '') + '>' + esc(a.label) +
                        '<span>' + esc(a.effect) + ' · ' + (a.hours ? a.hours + 'h' : 'free') + '</span></button>').join('') +
                    '<button type="button" class="quick-reply quick-reply--plain" data-email="' + email.email_id + '" data-email-act="read">' +
                        (email.actions.length ? 'Done' : 'Mark read') + '</button></div>' : '') +
                '<div class="status-text phone-status-text" id="mail_status"></div></div>';
        return;
    }
    ui.email = null;
    root.innerHTML = '<div class="phone-nav"><button type="button" class="phone-back" data-open-app="home">&#8249; Home</button><span class="phone-nav-title">Inbox</span></div>' +
        '<div class="phone-scroll"><ol class="mail-list">' + (inbox.map(e =>
            '<li><button type="button" class="mail-row' + (e.status === 'open' ? ' is-unread' : '') + '" data-email-open="' + e.email_id + '">' +
                '<span class="mail-row-top"><strong>' + esc(e.sender) + '</strong><span class="thread-time">Week ' + esc(e.week) + '</span></span>' +
                '<span class="mail-row-subject">' + esc(e.subject) + '</span><span class="thread-preview">' + esc(e.body) + '</span>' +
            '</button></li>').join('') || '<li class="phone-empty">No email yet. The staff write when the save moves to the next week.</li>') + '</ol></div>';
}

// ---------- Wiring ----------

function tick() {
    const el = document.getElementById('phone_time');
    if (el) el.textContent = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).replace(/\s?[AP]M$/i, '');
}

export function initPhone(game) {
    const phone = document.getElementById('phone');
    if (!phone) return;
    tick();
    setInterval(tick, 15000);
    renderWidgets(game);

    document.addEventListener('care:update', event => {
        care = event.detail;
        renderWidgets(game);
        updateBadges();
        if (ui.app === 'messages') renderMessages();
        if (ui.app === 'mail') renderMail();
    });

    phone.addEventListener('click', async event => {
        const app = event.target.closest('[data-open-app]');
        const thread = event.target.closest('[data-thread]');
        const back = event.target.closest('[data-thread-back]');
        const reply = event.target.closest('[data-reply]');
        const mailOpen = event.target.closest('[data-email-open]');
        const mailBack = event.target.closest('[data-mail-back]');
        const mailAct = event.target.closest('[data-email]');
        if (app) {
            ui.thread = null;
            ui.email = null;
            openApp(app.dataset.openApp);
        } else if (thread) {
            ui.thread = thread.dataset.thread;
            renderMessages();
        } else if (back) {
            ui.thread = null;
            renderMessages();
        } else if (reply) {
            reply.disabled = true;
            const data = await careAction('reply', { message_id: Number(reply.dataset.reply), choice: reply.dataset.choice });
            if (data.error) {
                renderMessages();
                setStatus(document.getElementById('dm_status'), data.error, true);
            }
        } else if (mailOpen) {
            ui.email = Number(mailOpen.dataset.emailOpen);
            renderMail();
        } else if (mailBack) {
            ui.email = null;
            renderMail();
        } else if (mailAct) {
            mailAct.disabled = true;
            const data = await careAction('email', { email_id: Number(mailAct.dataset.email), action: mailAct.dataset.emailAct });
            if (data.error) {
                renderMail();
                setStatus(document.getElementById('mail_status'), data.error, true);
            }
        }
    });

    document.getElementById('care_open').addEventListener('click', () => showPhone('care'));
    document.querySelector('.tab[data-tab="phone"]').addEventListener('click', () => { if (!care) loadCare(); });
    // ?care opens the Care app directly; #phone opens the phone; ?app=messages (or mail) opens that app
    const params = new URLSearchParams(location.search);
    if (params.has('care')) showPhone('care');
    else if (params.get('app')) showPhone(params.get('app'));
    else loadCare();
}
