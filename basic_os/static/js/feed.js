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

export function renderTweets(tweets) {
    const box = document.getElementById('twitter_feed_box');
    box.innerHTML = tweets && tweets.length
        ? tweets.map(tweetCard).join('')
        : '<div class="empty-note">Awaiting generator call... Local AI models will simulate campus tweets based on current matchup arrays.</div>';
}
