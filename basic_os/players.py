import json
import os
import re
import awards
import database
import league
import media
import recap
import roster

# Player profiles: one player's season game by game, his totals and honors, where he's from and how he was
# recruited, and (for our players) the storylines and campus photos he's been part of. Opened by clicking a player.

STAR_WORDS = {5: "Five-star", 4: "Four-star", 3: "Three-star", 2: "Two-star", 1: "One-star"}
WEEKLY_AWARDS = {"Offensive_Player_of_Week": "National Offensive Player of the Week", "Defensive_Player_of_Week": "National Defensive Player of the Week",
                 "Offensive_Player_of_Week_Conf": "Conference Offensive Player of the Week", "Defensive_Player_of_Week_Conf": "Conference Defensive Player of the Week"}
ALL_AMERICA = re.compile(r"^ALL_AM_(1ST|2ND)(_PRE)?(_CONF)?$")
PHOTOS = 6

def height_text(inches):
    return f"{inches // 12}'{inches % 12}\"" if inches else ""

def honors(player_id):
    out = []
    heisman = next((h for h in league.query_heisman() if h['player_id'] == player_id), None)
    if heisman and heisman['rank']:
        out.append(f"No. {heisman['rank']} in the Heisman race")
    for row in league.query_rows("SELECT award_type, position, conference FROM league_season_awards WHERE player_id = ?", (player_id,)):
        m = ALL_AMERICA.match(row['award_type'])
        if m:
            out.append(f"{'Preseason ' if m.group(2) else ''}All-{awards.conference_label(row['conference']) if m.group(3) else 'America'}, "
                       f"{'First' if m.group(1) == '1ST' else 'Second'} Team ({row['position']})")
    for row in league.query_rows("SELECT award_type, week FROM league_awards WHERE player_id = ? ORDER BY week", (player_id,)):
        out.append(f"{WEEKLY_AWARDS.get(row['award_type'], row['award_type'].replace('_', ' '))}, Week {row['week']}")
    return out

def game_log(player_id, team_id, ours_row):
    """[{week, opponent, venue, outcome, score, line}] newest first. Our players' lines come from the merged roster stats
    (a player can have several stat records per game, e.g. receiving and returns)."""
    teams = league.query_teams()
    games = {g['game_id']: g for g in league.query_rows("SELECT * FROM league_games WHERE played = 1 AND (home_id = ? OR away_id = ?)", (team_id, team_id))}
    by_week = {g['week']: g for g in games.values()}
    if ours_row:
        conn = roster.get_connection()
        lines = [(r['week_num'], json.loads(r['stats_json'])) for r in
                 conn.execute("SELECT week_num, stats_json FROM player_game_stats WHERE save_id = ?", (ours_row['save_id'],)).fetchall()]
        conn.close()
        entries = [(by_week.get(week), stats) for week, stats in lines]
    else:
        entries = [(games.get(r['game_id']), r['stats']) for r in league.query_player_games(player_ids=[player_id])]
    log, totals = [], {}
    for game, stats in entries:
        for key, value in stats.items():
            if key == 'GAMERATING' or 'LONGEST' in key:
                totals[key] = max(totals.get(key, 0), value)
            else:
                totals[key] = totals.get(key, 0) + value
        if not game:
            continue
        outcome, mine, theirs, venue, opponent_id = recap.side_result(game, team_id)
        log.append({"week": game['week'], "opponent": recap.team_view(teams[opponent_id]) if opponent_id in teams else None, "venue": venue,
                    "outcome": outcome, "score": f"{mine}-{theirs}", "line": roster.format_stat_line(stats) or "Played"})
    log.sort(key=lambda g: -g['week'])
    return log, totals

def storylines_for(roster_row):
    rows = league.query_rows("""SELECT storyline_id, title, status, start_week, end_week, premise, resolution FROM storylines
                                WHERE player_id = ? OR rival_id = ? ORDER BY storyline_id DESC""", (roster_row['player_id'], roster_row['player_id']))
    out = []
    for s in rows:
        chapter = league.query_rows("SELECT chapter_text FROM storyline_chapters WHERE storyline_id = ? ORDER BY week_num DESC LIMIT 1", (s['storyline_id'],))
        weeks = f"Week {s['start_week']}" + (f" to {s['end_week']}" if s['end_week'] and s['end_week'] != s['start_week'] else "")
        out.append({"title": s['title'], "status": "Ongoing" if s['status'] == 'active' else "Resolved", "weeks": weeks,
                    "text": (chapter[0]['chapter_text'] if chapter else s['premise'])})
    return out

