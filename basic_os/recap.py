import math
import league
import media
from request_cache import per_request
from storylines import impact_score, turnovers

# Weekly recap: awards, notable games, polls and races for one week, built from the league snapshot.

TOP_25 = 25
CFP_FIELD = 12
LIST_SIZE = 5          # rows in the poll risers / fallers / swings lists
STREAK_ROWS = 4
CLOSE_GAME_MARGIN = 8  # "game of the week" candidates are decided by this much or less
QUARTER_NAMES = ["1st", "2nd", "3rd"]

# ---------- Small helpers ----------

def playoff_chance(rank, losses):
    """App estimate of making the 12-team field from AP rank and losses (the save has no playoff odds)."""
    rank = rank or 40
    return 1 / (1 + math.exp(-(16 - rank - 4 * losses) / 5))

def is_fcs_placeholder(team):
    """The save's 'FCS East/West/...' teams stand in for many FCS schools at once, so they're left out of streaks and blowouts."""
    return team['name'].startswith("FCS ")

def records_through(games, week):
    """{team_id: [wins, losses]} from games up to and including week."""
    records = {}
    for g in games:
        if g['week'] > week:
            continue
        for team, mine, theirs in ((g['home_id'], g['home_score'], g['away_score']), (g['away_id'], g['away_score'], g['home_score'])):
            record = records.setdefault(team, [0, 0])
            record[0 if mine > theirs else 1] += 1
    return records

def team_view(team, rank=None):
    return {"id": team['team_id'], "name": team['name'], "short": team['short_name'] or team['name'][:4].upper(),
            "color": team['color'], "logo": media.logo_url(team['short_name']), "rank": rank if rank and rank <= TOP_25 else None}

def side_result(game, team_id):
    """('W', 52, 17, '@', opponent_id) from one team's side of a game."""
    home = game['home_id'] == team_id
    mine, theirs = (game['home_score'], game['away_score']) if home else (game['away_score'], game['home_score'])
    outcome = 'W' if mine > theirs else ('L' if mine < theirs else 'T')
    return outcome, mine, theirs, ('vs' if home else '@'), (game['away_id'] if home else game['home_id'])

def box_score(game, teams, ranks):
    """Both teams' lines for a box score card (away team first, like a scoreboard)."""
    rows = []
    for side in ('away', 'home'):
        team = teams[game[f'{side}_id']]
        quarters = list(game[f'{side}_quarters'] or [])
        total = game[f'{side}_score']
        # The save keeps four quarters; overtime points are whatever the total has beyond them
        if quarters and total is not None and sum(quarters) < total and len(quarters) == 4:
            quarters.append(total - sum(quarters))
        rows.append({"team": team_view(team, ranks.get(team['team_id'])), "quarters": quarters,
                     "total": game[f'{side}_score'], "won": game[f'{side}_score'] > game[f"{'home' if side == 'away' else 'away'}_score"]})
    return rows

def running_scores(game):
    """Cumulative (home, away) score after each quarter."""
    home = away = 0
    totals = []
    for h, a in zip(game['home_quarters'] or [], game['away_quarters'] or []):
        home, away = home + h, away + a
        totals.append((home, away))
    return totals

def lead_changes(game):
    changes, leader = 0, 0
    for home, away in running_scores(game):
        current = (home > away) - (home < away)
        if current and leader and current != leader:
            changes += 1
        if current:
            leader = current
    return changes

def stat_boxes(stats):
    """Four headline numbers that fit the player's game (passing, rushing, receiving, defense or kicking)."""
    s = lambda key: stats.get(key, 0)
    if s('PASSATTEMPTS') >= 10:
        return [("Pass Yds", s('PASSYARDS')), ("Pass TD", s('PASSTDS')), ("INT", s('PASSINTS')),
                ("Comp %", round(100 * s('PASSCOMPLETED') / s('PASSATTEMPTS')))]
    if s('RUSHATTEMPTS') and s('RUSHATTEMPTS') >= s('RECEIVECATCHES'):
        return [("Car", s('RUSHATTEMPTS')), ("Rush Yds", s('RUSHYARDS')), ("Rush TD", s('RUSHTDS')),
                ("YPC", round(s('RUSHYARDS') / s('RUSHATTEMPTS'), 1))]
    if s('RECEIVECATCHES'):
        return [("Rec", s('RECEIVECATCHES')), ("Rec Yds", s('RECEIVEYARDS')), ("TD", s('RECEIVETDS')), ("YAC", s('RECEIVEYARDSAFTER'))]
    if s('KICKFGATTEMPTS') or s('KICKEPATTEMPTS'):
        return [("FG", f"{s('KICKFGMADE')}/{s('KICKFGATTEMPTS')}"), ("Long", s('KICKFGLONGEST')), ("XP", f"{s('KICKEPMADE')}/{s('KICKEPATTEMPTS')}")]
    sacks = s('DLINESACKS') + 0.5 * s('DLINEHALFSACK')
    extras = [("Sack", f"{sacks:g}"), ("INT", s('DSECINTS')), ("PBU", s('DEFPASSDEFLECTIONS')), ("FF", s('DLINEFORCEDFUMBLES'))]
    # Tackles always, then whichever splash plays he made, padded with the rest
    chosen = [box for box in extras if box[1] not in (0, "0")] + [box for box in extras if box[1] in (0, "0")]
    return [("Tkl", s('DEFTACKLES') + s('ASSDEFTACKLES'))] + chosen[:3]

