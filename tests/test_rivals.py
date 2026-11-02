"""Rival watch: series and streak wording from the save's rivalry records, our meetings, and rivalry week."""
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import league
import rivals


def execute(sql, rows=((),)):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


class Wording(unittest.TestCase):
    def row(self, **kw):
        return {"our_wins": 53, "their_wins": 60, "streak_ours": 1, "streak_length": 2, "last_ours": 31, "last_theirs": 17, **kw}

    def test_texts(self):
        r = self.row()
        self.assertEqual(rivals.series_text(r, "Wyoming", "Colorado State"), "Colorado State leads the series 60-53")
        self.assertEqual(rivals.streak_text(r, "Wyoming", "Colorado State"), "Wyoming has won 2 straight")
        self.assertEqual(rivals.last_text(r, "Wyoming", "Colorado State"), "Last meeting: Wyoming 31, Colorado State 17")
        self.assertEqual(rivals.series_text(self.row(our_wins=10, their_wins=10), "A", "B"), "Series tied 10-10")
        self.assertEqual(rivals.streak_text(self.row(streak_ours=0, streak_length=1), "A", "B"), "B won the last meeting")

    def test_rival_without_history(self):
        r = {"our_wins": None, "their_wins": None, "streak_ours": None, "streak_length": None, "last_ours": None, "last_theirs": None}
        self.assertIsNone(rivals.series_text(r, "A", "B"))
        self.assertIsNone(rivals.streak_text(r, "A", "B"))
        self.assertIsNone(rivals.last_text(r, "A", "B"))


class Watch(unittest.TestCase):
    def setUp(self):
        for table in ("league_teams", "league_games", "league_rivalries", "schedule_tracking", "rivalry_columns"):
            execute(f"DELETE FROM {table}")
        execute("INSERT INTO league_teams (team_id, name, nickname, short_name, is_user) VALUES (?, ?, ?, ?, ?)",
                [(1, "Wyoming", "Cowboys", "WYO", 1), (2, "Colorado State", "Rams", "CSU", 0), (3, "Air Force", "Falcons", "AF", 0),
                 (4, "BYU", "Cougars", "BYU", 0)])
        execute("INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played, home_score, away_score) VALUES (?, ?, 'RegularSeason', ?, ?, ?, ?, ?)",
                [(1, 1, 2, 1, 1, 17, 31), (2, 2, 3, 4, 1, 28, 20), (3, 6, 1, 3, 0, None, None)])
        execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site) VALUES (?, ?, ?, ?, ?, ?)",
                [(1, "Colorado State Rams", 1, 31, 17, "Away"), (6, "Air Force Falcons", 0, None, None, "Home")])
        league.sync_rivalries([
            {"name": "The Border War", "opponentId": 2, "rank": 1, "ourWins": 53, "theirWins": 60, "streakOurs": True, "streakLength": 2, "lastOurs": 31, "lastTheirs": 17},
            {"name": "", "opponentId": 3, "rank": 2},
            {"name": "BYU/Wyoming Rivalry", "opponentId": 4, "rank": None, "ourWins": 30, "theirWins": 47, "streakOurs": False, "streakLength": 10},
        ])

    def test_watch(self):
        watch = rivals.build_rival_watch()
        self.assertEqual([r['team']['name'] for r in watch], ["Colorado State", "Air Force", "BYU"])  # named rivals first
        csu, af, byu = watch
        self.assertEqual((csu['meeting']['week'], csu['meeting']['venue'], csu['meeting']['result']), (1, "at", {"outcome": "W", "score": "31-17"}))
        self.assertEqual((af['name'], af['named'], af['series'], af['meeting']['next']), ("Air Force Rivalry", False, None, True))
        self.assertEqual(af['season']['record'], "1-0")
        self.assertIsNone(byu['meeting'])

    def test_rivalry_week(self):
        week = rivals.rivalry_week()
        self.assertEqual(week['team']['name'], "Air Force")
        context = rivals.prompt_context()
        self.assertIn("RIVALRY WEEK", context)
        self.assertIn("Air Force is one of Wyoming's rivals.", context)
        self.assertIn("Wyoming is 1-0 this season.", context)
        page = rivals.build_page()
        self.assertTrue(page['rivalry_week'])
        self.assertIsNone(page['column'])

    def test_normal_week(self):
        execute("UPDATE schedule_tracking SET week_id = 7 WHERE week_id = 6")
        execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, site) VALUES (6, 'Somebody Else', 0, 'Home')")
        self.assertIsNone(rivals.rivalry_week())
        self.assertEqual(rivals.prompt_context(), "")
        self.assertEqual(rivals.next_rival_game()['team']['name'], "Air Force")


if __name__ == "__main__":
    unittest.main()
