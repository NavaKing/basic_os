import os
import requests
import json
import re
import time
import database
import image_engine
import team
import progress

TWEET_COUNT = 8
PHOTO_TWEETS = 3  # how many tweets get a generated photo
HERO_SIZE = (1536, 640)  # wide banner for the story column
PHOTO_STYLE = "Candid smartphone photo posted to social media by a college football fan: {photo} {team} football, {colors} team colors. Photorealistic, natural lighting."

OLLAMA_URL = 'http://localhost:11434/api/generate'
OLLAMA_TIMEOUT = 120  # 12B models can take a while to cold-load

def call_ollama(selected_model, prompt, force_json=False, temperature=None):
    payload = {"model": selected_model, "prompt": prompt, "stream": False}
    if temperature is not None:
        payload["options"] = {"temperature": temperature}
    if force_json:
        payload["format"] = "json"
    res = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    body = res.json()
    if not res.ok or 'error' in body:
        raise RuntimeError(body.get('error', f"HTTP {res.status_code}"))
    text = body.get('response', '').strip()
    if not force_json:
        text = clean_text(text)
    if not text:
        raise RuntimeError("Model returned an empty response.")
    return text

# ---------- Output cleanup ----------

STAGE_DIRECTIONS = re.compile(r"\[(?:image|photo|picture|img|gif|video)[^\]]*\]", re.IGNORECASE)

def strip_tags(text):
    """Removes stray "[image: ...]" style placeholders the sports model likes to add."""
    text = STAGE_DIRECTIONS.sub("", text or "")
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,!?;:])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]+\n", "\n", text).strip()

def proper_names():
    """Names to restore capitals on: our roster's players (first and last names) and every team's school and nickname."""
    import roster, league
    names = set()
    for p in roster.query_full_roster():
        names.update(part for part in (p['player_name'] or "").split() if len(part) > 1)
    # Whole school names and nicknames only: single words like "Air" (Force) or "Green" (Wave) are everyday words
    for t in league.query_teams().values():
        names.update(phrase for phrase in (t['name'], t['nickname']) if phrase and phrase[0].isupper())
    # Opponents' players by full name only (their single first or last names could be everyday words)
    names.update(p['name'] for p in league.query_players().values() if " " in (p['name'] or ""))
    for team_id in league.query_teams():
        roster_data = league.query_plan_roster(team_id)
        names.update(p['name'] for p in (roster_data or {}).get('players', []) if " " in (p['name'] or ""))
    return names

def fix_casing(text):
    """cfb-gemma often writes names, and sometimes whole stories, in lowercase. Known names (our players, every team)
    are always restored; sentence capitals and "I" only when the text is almost entirely lowercase."""
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) <= 0.02:
        text = re.sub(r"(^|[.!?]\s+|\n\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
        text = re.sub(r"(?<![\w'’])i(?![\w'’])", "I", text)  # not the i in "hawai'i"
    for name in sorted(proper_names(), key=len, reverse=True):
        text = re.sub(r"(?<![\w'’])" + re.escape(name.lower()) + r"(?![\w'’])", name, text)
    # An older version capitalized the i after an apostrophe ("hawai'I"); undo that
    text = re.sub(r"(?<=[a-z]['’])I\b", "i", text)
    return text

def clean_text(text):
    return fix_casing(strip_tags(text))

def unload_ollama_model(selected_model):
    """Frees the text model's GPU memory (FLUX needs most of it). Ollama reloads it on the next call."""
    try:
        requests.post(OLLAMA_URL, json={"model": selected_model, "keep_alive": 0}, timeout=30)
    except requests.RequestException:
        pass

def game_venue(game, us=None):
    """Where a schedule game is played: our stadium, the opponent's, or a neutral site."""
    if game.get('site') == 'Neutral':
        return "a neutral-site stadium"
    if game.get('site') == 'Home':
        return (us or team.user_team())['stadium'] or "our home stadium"
    opponent = team.opponent(game.get('opponent_name'))
    return (opponent and opponent['stadium']) or f"the {game['opponent_name']} home stadium"

def hero_prompt(game):
    """Banner scene for the week's story, built from the game itself (venue and forecast weather)."""
    us = team.user_team()
    venue = game_venue(game, us)
    weather = {
        "Rain": "in steady rain, wet turf shining under the stadium lights",
        "Snow": "in falling snow, the field dusted white",
        "Overcast": "under a heavy overcast sky",
        "Clear": "under a clear blue sky in golden afternoon light",
    }.get(game.get('weather') or "", "in dramatic afternoon light")
    return (f"Wide cinematic sports photograph: the {us['full_name']} college football team in {us['colors']} uniforms "
            f"taking the field at {venue} {weather}, packed stands of fans in {us['colors']}, ready to face the {game['opponent_name']}. "
            "Photorealistic, epic wide angle, high detail.")

def featured_player(text):
    """The roster player a post is about (the first one named), if he has a portrait to borrow a face from."""
    import roster, media
    text = (text or "").lower()
    players = [p for p in roster.query_full_roster() if p.get('portrait_file') and p.get('player_name')]
    last_names = {}
    for p in players:
        last_names.setdefault(p['player_name'].split()[-1].lower(), []).append(p)
    word = lambda phrase: re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text)
    hits = []
    for p in players:
        full = p['player_name'].lower()
        last = full.split()[-1]
        match = word(full) or (len(last) > 3 and len(last_names[last]) == 1 and word(last))  # unique last name, e.g. "Hubbard"
        if match:
            hits.append((match.start(), p))
    if not hits:
        return None
    player = min(hits, key=lambda hit: hit[0])[1]
    path = os.path.join(media.PORTRAIT_DIRS['player'], player['portrait_file'])
    return {**player, "portrait_path": path} if os.path.exists(path) else None