def class_label(player):
    year = {"Freshman": "FR", "Sophomore": "SO", "Junior": "JR", "Senior": "SR"}.get(player['class_year'], player['class_year'] or "")
    return ("RS " if player.get('redshirt') == "Previous" else "") + year

def merged_week_stats(rows):
    """{player_id: {game_id, stats}} with a player's stat records for one game merged (offense + returns, etc.)."""
    merged = {}
    for row in rows:
        entry = merged.setdefault(row['player_id'], {"game_id": row['game_id'], "stats": {}})
        for key, value in row['stats'].items():
            entry['stats'][key] = max(entry['stats'].get(key, 0), value) if key == 'GAMERATING' or 'LONGEST' in key else entry['stats'].get(key, 0) + value
    return merged

def player_card(player_id, entry, ctx, note=None):
    player = ctx['players'].get(player_id)
    game = ctx['games_by_id'].get(entry['game_id']) if entry else None
    if not player or not game:
        return None
    team = ctx['teams'][player['team_id']]
    outcome, mine, theirs, venue, opponent_id = side_result(game, player['team_id'])
    first, _, last = player['name'].partition(" ")
    return {
        "id": player_id, "first_name": first, "last_name": last or first,
        "position": player['position'], "class": class_label(player),
        "portrait": media.portrait_url("player", player.get('portrait_file')),
        "team": team_view(team, ctx['ranks_before'].get(team['team_id'])),
        "result": {"outcome": outcome, "score": f"{mine}-{theirs}", "venue": venue,
                   "opponent": team_view(ctx['teams'][opponent_id], ctx['ranks_before'].get(opponent_id))},
        "boxes": [{"label": label, "value": value} for label, value in stat_boxes(entry['stats'])],
        "note": note
    }

# ---------- Cards ----------

def award_card(award_type, ctx):
    award = next((a for a in ctx['awards'] if a['award_type'] == award_type), None)
    if not award:
        return None
    return player_card(award['player_id'], ctx['week_stats'].get(award['player_id']), ctx)

# Fantasy-style points so a big passing day, a 300-yard receiving day and a 12-tackle game compare fairly.
# (The game's own rating tops out at 100, so several freshmen tie on it every week.)
PRODUCTION_POINTS = {
    'PASSYARDS': 0.04, 'PASSTDS': 4, 'PASSINTS': -2, 'RUSHYARDS': 0.1, 'RUSHTDS': 6, 'RUSHFUMBLES': -2,
    'RECEIVECATCHES': 0.5, 'RECEIVEYARDS': 0.1, 'RECEIVETDS': 6, 'KRETYARDS': 0.04, 'PRETYARDS': 0.04, 'KRETTDS': 6, 'PRETTDS': 6,
    'DEFTACKLES': 1, 'ASSDEFTACKLES': 0.5, 'DEFTACKLESFORLOSS': 1, 'DLINESACKS': 3, 'DLINEHALFSACK': 1.5, 'DSECINTS': 5,
    'DEFPASSDEFLECTIONS': 1.5, 'DLINEFORCEDFUMBLES': 3, 'DLINEFUMBLERECOVERIES': 2, 'DSECINTTDS': 6, 'DLINEFUMBLETDS': 6, 'DLINESAFETIES': 2,
}

def production_score(stats):
    return sum(PRODUCTION_POINTS.get(key, 0) * value for key, value in (stats or {}).items())

def freshman_card(ctx):
    freshmen = [(pid, e) for pid, e in ctx['week_stats'].items()
                if ctx['players'].get(pid, {}).get('class_year') == 'Freshman' and ctx['players'][pid]['position'] not in ('K', 'P')]
    if not freshmen:
        return None
    pid, entry = max(freshmen, key=lambda item: (production_score(item[1]['stats']), impact_score(item[1]['stats'])))
    return player_card(pid, entry, ctx)

