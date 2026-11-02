"""Player profiles: our players, other teams' players and All-America picks with no stat lines; plus a syntax check
of the save reader (a broken reader silently stops every sync)."""
import json
import os
import shutil
import subprocess
import unittest

from tests import APP_DIR
import database
import league
import players
import roster


def execute(sql, rows):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


class Profiles(unittest.TestCase):
    def setUp(self):
        for table in ("league_teams", "league_games", "league_players", "league_player_games", "league_season_awards",
                      "league_awards", "league_heisman", "storylines", "storyline_chapters"):
            execute(f"DELETE FROM {table}", [()])
        conn = roster.get_connection()
        conn.execute("DELETE FROM team_roster")
        conn.execute("DELETE FROM player_game_stats")
        conn.commit()
        conn.close()
        self.addCleanup(lambda: execute("DELETE FROM team_roster", [()]))  # other tests read names from the roster

        execute("INSERT INTO league_teams (team_id, name, short_name, is_user, conference) VALUES (?, ?, ?, ?, ?)",
                [(1, "Wyoming", "WYO", 1, "MW"), (2, "Hawaii", "HAW", 0, "MW"), (3, "Army", "ARMY", 0, "American")])
        execute("INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played, home_score, away_score) VALUES (?, ?, 'RegularSeason', ?, ?, 1, ?, ?)",
                [(10, 1, 2, 1, 17, 31), (11, 2, 1, 2, 24, 18)])
        execute("INSERT INTO league_players (player_id, name, position, class_year, jersey, team_id, hometown, home_state, stars) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [("p:1", "Samuel Harris", "HB", "Freshman", 1, 1, "Cibolo", "Texas", 3),
                 ("p:2", "Pofele Ashlock", "WR", "Senior", 5, 2, "Kahuku", "Hawaii", 2)])
        execute("INSERT INTO league_player_games (player_id, game_id, week, stats_json) VALUES (?, ?, ?, ?)",
                [("p:2", 10, 1, json.dumps({"RECEIVECATCHES": 7, "RECEIVEYARDS": 88, "RECEIVETDS": 1})),
                 ("p:2", 11, 2, json.dumps({"RECEIVECATCHES": 5, "RECEIVEYARDS": 60}))])
        execute("INSERT INTO league_awards (award_type, week, player_id, team_id) VALUES (?, ?, ?, ?)",
                [("Offensive_Player_of_Week_Conf", 1, "p:2", 2)])
        execute("INSERT INTO league_season_awards (award_type, position, conference, team_id, player_id, name, jersey, class_year) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [("ALL_AM_1ST_PRE_CONF", "LT", "American", 3, "p:3", "Henry Appleton", 58, "Junior")])
        conn = roster.get_connection()
        conn.execute("""INSERT INTO team_roster (player_id, save_id, player_name, position, jersey_num, health_status, depth_slot, overall,
                                                 class_year, height_in, weight_lb, hometown, home_state, stars, dev_trait)
                        VALUES (500, 'p:1', 'Samuel Harris', 'HB', 1, 'Healthy', 'HB1', 82, 'Freshman', 71, 196, 'Cibolo', 'Texas', 3, 'College_Impact')""")
        conn.executemany("INSERT INTO player_game_stats (save_id, week_num, stats_json) VALUES (?, ?, ?)",
                         [("p:1", 1, json.dumps({"RUSHATTEMPTS": 17, "RUSHYARDS": 75, "RUSHTDS": 2})),
                          ("p:1", 2, json.dumps({"RUSHATTEMPTS": 9, "RUSHYARDS": 125, "RUSHTDS": 1}))])
        conn.commit()
        conn.close()
        execute("INSERT INTO storylines (storyline_type, title, premise, player_id, status, start_week) VALUES (?, ?, ?, ?, ?, ?)",
                [("battle", "Hubbard Hunts Harris", "A backup closes in.", 500, "active", 2)])

    def test_our_player(self):
        p = players.build_profile("p:1")
        self.assertTrue(p['ours'])
        self.assertEqual((p['hometown'], p['recruit'], p['team']['name']), ("Cibolo, Texas", "Three-star recruit", "Wyoming"))
        self.assertEqual([(g['week'], g['venue'], g['outcome'], g['score']) for g in p['games']], [(2, "vs", "W", "24-18"), (1, "@", "W", "31-17")])
        self.assertEqual(p['boxes'][1], {"label": "Rush Yds", "value": 200})
        facts = {f['label']: f['value'] for f in p['facts']}
        self.assertEqual((facts['Height'], facts['Development'], facts['Depth chart']), ("5'11\"", "Impact", "HB1"))
        self.assertEqual([(s['title'], s['status'], s['text']) for s in p['storylines']], [("Hubbard Hunts Harris", "Ongoing", "A backup closes in.")])

    def test_other_teams_player(self):
        p = players.build_profile("p:2")
        self.assertFalse(p['ours'])
        self.assertEqual(p['season_line'], "12 rec, 148 rec yds, 1 TD")
        self.assertEqual(p['honors'], ["Conference Offensive Player of the Week, Week 1"])
        self.assertEqual((p['facts'], p['storylines'], p['photos']), ([], [], []))

    def test_pick_without_stat_lines(self):
        p = players.build_profile("p:3")
        self.assertEqual((p['name'], p['team']['name'], p['games']), ("Henry Appleton", "Army", []))
        self.assertEqual(p['honors'], ["Preseason All-American Athletic, First Team (LT)"])

    def test_unknown_player(self):
        self.assertIsNone(players.build_profile("nobody"))

    def test_route(self):
        from app import app
        client = app.test_client()
        self.assertEqual(client.get("/player/p:2", headers={"Host": "127.0.0.1:5000"}).get_json()['name'], "Pofele Ashlock")
        self.assertEqual(client.get("/player/nobody", headers={"Host": "127.0.0.1:5000"}).status_code, 404)


@unittest.skipUnless(shutil.which("node"), "needs Node.js")
class SaveReader(unittest.TestCase):
    def test_reader_parses(self):
        result = subprocess.run(["node", "--check", os.path.join(APP_DIR, "save_reader", "read_dynasty.mjs")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
