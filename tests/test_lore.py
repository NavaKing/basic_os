"""School lore: Wikipedia's infobox becomes plain facts (no bad numbers), a new school is fetched once in the background,
and this dynasty's title games are added on top of the history."""
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import care  # noqa: F401  (creates the care tables)
import database
import history  # noqa: F401  (creates history_games)
import lore

WIKITEXT = """{{Short description|x}}
{{Infobox NCAA football school
| ConfTitles = [[Big Sky Conference|Big Sky]]: [[1973 team|1973]], 1974<hr>[[Mountain West Conference|MW]]: 2012
| DivTitles = MW Mountain: 2014
| ATWins = 719
| ATLosses = 256
| BowlWins = {{some template}}
| BowlLosses = 10
| Stadium = [[Albertsons Stadium]]
| Location = [[Boise, Idaho]]
| Conference = [[Mountain West Conference|Mountain West]]
| Rivalries = [[Idaho Vandals football|Idaho]] ([[rivalry]])<br />[[Fresno State]]
}}"""


class FakeHttp:
    def __init__(self):
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        body = ({"extract": "The Broncos represent Boise State. Their current head coach is Real Person. They play on blue turf."}
                if "summary" in url else {"parse": {"title": "Boise State Broncos football", "wikitext": {"*": WIKITEXT}}})
        return mock.Mock(json=lambda: body)


class Lore(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.original = lore.LORE_FILE
        lore.LORE_FILE = os.path.join(self.dir, "school_lore.json")
        with open(lore.LORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"WYO": {"facts": ["Wyoming fact."]}}, f)
        conn = database.get_db_connection()
        try:
            for table in ("league_teams", "care_state", "history_games"):
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        lore.LORE_FILE = self.original
        shutil.rmtree(self.dir, ignore_errors=True)

    def coach_at(self, short, name, nickname):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_teams")
        conn.execute("INSERT INTO league_teams (team_id, name, nickname, short_name, is_user, conference) VALUES (1, ?, ?, ?, 1, 'MW')",
                     (name, nickname, short))
        conn.commit()
        conn.close()

    def test_infobox_to_facts(self):
        block = lore.fetch_school({"name": "Boise State", "nickname": "Broncos"}, session=FakeHttp())
        facts = " ".join(block['facts'])
        self.assertIn("conference titles (3): Big Sky: 1973, 1974; MW: 2012", facts)
        self.assertIn("All-time record: 719-256.", facts)
        self.assertNotIn("Bowl record", facts)           # a templated number is left out, not shown as 0-10
        self.assertNotIn("Real Person", facts)           # the real head coach isn't the dynasty's coach
        self.assertIn("Rivals: Idaho; Fresno State.", facts)
        self.assertEqual((block['conference_name'], block['auto'], block['reviewed']), ("Mountain West", True, False))

    def test_a_new_school_is_fetched_once_staying_changes_nothing(self):
        self.coach_at("WYO", "Wyoming", "Cowboys")
        self.assertFalse(lore.check_school())            # stayed: the school already has lore
        self.coach_at("BOIS", "Boise State", "Broncos")
        with mock.patch.object(lore, "fetch_school", return_value={"facts": ["Boise fact."], "auto": True}):
            self.assertTrue(lore.check_school())
            for _ in range(200):
                if not lore._fetching['running']:
                    break
                time.sleep(0.02)
        self.assertEqual(lore.read_file()['BOIS']['facts'], ["Boise fact."])
        self.assertEqual(lore.read_file()['WYO']['facts'], ["Wyoming fact."])   # the old school's lore is kept
        self.assertFalse(lore.check_school())

    def test_this_dynastys_title_games_come_after_the_history(self):
        self.coach_at("WYO", "Wyoming", "Cowboys")
        conn = database.get_db_connection()
        conn.execute("INSERT INTO care_state (state_key, state_value) VALUES ('title_game_2026', '15')")
        conn.execute("INSERT INTO history_games (season_year, week, opponent_name, site, our_score, their_score) VALUES (2026, 15, 'UNLV Rebels', 'Home', 31, 24)")
        conn.commit()
        conn.close()
        self.assertEqual(lore.dynasty_title_games(), ["2026 MW Championship Game: won 31-24 over UNLV Rebels"])
        context = lore.context()
        self.assertLess(context.index("Wyoming fact."), context.index("In this dynasty"))


if __name__ == "__main__":
    unittest.main()
