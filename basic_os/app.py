import datetime
import re
import database
import ai_engine
import roster
import storylines
import recap
import save_sync
import league
import media
import team
import team_page
import scouting
import recruiting
import timeline
import progress
import gameplan
import coaches
import events
import podcast
import backups
import awards
import offseason
import players
import rivals
import presser
import history
import printing
import games
import care
import care_messages
import care_incidents
import group_chat
import os
from urllib.parse import urlsplit
from flask import Flask, Response, render_template, request, jsonify, send_from_directory, abort, url_for

app = Flask(__name__)
# Screenshots for the podcast arrive as base64 images; nothing legitimate comes close to this
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024

# ---------- Local-only hardening ----------
# The app only listens on this PC, but any website open in your browser can still send requests to localhost.
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "img-src 'self' data: blob:",  # blob: lets the podcast uploader read a chosen screenshot before cropping it
    "media-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "script-src 'self'",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])

def host_name(value):
    return (urlsplit(f"//{value}").hostname or "") if value else ""

@app.before_request
def only_local_requests():
    # A page on another site can point its own domain name at 127.0.0.1 ("DNS rebinding") to read this app;
    # its requests then carry that foreign name in the Host header.
    if host_name(request.host) not in LOCAL_HOSTS:
        abort(403)
    # Other sites can't trigger generation, uploads or deletes: the browser names the page a change came from
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin and host_name(urlsplit(origin).netloc) not in LOCAL_HOSTS:
            abort(403)

@app.after_request
def security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if response.status_code == 200 and request.path.startswith("/static/"):
        if request.args.get("v"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # the address changes with the file
        elif request.path.startswith(UNIQUE_NAMES):
            response.headers["Cache-Control"] = "public, max-age=604800"
    return response

# Browser caching for static files: stylesheets and the main script carry ?v=<last changed> in their address, so they
# can be kept until they change. Generated photos and podcast audio never reuse a name, so they keep for a week.
# (Scripts imported by main.js keep revalidating: their import addresses can't carry a version.)
UNIQUE_NAMES = ("/static/generated/", "/static/podcasts/")

@app.url_defaults
def static_version(endpoint, values):
    if endpoint == "static" and "filename" in values and "v" not in values:
        path = os.path.join(app.static_folder, values["filename"])
        if os.path.exists(path):
            values["v"] = int(os.path.getmtime(path))

def spaced(value):
    """'LightBreeze' -> 'Light breeze'"""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value or "").capitalize()

def with_byes(schedule):
    """Our schedule rows with a {'week_id', 'bye'} row for each bye week, in week order."""
    byes = [{"week_id": week, "bye": True} for week in league.bye_weeks([g['week_id'] for g in schedule])]
    return sorted(schedule + byes, key=lambda g: g['week_id'])

def our_game_ids():
    """{week: league game id} for our played games, so schedule rows can open their box score."""
    row = league.query_user_team()
    return {g['week']: g['game_id'] for g in league.query_team_games(row['team_id']) if g['played']} if row else {}

def describe_game(game):
    """Adds display text (date, kickoff, venue, forecast) to a schedule row."""
    if not game:
        return game
    g = dict(game)
    g['date_text'] = ""
    if g.get('game_date'):
        g['date_text'] = datetime.date.fromisoformat(g['game_date']).strftime("%a, %b %d").replace(" 0", " ")
    g['kickoff_text'] = ""
    if g.get('kickoff_minutes') is not None:
        hours, minutes = divmod(g['kickoff_minutes'], 60)
        g['kickoff_text'] = f"{(hours - 1) % 12 + 1}:{minutes:02d} {'AM' if hours < 12 else 'PM'}"
    g['venue'] = ai_engine.game_venue(g)
    if g.get('site') == 'Neutral':
        g['venue'] = "Neutral site"
    elif g.get('site') == 'Away':
        g['venue'] = f"Away at {g['venue']}"
    g['weather_text'] = spaced(g.get('weather'))
    g['wind_text'] = spaced(g.get('wind'))
    opponent = team_media(g.get('opponent_name'))
    g['opponent_logo'] = opponent['logo']
    g['opponent_id'] = opponent['id']
    g['opponent_staff'] = opponent['staff']
    return g

