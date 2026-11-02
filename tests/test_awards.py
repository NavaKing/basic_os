"""Awards tab: which All-America teams show, the projected playoff bracket, bowls, and the Heisman column's facts."""
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import awards
import database
import league

TEAMS = {1: {"team_id": 1, "name": "Wyoming", "short_name": "WYO", "color": "#492F24"},
         2: {"team_id": 2, "name": "Boise State", "short_name": "BSU", "color": "#0033A0"}}


def pick(award_type, position, team_id=2, conference=None, name="Player"):
    return {"award_type": award_type, "position": position, "conference": conference, "team_id": team_id, "name": name,
            "jersey": 1, "class_year": "Junior", "overall": 90, "portrait_file": None}


class AllAmerica(unittest.TestCase):
    def test_preseason_until_final_teams_exist(self):
        rows = [pick("ALL_AM_1ST_PRE", "WR"), pick("ALL_AM_1ST_PRE", "QB"), pick("ALL_AM_2ND_PRE_CONF", "K", 1, "MW", "Our Kicker"),
                pick("ALL_AM_1ST_PRE_CONF", "QB", 2, "ACC")]
        aa = awards.all_america(rows, TEAMS, 1, "MW")
        self.assertEqual(aa['stage'], "Preseason")
        self.assertEqual([p['position'] for p in aa['national']['first']], ["QB", "WR"])  # football order, not save order
        self.assertEqual([c['name'] for c in aa['conferences']], ["MW", "ACC"])           # our conference first
        self.assertTrue(aa['conferences'][0]['second'][0]['ours'])
        self.assertEqual(aa['ours'], 1)

        final = awards.all_america(rows + [pick("ALL_AM_1ST", "HB", name="Final Back")], TEAMS, 1, "MW")
        self.assertEqual(final['stage'], "Final")
        self.assertEqual([p['name'] for p in final['national']['first']], ["Final Back"])
        self.assertEqual(final['conferences'], [])

    def test_no_awards(self):
        aa = awards.all_america([], TEAMS, 1, "MW")
        self.assertIsNone(aa['national'])
        self.assertEqual(aa['conferences'], [])


class Bracket(unittest.TestCase):
    def test_projected_seeding(self):
        cfp = [{"seed": s, "team": {"id": s, "name": f"Team {s}"}, "record": "5-0"} for s in range(1, 13)]
        games = [{"name": "CFP First Round", "date": f"2026-12-1{i}"} for i in range(4)]
        rounds = awards.projected_bracket(cfp, games)
        first = rounds[0]['games']
        self.assertEqual([(g['top']['seed'], g['bottom']['seed']) for g in first], [(8, 9), (5, 12), (6, 11), (7, 10)])
        self.assertEqual(first[0]['date'], "2026-12-10")
        self.assertEqual([g['top']['seed'] for g in rounds[1]['games']], [1, 4, 3, 2])
        self.assertEqual(rounds[1]['games'][0]['bottom']['label'], "Winner 8/9")
        self.assertIsNone(rounds[1]['games'][0]['date'])  # no quarterfinal dates given
        self.assertEqual([r['name'] for r in rounds], ["First Round", "Quarterfinals", "Semifinals", "National Championship"])

    def test_short_field_still_renders(self):
        rounds = awards.projected_bracket([{"seed": 1, "team": {"id": 1, "name": "A"}, "record": "1-0"}], [])
        self.assertEqual(rounds[0]['games'][0]['top'], {"seed": 8})


class Bowls(unittest.TestCase):
    def test_bowl_view(self):
        row = {"name": "Potato Bowl", "game_date": "2026-12-21", "week": 17, "home_id": 1, "away_id": 2, "played": 1,
               "home_score": 31, "away_score": 24}
        view = awards.bowl_view(row, TEAMS, {})
        self.assertTrue(view['home']['won'])
        self.assertFalse(view['away']['won'])
        unset = awards.bowl_view({**row, "home_id": None, "away_id": None, "played": 0}, TEAMS, {})
        self.assertIsNone(unset['home'])

    def test_sync_stores_conferences_awards_and_bowls(self):
        data = {"userTeamId": 1, "teams": [{"id": 1, "name": "Wyoming", "nickname": "Cowboys", "short": "WYO", "color": "#492F24",
                           "mediaRank": None, "mediaLastRank": None}],
                "games": [], "players": [], "weeklyAwards": [], "heisman": [],
                "conferences": [{"name": "MW", "champGame": "MW Championship", "teamIds": [1]}, {"name": "", "teamIds": []}],
                "seasonAwards": [{"type": "ALL_AM_1ST_PRE_CONF", "position": "QB", "conference": "MW", "teamId": 1, "playerId": "p",
                                  "name": "Kaleb Vance", "jersey": 7, "classYear": "Senior", "overall": 80, "score": 50}],
                "bowlGames": [{"id": 900, "week": 17, "weekType": "BowlSeason1", "name": "Arizona Bowl", "homeId": None, "awayId": None,
                               "played": False, "homeScore": None, "awayScore": None, "date": "2026-12-27"}]}
        league.sync_league(data, 5)
        self.assertEqual(league.query_teams()[1]['conference'], "MW")
        self.assertEqual([c['name'] for c in league.query_conferences()], ["MW"])
        self.assertEqual(league.query_season_awards()[0]['name'], "Kaleb Vance")
        self.assertEqual(league.query_bowls()[0]['name'], "Arizona Bowl")


class Column(unittest.TestCase):
    def test_facts_spell_out_stats_and_movement(self):
        heisman = [{"rank": 1, "movement": 0, "name": "A", "position": "WR", "team": {"name": "Miami"},
                    "boxes": [{"label": "YAC", "value": 300}]},
                   {"rank": 2, "movement": -1, "name": "B", "position": "QB", "team": {"name": "Ohio State"},
                    "boxes": [{"label": "Pass TD", "value": 20}]}]
        facts = awards.heisman_facts(heisman)
        self.assertIn("300 yards after the catch", facts)
        self.assertIn("(unchanged this week)", facts)
        self.assertIn("(down 1 spot this week)", facts)

    def test_one_block_is_split_into_paragraphs(self):
        text = " ".join(f"Sentence {i}." for i in range(8))
        self.assertEqual(awards.paragraphs(text).count("\n\n"), 3)
        self.assertEqual(awards.paragraphs("One.\n\nTwo."), "One.\n\nTwo.")

    def test_stored_column(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM award_columns")
        conn.execute("INSERT INTO award_columns (kind, week, title, body) VALUES ('heisman_watch', 4, 'T', 'One.\n\nTwo.')")
        conn.commit()
        conn.close()
        self.assertEqual(awards.query_column()['paragraphs'], ["One.", "Two."])


if __name__ == "__main__":
    unittest.main()
