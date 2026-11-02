import league
import media
import recap
import roster
import team

# Everything shown when a team's logo is clicked: record, staff, schedule, top players and poll history.

TOP_PLAYERS = 6

def season_totals(rows):
    """{player_id: summed stats} across the season (longest plays and the game rating aren't summed)."""
    totals = {}
    for row in rows:
        bucket = totals.setdefault(row['player_id'], {})
        for key, value in row['stats'].items():
            if key == 'GAMERATING' or 'LONGEST' in key:
                bucket[key] = max(bucket.get(key, 0), value)
            else:
                bucket[key] = bucket.get(key, 0) + value
    return totals

def schedule_rows(team_id, teams, polls_by_week):
    rows, wins, losses = [], 0, 0
    for g in league.query_team_games(team_id):
        home = g['home_id'] == team_id
        opponent = teams.get(g['away_id'] if home else g['home_id'])
        if not opponent:
            continue
        row = {"week": g['week'], "venue": "vs" if home else "@",
               "opponent": recap.team_view(opponent, polls_by_week.get(g['week'] - 1, {}).get(opponent['team_id'])),
               "result": None, "score": None}
        if g['played']:
            outcome, mine, theirs, _, _ = recap.side_result(g, team_id)
            row.update(result=outcome, score=f"{mine}-{theirs}")
            wins += outcome == 'W'
            losses += outcome == 'L'
        rows.append(row)
    return rows, wins, losses

def top_players(team_id):
    players = league.query_players()
    totals = season_totals(league.query_team_player_games(team_id))
    ranked = sorted(totals.items(), key=lambda item: recap.production_score(item[1]), reverse=True)[:TOP_PLAYERS]
    return [{"name": players[pid]['name'], "position": players[pid]['position'], "class": recap.class_label(players[pid]),
             "jersey": players[pid]['jersey'], "portrait": media.portrait_url("player", players[pid].get('portrait_file')),
             "line": roster.format_stat_line(stats),
             "boxes": [{"label": label, "value": value} for label, value in recap.stat_boxes(stats)]}
            for pid, stats in ranked if pid in players]

def build_team_page(team_id):
    row = league.query_team(team_id)
    if not row:
        return None
    teams = league.query_teams()
    polls = league.query_team_polls(team_id)
    # Every captured poll, so opponents show the rank they held going into each game
    polls_by_week = {week: league.query_poll(week) for week, _ in polls}
    games, wins, losses = schedule_rows(team_id, teams, polls_by_week)
    current_rank = next((rank for _, rank in reversed(polls) if rank), None) if polls else None
    return {
        **team.team_details(row),
        "color": row['color'], "color2": row.get('color2'),
        "record": f"{wins}-{losses}",
        "rank": current_rank if current_rank and current_rank <= recap.TOP_25 else None,
        "staff": team.staff(row),
        "schedule": games,
        "players": top_players(team_id),
        "polls": [{"week": week, "rank": rank if rank and rank <= recap.TOP_25 else None} for week, rank in polls],
        "is_user": bool(row.get('is_user')),
    }
