import json
import league
import media
import recap
import roster

# Box score for one played game (opened by clicking it in a schedule): the line score, both teams' stat lines side by
# side, each team's top performers, and the scoring plays when the app captured the game's scoring summary.
# Player stat lines for a week appear in the save once that week is advanced, so the newest games show team stats only.

def possession(seconds):
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else "—"

# (label, how to show a team's value, the number that decides who did better, whether lower is better)
STAT_ROWS = [
    ("First downs", lambda s, o: s['FIRSTDOWNS'], lambda s, o: s['FIRSTDOWNS'], False),
    ("Total yards", lambda s, o: s['OFFYARDS'], lambda s, o: s['OFFYARDS'], False),
    ("Passing", lambda s, o: f"{s['PASSCOMPLETIONS']}/{s['PASSATTEMPTS']}, {s['OFFPASSYARDS']} yds", lambda s, o: s['OFFPASSYARDS'], False),
    ("Rushing", lambda s, o: f"{s['RUSHATTEMPTS']} car, {s['OFFRUSHYARDS']} yds", lambda s, o: s['OFFRUSHYARDS'], False),
    ("Third downs", lambda s, o: f"{s['THIRDDOWNCONV']}/{s['THIRDDOWNS']}", None, False),
    ("Fourth downs", lambda s, o: f"{s['FOURTHDOWNCONV']}/{s['FOURTHDOWNS']}", None, False),
    ("Red zone", lambda s, o: f"{s['OFFREDZONETDS']} TD in {s['OFFREDZONES']} trips", None, False),
    ("Turnovers", lambda s, o: o['TAKEAWAYS'], lambda s, o: o['TAKEAWAYS'], True),   # what the other side took away
    ("Sacks", lambda s, o: s['SACKS'], lambda s, o: s['SACKS'], False),
    ("Penalties", lambda s, o: f"{s['PENALTIES']}-{s['PENALTYYARDS']}", lambda s, o: s['PENALTYYARDS'], True),
    ("Possession", lambda s, o: possession(s['POSSESSIONTIME']), lambda s, o: s['POSSESSIONTIME'], False),
]

# Leaders shown per team: (label, stat that ranks them)
LEADERS = [("Passing", "PASSYARDS"), ("Rushing", "RUSHYARDS"), ("Receiving", "RECEIVEYARDS"), ("Tackles", "TACKLES")]

def stat_value(stats, key):
    if key == "TACKLES":
        return stats.get('DEFTACKLES', 0) + stats.get('ASSDEFTACKLES', 0)
    return stats.get(key, 0)

def team_stats(game):
    away, home = (json.loads(game[f'{side}_stats_json']) if game.get(f'{side}_stats_json') else None for side in ("away", "home"))
    if not (away and home):
        return []
    rows = []
    for label, show, measure, lower_better in STAT_ROWS:
        better = None
        if measure:
            a, h = measure(away, home), measure(home, away)
            if a != h:
                better = "away" if (a < h) == lower_better else "home"
        rows.append({"label": label, "away": show(away, home), "home": show(home, away), "better": better})
    return rows

def performers(game, teams):
    """{team_id: [{label, id, name, position, portrait, line}]} from the game's player stat lines."""
    players = league.query_players()
    lines = {}
    for row in league.query_rows("SELECT player_id, stats_json FROM league_player_games WHERE game_id = ?", (game['game_id'],)):
        player = players.get(row['player_id'])
        if player:
            lines.setdefault(player['team_id'], []).append((player, json.loads(row['stats_json'])))
    out = {}
    for team_id in (game['away_id'], game['home_id']):
        picks = []
        for label, key in LEADERS:
            best = max(lines.get(team_id, []), key=lambda item: stat_value(item[1], key), default=None)
            if best and stat_value(best[1], key):
                player, stats = best
                picks.append({"label": label, "id": player['player_id'], "name": player['name'], "position": player['position'],
                              "portrait": media.portrait_url("player", player.get('portrait_file')),
                              "line": roster.format_stat_line(stats) or f"{stat_value(stats, key)} {label.lower()}"})
        out[team_id] = picks
    return out

def scoring_plays(game_id):
    """(the scoring plays, a note about them or None), or (None, None) when the game's scoring summary wasn't captured."""
    import events
    try:
        draft = events.build_save_draft(game_id)
    except ValueError:
        return None, None
    plays = [{"quarter": p['quarter'], "clock": p['clock'], "team": p['team'], "text": p['text']} for p in draft['plays']]
    return plays, (draft.get('notes') or [None])[0]   # e.g. why an overtime game's totals come from the scoreboard

def build_game(game_id):
    rows = league.query_rows("SELECT * FROM league_games WHERE game_id = ? AND played = 1", (game_id,))
    if not rows:
        return None
    game = rows[0]
    for side in ("home", "away"):
        game[f'{side}_quarters'] = json.loads(game[f'{side}_quarters'] or "[]")
    teams = league.query_teams()
    ranks = league.query_poll(game['week'] - 1)
    by_team = performers(game, teams)
    line = recap.box_score(game, teams, ranks)
    plays, note = scoring_plays(game_id)
    return {
        "game_id": game_id, "week": game['week'], "postseason": game['week_type'] not in (None, "RegularSeason"),
        "teams": [{**row, "side": side, "performers": by_team.get(row['team']['id'], [])} for side, row in zip(("away", "home"), line)],
        "stats": team_stats(game),
        "scoring": plays,
        "scoring_note": note,
    }
