"""Finish notifications (static/js/notify.js), run in Node against a stand-in for the browser."""
import json
import os
import shutil
import subprocess
import unittest

from tests import APP_DIR

HERE = os.path.dirname(os.path.abspath(__file__))


def run(hidden, permission):
    result = subprocess.run(["node", os.path.join(HERE, "notify_check.mjs"), os.path.join(APP_DIR, "static", "js", "notify.js"),
                             "1" if hidden else "0", permission], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("node"), "needs Node.js")
class Notify(unittest.TestCase):
    def test_visible_page_gets_toasts_only(self):
        out = run(hidden=False, permission="granted")
        self.assertEqual(out['ok'], {"text": "done"})
        self.assertEqual(out['toasts'], [{"text": "The hub generator is ready.", "error": False},
                                         {"text": "The game plan failed: Ollama is not running", "error": True},
                                         {"text": "The podcast recording failed: network down", "error": True}])
        self.assertEqual(out['shown'], [])          # no desktop notification while you're looking at the page
        self.assertEqual(out['title'], "BASIC OS")
        self.assertTrue(out['rethrown'])

    def test_hidden_page_gets_desktop_notifications_and_a_title_flag(self):
        out = run(hidden=True, permission="granted")
        self.assertEqual(out['shown'][0], {"title": "The hub generator is ready", "body": "Switch back to BASIC_OS to see it."})
        self.assertEqual(out['shown'][1], {"title": "The game plan failed", "body": "Ollama is not running"})
        self.assertEqual(out['title'], "(Failed) BASIC OS")

    def test_asks_once_and_respects_a_no(self):
        self.assertTrue(run(hidden=True, permission="default")['asked'])
        denied = run(hidden=True, permission="denied")
        self.assertFalse(denied['asked'])
        self.assertEqual(denied['shown'], [])
        self.assertEqual(len(denied['toasts']), 3)  # the toasts still show


if __name__ == "__main__":
    unittest.main()