def player_photo_prompt(photo, player, us):
    """Frames the shot so one player's face is large and clear, which is what the face swap needs."""
    import roster
    position = roster.POSITION_NAMES.get(player['position'], player['position']).lower()
    # FLUX weights the start of the prompt most, so the framing comes first. The face swap needs a bare,
    # unobstructed face: an on helmet's face mask cuts across the swapped face.
    return (f"Chest-up close-up photo of one college football player, bareheaded with no helmet on, carrying his helmet under his arm, "
            f"his whole face clearly visible, well lit and looking toward the camera. He is a {us['name']} {position} "
            f"in a {us['colors']} uniform with jersey number {player['jersey_num']}. "
            + PHOTO_STYLE.format(photo=photo, team=us['full_name'], colors=us['colors']))

def render_week_images(selected_model, game, tweet_list):
    """Renders the story hero banner and the tweet photos in one ComfyUI session (FLUX loads once).
    Tweets are kept without photos, and the story without a banner, if ComfyUI isn't available."""
    week_id = game['week_id']
    wanted = [t for t in tweet_list if isinstance(t.get('photo'), str) and t['photo'].strip()][:PHOTO_TWEETS]
    # The model sometimes describes fewer photos than asked; picture the scene from the post itself for the rest,
    # preferring posts about a player so his real face can be used
    for tweet in sorted(tweet_list, key=lambda t: featured_player(t['text']) is None):
        if len(wanted) >= PHOTO_TWEETS:
            break
        if tweet not in wanted:
            tweet['photo'] = f"A scene that matches this post: {tweet['text']}"
            wanted.append(tweet)
    if not image_engine.ensure_running():
        return
    unload_ollama_model(selected_model)
    try:
        try:
            width, height = HERO_SIZE
            progress.step("Rendering the banner photo")
            hero_path = image_engine.generate_image(hero_prompt(game), f"hero_w{week_id}_{int(time.time())}", width, height)
            database.save_story_image(week_id, hero_path)
        except Exception:
            pass  # The story still shows without a banner
        for index, tweet in enumerate(wanted):
            progress.step("Rendering post photos", f"photo {index + 1} of {len(wanted)}")
            try:
                us = team.user_team()
                # A post about a player gets his face from his portrait (when the ReActor face swap is installed)
                player = featured_player(f"{tweet['text']} {tweet['photo']}")
                prompt = player_photo_prompt(tweet['photo'].strip(), player, us) if player else                     PHOTO_STYLE.format(photo=tweet['photo'].strip(), team=us['full_name'], colors=us['colors'])
                tweet['image_path'] = image_engine.generate_image(prompt, f"tweet_w{week_id}_{int(time.time())}_{index}",
                                                                  face_path=player['portrait_path'] if player else None)
            except Exception:
                continue  # One failed render shouldn't cost the other photos
    finally:
        image_engine.free_memory()

def parse_tweets(raw_tweets):
    # Strip any markdown code fence (```json or bare ```)
    if raw_tweets.startswith("```"):
        raw_tweets = raw_tweets.split("\n", 1)[1] if "\n" in raw_tweets else ""
    if raw_tweets.endswith("```"):
        raw_tweets = raw_tweets[:-3]

    parsed = json.loads(raw_tweets)
    if isinstance(parsed, dict):
        parsed = parsed.get('tweets', [])
    tweets = [t for t in parsed if isinstance(t, dict) and all(t.get(k) for k in ('handle', 'name', 'text'))]
    for tweet in tweets:
        tweet['text'] = strip_tags(tweet['text'])  # tweets keep their casual lowercase style
    if not tweets:
        raise ValueError("No valid tweets in model output.")
    return tweets[:TWEET_COUNT]

