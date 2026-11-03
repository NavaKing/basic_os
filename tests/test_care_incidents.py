"""Off-field incidents: real players only ever get blameless incidents, neglect raises the odds, the coach's response
changes needs and trust, and only public, catalog wording reaches the writers."""
import random
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import care
import care_incidents
import database
import roster
from tests.test_care import player, tuning


class Rules(unittest.TestCase):
    def test_real_players_never_get_a_scandal(self):
        t = tuning()
        real = player(portrait="/static/portraits/players/nilpp_Unique_DoeJohn_1.webp", needs={n: 5 for n in care.NEEDS})
        generated = player(portrait="/static/portraits/players/nilpp_Generic_1955_P_T0095_D_1_2.webp", needs={n: 5 for n in care.NEEDS})
        unknown = player(portrait=None)
        picks = {key: {care_incidents.pick_incident(p, random.Random(i), t)['key'] for i in range(400)}
                 for key, p in (("real", real), ("generated", generated), ("unknown", unknown))}
        scandals = {i['key'] for i in care_incidents.INCIDENTS if i['scandal']}
        self.assertFalse(picks['real'] & scandals)
        self.assertFalse(picks['unknown'] & scandals)   # no face on file counts as real: the safe default
        self.assertTrue(picks['generated'] & scandals)

    def test_neglect_and_warnings_raise_the_odds_trust_and_counseling_lower_them(self):
        t = tuning()
        fine = care_incidents.incident_chance(player(), {}, t)
        empty = care_incidents.incident_chance(player(needs={**player()['needs'], "focus": 10}), {}, t)
        warned = care_incidents.incident_chance(player(warnings=[{"need": "focus", "text": "x"}]), {}, t)
        self.assertGreater(empty, fine * 5)
        self.assertGreater(warned, fine * 2)
        self.assertLess(care_incidents.incident_chance(player(trust=90), {}, t), fine)
        self.assertLess(care_incidents.incident_chance(player(), {}, t, counseled=True), fine)

    def test_blameless_incidents_cant_be_punished(self):
        t = tuning()
        self.assertNotIn("suspend", care_incidents.allowed_responses(care_incidents.BY_KEY['family'], t))
        self.assertNotIn("discipline", care_incidents.allowed_responses(care_incidents.BY_KEY['car'], t))
        self.assertIn("suspend", care_incidents.allowed_responses(care_incidents.BY_KEY['dui'], t))


def always():
    """load_tuning with an incident certain every week (for driving the stored flow)."""
    t = care.load_tuning()
    t['incidents'] = {**t['incidents'], "base_chance": 1.0, "max_chance": 1.0}
    return lambda: t


class Stored(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        for table in ("care_state", "care_players", "care_warnings", "care_log", "care_council", "care_mentors", "care_messages",
                      "care_emails", "care_incidents", "schedule_tracking", "team_roster"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site, game_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(1, "Utah Utes", 1, 31, 10, "Home", "2026-09-05"), (2, "Utah State Aggies", 0, None, None, "Away", "2026-09-12")])
        conn.commit()
        conn.close()
        conn = roster.get_connection()
        conn.execute("INSERT INTO team_roster (save_id, player_name, position, health_status, overall, class_year, home_state, portrait_file) "
                     "VALUES ('wr1', 'Wide Receiver', 'WR', 'Healthy', 75, 'Junior', 'Colorado', 'nilpp_Unique_ReceiverWide_1.webp')")
        conn.commit()
        conn.close()

    def tearDown(self):
        # Later test modules (the podcast, the press room) would otherwise pick these up as this week's off-field news
        care_incidents.execute("DELETE FROM care_incidents")
        care_incidents.execute("DELETE FROM care_state")

    def test_an_incident_then_a_response(self):
        care.advance(2)
        with mock.patch.object(care, "load_tuning", always()):
            care.advance(3)
        d = care.dashboard()
        self.assertEqual(len(d['incidents']), 1)
        incident = d['incidents'][0]
        self.assertFalse(care_incidents.BY_KEY[[i['key'] for i in care_incidents.INCIDENTS if i['title'] == incident['title']][0]]['scandal'])
        self.assertEqual(d['unread']['incidents'], 1)
        trust = care.load_players()[0]['trust']
        d = care_incidents.respond(incident['incident_id'], "support")
        self.assertEqual(d['incidents'], [])
        self.assertEqual(care.load_players()[0]['trust'], trust + care.load_tuning()['incidents']['responses']['support']['trust'])
        self.assertEqual(d['hours'], d['hours_total'] - 2)
        with self.assertRaises(ValueError):
            care_incidents.respond(incident['incident_id'], "support")
        lines = care_incidents.story_lines()
        self.assertEqual(len(lines), 1)
        self.assertIn("WR Wide Receiver", lines[0])
        self.assertIn("full support", lines[0])
        self.assertIn("never add details", care_incidents.prompt_context())
        panel = care_incidents.locker_room()
        self.assertEqual(panel['incidents'][0]['status'], "handled")

    def test_no_response_costs_trust_and_quiet_stays_out_of_the_press(self):
        care.advance(2)
        with mock.patch.object(care, "load_tuning", always()):
            care.advance(3)
        trust = care.load_players()[0]['trust']
        care_incidents.execute("DELETE FROM care_messages")   # he texted too; only the incident's penalty is measured here
        care.advance(4)   # ignored
        self.assertEqual(care.load_players()[0]['trust'], trust - care.load_tuning()['incidents']['unanswered_trust'])
        self.assertIn("have not commented", care_incidents.story_lines()[0])
        with mock.patch.object(care, "load_tuning", always()):
            care.advance(5)
        newest = care.dashboard()['incidents'][0]
        care_incidents.respond(newest['incident_id'], "protect")
        self.assertEqual(care_incidents.story_lines(), [])   # week 3's is old news now, and week 5's is kept quiet


if __name__ == "__main__":
    unittest.main()
