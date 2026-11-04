// The team group chat ("WYO Group Chat") in the phone's Messages app: the players' post-game messages and their answers to the coach,
// arriving one at a time (paced by group_chat.py), with notifications, a typing indicator and a compose box.

import { esc, setStatus, headshot, selectedModel } from './utils.js';
import { addThread, refreshMessages, threadHeader } from './phone.js';
import { notify } from './notify.js';

const POLL_MS = 5000;
const GAP_FOR_TIME = 15 * 60;   // a time stamp above any message 15+ minutes after the one before
const chat = { messages: [], reactions: {}, members: 0, unread: 0, typing: null, writing: false, loaded: false, picker: null };
const EMOJI = ['❤️', '👍', '😂', '‼️', '❓'];

// The tapbacks on a message (a small pill on its corner), and the picker when it's the one being reacted to
function tapbacks(m) {
    const groups = chat.reactions[m.id] || [];
    const pill = groups.length
        ? '<span class="tapbacks' + (m.me ? ' tapbacks--me' : '') + '" title="' + esc(groups.map(g => g.names.join(', ') + ' ' + g.emoji).join(' · ')) + '">' +
              groups.map(g => '<span class="tapback' + (g.mine ? ' is-mine' : '') + '">' + g.emoji + (g.count > 1 ? '<b>' + g.count + '</b>' : '') + '</span>').join('') + '</span>'
        : '';
    const mine = (groups.find(g => g.mine) || {}).emoji;
    const picker = chat.picker === m.id
        ? '<span class="tapback-picker' + (m.me ? ' tapback-picker--me' : '') + '">' + EMOJI.map(e =>
              '<button type="button" class="tapback-choice' + (e === mine ? ' is-mine' : '') + '" data-react="' + m.id + '" data-emoji="' + e + '" aria-label="React ' + e + '">' + e + '</button>').join('') + '</span>'
        : '';
    return pill + picker;
}

function timeLabel(at) {
    const d = new Date(at * 1000);
    const now = new Date();
    const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
    const clock = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (days === 0) return 'Today ' + clock;
    if (days === 1) return 'Yesterday ' + clock;
    if (days < 7) return d.toLocaleDateString([], { weekday: 'long' }) + ' ' + clock;
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + clock;
}

function firstName(m) {
    return m.me ? 'You' : (m.author.name || 'A teammate').split(' ')[0];
}

/** "WYO Group Chat": named after whichever school the coach is at now. */
function chatTitle() {
    return (document.getElementById('phone').dataset.teamName || 'Team') + ' Group Chat';
}

function groupAvatar() {
    const phone = document.getElementById('phone');
    const logo = phone.dataset.teamLogo;
    return '<span class="group-avatar">' + (logo ? '<img src="' + esc(logo) + '" alt="">' : esc((phone.dataset.teamName || 'Team').slice(0, 3))) + '</span>';
}