def bummer_card(ctx):
    """The rough day: heavy usage, turnovers and a low rating, on the losing side (worse if his team was ranked)."""
    best, best_score = None, 0
    for pid, entry in ctx['week_stats'].items():
        player, stats = ctx['players'].get(pid), entry['stats']
        game = ctx['games_by_id'].get(entry['game_id'])
        if not player or not game or (stats.get('PASSATTEMPTS', 0) < 15 and stats.get('RUSHATTEMPTS', 0) < 10):
            continue
        if side_result(game, player['team_id'])[0] != 'L':
            continue
        score = 12 * turnovers(stats) + max(0, 45 - stats.get('GAMERATING', 0)) / 2
        if ctx['ranks_before'].get(player['team_id'], 99) <= TOP_25:
            score += 10
        if score > best_score:
            best, best_score = (pid, entry), score
    if not best:
        return None
    stats = best[1]['stats']
    note = None
    if stats.get('PASSATTEMPTS'):
        note = (f"{round(100 * stats.get('PASSCOMPLETED', 0) / stats['PASSATTEMPTS'])}% completions, "
                f"{stats.get('PASSYARDS', 0) / stats['PASSATTEMPTS']:.1f} per attempt, {stats.get('PASSINTS', 0)} INT")
    return player_card(best[0], best[1], ctx, note)

def game_of_the_week(ctx):
    close = [g for g in ctx['week_games'] if abs(g['home_score'] - g['away_score']) <= CLOSE_GAME_MARGIN]
    if not close:
        return None
    ranked_bonus = lambda g: sum(2 for side in ('home_id', 'away_id') if ctx['ranks_before'].get(g[side], 99) <= TOP_25)
    game = max(close, key=lambda g: (3 * lead_changes(g) + (CLOSE_GAME_MARGIN - abs(g['home_score'] - g['away_score'])) + ranked_bonus(g)))
    changes, margin = lead_changes(game), abs(game['home_score'] - game['away_score'])
    detail = f"{changes} lead change{'s' if changes != 1 else ''}, decided by {margin}" if changes else f"Decided by {margin}"
    return {"rows": box_score(game, ctx['teams'], ctx['ranks_before']), "tag": f"{margin} PTS", "detail": detail}

def biggest_comeback(ctx):
    best = None
    for g in ctx['week_games']:
        winner_home = g['home_score'] > g['away_score']
        for quarter, (home, away) in enumerate(running_scores(g)[:3]):
            deficit = (away - home) if winner_home else (home - away)
            if deficit > 0 and (not best or deficit > best[1]):
                best = (g, deficit, quarter)
    if not best:
        return None
    game, deficit, quarter = best
    winner = ctx['teams'][game['home_id'] if game['home_score'] > game['away_score'] else game['away_id']]
    return {"rows": box_score(game, ctx['teams'], ctx['ranks_before']), "tag": f"DOWN {deficit}",
            "detail": f"{winner['name']} trailed by {deficit} after the {QUARTER_NAMES[quarter]}"}

def blowout(ctx):
    games = [g for g in ctx['week_games'] if not any(is_fcs_placeholder(ctx['teams'][g[side]]) for side in ('home_id', 'away_id'))]
    if not games:
        return None
    game = max(games, key=lambda g: abs(g['home_score'] - g['away_score']))
    margin = abs(game['home_score'] - game['away_score'])
    detail = f"{margin}-point margin"
    if game['home_yards'] is not None and game['away_yards'] is not None:
        winner_home = game['home_score'] > game['away_score']
        yards = (game['home_yards'] - game['away_yards']) * (1 if winner_home else -1)
        detail += f", outgained by {yards} yards" if yards > 0 else f", despite being outgained by {-yards} yards"
    return {"rows": box_score(game, ctx['teams'], ctx['ranks_before']), "tag": f"+{margin}", "detail": detail}

def upset(ctx):
    """A ranked team losing to a lower-ranked or unranked one; the bigger the rank gap, the bigger the upset."""
    best, best_gap = None, 0
    for g in ctx['week_games']:
        winner, loser = (g['home_id'], g['away_id']) if g['home_score'] > g['away_score'] else (g['away_id'], g['home_id'])
        loser_rank = ctx['ranks_before'].get(loser)
        if not loser_rank or loser_rank > TOP_25:
            continue
        winner_rank = ctx['ranks_before'].get(winner) or 99
        gap = min(winner_rank, 40) - loser_rank
        if gap > best_gap:
            best, best_gap = (g, winner, loser, winner_rank), gap
    if not best:
        return None
    game, winner, loser, winner_rank = best
    who = f"#{winner_rank} " if winner_rank <= TOP_25 else "Unranked "
    return {"rows": box_score(game, ctx['teams'], ctx['ranks_before']), "tag": "UPSET",
            "detail": f"{who}{ctx['teams'][winner]['name']} took down #{ctx['ranks_before'][loser]} {ctx['teams'][loser]['name']}"}

