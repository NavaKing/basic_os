"""School lore for the writers: real program history from school_lore.json plus what this dynasty has done (finished
seasons and conference title games, from the save), so the group chat and the dispatch know what a title game or a
ranking means for this school instead of guessing.

When a sync shows the coach at a school with no lore yet (a new dynasty, or he took another job), its history is fetched
from Wikipedia in the background and saved to school_lore.json, marked for review."""
import datetime
import json
import os
import re
import threading
import league

LORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "school_lore.json")
WIKIPEDIA = "https://en.wikipedia.org"
HEADERS = {"User-Agent": "BASIC_OS dynasty companion (a local app; one request per new school)"}
_fetching = {"running": False}

def read_file():
    try:
        with open(LORE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def school():
    """This team's block from school_lore.json ({} if it has none)."""
    us = league.query_user_team() or {}
    return read_file().get(us.get('short_name') or "", {})

def conference_name():
    us = league.query_user_team() or {}
    return school().get('conference_name') or us.get('conference') or "the conference"

def current_season():
    import save_sync
    return json.loads(save_sync.get_state('phase') or "{}").get('seasonYear')

def dynasty_seasons():
    """One line per finished dynasty season ("2026: 12-1, 1st in the MW, finished No. 9, won the Sun Bowl")."""
    lines = []
    import career
    for r in league.query_rows("SELECT * FROM program_seasons WHERE year < ? ORDER BY year", (current_season() or 9999,)):
        if not career.coached_season(r['year']):   # this school's seasons under other coaches are school history, not the dynasty's
            continue
        bowls = [b.replace("_", " ") for b in json.loads(r['bowls_json'] or "[]")]
        rank = f", finished No. {r['final_rank']}" if r['final_rank'] and r['final_rank'] <= 25 else ""
        place = {1: "1st", 2: "2nd", 3: "3rd"}.get(r['conf_standing'], f"{r['conf_standing']}th")
        lines.append(f"{r['year']}: {r['wins']}-{r['losses']}, {place} in the {r['conference']}{rank}" + (f", {', '.join(bowls)}" if bowls else ""))
    return lines

def dynasty_title_games():
    """This dynasty's conference title games, oldest first ("2026 Mountain West Championship Game: won 31-24 over UNLV"),
    from what player care recorded (title_game_<season> holds the game's week)."""
    import career
    out = []
    rows = league.query_rows("SELECT state_key, state_value FROM care_state WHERE state_key LIKE 'title_game_%' ORDER BY state_key")
    for r in rows:
        year = r['state_key'].rsplit("_", 1)[-1]
        if not year.isdigit() or not career.coached_season(year):   # a title game he coached at a previous school
            continue
        game = next(iter(league.query_rows("SELECT * FROM history_games WHERE season_year = ? AND week = ?", (int(year), int(r['state_value'])))), None)
        name = f"{year} {conference_name()} Championship Game"
        if game and game['our_score'] is not None:
            result = "won" if game['our_score'] > game['their_score'] else "lost"
            out.append(f"{name}: {result} {max(game['our_score'], game['their_score'])}-{min(game['our_score'], game['their_score'])} "
                       f"{'over' if result == 'won' else 'to'} {game['opponent_name']}")
        else:
            out.append(f"{name}: being played this season")
    return out

def dynasty_postseason():
    """This season's finished bowl and playoff games ("2026 CFP First Round: won 23-21 over LSU Tigers")."""
    import career
    us = league.query_user_team() or {}
    if current_season() and not career.coached_season(current_season()):
        return []   # he arrived after this school's bowl season: those games were someone else's
    teams = {t['team_id']: t for t in league.query_rows("SELECT team_id, name, nickname FROM league_teams")}
    out = []
    for b in league.query_rows("SELECT * FROM league_bowls WHERE (home_id = ? OR away_id = ?) AND played = 1 ORDER BY week",
                               (us.get('team_id'), us.get('team_id'))):
        home = b['home_id'] == us.get('team_id')
        ours, theirs = (b['home_score'], b['away_score']) if home else (b['away_score'], b['home_score'])
        other = teams.get(b['away_id'] if home else b['home_id']) or {}
        name = f"{other.get('name', 'their opponent')} {other.get('nickname') or ''}".strip()
        year = (b['game_date'] or "")[:4] or str(current_season() or "")
        result = f"won {ours}-{theirs} over" if ours > theirs else f"lost {theirs}-{ours} to"
        out.append(f"{year} {b['name']}: {result} {name}")
    return out

def context():
    """A fact block for prompts ("" when there's nothing): the school's history, then this dynasty's own story."""
    facts = list(school().get('facts') or [])
    titles = dynasty_title_games() + dynasty_postseason()
    if titles:
        facts.append("In this dynasty (newer than anything above, so it's the most recent): " + "; ".join(titles) + ".")
    seasons = dynasty_seasons()
    if seasons:
        facts.append("Earlier seasons of this dynasty: " + "; ".join(seasons) + ".")
    if not facts:
        return ""
    return " School history (real facts; use them when they matter, never invent other history): " + " ".join(facts)

# ---------- A new school: fetch its history ----------

def clean(wikitext):
    """Wikipedia markup to plain text: links to their labels, line breaks to semicolons, templates and refs dropped."""
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", wikitext or "", flags=re.S)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<hr\s*/?>|<br\s*/?>", "; ", text)
    text = re.sub(r"<[^>]+>|'''?", "", text)
    return re.sub(r"\s+", " ", text).strip(" ;")

