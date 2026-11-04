"""The dynasty chooser: every save in the game's folder is listed, the app waits for a pick before anything else, and
switching points every table at that save's own database (the original dynasty keeps dynasty_data.db)."""
import os
import tempfile
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import backups
import database
import dynasty
import game_day
import roster
import save_sync


class Chooser(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.saves = os.path.join(self.dir, "saves")
        os.makedirs(self.saves)
        for name in ("DYNASTY-WYOYEAR1", "DYNASTY-WYOYEAR1-AUTOSAVE", "DYNASTY-BOISE", "RTG-HEIS", "ROSTER-Official", "DYNASTY-OCT19-06h49m12-AUTOSAVE"):
            with open(os.path.join(self.saves, name), "wb") as f:
                f.write(b"save")
        os.utime(os.path.join(self.saves, "DYNASTY-BOISE"), (1_000_000_000, 1_000_000_000))   # played long ago
        self.before = (database.DB_FILE, roster.DB_FILE, save_sync.SAVE_FILE, backups.BACKUP_DIR, game_day.SAVE_BACKUPS, dict(dynasty.state))
        self.patches = [mock.patch.object(dynasty, "SAVES_DIR", self.saves), mock.patch.object(dynasty, "APP_DIR", self.dir),
                        mock.patch.object(dynasty, "REGISTRY", os.path.join(self.dir, "dynasties.json"))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        database.DB_FILE, roster.DB_FILE, save_sync.SAVE_FILE, backups.BACKUP_DIR, game_day.SAVE_BACKUPS, state = self.before
        dynasty.state.clear()
        dynasty.state.update(state)

    def test_lists_saves_newest_first_without_autosaves(self):
        names = [s['name'] for s in dynasty.saves()]
        self.assertEqual(names, ["DYNASTY-WYOYEAR1", "DYNASTY-BOISE"])
        self.assertFalse(dynasty.saves()[1]['has_data'])   # never opened in the app yet

    def test_switch_gives_each_save_its_own_database(self):
        dynasty.switch("DYNASTY-BOISE")
        self.assertEqual(database.DB_FILE, os.path.join(self.dir, "dynasties", "DYNASTY-BOISE.db"))
        self.assertEqual(roster.DB_FILE, database.DB_FILE)
        self.assertEqual(save_sync.SAVE_FILE, os.path.join(self.saves, "DYNASTY-BOISE"))
        self.assertEqual(game_day.SAVE_BACKUPS, os.path.join(self.dir, "backups", "dynasties", "DYNASTY-BOISE", "saves"))
        conn = database.get_db_connection()
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
        self.assertTrue({"schedule_tracking", "team_roster", "care_players", "chat_messages", "boost_runs"} <= tables)
        self.assertEqual(dynasty.last(), "DYNASTY-BOISE")
        dynasty.switch("DYNASTY-WYOYEAR1")
        self.assertEqual(database.DB_FILE, os.path.join(self.dir, "dynasty_data.db"))   # the original keeps its file
        self.assertEqual(backups.BACKUP_DIR, os.path.join(self.dir, "backups"))

    def test_only_saves_in_the_folder_can_be_picked(self):
        for name in ("..\\dynasty_data.db", "DYNASTY-MISSING", "", "RTG-HEIS", "DYNASTY-WYOYEAR1-AUTOSAVE", "DYNASTY-WYOYEAR1-AUTOSAVE/../DYNASTY-BOISE"):
            with self.assertRaises(ValueError):
                dynasty.switch(name)

    def test_no_switch_while_messages_are_being_written(self):
        dynasty.switch("DYNASTY-WYOYEAR1")
        with mock.patch.object(dynasty, "busy", return_value=True):
            with self.assertRaises(ValueError):
                dynasty.switch("DYNASTY-BOISE")

    def test_the_app_waits_for_a_pick(self):
        from app import app
        client = app.test_client()
        dynasty.state['chosen'] = False
        self.assertIn("/choose", client.get("/").headers["Location"])
        self.assertEqual(client.post("/generate", json={}).status_code, 409)
        page = client.get("/choose").get_data(as_text=True)
        self.assertIn("BOISE", page)
        self.assertIn('value="DYNASTY-WYOYEAR1" checked', page)          # the last one opened is preselected
        self.assertEqual(client.post("/choose", json={"name": "DYNASTY-NOPE"}).status_code, 400)
        response = client.post("/choose", json={"name": "DYNASTY-BOISE"})
        self.assertEqual(response.get_json()['current']['name'], "DYNASTY-BOISE")
        self.assertTrue(dynasty.state['chosen'])


if __name__ == "__main__":
    unittest.main()
