"""Game-day boosts: tiers from care, Bronze perks rolled to fit the position (never one he has), only into empty slots,
last week's taken back out with the original values, and nothing written while the game is open."""
import os
import random
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import care
import care_incidents  # noqa: F401  (creates its tables)
import care_messages  # noqa: F401
import game_day
import league  # noqa: F401
from tests.test_care import player, tuning


def slots(*names):
    return [{"slot": i + 1, "name": n, "rank": "Bronze" if n != "None" else "None"} for i, n in enumerate(names)]


class Rules(unittest.TestCase):
    def setUp(self):
        self.t = care.load_tuning()['game_day']

    def test_tiers_from_needs_trust_and_morale(self):
        fine = {n: 80 for n in care.NEEDS}
        self.assertEqual(game_day.tier(player(needs=fine, trust=80), {}, self.t), "excellent")
        self.assertEqual(game_day.tier(player(needs={**fine, "academics": 62}, trust=45), {}, self.t), "great")
        self.assertEqual(game_day.tier(player(needs={**fine, "academics": 50}, trust=35), {}, self.t), "good")
        self.assertIsNone(game_day.tier(player(needs={**fine, "morale": 60}, trust=80), {}, self.t))     # not riding high
        self.assertEqual(game_day.tier(player(needs={**fine, "focus": 20}, trust=20), {}, self.t), "cold")
        # On a playoff run a low home life doesn't hold anyone back
        self.assertEqual(game_day.tier(player(needs={**fine, "home": 30}, trust=80), {"playoff_alive": True}, self.t), "excellent")

    def test_perks_fit_the_position_skip_what_he_has_and_fill_only_empty_slots(self):
        lineman = {"position": "LT", "mentals": slots("ClearHeaded", "None", "None")}
        for i in range(30):
            perks = game_day.roll_perks(lineman, 3, "Home", random.Random(i))
            self.assertEqual([s for s, _ in perks], [2, 3])                      # two empty slots, so two at most
            names = {a for _, a in perks}
            self.assertNotIn("ClearHeaded", names)                               # he already has it: rerolled
            self.assertNotIn("RoadFanFavorite", names)                           # a home game
            self.assertTrue(names <= set(game_day.perk_pool("LT", "Home")))
        self.assertIn("OLRally", game_day.perk_pool("LT", "Home"))
        self.assertNotIn("FieldGeneral", game_day.perk_pool("LT", "Home"))
        self.assertIn("RoadFanFavorite", game_day.perk_pool("QB", "Neutral"))   # a neutral site is a road crowd
        full = {"position": "QB", "mentals": slots("WinningTime", "Headstrong", "TheNatural")}
        self.assertEqual(game_day.roll_perks(full, 3, "Away", random.Random(1)), [])


class Stored(unittest.TestCase):
    def setUp(self):
        import database, roster
        conn = database.get_db_connection()
        for table in ("care_state", "care_players", "care_warnings", "care_log", "care_council", "care_messages", "care_emails",
                      "care_incidents", "schedule_tracking", "team_roster", "league_bowls"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site, game_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(1, "Utah Utes", 1, 31, 10, "Home", "2026-09-05"), (2, "Utah State Aggies", 0, None, None, "Away", "2026-09-12")])
        conn.commit()
        conn.close()
        conn = roster.get_connection()
        conn.executemany("INSERT INTO team_roster (save_id, player_name, position, health_status, overall, class_year) VALUES (?, ?, ?, 'Healthy', 80, 'Senior')",
                         [("4255:1", "Hot Back", "HB"), ("4255:2", "Hot Tackle", "LT"), ("4255:3", "Hot Corner", "CB")])
        conn.commit()
        conn.close()
        care.advance(2)
        game_day.execute("DELETE FROM boost_runs")
        game_day.execute("DELETE FROM boost_changes")
        players = care.load_players()
        for p in players:
            p['needs'] = {n: 85 for n in care.NEEDS}
            p['trust'] = 80
        care.save_players(players, int(care.get_state("week")))
        self.dir = tempfile.mkdtemp()
        self.save = os.path.join(self.dir, "DYNASTY-TEST")
        open(self.save, "wb").write(b"save")
        self.patches = [mock.patch.object(game_day.save_sync, "SAVE_FILE", self.save),
                        mock.patch.object(game_day, "SAVE_BACKUPS", os.path.join(self.dir, "backups")),
                        mock.patch.object(game_day, "game_running", return_value=False)]
        for p in self.patches:
            p.start()
        self.written = []
        # A stand-in for the save: the writer reports what each field held, then takes the new values
        self.fields = {}
        def write(path, changes):
            before = {}
            for c in changes:
                row = c['row']
                before[row] = {f: self.fields.get((row, f), "None" if "Mental" in f else "Neutral") for f in c['set']}
                for f, v in c['set'].items():
                    if c.get('onlyIf') and f in c['onlyIf'] and self.fields.get((row, f)) != c['onlyIf'][f]:
                        continue
                    self.fields[(row, f)] = v
            self.written.append(changes)
            return before
        self.patches.append(mock.patch.object(game_day, "write", side_effect=write))
        self.patches[-1].start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_apply_twice_then_remove_restores_the_originals(self):
        self.fields[(1, "StartingHotCold")] = "Cold"   # what the game had for one of them
        status = game_day.apply(seed=1)
        self.assertTrue(status['players'])
        hot = {k: v for k, v in self.fields.items() if k[1] == "StartingHotCold"}
        self.assertTrue(all(v == "Hot" for v in hot.values()))
        game_day.apply(seed=2)                       # next week: last week's out, this week's in
        game_day.remove()
        self.assertEqual(self.fields[(1, "StartingHotCold")], "Cold")                # back to the game's own value
        self.assertTrue(all(v in ("Neutral", "None") for k, v in self.fields.items() if k != (1, "StartingHotCold")))
        self.assertEqual(game_day.last_run()['status'], "removed")

    def test_nothing_is_written_while_the_game_is_open(self):
        with mock.patch.object(game_day, "game_running", return_value=True):
            with self.assertRaises(ValueError):
                game_day.apply(seed=1)
        self.assertEqual(self.written, [])

    def test_a_backup_comes_first_and_undo_restores_it(self):
        game_day.apply(seed=1)
        backups = os.listdir(os.path.join(self.dir, "backups"))
        self.assertEqual(len(backups), 1)
        open(self.save, "wb").write(b"changed by the writer")
        game_day.undo()
        self.assertEqual(open(self.save, "rb").read(), b"save")
        self.assertEqual(game_day.last_run()['status'], "undone")


if __name__ == "__main__":
    unittest.main()
