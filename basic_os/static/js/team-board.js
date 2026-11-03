// Team Board (Locker Room tab): an internal, players-only feed about the last game, with teammates' replies.
// Written by the selected model on request; separate from the public campus feed.

import { esc, setStatus, headshot, postJSON } from './utils.js';
import { longJob } from './notify.js';

function byline(a) {
    return '<div class="board-byline">' + headshot(a.portrait, 'board-headshot') +
               '<button type="button" class="board-name" data-player-id="' + esc(a.save_id) + '">' + esc(a.name) + '</button>' +
               '<span class="board-meta">' + esc(a.position) + (a.jersey ? ' #' + esc(a.jersey) : '') + '</span>' +
               '<span class="board-badge">Player</span>' +
           '</div>';
}

function render(list, board) {
    if (!board || !board.posts.length) {
        list.innerHTML = '<p class="empty-note empty-note--compact">No posts yet. Press Generate to hear from the players about the last game.</p>';
        return;
    }
    list.innerHTML = '<div class="board-week">After Week ' + esc(board.week) + '</div>' + board.posts.map(p =>
        '<article class="board-post">' + byline(p.author) + '<p class="board-text">' + esc(p.text) + '</p>' +
            (p.replies.length ? '<div class="board-replies">' + p.replies.map(r =>
                '<div class="board-reply">' + byline(r.author) + '<p class="board-text">' + esc(r.text) + '</p></div>').join('') + '</div>' : '') +
        '</article>').join('');
}

export function initTeamBoard(board) {
    const list = document.getElementById('team_board_list');
    const button = document.getElementById('team_board_btn');
    const status = document.getElementById('team_board_status');
    if (!list || !button) return;
    render(list, board);
    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, 'The players are posting (about a minute)...');
        try {
            const data = await longJob('The team board', postJSON('/team-board/generate'));
            if (data.error) throw new Error(data.error);
            render(list, data);
            setStatus(status, 'Done.');
            setTimeout(() => setStatus(status, ''), 3000);
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            button.disabled = false;
        }
    });
}