def top_25_matchups(ctx):
    ranked = lambda team_id: ctx['ranks_before'].get(team_id, 99) <= TOP_25
    return [{"rows": box_score(g, ctx['teams'], ctx['ranks_before'])} for g in ctx['week_games'] if ranked(g['home_id']) and ranked(g['away_id'])]

def team_week_line(team_id, ctx):
    """'W 48-27 @ Florida State' for the team's game this week, or 'BYE'."""
    game = next((g for g in ctx['week_games'] if team_id in (g['home_id'], g['away_id'])), None)
    if not game:
        return "BYE"
    outcome, mine, theirs, venue, opponent = side_result(game, team_id)
    return f"{outcome} {mine}-{theirs} {venue} {ctx['teams'][opponent]['name']}"

def chances(ranks, records):
    return {team_id: playoff_chance(ranks.get(team_id), records.get(team_id, [0, 0])[1]) for team_id in ranks}

def cfp_picture(ctx):
    rows = sorted(ctx['chance_after'].items(), key=lambda item: -item[1])[:CFP_FIELD]
    return [{"seed": i + 1, "team": team_view(ctx['teams'][tid], ctx['ranks_after'].get(tid)),
             "record": "-".join(map(str, ctx['records_after'].get(tid, [0, 0]))), "chance": round(100 * chance, 1)}
            for i, (tid, chance) in enumerate(rows)]

def poll_movers(ctx, risers):
    if not ctx['ranks_before'] or not ctx['ranks_after']:
        return None  # This week's poll movement wasn't captured
    moves = []
    for tid, after in ctx['ranks_after'].items():
        before = ctx['ranks_before'].get(tid)
        if not before or not after:
            continue
        in_view = after <= TOP_25 if risers else before <= TOP_25
        delta = before - after
        if in_view and ((risers and delta > 0) or (not risers and delta < 0)):
            moves.append((tid, before, after, delta))
    moves.sort(key=lambda m: (-m[3], m[2]) if risers else (m[3], m[2]))
    return [{"team": team_view(ctx['teams'][tid]), "before": before, "after": after, "line": team_week_line(tid, ctx)}
            for tid, before, after, _ in moves[:LIST_SIZE]]

def biggest_swings(ctx):
    swings = [(tid, ctx['chance_after'][tid] - ctx['chance_before'].get(tid, 0)) for tid in ctx['chance_after']]
    swings = [s for s in swings if abs(s[1]) >= 0.005]
    swings.sort(key=lambda s: -abs(s[1]))
    return [{"team": team_view(ctx['teams'][tid], ctx['ranks_after'].get(tid)), "line": team_week_line(tid, ctx),
             "now": round(100 * ctx['chance_after'][tid], 1), "delta": round(100 * delta, 1)} for tid, delta in swings[:LIST_SIZE]]

def active_streaks(ctx):
    """Current winning and losing streaks as of this week, longest first."""
    results = {}
    for g in ctx['season_games']:
        for tid in (g['home_id'], g['away_id']):
            results.setdefault(tid, []).append(side_result(g, tid)[0])
    streaks = []
    for tid, outcomes in results.items():
        if is_fcs_placeholder(ctx['teams'][tid]):
            continue
        last = outcomes[-1]
        # Count back from the latest game until the result changes
        length = next((i for i, o in enumerate(reversed(outcomes)) if o != last), len(outcomes))
        streaks.append((tid, last, length))
    rank = lambda tid: ctx['ranks_after'].get(tid) or 99
    pick = lambda kind: [{"team": team_view(ctx['teams'][tid], ctx['ranks_after'].get(tid)), "streak": f"{kind}{length}"}
                         for tid, last, length in sorted((s for s in streaks if s[1] == kind), key=lambda s: (-s[2], rank(s[0])))[:STREAK_ROWS]]
    return {"winning": pick('W'), "losing": pick('L')}

