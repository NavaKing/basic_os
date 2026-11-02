"""Between the Numbers Weekly: facts from a recap page, the numbers check that drops invented scores, and the show writer."""
import json
import unittest
from unittest import mock

import tests  # noqa: F401  (sets up the throwaway database first)
import ai_engine
import fact_check
import podcast


def team(name, rank=None):
    return {"id": name, "name": name, "short": name[:4].upper(), "rank": rank}


def card(away, away_total, home, home_total, detail=None):
    return {"rows": [{"team": away, "total": away_total}, {"team": home, "total": home_total}], "detail": detail}


def player(pid, first, last, team_row, boxes):
    return {"id": pid, "first_name": first, "last_name": last, "position": "WR", "team": team_row, "boxes": boxes,
            "result": {"outcome": "W", "score": "77-0", "venue": "vs", "opponent": team("Central Michigan")}}


PAGE = {
    "games": {"game_of_the_week": card(team("Indiana", 6), 19, team("Northwestern"), 23, "3 lead changes, decided by 4"),
              "upset": None, "comeback": None, "blowout": None},
    "top25": [card(team("USC", 9), 15, team("Oregon", 10), 21)],
    "players": {"offense": player("p1", "Malachi", "Toney", team("Miami", 15), [{"label": "Rec", "value": 11}, {"label": "YAC", "value": 142}]),
                "freshman": player("p1", "Malachi", "Toney", team("Miami", 15), []), "defense": None, "bummer": None},
    "risers": [{"team": team("Tennessee"), "before": 16, "after": 8, "line": "W 27-24 vs Texas"}],
    "fallers": None, "cfp": [], "heisman": [], "streaks": {"winning": [{"team": team("Ohio State"), "streak": "W4"}], "losing": []},
}


class WeeklyFacts(unittest.TestCase):
    def test_facts_and_headlines(self):
        facts, headlines = podcast.weekly_facts(PAGE, "Wyoming", "beat Hawaii 24 to 18")
        text = {topic: [t for tp, t in facts if tp == topic] for topic, _ in facts}
        self.assertEqual(text['games'], ["Game of the week: Northwestern beat No. 6 Indiana 23 to 19 (3 lead changes, decided by 4)."])
        self.assertEqual(text['top25'], ["Top 25 matchups: No. 10 Oregon beat No. 9 USC 21 to 15."])
        self.assertIn("11 catches, 142 yards after the catch; his team won 77 to 0 against Central Michigan.", text['players'][0])
        self.assertEqual(text['players'][1], "Freshman of the Week: also Malachi Toney, a freshman, so he won both awards.")
        self.assertEqual(text['polls'], ["Biggest poll risers: Tennessee from 16 to 8 after W 27-24 vs Texas."])
        self.assertEqual(text['ours'], ["Wyoming this week: beat Hawaii 24 to 18."])
        self.assertEqual(text['streaks'], ["Longest winning streaks: Ohio State (4 straight)."])
        self.assertEqual(headlines[1:], ["Offensive Player of the Week: Malachi Toney, Miami", "Freshman of the Week: Malachi Toney again"])

    def test_welcome(self):
        self.assertEqual(podcast.weekly_welcome([{"name": "Andrew"}, {"name": "Ava"}], 4),
                         "Welcome to Between the Numbers Weekly, folks. I'm Andrew, and here with me is Ava. "
                         "Today we're going around college football after Week 4.")


class NumbersCheck(unittest.TestCase):
    def test_reads_digits_and_words(self):
        self.assertEqual(fact_check.spoken_numbers("Forty-five to twenty, 1,200 yards, eighteen catches, 24 to 18"), {45, 20, 1200, 18, 24})

    def test_flags_only_numbers_missing_from_the_facts(self):
        allowed = {24, 18}
        self.assertEqual(fact_check.invented_numbers("They won forty-five to twenty!", allowed), [20, 45])
        self.assertEqual(fact_check.invented_numbers("Wyoming beat Hawaii 24 to 18, one of the best", allowed), [])
        self.assertEqual(fact_check.invented_numbers("Three lead changes and four straight wins", allowed), [])  # small numbers pass


class DropInvented(unittest.TestCase):
    """The dispatch and campus posts keep only sentences whose numbers are in the facts."""

    def test_sentences_paragraphs_tags_and_years(self):
        allowed = {24, 18, 7220}
        text = "Wyoming beat Hawaii 24-18. They won 45 to 20, wow.\n\nThe 2026 season rolls on! #7220SPEED @Wyo88 loves it."
        self.assertEqual(fact_check.drop_invented(text, allowed),
                         "Wyoming beat Hawaii 24-18.\n\nThe 2026 season rolls on! #7220SPEED @Wyo88 loves it.")

    def test_everything_invented_leaves_nothing(self):
        self.assertEqual(fact_check.drop_invented("They scored 63 points.", {24}), "")


class ShowWriter(unittest.TestCase):
    def test_invented_lines_are_dropped(self):
        replies = iter([json.dumps({"title": "T", "summary": "S", "lines": [
            {"host": 1, "text": "Wyoming beat Hawaii 24 to 18."},
            {"host": 0, "text": "Forty-five to twenty, what a statement."},
            {"host": 1, "text": "The defense held when it mattered."}]})] +
            [json.dumps({"lines": [{"host": i % 2, "text": text} for i, text in enumerate(segment)]}) for segment in (
                ("The line opened holes all night.", "Their quarterback looked rattled early.", "Special teams flipped the field twice.", "Tackling was crisp."),
                ("The crowd was loud from the opening kick.", "Hawaii never found a rhythm.", "Our corners won their matchups.", "Clock management was sharp."),
            )])
        hosts = podcast.hosts_from(None)
        facts = [("result", "Final: Wyoming 24, Hawaii 18.")]
        with mock.patch.object(ai_engine, "call_ollama", side_effect=lambda *a, **k: next(replies)), \
             mock.patch.object(ai_engine, "proper_names", return_value=set()):
            title, summary, lines = podcast.write_show("model", hosts, "show", "Welcome.", [("open", ("result",), 3), ("more", ("result",), 4),
                                                                                             ("again", ("result",), 4)], facts, "Fallback")
        texts = [l['text'] for l in lines]
        self.assertIn("Wyoming beat Hawaii 24 to 18.", texts)
        self.assertNotIn("Forty-five to twenty, what a statement.", texts)
        self.assertEqual((title, summary), ("T", "S"))


if __name__ == "__main__":
    unittest.main()
