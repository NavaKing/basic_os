"""Offseason tab: the phase label, the roster outlook's sources (app rules, then the game's odds, then its lists),
and coaching changes detected between syncs."""
import json
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import league
import offseason
import roster
import save_sync


def add_player(save_id, name, position, slot, overall, class_year, transfer=-1, go_pro=-1):
    conn = roster.get_connection()
    conn.execute("""INSERT INTO team_roster (save_id, player_name, position, jersey_num, health_status, depth_slot, overall, class_year,
                                             transfer_chance, go_pro_chance) VALUES (?, ?, ?, 1, 'Healthy', ?, ?, ?, ?, ?)""",
                 (save_id, name, position, slot, overall, class_year, transfer, go_pro))
    conn.commit()
    conn.close()


class Phase(unittest.TestCase):
    def label(self, **phase):
        save_sync.set_state('phase', json.dumps(phase))
        return offseason.phase()

    def test_labels(self):
        self.assertEqual(self.label(stage="NFLSeason", weekType="RegularSeason", week=5)['label'], "Regular season, Week 5")
        self.assertEqual(self.label(weekType="BowlSeason2")['label'], "Bowl season")
        off = self.label(stage="NFLOffseason", weekType="OffSeason", offseasonStage=3, offseasonStages=9, carousel=True, signing=True)
        self.assertEqual(off['label'], "Offseason, stage 3 of 9")
        self.assertTrue(off['offseason'] and off['signing'])
        self.assertEqual(off['windows'], ["Coaching carousel", "Signing period"])


def clear_roster():
    conn = roster.get_connection()
    conn.execute("DELETE FROM team_roster")
    conn.commit()
    conn.close()


class Outlook(unittest.TestCase):
    def setUp(self):
        clear_roster()
        self.addCleanup(clear_roster)  # other tests read player names from the roster (name casing)
        add_player("qb1", "Senior Starter", "QB", "QB1", 76, "Senior")
        add_player("hb1", "Freshman Star", "HB", "HB1", 82, "Freshman")
        add_player("hb2", "Blocked Back", "HB", "HB2", 81, "Sophomore")
        add_player("hb3", "Third Stringer", "HB", "HB3", 79, "Junior")   # not the first backup: never on the transfer watch
        add_player("wr1", "Junior Ace", "WR", "WR1", 84, "Junior")
        add_player("wr2", "Second Wideout", "WR", "WR2", 70, "Sophomore")
        add_player("wr3", "Third Wideout", "WR", "WR3", 69, "Junior")
        add_player("wr4", "Far Back", "WR", "WR4", 60, "Sophomore")

    def test_app_rules_in_season(self):
        o = offseason.outlook({})
        self.assertEqual([p['name'] for p in o['seniors']], ["Senior Starter"])
        self.assertEqual(o['draft_source'], "estimate")
        self.assertEqual([p['name'] for p in o['draft']], ["Junior Ace"])       # juniors only: the freshman isn't eligible
        self.assertEqual(o['transfer_source'], "estimate")
        self.assertEqual([p['name'] for p in o['transfer']], ["Blocked Back"])  # first backup within 3 of the starter
        self.assertEqual((o['starters'], o['returning_starters']), (5, 4))

    def test_game_odds_replace_the_rules(self):
        conn = roster.get_connection()
        conn.execute("UPDATE team_roster SET go_pro_chance = 0, transfer_chance = 0")
        conn.execute("UPDATE team_roster SET go_pro_chance = 35 WHERE save_id = 'wr1'")
        conn.execute("UPDATE team_roster SET transfer_chance = 60 WHERE save_id = 'wr4'")
        conn.commit()
        conn.close()
        o = offseason.outlook({})
        self.assertEqual((o['draft_source'], [p['note'] for p in o['draft']]), ("odds", ["35% chance he turns pro"]))
        self.assertEqual((o['transfer_source'], [p['name'] for p in o['transfer']]), ("odds", ["Far Back"]))

    def test_game_lists_win(self):
        o = offseason.outlook({"earlyDraft": ["hb1"], "transferCandidates": ["hb3", "unknown"]})
        self.assertEqual((o['draft_source'], [p['name'] for p in o['draft']]), ("game", ["Freshman Star"]))
        self.assertEqual((o['transfer_source'], [p['name'] for p in o['transfer']]), ("game", ["Third Stringer"]))
        self.assertEqual(o['returning_starters'], 3)  # the senior QB and the declared HB starter leave


def team(team_id, name, hc, oc="OC", dc="DC"):
    return {"id": team_id, "name": name, "nickname": "", "short": name[:3].upper(), "color": None, "mediaRank": None, "mediaLastRank": None,
            "staff": {"hc": {"name": hc}, "oc": {"name": oc}, "dc": {"name": dc}}}


class Carousel(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM coaching_changes")
        conn.execute("DELETE FROM league_teams")
        conn.commit()
        conn.close()

    def sync(self, *teams):
        league.sync_league({"userTeamId": 1, "teams": list(teams), "games": [], "players": [], "weeklyAwards": [], "heisman": []},
                           9, {"stage": "NFLSeason", "seasonYear": 2026})

    def test_changes_detected_between_syncs(self):
        self.sync(team(1, "Wyoming", "Jay Sawvel", oc="Marcus Chiu"), team(2, "Boise State", "Spencer Danielson"))
        self.assertEqual(league.query_coaching_changes(), [])  # the first sync has nothing to compare against
        self.sync(team(1, "Wyoming", "Jay Sawvel", oc="New Hire"), team(2, "Boise State", "Spencer Danielson", oc="Marcus Chiu"))
        moves = offseason.carousel()
        self.assertEqual(sorted((m['team']['name'], m['old'], m['new']) for m in moves),
                         [("Boise State", "OC", "Marcus Chiu"), ("Wyoming", "Marcus Chiu", "New Hire")])
        bsu = next(m for m in moves if m['team']['name'] == "Boise State")
        self.assertEqual((bsu['role'], bsu['from']['name'], bsu['when']), ("Offensive Coordinator", "Wyoming", "Week 9"))

    def test_staff_names_reads_both_shapes(self):
        self.assertEqual(league.staff_names({"staff_json": json.dumps({"hc": {"name": "A", "portrait": None}})}), {"hc": "A"})
        self.assertEqual(league.staff_names({"staff": {"hc": None, "oc": {"name": "B"}}}), {"oc": "B"})


if __name__ == "__main__":
    unittest.main()
