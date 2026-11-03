"""The players' voices for the group chat: post-game messages grounded in the last game, teammates' replies, and answers
to the coach; unknown authors, stats in replies, repeats and leaked mood notes are dropped."""
import json
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import ai_engine
import care
import database
import group_chat
import roster
import team_board


def set_up_team():
    conn = database.get_db_connection()
    for table in ("care_state", "care_players", "care_warnings", "care_log", "care_council", "chat_messages", "chat_state", "chat_reactions",
                  "schedule_tracking", "team_roster", "player_game_stats"):
        conn.execute(f"DELETE FROM {table}")
    conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site, game_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     [(1, "Utah Utes", 1, 31, 10, "Home", "2026-09-05"), (2, "Utah State Aggies", 0, None, None, "Away", "2026-09-12")])
    conn.executemany("INSERT INTO player_game_stats (save_id, week_num, stats_json) VALUES (?, 1, ?)",
                     [("hb1", json.dumps({"DOWNSPLAYED": 50, "RUSHATTEMPTS": 20, "RUSHYARDS": 177, "RUSHTDS": 1})),
                      ("wr1", json.dumps({"DOWNSPLAYED": 40, "RECEIVECATCHES": 2, "RECEIVEYARDS": 19}))])
    conn.execute("INSERT INTO chat_state (state_key, state_value) VALUES ('migrated', '1')")
    conn.commit()
    conn.close()
    conn = roster.get_connection()
    conn.executemany("INSERT INTO team_roster (save_id, player_name, position, health_status, overall, class_year, jersey_num) VALUES (?, ?, ?, 'Healthy', ?, ?, ?)",
                     [("hb1", "Samuel Harris", "HB", 82, "Freshman", 1), ("wr1", "Eric Richardson", "WR", 75, "Senior", 2),
                      ("cb1", "Bench Corner", "CB", 60, "Freshman", 30)])
    conn.commit()
    conn.close()
    care.advance(2)


class Voices(unittest.TestCase):
    def setUp(self):
        set_up_team()

    def test_cast_puts_last_games_standouts_first(self):
        people = team_board.cast(1)
        self.assertEqual(people[0]['name'], "Samuel Harris")
        self.assertIn("177 rush yds", team_board.describe(people[0]))
        self.assertIn("didn't play last game", team_board.describe(next(c for c in people if c['name'] == "Bench Corner")))

    def test_compose_posts_and_replies(self):
        mood = team_board.cast(1)[0]['mood']
        posts = {"posts": [{"author": "Samuel Harris", "text": f"177 yards and the W. shoutout to the o-line {mood}"},
                           {"author": "Eric Richardson", "text": "back to work this week"},
                           {"author": "Somebody Else", "text": "not on our team"}]}
        replies = {"replies": [{"author": "Eric Richardson", "reply_to": 0, "text": "you were cooking sam"},
                               {"author": "Samuel Harris", "reply_to": 0, "text": "replying to myself"},
                               {"author": "Bench Corner", "reply_to": 1, "text": "you had 3 catches bro"},
                               {"author": "Bench Corner", "reply_to": 1, "text": "lets go"}]}
        with mock.patch.object(ai_engine, "call_ollama", side_effect=[json.dumps(posts), json.dumps(replies)]):
            out, answers = team_board.compose("test-model", 1)
        self.assertEqual([p['save_id'] for p in out], ["hb1", "wr1"])
        self.assertNotIn(mood, out[0]['text'])   # the mood note is for tone only
        self.assertEqual([(r['save_id'], r['reply_to'], r['text']) for r in answers], [("wr1", 0, "you were cooking sam"), ("cb1", 1, "lets go")])

    def test_no_repeats_angles_and_no_touchdown_lengths(self):
        group_chat.execute("INSERT INTO chat_messages (week, save_id, kind, text, delivered_at) VALUES (0, 'hb1', 'postgame', ?, 1)",
                           ("that 177 rush yards felt good, thanks to the o-line for opening those holes!",))
        posts = {"posts": [{"author": "Samuel Harris", "text": "that 177 rush yards felt good, thanks to the o-line for opening those lanes!"},
                           {"author": "Eric Richardson", "text": "that 19 yard td was a team effort. bus ride was loud."}]}
        prompts = []
        def answer(model, prompt, **kwargs):
            prompts.append(prompt)
            return json.dumps(posts) if len(prompts) == 1 else json.dumps({"replies": []})
        with mock.patch.object(ai_engine, "call_ollama", side_effect=answer):
            out, _ = team_board.compose("test-model", 1)
        self.assertIn("his last post, never repeat it", prompts[0])
        self.assertIn("his post this week:", prompts[0])
        self.assertEqual(out, [{"save_id": "wr1", "text": "bus ride was loud."}])

    def test_stat_lines_are_graded_like_college_football(self):
        self.assertEqual(team_board.grade({"RUSHATTEMPTS": 32, "RUSHYARDS": 212}), "great")
        self.assertEqual(team_board.grade({"RECEIVECATCHES": 6, "RECEIVEYARDS": 105}), "good")
        self.assertEqual(team_board.grade({"DEFTACKLES": 5}), "solid")
        self.assertEqual(team_board.grade({"PASSATTEMPTS": 25, "PASSYARDS": 121, "PASSTDS": 0, "PASSINTS": 2}), "rough")
        self.assertEqual(team_board.grade({"PASSYARDS": 280, "PASSTDS": 2, "PASSINTS": 2}), "solid")   # two picks take the shine off
        self.assertEqual(team_board.grade({"RUSHATTEMPTS": 14, "RUSHYARDS": 31}), "rough")
        harris = next(c for c in team_board.cast(1) if c['name'] == "Samuel Harris")
        self.assertIn("a great game by college football standards", team_board.describe(harris))
        team_board.assign_angles([harris], 1)
        self.assertIn(harris['angle'], team_board.STAT_ANGLES['great'])   # never "the numbers weren't enough"

    def test_answers_to_the_coach_in_order_without_stats(self):
        replies = {"replies": [{"author": "Eric Richardson", "text": "yes coach"}, {"author": "Samuel Harris", "text": "177 yards baby"},
                               {"author": "Samuel Harris", "text": "on it coach"}, {"author": "Nobody", "text": "hi"}]}
        with mock.patch.object(ai_engine, "call_ollama", return_value=json.dumps(replies)):
            out = team_board.answer("test-model", "Big week, Sam and Eric", ["hb1", "wr1"], ["Coach: hello"])
        self.assertEqual(out, [{"save_id": "wr1", "text": "yes coach"}, {"save_id": "hb1", "text": "on it coach"}])

    def test_no_model_answer_is_an_error(self):
        with mock.patch.object(ai_engine, "call_ollama", side_effect=RuntimeError("down")):
            with self.assertRaises(RuntimeError):
                team_board.compose("test-model", 1)


if __name__ == "__main__":
    unittest.main()
