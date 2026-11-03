"""Player care: needs drain toward a stress-dependent level, warning signs come from low needs, the coach's hours fill
needs, and the leadership council, mentors and difficulty preset do what the tuning file says."""
import random
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import care
import database
import roster


def player(save_id="p1", **overrides):
    p = {"save_id": save_id, "name": "Test Player", "position": "WR", "class": "Freshman", "overall": 70, "portrait": None,
         "starter": False, "blocked": False, "injured": False, "traits": [], "dev": "Normal", "distance": 0,
         "confidence": 50, "hot_cold": "Neutral", "birthday_week": 1, "temperament": {n: 1.0 for n in care.NEEDS},
         "needs": {n: 70 for n in care.NEEDS}, "trust": 30, "warnings": []}
    p.update(overrides)
    return p


def tuning(preset="Normal"):
    t = care.load_tuning()
    return {**t, **t['presets'][preset], "preset": preset}


NO_RNG = lambda key: random.Random(key)


class Rules(unittest.TestCase):
    def test_stress_sinks_needs_and_calm_players_settle(self):
        t = tuning()
        calm, stressed = player("calm"), player("stressed", injured=True, starter=True, blocked=True, distance=2)
        for week in range(20):
            care.run_week([calm, stressed], {"week": week}, t, [], {}, NO_RNG)
        settle = t['staff_target'] - t['drain']['health'] / t['staff_rate'] * (1 - t['trust_drain_relief'] * 0.3)
        self.assertAlmostEqual(calm['needs']['health'], settle, delta=1)
        self.assertGreater(calm['needs']['health'], t['low_need'])
        self.assertLess(stressed['needs']['health'], t['low_need'])
        self.assertLess(stressed['needs']['home'], calm['needs']['home'])

    def test_warnings_come_from_low_needs(self):
        t = tuning()
        fine, low = player(), player(needs={**player()['needs'], "focus": 10, "morale": 10})
        self.assertLess(care.warning_chance(fine, {}, t), 0.01)
        self.assertGreater(care.warning_chance(low, {}, t), 0.15)
        trusting = player(needs=low['needs'], trust=100)
        self.assertLess(care.warning_chance(trusting, {}, t), care.warning_chance(low, {}, t))

    def test_actions_fill_needs_build_trust_and_clear_warnings(self):
        t = tuning()
        p = player(warnings=[{"need": "focus", "text": "x"}], birthday_week=40)
        text = care.apply_action(p, "sit_down", "morale", t, {"week_of_year": 40})
        self.assertEqual(p['needs']['morale'], 100)
        self.assertEqual(p['needs']['focus'], 80)   # the sit-down's focus bonus
        self.assertEqual(p['trust'], 30 + t['actions']['sit_down']['trust'] + t['birthday_trust_bonus'])
        self.assertEqual(p['warnings'], [])
        self.assertIn("Sit-down with Test Player", text)
        visit = player()
        care.apply_action(visit, "home_visit", "academics", t, {})
        self.assertEqual((visit['needs']['home'], visit['needs']['morale'], visit['needs']['academics']), (100, 100, 70))
        with self.assertRaises(ValueError):
            care.apply_action(player(), "bribe", "morale", t, {})

    def test_mentors_and_a_struggling_captain(self):
        t = tuning()
        good, mentee, alone = player("good", **{"class": "Senior"}), player("mentee"), player("alone")
        care.run_week([good, mentee, alone], {"week": 1}, t, [], {"mentee": "good"}, NO_RNG)
        self.assertGreater(mentee['needs']['morale'], alone['needs']['morale'])
        self.assertEqual(good['trust'], 30 + t['mentor']['mentor_trust_per_week'])
        captain, teammate = player("cap", needs={**player()['needs'], "morale": 5}), player("mate")
        events = care.run_week([captain, teammate], {"week": 1}, t, ["cap"], {}, NO_RNG)
        self.assertTrue(any(kind == "council" for _, kind, _ in events))
        self.assertLess(teammate['needs']['morale'], alone['needs']['morale'] - 1)

    def test_care_list_puts_the_neediest_first(self):
        t = {**tuning(), "care_list_size": 2}
        players = [player("ok"), player("low", needs={**player()['needs'], "home": 20}), player("warned", warnings=[{"need": "focus", "text": "x"}])]
        self.assertEqual(care.pick_care_list(players, {}, t, []), ["low", "warned"])


