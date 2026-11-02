"""Dynasty history: the archive keeps past seasons after the save moves on, our players are measured against the school
record book, and dynasty bests and 'this week in history' come from the archive."""
import json
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import history
import league
import roster


def execute(sql, rows=((),)):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


def season_in_app(schedule, lines):
    """What the app holds after a sync: this season's schedule and stat lines only (the save has no older games)."""
    execute("DELETE FROM schedule_tracking")
    execute("DELETE FROM player_game_stats")
    execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site) VALUES (?, ?, 1, ?, ?, ?)", schedule)
    execute("INSERT INTO player_game_stats (save_id, week_num, stats_json) VALUES (?, ?, ?)", [(s, w, json.dumps(st)) for s, w, st in lines])


RECORDS = [{"scope": "game", "stat": "RushYards", "value": 302, "year": 1984, "name": "Kevin Lowe", "position": "RB"},
           {"scope": "season", "stat": "RushYards", "value": 1860, "year": 2016, "name": "Brian Hill", "position": "RB"},
           {"scope": "career", "stat": "RushYards", "value": 4287, "year": 2016, "name": "Brian Hill", "position": "RB"}]


class Archive(unittest.TestCase):
    def setUp(self):
        for table in ("history_games", "history_player_games", "program_records", "program_seasons"):
            execute(f"DELETE FROM {table}")
        conn = roster.get_connection()
        conn.execute("DELETE FROM team_roster")
        conn.execute("INSERT INTO team_roster (save_id, player_name, position, health_status, depth_slot) VALUES ('hb', 'Samuel Harris', 'HB', 'Healthy', 'HB1')")
        conn.commit()
        conn.close()
        self.addCleanup(lambda: execute("DELETE FROM team_roster"))

        # 2026: two games, then the save moves to 2027 and only holds 2027's first game
        season_in_app([(1, "Colorado State Rams", 31, 17, "Away"), (2, "FCS Midwest", 35, 21, "Home")],
                      [("hb", 1, {"RUSHYARDS": 75, "RUSHTDS": 2}), ("hb", 2, {"RUSHYARDS": 125})])
        history.sync({"phase": {"seasonYear": 2026}, "programRecords": RECORDS,
                      "programHistory": [{"year": 2026, "wins": 2, "losses": 0, "ties": 0, "confWins": 1, "confLosses": 0, "conference": "MW",
                                          "confStanding": 1, "finalRank": 22, "coach": "J. Sawvel", "bowls": ["Arizona_Bowl"]}]})
        season_in_app([(1, "Colorado State Rams", 14, 20, "Home")], [("hb", 1, {"RUSHYARDS": 310})])
        history.sync({"phase": {"seasonYear": 2027}, "programRecords": RECORDS, "programHistory": []})

    def test_past_season_survives(self):
        games = league.query_rows("SELECT season_year, week FROM history_games ORDER BY season_year, week")
        self.assertEqual([(g['season_year'], g['week']) for g in games], [(2026, 1), (2026, 2), (2027, 1)])
        self.assertEqual(history.current_season(), 2027)

    def test_record_book(self):
        rush = next(r for r in history.record_book() if r['label'] == "Rushing yards")
        game, season, career = rush['cells']
        self.assertEqual((game['ours']['value'], game['ours']['broken'], game['ours']['when']), (310, True, "2027, Week 1"))
        self.assertEqual((season['ours']['value'], season['ours']['pace'], season['ours']['pct']), (310, 3720, 17))
        self.assertTrue(season['ours']['on_pace'])
        self.assertEqual((career['ours']['value'], career['ours']['when']), (510, "dynasty career"))
        self.assertEqual(career['record']['name'], "Brian Hill")

    def test_seasons_and_bests(self):
        self.assertEqual(history.seasons(), [{"year": 2026, "record": "2-0", "conf": "1-0 MW", "standing": 1, "rank": 22, "coach": "J. Sawvel",
                                              "bowls": ["Arizona Bowl"]}])
        bests = history.dynasty_bests()
        team = {b['label']: (b['text'], b['when']) for b in bests['team']}
        self.assertEqual(team['Dynasty record'], ("2-1", "2 seasons"))
        self.assertEqual(team['Most points'], ("35-21 vs FCS Midwest", "2026, Week 2"))
        self.assertEqual(team['Longest winning streak'][0], "2 games")
        self.assertEqual(bests['performances'][0]['label'], "Rushing yards")

    def test_this_week_in_history(self):
        execute("DELETE FROM schedule_tracking")
        execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, site) VALUES (2, 'Somebody', 0, 'Home')")
        week = history.this_week()
        self.assertEqual(week['week'], 2)
        self.assertEqual(week['games'], [{"year": 2026, "opponent": "FCS Midwest", "site": "Home", "result": "W", "score": "35-21"}])


if __name__ == "__main__":
    unittest.main()
