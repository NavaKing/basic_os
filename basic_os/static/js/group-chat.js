// The WYO Group Chat in the phone's Messages app: the players' post-game messages and their answers to the coach,
// arriving one at a time (paced by group_chat.py), with notifications, a typing indicator and a compose box.

import { esc, setStatus, headshot, selectedModel } from './utils.js';
import { addThread, refreshMessages, threadHeader } from './phone.js';
import { notify } from './notify.js';

const POLL_MS = 5000;
const GAP_FOR_TIME = 15 * 60;   // a time stamp above any message 15+ minutes after the one before
const chat = { messages: [], members: 0, unread: 0, typing: null, writing: false, loaded: false };

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

function groupAvatar() {
    const phone = document.getElementById('phone');
    const logo = phone.dataset.teamLogo;
    return '<span class="group-avatar">' + (logo ? '<img src="' + esc(logo) + '" alt="">' : esc((phone.dataset.teamName || 'WYO').slice(0, 3))) + '</span>';
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
            html += '<div class="bubble bubble--me">' + esc(m.text) + '</div>';
            if (!next || !next.me) html += '<div class="bubble-receipt">' + (chat.messages.slice(i + 1).some(x => !x.me) ? 'Read' : 'Delivered') + '</div>';
            return;
        }
        html += '<div class="group-line' + (lastOfRun ? ' is-last' : '') + '">' +
                    '<span class="group-line-avatar">' + (lastOfRun ? headshot(m.author.portrait, 'group-headshot') : '') + '</span>' +
                    '<div class="group-line-body">' +
                        (sameAsPrev ? '' : '<button type="button" class="group-name" data-player-id="' + esc(m.author.save_id) + '">' + esc(m.author.name) +
                            (m.author.position ? ' <span>' + esc(m.author.position) + (m.author.jersey ? ' #' + esc(m.author.jersey) : '') + '</span>' : '') + '</button>') +
                        (m.reply_to ? '<div class="group-quote">&#8617; ' + esc(m.reply_to.name.split(' ')[0]) + ': ' + esc(m.reply_to.text) + '</div>' : '') +
                        '<div class="bubble bubble--them">' + esc(m.text) + '</div>' +
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
        root.innerHTML = threadHeader('WYO Group Chat', groupAvatar()).replace('</span></div>',
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

function take(data, announce) {
    const lastId = chat.messages.length ? chat.messages[chat.messages.length - 1].id : 0;
    const fresh = data.messages.filter(m => m.id > lastId);
    chat.messages = chat.messages.concat(fresh);
    chat.members = data.members;
    chat.typing = data.typing;
    chat.writing = data.writing;
    chat.unread = data.unread;
    const open = root();
    if (announce && !open) fresh.filter(m => !m.me).forEach(m => notify('WYO Group Chat', firstName(m) + ': ' + m.text));
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
        id: 'group', title: 'WYO Group Chat', icon: groupAvatar(), render,
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
        if (!event.target.closest('[data-chat-regenerate]')) return;
        if (!confirm("Write the last game's post-game chat again? Messages that haven't arrived yet are replaced.")) return;
        await fetch('/phone/chat/regenerate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: selectedModel() }) });
        setStatus(document.getElementById('group_chat_status'), 'The guys are writing… messages will start arriving shortly.');
    });
}
