import json
import os
import re
import sys
import urllib.request

# Team logos and player/coach portraits.
# Portraits come from the SMG CFB27 mod folders and are served straight from there (27k files, no copying).
# Logos and home stadiums are downloaded once from ESPN's public team list into static/logos/<SHORT>.png and
# static/logos/teams.json (run: python media.py).

SMG_DIR = os.environ.get("CFB_PORTRAIT_DIR", r"C:\Program Files (x86)\Steam\steamapps\common\SMG CFB27")
PORTRAIT_DIRS = {
    "player": os.path.join(SMG_DIR, "Player Portraits"),
    "coach": os.path.join(SMG_DIR, "coachportraits"),
}
LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logos")
ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams?limit=2000"
ESPN_TEAM_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/teams/{}"
TEAM_INFO_FILE = os.path.join(LOGO_DIR, "teams.json")

_index = {}

def portrait_index(kind):
    """(set of file names, {trailing id: file name}) for one portrait folder, built once per process."""
    if kind not in _index:
        folder = PORTRAIT_DIRS[kind]
        names = set(os.listdir(folder)) if os.path.isdir(folder) else set()
        by_id = {}
        for name in names:
            match = re.search(r"_(\d+)\.webp$", name)
            if match and "_Unique_" in name:
                by_id[int(match.group(1))] = name
        _index[kind] = (names, by_id)
    return _index[kind]

def player_portrait_file(asset_name, head_asset):
    """Portrait file for a player: their own scan, else their generic head, else None."""
    names, by_id = portrait_index("player")
    for candidate in (f"nilpp_Unique_{asset_name}.webp", f"nilpp_{head_asset}.webp"):
        if candidate in names:
            return candidate
    # Long names are truncated differently in the save and the file name; the trailing id still matches
    match = re.search(r"_(\d+)$", asset_name or "")
    return by_id.get(int(match.group(1))) if match else None

def coach_portrait_file(portrait_id, asset_name=None):
    names, by_id = portrait_index("coach")
    if asset_name and f"nilcp_{asset_name}.webp" in names:
        return f"nilcp_{asset_name}.webp"
    if portrait_id in by_id:
        return by_id[portrait_id]
    # Generic coach heads are named nilcp_Generic_<id>_C_...; any variant of that head will do
    prefix = f"nilcp_Generic_{portrait_id:04d}_" if isinstance(portrait_id, int) else None
    return next((n for n in sorted(names) if prefix and n.startswith(prefix)), None)

def portrait_url(kind, file_name):
    return f"/portraits/{kind}/{file_name}" if file_name else None

def logo_url(short_name):
    file_name = f"{short_name}.png"
    return f"/static/logos/{file_name}" if short_name and os.path.exists(os.path.join(LOGO_DIR, file_name)) else None

# ---------- One-time logo download ----------

ALIASES = {"FIU": "Florida International", "NIU": "Northern Illinois", "NDSU": "North Dakota State", "USF": "South Florida",
           "MTSU": "Middle Tennessee", "C. Carolina": "Coastal Carolina", "Jax State": "Jacksonville State",
           "Sac State": "Sacramento State", "App St.": "App State", "Ga Southern": "Georgia Southern", "FLA Atlantic": "Florida Atlantic"}
PREFIXES = {"E. ": "Eastern ", "W. ": "Western ", "C. ": "Central ", "N. ": "Northern ", "S. ": "Southern "}

def normalize(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower().replace("&", "and").replace("é", "e"))

def espn_school_name(name):
    school = ALIASES.get(name, name)
    for short, full in PREFIXES.items():
        if school.startswith(short):
            school = full + school[len(short):]
    return re.sub(r" St\.?$", " State", school)

LOGO_SIZE = 320   # ESPN's logos are 500 px; the largest the app shows is the 150 px header logo, so 320 stays sharp at 2x

def shrink_logo(path):
    """Scales a logo down to LOGO_SIZE (keeping transparency). Returns True if it was larger. Needs Pillow."""
    try:
        from PIL import Image
    except ImportError:
        return False
    with Image.open(path) as img:
        if max(img.size) <= LOGO_SIZE:
            return False
        img.thumbnail((LOGO_SIZE, LOGO_SIZE))
        img.save(path, "PNG", optimize=True)
    return True

def download_logos(teams):
    """teams: [(short_name, school name, nickname)]. Downloads any missing logo and home stadium; returns the schools with no match."""
    os.makedirs(LOGO_DIR, exist_ok=True)
    with urllib.request.urlopen(ESPN_TEAMS_URL, timeout=60) as response:
        espn = [entry['team'] for entry in json.load(response)['sports'][0]['leagues'][0]['teams']]
    by_name = {normalize(t['displayName']): t for t in espn}
    info = load_team_info()
    unmatched = []
    for short, name, nickname in teams:
        target = os.path.join(LOGO_DIR, f"{short}.png")
        if os.path.exists(target) and short in info:
            continue
        team = by_name.get(normalize(espn_school_name(name)) + normalize(nickname)) or by_name.get(normalize(name) + normalize(nickname))
        if not team:
            unmatched.append(name)
            continue
        if not os.path.exists(target):
            # The app has a dark theme, so prefer ESPN's dark-background variant
            variants = team.get('logos', [])
            logos = [l['href'] for l in variants if 'dark' in l.get('rel', [])] or [l['href'] for l in variants if 'default' in l.get('rel', [])]
            if logos:
                urllib.request.urlretrieve(logos[0], target)
                shrink_logo(target)
        info[short] = {"espn_id": team['id'], **fetch_venue(team['id'])}
    with open(TEAM_INFO_FILE, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=1, sort_keys=True)
    _team_info.clear()
    return unmatched

def fetch_venue(espn_id):
    """{'stadium': 'War Memorial Stadium', 'city': 'Laramie', 'state': 'WY'} from ESPN's team record."""
    try:
        with urllib.request.urlopen(ESPN_TEAM_URL.format(espn_id), timeout=30) as response:
            venue = json.load(response).get('venue') or {}
    except OSError:
        return {}
    address = venue.get('address') or {}
    return {"stadium": venue.get('fullName'), "city": address.get('city'), "state": address.get('state')}

# ---------- Team details (home stadium) ----------

_team_info = {}

def load_team_info():
    if not _team_info and os.path.exists(TEAM_INFO_FILE):
        with open(TEAM_INFO_FILE, encoding="utf-8") as f:
            _team_info.update(json.load(f))
    return _team_info

def stadium_text(short_name):
    """'War Memorial Stadium in Laramie, WY', or None when we don't know the venue."""
    venue = load_team_info().get(short_name) or {}
    if not venue.get('stadium'):
        return None
    place = ", ".join(part for part in (venue.get('city'), venue.get('state')) if part)
    return f"{venue['stadium']} in {place}" if place else venue['stadium']

if __name__ == "__main__":
    import league
    teams = [(t['short_name'], t['name'], t['nickname']) for t in league.query_teams().values() if t['short_name']]
    missing = download_logos(teams)
    print(f"Logos and stadiums ready in {LOGO_DIR}. No match for: {', '.join(missing) or 'none'}")
    sys.exit(0)
