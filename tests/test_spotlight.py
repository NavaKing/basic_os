"""Spotlight week: one player becomes the topic of everything generated that week, from a fact sheet built from the
save plus the week's news, and the spotlight ends by itself when the save moves to the next game week."""
import json
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import league  # noqa: F401
import save_sync
import spotlight


class Spotlight(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        for table in ("league_teams", "league_players", "league_player_games", "schedule_tracking"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO league_teams (team_id, name, nickname, short_name, is_user, staff_json) VALUES (?, ?, ?, ?, ?, ?)",
                         [(142, "Wyoming", "Cowboys", "WYO", 1, "{}"),
                          (112, "Texas", "Longhorns", "TEX", 0, json.dumps({"oc": {"name": "Kyle Flood"}}))])
        conn.executemany("INSERT INTO league_players (player_id, name, position, class_year, jersey, team_id, hometown, home_state, stars) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [("1:1", "Arch Manning", "QB", "Junior", 16, 112, "New Orleans", "Louisiana", 5),
                          ("1:2", "Arch Manning", "QB", "Freshman", 4, 142, "Laramie", "Wyoming", 2)])
        conn.executemany("INSERT INTO league_player_games (player_id, game_id, week, stats_json) VALUES (?, ?, ?, ?)",
                         [("1:1", 1, 1, json.dumps({"PASSYARDS": 300, "PASSTDS": 3})), ("1:1", 2, 2, json.dumps({"PASSYARDS": 386, "PASSTDS": 4}))])
        conn.execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played) VALUES (18, 'Ohio State Buckeyes', 0)")
        conn.commit()
        conn.close()
        save_sync.set_state('spotlight', "null")

    def tearDown(self):
        save_sync.set_state('spotlight', "null")

    def test_nothing_without_a_spotlight(self):
        self.assertEqual(spotlight.context("feed"), "")

    def test_his_fact_sheet_and_the_news_reach_every_writer(self):
        self.assertEqual(spotlight.find("arch manning")['player_id'], "1:1")    # the 5-star, not the namesake
        spotlight.start("1:1", "He returns to Texas instead of entering the NFL Draft, to keep playing for OC Kyle Flood.")
        text = spotlight.context("feed")
        for fact in ("Texas Longhorns QB (No. 16)", "686 passing yards, 7 passing touchdowns in 2 games", "Week 2, 386 passing yards",
                     "offensive coordinator Kyle Flood", "NFL Draft", "doesn't play for Wyoming"):
            self.assertIn(fact, text)
        for audience in ("dispatch", "chat", "presser", "podcast"):
            self.assertIn("SPOTLIGHT WEEK on Arch Manning", spotlight.context(audience))

    def test_it_ends_when_the_week_does(self):
        spotlight.start("1:1")
        conn = database.get_db_connection()
        conn.execute("UPDATE schedule_tracking SET is_played = 1")
        conn.execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played) VALUES (19, 'Miami Hurricanes', 0)")
        conn.commit()
        conn.close()
        self.assertFalse(spotlight.status()['active'])

    def test_the_route(self):
        from app import app
        client = app.test_client()
        self.assertEqual(client.post("/spotlight", json={"name": "Nobody Here"}).status_code, 400)
        self.assertEqual(client.post("/spotlight", json={"name": "Arch Manning", "news": "Staying."}).get_json()['name'], "Arch Manning")
        self.assertFalse(client.delete("/spotlight").get_json()['active'])


if __name__ == "__main__":
    unittest.main()
