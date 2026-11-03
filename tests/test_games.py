"""Box scores: line score, team stats side by side, top performers and scoring plays for a played game."""
import json
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import events
import games

STATS = dict(FIRSTDOWNS=21, OFFYARDS=353, OFFPASSYARDS=87, PASSCOMPLETIONS=7, PASSATTEMPTS=26, PASSTDS=1, OFFRUSHYARDS=266, RUSHATTEMPTS=38,
             RUSHTDS=2, THIRDDOWNCONV=6, THIRDDOWNS=13, FOURTHDOWNCONV=0, FOURTHDOWNS=0, OFFREDZONETDS=2, OFFREDZONES=3, TAKEAWAYS=1,
             SACKS=3, PENALTIES=3, PENALTYYARDS=34, POSSESSIONTIME=966)


def execute(sql, rows=((),)):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


class BoxScore(unittest.TestCase):
    def setUp(self):
        for table in ("league_teams", "league_games", "league_players", "league_player_games", "game_scoring", "event_draft"):
            try:
                execute(f"DELETE FROM {table}")
            except Exception:
                pass
        execute("INSERT INTO league_teams (team_id, name, short_name) VALUES (?, ?, ?)", [(1, "Wyoming", "WYO"), (2, "Hawai'i", "HAW")])
        away = {**STATS, "OFFYARDS": 308, "OFFRUSHYARDS": 91, "TAKEAWAYS": 0, "POSSESSIONTIME": 954}
        execute("""INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played, home_score, away_score, home_quarters, away_quarters,
                                             home_stats_json, away_stats_json) VALUES (?, 4, 'RegularSeason', 1, 2, ?, ?, ?, ?, ?, ?, ?)""",
                [(606, 1, 24, 18, "[0, 7, 0, 17]", "[0, 3, 0, 15]", json.dumps(STATS), json.dumps(away)),
                 (700, 0, None, None, None, None, None, None)])
        execute("INSERT INTO league_players (player_id, name, position, team_id) VALUES (?, ?, ?, ?)",
                [("hb", "Samuel Harris", "HB", 1), ("lb", "Kona Moore", "LB", 2)])
        execute("INSERT INTO league_player_games (player_id, game_id, week, stats_json) VALUES (?, 606, 4, ?)",
                [("hb", json.dumps({"RUSHATTEMPTS": 19, "RUSHYARDS": 160, "RUSHTDS": 1})), ("lb", json.dumps({"DEFTACKLES": 7, "ASSDEFTACKLES": 4}))])

    def test_box_score(self):
        g = games.build_game(606)
        away, home = g['teams']
        self.assertEqual((away['team']['name'], away['total'], home['team']['name'], home['total'], home['won']), ("Hawai'i", 18, "Wyoming", 24, True))
        stats = {r['label']: r for r in g['stats']}
        self.assertEqual((stats['Rushing']['home'], stats['Rushing']['better']), ("38 car, 266 yds", "home"))
        self.assertEqual((stats['Turnovers']['away'], stats['Turnovers']['home'], stats['Turnovers']['better']), (1, 0, "home"))  # fewer is better
        self.assertEqual(stats['Possession']['home'], "16:06")
        self.assertEqual([(p['label'], p['name'], p['line']) for p in home['performers']], [("Rushing", "Samuel Harris", "19 car, 160 rush yds, 1 TD")])
        self.assertEqual([(p['label'], p['line']) for p in away['performers']], [("Tackles", "11 tkl")])
        self.assertIsNone(g['scoring'])  # no scoring summary captured for this game

    def test_unplayed_and_route(self):
        self.assertIsNone(games.build_game(700))
        from app import app
        client = app.test_client()
        self.assertEqual(client.get("/game/606", headers={"Host": "127.0.0.1:5000"}).get_json()['week'], 4)
        self.assertEqual(client.get("/game/700", headers={"Host": "127.0.0.1:5000"}).status_code, 404)

    def test_scoring_plays_without_touching_the_podcast_draft(self):
        execute("INSERT INTO game_scoring (game_id, week, plays_json, home_id, away_id) VALUES (606, 4, ?, 1, 2)",
                [(json.dumps([{"quarter": 2, "secondsLeft": 300, "homeBefore": 0, "homeAfter": 6, "awayBefore": 0, "awayAfter": 0, "home": [], "away": []}]),)])
        events.clear_draft()
        plays = games.build_game(606)['scoring']
        self.assertEqual([(p['quarter'], p['team'], p['clock']) for p in plays], [(2, "WYO", "5:00")])
        self.assertIsNone(events.query_draft())


class ByeWeeks(unittest.TestCase):
    def setUp(self):
        execute("DELETE FROM league_games")
        execute("INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played) VALUES (?, ?, ?, 1, 2, 0)",
                [(1, 13, "RegularSeason"), (2, 17, "BowlSeason1")])

    def test_gaps_inside_the_regular_season_only(self):
        import league
        self.assertEqual(league.bye_weeks([0, 1, 2, 3, 5, 6, 13]), [4, 7, 8, 9, 10, 11, 12])
        self.assertEqual(league.bye_weeks([1, 2, 13, 17]), list(range(3, 13)))  # no byes counted toward a bowl week
        self.assertEqual(league.bye_weeks([]), [])


if __name__ == "__main__":
    unittest.main()
