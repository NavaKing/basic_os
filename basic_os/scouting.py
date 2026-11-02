import database
import league
import recap
import team
import team_page

# Opponent scouting card for Game Day: the facts come from the save, and a short preview is written
# by the AI during hub generation (stored per week so it stays put between page loads).

KEY_PLAYERS = 3

def initialize_scouting_table():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS scouting_reports (
        week_num INTEGER PRIMARY KEY,
        opponent_name TEXT NOT NULL,
        preview_text TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def last_result(team_id, teams):
    """'L 42-44 @ Air Force (Week 1)' for the team's most recent finished game, or None."""
    played = [g for g in league.query_team_games(team_id) if g['played']]
    if not played:
        return None
    game = played[-1]
    outcome, mine, theirs, venue, opponent_id = recap.side_result(game, team_id)
    opponent = teams.get(opponent_id)
    return f"{outcome} {mine}-{theirs} {venue} {opponent['name'] if opponent else 'TBD'} (Week {game['week']})"

def build_scouting(game):
    """Scouting card data for a schedule game, or None if we can't find the opponent in the league data."""
    if not game:
        return None
    row = league.query_team_by_name(game['opponent_name'])
    if not row:
        return None
    page = team_page.build_team_page(row['team_id'])
    head_coach = next((member for member in page['staff'] if member['short_role'] == 'HC'), None)
    # The game folds every FCS school into a few placeholder teams, so their record and last game aren't really one team's
    fcs = recap.is_fcs_placeholder(row)
    return {
        "fcs": fcs,
        "id": page['id'], "name": page['name'], "full_name": page['full_name'], "logo": page['logo'], "color": page['color'],
        "record": "FCS opponent" if fcs else page['record'], "rank": page['rank'], "head_coach": head_coach,
        "last_result": None if fcs else last_result(row['team_id'], league.query_teams()),
        "players": page['players'][:KEY_PLAYERS],
        "preview": query_preview(game['week_id'], game['opponent_name']),
    }

def scouting_context(card):
    """Plain-English facts about the opponent for the AI prompts."""
    if not card:
        return ""
    if card['fcs']:
        parts = [f"{card['full_name']} are an FCS opponent, a heavy underdog against an FBS team; do not mention a record."]
    else:
        parts = [f"{card['full_name']} are {card['record']}" + (f" and ranked #{card['rank']} in the AP poll" if card['rank'] else ", unranked") + "."]
    if card['head_coach']:
        parts.append(f"Their head coach is {card['head_coach']['name']}.")
    if card['last_result']:
        parts.append(f"Their last game: {card['last_result']}.")
    if card['players']:
        parts.append("Their top players this season: " + "; ".join(f"{p['position']} {p['name']} ({p['line']})" for p in card['players'] if p['line']) + ".")
    return " ".join(parts)

def generate_preview(selected_model, game):
    """Writes and stores a short scouting preview for this week's opponent. Returns the text, or None on failure."""
    import ai_engine
    card = build_scouting(game)
    if not card:
        return None
    us = team.user_team()
    focus = (f"Sentence 2: the opposing player {us['name']} must stop, by name and position." if card['players']
             else f"Sentence 2: the edge {us['name']} should press, without naming any opposing players (none are known).")
    prompt = (f"You are a beat writer covering {us['name']} Football. Write a 3-sentence scouting report on this week's opponent, "
              f"the {card['full_name']}, ahead of the Week {game['week_id']} game. Facts (use only these, never invent stats, scores or players): "
              f"{scouting_context(card)} Sentence 1: who they are and how their season is going. {focus} "
              f"Sentence 3: what {us['name']} needs to do to win. Write it as one plain paragraph: no numbers, labels or lists. Every player is a man; use he/him. Do not output raw code strings or brackets.")
    try:
        text = ai_engine.call_ollama(selected_model, prompt)
    except Exception:
        return None
    conn = database.get_db_connection()
    conn.execute("INSERT OR REPLACE INTO scouting_reports (week_num, opponent_name, preview_text) VALUES (?, ?, ?)",
                 (game['week_id'], game['opponent_name'], text))
    conn.commit()
    conn.close()
    return text

def query_preview(week_num, opponent_name):
    conn = database.get_db_connection()
    row = conn.execute("SELECT preview_text FROM scouting_reports WHERE week_num = ? AND opponent_name = ?", (week_num, opponent_name)).fetchone()
    conn.close()
    return row['preview_text'] if row else None

# Auto-initialize when scouting.py gets imported
initialize_scouting_table()
