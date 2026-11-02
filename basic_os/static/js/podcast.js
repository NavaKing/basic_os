// Weekly podcast: host voices, screenshot upload (cropped in the browser so the vision model sees the scoring list
// at full size), a review form for what was read, and the episode feed with a transcript-synced player.

import { esc, postJSON, setStatus, staticUrl, applyTeamColors } from './utils.js';
import { longJob } from './notify.js';

const FULL_MAX_WIDTH = 1600;
// Where the scoring list sits on College Football 27's post-game Scoring Summary screen (fractions of the screenshot)
const SUMMARY_CROP = { x: 0.06, y: 0.42, w: 0.50, h: 0.51 };
const HOSTS_KEY = 'basic_os.podcast_hosts';
const POLL_MS = 1500;

// ---------- Hosts ----------

function savedHosts() {
    try { return JSON.parse(localStorage.getItem(HOSTS_KEY)) || null; } catch { return null; }
}

function currentHosts() {
    return [0, 1].map(i => ({
        name: document.querySelector('.pod-host-name[data-host="' + i + '"]').value.trim(),
        voice: document.querySelector('.pod-host-voice[data-host="' + i + '"]').value
    }));
}

async function initHosts() {
    const data = await (await fetch('/podcast/voices')).json();
    const hosts = savedHosts() || data.defaults;
    const save = () => { try { localStorage.setItem(HOSTS_KEY, JSON.stringify(currentHosts())); } catch { /* per-browser convenience only */ } };
    [0, 1].forEach(i => {
        const name = document.querySelector('.pod-host-name[data-host="' + i + '"]');
        const select = document.querySelector('.pod-host-voice[data-host="' + i + '"]');
        name.value = (hosts[i] || data.defaults[i]).name;
        const voices = data.voices.length ? data.voices : [{ id: data.defaults[i].voice, name: data.defaults[i].name, locale: 'en-US', gender: '', style: '' }];
        select.innerHTML = voices.map(v => '<option value="' + esc(v.id) + '">' + esc(v.name) + ' (' + esc(v.locale) + (v.gender ? ', ' + esc(v.gender) : '') +
            (v.style ? ': ' + esc(v.style) : '') + ')</option>').join('');
        select.value = (hosts[i] || data.defaults[i]).voice;
        name.addEventListener('change', save);
        select.addEventListener('change', save);
    });
    const player = new Audio();
    document.querySelectorAll('.pod-preview').forEach(b => b.addEventListener('click', async () => {
        const host = currentHosts()[Number(b.dataset.host)];
        b.disabled = true;
        try {
            const res = await (await fetch('/podcast/preview?voice=' + encodeURIComponent(host.voice) + '&name=' + encodeURIComponent(host.name))).json();
            if (res.error) throw new Error(res.error);
            player.src = res.audio;
            await player.play();
        } catch (err) {
            setStatus(document.getElementById('pod_status'), 'Preview failed: ' + (err.message || err), true);
        } finally {
            b.disabled = false;
        }
    }));
}

// ---------- Uploads ----------

function toDataUrl(img, sx, sy, sw, sh, scale) {
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(sw * scale);
    canvas.height = Math.round(sh * scale);
    canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/png');
}

function loadImage(file) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('the browser could not open this file as an image'));
        img.src = URL.createObjectURL(file);
    });
}

async function prepare(file) {
    const img = await loadImage(file);
    const w = img.naturalWidth, h = img.naturalHeight;
    const full = toDataUrl(img, 0, 0, w, h, Math.min(1, FULL_MAX_WIDTH / w));
    const summary = toDataUrl(img, w * SUMMARY_CROP.x, h * SUMMARY_CROP.y, w * SUMMARY_CROP.w, h * SUMMARY_CROP.h, 1);
    URL.revokeObjectURL(img.src);
    return { name: file.name, full, summary };
}

function renderUploads(uploads) {
    const box = document.getElementById('pod_uploads');
    box.innerHTML = uploads.map(u => '<figure class="pod-thumb"><img src="' + esc(u.thumb) + '" alt=""><figcaption>' + esc(u.name) +
        '</figcaption><button type="button" class="pod-remove" data-id="' + esc(u.id) + '" aria-label="Remove">&times;</button></figure>').join('');
    box.querySelectorAll('.pod-remove').forEach(b => b.addEventListener('click', async () => {
        await fetch('/events/uploads/' + b.dataset.id, { method: 'DELETE' });
        refreshUploads();
    }));
    document.getElementById('pod_read').disabled = !uploads.length;
}

