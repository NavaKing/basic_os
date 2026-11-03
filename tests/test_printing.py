"""Printable issue: the print view renders the Season pages (one week or all), and the PDF route reports a missing Edge."""
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import database
import printing
from app import app

LOCAL = {"Host": "127.0.0.1:5000"}


def execute(sql, rows=((),)):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


class PrintView(unittest.TestCase):
    def setUp(self):
        execute("DELETE FROM schedule_tracking")
        execute("""INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site, game_date)
                   VALUES (?, ?, 1, ?, ?, 'Home', ?)""", [(1, "Colorado State Rams", 31, 17, "2026-09-05"), (2, "FCS Midwest", 35, 21, "2026-09-12")])
        self.client = app.test_client()

    def test_whole_season_has_a_cover_and_every_week(self):
        html = self.client.get("/print", headers=LOCAL).get_data(as_text=True)
        self.assertIn('class="print-cover"', html)
        self.assertIn("2 pages", html)
        self.assertEqual(html.count('class="print-page"'), 2)

    def test_one_week(self):
        html = self.client.get("/print?week=2", headers=LOCAL).get_data(as_text=True)
        self.assertNotIn('class="print-cover"', html)
        self.assertEqual(html.count('class="print-page"'), 1)
        self.assertIn("1 page &middot; Week 2", html)
        self.assertIn("Week 2 Edition", html)

    def test_week_with_nothing(self):
        html = self.client.get("/print?week=9", headers=LOCAL).get_data(as_text=True)
        self.assertIn("Nothing to print for Week 9 yet.", html)


class Pdf(unittest.TestCase):
    def test_missing_edge_is_explained(self):
        with mock.patch.object(printing, "edge_path", return_value=None):
            response = app.test_client().get("/print.pdf?week=1", headers=LOCAL)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Save as PDF", response.get_json()['error'])

    def test_pdf_is_sent_as_a_download(self):
        with mock.patch.object(printing, "render_pdf", return_value=b"%PDF-1.4 test"):
            response = app.test_client().get("/print.pdf?week=1", headers=LOCAL)
        self.assertEqual(response.data, b"%PDF-1.4 test")
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn('attachment; filename="', response.headers["Content-Disposition"])
        self.assertIn('-Week-1.pdf"', response.headers["Content-Disposition"])


class HubGeneratorFailure(unittest.TestCase):
    """When Ollama doesn't answer, /generate says so as an error (it used to answer 'OK' with the message as the story)."""

    def test_dispatch_failure_is_an_error(self):
        import ai_engine
        import database
        execute("DELETE FROM schedule_tracking")
        execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, site) VALUES (5, 'NDSU Bison', 0, 'Away')")
        with mock.patch.object(ai_engine, "call_ollama", side_effect=ConnectionError("refused")),              mock.patch("storylines.advance_storylines"), mock.patch("recruiting.create_commit_storylines"),              mock.patch("scouting.generate_preview", return_value=None), mock.patch("save_sync.sync_if_changed"):
            response = app.test_client().post("/generate", headers=LOCAL, json={"model": "m"})
        self.assertEqual(response.status_code, 500)
        self.assertIn("Ollama didn't answer while writing the dispatch", response.get_json()['error'])
        self.assertEqual([s for s in database.query_archived_stories() if s.get('week_num') == 5], [])


if __name__ == "__main__":
    unittest.main()