class Stored(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        for table in ("care_state", "care_players", "care_warnings", "care_log", "care_council", "care_mentors", "schedule_tracking", "team_roster"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site, game_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(1, "Utah Utes", 1, 31, 10, "Home", "2026-09-05"), (2, "Utah State Aggies", 0, None, None, "Away", "2026-09-12")])
        conn.commit()
        conn.close()
        conn = roster.get_connection()
        conn.executemany("INSERT INTO team_roster (save_id, player_name, position, health_status, overall, class_year, home_state) VALUES (?, ?, ?, 'Healthy', ?, ?, ?)",
                         [("qb1", "Senior Quarterback", "QB", 80, "Senior", "Wyoming"), ("qb2", "Young Quarterback", "QB", 66, "Freshman", "Texas"),
                          ("wr1", "Wide Receiver", "WR", 75, "Junior", "Colorado")])
        conn.commit()
        conn.close()

    def test_dashboard_actions_council_mentor_and_preset(self):
        d = care.dashboard()
        self.assertEqual((d['week'], d['hours'], d['hours_total']), (2, care.load_tuning()['hours'], care.load_tuning()['hours']))
        self.assertEqual({p['save_id'] for p in d['care_list']}, {"qb1", "qb2", "wr1"})
        with self.assertRaises(ValueError):
            care.act("qb2", "council", "focus")   # no captains yet
        d = care.set_council("qb1", True)
        self.assertEqual([p['save_id'] for p in d['council']], ["qb1"])
        d = care.act("qb2", "council", "focus")
        self.assertEqual(d['hours'], d['hours_total'] - 1)
        self.assertIn("via Senior Quarterback", d['log'][0]['text'])
        d = care.set_mentor("qb2", "qb1")
        self.assertEqual([(m['mentor']['name'], m['mentee']['name']) for m in d['mentors']], [("Senior Quarterback", "Young Quarterback")])
        with self.assertRaises(ValueError):
            care.set_mentor("qb2", "qb2")
        with self.assertRaises(ValueError):
            care.act("wr1", "bribe", "home")
        d = care.set_preset("Demanding")
        self.assertEqual((d['preset'], d['hours_total']), ("Demanding", care.load_tuning()['presets']['Demanding']['hours']))
        with self.assertRaises(ValueError):
            care.set_preset("Impossible")

    def test_advance_runs_missed_weeks_and_resets_hours(self):
        care.advance(2)
        care.act("wr1", "text", "morale")
        care.advance(4)
        d = care.dashboard()
        self.assertEqual((d['week'], d['hours']), (4, d['hours_total']))
        self.assertTrue(all(p['needs']['morale'] < 100 for p in d['care_list']))

    def test_routes_and_simulator(self):
        from app import app
        client = app.test_client()
        host = {"Host": "127.0.0.1:5000"}
        self.assertTrue(client.get("/care", headers=host).get_json()['started'])
        bad = client.post("/care/act", json={"save_id": "wr1", "action": "bribe", "need": "home"}, headers=host)
        self.assertEqual(bad.status_code, 400)
        sim = client.post("/care/simulate", json={"preset": "Normal", "weeks": 4}, headers=host).get_json()
        self.assertEqual((sim['ignore']['policy'], sim['care']['policy'], sim['care']['weeks']), ("ignore", "care", 4))
        self.assertGreaterEqual(sim['care']['average_need'], sim['ignore']['average_need'])
        self.assertEqual(client.post("/care/nope", json={}, headers=host).status_code, 404)


if __name__ == "__main__":
    unittest.main()