async function refreshUploads() {
    renderUploads(await (await fetch('/events/uploads')).json());
}

// ---------- Review ----------

function reviewForm(draft) {
    const teamOptions = selected => draft.teams.map(t => '<option' + (t.abbr === selected ? ' selected' : '') + '>' + esc(t.abbr) + '</option>').join('');
    const rows = draft.plays.map((p, i) => '<tr data-index="' + i + '">' +
        '<td><select class="ev-q">' + [1, 2, 3, 4, 5].map(q => '<option value="' + q + '"' + (q === p.quarter ? ' selected' : '') + '>' + (q === 5 ? 'OT' : 'Q' + q) + '</option>').join('') + '</select></td>' +
        '<td><select class="ev-team">' + teamOptions(p.team) + '</select></td>' +
        '<td><input class="ev-text" value="' + esc(p.text) + '"></td>' +
        '<td><input class="ev-clock" value="' + esc(p.clock) + '" size="5"></td>' +
        '<td class="ev-points">' + esc(p.points) + '</td>' +
        '<td><button type="button" class="pod-remove ev-delete" aria-label="Remove play">&times;</button></td></tr>').join('');
    const board = '<table class="pod-board"><thead><tr><th>Team</th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th><th>Plays add up to</th><th>Final</th></tr></thead><tbody>' +
        draft.teams.map((t, i) => '<tr><td><b>' + esc(t.name) + '</b> <span class="muted">' + esc(t.abbr) + '</span></td>' +
            t.quarters.slice(0, 4).map(q => '<td>' + esc(q) + '</td>').join('') + '<td>' + esc(t.total) + '</td>' +
            '<td><input class="ev-final" data-team="' + i + '" value="' + esc(t.final) + '" size="3"></td></tr>').join('') + '</tbody></table>';
    return '<h3>Check what was read</h3>' +
        (draft.warnings.length ? '<div class="pod-warning">' + draft.warnings.map(esc).join('<br>') + '</div>' : '<div class="pod-ok">The scoring plays add up to the final score.</div>') +
        board +
        '<table class="pod-plays"><thead><tr><th>Qtr</th><th>Team</th><th>Scoring play</th><th>Clock</th><th>Pts</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>' +
        '<div class="pod-actions"><button type="button" class="btn-secondary" id="pod_add">Add a play</button>' +
        '<button type="button" id="pod_generate">Record the episode</button><div class="status-text" id="pod_gen_status"></div></div>';
}

function collect(draft, root) {
    const plays = [...root.querySelectorAll('.pod-plays tbody tr')].map(tr => ({
        quarter: Number(tr.querySelector('.ev-q').value), team: tr.querySelector('.ev-team').value,
        text: tr.querySelector('.ev-text').value.trim(), clock: tr.querySelector('.ev-clock').value.trim()
    })).filter(p => p.text);
    const teams = draft.teams.map((t, i) => ({ ...t, final: Number(root.querySelector('.ev-final[data-team="' + i + '"]').value) }));
    return { teams, plays };
}

function showReview(draft, onDone) {
    const root = document.getElementById('pod_review');
    root.hidden = false;
    root.innerHTML = reviewForm(draft);
    root.querySelectorAll('.ev-delete').forEach(b => b.addEventListener('click', () => {
        const current = collect(draft, root);
        current.plays.splice(Number(b.closest('tr').dataset.index), 1);
        showReview({ ...draft, ...current }, onDone);
    }));
    document.getElementById('pod_add').addEventListener('click', () => {
        const current = collect(draft, root);
        current.plays.push({ quarter: 4, team: draft.teams[0].abbr, text: '', clock: '' });
        showReview({ ...draft, ...current, plays: current.plays.map(p => ({ points: '', ...p })) }, onDone);
        root.querySelector('.pod-plays tbody tr:last-child .ev-text').focus();
    });
    document.getElementById('pod_generate').addEventListener('click', async e => {
        const status = document.getElementById('pod_gen_status');
        e.target.disabled = true;
        setStatus(status, 'Starting...');
        const timer = setInterval(async () => {
            try {
                const p = await (await fetch('/generate/progress')).json();
                if (p.running) setStatus(status, p.step + (p.detail ? ' (' + p.detail + ')' : '') + '... ' + p.elapsed + 's');
            } catch { /* keep waiting */ }
        }, POLL_MS);
        try {
            const data = await longJob('Your podcast episode', postJSON('/podcast/generate', { draft: collect(draft, root), hosts: currentHosts() }));
            if (data.error) throw new Error(data.error);
            root.hidden = true;
            root.innerHTML = '';
            onDone(data.episodes, data.warning);
        } catch (err) {
            setStatus(status, String(err.message || err), true);
            e.target.disabled = false;
        } finally {
            clearInterval(timer);
        }
    });
}

