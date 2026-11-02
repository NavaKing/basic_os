import json
import re
import database
import league
import media
import recap
from sentences import split as sentence_split

# Awards tab: the game's All-America and All-Conference teams, a Heisman column, and bowl season
# (a projected 12-team playoff bracket until the game sets the real one, plus every bowl on the schedule).

ALL_AMERICA = re.compile(r"^ALL_AM_(1ST|2ND)(_PRE)?(_CONF)?$")
# Display names where the save's short name would mislead ("All-American" reads as the national honor)
CONFERENCE_NAMES = {"American": "American Athletic"}

def conference_label(name):
    return CONFERENCE_NAMES.get(name, name)
POSITION_ORDER = ["QB", "HB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT", "LEDG", "LE", "DT", "RE", "REDG",
                  "SAM", "LOLB", "MIKE", "MLB", "WILL", "ROLB", "CB", "FS", "SS", "K", "P", "KR", "PR", "ATH"]

# The playoff games in the save's schedule, by name, in bracket order
CFP_ROUNDS = [("CFP First Round", "First Round"), ("CFP Quarterfinal", "Quarterfinals"),
              ("CFP Semifinal", "Semifinals"), ("National Championship", "National Championship")]
CFP_NAMES = {name for name, _ in CFP_ROUNDS}
# 12-team format: seeds 5-12 play the first round at the higher seed; 1-4 wait in the quarterfinals.
# Listed top to bottom so each quarterfinal sits beside the first-round game that feeds it.
FIRST_ROUND = [(8, 9), (5, 12), (6, 11), (7, 10)]
BYES = [1, 4, 3, 2]

