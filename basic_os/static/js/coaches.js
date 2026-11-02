// Coaches tab: the weekly game plan (matchups from the save's ratings plus AI coaching notes)
// and the coaches news column (top 10 and hot seat for HCs, OCs and DCs).

import { esc, postJSON, setStatus, applyTeamColors } from './utils.js';

const GRADE_BARS = { decisive: 3, clear: 2, slight: 1 };
const SECTIONS = [['keys', 'Keys'], ['staff', 'Their staff'], ['availability', 'Availability'], ['qbs', 'Quarterbacks'],
                  ['attack', 'Attack'], ['stop', 'Stop'], ['tape', 'Tale of the tape'], ['press', 'Press room']];

// ---------- Small pieces ----------

function headshot(url, cls = '') {
    return '<span class="headshot ' + cls + '">' + (url ? '<img src="' + esc(url) + '" alt="" loading="lazy">' : '') + '</span>';
}

function logo(team, cls) {
    return team.logo
        ? '<img class="' + cls + '" src="' + esc(team.logo) + '" alt="" data-team-id="' + esc(team.id) + '">'
        : '<span class="team-chip ' + cls + '" data-color="' + esc(team.color || '') + '" data-team-id="' + esc(team.id) + '">' + esc(team.short || '') + '</span>';
}

function sectionHead(kicker, title, aside = '') {
    return '<div class="plan-head"><div><div class="plan-kicker">' + esc(kicker) + '</div><h3 class="plan-title">' + esc(title) + '</h3></div>' +
        (aside ? '<div class="plan-aside">' + aside + '</div>' : '') + '</div>';
}

function bullets(items, icon, empty) {
    if (!items || !items.length) return '<div class="plan-empty">' + esc(empty) + '</div>';
    return '<ul class="plan-bullets">' + items.map(text => '<li><span class="plan-bullet-icon">' + icon + '</span>' + esc(text) + '</li>').join('') + '</ul>';
}

function kickoff(minutes) {
    if (minutes === null || minutes === undefined) return '';
    const h = Math.floor(minutes / 60), m = minutes % 60;
    return ((h + 11) % 12 + 1) + ':' + String(m).padStart(2, '0') + (h < 12 ? ' AM' : ' PM');
}

function longDate(iso) {
    if (!iso) return 'Date TBD';
    const d = new Date(iso + 'T12:00:00');
    return d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' });
}

// ---------- Header ----------

function coachBox(side) {
    const hc = side.staff.find(s => s.short_role === 'HC');
    if (!hc) return '';
    return '<div class="plan-coach">' + headshot(hc.portrait) +
        '<div><div class="plan-coach-name">' + esc(hc.name) + '</div>' +
        '<div class="plan-coach-scheme"><b>OFF</b> ' + esc(side.off_scheme) + '</div>' +
        '<div class="plan-coach-scheme"><b>DEF</b> ' + esc(side.def_scheme) + '</div></div></div>';
}

function teamSide(side, label, align) {
    return '<div class="plan-side plan-side--' + align + '" data-color="' + esc(side.color || '') + '">' +
        logo(side, 'plan-side-logo') +
        '<div class="plan-side-id">' +
            '<div class="plan-side-label">' + label + '</div>' +
            '<div class="plan-side-name team-link" data-team-id="' + esc(side.id) + '">' + esc(side.name) + '</div>' +
            '<div class="plan-side-record">' + esc(side.record_text) + '</div>' +
            coachBox(side) +
        '</div></div>';
}

function header(p) {
    const venueWord = p.site === 'Away' ? '@' : 'VS';
    return '<div class="plan-banner">' +
        teamSide(p.us, 'Us', 'left') +
        '<div class="plan-center">' +
            '<div class="plan-vs">' + venueWord + '</div>' +
            '<div class="plan-odds"><span class="plan-odds-us">' + p.win_probability + '%</span><span class="plan-odds-label">Win probability (est.)</span><span class="plan-odds-them">' + (100 - p.win_probability) + '%</span></div>' +
            '<progress class="plan-odds-bar" max="100" value="' + p.win_probability + '"></progress>' +
            '<div class="plan-line"><strong>' + esc(p.line) + '</strong><span>Line (est.)</span></div>' +
            '<div class="plan-when">' + esc(longDate(p.date)) + ' <span>' + esc(kickoff(p.kickoff_minutes)) + '</span></div>' +
            '<div class="plan-venue">' + esc(p.venue || '') + '</div>' +
            '<button type="button" class="plan-generate" id="plan_generate">' + (p.generated ? 'Rewrite the game plan' : 'Write the game plan') + '</button>' +
            '<div class="status-text" id="plan_status"></div>' +
        '</div>' +
        teamSide(p.them, 'Opponent', 'right') +
    '</div>';
}