def heisman_race(ctx):
    totals = {}
    heisman = league.query_heisman()
    for row in league.query_player_games(through_week=ctx['week'], player_ids={h['player_id'] for h in heisman}):
        bucket = totals.setdefault(row['player_id'], {})
        for key, value in row['stats'].items():
            if key != 'GAMERATING' and 'LONGEST' not in key:
                bucket[key] = bucket.get(key, 0) + value
    rows = []
    for h in heisman:
        player = ctx['players'].get(h['player_id'])
        if not player or not totals.get(h['player_id']):
            continue
        movement = (h['last_rank'] - h['rank']) if h['last_rank'] and h['rank'] else 0
        rows.append({"id": h['player_id'], "rank": h['rank'], "movement": movement, "name": player['name'], "position": player['position'],
                     "portrait": media.portrait_url("player", player.get('portrait_file')),
                     "team": team_view(ctx['teams'][player['team_id']], ctx['ranks_after'].get(player['team_id'])),
                     "boxes": [{"label": label, "value": value} for label, value in stat_boxes(totals.get(h['player_id'], {}))]})
    return rows

# ---------- Entry points ----------

def available_weeks():
    """Weeks with finished games; a week still being played is flagged so the page can say so."""
    unfinished = league.query_unplayed_weeks()
    return [{"week": week, "games": count, "in_progress": week in unfinished} for week, count in league.query_played_weeks()]

def default_week():
    """The latest week that's fully played (falling back to the latest week with any results)."""
    weeks = available_weeks()
    finished = [w['week'] for w in weeks if not w['in_progress']]
    return finished[-1] if finished else (weeks[-1]['week'] if weeks else None)

@per_request
def build_recap(week):
    season_games = league.query_games(through_week=week)
    ranks_before, ranks_after = league.query_poll(week - 1), league.query_poll(week)
    records_before, records_after = records_through(season_games, week - 1), records_through(season_games, week)
    ctx = {
        "week": week,
        "teams": league.query_teams(),
        "players": league.query_players(),
        "season_games": season_games,
        "week_games": [g for g in season_games if g['week'] == week],
        "awards": league.query_awards(week),
        "week_stats": merged_week_stats(league.query_player_games(week=week)),
        "ranks_before": ranks_before, "ranks_after": ranks_after,
        "records_after": records_after,
        "chance_before": chances(ranks_before or ranks_after, records_before),
        "chance_after": chances(ranks_after or ranks_before, records_after),
    }
    ctx['games_by_id'] = {g['game_id']: g for g in season_games}
    return {
        "week": week,
        "game_count": len(ctx['week_games']),
        "polls_captured": bool(ranks_before and ranks_after),
        "players": {
            "offense": award_card('Offensive_Player_of_Week', ctx),
            "defense": award_card('Defensive_Player_of_Week', ctx),
            "freshman": freshman_card(ctx),
            "bummer": bummer_card(ctx),
        },
        "games": {
            "game_of_the_week": game_of_the_week(ctx),
            "comeback": biggest_comeback(ctx),
            "blowout": blowout(ctx),
            "upset": upset(ctx),
        },
        "top25": top_25_matchups(ctx),
        "cfp": cfp_picture(ctx),
        "risers": poll_movers(ctx, risers=True),
        "fallers": poll_movers(ctx, risers=False),
        "swings": biggest_swings(ctx),
        "streaks": active_streaks(ctx),
        "heisman": heisman_race(ctx),
    }

# ---------- Scores ticker ----------

TICKER_GAMES = 24

def scoreboard():
    """The latest week's finals for the ticker under the menu: our game first, then games with ranked teams, then the rest."""
    weeks = league.query_played_weeks()
    if not weeks:
        return None
    week = weeks[-1][0]
    teams = league.query_teams()
    ranks = league.query_poll(week - 1)  # the rank each team carried into the game
    user = next((tid for tid, t in teams.items() if t.get('is_user')), None)
    games = []
    for g in league.query_games(week=week):
        home, away = teams.get(g['home_id']), teams.get(g['away_id'])
        if not home or not away:
            continue
        best_rank = min(ranks.get(g['home_id']) or 99, ranks.get(g['away_id']) or 99)
        games.append({
            "ours": user in (g['home_id'], g['away_id']),
            "best_rank": best_rank,
            "rows": [{**team_view(t, ranks.get(t['team_id'])), "score": score, "won": score > other}
                     for t, score, other in ((away, g['away_score'], g['home_score']), (home, g['home_score'], g['away_score']))],
        })
    games.sort(key=lambda g: (not g['ours'], g['best_rank'], abs(g['rows'][0]['score'] - g['rows'][1]['score'])))
    return {"week": week, "in_progress": week in league.query_unplayed_weeks(), "games": games[:TICKER_GAMES]}
