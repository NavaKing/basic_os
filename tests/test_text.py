"""Cleanup of AI-written text: podcast lines, coach quotes, casing, colour names and recap math."""
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import ai_engine
import coaches
import database
import podcast
import recap
import team


class Speakable(unittest.TestCase):
    def test_scores_quarters_and_yards(self):
        self.assertEqual(podcast.speakable("Up 35-21 in Q4 after a 40 Yd run *laughs*"),
                         "Up 35 to 21 in fourth quarter after a 40 yards run")

    def test_stage_directions_removed(self):
        self.assertEqual(podcast.speakable("(pause) Big win.  (laughs) Really."), "Big win. Really.")

    def test_is_repeat(self):
        lines = [{"text": "Indiana outgained Rutgers four hundred to two hundred."}]
        self.assertTrue(podcast.is_repeat("Indiana outgained Rutgers, four hundred to two hundred!", lines))
        self.assertFalse(podcast.is_repeat("Next up is Iowa on the road.", lines))


class Welcome(unittest.TestCase):
    def test_names_hosts_and_both_teams(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_teams")
        conn.execute("INSERT INTO league_teams (team_id, name, nickname, short_name) VALUES (1, 'Indiana', 'Hoosiers', 'IU')")
        conn.commit()
        conn.close()
        hosts = [{"name": "Andrew"}, {"name": "Ava"}]
        line = podcast.welcome_line(hosts, {"name": "Indiana", "team_id": 1}, {"name": "Rutgers", "team_id": None})
        self.assertEqual(line, "Welcome to Between the Numbers, folks. I'm Andrew, and here with me is Ava. "
                               "Today we'll be talking about the Indiana Hoosiers and the Rutgers.")


class Quotes(unittest.TestCase):
    def test_clean_quote_drops_attribution_and_quote_marks(self):
        self.assertEqual(coaches.clean_quote('Coach Smith says, "We ran the ball well."'), "We ran the ball well.")
        self.assertEqual(coaches.clean_quote("We said we would win."), "We said we would win.")

    def test_tidy_quote_keeps_two_sentences(self):
        self.assertEqual(coaches.tidy_quote("One. Two! Three? Four."), "One. Two!")

    def test_banned_phrases(self):
        self.assertTrue(coaches.uses_banned("We just need to execute better."))
        self.assertFalse(coaches.uses_banned("Our tackling in space was poor."))


class Casing(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_teams")
        conn.execute("INSERT INTO league_teams (team_id, name, nickname, short_name) VALUES (1, 'Wyoming', 'Cowboys', 'WYO')")
        conn.commit()
        conn.close()

    def test_all_lowercase_gets_sentences_and_names(self):
        self.assertEqual(ai_engine.fix_casing("the cowboys won. i think wyoming is back."), "The Cowboys won. I think Wyoming is back.")

    def test_normal_text_only_gets_names(self):
        self.assertEqual(ai_engine.fix_casing("What a day for wyoming. hard to argue."), "What a day for Wyoming. hard to argue.")

    def test_i_and_contractions_in_normal_text(self):
        self.assertEqual(ai_engine.fix_casing("Coach said i'm proud, and i’ll say it: i love it."), "Coach said I'm proud, and I’ll say it: I love it.")

    def test_all_caps_names_from_any_casing(self):
        conn = database.get_db_connection()
        conn.execute("INSERT INTO league_teams (team_id, name, nickname, short_name) VALUES (2, 'NDSU', 'Bison', 'NDSU')")
        conn.commit()
        conn.close()
        self.assertEqual(ai_engine.fix_casing("Ndsu's a physical team. We respect ndsu."), "NDSU's a physical team. We respect NDSU.")
        self.assertEqual(ai_engine.fix_casing("The bison run downhill."), "The Bison run downhill.")

    def test_hawaii_apostrophe(self):
        self.assertEqual(ai_engine.fix_casing("we flew to hawai'i."), "We flew to hawai'i.")

    def test_strip_tags(self):
        self.assertEqual(ai_engine.strip_tags("Great win [image: team photo] today ."), "Great win today.")


class Colours(unittest.TestCase):
    def test_nearest_names(self):
        self.assertEqual(team.color_name("#492F24"), "brown")
        self.assertEqual(team.color_name("#FFC425"), "gold")
        self.assertIsNone(team.color_name(None))


class RecapMath(unittest.TestCase):
    def test_running_scores_and_lead_changes(self):
        game = {"home_quarters": [7, 0, 0, 10], "away_quarters": [0, 10, 3, 0]}
        self.assertEqual(recap.running_scores(game), [(7, 0), (7, 10), (7, 13), (17, 13)])
        self.assertEqual(recap.lead_changes(game), 2)


if __name__ == "__main__":
    unittest.main()