def initialize_awards_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS award_columns (
        column_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,             -- 'heisman_watch' during the season, 'heisman_ceremony' once it's over
        week INTEGER,
        title TEXT,
        body TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- All-America and All-Conference ----------

def position_key(position):
    return POSITION_ORDER.index(position) if position in POSITION_ORDER else len(POSITION_ORDER)

def player_view(row, teams, user_id):
    team = teams.get(row['team_id'])
    return {"id": row['player_id'], "name": row['name'], "position": row['position'], "jersey": row['jersey'], "overall": row['overall'],
            "class": recap.class_label(row), "portrait": media.portrait_url("player", row['portrait_file']),
            "team": recap.team_view(team) if team else None, "ours": row['team_id'] == user_id}

def all_america(rows, teams, user_id, user_conference):
    """The final teams once the game names them, otherwise the preseason ones. Our conference is listed first."""
    picks = [(ALL_AMERICA.match(r['award_type']), r) for r in rows]
    picks = [(m, r) for m, r in picks if m]
    final = any(not m.group(2) for m, _ in picks)
    groups = {}
    for m, r in picks:
        if bool(m.group(2)) == final:
            continue
        group = groups.setdefault(r['conference'] if m.group(3) else None, {"first": [], "second": []})
        group["first" if m.group(1) == "1ST" else "second"].append(player_view(r, teams, user_id))
    for group in groups.values():
        for side in group.values():
            side.sort(key=lambda p: position_key(p['position']))
    national = groups.pop(None, None)
    conferences = [{"name": name, "label": conference_label(name), **group} for name, group in groups.items() if name]
    conferences.sort(key=lambda c: (c['name'] != user_conference, c['name']))
    return {"stage": "Final" if final else "Preseason", "national": national, "conferences": conferences,
            "ours": sum(p['ours'] for g in [national or {}] + conferences for side in ("first", "second") for p in g.get(side, []))}

# ---------- Bowl season ----------

def bowl_view(b, teams, ranks):
    def side(team_id, score):
        team = teams.get(team_id)
        return {"team": recap.team_view(team, ranks.get(team_id)), "score": score} if team else None
    home, away = side(b['home_id'], b['home_score']), side(b['away_id'], b['away_score'])
    if b['played'] and home and away:
        home['won'], away['won'] = b['home_score'] > b['away_score'], b['away_score'] > b['home_score']
    return {"name": b['name'], "date": b['game_date'], "week": b['week'], "home": home, "away": away, "played": bool(b['played'])}

def projected_bracket(cfp, games):
    """The playoff if it started today, seeded from the recap's playoff odds (the save picks the real field later)."""
    seeds = {row['seed']: row for row in cfp}
    slot = lambda seed: {"seed": seed, "team": seeds[seed]['team'], "record": seeds[seed]['record']} if seed in seeds else {"seed": seed}
    dates = {name: [g['date'] for g in games if g['name'] == name] for name in CFP_NAMES}
    date = lambda name, i: dates[name][i] if i < len(dates[name]) else None
    rounds = [
        {"name": "First Round", "games": [{"top": slot(high), "bottom": slot(low), "date": date("CFP First Round", i), "note": f"at No. {high}"}
                                          for i, (high, low) in enumerate(FIRST_ROUND)]},
        {"name": "Quarterfinals", "games": [{"top": slot(bye), "bottom": {"label": f"Winner {high}/{low}"}, "date": date("CFP Quarterfinal", i)}
                                            for i, (bye, (high, low)) in enumerate(zip(BYES, FIRST_ROUND))]},
        {"name": "Semifinals", "games": [{"top": {"label": "Quarterfinal 1 winner"}, "bottom": {"label": "Quarterfinal 2 winner"}, "date": date("CFP Semifinal", 0)},
                                         {"top": {"label": "Quarterfinal 3 winner"}, "bottom": {"label": "Quarterfinal 4 winner"}, "date": date("CFP Semifinal", 1)}]},
        {"name": "National Championship", "games": [{"top": {"label": "Semifinal winner"}, "bottom": {"label": "Semifinal winner"},
                                                     "date": date("National Championship", 0)}]},
    ]
    return rounds

def actual_bracket(games):
    rounds = []
    for name, label in CFP_ROUNDS:
        games_in = [g for g in games if g['name'] == name]
        rounds.append({"name": label, "games": [{"top": g['away'] or {"label": "TBD"}, "bottom": g['home'] or {"label": "TBD"},
                                                 "date": g['date'], "played": g['played']} for g in games_in]})
    return rounds

def bowl_season(teams, ranks, cfp):
    games = [bowl_view(b, teams, ranks) for b in league.query_bowls()]
    playoff = [g for g in games if g['name'] in CFP_NAMES]
    field_set = any(g['home'] or g['away'] for g in playoff)
    bowls = [g for g in games if g['name'] not in CFP_NAMES]
    return {"field_set": field_set, "bracket": actual_bracket(playoff) if field_set else projected_bracket(cfp, playoff),
            "bowls": bowls, "bowls_set": sum(1 for g in bowls if g['home'] or g['away'])}

# ---------- Heisman column ----------

def regular_season_over():
    return not league.query_rows("SELECT 1 FROM league_games WHERE played = 0 AND week_type = 'RegularSeason' LIMIT 1")

def query_column():
    rows = league.query_rows("SELECT * FROM award_columns ORDER BY column_id DESC LIMIT 1")
    if not rows:
        return None
    column = rows[0]
    return {"kind": column['kind'], "week": column['week'], "title": column['title'],
            "paragraphs": [p.strip() for p in column['body'].split("\n\n") if p.strip()]}

# The recap's stat box labels, spelled out so the model can't misread them ("YAC" is yards after the catch)
STAT_WORDS = {"Pass Yds": "passing yards", "Pass TD": "passing touchdowns", "INT": "interceptions", "Comp %": "completion percentage",
              "Car": "carries", "Rush Yds": "rushing yards", "Rush TD": "rushing touchdowns", "YPC": "yards per carry",
              "Rec": "catches", "Rec Yds": "receiving yards", "TD": "touchdowns", "YAC": "yards after the catch",
              "Tkl": "tackles", "Sack": "sacks", "PBU": "pass breakups", "FF": "forced fumbles", "FG": "field goals made",
              "Long": "longest field goal", "XP": "extra points made"}
COLUMN_PARAGRAPHS = 4

def heisman_facts(heisman):
    lines = []
    for row in heisman[:5]:
        stats = ", ".join(f"{b['value']} {STAT_WORDS.get(b['label'], b['label'])}" for b in row['boxes'])
        spots = lambda n: f"{n} spot{'s' if n != 1 else ''}"
        move = (f"up {spots(row['movement'])} this week" if row['movement'] > 0 else
                f"down {spots(-row['movement'])} this week" if row['movement'] < 0 else "unchanged this week")
        lines.append(f"No. {row['rank']} {row['name']}, {row['position']}, {row['team']['name']} ({move}): {stats}.")
    return " ".join(lines)

def paragraphs(text, count=COLUMN_PARAGRAPHS):
    """Keeps the model's paragraphs; a column that came back as one block is split into about `count` by sentence."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return "\n\n".join(parts)
    sentences = sentence_split(text)
    size = max(1, -(-len(sentences) // count))
    return "\n\n".join(" ".join(sentences[i:i + size]) for i in range(0, len(sentences), size))

def generate_heisman_column(selected_model):
    import ai_engine
    week = recap.default_week()
    if week is None:
        raise ValueError("No games have been played yet.")
    heisman = recap.build_recap(week)['heisman']
    if not heisman:
        raise ValueError("The save has no Heisman ranking yet.")
    ceremony = regular_season_over()
    kind = "heisman_ceremony" if ceremony else "heisman_watch"
    task = ("Write the story of the Heisman Trophy ceremony in New York: build up the finalists, then name the winner, who is the No. 1 player below, "
            "and describe the moment he hears his name." if ceremony else
            f"Write a Heisman Watch column after Week {week}: who leads the race, who is rising or falling, and what each contender must do from here.")
    prompt = (f"You are a national college football columnist. {task} Use only these facts and stats, and never invent games, quotes or numbers: "
              f"{heisman_facts(heisman)} Only call a player rising or falling if the facts say he moved. "
              f"Write {COLUMN_PARAGRAPHS} paragraphs separated by blank lines, vivid but grounded in the numbers. "
              'Respond with ONLY JSON: {"title": "headline under 10 words", "body": "the column"}')
    for _attempt in range(3):
        try:
            data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
            body = paragraphs(ai_engine.clean_text(str(data.get('body') or "")))
            if len(body) > 200:
                break
        except Exception:
            continue
    else:
        raise RuntimeError("The model didn't return a usable column. Is Ollama running?")
    conn = database.get_db_connection()
    conn.execute("INSERT INTO award_columns (kind, week, title, body) VALUES (?, ?, ?, ?)",
                 (kind, week, ai_engine.clean_text(str(data.get('title') or "")) or "The Heisman Race", body))
    conn.commit()
    conn.close()
    return query_column()

# ---------- Page ----------

def our_all_america():
    teams = league.query_teams()
    user = next((t for t in teams.values() if t.get('is_user')), None)
    return all_america(league.query_season_awards(), teams, user['team_id'] if user else None, user.get('conference') if user else None)

def conference_teams(name):
    """One conference's first and second teams (the page loads the others on demand), or None."""
    return next(({"first": c['first'], "second": c['second']} for c in our_all_america()['conferences'] if c['name'] == name), None)

def page_all_america():
    """All-America plus our conference (listed first) for the page; the other conferences carry only their names."""
    aa = our_all_america()
    aa['conferences'] = [c if i == 0 else {"name": c['name'], "label": c['label']} for i, c in enumerate(aa['conferences'])]
    return aa

def build_awards():
    teams = league.query_teams()
    user = next((t for t in teams.values() if t.get('is_user')), None)
    week = recap.default_week()
    page = recap.build_recap(week) if week is not None else {"cfp": [], "heisman": []}
    ranks = league.query_poll(week) if week is not None else {}
    return {
        "week": week,
        "conference": user.get('conference') if user else None,
        "all_america": page_all_america(),
        "heisman": page['heisman'][:5],
        "column": query_column(),
        "ceremony": regular_season_over(),
        "postseason": bowl_season(teams, ranks, page['cfp']),
    }

initialize_awards_tables()
