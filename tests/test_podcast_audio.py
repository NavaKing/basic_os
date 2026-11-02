"""Podcast audio is stored once (the line files); the whole-episode MP3 is joined on request."""
import json
import os
import shutil
import unittest
from unittest import mock

from tests import TEMP_DIR
import database
import podcast


class EpisodeAudio(unittest.TestCase):
    def setUp(self):
        # A private podcasts folder: never the real episodes
        self.folder = os.path.join(TEMP_DIR, "podcasts")
        shutil.rmtree(self.folder, ignore_errors=True)
        patcher = mock.patch.object(podcast, "PODCAST_DIR", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        conn = database.get_db_connection()
        conn.execute("DELETE FROM podcast_episodes")
        conn.execute("""INSERT INTO podcast_episodes (episode_id, title, hosts_json, script_json, game_json, audio_file)
                        VALUES (7, 'T', '[]', ?, '{"teams": [], "plays": []}', 'podcasts/7/episode.mp3')""",
                     (json.dumps([{"host": 0, "text": "a"}, {"host": 1, "text": "b"}]),))
        conn.execute("""INSERT INTO podcast_episodes (episode_id, title, hosts_json, script_json, game_json, audio_file)
                        VALUES (8, 'Unfinished', '[]', '[{"host": 0, "text": "a"}]', '{"teams": [], "plays": []}', NULL)""")
        conn.commit()
        conn.close()
        os.makedirs(os.path.join(self.folder, "7"))
        for index, data in enumerate((b"AAAA", b"BBBBBB")):
            with open(podcast.line_path(os.path.join(self.folder, "7"), index), "wb") as f:
                f.write(data)

    def test_joined_on_request(self):
        self.assertEqual(podcast.episode_audio(7), b"AAAABBBBBB")
        self.assertIsNone(podcast.episode_audio(8))  # not every line is recorded yet
        episodes = {e['episode_id']: e for e in podcast.query_episodes()}
        self.assertEqual(episodes[7]['audio_url'], "/podcast/7/episode.mp3")
        self.assertIsNone(episodes[8]['audio_url'])

    def test_route_supports_seeking(self):
        from app import app
        client = app.test_client()
        local = {"Host": "127.0.0.1:5000"}
        self.assertEqual(client.get("/podcast/7/episode.mp3", headers=local).data, b"AAAABBBBBB")
        part = client.get("/podcast/7/episode.mp3", headers={**local, "Range": "bytes=4-"})
        self.assertEqual((part.status_code, part.data), (206, b"BBBBBB"))
        self.assertEqual(client.get("/podcast/8/episode.mp3", headers=local).status_code, 404)

    def test_old_joined_copies_are_removed(self):
        with open(os.path.join(self.folder, "7", "episode.mp3"), "wb") as f:
            f.write(b"AAAABBBBBB")
        self.assertEqual(podcast.drop_joined_copies(), 1)
        self.assertFalse(os.path.exists(os.path.join(self.folder, "7", "episode.mp3")))


if __name__ == "__main__":
    unittest.main()
