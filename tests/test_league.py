"""League queries the pages rely on."""
import json
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import league


class PlayerGames(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_player_games")
        conn.executemany("INSERT INTO league_player_games (player_id, game_id, week, stats_json) VALUES (?, ?, ?, ?)",
                         [("a", 1, 1, json.dumps({"PASSYARDS": 200})), ("a", 2, 2, json.dumps({"PASSYARDS": 150})),
                          ("b", 1, 1, json.dumps({"RUSHYARDS": 80})), ("c", 3, 3, json.dumps({"RUSHYARDS": 20}))])
        conn.commit()
        conn.close()

    def ids(self, **filters):
        return sorted((r['player_id'], r['week']) for r in league.query_player_games(**filters))

    def test_filters(self):
        self.assertEqual(len(self.ids()), 4)
        self.assertEqual(self.ids(player_ids=["a"]), [("a", 1), ("a", 2)])
        self.assertEqual(self.ids(player_ids={"a", "b"}, through_week=1), [("a", 1), ("b", 1)])
        self.assertEqual(self.ids(week=3), [("c", 3)])
        self.assertEqual(self.ids(player_ids=[]), [])

    def test_stats_decoded(self):
        self.assertEqual(league.query_player_games(player_ids=["b"])[0]['stats'], {"RUSHYARDS": 80})


if __name__ == "__main__":
    unittest.main()