def photos_of(save_id):
    """Campus-feed photos whose post is about him (the same match the face swap uses)."""
    import ai_engine
    out = []
    for row in league.query_rows("SELECT tweet_text, image_path FROM historical_tweets WHERE image_path IS NOT NULL ORDER BY tweet_id DESC"):
        if len(out) >= PHOTOS:
            break
        featured = ai_engine.featured_player(row['tweet_text'])
        if featured and featured.get('save_id') == save_id and os.path.exists(os.path.join(database.STATIC_DIR, row['image_path'])):
            out.append({"image": "/static/" + row['image_path'].replace("\\", "/"), "caption": row['tweet_text']})
    return out

def build_profile(player_id):
    player = next(iter(league.query_rows("SELECT * FROM league_players WHERE player_id = ?", (player_id,))), None)
    ours_row = next((p for p in roster.query_full_roster() if p.get('save_id') == player_id), None)
    picked = next(iter(league.query_rows("SELECT * FROM league_season_awards WHERE player_id = ? LIMIT 1", (player_id,))), None)
    if not (player or ours_row or picked):
        return None
    base = player or {}
    if not player and picked:  # linemen often have no stat lines; the All-America pick still knows who he is
        base = {"name": picked['name'], "position": picked['position'], "class_year": picked['class_year'], "jersey": picked['jersey'],
                "team_id": picked['team_id'], "portrait_file": picked['portrait_file']}
    if ours_row:
        user = league.query_user_team()
        base = {**base, "name": ours_row['player_name'], "position": ours_row['position'], "class_year": ours_row['class_year'],
                "jersey": ours_row['jersey_num'], "team_id": base.get('team_id') or (user['team_id'] if user else None),
                "portrait_file": ours_row.get('portrait_file') or base.get('portrait_file'),
                "hometown": ours_row.get('hometown'), "home_state": ours_row.get('home_state'), "stars": ours_row.get('stars')}
    team = league.query_teams().get(base.get('team_id'))
    log, totals = game_log(player_id, base.get('team_id'), ours_row)
    hometown = ", ".join(x for x in (base.get('hometown'), re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base.get('home_state') or "")) if x)
    profile = {
        "id": player_id, "name": base['name'], "position": base['position'],
        "position_name": roster.POSITION_NAMES.get(base['position'], base['position']), "jersey": base.get('jersey'),
        "class": base.get('class_year') or "", "team": recap.team_view(team) if team else None, "ours": bool(ours_row),
        "portrait": media.portrait_url("player", base.get('portrait_file')),
        "hometown": hometown, "recruit": f"{STAR_WORDS[base['stars']]} recruit" if base.get('stars') in STAR_WORDS else None,
        "boxes": [{"label": label, "value": value} for label, value in recap.stat_boxes(totals)] if totals else [],
        "season_line": roster.format_stat_line(totals), "games": log, "honors": honors(player_id),
        "storylines": [], "photos": [], "facts": [],
    }
    if ours_row:
        facts = [("Overall", ours_row.get('overall')), ("Height", height_text(ours_row.get('height_in'))),
                 ("Weight", f"{ours_row['weight_lb']} lbs" if ours_row.get('weight_lb') else None), ("Depth chart", ours_row.get('depth_slot')),
                 ("Status", ours_row.get('health_status') if ours_row.get('health_status') != "Healthy" else None),
                 ("Development", (ours_row.get('dev_trait') or "").replace("College_", "") or None),
                 ("Captain", "Team captain" if ours_row.get('captain') else None)]
        profile.update(facts=[{"label": label, "value": value} for label, value in facts if value],
                       storylines=storylines_for(ours_row), photos=photos_of(player_id))
    return profile
