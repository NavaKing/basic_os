import json
import re
import database
import gameplan
import league
import media
import recap
import team
from sentences import split as sentence_split

# Coaches news column: the top 10 and the hot seat for head coaches, offensive and defensive coordinators.
# Rankings come from results in the save; the headline and quote for each coach are written by the AI.

LIST_SIZE = 10
ROLES = {"hc": "Head Coach", "oc": "Offensive Coordinator", "dc": "Defensive Coordinator"}

def initialize_coach_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS coach_news (
        week_num INTEGER NOT NULL,
        role TEXT NOT NULL,          -- 'hc', 'oc' or 'dc'
        list TEXT NOT NULL,          -- 'top' or 'hot'
        team_id INTEGER NOT NULL,
        headline TEXT,
        quote TEXT,
        PRIMARY KEY (week_num, role, list, team_id)
    )
    """)
    conn.commit()
    conn.close()

def team_seasons():
    """Every real (non-placeholder) team with its record, scoring, yards, rank and next/last games."""
    teams = league.query_teams()
    games = league.query_games()
    polls = league.query_played_weeks()
    latest_poll = league.query_poll(max((w for w, _ in polls), default=0))
    all_games = league.query_rows("SELECT * FROM league_games ORDER BY week")
    seasons = {}
    for tid, t in teams.items():
        if recap.is_fcs_placeholder(t):
            continue
        played = [g for g in games if tid in (g['home_id'], g['away_id'])]
        pf = sum(g['home_score'] if g['home_id'] == tid else g['away_score'] for g in played)
        pa = sum(g['away_score'] if g['home_id'] == tid else g['home_score'] for g in played)
        yf = sum((g['home_yards'] if g['home_id'] == tid else g['away_yards']) or 0 for g in played)
        ya = sum((g['away_yards'] if g['home_id'] == tid else g['home_yards']) or 0 for g in played)
        wins = sum(1 for g in played if recap.side_result(g, tid)[0] == 'W')
        n = len(played) or 1
        last = None
        if played:
            outcome, mine, theirs, venue, opp = recap.side_result(played[-1], tid)
            last = f"{outcome} {mine}-{theirs} {venue} {teams[opp]['name']}"
        upcoming = next((g for g in all_games if not g['played'] and tid in (g['home_id'], g['away_id'])), None)
        nxt = None
        if upcoming:
            home = upcoming['home_id'] == tid
            nxt = f"{'vs' if home else '@'} {teams[upcoming['away_id'] if home else upcoming['home_id']]['name']} (Week {upcoming['week']})"
        ratings = json.loads(t.get('ratings_json') or "{}")
        rank = latest_poll.get(tid)
        seasons[tid] = {"row": t, "games": len(played), "wins": wins, "losses": len(played) - wins,
                        "ppg": round(pf / n, 1), "papg": round(pa / n, 1), "ypg": round(yf / n), "yapg": round(ya / n),
                        "rank": rank if rank and rank <= recap.TOP_25 else None, "ovr": ratings.get('OVR') or 0,
                        "last": last, "next": nxt}
    return seasons

def rankings(seasons):
    """{role: {'top': [team ids], 'hot': [team ids]}} ranked from results."""
    played = [s for s in seasons.values() if s['games']]
    tid = lambda s: s['row']['team_id']
    win_pct = lambda s: s['wins'] / s['games']
    # Head coaches: the poll first, then winning; the hot seat is losing with a roster that should be winning
    hc_top = sorted(played, key=lambda s: (s['rank'] or 99, -win_pct(s), -s['ovr']))
    hc_hot = sorted(played, key=lambda s: (-(s['losses'] - s['wins']) * 2 - max(0, s['ovr'] - 70) / 5, s['ppg'] - s['papg']))
    oc_top = sorted(played, key=lambda s: (-s['ppg'], -s['ypg']))
    oc_hot = sorted(played, key=lambda s: (s['ppg'], s['ypg']))
    dc_top = sorted(played, key=lambda s: (s['papg'], s['yapg']))
    dc_hot = sorted(played, key=lambda s: (-s['papg'], -s['yapg']))
    pick = lambda ordered: [tid(s) for s in ordered[:LIST_SIZE]]
    return {"hc": {"top": pick(hc_top), "hot": pick(hc_hot)}, "oc": {"top": pick(oc_top), "hot": pick(oc_hot)},
            "dc": {"top": pick(dc_top), "hot": pick(dc_hot)}}

def stat_line(role, s):
    record = f"{s['wins']}-{s['losses']}"
    if role == "oc":
        return f"{s['ppg']:g} pts/g · {s['ypg']} yds/g"
    if role == "dc":
        return f"{s['papg']:g} allowed/g · {s['yapg']} yds/g"
    return record + (f" · AP #{s['rank']}" if s['rank'] else "")

def coach_card(role, s, stored):
    row = s['row']
    member = json.loads(row.get('staff_json') or "{}").get(role) or {}
    news = stored.get(row['team_id'], {})
    return {"team_id": row['team_id'], "team": row['name'], "logo": media.logo_url(row['short_name']), "color": row['color'],
            "name": member.get('name') or "Unknown", "portrait": media.portrait_url("coach", member.get('portrait')),
            "role": ROLES[role], "record": f"{s['wins']}-{s['losses']}", "rank": s['rank'], "stat": stat_line(role, s),
            "scheme": gameplan.scheme_label(row.get('off_scheme') if role == "oc" else row.get('def_scheme')) if role != "hc" else None,
            "last": s['last'], "next": s['next'], "headline": news.get('headline'), "quote": news.get('quote')}

def current_week():
    game = database.query_active_week()
    return game['week_id'] if game else 0

def query_stored(week, role, list_name):
    conn = database.get_db_connection()
    rows = conn.execute("SELECT team_id, headline, quote FROM coach_news WHERE week_num = ? AND role = ? AND list = ?", (week, role, list_name)).fetchall()
    conn.close()
    return {r['team_id']: dict(r) for r in rows}

def build_news():
    seasons = team_seasons()
    ranked = rankings(seasons)
    week = current_week()
    return {"week": week, "lists": {role: {name: [coach_card(role, seasons[t], query_stored(week, role, name)) for t in ids]
                                           for name, ids in lists.items()} for role, lists in ranked.items()}}

def clean_quote(text):
    """Drops a leading 'Coach X says,' and the wrapping quote marks the model sometimes adds."""
    # Only a capitalized name followed by "says," or "said:" (so "We said we would..." is left alone)
    text = re.sub(r"^(Coach\s+)?[A-Z][\w.'-]*(\s+[A-Z][\w.'-]*){0,3}\s+(says|said)[,:]\s*", "", text.strip())
    return text.strip().strip('"').strip("'").strip()

# Each coach gets one angle so the column doesn't read like ten copies of the same press conference
ANGLES = {
    "top": ["the game he just played, naming the score", "his next opponent, naming them",
            "the player named in his facts and what he means to the team", "what his scheme asks of his players",
            "handling the expectations that come with his team's ranking or record"],
    "hot": ["answering the criticism head-on", "why the next game matters, naming the opponent",
            "a player named in his facts who is giving him hope", "one specific thing that changes in practice this week",
            "what the last game, with its score, taught him"],
}
BANNED = "get back on track, execute, scratching the surface, energy, at the end of the day, one game at a time, we have to be better"
TONES = ["dry and matter-of-fact", "fiery", "relaxed, with a touch of humor", "measured and analytical", "short and blunt", "upbeat"]
MAX_QUOTE_SENTENCES = 2

def tidy_quote(text):
    """Keeps the first two sentences (the model sometimes writes a whole press conference)."""
    sentences = sentence_split(text)
    return " ".join(sentences[:MAX_QUOTE_SENTENCES])

def uses_banned(text):
    lowered = text.lower()
    return any(phrase.strip() in lowered for phrase in BANNED.split(","))
NEWS_WORKERS = 4      # requests sent to Ollama at once
NEWS_TEMPERATURE = 1.0

def team_top_players():
    """{team_id: {'offense': (name, position, line), 'defense': (...), 'any': (...)}} from season stats."""
    import roster
    players = league.query_players()
    totals = {}
    for row in league.query_player_games():
        bucket = totals.setdefault(row['player_id'], {})
        for key, value in row['stats'].items():
            if key != 'GAMERATING' and 'LONGEST' not in key:
                bucket[key] = bucket.get(key, 0) + value
    defensive = {'DE', 'LE', 'RE', 'DT', 'LOLB', 'MLB', 'ROLB', 'CB', 'FS', 'SS', 'EDGE', 'SAM', 'MIKE', 'WILL'}
    best = {}
    for pid, stats in totals.items():
        p = players.get(pid)
        if not p or p['position'] in ('K', 'P'):
            continue
        score = recap.production_score(stats)
        side = 'defense' if p['position'] in defensive else 'offense'
        entry = (score, p['name'], p['position'], roster.format_stat_line(stats, 'prose'))
        team_best = best.setdefault(p['team_id'], {})
        for key in (side, 'any'):
            if key not in team_best or score > team_best[key][0]:
                team_best[key] = entry
    return {tid: {k: v[1:] for k, v in sides.items()} for tid, sides in best.items()}

def coach_prompt(role, list_name, card, index, top_players):
    player = (top_players.get(card['team_id']) or {}).get({"oc": "offense", "dc": "defense"}.get(role, "any"))
    facts = [f"{card['name']} is the {card['role'].lower()} at {card['team']} ({card['record']}{', AP #' + str(card['rank']) if card['rank'] else ''}).",
             f"His unit this season: {card['stat']}." if role != "hc" else "",
             f"Scheme: {card['scheme']}." if card['scheme'] else "",
             f"Last game: {card['last']}." if card['last'] else "",
             f"Next game: {card['next']}." if card['next'] else "",
             f"His top player: {player[1]} {player[0]}, who has {player[2]} this season." if player and player[2] else ""]
    situation = "is one of the ten best in the country right now" if list_name == "top" else "is on the hot seat"
    angle = ANGLES[list_name][index % len(ANGLES[list_name])]
    tone = TONES[(index * 7 + len(card['team'])) % len(TONES)]
    return (f"You write a college football column about what coaches are saying. This {card['role'].lower()} {situation}. "
            + " ".join(f for f in facts if f)
            + f" Write a headline (under 10 words) and a quote of at most two short sentences (under 40 words) in his own voice. Angle: {angle}. Tone: {tone}. "
            "The quote must mention at least one specific fact from above (a score, an opponent, a player or a number) so it could only come from him. "
            f"Never use these phrases: {BANNED}. Use only the facts given: never invent scores, stats, injuries or players. "
            "The quote is only his words, with no attribution like 'he said'. "
            'Respond with ONLY a JSON object: {"headline": "...", "quote": "..."}')

def generate_news(selected_model):
    """Writes a headline and a quote for every coach on all six lists, one coach per request."""
    import ai_engine
    from concurrent.futures import ThreadPoolExecutor
    news = build_news()
    week = news['week']
    top_players = team_top_players()
    jobs = [(role, list_name, card, index) for role, lists in news['lists'].items()
            for list_name, cards in lists.items() for index, card in enumerate(cards)]

    def write(job):
        role, list_name, card, index = job
        for _attempt in range(3):  # retry a broken response or one that falls back on banned coach-speak
            try:
                data = json.loads(ai_engine.call_ollama(selected_model, coach_prompt(role, list_name, card, index, top_players),
                                                        force_json=True, temperature=NEWS_TEMPERATURE))
                quote = tidy_quote(clean_quote(ai_engine.strip_tags(data.get('quote') or "")))
                if quote and (not uses_banned(quote) or _attempt == 2):
                    return (week, role, list_name, card['team_id'], ai_engine.strip_tags(data.get('headline') or ""), quote)
            except Exception:
                continue
        return None

    with ThreadPoolExecutor(max_workers=NEWS_WORKERS) as pool:
        rows = [row for row in pool.map(write, jobs) if row]
    if not rows:
        raise RuntimeError("The model didn't return any coach news. Is Ollama running?")
    conn = database.get_db_connection()
    conn.executemany("INSERT OR REPLACE INTO coach_news (week_num, role, list, team_id, headline, quote) VALUES (?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return build_news()

# Auto-initialize when coaches.py gets imported
initialize_coach_tables()
