"""Spotlight week: one player is the story of the week. Everything the app writes while it's on (the dispatch, the
campus feed, the group chat, the press room and the podcast) is about him, from a fact sheet built from the save plus
the week's news about him (written by the coach, e.g. a decision about the draft). It lasts for the current game week
and ends by itself when the save moves on to the next one."""
import json
import database
import league
import save_sync

STAT_WORDS = [("PASSCOMPLETED", "completions"), ("PASSATTEMPTS", "pass attempts"), ("PASSYARDS", "passing yards"), ("PASSTDS", "passing touchdowns"),
              ("PASSINTS", "interceptions thrown"), ("RUSHATTEMPTS", "carries"), ("RUSHYARDS", "rushing yards"), ("RUSHTDS", "rushing touchdowns"),
              ("RECEIVECATCHES", "catches"), ("RECEIVEYARDS", "receiving yards"), ("RECEIVETDS", "receiving touchdowns"),
              ("TACKLES", "tackles"), ("SACKS", "sacks"), ("DSECINTS", "interceptions")]

def current_week():
    game = database.query_active_week()
    return game['week_id'] if game else None

def get():
    """The spotlight for this week ({player_id, week, news}), or None (none set, or its week has passed)."""
    try:
        spot = json.loads(save_sync.get_state('spotlight') or "null")
    except ValueError:
        return None
    if not spot or spot.get('week') != current_week():
        return None
    return spot

def start(player_id, news=""):
    if player_id not in league.query_players():
        raise ValueError("That player isn't in the save.")
    save_sync.set_state('spotlight', json.dumps({"player_id": player_id, "week": current_week(), "news": news.strip()}))
    return status()

def stop():
    save_sync.set_state('spotlight', "null")
    return status()

def find(name):
    """A player by name ("Arch Manning"), preferring the highest-rated recruit when names repeat."""
    matches = [p for p in league.query_players().values() if p['name'].lower() == name.strip().lower()]
    return max(matches, key=lambda p: p.get('stars') or 0) if matches else None

def team_record(team_id):
    wins = losses = 0
    for g in league.query_rows("SELECT * FROM league_games WHERE played = 1 AND (home_id = ? OR away_id = ?)", (team_id, team_id)):
        ours, theirs = (g['home_score'], g['away_score']) if g['home_id'] == team_id else (g['away_score'], g['home_score'])
        if ours is None or theirs is None:
            continue
        wins, losses = (wins + 1, losses) if ours > theirs else (wins, losses + 1)
    return wins, losses

def season_line(player_id):
    """'3,412 passing yards, 31 passing touchdowns ... in 12 games' and his best game, from the save's stat lines."""
    games = league.query_player_games(player_ids=[player_id])
    if not games:
        return "", ""
    totals = {}
    for g in games:
        stats = g['stats'] if isinstance(g.get('stats'), dict) else json.loads(g['stats_json'])
        for key, _ in STAT_WORDS:
            totals[key] = totals.get(key, 0) + (stats.get(key) or 0)
    parts = [f"{totals[k]:,} {words}" for k, words in STAT_WORDS if totals.get(k)]
    season = f"{', '.join(parts)} in {len(games)} games"
    key = next((k for k in ("PASSYARDS", "RUSHYARDS", "RECEIVEYARDS", "TACKLES") if totals.get(k)), None)
    best = ""
    if key:
        top = max(games, key=lambda g: (g['stats'] if isinstance(g.get('stats'), dict) else json.loads(g['stats_json'])).get(key) or 0)
        stats = top['stats'] if isinstance(top.get('stats'), dict) else json.loads(top['stats_json'])
        best = f"His best game: Week {top['week']}, " + ", ".join(f"{stats[k]} {w}" for k, w in STAT_WORDS if stats.get(k)) + "."
    return season, best

def facts(spot):
    p = league.query_players().get(spot['player_id']) or {}
    team = league.query_team(p.get('team_id')) or {}
    school = f"{team.get('name', '')} {team.get('nickname') or ''}".strip()
    us = league.query_user_team() or {}
    lines = [f"{p.get('name')} is the {school} {p.get('position')} (No. {p.get('jersey')}), a {(p.get('class_year') or '').lower()}"
             + (f", a former {p['stars']}-star recruit" if p.get('stars') else "")
             + (f" from {p['hometown']}, {p['home_state']}" if p.get('hometown') else "") + "."]
    season, best = season_line(spot['player_id'])
    if season:
        lines.append(f"His season: {season}. {best}")
    if team:
        wins, losses = team_record(team['team_id'])
        if wins + losses:
            lines.append(f"{school} went {wins}-{losses} this season.")
        staff = json.loads(team.get('staff_json') or "{}")
        coaches = [f"{role} {staff[key]['name']}" for key, role in (("hc", "head coach"), ("oc", "offensive coordinator"), ("dc", "defensive coordinator")) if staff.get(key)]
        if coaches:
            lines.append(f"{school}'s staff: {', '.join(coaches)}.")
    if spot.get('news'):
        lines.append(f"This week's news: {spot['news']}")
    if team and team.get('team_id') != us.get('team_id'):
        lines.append(f"He doesn't play for {us.get('name', 'our team')}: our coach, players and fans talk about him from the outside.")
    return " ".join(lines)

def context(audience):
    """The instruction and fact sheet for one kind of writing, or "" when there's no spotlight this week.
    audience: dispatch, feed, chat, presser, podcast."""
    spot = get()
    if not spot:
        return ""
    name = (league.query_players().get(spot['player_id']) or {}).get('name')
    sheet = f" SPOTLIGHT WEEK on {name}: {facts(spot)} Use only these facts about him (never invent his stats, quotes beyond the news, or other news)."
    how = {
        "dispatch": f" This week's dispatch is a feature on {name}: make all three sentences about him, his season and this week's news, "
                    "and mention our own game only in passing.",
        "feed": f" Every post this week is about {name}: fans of his school, rival fans, our own fans, national sports shows, NFL draft "
                "analysts and beat writers reacting to him and this week's news, each from a different angle.",
        "chat": f" This week the whole team can't stop talking about {name}: every message is about him and this week's news (what they "
                "think of it, what it'd be like to face him, who's next), in each player's own voice, instead of the usual angles. No stats or numbers.",
        "presser": f" This week the reporters only want to talk about {name} and this week's news: every question is about him, and the "
                   "coaches answer as people outside his program would (respectful, honest, a little competitive).",
        "podcast": f" This week's show has a segment all about {name}, and the hosts keep coming back to him.",
    }[audience]
    return sheet + how

def status():
    spot = get()
    if not spot:
        return {"active": False}
    p = league.query_players().get(spot['player_id']) or {}
    team = league.query_team(p.get('team_id')) or {}
    return {"active": True, "player_id": spot['player_id'], "name": p.get('name'), "position": p.get('position'),
            "team": f"{team.get('name', '')} {team.get('nickname') or ''}".strip(), "week": spot['week'], "news": spot.get('news')}
