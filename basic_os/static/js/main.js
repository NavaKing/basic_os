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
import { applyTeamColors } from './utils.js';

const page = JSON.parse(document.getElementById('page_data').textContent);

initTabs();
applyTeamColors();
initTeamPages();
renderTweets(page.tweets);
renderStories(page.stories, page.game, page.team_name);
initDepthChart(page.depth_chart);
initStorylines(page.storylines);
initRecap(page.recap_weeks, page.recap);
initCoaches(page.coach_plan, page.plan_weeks, page.coach_news);
initPodcast(page.podcast_episodes, page.event_uploads, page.event_draft);
initGenerator(data => {
    renderTweets(data.tweets);
    renderStories(data.past_stories, page.game, page.team_name);
    if (data.storylines) renderStorylines(data.storylines);
    const preview = document.getElementById('scouting_preview');
    if (preview && data.scouting_preview) preview.textContent = data.scouting_preview;
});
