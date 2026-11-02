// Entry point: reads the data the server embedded in the page and starts each component.

import { initTabs } from './tabs.js';
import { renderTweets } from './feed.js';
import { renderStories } from './stories.js';
import { initDepthChart } from './depth-chart.js';
import { initStorylines, renderStorylines } from './storylines.js';
import { initGenerator } from './generator.js';
import { initRecap } from './recap.js';
import { initTeamPages } from './team.js';
import { initCoaches } from './coaches.js';
import { initPodcast } from './podcast.js';
import { initBackups } from './backups.js';
import { initAwards } from './awards.js';
import { applyTeamColors } from './utils.js';

const page = JSON.parse(document.getElementById('page_data').textContent);

/** Starts one component; an error in one tab is logged instead of stopping every tab after it. */
function start(name, fn) {
    try {
        fn();
    } catch (err) {
        console.error('BASIC_OS: the ' + name + ' component failed to start', err);
    }
}

start('tabs', initTabs);
start('team colours', () => applyTeamColors());
start('team pages', initTeamPages);
start('backups', initBackups);
start('campus feed', () => renderTweets(page.tweets));
start('story column', () => renderStories(page.stories, page.game, page.team_name));
start('depth chart', () => initDepthChart(page.depth_chart));
start('locker room', () => initStorylines(page.storylines));
start('weekly recap', () => initRecap(page.recap_weeks, page.recap));
start('coaches', () => initCoaches(page.coach_plan, page.plan_weeks, page.coach_news));
start('awards', () => initAwards(page.awards));
start('podcast', () => initPodcast(page.podcast_episodes, page.event_uploads, page.event_draft));
start('hub generator', () => initGenerator(data => {
    renderTweets(data.tweets);
    renderStories(data.past_stories, page.game, page.team_name);
    if (data.storylines) renderStorylines(data.storylines);
    const preview = document.getElementById('scouting_preview');
    if (preview && data.scouting_preview) preview.textContent = data.scouting_preview;
}));
