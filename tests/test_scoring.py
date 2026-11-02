"""Scoring plays: reading them (screenshots or save), adding them up, and naming the scorer."""
import json
import os
import shutil
import unittest

from tests import REAL_DB, TEMP_DIR
import database
import events
import league
import roster


class ParsePlay(unittest.TestCase):
    def test_screenshot_touchdown_pass_with_kick(self):
        play = events.parse_play("Jackson Holman 1 Yd pass from Tyler Hughes (Erik Sandvik kick)")
        self.assertEqual(play, {"player": "Jackson Holman", "yards": 1, "kind": "pass", "passer": "Tyler Hughes", "points": 7})

    def test_screenshot_run_with_two_point_conversion(self):
        play = events.parse_play("Diore Hubbard 12 Yd run (two-point conversion)")
        self.assertEqual((play['kind'], play['points']), ("run", 8))

    def test_failed_kick_is_six(self):
        self.assertEqual(events.parse_play("Diore Hubbard 3 Yd run (kick failed)")['points'], 6)

    def test_screenshot_field_goal(self):
        play = events.parse_play("Erik Sandvik 42 Yd field goal")
        self.assertEqual((play['kind'], play['yards'], play['points']), ("field goal", 42, 3))

    def test_save_formats(self):
        self.assertEqual(events.parse_play("Field goal")['points'], 3)
        self.assertEqual(events.parse_play("Safety")['points'], 2)
        catch = events.parse_play("KJ Duff touchdown catch from AJ Surace (kick)")
        self.assertEqual((catch['player'], catch['kind'], catch['passer'], catch['points']), ("KJ Duff", "pass", "AJ Surace", 7))
        self.assertEqual(events.parse_play("Touchdown (kick)"), {"player": None, "yards": None, "kind": "touchdown", "passer": None, "points": 7})
        self.assertEqual(events.parse_play("Touchdown pass from AJ Surace (kick failed)")['points'], 6)

    def test_conversion_points(self):
        self.assertEqual([events.conversion_points(x) for x in ("kick", "kick failed", "two-point conversion", "2pt no good", None)], [1, 0, 2, 0, 0])


