// Story Column: hero banner, the week's cover story and the back-issue archive, in the magazine layout.

import { esc, staticUrl } from './utils.js';

// Sentence ends, skipping the periods in "No. 6", "Michigan St.", "Jr.", "Sr." and "vs." (same rule as sentences.py)
const SENTENCE_END = /(?<!\b(?:No|St|Jr|Sr|vs)\.)(?<=[.!?])\s+/;

/** Splits a dispatch into paragraphs: blank lines, or every three sentences for one long block. */
function paragraphs(text) {
    const blocks = (text || '').split(/\n\s*\n/).map(b => b.trim()).filter(Boolean);
    if (blocks.length !== 1) return blocks;
    const sentences = blocks[0].split(SENTENCE_END);
    if (sentences.length <= 4) return blocks;
    const out = [];
    for (let i = 0; i < sentences.length; i += 3) out.push(sentences.slice(i, i + 3).join(' '));
    return out;
}

function body(text, dropcap) {
    return paragraphs(text).map((p, i) => '<p' + (dropcap && i === 0 ? ' class="mag-dropcap"' : '') + '>' + esc(p) + '</p>').join('');
}

function headline(story, teamName) {
    return teamName + ' vs ' + story.opponent_name;
}

function renderHero(lead, game, teamName) {
    const image = document.getElementById('hero_image');
    if (lead && lead.image_path) {
        image.src = staticUrl(lead.image_path);
        image.hidden = false;
    } else {
        image.removeAttribute('src');
        image.hidden = true;
    }
    const week = lead ? lead.week_num : (game ? game.week_id : null);
    document.getElementById('hero_kicker').textContent = week ? 'Week ' + week + ' Cover Story' : 'The Dispatch';
    document.getElementById('hero_title').textContent = teamName + ' vs ' + (lead ? lead.opponent_name : (game ? game.opponent_name : 'TBD'));
    document.getElementById('hero_note').textContent = lead && lead.image_path ? '' : 'The banner photo renders with the next hub generation.';
}

function leadStory(lead, teamName) {
    if (!lead) {
        return '<p class="mag-empty">No dispatch yet. Click Execute Hub Generator to write this week\'s story.</p>';
    }
    const words = (lead.generated_text || '').split(/\s+/).length;
    return '<div class="mag-folio"><span>The ' + esc(teamName) + ' Dispatch</span><span>Week ' + esc(lead.week_num) + ' Edition &middot; ' +
            Math.max(1, Math.round(words / 220)) + ' min read</span></div>' +
        '<div class="mag-top mag-top--flush"><div class="mag-top-text"><h3 class="mag-kicker-headline">Game week preview</h3>' +
            '<p class="mag-byline">By The ' + esc(teamName) + ' Dispatch</p></div></div>' +
        '<h2 class="mag-slab">' + esc(headline(lead, teamName)) + '</h2>' +
        '<div class="mag-strap">Cover story &middot; Week ' + esc(lead.week_num) + '</div>' +
        '<div class="mag-body' + (words > 140 ? ' mag-body--columns' : '') + '">' + body(lead.generated_text, true) + '</div>';
}

function archiveEntry(story, teamName) {
    const excerpt = (story.generated_text || '').split(SENTENCE_END)[0];
    return '<li><details class="mag-index-item"><summary>' +
        (story.image_path ? '<img class="mag-index-thumb" src="' + esc(staticUrl(story.image_path)) + '" alt="" loading="lazy">' : '<span class="mag-index-thumb"></span>') +
        '<div><div class="mag-card-kicker">Week ' + esc(story.week_num) + '</div>' +
            '<h4 class="mag-card-title">' + esc(headline(story, teamName)) + '</h4>' +
            '<div class="mag-index-excerpt">' + esc(excerpt) + '</div></div>' +
        '</summary><div class="mag-body">' + body(story.generated_text, false) + '</div></details></li>';
}

/** stories are newest first; the first one is the lead. */
export function renderStories(stories, game, teamName = 'Our team') {
    const lead = stories && stories.length ? stories[0] : null;
    renderHero(lead, game, teamName);
    document.getElementById('lead_story').innerHTML = leadStory(lead, teamName);

    const older = (stories || []).slice(1);
    document.getElementById('history_feed_list').innerHTML = older.length
        ? older.map(story => archiveEntry(story, teamName)).join('')
        : '<li class="mag-empty">Earlier weeks\' stories will collect here.</li>';
}
