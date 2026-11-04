"""School lore for the writers: the real program history in school_lore.json plus the dynasty's own seasons from the
save, so the group chat and the dispatch know what a title game or a ranking means for this school instead of guessing."""
import json
import os
import league

LORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "school_lore.json")

def school():
    """This team's block from school_lore.json ({} if it has none)."""
    us = league.query_user_team() or {}
    try:
        with open(LORE_FILE, encoding="utf-8") as f:
            return json.load(f).get(us.get('short_name') or "", {})
    except (OSError, ValueError):
        return {}

def conference_name():
    us = league.query_user_team() or {}
    return school().get('conference_name') or us.get('conference') or "the conference"

def dynasty_seasons():
    """One line per finished dynasty season ("2026: 12-1, 1st in the MW, finished No. 9, won the Sun Bowl")."""
    import save_sync
    current = (json.loads(save_sync.get_state('phase') or "{}")).get('seasonYear')
    lines = []
    for r in league.query_rows("SELECT * FROM program_seasons WHERE year < ? ORDER BY year", (current or 9999,)):
        bowls = [b.replace("_", " ") for b in json.loads(r['bowls_json'] or "[]")]
        rank = f", finished No. {r['final_rank']}" if r['final_rank'] and r['final_rank'] <= 25 else ""
        place = {1: "1st", 2: "2nd", 3: "3rd"}.get(r['conf_standing'], f"{r['conf_standing']}th")
        lines.append(f"{r['year']}: {r['wins']}-{r['losses']}, {place} in the {r['conference']}{rank}" + (f", {', '.join(bowls)}" if bowls else ""))
    return lines

def context():
    """A fact block for prompts ("" when there's nothing): the school's history, then this dynasty's seasons."""
    facts = list(school().get('facts') or [])
    seasons = dynasty_seasons()
    if seasons:
        facts.append("Earlier seasons of this dynasty: " + "; ".join(seasons) + ".")
    if not facts:
        return ""
    return " School history (real facts; use them when they matter, never invent other history): " + " ".join(facts)