function bubbles() {
    let html = '';
    chat.messages.forEach((m, i) => {
        const prev = chat.messages[i - 1];
        const next = chat.messages[i + 1];
        if (!prev || m.at - prev.at >= GAP_FOR_TIME) html += '<div class="chat-time">' + esc(timeLabel(m.at)) + '</div>';
        const sameAsPrev = prev && !prev.me && !m.me && prev.author.save_id === m.author.save_id && m.at - prev.at < GAP_FOR_TIME;
        const lastOfRun = !next || next.me !== m.me || (!m.me && next.author.save_id !== m.author.save_id) || next.at - m.at >= GAP_FOR_TIME;
        if (m.me) {
            html += '<div class="bubble bubble--me" data-bubble="' + m.id + '">' + esc(m.text) + tapbacks(m) + '</div>';
            if (!next || !next.me) html += '<div class="bubble-receipt">' + (chat.messages.slice(i + 1).some(x => !x.me) ? 'Read' : 'Delivered') + '</div>';
            return;
        }
        html += '<div class="group-line' + (lastOfRun ? ' is-last' : '') + '">' +
                    '<span class="group-line-avatar">' + (lastOfRun ? headshot(m.author.portrait, 'group-headshot') : '') + '</span>' +
                    '<div class="group-line-body">' +
                        (sameAsPrev ? '' : '<button type="button" class="group-name" data-player-id="' + esc(m.author.save_id) + '">' + esc(m.author.name) +
                            (m.author.position ? ' <span>' + esc(m.author.position) + (m.author.jersey ? ' #' + esc(m.author.jersey) : '') + '</span>' : '') + '</button>') +
                        (m.reply_to ? '<div class="group-quote">&#8617; ' + esc(m.reply_to.name.split(' ')[0]) + ': ' + esc(m.reply_to.text) + '</div>' : '') +
                        '<div class="bubble bubble--them" data-bubble="' + m.id + '">' + esc(m.text) + tapbacks(m) + '</div>' +
                    '</div>' +
                '</div>';
    });
    if (!chat.messages.length) {
        html += '<div class="phone-empty">' + (chat.writing ? 'The guys are typing about the last game…' :
            'Quiet so far. After each game the players post here, and you can write to the whole team anytime.') + '</div>';
    }
    return html;
}

function typingLine() {
    if (!chat.typing) return '';
    return '<div class="group-line is-last"><span class="group-line-avatar"></span><div class="group-line-body">' +
               '<div class="typing-name">' + esc(chat.typing) + ' is typing…</div>' +
               '<div class="bubble bubble--them bubble--typing"><span></span><span></span><span></span></div></div></div>';
}

function render(root) {
    if (root.dataset.view !== 'group') {
        root.dataset.view = 'group';
        root.innerHTML = threadHeader(chatTitle(), groupAvatar()).replace('</span></div>',
                '<span class="thread-head-sub">' + esc(chat.members) + ' members</span></span>' +
                '<button type="button" class="group-tool" data-chat-regenerate title="Write the last game\'s post-game chat again">&#8635;</button></div>') +
            '<div class="phone-scroll chat-scroll"><div class="chat group-chat" id="group_chat_list"></div><div id="group_chat_typing"></div>' +
                '<div class="status-text phone-status-text" id="group_chat_status"></div></div>' +
            '<form class="chat-compose" id="group_chat_form"><input id="group_chat_input" maxlength="500" autocomplete="off" placeholder="Message the team" aria-label="Message the team">' +
                '<button type="submit" class="chat-send" aria-label="Send">&#8593;</button></form>';
    }
    update(root, true);
    markRead();
}

function update(root, scroll) {
    const list = root.querySelector('#group_chat_list');
    if (!list) return;
    const box = root.querySelector('.chat-scroll');
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    list.innerHTML = bubbles();
    const sub = root.querySelector('.thread-head-sub');
    if (sub) sub.textContent = chat.members + ' members';
    root.querySelector('#group_chat_typing').innerHTML = typingLine();
    if (scroll || nearBottom) box.scrollTop = box.scrollHeight;
}