class Clock(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(events.clock_seconds("10:29"), 629)
        self.assertEqual(events.clock_text(629), "10:29")
        self.assertEqual(events.clock_text(-5), "0:00")
        self.assertIsNone(events.clock_seconds("--"))


class BuildDraft(unittest.TestCase):
    def plays(self):
        return [{"quarter": 1, "team": "IU", "text": "Field goal", "clock": "10:29"},
                {"quarter": 1, "team": "RU", "text": "Touchdown (kick)", "clock": "9:42"},
                {"quarter": 5, "team": "IU", "text": "Touchdown (kick)", "clock": "0:00"}]

    def test_quarters_and_overtime(self):
        teams = [{"abbr": "IU", "name": "Indiana"}, {"abbr": "RU", "name": "Rutgers"}]
        draft = events.build_draft(teams, self.plays(), {"IU": 10, "RU": 7})
        self.assertEqual(draft['teams'][0]['quarters'], [3, 0, 0, 0, 7])
        self.assertEqual(draft['teams'][1]['quarters'], [7, 0, 0, 0])
        self.assertEqual(draft['warnings'], [])

    def test_mismatch_warns(self):
        teams = [{"abbr": "IU", "name": "Indiana"}, {"abbr": "RU", "name": "Rutgers"}]
        draft = events.build_draft(teams, self.plays(), {"IU": 13, "RU": 7})
        self.assertEqual(len(draft['warnings']), 1)
        self.assertEqual(draft['teams'][0]['final'], 13)


class MergePlays(unittest.TestCase):
    def test_overlapping_screenshots_and_quarter_rollover(self):
        a = [{"quarter": 1, "team": "IU", "text": "Field goal", "clock": "10:29"},
             {"quarter": 1, "team": "RU", "text": "Touchdown (kick)", "clock": "2:00"}]
        # The second screenshot repeats the last play and lost its quarter heading (reads quarter 1)
        b = [{"quarter": 1, "team": "RU", "text": "Touchdown (kick)", "clock": "2:00"},
             {"quarter": 1, "team": "IU", "text": "Touchdown (kick)", "clock": "12:39"}]
        merged = events.merge_plays([a, b])
        self.assertEqual([(p['clock'], p['quarter']) for p in merged], [("10:29", 1), ("2:00", 1), ("12:39", 2)])


def snap(player_id, name, position, touchdowns, attempts=0):
    return {"playerId": player_id, "name": name, "position": position, "touchdowns": touchdowns, "attempts": attempts}


class ScorerText(unittest.TestCase):
    def test_catch_from_passer(self):
        before = {"home": [snap(1, "AJ Surace", "QB", 0, 10), snap(2, "KJ Duff", "WR", 0)]}
        after = {"home": [snap(1, "AJ Surace", "QB", 1, 14), snap(2, "KJ Duff", "WR", 1)]}
        self.assertEqual(events.scorer_text(after, before, "home", 7), "KJ Duff touchdown catch from AJ Surace (kick)")

    def test_run_and_unknown(self):
        after = {"away": [snap(3, "Tyler Cross", "RB", 1)]}
        self.assertEqual(events.scorer_text(after, None, "away", 6), "Tyler Cross touchdown run (kick failed)")
        self.assertEqual(events.scorer_text({"away": []}, None, "away", 8), "Touchdown (two-point conversion)")

    def test_lagging_snapshot_uses_next_score(self):
        row = {"home": [snap(2, "KJ Duff", "WR", 0)]}
        later = {"home": [snap(2, "KJ Duff", "WR", 1)]}
        self.assertEqual(events.scorer_text(row, row, "home", 7, later), "KJ Duff touchdown catch (kick)")

    def test_field_goal_and_safety(self):
        self.assertEqual(events.scorer_text({}, None, "home", 3), "Field goal")
        self.assertEqual(events.scorer_text({}, None, "home", 2), "Safety")


def save_row(quarter, seconds_left, home_before, away_before, home_after, away_after):
    return {"quarter": quarter, "secondsLeft": seconds_left, "homeBefore": home_before, "awayBefore": away_before,
            "homeAfter": home_after, "awayAfter": away_after, "home": [], "away": []}


class DraftFromSave(unittest.TestCase):
    """The save logs each score before its extra point; the point shows up in the next row's 'before' score."""

    def setUp(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_teams")
        conn.execute("DELETE FROM league_games")
        conn.execute("DELETE FROM game_scoring")
        conn.executemany("INSERT INTO league_teams (team_id, name, nickname, short_name) VALUES (?, ?, ?, ?)",
                         [(1, "Indiana", "Hoosiers", "IU"), (2, "Rutgers", "Scarlet Knights", "RU")])
        # Rutgers (home) 14, Indiana (away) 9
        conn.execute("INSERT INTO league_games (game_id, week, home_id, away_id, played, home_score, away_score) VALUES (77, 3, 2, 1, 1, 14, 9)")
        conn.commit()
        conn.close()

    def test_points_from_score_changes(self):
        plays = [save_row(1, 629, 0, 0, 0, 3),    # IU field goal
                 save_row(1, 582, 0, 3, 6, 3),    # RU touchdown; its kick shows in the next scoring row's 'before'
                 save_row(2, 900, 7, 3, 7, 3),    # no score change (end of a half): skipped
                 save_row(4, 120, 7, 3, 7, 9),    # IU touchdown, kick failed: the next row still starts at 9
                 save_row(4, 30, 7, 9, 13, 9)]    # RU touchdown; the kick only shows in the final, 14
        league.sync_scoring([{"homeId": 2, "awayId": 1, "homeScore": 14, "awayScore": 9, "plays": plays}])

        draft = events.draft_from_save(77)
        self.assertEqual([(p['team'], p['points'], p['clock']) for p in draft['plays']],
                         [("IU", 3, "10:29"), ("RU", 7, "9:42"), ("IU", 6, "2:00"), ("RU", 7, "0:30")])
        totals = {t['abbr']: t['total'] for t in draft['teams']}
        self.assertEqual(totals, {"IU": 9, "RU": 14})
        self.assertEqual(draft['warnings'], [])


@unittest.skipUnless(os.path.exists(REAL_DB), "needs a synced dynasty_data.db")
class RealSave(unittest.TestCase):
    """Every scoring summary captured from your save must add up to that game's final (run on a copy of the database)."""

    def setUp(self):
        self.original = database.DB_FILE, roster.DB_FILE
        copy = os.path.join(TEMP_DIR, "real_copy.db")
        shutil.copyfile(REAL_DB, copy)
        database.DB_FILE = roster.DB_FILE = copy

    def tearDown(self):
        database.DB_FILE, roster.DB_FILE = self.original

    def test_every_captured_game_adds_up(self):
        games = league.query_scoring_games()
        if not games:
            self.skipTest("no scoring summaries captured yet")
        for g in games:
            with self.subTest(game=g['game_id'], week=g['week']):
                draft = events.draft_from_save(g['game_id'])
                self.assertEqual(draft['warnings'], [])
                totals = sorted(t['total'] for t in draft['teams'])
                self.assertEqual(totals, sorted((g['home_score'], g['away_score'])))


if __name__ == "__main__":
    unittest.main()
