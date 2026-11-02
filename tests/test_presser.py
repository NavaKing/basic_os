"""Press conference: answers stay in character and on the facts, coaches keep one personality, and the week's quotes
reach the hub generator."""
import json
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import ai_engine
import database
import presser


def execute(sql, rows=((),)):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


class Answers(unittest.TestCase):
    ALLOWED = {24, 18, 160, 19}

    def test_invented_numbers_and_meta_talk_are_dropped(self):
        text = ("We won 24 to 18 and I loved the effort. We'll score 45 next week. "
                "I can't speculate beyond the facts provided. He's a Cowboy right now.")
        self.assertEqual(presser.usable(text, self.ALLOWED), "We won 24 to 18 and I loved the effort. He's a Cowboy right now.")

    def test_stat_budget_trims_later_sentences(self):
        text = "Harris ran 19 times for 160 yards. We won 24 to 18. The line was great."
        self.assertEqual(presser.usable(text, self.ALLOWED), "Harris ran 19 times for 160 yards. The line was great.")

    def test_empty_answers_are_rejected(self):
        self.assertEqual(presser.usable("...", self.ALLOWED), "")

    def test_best_answer_retries_then_keeps_the_least_stat_heavy(self):
        replies = iter(["...", "Harris ran 19 times for 160 yards, and we won by six. Great effort.", "Great effort from everybody on Saturday."])
        self.assertEqual(presser.best_answer(lambda: next(replies), self.ALLOWED), "Great effort from everybody on Saturday.")

    def test_persona_is_stable(self):
        self.assertEqual(presser.persona("Jay Sawvel"), presser.persona("Jay Sawvel"))
        self.assertIn(presser.persona("Jay Sawvel"), presser.PERSONAS)


class Conference(unittest.TestCase):
    def setUp(self):
        for table in ("league_teams", "press_conference", "schedule_tracking"):
            execute(f"DELETE FROM {table}")
        staff = {"hc": {"name": "Jay Sawvel", "portrait": None}, "oc": {"name": "Marcus Chiu", "portrait": None}}
        execute("INSERT INTO league_teams (team_id, name, nickname, short_name, is_user, staff_json) VALUES (1, 'Wyoming', 'Cowboys', 'WYO', 1, ?)",
                [(json.dumps(staff),)])
        execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, site) VALUES (5, 'NDSU Bison', 0, 'Away')")

    def ask(self, role, question, reply):
        with mock.patch.object(presser, "week_facts", return_value="Wyoming won 24-18."), \
             mock.patch.object(ai_engine, "call_ollama", return_value=json.dumps({"answer": reply})), \
             mock.patch.object(ai_engine, "proper_names", return_value=set()):
            return presser.ask("model", role, question)

    def test_ask_and_quote(self):
        self.assertEqual([s['name'] for s in presser.speakers()], ["Jay Sawvel", "Marcus Chiu"])
        self.ask("oc", "How did the line play?", "The line played with real effort up front.")
        transcript = self.ask("hc", "What did you think of the win?", "A 24 to 18 win on the road is never easy.")
        self.assertEqual([(t['speaker'], t['title']) for t in transcript], [("Marcus Chiu", "Offensive Coordinator"), ("Jay Sawvel", "Head Coach")])
        quotes = presser.dispatch_context()
        self.assertLess(quotes.index("Jay Sawvel"), quotes.index("Marcus Chiu"))  # the head coach is quoted first
        self.assertIn('said: "A 24 to 18 win on the road is never easy."', quotes)

    def test_bad_requests(self):
        with self.assertRaisesRegex(ValueError, "Type a question"):
            presser.ask("model", "hc", "Hi")
        with self.assertRaisesRegex(ValueError, "isn't in the synced data"):
            presser.ask("model", "dc", "How is the secondary holding up?")

    def test_clear_and_quiet_week(self):
        self.ask("hc", "What did you think of the win?", "We played hard for four quarters.")
        presser.clear_week()
        self.assertEqual(presser.transcript(), [])
        self.assertEqual(presser.dispatch_context(), "")


if __name__ == "__main__":
    unittest.main()
