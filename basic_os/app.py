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
import os
from urllib.parse import urlsplit
from flask import Flask, render_template, request, jsonify, send_from_directory, abort, url_for

app = Flask(__name__)
# Screenshots for the podcast arrive as base64 images; nothing legitimate comes close to this
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024

# ---------- Local-only hardening ----------
# The app only listens on this PC, but any website open in your browser can still send requests to localhost.
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "img-src 'self' data:",
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
    return response

def spaced(value):
    """'LightBreeze' -> 'Light breeze'"""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value or "").capitalize()

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
        schedule=[describe_game(g) for g in schedule],
        season_year=season_year(schedule),
        past_stories=database.query_archived_stories(),
        tweets=database.query_active_tweets(active_game['week_id']) if active_game else [],
        injuries=roster.query_injury_report(),
        depth_chart=depth_chart,
        positions=positions,
        storylines=storylines.query_storylines(),
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
        return jsonify({"episodes": podcast.generate_episode(request.json.get('model', 'gemma3:12b'), request.json.get('draft'), request.json.get('hosts'))})
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

if __name__ == '__main__':
    # Debug mode (auto-reload and Werkzeug's in-browser debugger) is for development only: set BASIC_OS_DEBUG=1
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("BASIC_OS_DEBUG") == "1")
