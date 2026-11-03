// Campus feed: renders the simulated Twitter/X posts.

import { esc, staticUrl } from './utils.js';

function tweetCard(tweet) {
    return '<div class="tweet-card">' +
        '<div class="tweet-header">' +
            '<span class="tweet-name">' + esc(tweet.display_name) + '</span>' +
            '<span class="tweet-handle">' + esc(tweet.user_handle) + '</span>' +
            '<span class="tweet-badge">&#10003;</span>' +
        '</div>' +
        '<div class="tweet-body">' + esc(tweet.tweet_text) + '</div>' +
        (tweet.image_path ? '<img class="tweet-photo" src="' + esc(staticUrl(tweet.image_path)) + '" alt="Photo attached to the post">' : '') +
        '<div class="tweet-footer">' +
            '<span>&#128172; 44</span> <span>&#128019; ' + esc(tweet.retweets) + '</span> ' +
            '<span>&#10084; ' + esc(tweet.likes) + '</span> <span>&#128202; ' + esc(tweet.views) + '</span>' +
        '</div>' +
    '</div>';
}

const SEEN_KEY = 'basic_os_feed_seen';
let unseen = 0;

function signature(tweets) {
    return (tweets || []).map(t => t.tweet_text).join('|').slice(0, 400);
}

function remembered() {
    try { return localStorage.getItem(SEEN_KEY); } catch (err) { return null; }
}

/** Posts that arrived since the feed app was last opened (for its badge on the phone). */
export function unseenPosts() {
    return unseen;
}

/** Called when the feed app opens: everything on it now counts as seen. */
export function markFeedSeen(tweets) {
    unseen = 0;
    try { localStorage.setItem(SEEN_KEY, signature(tweets)); } catch (err) { /* private window: the badge just won't remember */ }
}

export function renderTweets(tweets) {
    const box = document.getElementById('twitter_feed_box');
    if (!box) return;
    box.innerHTML = tweets && tweets.length
        ? tweets.map(tweetCard).join('')
        : '<div class="empty-note">No posts yet. Run the hub generator and the campus starts talking about the matchup.</div>';
    unseen = tweets && tweets.length && signature(tweets) !== remembered() ? tweets.length : 0;
    document.dispatchEvent(new CustomEvent('feed:update', { detail: tweets || [] }));
}
