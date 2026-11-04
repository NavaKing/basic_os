"""Player care: needs drain toward a stress-dependent level, warning signs come from low needs, the coach's hours fill
needs, and the leadership council, mentors and difficulty preset do what the tuning file says."""
import random
import unittest

import tests  # noqa: F401  (sets up the throwaway database first)
import care
import care_messages
import database
import league
import roster


def player(save_id="p1", **overrides):
    p = {"save_id": save_id, "name": "Test Player", "position": "WR", "class": "Freshman", "overall": 70, "portrait": None,
         "starter": False, "blocked": False, "injured": False, "traits": [], "dev": "Normal", "distance": 0,
         "confidence": 50, "hot_cold": "Neutral", "birthday_week": 1, "temperament": {n: 1.0 for n in care.NEEDS},
         "needs": {n: 70 for n in care.NEEDS}, "trust": 30, "warnings": []}
    p.update(overrides)
    return p


def tuning(preset="Normal"):
    t = care.load_tuning()
    return {**t, **t['presets'][preset], "preset": preset}


NO_RNG = lambda key: random.Random(key)


class Rules(unittest.TestCase):
    def test_stress_sinks_needs_and_calm_players_settle(self):
        t = tuning()
        calm, stressed = player("calm"), player("stressed", injured=True, starter=True, blocked=True, distance=2)
        for week in range(20):
            care.run_week([calm, stressed], {"week": week}, t, [], {}, NO_RNG)
        settle = t['staff_target'] - t['drain']['health'] / t['staff_rate'] * (1 - t['trust_drain_relief'] * 0.3)
        self.assertAlmostEqual(calm['needs']['health'], settle, delta=1)
        self.assertGreater(calm['needs']['health'], t['low_need'])
        self.assertLess(stressed['needs']['health'], t['low_need'])
        self.assertLess(stressed['needs']['home'], calm['needs']['home'])

    def test_warnings_come_from_low_needs(self):
        t = tuning()
        fine, low = player(), player(needs={**player()['needs'], "focus": 10, "morale": 10})
        self.assertLess(care.warning_chance(fine, {}, t), 0.01)
        self.assertGreater(care.warning_chance(low, {}, t), 0.15)
        trusting = player(needs=low['needs'], trust=100)
        self.assertLess(care.warning_chance(trusting, {}, t), care.warning_chance(low, {}, t))

    def test_actions_fill_needs_build_trust_and_clear_warnings(self):
        t = tuning()
        p = player(warnings=[{"need": "focus", "text": "x"}], birthday_week=40)
        text = care.apply_action(p, "sit_down", "morale", t, {"week_of_year": 40})
        self.assertEqual(p['needs']['morale'], 100)
        self.assertEqual(p['needs']['focus'], 80)   # the sit-down's focus bonus
        self.assertEqual(p['trust'], 30 + t['actions']['sit_down']['trust'] + t['birthday_trust_bonus'])
        self.assertEqual(p['warnings'], [])
        self.assertIn("Sit-down with Test Player", text)
        visit = player()
        care.apply_action(visit, "home_visit", "academics", t, {})
        self.assertEqual((visit['needs']['home'], visit['needs']['morale'], visit['needs']['academics']), (100, 100, 70))
        with self.assertRaises(ValueError):
            care.apply_action(player(), "bribe", "morale", t, {})

    def test_mentors_and_a_struggling_captain(self):
        t = tuning()
        good, mentee, alone = player("good", **{"class": "Senior"}), player("mentee"), player("alone")
        care.run_week([good, mentee, alone], {"week": 1}, t, [], {"mentee": "good"}, NO_RNG)
        self.assertGreater(mentee['needs']['morale'], alone['needs']['morale'])
        self.assertEqual(good['trust'], 30 + t['mentor']['mentor_trust_per_week'])
        captain, teammate = player("cap", needs={**player()['needs'], "morale": 5}), player("mate")
        events = care.run_week([captain, teammate], {"week": 1}, t, ["cap"], {}, NO_RNG)
        self.assertTrue(any(kind == "council" for _, kind, _ in events))
        self.assertLess(teammate['needs']['morale'], alone['needs']['morale'] - 1)

    def test_care_list_puts_the_neediest_first(self):
        t = {**tuning(), "care_list_size": 2}
        players = [player("ok"), player("low", needs={**player()['needs'], "home": 20}), player("warned", warnings=[{"need": "focus", "text": "x"}])]
        self.assertEqual(care.pick_care_list(players, {}, t, []), ["low", "warned"])