// ---------- Sections ----------

function keysAndStaff(p) {
    const keys = p.keys.length ? '<ol class="plan-keys">' + p.keys.map((k, i) => '<li><span>' + (i + 1) + '</span>' + esc(k) + '</li>').join('') + '</ol>'
        : '<div class="plan-empty">Press "Write the game plan" for the keys to this game.</div>';
    const staff = '<div class="plan-staff">' + p.them.staff.map(s => '<div class="plan-staff-member">' + headshot(s.portrait) +
        '<div><div class="plan-coach-name">' + esc(s.name) + '</div><div class="plan-staff-role">' + esc(s.role) + '</div></div></div>').join('') + '</div>';
    const injuries = side => side.injuries.length
        ? side.injuries.map(i => '<div class="plan-injury"><b>#' + esc(i.jersey) + ' ' + esc(i.name) + '</b> ' + esc(i.position) + ' &middot; ' + esc(i.injury) + ' <span class="plan-injury-status">' + esc(i.status) + '</span></div>').join('')
        : '<div class="plan-empty plan-empty--inline">Full strength.</div>';
    return '<div class="plan-row plan-row--3">' +
        '<div class="panel plan-card" id="plan-keys">' + sectionHead('The plan', 'Keys to the game') + keys + '</div>' +
        '<div class="panel plan-card" id="plan-staff">' + sectionHead('Their sideline', 'How ' + p.them.name + ' coach it', esc(p.them.off_scheme) + ' &middot; ' + esc(p.them.def_scheme)) +
            staff + bullets(p.staff_notes, '', 'Scheme tendencies appear when the game plan is written.') + '</div>' +
        '<div class="panel plan-card" id="plan-availability">' + sectionHead('Injury report', 'Availability') +
            '<div class="plan-avail-team">' + logo(p.them, 'team-logo') + esc(p.them.name) + '</div>' + injuries(p.them) +
            '<div class="plan-avail-team">' + logo(p.us, 'team-logo') + esc(p.us.name) + '</div>' + injuries(p.us) + '</div>' +
    '</div>';
}

function qbPanel(qb, kicker, title, notes, icon, emptyNotes) {
    if (!qb) return '<div class="panel plan-card">' + sectionHead(kicker, title) + '<div class="plan-empty">No quarterback found.</div></div>';
    const stats = qb.has_stats
        ? '<div class="plan-statline">' + qb.stats.map(s => '<div><b>' + esc(s.value) + '</b><span>' + esc(s.label) + '</span></div>').join('') + '</div>'
        : '<div class="plan-empty plan-empty--inline">He has not thrown a pass this season.</div>';
    const ratings = '<div class="plan-ratings">' + qb.ratings.map(r => '<div class="plan-rating"><span>' + esc(r.label) + '</span>' +
        '<meter min="0" max="100" low="60" high="80" optimum="100" value="' + esc(r.value) + '"></meter><b>' + esc(r.value) + '</b></div>').join('') + '</div>';
    return '<div class="panel plan-card">' + sectionHead(kicker, title) +
        '<div class="plan-qb">' +
            '<div class="plan-qb-id">' + headshot(qb.portrait, 'headshot--lg') + '<div class="plan-qb-jersey">#' + esc(qb.jersey) + '</div>' +
                '<div class="plan-qb-first">' + esc(qb.first) + '</div><div class="plan-qb-last">' + esc(qb.last) + '</div>' +
                '<div class="plan-qb-meta">' + esc(qb.class) + ', ' + esc(qb.handed.toLowerCase()) + '-handed ' + esc(qb.style) + '</div></div>' +
            '<div class="plan-qb-body">' + stats + ratings + bullets(notes, icon, emptyNotes) + '</div>' +
        '</div></div>';
}

function matchupCard(m, tone) {
    const bars = GRADE_BARS[m.grade] || 0;
    const meter = m.grade ? '<span class="plan-grade plan-grade--' + tone + '">' + esc(m.grade) + ' <i>' + [1, 2, 3].map(n => '<em class="' + (n <= bars ? 'on' : '') + '"></em>').join('') + '</i></span>' : '';
    const face = (pl, theirs) => '<div class="plan-face">' + headshot(pl.portrait) + '<b>' + esc(pl.last) + '</b><span>' + (theirs ? '#' + esc(pl.jersey) + ' &middot; ' : '') + esc(pl.position) + '</span></div>';
    return '<div class="plan-matchup plan-matchup--' + tone + '">' +
        '<div class="plan-faces">' + face(m.ours, false) + '<span class="plan-vs-small">vs</span>' + face(m.theirs, true) + '</div>' +
        '<div class="plan-matchup-body"><div class="plan-matchup-top"><span class="plan-matchup-label">' + esc(m.label) + '</span>' + meter + '</div>' +
        '<div class="plan-matchup-note">' + esc(m.note) + '</div></div></div>';
}