def team_media(name):
    """A team's id, logo and coaching staff, by schedule or school name."""
    row = league.query_team_by_name(name)
    return {"id": row['team_id'] if row else None, "logo": media.logo_url(row['short_name']) if row else None, "staff": team.staff(row)}

def user_team_view():
    """Our team: names, logo, colours and stadium (team.py) plus the coaching staff."""
    return {**team.user_team(), "staff": team.staff(league.query_user_team())}

def season_year(schedule):
    """The season's year, from the first dated game on the schedule (the save's calendar)."""
    dates = [g['game_date'] for g in schedule if g.get('game_date')]
    return min(dates)[:4] if dates else str(datetime.date.today().year)

@app.route('/')
def home():
    sync_status = save_sync.sync_if_changed()
    storylines.check_depth_changes()
    active_game = database.query_active_week()
    last_game = database.query_last_played_week()
    # The stored status names the week the save was on when it last synced; show the week the schedule is on now
    sync_status = re.sub(r"\s*·\s*Week \d+\s*$", "", sync_status or "")
    if active_game:
        sync_status += f" · Week {active_game['week_id']}" if sync_status else f"Week {active_game['week_id']}"
    wins, losses = database.query_season_record()
    schedule = database.query_full_schedule()
    depth_chart = roster.query_depth_chart(last_game['week_id'] if last_game else None)
    positions = [(pos, roster.POSITION_NAMES.get(pos, pos)) for pos in roster.DEPTH_CHART_ORDER
                 if any(p['position'] == pos for p in depth_chart)]

    return render_template(
        'index.html',
        backup_auto_keep=backups.AUTO_KEEP,
        awards_page=awards.build_awards(),
        offseason_page=offseason.build_offseason(),
        rival_page=rivals.build_page(),
        presser_page=presser.build_page(),
        history_page=history.build_page(),
        game=describe_game(active_game),
        last_game=describe_game(last_game),
        record=f"{wins}-{losses}",
        us=user_team_view(),
        scouting=scouting.build_scouting(active_game),
        leaders=roster.query_season_leaders(),
        recruiting=recruiting.build_recruiting_page(),
        timeline=timeline.build_timeline(),
        coach_plan=gameplan.build_plan(active_game['week_id']) if active_game else None,
        plan_weeks=gameplan.plan_weeks(),
        coach_news=coaches.build_news(),
        podcast_episodes=podcast.query_episodes(),
        event_uploads=events.list_uploads(),
        event_draft=events.query_draft(),
        schedule=with_byes([describe_game(g) for g in schedule]),
        our_game_ids=our_game_ids(),
        season_year=season_year(schedule),
        past_stories=database.query_archived_stories(),
        tweets=database.query_active_tweets(active_game['week_id']) if active_game else [],
        injuries=roster.query_injury_report(),
        depth_chart=depth_chart,
        positions=positions,
        storylines=storylines.query_storylines(),
        off_field=care_incidents.locker_room(),
        recap_weeks=recap.available_weeks(),
        recap=recap.build_recap(recap.default_week()) if recap.default_week() is not None else None,
        sync_status=sync_status,
        scoreboard=recap.scoreboard()
    )

@app.route('/portraits/<kind>/<path:file_name>')
def portrait(kind, file_name):
    """Serves portraits straight from the SMG portrait packs (send_from_directory blocks path tricks)."""
    if kind not in media.PORTRAIT_DIRS:
        abort(404)
    return send_from_directory(media.PORTRAIT_DIRS[kind], file_name, max_age=86400)

@app.route('/team/<int:team_id>')
def team_detail(team_id):
    page = team_page.build_team_page(team_id)
    return jsonify(page) if page else (jsonify({"error": "Unknown team"}), 404)

@app.route('/game/<int:game_id>')
def game_box_score(game_id):
    game = games.build_game(game_id)
    return jsonify(game) if game else (jsonify({"error": "That game hasn't been played yet."}), 404)

@app.route('/player/<player_id>')
def player_profile(player_id):
    profile = players.build_profile(player_id)
    return jsonify(profile) if profile else (jsonify({"error": "No player with that id."}), 404)

# ---------- Printable issue ----------

