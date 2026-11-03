"""WYO Group Chat: post-game messages arrive one at a time at their pace, the coach's messages get a few answers (named
players first), a care lift once a week, and old Team Board posts move into the history."""
import json
import random
import time
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import care
import group_chat
import league
import team_board
from tests.test_team_board import set_up_team


def wait_for(job):
    for _ in range(200):
        if group_chat._jobs[job] and group_chat._jobs[job].get('done'):
            return group_chat._jobs[job]
        time.sleep(0.02)
    raise AssertionError(f"the {job} job didn't finish")


class GroupChat(unittest.TestCase):
    def setUp(self):
        set_up_team()
        group_chat._jobs.update(postgame=None, answer=None)

    def test_post_game_chat_once_per_game_then_paced(self):
        self.assertTrue(group_chat.postgame_due())
        posts = [{"save_id": "hb1", "text": "big win"}, {"save_id": "wr1", "text": "back to work"}]
        replies = [{"save_id": "wr1", "text": "you cooked", "reply_to": 0}]
        with mock.patch.object(team_board, "compose", return_value=(posts, replies)) as compose:
            self.assertTrue(group_chat.start_postgame("test-model"))
            wait_for("postgame")
            self.assertFalse(group_chat.start_postgame("test-model"))   # once per game
        self.assertEqual(compose.call_args.args[2], care.load_tuning()['chat']['postgame_messages'])   # a win, not a big one
        self.assertFalse(group_chat.postgame_due())
        rows = league.query_rows("SELECT save_id, kind, text, reply_to, delay FROM chat_messages ORDER BY msg_id")
        self.assertEqual([(r['save_id'], r['kind'], r['text']) for r in rows],
                         [("hb1", "postgame", "big win"), ("wr1", "reply", "you cooked"), ("wr1", "postgame", "back to work")])
        self.assertIsNotNone(rows[1]['reply_to'])   # the reply points at Harris's message

        now = 1_000_000.0
        self.assertEqual(group_chat.deliver(now + 10)['text'], "big win")
        self.assertIsNone(group_chat.deliver(now + 11))        # the next one waits its delay
        delay = rows[1]['delay']
        self.assertEqual(group_chat.typing(now + 10 + delay - 1), "wr1")   # typing just before it arrives
        self.assertEqual(group_chat.deliver(now + 10 + delay)['text'], "you cooked")
        view = group_chat.view()
        self.assertEqual([m['text'] for m in view['messages']], ["big win", "you cooked"])
        self.assertEqual(view['messages'][1]['reply_to']['name'], "Samuel Harris")
        self.assertEqual((view['unread'], view['waiting']), (2, 1))
        group_chat.mark_read()
        self.assertEqual(group_chat.view()['unread'], 0)

    def test_fewer_messages_after_a_loss(self):
        group_chat.execute("UPDATE schedule_tracking SET wyo_score = 10, opp_score = 31 WHERE week_id = 1")
        self.assertEqual(group_chat.postgame_count(1), care.load_tuning()['chat']['postgame_after_loss'])

    def test_a_failed_write_waits_before_retrying(self):
        with mock.patch.object(team_board, "compose", side_effect=RuntimeError("Ollama is down")):
            group_chat.start_postgame("test-model")
            self.assertIn("down", wait_for("postgame")['error'])
            self.assertFalse(group_chat.start_postgame("test-model"))   # waits retry_seconds
        self.assertTrue(group_chat.postgame_due())

    def test_responders_named_first_and_one_during_the_cooldown(self):
        players = care.load_players()
        picked, named = group_chat.pick_responders("Huge game Harris, proud of you", players, [], now=1000.0, rng=random.Random(1))
        self.assertEqual((picked[0], named), ("hb1", ["hb1"]))
        low, high = care.load_tuning()['chat']['responders']
        self.assertTrue(low <= len(picked) <= high)
        group_chat.set_state("coach_last_at", 1000.0)
        picked, _ = group_chat.pick_responders("one more thing", players, [], now=1005.0, rng=random.Random(1))
        self.assertEqual(len(picked), 1)

    def test_coach_message_lift_and_answers(self):
        morale = {p['save_id']: p['needs']['morale'] for p in care.load_players()}
        with mock.patch.object(team_board, "answer", return_value=[{"save_id": "hb1", "text": "thanks coach"}]):
            view = group_chat.send("Great work Harris", "test-model")
            wait_for("answer")
        self.assertEqual(view['messages'][-1], {**view['messages'][-1], "me": True, "text": "Great work Harris"})
        t = care.load_tuning()['chat']
        after = {p['save_id']: p['needs']['morale'] for p in care.load_players()}
        self.assertEqual(after['wr1'], min(100, morale['wr1'] + t['rally_morale']))
        self.assertEqual(after['hb1'], min(100, morale['hb1'] + t['rally_morale'] + t['shoutout_morale']))
        with mock.patch.object(team_board, "answer", return_value=[]):
            group_chat.send("Great work Harris", "test-model")   # the lift is once a week
            wait_for("answer")
        self.assertEqual({p['save_id']: p['needs']['morale'] for p in care.load_players()}, after)
        self.assertEqual(league.query_rows("SELECT text FROM chat_messages WHERE kind = 'answer'")[0]['text'], "thanks coach")
        with self.assertRaises(ValueError):
            group_chat.send("   ", "test-model")

    def test_old_team_board_posts_move_into_the_chat(self):
        group_chat.execute("DELETE FROM chat_state")
        group_chat.execute("DELETE FROM team_board_posts")
        first = group_chat.execute("INSERT INTO team_board_posts (week, save_id, text) VALUES (1, 'hb1', 'old post')")
        group_chat.execute("INSERT INTO team_board_posts (week, save_id, text, reply_to) VALUES (1, 'wr1', 'old reply', ?)", (first,))
        group_chat.migrate_team_board()
        group_chat.migrate_team_board()   # once only
        rows = league.query_rows("SELECT kind, text, reply_to, read FROM chat_messages ORDER BY msg_id")
        self.assertEqual([(r['kind'], r['text'], r['read']) for r in rows], [("postgame", "old post", 1), ("reply", "old reply", 1)])
        self.assertFalse(group_chat.postgame_due())   # week 1's chat already happened on the board
        group_chat.execute("DELETE FROM team_board_posts")

    def test_routes(self):
        from app import app
        client = app.test_client()
        host = {"Host": "127.0.0.1:5000"}
        with mock.patch.object(group_chat, "start_postgame", return_value=False):
            self.assertIn("messages", client.get("/phone/chat?since=0", headers=host).get_json())
        self.assertEqual(client.post("/phone/chat/send", json={"text": ""}, headers=host).status_code, 400)
        self.assertTrue(client.post("/phone/chat/read", json={}, headers=host).get_json()['ok'])
        self.assertEqual(client.post("/phone/chat/nope", json={}, headers=host).status_code, 404)


if __name__ == "__main__":
    unittest.main()