function callCard(m) {
    return '<div class="plan-call"><div class="plan-matchup-label">' + esc(m.label) + '</div><div class="plan-matchup-note">' + esc(m.note) + '</div></div>';
}

function matchupSection(id, kicker, title, groups, personnelLabel, personnel) {
    const column = (label, items, tone) => '<h4 class="plan-col-title plan-col-title--' + tone + '">' + label + ' <sup>' + items.length + '</sup></h4>' +
        (items.length ? items.map(m => matchupCard(m, tone)).join('') : '<div class="plan-empty">None this week.</div>');
    return '<div class="panel plan-card plan-section" id="plan-' + id + '">' + sectionHead(kicker, title) +
        '<div class="plan-personnel"><div class="plan-kicker">' + esc(personnelLabel) + '</div>' + esc(personnel) + '</div>' +
        '<div class="plan-columns">' +
            '<div>' + column('Where we win', groups.win, 'win') + '</div>' +
            '<div>' + column('Where they can hurt us', groups.lose, 'lose') +
                '<h4 class="plan-col-title plan-col-title--call">Comes down to the call <sup>' + groups.call.length + '</sup> <small>Even on talent: the scheme and the call decide these.</small></h4>' +
                (groups.call.length ? groups.call.map(callCard).join('') : '<div class="plan-empty">None this week.</div>') + '</div>' +
        '</div></div>';
}

function tape(p) {
    return '<div class="panel plan-card" id="plan-tape">' + sectionHead('By the numbers', 'Tale of the tape', 'Team ratings from the save &middot; scoring this season') +
        '<table class="plan-tape"><thead><tr><th>' + esc(p.us.name) + '</th><th></th><th>' + esc(p.them.name) + '</th></tr></thead><tbody>' +
        p.tape.map(row => '<tr><td class="' + (row.better === 'us' ? 'plan-better' : '') + '">' + esc(row.us ?? '—') + '</td><td class="plan-tape-label">' + esc(row.label) +
            '</td><td class="' + (row.better === 'them' ? 'plan-better' : '') + '">' + esc(row.them ?? '—') + '</td></tr>').join('') +
        '</tbody></table></div>';
}

function render(root, p) {
    if (!p) {
        root.innerHTML = '<div class="panel empty-note">No opponent data for this week yet. It appears after the next save sync.</div>';
        return;
    }
    root.innerHTML = header(p) +
        '<nav class="plan-nav">' + SECTIONS.map(([id, label]) => '<button type="button" data-section="' + id + '">' + esc(label) + '</button>').join('') + '</nav>' +
        (p.fcs ? '<div class="plan-note">FCS placeholder opponent: the save groups many FCS schools into this team, so its ratings and players are generic.</div>' : '') +
        keysAndStaff(p) +
        '<div class="plan-row plan-row--2" id="plan-qbs">' +
            qbPanel(p.their_qb, 'Scouting', p.them.name + "'s quarterback", p.their_qb_notes, '', 'How to defend him appears when the game plan is written.') +
            qbPanel(p.our_qb, 'Our side', 'Our quarterback', p.our_qb_notes, '', 'Where he can hurt them appears when the game plan is written.') +
        '</div>' +
        matchupSection('attack', 'Offense', 'Attacking the ' + p.them.name + ' defense', p.attack, 'Our personnel', p.personnel.offense) +
        matchupSection('stop', 'Defense', 'Stopping the ' + p.them.name + ' offense', p.stop, 'Our defensive personnel', p.personnel.defense) +
        tape(p);
    applyTeamColors(root);
    root.querySelectorAll('.plan-nav button').forEach(button => button.addEventListener('click', () =>
        document.getElementById('plan-' + button.dataset.section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })));
}

// ---------- News column ----------