async function markRead() {
    if (!chat.unread) return;
    chat.unread = 0;
    refreshMessages();
    await fetch('/phone/chat/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
}

function root() {
    const el = document.getElementById('phone_messages');
    return el && el.dataset.view === 'group' && document.querySelector('#phone .phone-messages.is-active') ? el : null;
}

// A notification when a teammate reacts to one of the coach's messages
function announceReactions(next, announce) {
    if (!announce) return;
    chat.messages.filter(m => m.me).forEach(m => {
        const before = (chat.reactions[m.id] || []).reduce((n, g) => n + g.count - (g.mine ? 1 : 0), 0);
        const after = (next[m.id] || []).filter(g => g.count > (g.mine ? 1 : 0));
        if (after.reduce((n, g) => n + g.count - (g.mine ? 1 : 0), 0) > before) {
            const g = after[after.length - 1];
            const who = g.names.filter(n => n !== 'You');
            notify(chatTitle(), who[who.length - 1] + ' reacted ' + g.emoji + ' to "' + m.text.slice(0, 40) + (m.text.length > 40 ? '…' : '') + '"');
        }
    });
}

function take(data, announce) {
    const lastId = chat.messages.length ? chat.messages[chat.messages.length - 1].id : 0;
    const fresh = data.messages.filter(m => m.id > lastId);
    chat.messages = chat.messages.concat(fresh);
    announceReactions(data.reactions || {}, announce && !root());
    chat.reactions = data.reactions || {};
    chat.members = data.members;
    chat.typing = data.typing;
    chat.writing = data.writing;
    chat.unread = data.unread;
    const open = root();
    if (announce && !open) fresh.filter(m => !m.me).forEach(m => notify(chatTitle(), firstName(m) + ': ' + m.text));
    if (open) {
        update(open, false);
        if (chat.unread) markRead();
    }
    refreshMessages();
}

async function poll() {
    try {
        const since = chat.messages.length ? chat.messages[chat.messages.length - 1].id : 0;
        const res = await fetch('/phone/chat?since=' + since + '&model=' + encodeURIComponent(selectedModel()));
        const data = await res.json();
        if (!data.error) take(data, chat.loaded);
        chat.loaded = true;
    } catch (err) {
        /* the app restarted or went away; the next poll tries again */
    }
}

export function initGroupChat() {
    const phone = document.getElementById('phone');
    if (!phone) return;
    addThread({
        id: 'group', title: chatTitle(), icon: groupAvatar(), render,
        unread: () => chat.unread,
        // The list row follows the newest message
        get preview() {
            const m = chat.messages[chat.messages.length - 1];
            return chat.typing ? chat.typing + ' is typing…' : m ? firstName(m) + ': ' + m.text : 'The whole roster and you';
        },
        get time() {
            const m = chat.messages[chat.messages.length - 1];
            return m ? timeLabel(m.at).replace(/^Today /, '') : '';
        }
    });
    poll();
    setInterval(poll, POLL_MS);

    phone.addEventListener('submit', async event => {
        if (event.target.id !== 'group_chat_form') return;
        event.preventDefault();
        const input = document.getElementById('group_chat_input');
        const status = document.getElementById('group_chat_status');
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        setStatus(status, '');
        const res = await fetch('/phone/chat/send', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                       body: JSON.stringify({ text, model: selectedModel() }) });
        const data = await res.json().catch(() => ({ error: 'HTTP ' + res.status }));
        if (data.error) {
            input.value = text;
            setStatus(status, data.error, true);
            return;
        }
        take(data, false);
        const open = root();
        if (open) update(open, true);
    });
    phone.addEventListener('click', async event => {
        const choice = event.target.closest('[data-react]');
        const bubble = event.target.closest('[data-bubble]');
        const open = root();
        if (choice) {
            chat.picker = null;
            const res = await fetch('/phone/chat/react', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                                            body: JSON.stringify({ msg_id: Number(choice.dataset.react), emoji: choice.dataset.emoji }) });
            const data = await res.json().catch(() => ({ error: 'HTTP ' + res.status }));
            if (!data.error) chat.reactions = data.reactions;
            if (open) update(open, false);
            return;
        }
        if (open && (bubble || chat.picker !== null)) {
            // Tap a bubble to react to it; tap anywhere else to close the picker
            chat.picker = bubble && chat.picker !== Number(bubble.dataset.bubble) ? Number(bubble.dataset.bubble) : null;
            update(open, false);
        }
        if (!event.target.closest('[data-chat-regenerate]')) return;
        if (!confirm("Write the last game's post-game chat again? Messages that haven't arrived yet are replaced.")) return;
        await fetch('/phone/chat/regenerate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: selectedModel() }) });
        setStatus(document.getElementById('group_chat_status'), 'The guys are writing… messages will start arriving shortly.');
    });
}
