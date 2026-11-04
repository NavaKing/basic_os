"""The coach's career: a job change is noticed at the next sync, his old school's seasons and big games go with him
(they don't become the new school's lore), and the writers bring up his past while he's new, when he faces an old
school, and only now and then after that."""
import random
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import care  # noqa: F401  (creates care_state)
import care_messages  # noqa: F401  (creates care_emails)
import career
import database
import history  # noqa: F401  (creates history_games)
import league
import lore


def schedule(conn, games):
    conn.execute("DELETE FROM schedule_tracking")
    conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score) VALUES (?, ?, ?, ?, ?)", games)


def coach_at(conn, team_id):
    conn.execute("UPDATE league_teams SET is_user = CASE WHEN team_id = ? THEN 1 ELSE 0 END", (team_id,))


class Career(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        for table in ("league_teams", "schedule_tracking", "care_state", "history_games", "league_bowls", "coach_career", "coach_moves",
                      "care_emails", "program_seasons"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO league_teams (team_id, name, nickname, short_name, is_user, conference, staff_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(142, "Wyoming", "Cowboys", "WYO", 1, "MW", '{"hc": {"name": "Jay Sawvel"}}'),
                          (200, "Texas", "Longhorns", "TEX", 0, "SEC", '{"hc": {"name": "Jay Sawvel"}}')])
        schedule(conn, [(1, "Utah Utes", 1, 31, 10), (2, "UNLV Rebels", 1, 28, 21), (15, "UNLV Rebels", 1, 31, 24)])
        conn.execute("INSERT INTO care_state (state_key, state_value) VALUES ('title_game_2026', '15')")
        conn.execute("INSERT INTO history_games (season_year, week, opponent_name, our_score, their_score) VALUES (2026, 15, 'UNLV Rebels', 31, 24)")
        conn.commit()
        conn.close()

    def tearDown(self):
        conn = database.get_db_connection()
        for table in ("league_teams", "schedule_tracking", "care_state", "history_games", "coach_career", "coach_moves", "care_emails"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()

    def move_to_texas(self, played_by_someone_else=True):
        career.record(2026, 16)                       # his season at Wyoming
        conn = database.get_db_connection()
        coach_at(conn, 200)
        schedule(conn, [(1, "Rice Owls", 1, 45, 3), (2, "Ohio State Buckeyes", 1, 10, 24)] if played_by_someone_else else [])
        conn.commit()
        conn.close()
        return career.record(2026, 17)

    def test_his_season_is_recorded_with_its_big_games(self):
        self.assertIsNone(career.record(2026, 16))
        stop, = career.stints()
        self.assertEqual((stop['team'], stop['wins'], stop['losses']), ("Wyoming Cowboys", 3, 0))
        self.assertIn("2026", stop['highlights'][0])
        self.assertEqual(career.context(), "")       # nothing to bring up: he's never coached anywhere else

    def test_a_job_change_is_noticed_and_his_old_season_goes_with_him(self):
        move = self.move_to_texas()
        self.assertEqual(move, {"from": "Wyoming Cowboys", "to": "Texas Longhorns"})
        self.assertEqual([s['team'] for s in career.past_stops()], ["Wyoming Cowboys"])
        # Texas's 2026 season was someone else's: its record isn't his, and Wyoming's title game isn't Texas lore
        self.assertEqual(career.years_here(), [])
        self.assertEqual(lore.dynasty_title_games(), [])
        email = league.query_rows("SELECT * FROM care_emails")
        self.assertEqual(email[0]['subject'], "Welcome to Texas")
        self.assertIn("Wyoming Cowboys", email[0]['body'])
        self.assertIsNone(career.record(2026, 17))   # the next sync at Texas isn't another move

    def test_while_hes_new_his_past_always_comes_up(self):
        self.move_to_texas()
        text = career.context(rng=random.Random(0))
        self.assertIn("hired from Wyoming Cowboys", text)
        self.assertIn("went 3-0", text)
        self.assertIn("Championship Game", text)
        self.assertIn("just arrived from Wyoming Cowboys", career.context(audience="players"))

    def test_facing_an_old_school_is_a_big_story(self):
        self.move_to_texas()
        self.assertIn("huge storyline", career.context(opponent="Wyoming Cowboys"))
        self.assertIn("huge storyline", career.context(opponent="Wyoming"))
        self.assertNotIn("huge storyline", career.context(opponent="Rice Owls"))

    def test_later_on_it_only_comes_up_now_and_then(self):
        self.move_to_texas(played_by_someone_else=False)
        conn = database.get_db_connection()
        schedule(conn, [(w, "Rice Owls", 1, 30, 10) for w in range(1, 7)])
        conn.commit()
        conn.close()
        career.record(2026, 7)
        self.assertEqual(career.years_here(), [2026])                     # hired before the season: it's his
        self.assertEqual(career.context(rng=mock_rng(0.9)), "")           # most of the time, nothing
        self.assertIn("only if it fits", career.context(rng=mock_rng(0.1)))


def mock_rng(value):
    class Fixed:
        def random(self):
            return value
    return Fixed()


if __name__ == "__main__":
    unittest.main()