class GamePerformance(unittest.TestCase):
    def test_big_games_lift_needs_and_awards_build_trust(self):
        t = tuning()
        quiet = player("quiet", game={"played": True, "standout": False, "award": None})
        star = player("star", game={"played": True, "standout": True, "award": None})
        potw = player("potw", game={"played": True, "standout": True, "award": "national"})
        care.run_week([quiet, star, potw], {"week": 1}, t, [], {}, NO_RNG)
        self.assertGreater(star['needs']['morale'], quiet['needs']['morale'])
        self.assertGreater(potw['needs']['morale'], 70)   # a Player of the Week award can raise a need
        self.assertEqual(potw['trust'], 30 + t['game']['player_of_week_trust'])

    def test_bench_players_drain_less(self):
        t = tuning()
        played = player("played", game={"played": True, "standout": False, "award": None})
        bench = player("bench", game={"played": False, "standout": False, "award": None})
        on, off = care.drain_for(played, {}, t), care.drain_for(bench, {}, t)
        self.assertLess(off['health'], on['health'])
        self.assertLess(off['morale'], on['morale'])
        self.assertEqual(off['academics'], on['academics'])   # class is class
        self.assertEqual(care.drain_for(player(game=None), {}, t), on)   # no game that week (a bye): nobody counts as benched


class TeamSuccess(unittest.TestCase):
    def test_wins_streaks_and_rankings_lift_everyone(self):
        t = tuning()
        tt = t['team']
        boost, reasons = care.team_boost({"won": True, "streak": 12, "rank": 16}, t)
        self.assertEqual(boost, {"morale": tt['win_morale'] + tt['streak_cap'] + tt['ranked_morale'], "focus": tt['win_focus']})
        boost, reasons = care.team_boost({"won": True, "streak": 10, "rank": 23, "first_ranked": True}, t)
        self.assertEqual(boost['morale'], tt['win_morale'] + tt['streak_cap'] + tt['ranked_morale'] + tt['first_ranked_morale'])
        self.assertIn("cracking the poll for the first time", reasons)
        self.assertEqual(care.team_boost({"lost": True, "streak": 0}, t), ({}, []))
        self.assertEqual(care.a_or_an(11) + " " + care.a_or_an(12), "an a")
        p = player(needs={n: 60 for n in care.NEEDS})
        events = care.run_week([p], {"week": 1, "won": True, "streak": 12, "rank": 16}, t, [], {}, NO_RNG)
        self.assertGreater(p['needs']['morale'], 60)   # a winning, ranked team's morale goes up
        self.assertTrue(any(kind == "team" for _, kind, _ in events))

    def test_team_success_fills_up_to_the_ceiling_but_awards_go_past_it(self):
        t = tuning()
        ceiling = t['team']['ceiling']
        p = player(needs={n: ceiling - 1 for n in care.NEEDS})
        care.run_week([p], {"week": 1, "won": True, "streak": 12, "rank": 16}, t, [], {}, NO_RNG)
        self.assertLessEqual(p['needs']['morale'], ceiling)
        star = player(needs={n: ceiling - 1 for n in care.NEEDS}, game={"played": True, "standout": True, "award": "national"})
        care.run_week([star], {"week": 1, "won": True, "streak": 12, "rank": 16}, t, [], {}, NO_RNG)
        self.assertGreater(star['needs']['morale'], ceiling)

    def test_standing_from_the_schedule_and_polls(self):
        conn = database.get_db_connection()
        for table in ("schedule_tracking", "league_polls", "league_teams"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO league_teams (team_id, name, is_user) VALUES (142, 'Wyoming', 1)")
        conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score) VALUES (?, 'X', 1, ?, ?)",
                         [(1, 10, 20), (2, 30, 3), (3, 30, 3), (4, 30, 3)])
        conn.executemany("INSERT INTO league_polls (poll_week, team_id, media_rank) VALUES (?, 142, ?)", [(1, 40), (2, 24), (3, 14)])
        conn.commit()
        conn.close()
        schedule = {g['week_id']: g for g in database.query_full_schedule()}
        pick = lambda d: {k: d[k] for k in ("streak", "rank", "first_ranked", "milestone") if k in d}
        self.assertEqual(pick(care.team_standing(4, schedule)), {"streak": 2, "rank": 24, "first_ranked": True})
        self.assertEqual(pick(care.team_standing(5, schedule)), {"streak": 3, "rank": 14, "milestone": 15})