// ---------- Episodes ----------

function boxScore(game) {
    const quarters = Math.max(4, ...game.teams.map(t => t.quarters.length));
    const top = Math.max(...game.teams.map(x => x.final));
    return '<table class="box-score pod-box"><thead><tr><th>Team</th>' + Array.from({ length: quarters }, (_, i) => '<th>' + (i < 4 ? 'Q' + (i + 1) : 'OT') + '</th>').join('') +
        '<th>T</th></tr></thead><tbody>' + game.teams.map(t => '<tr class="' + (t.final === top ? 'box-winner' : '') + '"><td>' +
            (t.logo ? '<img class="team-logo recap-logo" src="' + esc(t.logo) + '" alt="" data-team-id="' + esc(t.team_id) + '">' : '<span class="team-chip" data-color="' + esc(t.color || '') + '">' + esc(t.abbr) + '</span>') +
            '<span class="team-name">' + esc(t.name) + '</span></td>' +
            Array.from({ length: quarters }, (_, i) => '<td class="box-num">' + esc(t.quarters[i] ?? 0) + '</td>').join('') +
            '<td class="box-num box-total">' + esc(t.final) + '</td></tr>').join('') + '</tbody></table>';
}

/** An episode as a printed magazine page (static/css/magazine.css): the transcript reads like a Q&A interview. */
/** The headlines a weekly episode covered, as a list for its page. */
function headlineList(ep) {
    return '<ol class="mag-numbered pod-headlines">' + (ep.game.headlines || []).map(h => '<li><p>' + esc(h) + '</p></li>').join('') + '</ol>';
}

function isWeekly(ep) {
    return ep.game.kind === 'weekly';
}

function episodeCard(ep) {
    if (isWeekly(ep)) return weeklyCard(ep);
    const lines = ep.script.map((line, i) => '<li class="pod-line pod-line--' + line.host + '" data-line="' + i + '"><b>' + esc(ep.hosts[line.host].name) + ':</b> ' + esc(line.text) + '</li>').join('');
    const plays = ep.game.plays.map(p => '<div class="mag-post"><b>' + (p.quarter === 5 ? 'OT' : 'Q' + esc(p.quarter)) + ' &middot; ' + esc(p.clock) + ' &middot; ' + esc(p.team) + '</b>' + esc(p.text) + '</div>').join('');
    const [a, b] = ep.game.teams;
    const winner = a.final >= b.final ? a : b, loser = winner === a ? b : a;
    const week = ep.week_num !== null ? 'Week ' + esc(ep.week_num) : 'This week';
    return '<article class="mag-issue pod-episode" data-episode="' + esc(ep.episode_id) + '">' +
        '<div class="mag-folio"><span>Between the Numbers &middot; ' + week + '</span><span>Episode ' + esc(ep.episode_id) + ' &middot; ' + ep.script.length + ' segments</span></div>' +
        '<div class="mag-top"><div class="mag-top-text">' +
            '<h3 class="mag-kicker-headline">' + esc(a.name) + ' vs ' + esc(b.name) + ', by the numbers</h3>' +
            '<p class="mag-byline">With ' + esc(ep.hosts[0].name) + ' and ' + esc(ep.hosts[1].name) + '</p></div>' +
            '<div class="mag-badge"><span class="mag-badge-top">Final</span><span class="mag-badge-main">' + esc(winner.final) + '-' + esc(loser.final) + '</span>' +
            '<span class="mag-badge-bottom">' + esc(winner.abbr) + ' wins</span></div></div>' +
        '<div class="mag-grid">' +
            '<div class="mag-col mag-col--left">' +
                (ep.cover_image ? '<img class="pod-cover" src="' + esc(staticUrl(ep.cover_image)) + '" alt="">' : '<div class="pod-cover pod-cover--blank">ON AIR</div>') +
                playerControls(ep) +
                '<h4 class="mag-feature-title">The Scoring Summary</h4><div class="mag-bubble">' + plays + '</div>' +
            '</div>' +
            '<div class="mag-col mag-col--center">' +
                '<h2 class="mag-slab">' + esc(ep.title) + '</h2>' +
                '<div class="mag-strap">' + (ep.summary ? esc(ep.summary) : 'Two hosts break the game down') + '</div>' +
                '<ol class="pod-transcript">' + lines + '</ol>' +
            '</div>' +
            '<div class="mag-col mag-col--right">' +
                '<h4 class="mag-feature-title">The Box Score</h4>' + boxScore(ep.game) +
                '<p class="mag-small">Click any line of the transcript to hear it.</p>' +
                '<button type="button" class="btn-secondary pod-delete" data-id="' + esc(ep.episode_id) + '">Delete this episode</button>' +
            '</div>' +
        '</div></article>';
}