@app.route('/print')
def print_issue():
    week = request.args.get('week', type=int)  # one week, or the whole season without it
    entries = [e for e in timeline.build_timeline() if week is None or e['week'] == week]
    wins, losses = database.query_season_record()
    return render_template('print.html', us=user_team_view(), entries=entries, week=week, record=f"{wins}-{losses}",
                           season_year=season_year(database.query_full_schedule()))

@app.route('/print.pdf')
def print_pdf():
    week = request.args.get('week', type=int)
    us = team.user_team()
    year = season_year(database.query_full_schedule())
    try:
        pdf = printing.render_pdf(url_for('print_issue', week=week, _external=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    name = re.sub(r"[^A-Za-z0-9]+", "-", f"{us['name']} {year} {'Week ' + str(week) if week is not None else 'Season'}").strip("-")
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})

@app.route('/recap/<int:week>')
def weekly_recap(week):
    return jsonify(recap.build_recap(week))

@app.route('/generate', methods=['POST'])
def generate_lore():
    selected_model = request.json.get('model', 'gemma3:12b')
    progress.start()
    try:
        progress.step("Syncing the save")
        save_sync.sync_if_changed()
        # Advance storylines first so this week's article and tweets can reference them
        storylines.check_depth_changes()
        progress.step("Writing storyline chapters")
        storylines.advance_storylines(selected_model)
        progress.step("Checking recruiting commits")
        recruiting.create_commit_storylines(selected_model)
        active_game = database.query_active_week()
        progress.step("Scouting the opponent")
        scouting_card = scouting.build_scouting(active_game)
        preview = scouting.generate_preview(selected_model, active_game) if active_game else None
        story_text = ai_engine.generate_dynasty_content(selected_model, storylines.build_storyline_context(),
                                                        storylines.build_player_impact_lines(), storylines.build_storyline_titles(),
                                                        scouting.scouting_context(scouting_card))
    except Exception as e:
        # A failure reads as one (the status line and the finish notice), with nothing half-saved shown as new
        return jsonify({"error": str(e)}), 500
    finally:
        progress.finish()
    return jsonify({
        "text": story_text,
        "past_stories": database.query_archived_stories(),
        "tweets": database.query_active_tweets(active_game['week_id']) if active_game else [],
        "storylines": storylines.query_storylines(),
        "scouting_preview": preview
    })

@app.route('/coaches/plan/<int:week>')
def coach_plan(week):
    plan = gameplan.build_plan(week)
    return jsonify(plan) if plan else (jsonify({"error": "No opponent data for that week yet."}), 404)

@app.route('/coaches/plan/<int:week>/generate', methods=['POST'])
def generate_coach_plan(week):
    try:
        return jsonify(gameplan.generate_plan(request.json.get('model', 'gemma3:12b'), week))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/phone/chat')
def phone_chat():
    return jsonify(group_chat.poll(request.args.get('model'), int(request.args.get('since') or 0)))

