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

# Weekly podcast: two hosts break down a game from the scoring-summary screenshots (read by events.py) plus the save's
# stats: the numbers, where each team shined and where it can be better, the season so far and the next opponent.
# The script is written by the AI and voiced with Microsoft's neural voices (edge-tts), one audio file per line.

PODCAST_DIR = os.path.join(database.STATIC_DIR, "podcasts")
DEFAULT_HOSTS = [{"name": "Andrew", "voice": "en-US-AndrewNeural", "role": "lead host who lives in the numbers"},
                 {"name": "Ava", "voice": "en-US-AvaNeural", "role": "color analyst with strong opinions on effort and execution"}]
VOICE_LOCALES = ("en-US", "en-GB", "en-AU", "en-CA")
TTS_WORKERS = 4
TTS_ATTEMPTS = 5
COVER_SIZE = (1024, 1024)
TARGET_LINES = 30

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
    file_name = f"{voice}_{re.sub(r'[^A-Za-z]', '', name)}.mp3"
    path = os.path.join(folder, file_name)
    if not os.path.exists(path):
        asyncio.run(edge_tts.Communicate(f"Hey everybody, I'm {name}. Let's break down this week's game by the numbers.", voice, rate="+4%").save(path))
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
                "Every player is a man; use he/him. Use only the facts given: never invent stats, injuries, quotes or plays.")

def segments(ours, theirs):
    """The show's running order: (what the segment covers, fact topics it may use, how many lines)."""
    return [
        ("a quick cold open and welcome that teases the final score and the biggest play", ("result", "us_good"), 3),
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

def is_repeat(text, lines):
    """True when a line says (nearly) the same thing as one already in the script."""
    import difflib
    key = re.sub(r"[^a-z0-9 ]", "", text.lower())
    return any(difflib.SequenceMatcher(None, key, re.sub(r"[^a-z0-9 ]", "", l['text'].lower())).ratio() > 0.8 for l in lines)

def write_script(selected_model, hosts, ours, theirs, week, facts):
    """Writes the show one segment at a time (small models write short, repetitive scripts when asked for it all at once)."""
    import ai_engine
    a, b = hosts
    us_name, them_name = spoken_names(ours['name']), spoken_names(theirs['name'])
    show = (f"You write a two-host college football podcast about {us_name}'s Week {week} game against {them_name} "
            f"(final: {us_name} {ours['final']}, {them_name} {theirs['final']}). "
            f"Host 0 is {a['name']}, the {a['role']}. Host 1 is {b['name']}, the {b['role']}. They are friends: they banter, "
            "disagree a little, ask each other questions and build on each other's points. Lines are short and conversational, "
            f"and the show is family friendly. {SPOKEN_RULES}")
    lines, title, summary = [], None, None
    for index, (topic, fact_topics, count) in enumerate(segments(us_name, them_name)):
        segment_facts = " ".join(text for t, text in facts if t in fact_topics) or "No extra facts: keep it general and don't invent any."
        first_host = index % 2
        covered = "; ".join(seg[0] for seg in segments(us_name, them_name)[:index]) or "nothing yet (this opens the show)"
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
                    text = " ".join(re.split(r"(?<=[.!?])\s+", text)[:MAX_LINE_SENTENCES])
                    text = re.sub(r"\.{2,}$", ".", text)
                    if text and not is_repeat(text, lines + new_lines):
                        new_lines.append({"host": 1 if line.get('host') in (1, "1", b['name']) else 0, "text": text})
            if new_lines:
                lines.extend(new_lines)
                if index == 0:
                    title = ai_engine.strip_tags(str(data.get('title') or "")) or None
                    summary = ai_engine.strip_tags(str(data.get('summary') or "")) or None
                break
    if len(lines) < 10:
        raise RuntimeError("The model didn't return a usable podcast script. Try again.")
    return title or f"Week {week}: {us_name} vs {them_name}", summary or "", lines

def speakable(text):
    """Cleans a line for text-to-speech: no stage directions, scores read as 'X to Y', abbreviations spelled out."""
    text = re.sub(r"\*[^*]*\*|\([^)]*(laugh|music|pause|sigh|chuckle)[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d+)\s*-\s*(\d+)", r"\1 to \2", text)
    text = re.sub(r"\bYd\b|\byds\b", "yards", text, flags=re.IGNORECASE)
    text = re.sub(r"\bQ([1-4])\b", lambda m: ["first", "second", "third", "fourth"][int(m.group(1)) - 1] + " quarter", text)
    return re.sub(r"\s{2,}", " ", text).strip()

# ---------- Audio ----------

def voice_lines(episode_dir, lines, hosts):
    """Synthesizes every line (a few at a time) and joins them into one episode file. Returns the episode file name."""
    import edge_tts
    os.makedirs(episode_dir, exist_ok=True)

    async def synth_all():
        gate = asyncio.Semaphore(TTS_WORKERS)
        async def one(index, line):
            async with gate:
                path = os.path.join(episode_dir, f"line_{index:03d}.mp3")
                for attempt in range(TTS_ATTEMPTS):
                    try:
                        await edge_tts.Communicate(line['text'], hosts[line['host']]['voice'], rate="+4%").save(path)
                        return
                    except Exception:
                        await asyncio.sleep(2 * (attempt + 1))  # the service sometimes drops requests for a few seconds
                raise RuntimeError("Microsoft's voice service didn't answer. Check the internet connection and try again.")
        await asyncio.gather(*(one(i, line) for i, line in enumerate(lines)))
    asyncio.run(synth_all())

    # MP3 frames from the same voice service share one format, so the files join end to end
    with open(os.path.join(episode_dir, "episode.mp3"), "wb") as out:
        for index in range(len(lines)):
            with open(os.path.join(episode_dir, f"line_{index:03d}.mp3"), "rb") as part:
                out.write(part.read())
    return "episode.mp3"

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

def render_cover(selected_model, ours, theirs, plays, episode_dir):
    import ai_engine, image_engine
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
        us = team.user_team()
        if player:
            prompt = ai_engine.player_photo_prompt(f"{scene}, dramatic stadium lighting. No text, letters or captions anywhere in the image.", {"position": player['position'], "jersey_num": player['jersey']}, us)
        else:
            prompt = ai_engine.PHOTO_STYLE.format(photo=f"The {us['full_name']} celebrating a win over the {theirs['name']}. No text, letters or captions anywhere in the image.", team=us['full_name'], colors=us['colors'])
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
        try:
            audio_file = voice_lines(episode_dir, lines, hosts)
        except Exception:
            delete_episode(episode_id)  # don't leave a half-made episode; the screenshots stay so it can be retried
            raise
        for index, line in enumerate(lines):
            line['audio'] = f"podcasts/{episode_id}/line_{index:03d}.mp3"
        progress.step("Rendering the cover art")
        cover = render_cover(selected_model, ours, theirs, draft['plays'], episode_dir)

        conn = database.get_db_connection()
        conn.execute("UPDATE podcast_episodes SET script_json = ?, audio_file = ?, cover_image = ? WHERE episode_id = ?",
                     (json.dumps(lines), f"podcasts/{episode_id}/{audio_file}", cover, episode_id))
        conn.commit()
        conn.close()
    finally:
        progress.finish()
    events.clear_uploads()
    events.clear_draft()
    return query_episodes()

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