/** Controls shared by both kinds of episode page: play, progress and download, or retry when lines are missing. */
function playerControls(ep) {
    const recorded = ep.script.filter(l => l.audio).length;
    return recorded === ep.script.length
        ? '<div class="pod-controls"><button type="button" class="pod-play">▶ Play episode</button>' +
          '<div class="pod-progress"><progress class="pod-bar" max="' + ep.script.length + '" value="0"></progress><span class="pod-now">Ready</span></div>' +
          (ep.audio_file ? '<a class="pod-download" href="' + esc(staticUrl(ep.audio_file)) + '" download>Download MP3</a>' : '') + '</div>'
        : '<p class="mag-small">' + recorded + ' of ' + ep.script.length + ' lines are recorded; Microsoft\'s voice service dropped the rest. The script is here.</p>' +
          '<button type="button" class="pod-retry" data-id="' + esc(ep.episode_id) + '">Retry recording</button><div class="status-text pod-retry-status"></div>';
}

function weeklyCard(ep) {
    const lines = ep.script.map((line, i) => '<li class="pod-line pod-line--' + line.host + '" data-line="' + i + '"><b>' + esc(ep.hosts[line.host].name) + ':</b> ' + esc(line.text) + '</li>').join('');
    return '<article class="mag-issue pod-episode" data-episode="' + esc(ep.episode_id) + '">' +
        '<div class="mag-folio"><span>Between the Numbers Weekly &middot; Week ' + esc(ep.week_num) + '</span><span>Episode ' + esc(ep.episode_id) + ' &middot; ' + ep.script.length + ' segments</span></div>' +
        '<div class="mag-top"><div class="mag-top-text">' +
            '<h3 class="mag-kicker-headline">Around college football after Week ' + esc(ep.week_num) + '</h3>' +
            '<p class="mag-byline">With ' + esc(ep.hosts[0].name) + ' and ' + esc(ep.hosts[1].name) + '</p></div>' +
            '<div class="mag-badge"><span class="mag-badge-top">Weekly</span><span class="mag-badge-main">WK ' + esc(ep.week_num) + '</span>' +
            '<span class="mag-badge-bottom">Around the league</span></div></div>' +
        '<div class="mag-grid">' +
            '<div class="mag-col mag-col--left">' +
                (ep.cover_image ? '<img class="pod-cover" src="' + esc(staticUrl(ep.cover_image)) + '" alt="">' : '<div class="pod-cover pod-cover--blank">ON AIR</div>') +
                playerControls(ep) +
            '</div>' +
            '<div class="mag-col mag-col--center">' +
                '<h2 class="mag-slab">' + esc(ep.title) + '</h2>' +
                '<div class="mag-strap">' + (ep.summary ? esc(ep.summary) : 'Two hosts go around the league') + '</div>' +
                '<ol class="pod-transcript">' + lines + '</ol>' +
            '</div>' +
            '<div class="mag-col mag-col--right">' +
                '<h4 class="mag-feature-title">The Headlines</h4>' + headlineList(ep) +
                '<p class="mag-small">Click any line of the transcript to hear it.</p>' +
                '<button type="button" class="btn-secondary pod-delete" data-id="' + esc(ep.episode_id) + '">Delete this episode</button>' +
            '</div>' +
        '</div></article>';
}

