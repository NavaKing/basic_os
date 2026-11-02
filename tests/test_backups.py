"""Backups: make, list, restore (with a safety copy), delete, upload, and the automatic ones before a save sync."""
import os
import shutil
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database and backups folder first)
import backups
import database


def story_count():
    conn = database.get_db_connection()
    count = conn.execute("SELECT COUNT(*) FROM schedule_tracking").fetchone()[0]
    conn.close()
    return count


def add_week(week):
    conn = database.get_db_connection()
    conn.execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played) VALUES (?, 'Test', 0)", (week,))
    conn.commit()
    conn.close()


class Backups(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(backups.BACKUP_DIR, ignore_errors=True)
        conn = database.get_db_connection()
        conn.execute("DELETE FROM schedule_tracking")
        conn.commit()
        conn.close()
        # Distinct timestamps for backups made in quick succession
        ticks = iter(range(1, 1000))
        patcher = mock.patch.object(backups, "timestamp", lambda: f"20261102-12{next(ticks):04d}")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_make_and_list(self):
        file_name = backups.create_backup("Before Week 6!")
        self.assertRegex(file_name, r"^dynasty_20261102-120001_before-week-6\.db$")
        listed = backups.list_backups()
        self.assertEqual([(b['file'], b['label_text'], b['automatic']) for b in listed], [(file_name, "Before week 6", False)])

    def test_restore_brings_data_back_and_keeps_a_safety_copy(self):
        add_week(1)
        saved = backups.create_backup("one-week")
        add_week(2)
        self.assertEqual(story_count(), 2)
        safety = backups.restore_backup(saved)
        self.assertEqual(story_count(), 1)
        self.assertIn("before-restore", safety)
        backups.restore_backup(safety)  # undo
        self.assertEqual(story_count(), 2)

    def test_only_backup_files_are_accepted(self):
        for name in ("../dynasty_data.db", "dynasty_20261102-120000.db", "notes.txt", "", None):
            with self.subTest(name=name), self.assertRaises(ValueError):
                backups.backup_path(name)

    def test_delete(self):
        file_name = backups.create_backup()
        backups.delete_backup(file_name)
        self.assertEqual(backups.list_backups(), [])

    def test_upload_checks_the_file(self):
        with self.assertRaisesRegex(ValueError, "isn't a database"):
            backups.save_upload(b"hello")
        os.makedirs(backups.BACKUP_DIR, exist_ok=True)
        with open(database.DB_FILE, "rb") as f:
            uploaded = backups.save_upload(f.read())
        self.assertEqual([b['file'] for b in backups.list_backups()], [uploaded])

    def test_automatic_backups_are_capped(self):
        keep = backups.create_backup("keep-me")
        for _ in range(backups.AUTO_KEEP + 3):
            backups.create_backup(backups.AUTO_LABEL)
        listed = backups.list_backups()
        self.assertEqual(sum(b['label'] == backups.AUTO_LABEL for b in listed), backups.AUTO_KEEP)
        self.assertIn(keep, [b['file'] for b in listed])


class Routes(unittest.TestCase):
    def setUp(self):
        from app import app
        shutil.rmtree(backups.BACKUP_DIR, ignore_errors=True)
        self.client = app.test_client()
        self.local = {"Host": "127.0.0.1:5000"}

    def test_make_download_and_bad_names(self):
        made = self.client.post("/backups", headers=self.local, json={"label": "route test"}).get_json()['backups'][0]
        download = self.client.get("/backups/" + made['file'], headers=self.local)
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.data.startswith(b"SQLite format 3"))
        self.assertIn("attachment", download.headers["Content-Disposition"])
        self.assertEqual(self.client.get("/backups/..%2Fdynasty_data.db", headers=self.local).status_code, 404)

    def test_other_sites_cannot_restore(self):
        made = self.client.post("/backups", headers=self.local, json={}).get_json()['backups'][0]
        response = self.client.post(f"/backups/{made['file']}/restore", headers={**self.local, "Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