@app.route('/phone/chat/<action>', methods=['POST'])
def phone_chat_action(action):
    body = request.json or {}
    try:
        if action == "send":
            return jsonify(group_chat.send(body.get('text'), body.get('model') or 'gemma3:12b'))
        if action == "read":
            group_chat.mark_read()
            return jsonify({"ok": True})
        if action == "react":
            return jsonify(group_chat.react(int(body.get('msg_id') or 0), body.get('emoji')))
        if action == "regenerate":
            return jsonify({"started": group_chat.start_postgame(body.get('model') or 'gemma3:12b', force=True)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    abort(404)

@app.route('/coaches/news/generate', methods=['POST'])
def generate_coach_news():
    try:
        return jsonify(coaches.generate_news(request.json.get('model', 'gemma3:12b')))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/events/uploads', methods=['GET', 'POST', 'DELETE'])
def event_uploads():
    if request.method == 'POST':
        try:
            events.save_upload(request.json.get('full'), request.json.get('summary'), request.json.get('name'))
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    elif request.method == 'DELETE':
        events.clear_uploads()
        events.clear_draft()
    return jsonify(events.list_uploads())

@app.route('/events/uploads/<file_name>', methods=['GET', 'DELETE'])
def event_upload_file(file_name):
    if request.method == 'DELETE':
        events.delete_upload(file_name)
        return jsonify(events.list_uploads())
    path = events.upload_path(file_name)
    if not path:
        abort(404)
    return send_from_directory(events.UPLOAD_DIR, file_name)

@app.route('/events/read', methods=['POST'])
def read_event_screenshots():
    try:
        return jsonify(events.read_uploads(request.json.get('model')))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/podcast/save-games')
def podcast_save_games():
    return jsonify(events.saved_games())

@app.route('/events/read-save', methods=['POST'])
def read_save_scoring():
    try:
        return jsonify(events.draft_from_save(int(request.json.get('game_id'))))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/podcast/voices')
def podcast_voices():
    try:
        return jsonify({"voices": podcast.list_voices(), "defaults": podcast.DEFAULT_HOSTS})
    except Exception as e:
        return jsonify({"voices": [], "defaults": podcast.DEFAULT_HOSTS, "error": str(e)})

@app.route('/podcast/preview')
def podcast_preview():
    try:
        return jsonify({"audio": url_for('static', filename=podcast.preview(request.args.get('voice'), request.args.get('name')))})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/podcast/generate', methods=['POST'])
def generate_podcast():
    try:
        return jsonify(podcast.generate_episode(request.json.get('model', 'gemma3:12b'), request.json.get('draft'), request.json.get('hosts')))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/podcast/weekly/generate', methods=['POST'])
def generate_weekly_podcast():
    try:
        return jsonify(podcast.generate_weekly_episode(request.json.get('model', 'gemma3:12b'), request.json.get('week'), request.json.get('hosts')))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/podcast/<int:episode_id>/episode.mp3')
def podcast_episode_audio(episode_id):
    import io
    from flask import send_file
    audio = podcast.episode_audio(episode_id)
    if audio is None:
        abort(404)
    return send_file(io.BytesIO(audio), mimetype="audio/mpeg", download_name=f"between-the-numbers-{episode_id}.mp3", conditional=True)

@app.route('/podcast/<int:episode_id>/record', methods=['POST'])
def retry_podcast_recording(episode_id):
    try:
        return jsonify(podcast.retry_recording(episode_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/podcast/<int:episode_id>', methods=['DELETE'])
def delete_podcast(episode_id):
    podcast.delete_episode(episode_id)
    return jsonify(podcast.query_episodes())

@app.route('/generate/progress')
def generate_progress():
    return jsonify(progress.snapshot())

@app.route('/storylines', methods=['POST'])
def new_storyline():
    selected_model = request.json.get('model', 'gemma3:12b')
    try:
        storylines.create_storyline(selected_model)
    except Exception as e:
        return jsonify({"error": str(e), "storylines": storylines.query_storylines()})
    return jsonify({"storylines": storylines.query_storylines()})

@app.route('/storylines/from-game', methods=['POST'])
def storylines_from_game():
    selected_model = request.json.get('model', 'gemma3:12b')
    try:
        created = storylines.create_storylines_from_game(selected_model)
    except Exception as e:
        return jsonify({"error": str(e), "storylines": storylines.query_storylines()})
    return jsonify({"message": f"Started {created} new storyline{'s' if created != 1 else ''}.", "storylines": storylines.query_storylines()})

@app.route('/storylines/<int:storyline_id>/resolve', methods=['POST'])
def resolve_storyline(storyline_id):
    selected_model = request.json.get('model', 'gemma3:12b')
    try:
        storylines.resolve_storyline(storyline_id, request.json.get('action'), selected_model)
    except Exception as e:
        return jsonify({"error": str(e), "storylines": storylines.query_storylines()})
    return jsonify({"storylines": storylines.query_storylines()})

@app.route('/awards/all-america/<name>')
def all_conference_teams(name):
    group = awards.conference_teams(name)
    return jsonify(group) if group else (jsonify({"error": "No All-Conference teams for that conference."}), 404)

@app.route('/awards/heisman/generate', methods=['POST'])
def generate_heisman_column():
    try:
        return jsonify({"column": awards.generate_heisman_column(request.json.get('model', 'gemma3:12b'))})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/offseason/signing-day/generate', methods=['POST'])
def generate_signing_day():
    try:
        return jsonify({"column": offseason.generate_signing_day(request.json.get('model', 'gemma3:12b'))})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/rivals/issue/generate', methods=['POST'])
def generate_rivalry_issue():
    try:
        return jsonify({"column": rivals.generate_issue(request.json.get('model', 'gemma3:12b'))})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/presser', methods=['GET', 'POST', 'DELETE'])
def press_conference():
    try:
        if request.method == 'POST':
            return jsonify({"transcript": presser.ask(request.json.get('model', 'gemma3:12b'), request.json.get('role'), request.json.get('question'))})
        if request.method == 'DELETE':
            presser.clear_week()
        return jsonify({"transcript": presser.transcript()})
    except Exception as e:
        return jsonify({"error": str(e), "transcript": presser.transcript()}), 400

@app.route('/presser/questions', methods=['POST'])
def press_questions():
    try:
        return jsonify({"questions": presser.suggest_questions(request.json.get('model', 'gemma3:12b'))})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ---------- Player care ----------

@app.route('/care')
def care_dashboard():
    return jsonify(care.dashboard())

@app.route('/care/unread')
def care_unread():
    texts, emails = care_messages.unread()
    return jsonify({"texts": texts, "emails": emails, "incidents": care_messages.open_incident_count()})

@app.route('/care/<action>', methods=['POST'])
def care_action(action):
    body = request.json or {}
    try:
        if action == "act":
            return jsonify(care.act(body.get('save_id'), body.get('action'), body.get('need'), body.get('captain')))
        if action == "council":
            return jsonify(care.set_council(body.get('save_id'), bool(body.get('on'))))
        if action == "mentor":
            return jsonify(care.set_mentor(body.get('mentee'), body.get('mentor') or None))
        if action == "preset":
            return jsonify(care.set_preset(body.get('preset')))
        if action == "reply":
            return jsonify(care_messages.reply(int(body.get('message_id') or 0), body.get('choice')))
        if action == "reply_text":
            return jsonify(care_messages.reply_text(int(body.get('message_id') or 0), body.get('text'), body.get('model') or 'gemma3:12b'))
        if action == "email":
            return jsonify(care_messages.email_action(int(body.get('email_id') or 0), body.get('action')))
        if action == "incident":
            return jsonify(care_incidents.respond(int(body.get('incident_id') or 0), body.get('response')))
        if action == "simulate":
            return jsonify({policy: care.simulate(int(body.get('weeks') or 12), policy, body.get('preset')) for policy in ("ignore", "care")})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    abort(404)

# ---------- Backups ----------

@app.route('/backups', methods=['GET', 'POST'])
def backup_list():
    if request.method == 'POST':
        try:
            backups.create_backup((request.json or {}).get('label') or "")
        except Exception as e:
            return jsonify({"error": str(e), "backups": backups.list_backups()}), 400
    return jsonify({"backups": backups.list_backups()})

@app.route('/backups/upload', methods=['POST'])
def backup_upload():
    try:
        backups.save_upload(request.get_data())
    except Exception as e:
        return jsonify({"error": str(e), "backups": backups.list_backups()}), 400
    return jsonify({"backups": backups.list_backups()})

@app.route('/backups/<file_name>', methods=['GET', 'DELETE'])
def backup_file(file_name):
    try:
        backups.backup_path(file_name)
    except ValueError:
        abort(404)
    if request.method == 'DELETE':
        backups.delete_backup(file_name)
        return jsonify({"backups": backups.list_backups()})
    data, download_name = backups.download(file_name)
    return Response(data, mimetype="application/x-sqlite3", headers={"Content-Disposition": f'attachment; filename="{download_name}"'})

@app.route('/backups/<file_name>/restore', methods=['POST'])
def backup_restore(file_name):
    try:
        safety = backups.restore_backup(file_name)
    except Exception as e:
        return jsonify({"error": str(e), "backups": backups.list_backups()}), 400
    return jsonify({"restored": file_name, "safety": safety, "backups": backups.list_backups()})

if __name__ == '__main__':
    import housekeeping
    for step, count in housekeeping.run().items():
        print(f"Housekeeping: {count} {step}")
    # Debug mode (auto-reload and Werkzeug's in-browser debugger) is for development only: set BASIC_OS_DEBUG=1
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("BASIC_OS_DEBUG") == "1")