/** Plays the episode one line at a time, highlighting the line being read; clicking a line jumps to it. */
function wirePlayer(card, ep) {
    const button = card.querySelector('.pod-play');
    if (!button) return;
    const audio = new Audio();
    const bar = card.querySelector('.pod-bar');
    const now = card.querySelector('.pod-now');
    let index = 0;
    const mark = () => {
        card.querySelectorAll('.pod-line').forEach(li => li.classList.toggle('is-playing', Number(li.dataset.line) === index && !audio.paused));
        bar.value = index;
        now.textContent = (index + 1) + ' of ' + ep.script.length + ' · ' + ep.hosts[ep.script[index].host].name;
    };
    const playLine = i => {
        index = i;
        if (index >= ep.script.length) { index = 0; audio.pause(); button.textContent = '▶ Play episode'; mark(); now.textContent = 'Finished'; return; }
        audio.src = staticUrl(ep.script[index].audio);
        audio.play().then(mark);
        button.textContent = '❚❚ Pause';
        const line = card.querySelector('.pod-line[data-line="' + index + '"]');
        if (line) line.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    };
    audio.addEventListener('ended', () => playLine(index + 1));
    button.addEventListener('click', () => {
        if (!audio.src) return playLine(0);
        if (audio.paused) { audio.play().then(mark); button.textContent = '❚❚ Pause'; }
        else { audio.pause(); button.textContent = '▶ Resume'; mark(); }
    });
    card.querySelectorAll('.pod-line').forEach(li => li.addEventListener('click', () => playLine(Number(li.dataset.line))));
}

/** A Back Catalog entry: cover, title, the episode's MP3 in a native player, and the write-up (summary and transcript). */
function archiveItem(ep) {
    const recorded = ep.script.filter(l => l.audio).length;
    const [a, b] = ep.game.teams;
    const kicker = isWeekly(ep) ? 'Week ' + esc(ep.week_num) + ' &middot; Between the Numbers Weekly'
        : (ep.week_num !== null ? 'Week ' + esc(ep.week_num) + ' &middot; ' : '') + esc(a.name) + ' ' + esc(a.final) + ', ' + esc(b.name) + ' ' + esc(b.final);
    const transcript = ep.script.map(line => '<p class="pod-archive-line"><b>' + esc(ep.hosts[line.host].name) + ':</b> ' + esc(line.text) + '</p>').join('');
    return '<li class="pod-archive-item">' +
        (ep.cover_image ? '<img class="pod-archive-cover" src="' + esc(staticUrl(ep.cover_image)) + '" alt="" loading="lazy">' : '<div class="pod-archive-cover pod-cover--blank">ON AIR</div>') +
        '<div class="pod-archive-body">' +
            '<div class="mag-numbered-kicker">' + kicker + '</div>' +
            '<h3 class="mag-card-title">' + esc(ep.title) + '</h3>' +
            (ep.summary ? '<p class="mag-card-text">' + esc(ep.summary) + '</p>' : '') +
            (ep.audio_file ? '<audio class="pod-archive-audio" controls preload="none" src="' + esc(staticUrl(ep.audio_file)) + '"></audio>'
                : '<p class="mag-small">' + recorded + ' of ' + ep.script.length + ' lines recorded.</p>' +
                  '<button type="button" class="pod-retry" data-id="' + esc(ep.episode_id) + '">Retry recording</button><div class="status-text pod-retry-status"></div>') +
            '<details class="pod-archive-writeup"><summary>Read the write-up</summary>' + transcript + '</details>' +
            '<div class="pod-archive-actions">' + (ep.audio_file ? '<a class="pod-download" href="' + esc(staticUrl(ep.audio_file)) + '" download>Download MP3</a>' : '') +
            '<button type="button" class="btn-secondary pod-delete" data-id="' + esc(ep.episode_id) + '">Delete</button></div>' +
        '</div></li>';
}

function wireButtons(root) {
    root.querySelectorAll('.pod-retry').forEach(b => b.addEventListener('click', async () => {
        const note = b.nextElementSibling;
        b.disabled = true;
        setStatus(note, 'Recording the missing lines...');
        try {
            const data = await longJob('The podcast recording', postJSON('/podcast/' + b.dataset.id + '/record'));
            if (data.error) throw new Error(data.error);
            renderFeed(data.episodes);
            if (data.warning) setStatus(document.getElementById('pod_status'), data.warning, true);
        } catch (err) {
            setStatus(note, String(err.message || err), true);
            b.disabled = false;
        }
    }));
    root.querySelectorAll('.pod-delete').forEach(b => b.addEventListener('click', async () => {
        if (!confirm('Delete this episode, its audio and its cover art?')) return;
        renderFeed(await (await fetch('/podcast/' + b.dataset.id, { method: 'DELETE' })).json());
    }));
}