/** One coach as a magazine item: big rank numeral, headshot, headline and pull quote. The No. 1 coach is the lead feature. */
function newsCard(c, listName, rank) {
    return '<article class="news-card' + (rank === 1 ? ' news-card--lead' : '') + (listName === 'hot' ? ' news-card--hot' : '') + '">' +
        '<div class="news-card-rank">' + rank + '</div>' +
        '<div class="news-card-head">' + headshot(c.portrait) +
            '<div class="news-card-id"><div class="news-card-name">' + esc(c.name) + '</div>' +
            '<div class="news-card-team team-link" data-team-id="' + esc(c.team_id) + '">' + (c.logo ? '<img class="team-logo team-logo--sm" src="' + esc(c.logo) + '" alt="">' : '') +
                (c.rank ? 'No. ' + esc(c.rank) + ' ' : '') + esc(c.team) + ' &middot; ' + esc(c.record) + '</div>' +
            (c.stat !== c.record || c.scheme ? '<div class="news-card-stat">' + esc(c.stat === c.record ? '' : c.stat) + (c.scheme ? (c.stat === c.record ? '' : ' &middot; ') + esc(c.scheme) : '') + '</div>' : '') + '</div></div>' +
        (c.headline ? '<h4 class="news-card-headline">' + esc(c.headline) + '</h4>' : '') +
        (c.quote ? '<blockquote class="news-card-quote">&ldquo;' + esc(c.quote) + '&rdquo;</blockquote>' : '<p class="mag-empty">No quote yet this week.</p>') +
        '<div class="news-card-foot">' + (c.last ? 'Last: ' + esc(c.last) : '') + (c.next ? ' &middot; Next: ' + esc(c.next) : '') + '</div>' +
    '</article>';
}

function initNews(news) {
    const grid = document.getElementById('news_grid');
    const status = document.getElementById('news_status');
    const button = document.getElementById('news_generate');
    let state = { role: 'hc', list: 'top', news };
    const show = () => {
        document.querySelectorAll('.news-role').forEach(b => b.setAttribute('aria-selected', String(b.dataset.role === state.role)));
        document.querySelectorAll('.news-list').forEach(b => b.setAttribute('aria-selected', String(b.dataset.list === state.list)));
        const cards = state.news ? state.news.lists[state.role][state.list] : [];
        grid.innerHTML = cards.length ? cards.map((c, i) => newsCard(c, state.list, i + 1)).join('') : '<p class="mag-empty">No games played yet.</p>';
        const edition = document.getElementById('news_week');
        if (edition && state.news) edition.textContent = 'Week ' + state.news.week + ' Coaches Edition';
    };
    document.querySelectorAll('.news-role').forEach(b => b.addEventListener('click', () => { state.role = b.dataset.role; show(); }));
    document.querySelectorAll('.news-list').forEach(b => b.addEventListener('click', () => { state.list = b.dataset.list; show(); }));
    button.addEventListener('click', async () => {
        button.disabled = true;
        setStatus(status, 'Writing a quote for each of the 60 coaches (a minute or two)...');
        try {
            const data = await postJSON('/coaches/news/generate');
            if (data.error) throw new Error(data.error);
            state.news = data;
            show();
            setStatus(status, 'Done.');
        } catch (err) {
            setStatus(status, String(err.message || err), true);
        } finally {
            button.disabled = false;
        }
    });
    show();
}

// ---------- Entry point ----------

export function initCoaches(plan, weeks, news) {
    const root = document.getElementById('coach_plan');
    const chips = document.getElementById('plan_weeks');
    let current = plan ? plan.week : null;

    const drawChips = () => {
        chips.innerHTML = (weeks || []).map(w => '<button type="button" class="plan-week' + (w.week === current ? ' is-current' : '') + (w.played ? ' is-played' : '') +
            '" data-week="' + w.week + '">W' + w.week + ' <span>' + esc(w.opponent.replace(/ [A-Z][a-z]+$/, '')) + '</span></button>').join('');
        chips.querySelectorAll('.plan-week').forEach(b => b.addEventListener('click', () => load(Number(b.dataset.week))));
    };

    const wire = () => {
        const button = document.getElementById('plan_generate');
        if (!button) return;
        button.addEventListener('click', async () => {
            const status = document.getElementById('plan_status');
            button.disabled = true;
            setStatus(status, 'Writing the game plan (three AI passes, about 30 seconds)...');
            try {
                const data = await postJSON('/coaches/plan/' + current + '/generate');
                if (data.error) throw new Error(data.error);
                render(root, data);
                wire();
            } catch (err) {
                setStatus(status, String(err.message || err), true);
                button.disabled = false;
            }
        });
    };

    async function load(week) {
        current = week;
        drawChips();
        root.innerHTML = '<div class="panel empty-note">Loading Week ' + week + '...</div>';
        try {
            const res = await fetch('/coaches/plan/' + week);
            render(root, res.ok ? await res.json() : null);
            wire();
        } catch (err) {
            root.innerHTML = '<div class="panel empty-note">Could not load the game plan: ' + esc(String(err)) + '</div>';
        }
    }

    drawChips();
    render(root, plan);
    wire();
    initNews(news);
}
