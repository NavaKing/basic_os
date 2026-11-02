import re
import league
import media

# Who "our team" is: read from the save (the team the dynasty's user coaches), so nothing in the app
# assumes Wyoming. Display names, colours and stadium all come from here.

# Plain colour names for the image prompts ("brown and gold"); each team colour maps to the nearest one
COLOR_NAMES = {
    "black": (20, 20, 20), "white": (245, 245, 245), "gray": (128, 128, 128), "silver": (192, 192, 192),
    "red": (200, 30, 40), "crimson": (150, 20, 40), "maroon": (110, 25, 35), "orange": (240, 120, 20),
    "burnt orange": (190, 85, 0), "gold": (255, 195, 40), "old gold": (180, 150, 80), "yellow": (250, 225, 30),
    "brown": (80, 55, 40), "green": (20, 120, 50), "dark green": (15, 70, 40), "kelly green": (30, 160, 60),
    "teal": (0, 125, 130), "navy blue": (15, 30, 80), "royal blue": (30, 70, 180), "light blue": (110, 170, 225),
    "purple": (80, 40, 130), "cardinal": (160, 25, 45),
}

def color_name(hex_color):
    if not hex_color:
        return None
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return min(COLOR_NAMES, key=lambda name: sum((a - b) ** 2 for a, b in zip(rgb, COLOR_NAMES[name])))

STAFF_ROLES = (("hc", "Head Coach"), ("oc", "Offensive Coordinator"), ("dc", "Defensive Coordinator"))

def staff(row):
    """Head coach and coordinators: [{role, short_role, name, portrait url}]."""
    members = (row or {}).get('staff') or {}
    return [{"role": label, "short_role": key.upper(), "name": members[key]['name'],
             "portrait": media.portrait_url("coach", members[key]['portrait'])}
            for key, label in STAFF_ROLES if members.get(key)]

def team_details(row):
    """Display details for any league team row."""
    colors = [c for c in (color_name(row.get('color')), color_name(row.get('color2'))) if c]
    return {
        "id": row['team_id'],
        "name": row['name'],
        "nickname": row.get('nickname') or "",
        "full_name": f"{row['name']} {row.get('nickname') or ''}".strip(),
        "short": row.get('short_name'),
        "logo": media.logo_url(row.get('short_name')),
        "colors": " and ".join(dict.fromkeys(colors)) or "team",
        "stadium": media.stadium_text(row.get('short_name')),
    }

# Program identity used by the AI writing and the feed title. Teams not listed get a generic version.
TEAM_FLAVOR = {
    "WYO": {"identity": "our high-velocity 7220 Speed tempo altitude engine", "hashtag": "#7220SPEED"},
}

def flavor(details):
    custom = TEAM_FLAVOR.get(details.get('short') or "", {})
    nickname = re.sub(r"[^A-Za-z]", "", details.get('nickname') or details.get('name') or "Team")
    return {"identity": custom.get('identity', "our game plan"), "hashtag": custom.get('hashtag', f"#Go{nickname}")}

FALLBACK = {"id": None, "name": "Our Team", "nickname": "", "full_name": "Our Team", "short": None, "logo": None, "colors": "team", "stadium": None}

def user_team():
    """Our team's details, or neutral placeholders before the first save sync."""
    row = league.query_user_team()
    details = team_details(row) if row else dict(FALLBACK)
    return {**details, **flavor(details)}

def opponent(name):
    """Details for a team by its schedule name ("Colorado State Rams") or school name, or None."""
    row = league.query_team_by_name(name)
    return team_details(row) if row else None