class SeasonMilestones(unittest.TestCase):
    def test_title_game_championship_and_bowl_lift_once_a_season(self):
        conn = database.get_db_connection()
        for table in ("schedule_tracking", "league_polls", "league_teams", "league_games", "care_state"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO league_teams (team_id, name, short_name, is_user, conference) VALUES (142, 'Wyoming', 'WYO', 1, 'MW')")
        conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, game_date) VALUES (?, ?, ?, ?, ?, ?)",
                         [(10, "UNLV Rebels", 1, 35, 28, "2026-11-07"), (13, "UConn Huskies", 1, 45, 0, "2026-11-28"),
                          (15, "UNLV Rebels", 0, None, None, "2026-12-05")])
        conn.commit()
        conn.close()
        schedule = {g['week_id']: g for g in database.query_full_schedule()}
        standing = care.team_standing(15, schedule)
        self.assertEqual((standing['title_game'], standing.get('made_title_game')), ("UNLV Rebels", True))
        boost, reasons = care.team_boost(standing, tuning())
        self.assertIn("making the conference championship game", reasons)
        care.set_state("title_game_2026", 15)   # what advance() records after the week
        self.assertNotIn('made_title_game', care.team_standing(15, schedule))
        group = database.get_db_connection()
        group.execute("UPDATE schedule_tracking SET is_played = 1, wyo_score = 31, opp_score = 24 WHERE week_id = 15")
        group.commit()
        group.close()
        schedule = {g['week_id']: g for g in database.query_full_schedule()}
        self.assertTrue(care.team_standing(16, schedule).get('conference_champs'))

    def test_a_playoff_berth_counts_instead_of_a_bowl(self):
        conn = database.get_db_connection()
        for table in ("league_teams", "league_bowls", "league_games", "care_state", "schedule_tracking"):
            conn.execute(f"DELETE FROM {table}")
        conn.execute("INSERT INTO league_teams (team_id, name, short_name, is_user) VALUES (142, 'Wyoming', 'WYO', 1)")
        conn.execute("INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played) VALUES (925, 17, 'BowlSeason1', 61, 142, 0)")
        conn.execute("INSERT INTO league_bowls (game_id, week, week_type, name, home_id, away_id, played) VALUES (925, 17, 'BowlSeason1', 'CFP First Round', 61, 142, 0)")
        conn.execute("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, game_date) VALUES (17, 'LSU Tigers', 0, '2026-12-19')")
        conn.commit()
        conn.close()
        standing = care.team_standing(17, {g['week_id']: g for g in database.query_full_schedule()})
        self.assertTrue(standing.get('playoff_berth'))
        self.assertNotIn('bowl_berth', standing)
        self.assertIn("a College Football Playoff berth", care.team_boost(standing, tuning())[1])
        self.assertEqual(league.bowl_name(142, 17), "CFP First Round")
        self.assertTrue(league.is_playoff("CFP First Round") and not league.is_playoff("Sun Bowl"))
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_bowls")   # later tests would think their team is on a playoff run
        conn.execute("DELETE FROM league_games")
        conn.commit()
        conn.close()

    def test_a_playoff_win_lifts_home_and_a_run_eases_holiday_homesickness(self):
        t = tuning()
        boost, reasons = care.team_boost({"playoff_win": "CFP First Round"}, t)
        self.assertEqual(boost['home'], t['team']['playoff_win_home'])
        far = player(distance=2)
        alone = care.drain_for(far, {"holiday": True}, t)['home']
        alive = care.drain_for(far, {"holiday": True, "postseason_alive": True}, t)['home']
        self.assertLess(alive, alone)
        self.assertEqual(care.drain_for(far, {"holiday": True, "postseason_alive": True, "playoff_alive": True}, t)['home'], 0)   # a playoff run: no homesickness

    def test_players_riding_high_dont_send_worried_texts(self):
        import care_messages, random
        t = tuning()
        high = player("high", needs={**{n: 50 for n in care.NEEDS}, "morale": 92})       # slipping home life, but on a high
        red = player("red", needs={**{n: 50 for n in care.NEEDS}, "morale": 92, "home": 20})   # in the red: still texts
        low = player("low", needs={n: 45 for n in care.NEEDS})
        picked = [p['save_id'] for p in care_messages.texters([high, red, low], t, lambda k: random.Random(k))]
        self.assertEqual(sorted(picked), ["low", "red"])

    def test_lore_facts_for_the_writers(self):
        import lore
        conn = database.get_db_connection()
        conn.execute("DELETE FROM league_teams")
        conn.execute("INSERT INTO league_teams (team_id, name, short_name, is_user, conference) VALUES (142, 'Wyoming', 'WYO', 1, 'MW')")
        conn.commit()
        conn.close()
        self.assertEqual(lore.conference_name(), "Mountain West")
        self.assertIn("never won a Mountain West title", lore.context())


