import asyncio
import json
import os
import re
import shutil
import time
import database
import events
import league
import media
import roster
import scouting
import storylines
import team
from sentences import split as sentence_split

# Weekly podcast: two hosts break down a game from the scoring-summary screenshots (read by events.py) plus the save's
# stats: the numbers, where each team shined and where it can be better, the season so far and the next opponent.
# The script is written by the AI and voiced with Microsoft's neural voices (edge-tts), one audio file per line.

PODCAST_DIR = os.path.join(database.STATIC_DIR, "podcasts")
DEFAULT_HOSTS = [{"name": "Andrew", "voice": "en-US-AndrewNeural", "role": "lead host who lives in the numbers"},
                 {"name": "Ava", "voice": "en-US-AvaNeural", "role": "color analyst with strong opinions on effort and execution"}]
VOICE_LOCALES = ("en-US", "en-GB", "en-AU", "en-CA")
TTS_WORKERS = 4
TTS_ATTEMPTS = 8
COVER_SIZE = (1024, 1024)
TARGET_LINES = 30
ARCHIVE_SIZE = 5          # previous episodes kept in the Back Catalog; the oldest is dropped when a new one is made

def initialize_podcast_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS podcast_episodes (
        episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_num INTEGER,
        opponent_name TEXT,
        title TEXT NOT NULL,
        summary TEXT,
        hosts_json TEXT NOT NULL,
        script_json TEXT NOT NULL,     -- [{"host": 0|1, "text": "...", "audio": "podcasts/<id>/line_000.mp3"}]
        game_json TEXT NOT NULL,
        cover_image TEXT,
        audio_file TEXT,               -- the whole episode as one mp3, for download
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- Voices ----------

_voices = []

def list_voices():
    """English neural voices from Microsoft (cached for the session)."""
    if not _voices:
        import edge_tts
        voices = asyncio.run(edge_tts.list_voices())
        _voices.extend(sorted(({"id": v['ShortName'], "name": v['ShortName'].split('-')[-1].replace('Neural', ''), "locale": v['Locale'],
                                "gender": v['Gender'], "style": ", ".join(v.get('VoiceTag', {}).get('VoicePersonalities', []))}
                               for v in voices if v['Locale'] in VOICE_LOCALES and 'Multilingual' not in v['ShortName']),
                              key=lambda v: (VOICE_LOCALES.index(v['locale']), v['name'])))
    return _voices

def hosts_from(request_hosts):
    hosts = []
    for index, default in enumerate(DEFAULT_HOSTS):
        given = (request_hosts or [{}, {}])[index] if index < len(request_hosts or []) else {}
        name = re.sub(r"[^\w .'-]", "", (given.get('name') or default['name']))[:24].strip() or default['name']
        voice = given.get('voice') if re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+Neural", given.get('voice') or "") else default['voice']
        hosts.append({"name": name, "voice": voice, "role": default['role']})
    return hosts

def preview(voice, name):
    """A short sample of a voice introducing itself (cached). Returns the path under static/."""
    import edge_tts
    if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+Neural", voice or ""):
        raise ValueError("Unknown voice.")
    name = re.sub(r"[^\w .'-]", "", name or "")[:24] or "your host"
    folder = os.path.join(PODCAST_DIR, "previews")
    os.makedirs(folder, exist_ok=True)
    file_name = f"{voice}_{re.sub(r'[^A-Za-z]', '', name)}_btn.mp3"
    path = os.path.join(folder, file_name)
    if not os.path.exists(path):
        asyncio.run(edge_tts.Communicate(f"Hey everybody, I'm {name}, and this is {SHOW_NAME}.", voice, rate="+4%").save(path))
    return f"podcasts/previews/{file_name}"

# ---------- What the hosts know ----------

def scheduled_game(opponent_row):
    if not opponent_row:
        return None
    full = f"{opponent_row['name']} {opponent_row['nickname'] or ''}".strip()
    return next((g for g in database.query_full_schedule() if g['opponent_name'] in (full, opponent_row['name'])), None)

def played_game_row(us_id, them_id, week):
    return next((g for g in league.query_games(week=week) if {g['home_id'], g['away_id']} == {us_id, them_id}), None) if week is not None else None

def top_lines(stats_by_player, names, count):
    ranked = sorted(stats_by_player.items(), key=lambda item: -storylines.impact_score(item[1]))[:count]
    return [f"{names[pid]} had {roster.format_stat_line(stats, 'prose')}" for pid, stats in ranked if pid in names and roster.format_stat_line(stats, 'prose')]

def game_facts(draft, ours, theirs, game):
    """Everything the hosts may cite about this game, as plain sentences, plus each team's strengths and concerns
    (worked out here so the model never has to do arithmetic or decide which side a number belongs to)."""
    us_n, them_n = ours['name'], theirs['name']
    facts, play_lines = [], []
    score, halftime = {ours['abbr']: 0, theirs['abbr']: 0}, None
    for p in draft['plays']:
        if halftime is None and p['quarter'] >= 3:
            halftime = dict(score)
        score[p['team']] = score.get(p['team'], 0) + events.parse_play(p['text'])['points']
        who = us_n if p['team'] == ours['abbr'] else them_n
        play_lines.append(f"Quarter {p['quarter']}, {p['clock']} left: {who} scored, {p['text'].replace(' Yd ', '-yard ')}. "
                          f"Score: {us_n} {score[ours['abbr']]}, {them_n} {score[theirs['abbr']]}.")
    halftime = halftime or score
    facts.append(("result", f"Final: {us_n} {ours['final']}, {them_n} {theirs['final']}. Halftime: {us_n} {halftime[ours['abbr']]}, {them_n} {halftime[theirs['abbr']]}. "
                 f"By quarter, {us_n} scored {', '.join(map(str, ours['quarters']))} and {them_n} scored {', '.join(map(str, theirs['quarters']))}."))
    facts.append(("plays", "Scoring plays in order: " + " ".join(play_lines)))

    good = {us_n: [], them_n: []}
    bad = {us_n: [], them_n: []}
    for side, other in ((ours, theirs), (theirs, ours)):
        name, q = side['name'], side['quarters']
        if q and q[0] > (other['quarters'] or [0])[0]:
            good[name].append(f"won the first quarter {q[0]} to {other['quarters'][0]}")
        elif q and q[0] < (other['quarters'] or [0])[0]:
            bad[name].append(f"fell behind in the first quarter, {q[0]} to {other['quarters'][0]}")
        half, other_half = sum(q[2:]), sum(other['quarters'][2:])
        (good if half > other_half else bad if half < other_half else {name: []})[name].append(
            f"{'outscored' if half > other_half else 'was outscored by'} {other['name']} {max(half, other_half)} to {min(half, other_half)} in the second half") if half != other_half else None
        for index, points in enumerate(q[:4]):
            if points == 0:
                bad[name].append(f"was shut out in the {['first', 'second', 'third', 'fourth'][index]} quarter")
    longest = max(((events.parse_play(p['text'])['yards'] or 0, p) for p in draft['plays']), key=lambda x: x[0], default=(0, None))
    if longest[1]:
        name = us_n if longest[1]['team'] == ours['abbr'] else them_n
        good[name].append(f"had the longest scoring play of the game: {longest[1]['text'].replace(' Yd ', '-yard ')}")

    if game and game.get('is_played'):
        facts.append(("numbers", f"Team yards: {us_n} ran for {game['wyo_rush_yds']} and threw for {game['wyo_pass_yds']}; "
                     f"{them_n} ran for {game['opp_rush_yds']} and threw for {game['opp_pass_yds']}."))
        for name, rush, pas in ((us_n, game['wyo_rush_yds'], game['wyo_pass_yds']), (them_n, game['opp_rush_yds'], game['opp_pass_yds'])):
            if rush >= 200:
                good[name].append(f"ran for {rush} yards")
            if pas < 150:
                bad[name].append(f"threw for only {pas} yards")
        if game['opp_rush_yds'] >= 180:
            bad[us_n].append(f"the defense let {them_n} run for {game['opp_rush_yds']} yards")
        names = {p['save_id']: roster.describe_player(p) for p in roster.query_full_roster() if p['save_id']}
        mine = roster.query_week_stats(game['week_id'])
        if mine:
            facts.append(("us_players", f"{us_n} individual stats: " + "; ".join(top_lines(mine, names, 6)) + "."))
            giveaways = sum(storylines.turnovers(x) for x in mine.values())
            sacked = sum(x.get('PASSSACKED', 0) for x in mine.values())
            carries = sum(x.get('RUSHATTEMPTS', 0) for x in mine.values())
            completions = sum(x.get('PASSCOMPLETED', 0) for x in mine.values())
            attempts = sum(x.get('PASSATTEMPTS', 0) for x in mine.values())
            (good if not giveaways else bad)[us_n].append("did not turn the ball over" if not giveaways else f"turned the ball over {giveaways} times")
            if sacked:
                bad[us_n].append(f"the quarterback was sacked {sacked} time{'s' if sacked != 1 else ''}")
            if carries and game['wyo_rush_yds'] / carries >= 5:
                good[us_n].append(f"averaged {game['wyo_rush_yds'] / carries:.1f} yards per carry")
            if attempts:
                pct = round(100 * completions / attempts)
                (good if pct >= 65 else bad if pct < 60 else {us_n: []})[us_n].append(f"completed {completions} of {attempts} passes, {pct} percent")
        row = played_game_row(ours.get('team_id'), theirs.get('team_id'), game['week_id'])
        if row:
            players = league.query_players()
            theirs_stats = {r['player_id']: r['stats'] for r in league.query_player_games(week=game['week_id'])
                            if players.get(r['player_id'], {}).get('team_id') == theirs.get('team_id')}
            their_names = {pid: f"{players[pid]['position']} {players[pid]['name']}" for pid in theirs_stats}
            if theirs_stats:
                facts.append(("them", f"{them_n} individual stats: " + "; ".join(top_lines(theirs_stats, their_names, 4)) + "."))
    for name, good_topic, bad_topic in ((us_n, "us_good", "us_bad"), (them_n, "them", "them")):
        if good[name]:
            facts.append((good_topic, f"Where {name} shined: " + "; ".join(good[name]) + "."))
        if bad[name]:
            facts.append((bad_topic, f"Where {name} has to be better: " + "; ".join(bad[name]) + "."))
    return [(topic, spoken_names(text)) for topic, text in facts]

def season_facts(ours, week):
    """The season around this game: earlier results, the record, and next week's opponent."""
    schedule = database.query_full_schedule()
    earlier = [g for g in schedule if g['is_played'] and week is not None and g['week_id'] < week and g['wyo_score'] is not None]
    facts = []
    if earlier:
        facts.append(("season", "Earlier this season: " + "; ".join(
            f"Week {g['week_id']} {'beat' if g['wyo_score'] > g['opp_score'] else 'lost to'} {g['opponent_name']} {g['wyo_score']} to {g['opp_score']}" for g in earlier) + "."))
    wins, losses = database.query_season_record()
    facts.append(("season", f"{ours['name']} is now {wins} and {losses} on the season."))
    upcoming = next((g for g in schedule if week is not None and g['week_id'] > week), None)
    if upcoming:
        card = scouting.build_scouting(upcoming)
        context = scouting.scouting_context(card) if card else ""
        facts.append(("ahead", f"Next up, Week {upcoming['week_id']}: {'home against' if upcoming.get('site') == 'Home' else 'at'} the {upcoming['opponent_name']}. {context}"))
    return [(topic, spoken_names(text)) for topic, text in facts]

_spoken = {}

def spoken_names(text):
    """'C. Michigan' -> 'Central Michigan', 'Washington St.' -> 'Washington State' (read aloud as written otherwise)."""
    if not _spoken:
        for t in league.query_teams().values():
            full = media.espn_school_name(t['name'])
            if full != t['name']:
                _spoken[t['name']] = full
        _spoken[""] = ""
    for short, full in sorted(_spoken.items(), key=lambda item: -len(item[0])):
        if short:
            text = re.sub(r"(?<!\w)" + re.escape(short) + r"(?!\w)", full, text)
    return text

# ---------- Script ----------

SPOKEN_RULES = ("This is read aloud by a text-to-speech voice, so write only spoken words: no stage directions, sound effects, asterisks, emoji or brackets. "
                "Say scores as 'thirty-five to twenty-one' style numbers or '35 to 21', never '35-21'. Write 'yards', never 'Yd'. "
                "Every player is a man; use he/him. Use only the facts given: never invent stats, scores, injuries, quotes, plays or places. "
                "No sponsor reads or ad breaks.")

SHOW_NAME = "Between the Numbers"

def team_spoken(t):
    """'the Indiana Hoosiers': the school plus nickname when the league knows the team."""
    row = league.query_team(t['team_id']) if t.get('team_id') is not None else None
    return "the " + spoken_names(team.team_details(row)['full_name'] if row else t['name'])

def welcome_line(hosts, ours, theirs):
    """Every episode opens the same way; the model takes over from the co-host's reply."""
    return (f"Welcome to {SHOW_NAME}, folks. I'm {hosts[0]['name']}, and here with me is {hosts[1]['name']}. "
            f"Today we'll be talking about {team_spoken(ours)} and {team_spoken(theirs)}.")

def segments(ours, theirs):
    """The show's running order: (what the segment covers, fact topics it may use, how many lines)."""
    return [
        ("the co-host's reply to the welcome, then a quick cold open that teases the final score and the biggest play", ("result", "us_good"), 3),
        ("the result and how the game swung, quarter by quarter, using the running scores", ("result", "plays"), 5),
        ("the game by the numbers: team yards and the standout individual stat lines", ("numbers", "us_players"), 6),
        (f"where {ours} shined", ("us_good", "us_players"), 4),
        (f"where {ours} has to be better (a win can still expose problems)", ("us_bad",), 5),
        (f"the {theirs} side: where they shined and where they have to be better", ("them",), 4),
        ("how this game fits with the earlier games this season", ("season", "result"), 3),
        ("a look ahead at next week's opponent and what to watch for", ("ahead",), 4),
        ("a short sign-off that names next week's opponent", ("result", "ahead"), 2),
    ]

MAX_LINE_SENTENCES = 3

# Numbers check: small models drift into made-up scores ("forty-five to twenty") even with the facts in front of them.
# A line that states a number the facts don't contain is dropped. Small numbers (0-4) are everyday words ("one of the best").
NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                            "fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
CHECKED_FROM = 5

def spoken_numbers(text):
    """Every number in the text, written as digits ('227', '1,200') or words ('forty-five', 'eighteen')."""
    found = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}
    compound = re.compile(r"\b(" + "|".join(TENS) + r")(?:[- ](one|two|three|four|five|six|seven|eight|nine))?\b")
    for tens, ones in compound.findall(text.lower()):
        found.add(TENS[tens] + (NUMBER_WORDS[ones] if ones else 0))
    rest = compound.sub(" ", text.lower())  # so the "five" in "forty-five" isn't counted again
    for word in re.findall(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", rest):
        found.add(NUMBER_WORDS[word])
    return found

def invented_numbers(text, allowed):
    return sorted(n for n in spoken_numbers(text) if n >= CHECKED_FROM and n not in allowed)

def is_repeat(text, lines):
    """True when a line says (nearly) the same thing as one already in the script."""
    import difflib
    key = re.sub(r"[^a-z0-9 ]", "", text.lower())
    return any(difflib.SequenceMatcher(None, key, re.sub(r"[^a-z0-9 ]", "", l['text'].lower())).ratio() > 0.8 for l in lines)

def show_setup(hosts, about, welcome):
    """The part of every segment prompt that describes the show and its hosts."""
    a, b = hosts
    return (f"You write {about}. "
            f"Host 0 is {a['name']}, the {a['role']}. Host 1 is {b['name']}, the {b['role']}. They are friends: they banter, "
            "disagree a little, ask each other questions and build on each other's points. Lines are short and conversational, "
            f"and the show is family friendly. Host 0 has already opened the show with: \"{welcome}\" "
            f"Nobody welcomes the listeners or introduces the hosts again. {SPOKEN_RULES}")

def write_script(selected_model, hosts, ours, theirs, week, facts):
    """A game episode: one game, both teams' numbers."""
    us_name, them_name = spoken_names(ours['name']), spoken_names(theirs['name'])
    welcome = welcome_line(hosts, ours, theirs)
    about = (f"{SHOW_NAME}, a two-host college football podcast, this episode about {us_name}'s Week {week} game against {them_name} "
             f"(final: {us_name} {ours['final']}, {them_name} {theirs['final']})")
    return write_show(selected_model, hosts, show_setup(hosts, about, welcome), welcome, segments(us_name, them_name), facts,
                      f"Week {week}: {us_name} vs {them_name}")

def write_show(selected_model, hosts, show, welcome, running_order, facts, fallback_title):
    """Writes the show one segment at a time (small models write short, repetitive scripts when asked for it all at once)."""
    import ai_engine
    a, b = hosts
    lines, title, summary = [{"host": 0, "text": welcome}], None, None
    allowed = spoken_numbers(" ".join(text for _, text in facts) + " " + show)
    for index, (topic, fact_topics, count) in enumerate(running_order):
        segment_facts = " ".join(text for t, text in facts if t in fact_topics) or "No extra facts: keep it general and don't invent any."
        first_host = (index + 1) % 2  # host 0 said the welcome, so host 1 answers it
        covered = "; ".join(seg[0] for seg in running_order[:index]) or "nothing yet (this opens the show)"
        prompt = (f"{show} Facts for this segment (the only facts you may use): {segment_facts} "
                  f"Write the next segment: {topic}. Exactly {count} lines that alternate between the hosts, starting with host {first_host}. "
                  f"Each line is one or two sentences of dialogue only (no speaker names). Segments already done: {covered}. "
                  "Don't repeat points from those segments; stick to this segment's topic. "
                  + ('Also give the episode a title under 10 words and a one-sentence description. '
                     'Respond with ONLY a JSON object: {"title": "...", "summary": "...", "lines": [{"host": 0, "text": "..."}, ...]}' if index == 0 else
                     'Respond with ONLY a JSON object: {"lines": [{"host": 0, "text": "..."}, ...]}'))
        for _attempt in range(2):
            try:
                data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
            except Exception:
                continue
            new_lines = []
            for line in data.get('lines') or []:
                if isinstance(line, dict):
                    text = speakable(spoken_names(ai_engine.clean_text(str(line.get('text') or ""))))  # clean_text also restores name capitals
                    text = re.sub(rf"^(?:({re.escape(a['name'])}|{re.escape(b['name'])})\s*:\s*)+", "", text)  # "Ava: Ava: ..." prefixes
                    text = " ".join(sentence_split(text)[:MAX_LINE_SENTENCES])
                    text = re.sub(r"\.{2,}$", ".", text)
                    if text and not is_repeat(text, lines + new_lines) and not invented_numbers(text, allowed):
                        new_lines.append({"host": 1 if line.get('host') in (1, "1", b['name']) else 0, "text": text})
            if new_lines:
                lines.extend(new_lines)
                if index == 0:
                    title = ai_engine.strip_tags(str(data.get('title') or "")) or None
                    summary = ai_engine.strip_tags(str(data.get('summary') or "")) or None
                break
    if len(lines) < 10:
        raise RuntimeError("The model didn't return a usable podcast script. Try again.")
    return title or fallback_title, summary or "", lines

def speakable(text):
    """Cleans a line for text-to-speech: no stage directions, scores read as 'X to Y', abbreviations spelled out."""
    text = re.sub(r"\*[^*]*\*|\([^)]*(laugh|music|pause|sigh|chuckle)[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1 to \2", text)
    text = re.sub(r"\bYd\b|\byds\b", "yards", text, flags=re.IGNORECASE)
    text = re.sub(r"\bQ([1-4])\b", lambda m: ["first", "second", "third", "fourth"][int(m.group(1)) - 1] + " quarter", text)
    return re.sub(r"\s{2,}", " ", text).strip()

# ---------- Audio ----------

def line_path(episode_dir, index):
    return os.path.join(episode_dir, f"line_{index:03d}.mp3")

def voice_lines(episode_dir, lines, hosts):
    """Records every line that isn't recorded yet (a few at a time). Microsoft's free service drops a share of requests
    at random, so each line retries with growing pauses, and lines already recorded are kept for the next try.
    Returns (recorded count, last error text)."""
    import edge_tts
    os.makedirs(episode_dir, exist_ok=True)
    errors = []

    async def synth_all():
        gate = asyncio.Semaphore(TTS_WORKERS)
        async def one(index, line):
            path = line_path(episode_dir, index)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return
            async with gate:
                for attempt in range(TTS_ATTEMPTS):
                    try:
                        await edge_tts.Communicate(line['text'], hosts[line['host']]['voice'], rate="+4%").save(path)
                        if os.path.getsize(path) > 0:
                            return
                    except Exception as e:
                        errors.append(f"{type(e).__name__}: {e}")
                    if os.path.exists(path):
                        os.remove(path)  # a dropped request can leave an empty file behind
                    await asyncio.sleep(min(2 * (attempt + 1), 12))
        await asyncio.gather(*(one(i, line) for i, line in enumerate(lines)))
    asyncio.run(synth_all())
    recorded = sum(1 for i in range(len(lines)) if os.path.exists(line_path(episode_dir, i)))
    return recorded, (errors[-1] if errors else "")

def join_episode(episode_dir, count):
    """MP3 frames from the same voice service share one format, so the line files join end to end."""
    with open(os.path.join(episode_dir, "episode.mp3"), "wb") as out:
        for index in range(count):
            with open(line_path(episode_dir, index), "rb") as part:
                out.write(part.read())

def record_episode(episode_id):
    """Records an episode's missing lines; once every line exists, joins them into the downloadable MP3.
    Returns (recorded, total, error text)."""
    conn = database.get_db_connection()
    row = conn.execute("SELECT hosts_json, script_json FROM podcast_episodes WHERE episode_id = ?", (episode_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("That episode no longer exists.")
    hosts, lines = json.loads(row['hosts_json']), json.loads(row['script_json'])
    episode_dir = os.path.join(PODCAST_DIR, str(int(episode_id)))
    recorded, error = voice_lines(episode_dir, lines, hosts)
    for index, line in enumerate(lines):
        if os.path.exists(line_path(episode_dir, index)):
            line['audio'] = f"podcasts/{episode_id}/line_{index:03d}.mp3"
        else:
            line.pop('audio', None)
    audio_file = None
    if recorded == len(lines):
        join_episode(episode_dir, len(lines))
        audio_file = f"podcasts/{episode_id}/episode.mp3"
    conn = database.get_db_connection()
    conn.execute("UPDATE podcast_episodes SET script_json = ?, audio_file = ? WHERE episode_id = ?", (json.dumps(lines), audio_file, episode_id))
    conn.commit()
    conn.close()
    return recorded, len(lines), error

def retry_recording(episode_id):
    """The Retry recording button: records whatever is still missing."""
    recorded, total, error = record_episode(episode_id)
    return {"episodes": query_episodes(), "warning": None if recorded == total else recording_warning(recorded, total, error)}

def recording_warning(recorded, total, error):
    return (f"Recorded {recorded} of {total} lines; Microsoft's voice service kept dropping the rest"
            + (f" ({error})" if error else "") + ". The script is saved: press Retry recording on the episode in a minute.")

# ---------- Cover art ----------

def cover_subject(plays, ours, players):
    """Our player with the longest score (he gets his portrait face on the cover)."""
    best = None
    for p in plays:
        info = events.parse_play(p['text'])
        if p['team'] == ours['abbr'] and info['player'] and (not best or (info['yards'] or 0) > (best[1]['yards'] or 0)):
            best = (p, info)
    if not best:
        return None, None
    return players.get(best[1]['player']), f"{best[1]['player']} after his {best[1]['yards']}-yard touchdown {'catch' if best[1]['kind'] == 'pass' else best[1]['kind']}"

def cover_teams(ours, theirs):
    """The team the cover features (ours when we played, otherwise the winner) and its opponent, with their colours."""
    if ours.get('team_id') != team.user_team()['id'] and (theirs.get('final') or 0) > (ours.get('final') or 0):
        ours, theirs = theirs, ours
    def details(t):
        row = league.query_team(t['team_id']) if t.get('team_id') is not None else None
        return {**(team.team_details(row) if row else {"name": t['name'], "full_name": t['name'], "colors": "team"}), **t}
    return details(ours), details(theirs)

def render_cover(selected_model, ours, theirs, plays, episode_dir):
    import ai_engine, image_engine
    ours, theirs = cover_teams(ours, theirs)
    players = {}
    for name, p in events.roster_names([ours.get('team_id')]).items():
        file_name = media.player_portrait_file(p.get('assetName'), p.get('headAsset'))
        path = os.path.join(media.PORTRAIT_DIRS['player'], file_name) if file_name else None
        players[name] = {**p, "portrait_path": path if path and os.path.exists(path) else None}
    player, scene = cover_subject(plays, ours, players)
    if not image_engine.ensure_running():
        return None
    ai_engine.unload_ollama_model(selected_model)
    try:
        no_text = "No text, letters or captions anywhere in the image."
        if player:
            prompt = ai_engine.player_photo_prompt(f"{scene}, dramatic stadium lighting. {no_text}", {"position": player['position'], "jersey_num": player['jersey']}, ours)
        else:
            won = (ours.get('final') or 0) >= (theirs.get('final') or 0)
            moment = "celebrating a win over" if won else "walking off the field after a tough loss to"
            prompt = ai_engine.PHOTO_STYLE.format(
                photo=f"The {ours['full_name']} in {ours['colors']} uniforms {moment} the {theirs['full_name']}, "
                      f"whose players wear {theirs['colors']} in the background. {no_text}",
                team=ours['full_name'], colors=ours['colors'])
        path = image_engine.generate_image(prompt, f"podcast_cover_{int(time.time())}", *COVER_SIZE, face_path=(player or {}).get('portrait_path'))
        return path
    except Exception:
        return None
    finally:
        image_engine.free_memory()

# ---------- Episodes ----------

def generate_episode(selected_model, draft, request_hosts=None):
    """Writes, voices and stores an episode from the reviewed screenshot reading; deletes the screenshots afterwards."""
    import progress
    us = team.user_team()
    hosts = hosts_from(request_hosts)
    teams = draft['teams']
    if len(teams) != 2 or not draft['plays']:
        raise ValueError("The reading needs both teams and at least one scoring play.")
    draft = events.build_draft(teams, draft['plays'], {t['abbr'].upper(): t.get('final') for t in teams})
    ours = next((t for t in draft['teams'] if t.get('team_id') == us['id']), None) or next((t for t in draft['teams'] if t['name'] == us['name']), draft['teams'][1])
    theirs = next(t for t in draft['teams'] if t is not ours)
    their_row = league.query_team(theirs['team_id']) if theirs.get('team_id') is not None else None
    game = scheduled_game(their_row)
    week = game['week_id'] if game else None

    progress.start()
    try:
        progress.step("Writing the script")
        facts = game_facts(draft, ours, theirs, game) + season_facts(ours, week)
        title, summary, lines = write_script(selected_model, hosts, ours, theirs, week, facts)

        conn = database.get_db_connection()
        cursor = conn.execute("""INSERT INTO podcast_episodes (week_num, opponent_name, title, summary, hosts_json, script_json, game_json)
                                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
                              (week, theirs['name'], title, summary, json.dumps(hosts), json.dumps(lines),
                               json.dumps({"teams": draft['teams'], "plays": draft['plays'], "facts": [text for _, text in facts]})))
        episode_id = cursor.lastrowid
        conn.commit()
        conn.close()

        episode_dir = os.path.join(PODCAST_DIR, str(episode_id))
        progress.step("Recording the voices", f"{len(lines)} lines")
        # The script is already saved, so a flaky voice service never costs the episode: missing lines can be retried
        recorded, total, error = record_episode(episode_id)
        progress.step("Rendering the cover art")
        cover = render_cover(selected_model, ours, theirs, draft['plays'], episode_dir)

        conn = database.get_db_connection()
        conn.execute("UPDATE podcast_episodes SET cover_image = ? WHERE episode_id = ?", (cover, episode_id))
        conn.commit()
        conn.close()
    finally:
        progress.finish()
    events.clear_uploads()
    events.clear_draft()
    prune_episodes()
    return {"episodes": query_episodes(), "warning": None if recorded == total else recording_warning(recorded, total, error)}

# ---------- Between the Numbers Weekly: around the league from the Weekly Recap ----------

WEEKLY_NAME = f"{SHOW_NAME} Weekly"
WEEKLY_AWARDS = (("offense", "Offensive Player of the Week"), ("defense", "Defensive Player of the Week"),
                 ("freshman", "Freshman of the Week"), ("bummer", "Bummer of the Week (the week's worst game by a big name)"))

def weekly_segments(us_name):
    return [
        ("the co-host's reply to the welcome, then a quick cold open teasing the week's wildest result", ("games",), 3),
        ("the game of the week, the upset and the biggest comeback: how each one swung", ("games",), 6),
        ("the Top 25 matchups and the biggest blowout", ("top25", "games"), 4),
        ("the players of the week, the top freshman and the bummer of the week", ("players",), 6),
        ("the polls: who rose, who fell, and the playoff picture", ("polls", "cfp"), 5),
        ("the Heisman race", ("heisman",), 4),
        (f"a quick hit on {us_name}'s week", ("ours",), 3),
        ("the hottest and coldest streaks, then a short sign-off", ("streaks",), 3),
    ]

def ranked_name(team):
    return (f"No. {team['rank']} " if team.get('rank') else "") + team['name']

def result_line(card):
    """A recap game card -> 'No. 3 Notre Dame beat North Carolina 42 to 31 (2 lead changes, decided by 11)'."""
    away, home = card['rows']
    winner, loser = (home, away) if home['total'] > away['total'] else (away, home)
    return (f"{ranked_name(winner['team'])} beat {ranked_name(loser['team'])} {winner['total']} to {loser['total']}"
            + (f" ({card['detail']})" if card.get('detail') else ""))

def weekly_facts(page, us_name, our_line):
    """([(topic, text)], headlines) from one week's recap, with stats spelled out for the voices."""
    import awards
    facts, headlines = [], []
    games = page['games']
    for key, label in (("game_of_the_week", "Game of the week"), ("upset", "Upset of the week"), ("comeback", "Comeback of the week"),
                       ("blowout", "Blowout of the week")):
        if games.get(key):
            text = f"{label}: {result_line(games[key])}."
            facts.append(("games", text))
            headlines.append(text)
    if page['top25']:
        facts.append(("top25", "Top 25 matchups: " + "; ".join(result_line(g) for g in page['top25']) + "."))
    offense = page['players'].get('offense')
    for key, label in WEEKLY_AWARDS:
        card = page['players'].get(key)
        if not card:
            continue
        if key == 'freshman' and offense and card.get('id') == offense.get('id'):
            facts.append(("players", f"{label}: also {card['first_name']} {card['last_name']}, a freshman, so he won both awards."))
            headlines.append(f"{label}: {card['first_name']} {card['last_name']} again")
            continue
        stats = ", ".join(f"{b['value']} {awards.STAT_WORDS.get(b['label'], b['label'])}" for b in card['boxes'])
        result = card['result']
        facts.append(("players", f"{label}: {card['position']} {card['first_name']} {card['last_name']} of {card['team']['name']}, {stats}; "
                                 f"his team {'won' if result['outcome'] == 'W' else 'lost'} {result['score'].replace('-', ' to ')} "
                                 f"{'against' if result['venue'] == 'vs' else 'at'} {result['opponent']['name']}."))
        headlines.append(f"{label.split(' (')[0]}: {card['first_name']} {card['last_name']}, {card['team']['name']}")
    for key, label in (("risers", "Biggest poll risers"), ("fallers", "Biggest poll fallers")):
        if page.get(key):
            moves = "; ".join(f"{m['team']['name']} from {m['before'] or 'unranked'} to {m['after'] or 'unranked'} after {m['line']}" for m in page[key][:3])
            facts.append(("polls", f"{label}: {moves}."))
    if page['cfp']:
        seeds = lambda rows: "; ".join(f"{c['seed']}. {c['team']['name']} ({c['record']})" for c in rows)
        bubble = page['cfp'][10:12]
        facts.append(("cfp", f"The app's playoff projection, top four: {seeds(page['cfp'][:4])}" + (f". On the bubble: {seeds(bubble)}" if bubble else "") + "."))
    if page['heisman']:
        facts.append(("heisman", "Heisman race: " + awards.heisman_facts(page['heisman'])))
    if our_line:
        facts.append(("ours", f"{us_name} this week: {our_line}."))
    streaks = page.get('streaks') or {}
    for kind, label in (("winning", "Longest winning streaks"), ("losing", "Longest losing streaks")):
        if streaks.get(kind):
            facts.append(("streaks", f"{label}: " + "; ".join(f"{s['team']['name']} ({s['streak'][1:]} straight)" for s in streaks[kind][:3]) + "."))
    return [(topic, spoken_names(text)) for topic, text in facts], headlines

def weekly_welcome(hosts, week):
    return (f"Welcome to {WEEKLY_NAME}, folks. I'm {hosts[0]['name']}, and here with me is {hosts[1]['name']}. "
            f"Today we're going around college football after Week {week}.")

def our_week_line(week, us):
    """'beat Hawaii 24 to 18' for our game that week, or None on a bye."""
    import recap
    game = next((g for g in league.query_games(week=week) if us['id'] in (g['home_id'], g['away_id'])), None)
    if not game:
        return None
    outcome, mine, theirs, venue, opponent_id = recap.side_result(game, us['id'])
    opponent = league.query_teams().get(opponent_id)
    name = opponent['name'] if opponent else "their opponent"
    return {"W": f"beat {name} {mine} to {theirs}", "L": f"lost to {name} {mine} to {theirs}"}.get(outcome, f"tied {name} {mine} to {theirs}")

def render_weekly_cover(selected_model, card, episode_dir):
    """The Offensive Player of the Week on the cover, with his portrait face when the pack has it."""
    import ai_engine, image_engine
    row = next(iter(league.query_rows("SELECT * FROM league_players WHERE player_id = ?", (card.get('id'),))), None)
    team_row = league.query_team(row['team_id']) if row else None
    if not row or not team_row:
        return None
    path = os.path.join(media.PORTRAIT_DIRS['player'], row['portrait_file']) if row.get('portrait_file') else None
    if not image_engine.ensure_running():
        return None
    ai_engine.unload_ollama_model(selected_model)
    try:
        prompt = ai_engine.player_photo_prompt(f"{row['name']} after a huge game, dramatic stadium lighting. No text, letters or captions anywhere in the image.",
                                               {"position": row['position'], "jersey_num": row['jersey']}, team.team_details(team_row))
        return image_engine.generate_image(prompt, f"podcast_cover_{int(time.time())}", *COVER_SIZE,
                                           face_path=path if path and os.path.exists(path) else None)
    except Exception:
        return None
    finally:
        image_engine.free_memory()

def generate_weekly_episode(selected_model, week=None, request_hosts=None):
    """Writes, voices and stores a league-wide episode from one week's recap."""
    import progress, recap
    week = int(week) if week is not None else recap.default_week()
    if week is None:
        raise ValueError("No week has been played yet.")
    page = recap.build_recap(week)
    if not page['game_count']:
        raise ValueError(f"No games were played in Week {week}.")
    us = team.user_team()
    hosts = hosts_from(request_hosts)
    us_name = spoken_names(us['name'])
    facts, headlines = weekly_facts(page, us_name, our_week_line(week, us))

    progress.start()
    try:
        progress.step("Writing the script")
        welcome = weekly_welcome(hosts, week)
        about = f"{WEEKLY_NAME}, a two-host college football podcast that goes around the whole country after Week {week} (not one team's game)"
        title, summary, lines = write_show(selected_model, hosts, show_setup(hosts, about, welcome), welcome,
                                           weekly_segments(us_name), facts, f"Week {week} Around the League")
        conn = database.get_db_connection()
        cursor = conn.execute("""INSERT INTO podcast_episodes (week_num, opponent_name, title, summary, hosts_json, script_json, game_json)
                                 VALUES (?, ?, ?, ?, ?, ?, ?)""",
                              (week, "Around the league", title, summary, json.dumps(hosts), json.dumps(lines),
                               json.dumps({"kind": "weekly", "teams": [], "plays": [], "headlines": headlines,
                                           "facts": [text for _, text in facts]})))
        episode_id = cursor.lastrowid
        conn.commit()
        conn.close()

        episode_dir = os.path.join(PODCAST_DIR, str(episode_id))
        progress.step("Recording the voices", f"{len(lines)} lines")
        recorded, total, error = record_episode(episode_id)
        progress.step("Rendering the cover art")
        cover = render_weekly_cover(selected_model, page['players'].get('offense') or {}, episode_dir)
        conn = database.get_db_connection()
        conn.execute("UPDATE podcast_episodes SET cover_image = ? WHERE episode_id = ?", (cover, episode_id))
        conn.commit()
        conn.close()
    finally:
        progress.finish()
    prune_episodes()
    return {"episodes": query_episodes(), "warning": None if recorded == total else recording_warning(recorded, total, error)}

def query_episodes():
    conn = database.get_db_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM podcast_episodes ORDER BY episode_id DESC").fetchall()]
    conn.close()
    teams = league.query_teams()
    for r in rows:
        r['hosts'] = json.loads(r.pop('hosts_json'))
        r['script'] = json.loads(r.pop('script_json'))
        r['game'] = json.loads(r.pop('game_json'))
        r['game'].pop('facts', None)
        for t in r['game']['teams']:
            row = teams.get(t.get('team_id'))
            t['logo'] = media.logo_url(row['short_name']) if row else None
            t['color'] = row['color'] if row else None
    return rows

def prune_episodes():
    """Keeps the newest episode plus ARCHIVE_SIZE earlier ones, deleting older episodes with their audio and art."""
    conn = database.get_db_connection()
    ids = [r['episode_id'] for r in conn.execute("SELECT episode_id FROM podcast_episodes ORDER BY episode_id DESC").fetchall()]
    conn.close()
    for episode_id in ids[ARCHIVE_SIZE + 1:]:
        delete_episode(episode_id)

def delete_episode(episode_id):
    """Removes an episode with its audio and cover art."""
    conn = database.get_db_connection()
    row = conn.execute("SELECT cover_image FROM podcast_episodes WHERE episode_id = ?", (episode_id,)).fetchone()
    if row:
        if row['cover_image'] and os.path.exists(os.path.join(database.STATIC_DIR, row['cover_image'])):
            os.remove(os.path.join(database.STATIC_DIR, row['cover_image']))
        shutil.rmtree(os.path.join(PODCAST_DIR, str(int(episode_id))), ignore_errors=True)
        conn.execute("DELETE FROM podcast_episodes WHERE episode_id = ?", (episode_id,))
        conn.commit()
    conn.close()

# Auto-initialize when podcast.py gets imported
initialize_podcast_tables()