def infobox(wikitext):
    """{Field: plain value} from the page's college football infobox."""
    found = re.search(r"\{\{\s*Infobox (?:college football team|NCAA football school)", wikitext)   # pages use either box
    if not found:
        return {}
    start = found.start()
    fields = {}
    for key, value in re.findall(r"^\|\s*(\w+)\s*=\s*(.*)$", wikitext[start:start + 12000], re.M):
        fields.setdefault(key, clean(value))
    return fields

def facts_from(summary, box, name):
    """Plain facts for the prompts from the page summary and infobox (the real head coach is left out: the dynasty has its own)."""
    facts = [s for s in re.split(r"(?<=\.)\s+", summary or "") if s and "coach" not in s.lower()][:2]
    if box.get('ConfTitles'):
        years = re.findall(r"\b(?:18|19|20)\d{2}\b", box['ConfTitles'])
        facts.append(f"{name} conference titles ({len(years)}): {box['ConfTitles']}." if years else f"{name} conference titles: {box['ConfTitles']}.")
    if box.get('DivTitles'):
        facts.append(f"Division titles: {box['DivTitles']}.")
    if box.get('NationalTitles'):
        facts.append(f"National titles: {box['NationalTitles']}.")
    # A record only when both numbers are plain digits (some pages fill them with templates; a wrong record is worse than none)
    number = lambda key: (box.get(key) or "").replace(",", "").isdigit()
    if number('ATWins') and number('ATLosses'):
        facts.append(f"All-time record: {box['ATWins']}-{box['ATLosses']}" + (f"-{box['ATTies']}" if number('ATTies') else "") + ".")
    if number('BowlWins') and number('BowlLosses'):
        facts.append(f"Bowl record: {box['BowlWins']}-{box['BowlLosses']}.")
    if box.get('Stadium'):
        facts.append(f"Home stadium: {box['Stadium']}" + (f" in {box['Location']}" if box.get('Location') else "") +
                     (f" (capacity {box['StadCapacity']})" if box.get('StadCapacity') else "") + ".")
    if box.get('Rivalries'):
        rivals = re.sub(r"\s*\(rivalry\)", "", box['Rivalries'])
        facts.append(f"Rivals: {rivals}.")
    if box.get('FightSong'):
        facts.append(f"Fight song: {box['FightSong']}" + (f"; mascot: {box['MascotDisplay']}" if box.get('MascotDisplay') else "") + ".")
    return facts

def fetch_school(team, session=None):
    """{conference_name, facts, auto, source, fetched} for a team, from its Wikipedia page ("<School> <Nickname> football")."""
    import requests
    http = session or requests
    title = f"{team['name']} {team.get('nickname') or ''} football".replace("  ", " ")
    page = http.get(f"{WIKIPEDIA}/w/api.php", params={"action": "parse", "page": title, "prop": "wikitext", "section": 0,
                                                      "format": "json", "redirects": 1}, headers=HEADERS, timeout=15).json()
    if 'parse' not in page:   # no page by that name: take the top search hit
        found = http.get(f"{WIKIPEDIA}/w/api.php", params={"action": "query", "list": "search", "srsearch": title, "srlimit": 1,
                                                           "format": "json"}, headers=HEADERS, timeout=15).json()
        hits = found.get('query', {}).get('search', [])
        if not hits:
            raise RuntimeError(f"No Wikipedia page found for {title}.")
        title = hits[0]['title']
        page = http.get(f"{WIKIPEDIA}/w/api.php", params={"action": "parse", "page": title, "prop": "wikitext", "section": 0,
                                                          "format": "json", "redirects": 1}, headers=HEADERS, timeout=15).json()
    title = page['parse']['title']
    summary = http.get(f"{WIKIPEDIA}/api/rest_v1/page/summary/{title.replace(' ', '_')}", headers=HEADERS, timeout=15).json().get('extract', "")
    box = infobox(page['parse']['wikitext']['*'])
    return {"conference_name": box.get('Conference') or team.get('conference') or "", "facts": facts_from(summary, box, team['name']),
            "auto": True, "reviewed": False, "source": f"{WIKIPEDIA}/wiki/{title.replace(' ', '_')}",
            "fetched": datetime.date.today().isoformat()}

def check_school():
    """Called after each sync: if the coach is at a school with no lore (a new dynasty, or he moved on), fetch it in the
    background. Staying put changes nothing. Returns True if a fetch started."""
    us = league.query_user_team()
    if not us or not us.get('short_name') or _fetching['running'] or us['short_name'] in read_file():
        return False
    _fetching['running'] = True
    threading.Thread(target=_fetch_and_save, args=(dict(us),), daemon=True).start()
    return True

def _fetch_and_save(team):
    try:
        block = fetch_school(team)
        data = read_file() or {"_about": "Real program history for the app's writers. Edit freely."}
        data[team['short_name']] = block
        with open(LORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        print(f"BASIC_OS: couldn't fetch school history for {team.get('name')}: {e}")
    finally:
        _fetching['running'] = False