class Stored(unittest.TestCase):
    def setUp(self):
        conn = database.get_db_connection()
        for table in ("care_state", "care_players", "care_warnings", "care_log", "care_council", "care_mentors", "care_messages", "care_emails",
                      "schedule_tracking", "team_roster"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_score, opp_score, site, game_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(1, "Utah Utes", 1, 31, 10, "Home", "2026-09-05"), (2, "Utah State Aggies", 0, None, None, "Away", "2026-09-12")])
        conn.commit()
        conn.close()
        conn = roster.get_connection()
        conn.executemany("INSERT INTO team_roster (save_id, player_name, position, health_status, overall, class_year, home_state) VALUES (?, ?, ?, 'Healthy', ?, ?, ?)",
                         [("qb1", "Senior Quarterback", "QB", 80, "Senior", "Wyoming"), ("qb2", "Young Quarterback", "QB", 66, "Freshman", "Texas"),
                          ("wr1", "Wide Receiver", "WR", 75, "Junior", "Colorado")])
        conn.commit()
        conn.close()

    def test_dashboard_actions_council_mentor_and_preset(self):
        d = care.dashboard()
        self.assertEqual((d['week'], d['hours'], d['hours_total']), (2, care.load_tuning()['hours'], care.load_tuning()['hours']))
        everyone = [p for g in d['groups'].values() for p in g]
        self.assertEqual({p['save_id'] for p in everyone}, {"qb1", "qb2", "wr1"})
        self.assertTrue(all(p['change'] is None for p in everyone))   # no weekly update yet, so no arrows
        with self.assertRaises(ValueError):
            care.act("qb2", "council", "focus")   # no captains yet
        d = care.set_council("qb1", True)
        self.assertEqual([p['save_id'] for p in d['council']], ["qb1"])
        d = care.act("qb2", "council", "focus")
        self.assertEqual(d['hours'], d['hours_total'] - 1)
        self.assertIn("via Senior Quarterback", d['log'][0]['text'])
        d = care.set_mentor("qb2", "qb1")
        self.assertEqual([(m['mentor']['name'], m['mentee']['name']) for m in d['mentors']], [("Senior Quarterback", "Young Quarterback")])
        with self.assertRaises(ValueError):
            care.set_mentor("qb2", "qb2")
        with self.assertRaises(ValueError):
            care.act("wr1", "bribe", "home")
        d = care.set_preset("Demanding")
        self.assertEqual((d['preset'], d['hours_total']), ("Demanding", care.load_tuning()['presets']['Demanding']['hours']))
        with self.assertRaises(ValueError):
            care.set_preset("Impossible")

    def test_advance_runs_missed_weeks_and_resets_hours(self):
        care.advance(2)
        care.act("wr1", "text", "morale")
        care.advance(4)
        d = care.dashboard()
        self.assertEqual((d['week'], d['hours']), (4, d['hours_total']))
        everyone = [p for g in d['groups'].values() for p in g]
        self.assertTrue(all(p['needs']['morale'] < 100 for p in everyone))
        self.assertTrue(all(set(p['change']) == set(care.NEEDS) for p in everyone))   # what the last weekly update did

    def test_groups_by_urgency(self):
        care.advance(2)
        players = care.load_players()
        for p in players:
            p['needs'] = {n: 80 for n in care.NEEDS}
            p['needs']['home'] = {"qb1": 20, "qb2": 45}.get(p['save_id'], 80)
        care.save_players(players, 2)
        groups = {name: [p['save_id'] for p in g] for name, g in care.dashboard()['groups'].items()}
        self.assertEqual(groups, {"now": ["qb1"], "close": ["qb2"], "fine": ["wr1"]})

    def test_game_results_from_stat_lines_and_awards(self):
        conn = database.get_db_connection()
        conn.execute("DELETE FROM player_game_stats")
        conn.execute("DELETE FROM league_awards")
        conn.executemany("INSERT INTO player_game_stats (save_id, week_num, stats_json) VALUES (?, 1, ?)",
                         [("qb1", '{"DOWNSPLAYED": 60, "PASSYARDS": 310}'), ("wr1", '{"DOWNSPLAYED": 40, "RECEIVEYARDS": 30}'), ("qb2", '{"DOWNSPLAYED": 0}')])
        conn.executemany("INSERT INTO league_awards (award_type, week, player_id, team_id) VALUES (?, 1, 'qb1', 1)",
                         [("Offensive_Player_of_Week_Conf",), ("Offensive_Player_of_Week",)])
        conn.commit()
        conn.close()
        results = care.game_results(1, care.load_tuning())
        self.assertEqual(results['qb1'], {"played": True, "standout": True, "award": "national"})
        self.assertEqual(results['wr1'], {"played": True, "standout": False, "award": None})
        self.assertFalse(results['qb2']['played'])
        self.assertEqual(care.game_results(2, care.load_tuning()), {})   # no stat lines: a bye or not synced yet
        care.advance(2)
        care.advance(3)   # week 2's game has no stat lines: no lifts, nobody benched
        care.save_players(care.load_players(), 3)
        flags = {p['save_id']: p['flags'] for g in care.dashboard()['groups'].values() for p in g}
        self.assertNotIn("Player of the Week", flags['qb1'])

    def test_mood_ring_hints_for_the_campus_feed(self):
        care.advance(2)
        players = care.load_players()
        for p in players:
            p['needs'] = {n: 70 for n in care.NEEDS}
        by_id = {p['save_id']: p for p in players}
        by_id['qb1']['needs']['focus'] = 20      # a starter in the red
        by_id['wr1']['needs']['morale'] = 95     # a starter riding high
        by_id['qb2']['needs']['home'] = 10       # a backup: fans wouldn't notice
        care.save_players(players, 2)
        self.assertEqual([(p['save_id'], sign) for p, sign in care.mood_hints()],
                         [("qb1", care.MOOD_SIGNS['focus']), ("wr1", "is all smiles and riding high")])
        context = care.mood_context()
        self.assertIn("Senior Quarterback (QB) seems off and distracted lately", context)
        self.assertIn("no rumors", context)

    def slip(self, needs):
        """Sets every player's needs to 70 except the given {save_id: {need: value}}."""
        players = care.load_players()
        for p in players:
            p['needs'] = {n: 70 for n in care.NEEDS}
            p['needs'].update(needs.get(p['save_id'], {}))
        care.save_players(players, int(care.get_state("week")))

    def test_texts_replies_and_left_on_read(self):
        care.advance(2)
        self.slip({"qb2": {"home": 30}, "wr1": {"focus": 50}})
        care.advance(3)
        d = care.dashboard()
        waiting = {t['save_id']: t for t in d['phone'] if t['waiting']}
        self.assertEqual(set(waiting), {"qb2", "wr1"})   # qb1 is fine: no text
        self.assertEqual(d['unread']['texts'], 2)
        self.assertIn(waiting['qb2']['messages'][0]['text'], care_messages.TEXTS['home']['low'])
        hours = d['hours']
        d = care_messages.reply(waiting['qb2']['waiting']['message_id'], "call")
        self.assertEqual(d['hours'], hours - 2)
        self.assertEqual(d['unread']['texts'], 1)
        with self.assertRaises(ValueError):
            care_messages.reply(waiting['qb2']['waiting']['message_id'], "call")   # already answered
        trust = {p['save_id']: p['trust'] for p in care.load_players()}['wr1']
        care.advance(4)   # wr1's text was never answered
        wr1 = next(p for p in care.load_players() if p['save_id'] == "wr1")
        self.assertEqual(wr1['trust'], trust - care.load_tuning()['phone']['unanswered_trust'])
        thread = next(t for t in care.dashboard()['phone'] if t['save_id'] == "wr1")
        self.assertEqual(thread['messages'][0]['status'], "missed")

    def test_a_bye_week_catch_up_is_fair(self):
        care.advance(2)
        self.slip({"wr1": {"focus": 40}})
        trust = {p['save_id']: p['trust'] for p in care.load_players()}
        conn = database.get_db_connection()
        conn.execute("INSERT INTO player_game_stats (save_id, week_num, stats_json) VALUES ('wr1', 2, '{\"DOWNSPLAYED\": 50, \"RECEIVEYARDS\": 150}')")
        conn.commit()
        conn.close()
        care.advance(4)   # week 3 was a bye: one sync covers weeks 3 and 4
        texts = league.query_rows("SELECT week, status FROM care_messages")
        self.assertTrue(texts and all(t['week'] == 4 and t['status'] == "open" for t in texts))   # nothing made, and missed, in week 3
        self.assertEqual({p['save_id']: p['trust'] for p in care.load_players()}, trust)           # so nobody was left on read
        wr1 = next(p for g in care.dashboard()['groups'].values() for p in g if p['save_id'] == "wr1")
        self.assertGreater(wr1['change']['focus'], 0)   # week 2's big game still shows, though week 4's update came after the bye
        conn = database.get_db_connection()
        conn.execute("DELETE FROM player_game_stats")
        conn.commit()
        conn.close()

    def test_texts_are_rewritten_in_the_players_voice(self):
        import json, time
        from unittest import mock
        import team_board
        care.advance(2)
        self.slip({"qb2": {"home": 30}, "wr1": {"focus": 50}})
        care.advance(3)
        self.assertEqual(team_board.voice("qb2"), team_board.voice("qb2"))   # stable for the whole dynasty
        rewrites = {"texts": [{"id": 1, "text": "miss my folks bad this week coach"}, {"id": 2, "text": "had 3 bad reps today"}]}
        with mock.patch("ai_engine.call_ollama", return_value=json.dumps(rewrites)) as call:
            self.assertTrue(care_messages.start_voicing("test-model"))
            for _ in range(200):
                if not care_messages._voicing['running']:
                    break
                time.sleep(0.02)
        self.assertIn("how he texts:", call.call_args.args[1])
        rows = league.query_rows("SELECT save_id, text, template, voiced FROM care_messages ORDER BY message_id")
        self.assertEqual((rows[0]['text'], rows[0]['voiced']), ("miss my folks bad this week coach", 1))
        self.assertEqual(rows[1]['voiced'], 2)                    # a rewrite with an invented number keeps the template
        self.assertEqual(rows[1]['text'], rows[1]['template'] or rows[1]['text'])
        self.assertFalse(care_messages.start_voicing("test-model"))   # nothing left to voice

    def test_typed_replies_count_as_the_action_their_tone_matches(self):
        import json
        from unittest import mock
        self.assertEqual([care_messages.guess_action(t) for t in ("come by my office tomorrow", "I'll call you tonight",
                                                                  "deal with it", "proud of you, hang in there")],
                         ["sit_down", "call", "not_now", "text"])
        care.advance(2)
        self.slip({"qb2": {"home": 30}, "wr1": {"focus": 50}})
        care.advance(3)
        waiting = {t['save_id']: t['waiting']['message_id'] for t in care.dashboard()['phone'] if t['waiting']}
        with mock.patch("ai_engine.call_ollama", return_value=json.dumps({"action": "text", "followup": "see you tomorrow coach"})):
            d = care_messages.reply_text(waiting['qb2'], "come by my office tomorrow", "test-model")
        self.assertEqual((d['typed']['action'], d['hours']), ("sit_down", d['hours_total'] - 3))   # the words win over the model
        thread = next(t for t in d['phone'] if t['save_id'] == "qb2")
        self.assertEqual((thread['messages'][-1]['reply'], thread['messages'][-1]['followup']), ("come by my office tomorrow", "see you tomorrow coach"))
        care.set_state("hours", 1)
        with mock.patch("ai_engine.call_ollama", side_effect=RuntimeError("down")):
            d = care_messages.reply_text(waiting['wr1'], "give me a call later", "test-model")
        self.assertEqual(d['typed']['action'], "text")   # a call steps down to a text when the hours run short
        with self.assertRaises(ValueError):
            care_messages.reply_text(waiting['wr1'], "again", "test-model")

    def test_not_now_is_free_but_costs_trust(self):
        care.advance(2)
        self.slip({"wr1": {"morale": 40}})
        care.advance(3)
        d = care.dashboard()
        message = next(t for t in d['phone'] if t['save_id'] == "wr1")['waiting']['message_id']
        before = next(p for p in care.load_players() if p['save_id'] == "wr1")['trust']
        d = care_messages.reply(message, "not_now")
        self.assertEqual(d['hours'], d['hours_total'])
        self.assertEqual(next(p for p in care.load_players() if p['save_id'] == "wr1")['trust'], before - care.load_tuning()['phone']['not_now_trust'])

    def test_staff_emails_and_their_actions(self):
        care.advance(2)
        self.slip({"qb2": {"academics": 30}, "wr1": {"academics": 40}})
        care.advance(3)
        d = care.dashboard()
        advisor = next(e for e in d['inbox'] if e['sender'] == "Academic Advisor")
        self.assertIn("Young Quarterback (QB)", advisor['body'])
        self.assertEqual([a['label'] for a in advisor['actions']], ["Tutor for Young Quarterback", "Tutor for Wide Receiver", "Study hall for all of them"])
        academics = {p['save_id']: p['needs']['academics'] for p in care.load_players()}
        d = care_messages.email_action(advisor['email_id'], "Study hall for all of them")
        after = {p['save_id']: p for p in care.load_players()}
        self.assertEqual(after['qb2']['needs']['academics'], academics['qb2'] + 10)
        self.assertEqual(after['wr1']['needs']['academics'], academics['wr1'] + 10)
        self.assertEqual(d['hours'], d['hours_total'] - 2)
        advisor = next(e for e in d['inbox'] if e['email_id'] == advisor['email_id'])
        self.assertEqual(len(advisor['actions']), 2)   # the tutors are still on offer
        d = care_messages.email_action(advisor['email_id'], "read")
        self.assertEqual(next(e for e in d['inbox'] if e['email_id'] == advisor['email_id'])['status'], "read")
        care.advance(4)
        self.assertTrue(all(e['status'] != "open" or e['week'] == 4 for e in care.dashboard()['inbox']))   # last week's expired

    def test_routes_and_simulator(self):
        from app import app
        client = app.test_client()
        host = {"Host": "127.0.0.1:5000"}
        self.assertTrue(client.get("/care", headers=host).get_json()['started'])
        bad = client.post("/care/act", json={"save_id": "wr1", "action": "bribe", "need": "home"}, headers=host)
        self.assertEqual(bad.status_code, 400)
        sim = client.post("/care/simulate", json={"preset": "Normal", "weeks": 4}, headers=host).get_json()
        self.assertEqual((sim['ignore']['policy'], sim['care']['policy'], sim['care']['weeks']), ("ignore", "care", 4))
        self.assertGreaterEqual(sim['care']['average_need'], sim['ignore']['average_need'])
        self.assertIsNone(sim['ignore']['trust_of_players_cared_for'])
        self.assertGreater(sim['care']['trust_of_players_cared_for'], care.load_tuning()['start_trust'])   # texts, calls and sit-downs build trust
        self.assertEqual(client.post("/care/nope", json={}, headers=host).status_code, 404)


if __name__ == "__main__":
    unittest.main()
