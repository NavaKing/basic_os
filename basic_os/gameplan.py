import json
import math
import re
import database
import league
import media
import recap
import team

# Coaches tab game plan: player-vs-player matchups scored from the save's ratings, grouped into
# where we win, where they can hurt us, and what comes down to the call. The AI adds coaching notes,
# keys to the game and scouting bullets on demand; everything else is computed from the save.

DECISIVE, CLEAR, SLIGHT = 8, 5, 2.5   # rating edge needed for each grade
HOME_EDGE = 3                         # rating points home field is worth in the estimate
INJURY_TEXT = {"CoupleGames": "Questionable", "SeveralGames": "Out", "Season": "Out for the season"}
QB_RATINGS = [("THP", "Arm"), ("SAC", "Short acc"), ("MAC", "Mid acc"), ("DAC", "Deep acc"), ("TUP", "Under pressure"), ("SPD", "Speed")]

def initialize_gameplan_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS game_plans (
        week_num INTEGER PRIMARY KEY,
        opponent_name TEXT NOT NULL,
        plan_json TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- Rating formulas (0-100 scale, same weights for both sides) ----------

def avg(*values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else 0

def r(player, key):
    return (player or {}).get('ratings', {}).get(key, 0)

def pass_block(p):  return 0.5 * r(p, 'PBK') + 0.25 * r(p, 'PBP') + 0.25 * r(p, 'PBF')
def run_block(p):   return 0.5 * r(p, 'RBK') + 0.25 * r(p, 'RBP') + 0.25 * r(p, 'RBF')
def pass_rush(p):   return 0.4 * max(r(p, 'PMV'), r(p, 'FMV')) + 0.2 * r(p, 'BSH') + 0.2 * r(p, 'ACC') + 0.2 * r(p, 'STR')
def run_stop(p):    return 0.45 * r(p, 'BSH') + 0.25 * r(p, 'STR') + 0.15 * r(p, 'TAK') + 0.15 * r(p, 'PRC')
def receiver(p):    return 0.25 * r(p, 'SPD') + 0.2 * r(p, 'RLS') + 0.3 * avg(r(p, 'SRR'), r(p, 'MRR'), r(p, 'DRR')) + 0.25 * r(p, 'CTH')
def coverage(p):    return 0.3 * max(r(p, 'MCV'), r(p, 'ZCV')) + 0.2 * r(p, 'PRS') + 0.3 * r(p, 'SPD') + 0.2 * r(p, 'PRC')
def deep_threat(p): return 0.5 * r(p, 'SPD') + 0.3 * r(p, 'DRR') + 0.2 * r(p, 'SPC')
def deep_cover(p):  return 0.4 * r(p, 'SPD') + 0.4 * r(p, 'ZCV') + 0.2 * r(p, 'PRC')
def ball_carrier(p): return 0.3 * r(p, 'BCV') + 0.25 * r(p, 'BTK') + 0.2 * r(p, 'SPD') + 0.25 * max(r(p, 'JKM'), r(p, 'TRK'))
def tackler(p):     return 0.35 * r(p, 'TAK') + 0.25 * r(p, 'PUR') + 0.2 * r(p, 'PRC') + 0.2 * r(p, 'SPD')
def lb_cover(p):    return 0.4 * r(p, 'ZCV') + 0.2 * r(p, 'MCV') + 0.2 * r(p, 'SPD') + 0.2 * r(p, 'PRC')
def protector(p):   return 0.6 * r(p, 'PBK') + 0.2 * r(p, 'AWR') + 0.2 * r(p, 'STR')
def blitzer(p):     return 0.4 * max(r(p, 'PMV'), r(p, 'FMV')) + 0.3 * r(p, 'SPD') + 0.3 * r(p, 'ACC')
def poise(p):       return 0.4 * r(p, 'TUP') + 0.3 * r(p, 'AWR') + 0.3 * r(p, 'BSK')

# ---------- Lineups ----------

class Lineup:
    """A team's starters by depth chart slot, falling back to the best-rated player at the position."""
    def __init__(self, roster):
        self.players = {p['id']: p for p in roster['players']}
        self.chart = roster['depthChart']

    def slot(self, position, index=0, fallback=None):
        ids = [pid for pid in self.chart.get(position, []) if pid in self.players]
        if index < len(ids):
            return self.players[ids[index]]
        pool = sorted((p for p in self.players.values() if p['position'] in (fallback or (position,))), key=lambda p: -(p['overall'] or 0))
        taken = set(ids[:index])
        pool = [p for p in pool if p['id'] not in taken]
        offset = index - len(ids) if index >= len(ids) else 0
        return pool[offset] if offset < len(pool) else None

    def first_unused(self, positions, used):
        """The first player on these charts (in order) who isn't already starting elsewhere, e.g. the slot receiver."""
        taken = {p['id'] for p in used if p}
        for position in positions:
            for pid in self.chart.get(position, []):
                if pid in self.players and pid not in taken:
                    return self.players[pid]
        return None

    def best(self, positions, score):
        candidates = [self.slot(pos) for pos in positions]
        candidates = [c for c in candidates if c]
        return max(candidates, key=score) if candidates else None

def offense(l):
    qb = l.slot('QB')
    lefty = (qb or {}).get('handed') == 'Left'
    outside = [l.slot('WR', 0), l.slot('WR', 1)]
    wrs = outside + [l.first_unused(('SLWR', 'WR'), outside)]
    return {"QB": qb, "HB": l.slot('HB'), "TE": l.slot('TE'), "WR": [w for w in wrs if w],
            "LT": l.slot('LT'), "LG": l.slot('LG'), "C": l.slot('C'), "RG": l.slot('RG'), "RT": l.slot('RT'),
            # The blind side is the tackle behind the quarterback's throwing motion
            "BLIND": l.slot('RT') if lefty else l.slot('LT'), "FRONT": l.slot('LT') if lefty else l.slot('RT'), "lefty": lefty}

def outside_cbs(l):
    return [l.slot('CB', 0), l.slot('CB', 1)]

def defense(l):
    return {"LE": l.slot('LE'), "RE": l.slot('RE'), "DT": [d for d in (l.slot('DT', 0), l.slot('DT', 1, fallback=('DT', 'NT'))) if d],
            "LOLB": l.slot('LOLB'), "MLB": l.slot('MLB'), "ROLB": l.slot('ROLB'),
            "CB": [c for c in (*outside_cbs(l), l.first_unused(('SLCB', 'CB'), outside_cbs(l))) if c],
            "FS": l.slot('FS'), "SS": l.slot('SS')}

# ---------- Matchups ----------

def matchup(mid, label, ours, theirs, our_score, their_score, fact):
    if not ours or not theirs:
        return None
    return {"id": mid, "label": label, "ours": ours, "theirs": theirs,
            "edge": round(our_score - their_score, 1), "fact": fact}

def offense_matchups(o, d):
    """Our offense against their defense."""
    m = []
    blind_rusher = d['LE'] if o['lefty'] else d['RE']
    front_rusher = d['RE'] if o['lefty'] else d['LE']
    m.append(matchup("blind_side", "Blind-side protection", o['BLIND'], blind_rusher, pass_block(o['BLIND']), pass_rush(blind_rusher), "pass blocking vs pass rush moves"))
    m.append(matchup("front_side", "Front-side protection", o['FRONT'], front_rusher, pass_block(o['FRONT']), pass_rush(front_rusher), "pass blocking vs pass rush moves"))
    if d['DT']:
        dt = max(d['DT'], key=pass_rush)
        m.append(matchup("interior_pass", "Interior protection", o['C'], dt, avg(*(pass_block(p) for p in (o['LG'], o['C'], o['RG']) if p)), avg(*(pass_rush(t) for t in d['DT'])), "interior pass blocking vs interior rush"))
        m.append(matchup("run_inside", "Run game, inside", o['C'], max(d['DT'], key=run_stop), avg(*(run_block(p) for p in (o['LG'], o['C'], o['RG']) if p)), avg(*(run_stop(t) for t in d['DT'])), "interior run blocking vs block shedding"))
    m.append(matchup("run_left", "Run game, left side", o['LT'], d['RE'], avg(run_block(o['LT']), run_block(o['LG'])), run_stop(d['RE']), "run blocking vs block shedding"))
    m.append(matchup("run_right", "Run game, right side", o['RT'], d['LE'], avg(run_block(o['RT']), run_block(o['RG'])), run_stop(d['LE']), "run blocking vs block shedding"))
    for index, (wr, cb) in enumerate(zip(o['WR'], d['CB'])):
        label = "The slot" if index == 2 else "Outside receivers"
        m.append(matchup(f"wr_{index + 1}", label, wr, cb, receiver(wr), coverage(cb), "routes, release and hands vs coverage"))
    if o['WR'] and d['FS']:
        fastest = max(o['WR'], key=deep_threat)
        m.append(matchup("deep_ball", "Deep ball", fastest, d['FS'], deep_threat(fastest), deep_cover(d['FS']), "speed and deep routes vs safety range"))
    cover_lb = max((p for p in (d['LOLB'], d['MLB'], d['ROLB'], d['SS']) if p), key=lb_cover, default=None)
    m.append(matchup("tight_end", "Tight end", o['TE'], cover_lb, receiver(o['TE']), lb_cover(cover_lb) if cover_lb else 0, "receiving vs underneath coverage"))
    m.append(matchup("second_level", "Back vs the second level", o['HB'], d['MLB'], ball_carrier(o['HB']), tackler(d['MLB']), "vision and tackle-breaking vs tackling"))
    edge_lb = max((p for p in (d['LOLB'], d['ROLB']) if p), key=blitzer, default=None)
    m.append(matchup("blitz_pickup", "Blitz pickup", o['HB'], edge_lb, protector(o['HB']), blitzer(edge_lb) if edge_lb else 0, "back's pass protection vs blitzing linebacker"))
    best_rusher = max((p for p in (d['LE'], d['RE'], *d['DT']) if p), key=pass_rush, default=None)
    m.append(matchup("qb_pressure", "Quarterback under pressure", o['QB'], best_rusher, poise(o['QB']), pass_rush(best_rusher) if best_rusher else 0, "poise under pressure vs their best rusher"))
    return [x for x in m if x]

def defense_matchups(d, o):
    """Our defense against their offense (scored from our side: positive means we win it)."""
    m = []
    blind_rusher = d['LE'] if o['lefty'] else d['RE']
    front_rusher = d['RE'] if o['lefty'] else d['LE']
    m.append(matchup("edge_blind", "Edge rush, blind side", blind_rusher, o['BLIND'], pass_rush(blind_rusher), pass_block(o['BLIND']), "pass rush moves vs pass blocking"))
    m.append(matchup("edge_front", "Edge rush, front side", front_rusher, o['FRONT'], pass_rush(front_rusher), pass_block(o['FRONT']), "pass rush moves vs pass blocking"))
    if d['DT']:
        m.append(matchup("interior_rush", "Interior rush", max(d['DT'], key=pass_rush), o['C'], avg(*(pass_rush(t) for t in d['DT'])), avg(*(pass_block(p) for p in (o['LG'], o['C'], o['RG']) if p)), "interior rush vs interior pass blocking"))
        m.append(matchup("their_run_inside", "Their run game, inside", max(d['DT'], key=run_stop), o['C'], avg(*(run_stop(t) for t in d['DT'])), avg(*(run_block(p) for p in (o['LG'], o['C'], o['RG']) if p)), "block shedding vs interior run blocking"))
    m.append(matchup("their_run_edges", "Their run game, edges", d['LE'], o['RT'], avg(run_stop(d['LE']), run_stop(d['RE'])), avg(run_block(o['LT']), run_block(o['RT'])), "edge run defense vs tackle run blocking"))
    for index, (cb, wr) in enumerate(zip(d['CB'], o['WR'])):
        label = "Their slot" if index == 2 else "Their receivers"
        m.append(matchup(f"cb_{index + 1}", label, cb, wr, coverage(cb), receiver(wr), "coverage vs routes, release and hands"))
    if o['WR'] and d['FS']:
        fastest = max(o['WR'], key=deep_threat)
        m.append(matchup("deep_coverage", "Deep coverage", d['FS'], fastest, deep_cover(d['FS']), deep_threat(fastest), "safety range vs speed and deep routes"))
    cover_lb = max((p for p in (d['LOLB'], d['MLB'], d['ROLB'], d['SS']) if p), key=lb_cover, default=None)
    m.append(matchup("their_tight_end", "Their tight end", cover_lb, o['TE'], lb_cover(cover_lb) if cover_lb else 0, receiver(o['TE']), "underneath coverage vs receiving"))
    m.append(matchup("their_back", "Their back", d['MLB'], o['HB'], tackler(d['MLB']), ball_carrier(o['HB']), "tackling vs vision and tackle-breaking"))
    m.append(matchup("their_qb", "Getting home on the quarterback", max((p for p in (d['LE'], d['RE'], *d['DT']) if p), key=pass_rush, default=None), o['QB'],
                     pass_rush(max((p for p in (d['LE'], d['RE'], *d['DT']) if p), key=pass_rush, default=None)), poise(o['QB']), "our best rusher vs their quarterback's poise"))
    return [x for x in m if x]

def grade(edge):
    size = abs(edge)
    return "decisive" if size >= DECISIVE else "clear" if size >= CLEAR else "slight" if size >= SLIGHT else None

def group(matchups):
    win, lose, call = [], [], []
    for m in matchups:
        m['grade'] = grade(m['edge'])
        (call if not m['grade'] else win if m['edge'] > 0 else lose).append(m)
    win.sort(key=lambda m: -m['edge'])
    lose.sort(key=lambda m: m['edge'])
    call.sort(key=lambda m: -abs(m['edge']))
    return {"win": win, "lose": lose, "call": call}

# ---------- Display helpers ----------

def scheme_label(value):
    """'OFF_MULTIPLE_OFFENSE' -> 'Multiple', 'DEF_4_2_5' -> '4-2-5', 'DEF_3_4_MULTIPLE' -> '3-4 Multiple'."""
    words = re.sub(r"^(OFF|DEF)_", "", value or "").replace("_OFFENSE", "").split("_")
    digits = [w for w in words if w.isdigit()]
    rest = [w.title() for w in words if not w.isdigit()]
    return " ".join(filter(None, ["-".join(digits), *rest])) or "Unknown"

def player_view(p):
    if not p:
        return None
    first, _, last = p['name'].partition(" ")
    return {"id": p['id'], "name": p['name'], "first": first, "last": last or first, "position": p['position'], "jersey": p['jersey'],
            "overall": p['overall'], "class": p.get('classYear') or "",
            "portrait": media.portrait_url("player", media.player_portrait_file(p.get('assetName'), p.get('headAsset')))}

def matchup_view(m, notes):
    return {"id": m['id'], "label": m['label'], "fact": m['fact'], "grade": m['grade'], "edge": m['edge'], "ours": player_view(m['ours']), "theirs": player_view(m['theirs']),
            "note": notes.get(m['id']) or default_note(m)}

def default_note(m):
    o, t = m['ours'], m['theirs']
    if m['grade'] is None:
        return f"{o['name']} and #{t['jersey']} {t['name']} grade out even ({m['fact']}). The call decides this one."
    who = f"{o['name']} ({o['position']})" if m['edge'] > 0 else f"#{t['jersey']} {t['name']} ({t['position']})"
    return f"{who} has the edge here: {m['fact']}."

def injuries(roster):
    return [{"name": p['name'], "position": p['position'], "jersey": p['jersey'], "injury": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", p['injuryType'] or "Injury"),
             "status": INJURY_TEXT.get(p['injurySeverity'], p['injuryStatus'])}
            for p in roster['players'] if p['injuryStatus'] not in ("Uninjured", "")]

def season_line(player_id):
    totals = {}
    for row in league.query_player_games():
        if row['player_id'] == player_id:
            for key, value in row['stats'].items():
                totals[key] = totals.get(key, 0) + value
    return totals

def qb_card(qb):
    if not qb:
        return None
    s = season_line(qb['id'])
    att = s.get('PASSATTEMPTS', 0)
    speed = r(qb, 'SPD')
    style = "dual threat" if speed >= 80 else ("pocket passer" if speed < 70 else "can extend plays")
    return {**player_view(qb), "handed": qb.get('handed') or "Right", "style": style,
            "ratings": [{"label": label, "value": r(qb, key)} for key, label in QB_RATINGS],
            "stats": [{"label": label, "value": value} for label, value in (
                ("Comp", f"{s.get('PASSCOMPLETED', 0)}/{att}"), ("Pct", f"{round(100 * s.get('PASSCOMPLETED', 0) / att)}%" if att else "—"),
                ("Yards", s.get('PASSYARDS', 0)), ("TD", s.get('PASSTDS', 0)), ("INT", s.get('PASSINTS', 0)),
                ("Sacked", s.get('PASSSACKED', 0)), ("Rush Yds", s.get('RUSHYARDS', 0)))],
            "has_stats": bool(att)}

def scoring(team_id):
    """(points per game, points allowed per game, games) this season."""
    games = [g for g in league.query_team_games(team_id) if g['played']]
    if not games:
        return None, None, 0
    pf = sum(g['home_score'] if g['home_id'] == team_id else g['away_score'] for g in games)
    pa = sum(g['away_score'] if g['home_id'] == team_id else g['home_score'] for g in games)
    return round(pf / len(games), 1), round(pa / len(games), 1), len(games)

def side_view(row, roster):
    details = team.team_details(row)
    ratings = json.loads(row.get('ratings_json') or "{}")
    ppg, papg, games = scoring(row['team_id'])
    record = recap.records_through(league.query_games(), 99).get(row['team_id'], [0, 0])
    # FCS placeholder teams stand in for many schools, so their combined record means nothing
    record_text = "FCS" if recap.is_fcs_placeholder(row) else f"{record[0]}-{record[1]}"
    return {**details, "color": row['color'], "record": record, "record_text": record_text,
            "staff": team.staff(row), "off_scheme": scheme_label(row.get('off_scheme')), "def_scheme": scheme_label(row.get('def_scheme')),
            "ratings": ratings, "ppg": ppg, "papg": papg, "games": games, "off_rank": row.get('off_rank'), "def_rank": row.get('def_rank'),
            "injuries": injuries(roster)}

def personnel_advice(o_us, d_them, d_us, o_them):
    """One line each on personnel groupings, from where the unit-vs-unit edges are."""
    run_edge = avg(run_block(o_us['LT']), run_block(o_us['C']), run_block(o_us['RT']), ball_carrier(o_us['HB'])) - avg(*(run_stop(p) for p in (d_them['LE'], d_them['RE'], *d_them['DT']) if p), tackler(d_them['MLB']))
    pass_edge = avg(*(receiver(w) for w in o_us['WR'])) - avg(*(coverage(c) for c in d_them['CB']))
    if run_edge > pass_edge:
        offense = f"We win up front more than on the outside ({run_edge:+.0f} in the run game vs {pass_edge:+.0f} passing), so play big: 12 and 21 personnel put more blockers at the point of attack."
    else:
        offense = f"Our receivers are the better edge ({pass_edge:+.0f} vs {run_edge:+.0f} in the run game), so spread them out: 11 and 10 personnel make their corners cover in space."
    their_pass = avg(*(receiver(w) for w in o_them['WR'])) - avg(*(coverage(c) for c in d_us['CB']))
    their_run = avg(ball_carrier(o_them['HB']), run_block(o_them['C'])) - avg(*(run_stop(p) for p in (d_us['LE'], d_us['RE'], *d_us['DT']) if p))
    if their_pass > their_run:
        defense = "Their passing game tests us more than their run game does: start in nickel and go to dime on second and third and long."
    else:
        defense = "Their run game tests us more than their passing game does: stay in base and make them prove they can throw."
    return offense, defense

# ---------- The plan ----------

def query_stored(week):
    conn = database.get_db_connection()
    row = conn.execute("SELECT opponent_name, plan_json FROM game_plans WHERE week_num = ?", (week,)).fetchone()
    conn.close()
    return json.loads(row['plan_json']) if row else {}

def schedule_game(week):
    return next((g for g in database.query_full_schedule() if g['week_id'] == week), None)

def build_plan(week):
    game = schedule_game(week)
    us_row = league.query_user_team()
    them_row = league.query_team_by_name(game['opponent_name']) if game else None
    if not game or not us_row or not them_row:
        return None
    us_roster, them_roster = league.query_plan_roster(us_row['team_id']), league.query_plan_roster(them_row['team_id'])
    if not us_roster or not them_roster:
        return None
    o_us, d_us = offense(Lineup(us_roster)), defense(Lineup(us_roster))
    o_them, d_them = offense(Lineup(them_roster)), defense(Lineup(them_roster))
    attack, stop = group(offense_matchups(o_us, d_them)), group(defense_matchups(d_us, o_them))
    stored = query_stored(week) if (query_stored(week).get('opponent') == game['opponent_name']) else {}
    notes = stored.get('notes', {})

    us, them = side_view(us_row, us_roster), side_view(them_row, them_roster)
    home = {"Home": HOME_EDGE, "Away": -HOME_EDGE}.get(game.get('site'), 0)
    diff = (us['ratings'].get('OVR') or 0) - (them['ratings'].get('OVR') or 0) + home
    win = 1 / (1 + math.exp(-diff / 7))
    spread = round(diff * 0.9 * 2) / 2
    off_personnel, def_personnel = personnel_advice(o_us, d_them, d_us, o_them)
    view = lambda groups: {k: [matchup_view(m, notes) for m in v] for k, v in groups.items()}
    return {
        "week": week, "opponent": game['opponent_name'], "date": game.get('game_date'), "kickoff_minutes": game.get('kickoff_minutes'),
        "site": game.get('site'), "venue": us['stadium'] if game.get('site') == 'Home' else (them['stadium'] if game.get('site') == 'Away' else "Neutral site"),
        "us": us, "them": them, "fcs": recap.is_fcs_placeholder(them_row),
        "win_probability": round(100 * win), "line": f"{us['name'] if spread >= 0 else them['name']} -{abs(spread):g}" if spread else "Pick'em",
        "attack": view(attack), "stop": view(stop),
        "personnel": {"offense": stored.get('offense_personnel') or off_personnel, "defense": stored.get('defense_personnel') or def_personnel},
        "their_qb": qb_card(o_them['QB']), "our_qb": qb_card(o_us['QB']),
        "keys": stored.get('keys', []), "staff_notes": stored.get('staff_notes', []),
        "their_qb_notes": stored.get('their_qb_notes', []), "our_qb_notes": stored.get('our_qb_notes', []),
        "generated": bool(stored), "tape": tale_of_the_tape(us, them),
    }

def tale_of_the_tape(us, them):
    rows = [(unit, us['ratings'].get(unit), them['ratings'].get(unit)) for unit in ('OVR', 'OFF', 'DEF', 'QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB', 'ST')]
    rows += [("Points / game", us['ppg'], them['ppg']), ("Allowed / game", us['papg'], them['papg'])]
    return [{"label": label, "us": a, "them": b,
             "better": None if a is None or b is None or a == b else ("us" if (a > b) != (label == "Allowed / game") else "them")} for label, a, b in rows]

def plan_weeks():
    return [{"week": g['week_id'], "opponent": g['opponent_name'], "played": bool(g['is_played'])} for g in database.query_full_schedule()]

# ---------- AI writing ----------

def matchup_fact(m):
    """One matchup (as shown on the page) in plain words for the prompt."""
    o, t = m['ours'], m['theirs']
    side = "even" if not m['grade'] else f"{m['grade']} edge to {'us' if m['edge'] > 0 else 'them'}"
    return f'"{m["id"]}": {m["label"]}, our {o["position"]} {o["name"]} vs their {t["position"]} #{t["jersey"]} {t["name"]}, judged on {m["fact"]}: {side}.'

def generate_plan(selected_model, week):
    """Writes the coaching notes, keys and scouting bullets for one week's plan and stores them."""
    import ai_engine
    plan = build_plan(week)
    if not plan:
        raise ValueError("No opponent data for that week yet.")
    us, them = plan['us'], plan['them']
    rules = ("You are the offensive and defensive coordinators of a college football team writing the weekly game plan. "
             "Write like a coach: short, direct, specific. Every player is a man; use he/him. Use only the players and facts given. "
             "Never invent stats, scores or injuries. Refer to opponents by jersey number and last name.")
    def notes_for(groups, side):
        items = [m for key in ("win", "lose", "call") for m in groups[key]]
        if not items:
            return {}
        facts = " ".join(matchup_fact(m) for m in items)
        prompt = (f"{rules} {side} matchups against the {them['full_name']} ({them['off_scheme']} offense, {them['def_scheme']} defense). {facts} "
                  "For each matchup id write ONE sentence of coaching advice about that exact matchup (what each player does in it is stated after 'judged on'): "
                  "how we exploit it when we have the edge, how we protect against it when they do, and which call or adjustment wins it when it's even. "
                  "Linemen block, backs carry the ball, receivers run routes, defenders rush, tackle and cover. "
                  'Respond with ONLY a JSON object: {"notes": {"<id>": "sentence", ...}}')
        for _attempt in range(2):  # the model occasionally returns broken JSON; one retry usually fixes it
            try:
                data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
                notes = {k: ai_engine.strip_tags(v) for k, v in (data.get('notes') or {}).items() if isinstance(v, str)}
                if notes:
                    return notes
            except Exception:
                continue
        return {}

    notes = {**notes_for(plan['attack'], "Our offense vs their defense:"), **notes_for(plan['stop'], "Our defense vs their offense:")}
    top = lambda key, part: ", ".join(f"{m['label']} ({m['ours']['name']} vs #{m['theirs']['jersey']} {m['theirs']['name']})" for m in plan[key][part][:3]) or "none"
    tq, oq = plan['their_qb'], plan['our_qb']
    qb_fact = lambda q: (f"{q['name']}, {q['class']} {q['handed'].lower()}-handed {q['style']}; ratings "
                         + ", ".join(f"{x['label']} {x['value']}" for x in q['ratings'])
                         + ("; season: " + ", ".join(f"{x['label']} {x['value']}" for x in q['stats']) if q['has_stats'] else "; no passes thrown this season")) if q else "unknown"
    prompt = (f"{rules} Week {week}: {us['full_name']} ({us['record_text']}) vs {them['full_name']} ({them['record_text']}). "
              f"Their head coach {next((s['name'] for s in them['staff'] if s['short_role'] == 'HC'), 'unknown')} runs a {them['off_scheme']} offense and a {them['def_scheme']} defense. "
              f"Our biggest offensive edges: {top('attack', 'win')}. Where their defense can hurt us: {top('attack', 'lose')}. "
              f"Our biggest defensive edges: {top('stop', 'win')}. Where their offense can hurt us: {top('stop', 'lose')}. "
              f"Their quarterback: {qb_fact(tq)}. Our quarterback: {qb_fact(oq)}. "
              "Fill in this JSON object and respond with ONLY the JSON. Every list item is one complete sentence of coaching advice: "
              "staff_notes are only about THEIR coaching tendencies that come with their scheme (e.g. what an Air Raid offense or a 3-3-5 defense likes to do) and never mention our players. "
              "Quarterback notes describe how he plays and what to do about it; never repeat the rating numbers. "
              '{"staff_notes": ["what to expect from their offensive scheme", "another", "what to expect from their defensive scheme", "another"], '
              '"their_qb_notes": ["how their quarterback plays", "how we defend him", "another", "another"], '
              '"our_qb_notes": ["where our quarterback can hurt them", "another", "another"]}')
    extras = {}
    try:
        extras = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
    except Exception:
        pass
    # Placeholder-looking items ("key 2", "another") mean the model echoed the template
    as_list = lambda v: [ai_engine.strip_tags(x) for x in v if isinstance(x, str) and len(x) > 25] if isinstance(v, list) else []
    keys_prompt = (prompt.split("Fill in this JSON object")[0]
                   + "Write the 4 keys to the game for us: four numbered lines, one complete sentence each, naming players where it helps. No other text.")
    try:
        raw_keys = ai_engine.call_ollama(selected_model, keys_prompt)
        keys = [re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", line).strip() for line in raw_keys.splitlines()]
        keys = [k for k in keys if len(k) > 25][:4]
    except Exception:
        keys = []
    stored = {"opponent": plan['opponent'], "notes": notes, "keys": keys, "staff_notes": as_list(extras.get('staff_notes')),
              "their_qb_notes": as_list(extras.get('their_qb_notes')), "our_qb_notes": as_list(extras.get('our_qb_notes')),
              "offense_personnel": None, "defense_personnel": None}  # personnel stays computed from the ratings
    if not notes and not stored['keys']:
        raise RuntimeError("The model didn't return a usable game plan. Try again.")
    conn = database.get_db_connection()
    conn.execute("INSERT OR REPLACE INTO game_plans (week_num, opponent_name, plan_json) VALUES (?, ?, ?)", (week, plan['opponent'], json.dumps(stored)))
    conn.commit()
    conn.close()
    return build_plan(week)

# Auto-initialize when gameplan.py gets imported
initialize_gameplan_tables()