def build_prev_context(last_played):
    if not last_played:
        return "No games recorded yet."
    name = team.user_team()['name']
    prev_context = f"In Week {last_played['week_id']}, {name} played {last_played['opponent_name']} putting up {last_played['wyo_pass_yds']} pass yards and {last_played['wyo_rush_yds']} rush yards."
    wyo, opp = last_played['wyo_score'], last_played['opp_score']
    if wyo is not None and opp is not None:
        if wyo > opp:
            result = f"{name} WON {wyo}-{opp}"
        elif wyo < opp:
            result = f"{name} LOST {opp}-{wyo}"
        else:
            result = f"the game ended in a {wyo}-{opp} TIE"
        prev_context += f" Final score: {result}. Use this exact final score and do not invent a different one."
    return prev_context

def generate_dynasty_content(selected_model, storyline_context="", player_lines=None, storyline_titles="", scouting_context=""):
    active_stats = database.query_active_week()
    prev_context = build_prev_context(database.query_last_played_week())

    headline = f"CURRENT WEEK FOCUS: Preparing for Week {active_stats['week_id']} against {active_stats['opponent_name']}."
    us = team.user_team()
    scouting = f" Scouting report on the opponent (use only these facts about them): {scouting_context}" if scouting_context else ""
    import rivals, presser
    rivalry = rivals.prompt_context()
    presser_quotes = presser.dispatch_context()

    # Generate main article
    article_prompt = f"IMPORTANT: every player is a man on a men's college football team, so always use he/him/his for players, whatever their first name. Write an immersive 3-sentence game dispatch layout entry. Sentence 1 must summarize the dramatic outcome from the PREVIOUS game: {prev_context}. Sentences 2 and 3 must pivot directly into the game preparation strategy for the UPCOMING matchup: {headline} using {us['identity']}.{scouting}{rivalry}{presser_quotes} Do not output raw code strings or brackets."
    if storyline_context:
        article_prompt += f" Ongoing player storylines on the team: {storyline_context} Work a brief nod to one of these storylines into sentence 3, referring to players by name and position."

    try:
        progress.step("Writing the dispatch")
        story_text = call_ollama(selected_model, article_prompt)
    except Exception as e:
        # Don't save anything, so the existing story for this week is kept
        return f"Ollama processing connection dropped: {str(e)}"

    database.save_story_to_db(active_stats['week_id'], active_stats['opponent_name'], story_text)

    # Generate tweets
    # Spell out what each post is for; small models follow an explicit plan far better than "at least N" rules
    plan = []
    player_lines = (player_lines or [])[:TWEET_COUNT - 2]
    for number, line in enumerate(player_lines, start=1):
        plan.append(f"Post {number}: about {line} in the last game; quote those numbers and say how he impacted the result.")
    if storyline_titles:
        plan.append(f"Post {len(player_lines) + 1}: reacts to one of these ongoing player storylines: {storyline_titles}.")
    if presser_quotes:
        plan.append("One of the remaining posts reacts to a quote from the press conference, quoting it exactly." + presser_quotes)
    if rivalry:
        plan.append("At least two of the remaining posts are rivalry trash talk aimed at the other side's fans, built on the rivalry facts." + rivalry)
    plan.append(f"The remaining posts hype the upcoming Week {active_stats['week_id']} game vs {active_stats['opponent_name']}.")
    plan.append(f"Exactly {PHOTO_TWEETS} posts include a photo: give only those posts a \"photo\" field with one vivid sentence describing what the photo shows (the scene, people, action and setting). The other posts have no photo field.")
    tweet_prompt = (
        "IMPORTANT: every player mentioned is a man on a men's college football team, so always use he/him/his for players, whatever their first name. "
        f"Create {TWEET_COUNT} distinct mock Twitter/X posts about {team.user_team()['name']} Football. Recent context: {prev_context}. "
        + " ".join(plan)
        + " Every post is written by a fan or sports media account, never by a player, and each comes from a different, creative account handle."
        + " Refer to players by name and position, never depth chart codes like HB2, and never invent stats or injuries."
        + f' Respond with ONLY a JSON object in exactly this shape, with {TWEET_COUNT} items: {{"tweets": [{{"handle": "@GamedayFan", "name": "Fan", "text": "Tweet text here", "photo": "only on photo posts: what the photo shows"}}, ...]}}'
    )

    try:
        progress.step("Writing the social posts", f"{TWEET_COUNT} posts")
        tweet_list = parse_tweets(call_ollama(selected_model, tweet_prompt, force_json=True))
    except Exception:
        # Fallback layout inject if the tweet call or json formatting fails
        tweet_list = [{"handle": "@GamedayFan", "name": "Gameday Fan", "text": f"Locked in for the week {active_stats['week_id']} matchup vs {active_stats['opponent_name']}! {team.user_team()['hashtag']}"}]
    render_week_images(selected_model, active_stats, tweet_list)
    database.save_tweets_to_db(active_stats['week_id'], tweet_list)

    return story_text
