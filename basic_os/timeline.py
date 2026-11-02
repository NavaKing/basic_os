import datetime
import re
import database
import league
import media
import roster
import storylines
import team
from sentences import split as sentence_split

# The season as a story: one entry per week with the game, that week's dispatch and photos,
# the player of the game, storyline beats and where the team stood in the AP poll.

TWEET_PHOTOS = 3
FEED_POSTS = 4

def player_of_the_game(week):
    """Our best performer in that week's game by impact score, with his stat line."""
    stats = roster.query_week_stats(week)
    if not stats:
        return None
    players = {p['save_id']: p for p in roster.query_full_roster() if p['save_id']}
    best = max((pid for pid in stats if pid in players), key=lambda pid: storylines.impact_score(stats[pid]), default=None)
    if not best:
        return None
    p = players[best]
    return {"name": p['player_name'], "position": p['position'], "line": roster.format_stat_line(stats[best]),
            "portrait": media.portrait_url("player", p.get('portrait_file'))}

def storyline_beats():
    """{week: [beat]} for storylines starting, continuing and ending each week."""
    beats = {}
    for status in ("active", "resolved"):
        for s in storylines.query_storyline_rows(status):
            for chapter in storylines.query_chapters(s['storyline_id']):
                kind = "started" if chapter['week_num'] == s['start_week'] else "chapter"
                beats.setdefault(chapter['week_num'], []).append({"kind": kind, "title": s['title'], "text": chapter['chapter_text']})
            if status == "resolved" and s.get('end_week'):
                beats.setdefault(s['end_week'], []).append({"kind": "resolved", "title": s['title'], "text": s.get('finale_text') or s.get('resolution') or ""})
    return beats

def headline(us, game, result):
    """'Wyoming beats FCS Midwest Thunderbirds, 35-21' style headline for a week."""
    opponent = game['opponent_name']
    if not result:
        return f"Up next: {'at ' if game.get('site') == 'Away' else ''}{opponent}"
    verb = {"W": "beats", "L": "falls to", "T": "ties"}[result['outcome']]
    return f"{us['name']} {verb} {opponent}, {result['score']}"

def paragraphs(text):
    """Splits generated text into paragraphs (blank lines, or every few sentences for one long block)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    if len(blocks) == 1:
        sentences = sentence_split(blocks[0])
        if len(sentences) > 4:
            blocks = [" ".join(sentences[i:i + 3]) for i in range(0, len(sentences), 3)]
    return blocks

def build_timeline():
    us = team.user_team()
    stories = {s['week_num']: s for s in database.query_archived_stories()}
    beats = storyline_beats()
    polls = dict(league.query_team_polls(us['id'])) if us.get('id') is not None else {}
    active = database.query_active_week()
    rivalries = {r['opponent_id']: r['name'] or "Rivalry game" for r in league.query_rivalries()}
    entries = []
    for game in database.query_full_schedule():
        week = game['week_id']
        if not game['is_played'] and (not active or week != active['week_id']):
            continue  # future weeks beyond the next game have nothing to tell yet
        opponent = team.opponent(game['opponent_name'])
        story = stories.get(week)
        tweets = database.query_active_tweets(week)
        result = None
        if game['is_played'] and game['wyo_score'] is not None:
            mine, theirs = game['wyo_score'], game['opp_score']
            result = {"outcome": "W" if mine > theirs else ("L" if mine < theirs else "T"), "score": f"{mine}-{theirs}"}
        rank = polls.get(week)
        top_post = next((t for t in tweets if t.get('tweet_text')), None)
        entries.append({
            "headline": headline(us, game, result),
            "date_text": datetime.date.fromisoformat(game['game_date']).strftime("%A, %B %d").replace(" 0", " ") if game.get('game_date') else "",
            "week": week, "played": bool(game['is_played']), "date": game.get('game_date'),
            "venue": "vs" if game.get('site') in ("Home", "Neutral") else "at",
            "opponent": game['opponent_name'], "opponent_id": opponent['id'] if opponent else None,
            "rivalry": rivalries.get(opponent['id']) if opponent else None, "opponent_logo": opponent['logo'] if opponent else None,
            "result": result,
            "rank_after": rank if rank and rank <= 25 else None,
            "player": player_of_the_game(week) if game['is_played'] else None,
            "story": {"paragraphs": paragraphs(story['generated_text']), "image": story.get('image_path')} if story else None,
            "photos": [t['image_path'] for t in tweets if t.get('image_path')][:TWEET_PHOTOS],
            "top_post": {"text": top_post['tweet_text'], "by": top_post.get('display_name') or top_post.get('user_handle')} if top_post else None,
            "posts": [{"handle": t.get('user_handle') or "", "text": t['tweet_text']} for t in tweets if t.get('tweet_text')][:FEED_POSTS],
            "beats": beats.get(week, []),
        })
    return entries