/** episodes are newest first: the newest is the full magazine page, the rest go to the Back Catalog. */
function renderFeed(episodes) {
    const feed = document.getElementById('pod_feed');
    const archive = document.getElementById('pod_archive');
    const [latest, ...older] = episodes || [];
    feed.innerHTML = latest ? episodeCard(latest) : '<div class="panel empty-note">No episodes yet. Pick a game or upload its screenshots above to record one.</div>';
    applyTeamColors(feed);
    if (latest) wirePlayer(feed.querySelector('[data-episode="' + latest.episode_id + '"]'), latest);
    archive.hidden = !older.length;
    document.getElementById('pod_archive_list').innerHTML = older.map(archiveItem).join('');
    wireButtons(feed);
    wireButtons(archive);
}

// ---------- Entry point ----------

export function initPodcast(episodes, uploads, draft) {
    const input = document.getElementById('pod_files');
    const drop = document.getElementById('pod_drop');
    const status = document.getElementById('pod_status');

    async function upload(files) {
        const images = [...files].filter(f => f.type.startsWith('image/'));
        for (const [i, file] of images.entries()) {
            setStatus(status, 'Uploading ' + (i + 1) + ' of ' + images.length + '...');
            try {
                const res = await postJSON('/events/uploads', await prepare(file));
                if (res.error) throw new Error(res.error);
            } catch (err) {
                setStatus(status, 'Could not upload ' + file.name + ': ' + (err.message || err), true);
                return;
            }
        }
        setStatus(status, images.length ? 'Ready. Add more, or read the screenshots.' : '');
        refreshUploads();
    }

    input.addEventListener('change', () => { upload(input.files); input.value = ''; });
    drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('is-over'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
    drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('is-over'); upload(e.dataTransfer.files); });

    document.getElementById('pod_clear').addEventListener('click', async () => {
        await fetch('/events/uploads', { method: 'DELETE' });
        document.getElementById('pod_review').hidden = true;
        refreshUploads();
        setStatus(status, '');
    });

    const done = (list, warning) => {
        renderFeed(list);
        refreshUploads();
        setStatus(status, warning || 'Episode recorded. Any screenshots were deleted.', Boolean(warning));
    };
    document.getElementById('pod_read').addEventListener('click', async e => {
        e.target.disabled = true;
        setStatus(status, 'Reading the screenshots (about 10 seconds each)...');
        try {
            const data = await longJob('The screenshot reading', postJSON('/events/read'));
            if (data.error) throw new Error(data.error);
            setStatus(status, 'Check the plays below, fix anything that was misread, then record the episode.');
            showReview(data, done);
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            e.target.disabled = false;
        }
    });

    // Games whose scoring summary the app copied from the save
    const picker = document.getElementById('pod_save_game');
    const readSave = document.getElementById('pod_read_save');
    fetch('/podcast/save-games').then(r => r.json()).then(games => {
        picker.innerHTML = games.length
            ? games.map(g => '<option value="' + esc(g.game_id) + '">' + (g.ours ? '★ ' : '') + esc(g.label) + '</option>').join('')
            : '<option value="">No games captured yet: they appear after the next sync following a game</option>';
        readSave.disabled = !games.length;
    }).catch(() => { picker.innerHTML = '<option value="">Could not load the saved games</option>'; readSave.disabled = true; });
    readSave.addEventListener('click', async () => {
        if (!picker.value) return;
        readSave.disabled = true;
        try {
            const data = await postJSON('/events/read-save', { game_id: Number(picker.value) });
            if (data.error) throw new Error(data.error);
            setStatus(status, 'Loaded from your save. Name any scorer shown as just "Touchdown", then record the episode.');
            showReview(data, done);
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            readSave.disabled = false;
        }
    });

    // Between the Numbers Weekly: around the league from one week's recap
    const weekly = document.getElementById('pod_weekly');
    weekly.addEventListener('click', async () => {
        const week = document.getElementById('pod_weekly_week').value;
        if (!week) return;
        weekly.disabled = true;
        setStatus(status, 'Starting...');
        const timer = setInterval(async () => {
            try {
                const p = await (await fetch('/generate/progress')).json();
                if (p.running) setStatus(status, p.step + (p.detail ? ' (' + p.detail + ')' : '') + '... ' + p.elapsed + 's');
            } catch { /* keep waiting */ }
        }, POLL_MS);
        try {
            const data = await longJob('Your weekly episode', postJSON('/podcast/weekly/generate', { week: Number(week), hosts: currentHosts() }));
            if (data.error) throw new Error(data.error);
            done(data.episodes, data.warning);
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            clearInterval(timer);
            weekly.disabled = false;
        }
    });

    initHosts().catch(err => setStatus(status, 'Could not load the voices: ' + err, true));
    renderUploads(uploads || []);
    renderFeed(episodes || []);
    if (draft) showReview(draft, done);
}
