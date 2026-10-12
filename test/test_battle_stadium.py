from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from pcrscript import news
from pcrscript.constants import SERVER_TIMEZONE as CN
from pcrscript.game_ui import battle_stadium as field
from pcrscript.game_ui.guide_vision import GuideText, formation_team
from pcrscript.tasks.strategy_document import missing_fields
from pcrscript.game_ui.screen import EventUI
from pcrscript.tasks import BattleStadium, Event
from pcrscript.tasks.stadium_strategy import round_scope, source_rejection, parties_for_round, collection_candidate
from pcrscript.tasks.strategy_video import observed_scope, parse_video_source
from pcrscript.tasks.task_battle_stadium import validate_options
from pcrscript.run_session import RunSession, RunCancelled, atomic_json
from stadium_fixtures import home, reward_page, reward_receipt, detail, formation, battle_result
from ui_fixtures import TaskReplayMixin, replay_ui, screen


class StadiumScheduleTests(TestCase):
    def test_challenge_end_keeps_reward_period_and_closing_filters_event(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.create_function('ISO', 1, news._iso_datetime)
            conn.execute('CREATE TABLE dome_schedule_data(schedule_id INTEGER,start_time TEXT,end_time TEXT,close_time TEXT)')
            conn.execute('INSERT INTO dome_schedule_data VALUES(7,?,?,?)',
                         ('2026/10/09 12:00:00', '2026/10/13 23:59:59', '2026/10/17 14:59:59'))
            for day, hour, active in ((9, 11, False), (9, 12, True), (14, 0, True), (17, 15, False)):
                instant = datetime(2026, 10, day, hour, tzinfo=CN)
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return instant.astimezone(tz or CN)
                with self.subTest(day=day, hour=hour), patch.object(news, 'datetime', Clock):
                    event = news._query_battle_stadium(conn)
                    self.assertEqual(event is not None, active)
                    if event:
                        self.assertEqual(event.extras['battle_end'], datetime(2026, 10, 13, 23, 59, 59, tzinfo=CN).timestamp())
                        self.assertEqual(event.extras['schedule_id'], 7)

    def test_optional_table_absence_and_malformed_schema(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            self.assertIsNone(news._query_battle_stadium(conn))
            conn.execute('CREATE TABLE dome_schedule_data(broken INTEGER)')
            with self.assertRaises(sqlite3.OperationalError):
                news._query_battle_stadium(conn)

    def test_invalid_configuration_precedes_network_or_device(self):
        for option in ({'max_battles': True}, {'max_attempts_per_round': 6}, {'allow_local_trials': 1},
                       {'sources': []}, {'sources': {'refresh_media': 'true'}}, {'account_key': ''}, {'auto_equip': 1},
                       {'auto_equip_priorities': {'armor': 'unknown'}},
                       {'auto_equip_priorities': {'armor': 'hp'}}):
            with self.subTest(option=option), patch('pcrscript.news.fetch_event_news') as fetch:
                with self.assertRaises(ValueError):
                    BattleStadium.prepare({'BattleStadium': option})
                fetch.assert_not_called()
        original = {}
        self.assertEqual(validate_options(original)['max_battles'], 36)
        self.assertEqual(original, {})


class StadiumRecognitionTests(TestCase):
    def test_fixed_equipment_chrome_does_not_hide_authored_requirement(self):
        from pcrscript.tasks.strategy_video import text_constraints
        from pcrscript.tasks.strategy_document import Evidence
        anchors=[GuideText(n,1,(10,10,100,20)) for n in ('选择装备','取消','装备确定')]
        chrome=[GuideText('特别装备替换详情',1,(368,138,182,29)),
                GuideText('已选择其他角色装备中的特别装备。',1,(463,556,359,28))]
        requirement=GuideText('特别装备必须使用指定防具',1,(300,300,400,30))
        proof=Evidence('https://example.com/synthetic',image='synthetic.jpg')
        constraints,_=text_constraints(anchors+chrome+[requirement],proof,unsupported_builds=True,stadium=True)
        self.assertEqual([r['text'] for r in constraints],[requirement.text])
        constraints,_=text_constraints(chrome,proof,unsupported_builds=True,stadium=True)
        self.assertEqual(len(constraints),2)
        outside=GuideText(chrome[0].text,1,(20,300,200,30))
        constraints,_=text_constraints(anchors+[outside],proof,unsupported_builds=True,stadium=True)
        self.assertEqual([r['text'] for r in constraints],[outside.text])
        for names,title in (
            (('选择装备','特别装备替换确认','替换特别装备。','关闭','确认'),'特别装备替换确认'),
            (('选择装备','特别装备替换确认','替换特别装备。','关闭','装备确定'),'特别装备替换确认'),
            (('选择装备','特别装备替换详情','取消','全部卸下','稀有度','降序'),'特别装备替换详情')):
            rows=[GuideText(n,1,(368,138,182,29) if '特别装备' in n else (10,10,100,20)) for n in names]
            constraints,_=text_constraints(rows,proof,unsupported_builds=True,stadium=True)
            self.assertEqual(constraints,[])

    def test_dim_combat_probe_preserves_cap_and_existing_nearby_samples(self):
        from pcrscript.tasks.strategy_video import probe_stadium_combat
        samples = [1,4.75,5.75,6.75,7.75]
        probe_stadium_combat(samples,4.75)
        self.assertEqual(samples,[1,4.75,5,5.5,7.75])
        for values in ([1,4.75,5,5.25], [1,4.75,5.75], [1,4.75,5.4,5.45]):
            before = values[:]
            probe_stadium_combat(values,4.75)
            self.assertEqual(values,before)

    def test_gold_combat_row_corrects_bounded_trim_and_still_requires_live_bars(self):
        import cv2 as cv
        image = np.full((540,960,3),220,np.uint8)
        for x,y in zip((430,550,670),(392,395,400)):
            cv.rectangle(image,(x,y),(x+95,y+95),(20,195,245),2)
            cv.rectangle(image,(x,500),(x+95,507),(35,230,50),-1)
        boxes = field.combat_rectangles(image,3)
        self.assertEqual(len(boxes),3)
        self.assertEqual(len({r[1] for r in boxes}),1)
        image[500:508,670:766] = 220
        self.assertEqual(field.combat_rectangles(image,3),[])

    def test_progress_rereads_missing_denominator_without_repairing_ocr_digits(self):
        page = home(stars=47, unlocked=17)
        original = page.text
        page.text = lambda roi=None: original(roi).replace('/54', '154')
        ui = Mock()
        ui.number.side_effect = [17, 47]
        ui.read_region.return_value = screen(('/54获得', 720, 32))
        self.assertEqual(field.progress(ui, page),
                         dict(unlocked=17, rounds=18, stars=47, maximum_stars=54))
        ui.read_region.assert_called_once_with(page, (691, 16, 752, 49), classify=False)
        for text in ('154获得', '/51获得', '获得'):
            ui.number.side_effect = [17, 47]
            ui.read_region.return_value = screen((text, 720, 32))
            self.assertIsNone(field.progress(ui, page))

    def test_source_outcome_requires_recent_combat_and_large_unambiguous_result(self):
        tracker = field.SourceOutcome()
        win = GuideText('WIN!', .99, (450, 100, 400, 100))
        proof = dict(cid=1, seconds=3, image='synthetic.jpg')
        self.assertIsNone(tracker.observe([win], 3, proof))
        tracker.bind('verified-party', 2)
        result = tracker.observe([win], 3, proof)
        self.assertEqual(result[0], 'verified-party')
        self.assertEqual(result[1]['outcome'], 'win')
        self.assertEqual(result[1]['evidence']['method'], 'stadium_result_win')
        for texts, seconds in (([win], 10.1), ([win], 1),
                ([GuideText('WIN', .94, win.rectangle)], 3),
                ([GuideText('WIN', 1, (10, 10, 60, 20))], 3),
                ([win, GuideText('LOSE', 1, win.rectangle)], 3)):
            self.assertIsNone(tracker.observe(texts, seconds, proof))
        for names in (('编组详情', '挑战目标'), ('队伍编组', '当前的成员')):
            tracker.bind('verified-party', 2)
            tracker.observe([GuideText(n, 1, (10, 10, 100, 20)) for n in names], 3, proof)
            self.assertIsNone(tracker.observe([win], 4, proof))
        tracker.bind('verified-party', 2)
        tracker.clear()
        self.assertIsNone(tracker.observe([win], 3, proof))

    def test_source_result_ranking_needs_distinct_high_confidence_frames(self):
        def party(name, outcome=None, seconds=(3, 4), confidence=.99):
            return dict(name=name, task_type='stadium', scope={'round':16},
                source_results=[] if outcome is None else [dict(outcome=outcome,
                    evidence=dict(cid=1, seconds=s, image='synthetic.jpg',
                        method='stadium_result_'+outcome, confidence=confidence)) for s in seconds])
        rows = [party('unknown'), party('duplicate-lose', 'lose', (3, 3)),
                party('lost', 'lose'), party('weak-win', 'win', confidence=.94),
                party('won', 'win')]
        with patch('pcrscript.tasks.stadium_strategy.parties_for_floor',
                   side_effect=lambda report, *a, **k: report['parties']):
            result = parties_for_round(dict(parties=rows), 16)
            self.assertEqual([p['name'] for p in result],
                             ['won', 'unknown', 'duplicate-lose', 'weak-win'])
            self.assertEqual(parties_for_round(dict(parties=rows), 17), [])

    def test_explicit_part_formation_keeps_members_through_loading(self):
        labels = lambda *names: [GuideText(n,1,(10,10,100,20)) for n in names]
        context = field.SourceScope()
        context.resolve({'round':17},True,
            labels('队伍编组','当前的成员','对战对手的队伍','战斗效果'),0,{})
        context.observe_formation([dict(name='合成角色')],0)
        context.resolve({'round':17},True,labels('加载中'),1,{})
        self.assertEqual(context.names,['合成角色'])
        self.assertEqual(context.scope,{'round':17})
        self.assertEqual(context.resolve({},False,[],2,{},combat_scene=True,
            combat_names=['合成角色'])[:2],({'round':17},True))
        context.resolve({},False,[],9,{},combat_scene=True,combat_names=['合成角色'])
        self.assertEqual(context.scope,{})
    def test_blurry_same_detail_title_preserves_existing_roster_only(self):
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context = field.SourceScope()
        controls = labels('取消', '挑战', '挑战目标', '战斗效果')
        context.resolve({'round': 11}, True, controls+labels('编组详情'), 1, {})
        context.resolve({}, False,
                        labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果'), 2, {})
        context.observe_formation([dict(name='合成角色')], 2)
        blurry = controls+[GuideText('编组详情', .92, (60, 50, 180, 40))]
        context.resolve({'round': 11}, True, blurry, 2.5, {})
        self.assertEqual(context.resolve({}, False, [], 4, {}, combat_scene=True,
                                         combat_names=['合成角色'])[:2], ({'round': 11}, True))
        context.resolve({'round': 12}, True, blurry, 5, {})
        self.assertEqual(context.scope, {})
        self.assertFalse(context.resolve({}, False, [], 6, {}, combat_scene=True,
                                         combat_names=['合成角色'])[1])

    def test_large_start_animation_keeps_only_short_context_for_clear_combat(self):
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context = field.SourceScope()
        context.resolve({'round': 9}, True,
                        labels('编组详情', '取消', '挑战', '战斗效果'), 1, {})
        context.resolve({}, False,
                        labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果'), 2, {})
        context.observe_formation([dict(name='合成角色')], 2)
        intro = [GuideText('开始', .99, (346, 170, 621, 330))]
        self.assertEqual(context.resolve({}, False, intro, 4, {})[:2], ({}, False))
        self.assertEqual(context.resolve({}, False, [], 5, {}, combat_scene=True,
                                         combat_names=['合成角色'])[:2], ({'round': 9}, True))
        self.assertFalse(context.resolve({}, False, intro, 9.9, {})[1])
        self.assertFalse(context.resolve({}, False, [], 10.1, {}, combat_scene=True,
                                         combat_names=['合成角色'])[1])

    def test_missing_detail_round_header_requires_explicit_region_reread(self):
        s = screen(('编组详情', 90, 50), ('挑战目标', 130, 322),
                   ('战斗效果', 680, 335))
        ui = Mock()
        ui.read_region.return_value = screen(('回合7', 200, 50))
        self.assertIsNone(field.round_number(s))
        self.assertEqual(field.round_number(s, ui), 7)
        ui.read_region.assert_called_once_with(s, (140, 20, 300, 80), classify=False)
        ui.read_region.return_value = screen(('回合', 200, 50))
        self.assertIsNone(field.round_number(s, ui))
        ui.reset_mock()
        self.assertIsNone(field.round_number(home(), ui))
        ui.read_region.assert_not_called()

    def test_saved_party_dialog_and_start_fades_keep_only_the_bound_round(self):
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context = field.SourceScope()
        detail = labels('编组详情', '取消', '挑战', '挑战目标', '战斗效果')
        context.resolve({'round': 17}, True, detail, 1, {})
        context.resolve({}, False, labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果'), 2, {})
        context.observe_formation([dict(name='旧角色')], 2)
        # Loading a saved roster clears the old team but keeps the round.
        self.assertEqual(context.resolve({}, False, labels('我的队伍一览', '呼出此编组', '关闭'), 3, {})[:2],
                         ({}, False))
        self.assertEqual((context.scope, context.names), ({'round': 17}, []))
        # A scrolled roster can hide the opponent label; bottom controls remain.
        scrolled = labels('队伍编组', '当前的成员', '战斗效果', '取消', '战斗开始')
        self.assertEqual(context.resolve({}, False, scrolled, 4, {})[:2], ({'round': 17}, True))
        context.observe_formation([dict(name='合成角色')], 4)
        # The post-start detail flash may leave its badge unreadable.
        unreadable = detail+[GuideText('小号', .71, (330, 79, 51, 26))]
        self.assertEqual(context.resolve({}, False, unreadable, 5, {})[:2], ({}, False))
        context.resolve({}, False, labels('加载中'), 6, {})
        self.assertEqual(context.resolve({}, False, [GuideText('水印', .9, (900, 10, 300, 50))], 6.5, {})[:2],
                         ({}, False))
        self.assertEqual(context.resolve({}, False, [], 7, {}, combat_scene=True,
                                         combat_names=['合成角色'])[:2], ({'round': 17}, True))
        # Another round's saved-party dialog cannot keep the old context.
        context.resolve({'round': 18}, True, labels('我的队伍一览', '呼出此编组'), 8, {})
        self.assertEqual(context.scope, {})

    def test_dim_loading_hint_retains_deadline_without_supplying_scope_proof(self):
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context = field.SourceScope()
        context.resolve({'round': 7}, True,
                        labels('编组详情', '取消', '挑战', '战斗效果'), 1, {})
        context.resolve({}, False,
                        labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果'), 2, {})
        context.observe_formation([dict(name='合成角色')], 2)
        dim = [GuideText('加载中.', .89, (1025, 635, 140, 45))]
        self.assertEqual(context.resolve({}, False, dim, 3, {})[:2], ({}, False))
        self.assertEqual(context.resolve({}, False, [], 4, {}, combat_scene=True,
                                         combat_names=['合成角色'])[:2], ({'round': 7}, True))
        # A weak loading observation does not renew battle authorization.
        self.assertFalse(context.resolve({}, False, dim, 11, {})[1])
        self.assertFalse(context.resolve({}, False, [], 12, {}, combat_scene=True,
                                         combat_names=['合成角色'])[1])

    def test_gold_combat_cards_need_life_bars_exact_count_and_regular_row(self):
        import cv2 as cv
        image = np.full((540, 960, 3), 220, np.uint8)
        for x in (554, 674):
            cv.rectangle(image, (x, 394), (x+95, 489), (40, 100, 160), 2)
            cv.rectangle(image, (x, 497), (x+95, 508), (30, 210, 70), -1)
        self.assertEqual(len(field.combat_rectangles(image, 2)), 2)
        self.assertEqual(field.combat_rectangles(image, 1), [])
        image[492:] = 220
        self.assertEqual(field.combat_rectangles(image, 2), [])

    def test_inset_combat_outline_and_dead_extra_member_do_not_change_team_count(self):
        import cv2 as cv
        image = np.full((540, 960, 3), 220, np.uint8)
        cv.rectangle(image, (557, 398), (644, 483), (90, 160, 190), 1)
        cv.rectangle(image, (674, 394), (769, 489), (40, 100, 160), 2)
        for x in (554, 674):
            cv.rectangle(image, (x, 497), (x+95, 508), (30, 210, 70), -1)
        self.assertEqual(len(field.combat_rectangles(image, 2)), 2)
        # A dead third card remains part of the visible combat roster.
        cv.rectangle(image, (434, 394), (529, 489), (40, 100, 160), 2)
        self.assertEqual(field.combat_rectangles(image, 2), [])

    def test_supported_goals_require_all_three_and_reject_unknown_conditions(self):
        self.assertEqual(len(field.challenge_goals(detail())), 3)
        labels = [('在战斗剩余时间为1:00以上的情况下获胜', 235, 348),
                  ('在战斗剩余时间为0:45以上的情况下获胜', 235, 375),
                  ('在无法战斗的角色为0人的情况下获胜', 235, 399)]
        self.assertEqual(len(field.challenge_goals(screen(*labels))), 3)
        third = [('在我方总生命值为70%以上的情况下获胜', 235, 348),
                 labels[2], ('在无法战斗的角色为1人以下的情况下获胜', 235, 399)]
        third[1] = (third[1][0], 235, 375)
        self.assertEqual(len(field.challenge_goals(screen(*third))), 3)
        labels[2] = ('使用指定角色获胜', 235, 399)
        self.assertIsNone(field.challenge_goals(screen(*labels)))

    def test_near_full_hp_goal_wording_preserves_threshold_and_rejects_unsupported_relations(self):
        labels = [('在战斗剩余时间为1:00以上的情况下获胜', 235, 348),
                  ('我方总生命值在99%以上可获胜', 235, 375),
                  ('在我方总生命值为80%以上的情况下获胜', 235, 399)]
        self.assertIn('我方总生命值在99%以上可获胜', field.challenge_goals(screen(*labels)))
        for text in ('我方总生命值在99%以下可获胜', '我方总生命值在101%以上可获胜'):
            labels[1] = (text, 235, 375)
            self.assertIsNone(field.challenge_goals(screen(*labels)))

    def test_full_life_bar_nominates_missing_badge_merged_card(self):
        import cv2 as cv
        image = np.full((540, 960, 3), 220, np.uint8)
        cv.rectangle(image, (554, 394), (649, 489), (40, 100, 160), 2)
        for x in (557, 675):
            cv.rectangle(image, (x, 499), (x+91, 506), (30, 210, 70), -1)
        self.assertEqual(len(field.combat_rectangles(image, 2)), 2)
        image[499:507, 675:767] = 220
        self.assertEqual(field.combat_rectangles(image, 2), [])

    def test_damaged_life_outline_nominates_card_but_dead_bar_does_not(self):
        import cv2 as cv
        image = np.full((540, 960, 3), 220, np.uint8)
        cv.rectangle(image, (554, 394), (649, 489), (40, 100, 160), 2)
        cv.rectangle(image, (557, 499), (648, 506), (30, 210, 70), -1)
        cv.rectangle(image, (673, 499), (767, 507), (80, 80, 80), -1)
        cv.rectangle(image, (675, 501), (740, 505), (30, 210, 70), -1)
        # A second TP outline below the life bar cannot shift the missing
        # portrait proposal downward, even when its fill is depleted.
        cv.rectangle(image, (673, 513), (767, 521), (80, 80, 80), -1)
        self.assertEqual(len(field.combat_rectangles(image, 2)), 2)
        self.assertEqual(field.combat_rectangles(image, 1), [])
        cv.rectangle(image, (673, 499), (767, 507), (80, 80, 80), -1)
        self.assertEqual(field.combat_rectangles(image, 2), [])

    def test_dim_source_hud_needs_two_hp_bars_and_timer_and_keeps_original_deadline(self):
        import cv2 as cv
        image = np.full((540,960,3),10,np.uint8)
        cv.rectangle(image,(120,28),(380,34),(0,28,36),-1)
        cv.rectangle(image,(540,28),(800,34),(0,28,36),-1)
        timer = [GuideText('1:30',1,(630,60,50,20))]
        self.assertTrue(field.source_combat_hud(image,timer))
        self.assertFalse(field.source_combat_hud(image,[]))
        image[:,500:] = 10
        self.assertFalse(field.source_combat_hud(image,timer))
        labels = lambda *names:[GuideText(n,1,(10,10,100,20)) for n in names]
        context = field.SourceScope()
        context.resolve({'round':10},True,labels('编组详情','挑战目标','战斗效果'),1,{})
        context.resolve({},False,labels('队伍编组','当前的成员','对战对手的队伍','战斗效果'),2,{})
        context.observe_formation([dict(name='合成角色')],2)
        self.assertFalse(context.resolve({},False,timer,5,{},combat_scene=True)[1])
        self.assertEqual(context.names,['合成角色'])
        self.assertTrue(context.resolve({},False,[],6,{},combat_scene=True,combat_names=['合成角色'])[1])
        self.assertFalse(context.resolve({},False,timer,11,{},combat_scene=True)[1])
        self.assertEqual(context.names,[])

    def test_loading_and_same_detail_preserve_roster_but_other_round_resets_it(self):
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context = field.SourceScope()
        d = labels('编组详情', '取消', '挑战', '战斗效果', '回合2')
        f = labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果')
        context.resolve({'round': 2}, True, d, 1, {})
        context.resolve({}, False, f, 2, {})
        context.observe_formation([dict(name='合成角色')], 2)
        self.assertFalse(context.resolve({'round': 2}, True, d+labels('正在进行数据连接'), 2.25, {})[1])
        context.resolve({'round': 2}, True, d, 2.5, {})
        context.resolve({}, False, labels('加载中...'), 3, {})
        self.assertFalse(context.resolve({}, False, [], 3.75, {}, loading_scene=True)[1])
        self.assertFalse(context.resolve({}, False, [], 3.9, {}, combat_scene=True)[1])
        self.assertEqual(context.resolve({}, False, [], 4, {}, combat_names=['合成角色'], combat_scene=True)[:2],
                         ({'round': 2}, True))
        context.resolve({'round': 3}, True, d, 5, {})
        self.assertFalse(context.resolve({}, False, [], 6, {}, combat_names=['合成角色'], combat_scene=True)[1])

    def test_collection_is_candidate_only_and_excludes_explicit_other_round(self):
        self.assertTrue(collection_candidate('2026年10月斗技场18层全攻略', {'stage': '2'}))
        self.assertFalse(collection_candidate('斗技场 回合1', {'stage': '2'}))
        self.assertEqual(round_scope('2026年10月斗技场18层全攻略'), {})

    def test_equipment_conditions_keep_round_without_extending_combat_deadline(self):
        context = field.SourceScope()
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context.resolve({'round': 18}, True, labels('编组详情', '挑战目标', '战斗效果', '回合18'), 1, {})
        context.resolve({}, False, labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果'), 5, {})
        context.observe_formation([dict(name='合成角色')], 5)
        equipment = labels('选择装备', '特别装备替换详情', '取消', '装备确定')
        self.assertEqual(context.resolve({}, False, equipment, 10, {})[:2], ({'round': 18}, True))
        self.assertEqual(context.resolve({}, False, equipment, 20, {})[:2], ({'round': 18}, True))
        # Reading equipment cannot turn an expired combat transition into proof.
        self.assertFalse(context.resolve({}, False, [], 21, {}, combat_names=['合成角色'], combat_scene=True)[1])
        self.assertFalse(context.resolve({}, False, equipment, 22, {})[1])

    def test_equipment_return_needs_fresh_same_round_detail_before_combat(self):
        labels=lambda *names:[GuideText(n,1,(10,10,100,20)) for n in names]
        detail=labels('编组详情','挑战目标','战斗效果')
        form=labels('队伍编组','当前的成员','对战对手的队伍','战斗效果')
        gear=labels('特别装备设定','可变更队伍角色的特别装备。','取消','自动装备')
        def prepare():
            context=field.SourceScope()
            context.resolve({'round':18},True,detail,1,{'image':'old.jpg'})
            context.resolve({},False,form,10,{})
            context.observe_formation([dict(name='合成角色')],10)
            context.resolve({},False,gear,24,{})
            return context
        context=prepare()
        self.assertTrue(context.resolve({},False,form,25,{})[1])
        context.observe_formation([dict(name='合成角色')],25)
        self.assertFalse(context.resolve({},False,[],26,{},combat_scene=True,combat_names=['合成角色'])[1])
        context=prepare()
        context.resolve({},False,form,25,{})
        context.observe_formation([dict(name='合成角色')],25)
        self.assertTrue(context.resolve({'round':18},True,detail,26,{'image':'fresh.jpg'})[1])
        scope,verified,proof=context.resolve({},False,[],27,{},combat_scene=True,combat_names=['合成角色'])
        self.assertEqual((scope,verified,proof['image']),({'round':18},True,'fresh.jpg'))
        context=prepare()
        self.assertFalse(context.resolve({},False,form,27,{})[1])
        context=prepare()
        context.resolve({},False,form,25,{})
        context.observe_formation([dict(name='合成角色')],25)
        context.resolve({'round':17},True,detail,26,{'image':'other.jpg'})
        self.assertFalse(context.resolve({},False,[],27,{},combat_scene=True,combat_names=['合成角色'])[1])

    def test_round_context_links_only_adjacent_detail_and_formation(self):
        context = field.SourceScope()
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        d = labels('编组详情', '挑战目标', '战斗效果', '回合1')
        f = labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果', '战斗开始')
        context.resolve({'round': 1}, True, d, 1, {'image': 'synthetic.jpg'})
        scope, verified, proof = context.resolve({}, False, f, 2, {})
        self.assertEqual((scope, verified, proof['method']), ({'round': 1}, True, 'stadium_detail_to_formation'))
        # A pressed/dim start button can disappear while all page landmarks
        # and the final selected portraits remain visible.
        f = [t for t in f if t.text != '战斗开始']
        scope, verified, _ = context.resolve({}, False, f, 2.5, {})
        self.assertEqual((scope, verified), ({'round': 1}, True))
        # Results, unexplained cuts and another detail invalidate the binding.
        context.resolve({}, False, labels('WIN'), 3, {})
        self.assertEqual(context.resolve({}, False, f, 4, {})[:2], ({}, False))
        context.resolve({'round': 1}, True, d, 5, {})
        self.assertEqual(context.resolve({}, False, f, 21, {})[:2], ({}, False))
        context.resolve({'round': 2}, True, d, 22, {})
        self.assertFalse(context.resolve({'round': 1}, True, f, 23, {})[1])

    def test_equipment_condition_can_be_scoped_without_authorizing_unknown_roster(self):
        context = field.SourceScope()
        labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
        context.resolve({'round': 18}, True, labels('编组详情', '挑战目标', '战斗效果'), 1, {})
        context.resolve({}, False, labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果'), 2, {})
        context.observe_formation([], 2)
        equipment = labels('选择装备', '特别装备替换详情', '取消', '装备确定')
        self.assertEqual(context.resolve({}, False, equipment, 3, {})[:2], ({'round': 18}, True))
        # A codec-damaged confirm label does not hide the inventory page.
        equipment = labels('选择装备', '特别装备替换详情', '取消', '全部卸下', '稀有度', '降序')
        self.assertEqual(context.resolve({}, False, equipment, 3.25, {})[:2], ({'round': 18}, True))
        settings = labels('特别装备设定', '可变更队伍角色的特别装备。', '取消', '自动装备', '装备定')
        self.assertEqual(context.resolve({}, False, settings, 3.5, {})[:2], ({'round': 18}, True))
        self.assertFalse(context.resolve({}, False, [], 4, {}, combat_names=['合成角色'], combat_scene=True)[1])

    def test_short_team_requires_verified_empty_slots_and_all_selected_identities(self):
        import cv2 as cv
        image = np.full((540, 960, 3), 220, np.uint8)
        for i in range(2):
            cv.rectangle(image, (48+109*i, 405), (143+109*i, 500), (230, 155, 25), -1)
        texts = [GuideText(n, 1, (1, 1, 100, 20)) for n in ('队伍编组', '当前的成员')]
        matched = [dict(name=f'合成角色{i}', rectangle=[], score=.99) for i in range(2)]
        with patch('pcrscript.game_ui.guide_vision.match_portrait', side_effect=matched):
            self.assertEqual(len(formation_team(image, texts, Mock(), allow_partial=True)), 2)
        with patch('pcrscript.game_ui.guide_vision.match_portrait', return_value=None):
            self.assertEqual(formation_team(image, texts, Mock(), allow_partial=True), [])
        # An ambiguous third slot cannot silently become an empty slot.
        cv.rectangle(image, (276, 430), (295, 459), (230, 155, 25), -1)
        with patch('pcrscript.game_ui.guide_vision.match_portrait') as match:
            self.assertEqual(formation_team(image, texts, Mock(), allow_partial=True), [])
            match.assert_not_called()

    def test_pale_occupied_card_requires_actual_outline_and_high_identity(self):
        import cv2 as cv
        image = np.full((540,960,3),220,np.uint8)
        cv.rectangle(image,(48,405),(143,500),(90,90,90),-1)
        cv.rectangle(image,(70,435),(88,460),(230,155,25),-1)
        texts = [GuideText(n,1,(1,1,100,20)) for n in ('队伍编组','当前的成员')]
        with patch('pcrscript.game_ui.guide_vision.match_portrait',return_value=
                   dict(name='合成浅色角色',score=.99,rectangle=[])) as match:
            self.assertEqual(len(formation_team(image,texts,Mock(),allow_partial=True)),1)
            self.assertEqual(match.call_args.kwargs['minimum'],.92)
        with patch('pcrscript.game_ui.guide_vision.match_portrait',return_value=None):
            self.assertEqual(formation_team(image,texts,Mock(),allow_partial=True),[])

    def test_small_body_scroll_keeps_overlap_and_verifies_thumb_movement(self):
        before = screen(('合成报酬3', 600, 110))
        after = screen(('合成报酬6', 600, 110))
        ui = Mock(width=960, height=540)
        ui.scrollbar_bounds.side_effect = [(75, 125), (96, 146)]
        ui.capture.return_value = after
        self.assertTrue(EventUI.scrollbar(ui, before, field.REWARD_TRACK, 1, content_distance=150))
        ui.swipe.assert_called_once_with((711, 312), (711, 162), duration=500)
        ui.driver.swipe.assert_not_called()

    def test_live_progress_star_colors_and_unknown_are_distinct(self):
        s = home(stars=4, unlocked=3, round_stars=(3, 1, None))
        ui = Mock(number=lambda frame, roi: frame.number(roi))
        self.assertEqual(field.progress(ui, s)['stars'], 4)
        self.assertEqual([r.stars for r in field.rounds(s)], [3, 1, None])
        self.assertIsNone(field.progress(ui, reward_page()))
        inconsistent = home(stars=55)
        self.assertIsNone(field.progress(ui, inconsistent))

    def test_shifted_effect_labels_do_not_count_gold_pedestal_as_star(self):
        s = home(stars=24, unlocked=9, first=7, round_stars=(3,3,0))
        for item in s.items:
            if item.text.startswith('回合'):
                item.box = [[x-26,y] for x,y in item.box]
        s.image[295:315,708:727] = (20,195,245)
        self.assertEqual([r.stars for r in field.rounds(s)], [3,3,0])

    def test_progress_accepts_merged_fraction_without_using_numerator_as_total(self):
        from ui_fixtures import screen
        s = screen(('斗技场', 100, 30), ('进度', 450, 32), ('6/18解锁', 590, 32),
                   ('☆15/54获得', 700, 32), ('报酬', 901, 450))
        ui = Mock()
        ui.number.side_effect = [6, 15]
        self.assertEqual(field.progress(ui, s),
                         dict(unlocked=6, rounds=18, stars=15, maximum_stars=54))
        # Missing numerator remains unknown, even if the fractions are readable.
        ui.number.side_effect = [None, 15]
        self.assertIsNone(field.progress(ui, s))

    def test_reward_scroll_checks_left_targets_when_right_button_text_is_identical(self):
        before, after = reward_page((3, 6, 9)), reward_page((6, 9, 12))
        self.assertEqual(before.text((481, 60, 899, 424)), after.text((481, 60, 899, 424)))
        ui = Mock(width=960, height=540)
        ui.scrollbar_bounds.side_effect = [(75, 125), (96, 146)]
        ui.capture.return_value = after
        self.assertTrue(EventUI.scrollbar(ui, before, field.REWARD_TRACK, 1,
                        content_distance=150, content_roi=(40, 65, 900, 408)))
        ui.driver.swipe.assert_not_called()

    def test_disabled_reward_is_not_received_and_partial_last_row_is_ignored(self):
        rows = field.reward_rows(reward_page())
        self.assertEqual(len(rows), 3)
        self.assertFalse(any(r['received'] or r['claimable'] for r in rows))
        self.assertTrue(all(r['received'] for r in field.reward_rows(reward_page(received=True))))
        self.assertTrue(field.receipt(screen(('收取报酬', 480, 42), ('获得了以下报酬。', 480, 80), ('关闭', 480, 480))))

    def test_home_navigation_cancels_known_stadium_selector_without_claiming(self):
        detail = screen(('编组详情', 90, 50), ('回合1', 200, 50), ('挑战目标', 130, 322),
                        ('战斗效果', 680, 335), ('取消', 650, 450), ('挑战', 830, 450))
        self.assertEqual(field.navigation_exit(detail).text, '取消')
        self.assertIsNone(field.navigation_exit(reward_receipt()))

    def test_source_period_region_and_author_conditions(self):
        start = datetime(2026, 10, 9, 12, tzinfo=CN).timestamp()
        options = dict(period_start=start, period_end=start+5*86400)
        good = dict(title='公主连结 国服 2026年10月斗技场', published_at=start-86400,
                    comment_complete=True, author_comments=[])
        self.assertIsNone(source_rejection(good, options))
        for change in (dict(title='公主连结 日服斗技场'), dict(published_at=start-8*86400),
                       dict(title='2026年9月斗技场'), dict(comment_complete=False),
                       dict(author_comments=[dict(images=['https://example.com/synthetic.png'])])):
            self.assertTrue(source_rejection(dict(good, **change), options))
        self.assertEqual(round_scope('回合18'), {'round': 18})
        self.assertEqual(round_scope('1-18层合集'), {})
        for label in ('第1-18层', '回合1～18合集', '第1套队伍', '回合1及回合2'):
            self.assertEqual(round_scope(label), {})
        self.assertEqual(round_scope('第18层'), {'round': 18})
        self.assertEqual(round_scope('R17',part_title=True), {'round':17})
        self.assertEqual(round_scope('R11b',part_title=True), {'round':11})
        self.assertEqual(round_scope('R17'), {})
        self.assertEqual(observed_scope([GuideText('R17',1,(10,10,50,20))],{'part':'合集'},'stadium'), ({},False))
        self.assertEqual(observed_scope([],{'part':'R17'},'stadium'), ({'round':17},True))
        self.assertEqual(observed_scope([GuideText('回合16',1,(10,10,50,20))],{'part':'R17'},'stadium'),
                         ({'conflict':True},False))
        self.assertEqual(observed_scope([GuideText('回合2', 1, (0, 0, 50, 20))], {'part': '回合1'}, 'stadium'),
                         ({'conflict': True}, False))

    def test_video_pipeline_requires_two_frames_and_exact_round_without_set_controls(self):
        with TemporaryDirectory() as folder:
            boxes = [(190+i*120, 390, 100, 100) for i in range(5)]
            members = [dict(name=f'合成角色{i}', rectangle=list(box), score=.99) for i, box in enumerate(boxes)]
            fields = [GuideText(m['name']+':5星Lv100Rank10技能100专武1有专武2无',
                                1, (0, 150+i*30, 500, 20)) for i, m in enumerate(members)]
            capture = Mock()
            capture.read.side_effect = [(True, np.full((540, 960, 3), v, np.uint8)) for v in (30, 50, 70, 90)]
            source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                          title='公主连结 国服 合成斗技场', pages=[dict(cid=1, part='回合1', duration=4)])
            index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((5, 1728), np.float32))
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.COMBAT_AUDIT_SECONDS', 0), \
                 patch('pcrscript.tasks.strategy_video.frame_texts', return_value=fields+[GuideText('回合1', 1, (30, 50, 80, 20))]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles', return_value=boxes), \
                 patch('pcrscript.tasks.strategy_video.combat_team', return_value=members), \
                 patch('pcrscript.tasks.strategy_video.combat_auto', return_value=None), \
                 patch('pcrscript.tasks.strategy_video.combat_set', return_value=None):
                report = parse_video_source(source, dict(task_type='stadium', area='斗技场', stage='1', parsed_dir=folder),
                    index, api=Mock(), ocr=Mock(), media_fetcher=lambda *a, **k: (Path(folder)/'synthetic.avi', dict(duration=4)))
            self.assertEqual(len(report['parties']), 1)
            self.assertEqual(len(parties_for_round(report, 1)), 1)
            self.assertEqual(parties_for_round(report, 2, allow_local_trials=True), [])
            raw = report['parties'][0]
            self.assertTrue(raw['auto']['value'])
            self.assertTrue(all(m['instant']['value'] for m in raw['members']))
            short = dict(raw, members=raw['members'][:2])
            self.assertEqual(missing_fields(short), [])
            self.assertEqual(len(parties_for_round(dict(parties=[short]), 1)[0].members), 2)
            self.assertTrue(missing_fields(dict(short, task_type='recollection')))
            raw['global_requirements'] = [dict(text='未知装备要求')]
            self.assertEqual(parties_for_round(report, 1, allow_local_trials=True), [])

    def test_compilation_short_party_is_parsed_after_its_round_detail(self):
        with TemporaryDirectory() as folder:
            members = [dict(name=f'合成角色{i}', rectangle=[50+109*i, 405, 96, 96], score=.99) for i in range(2)]
            named = [GuideText(m['name']+':5星Lv100Rank10技能100专武1无专武2无', 1, (0, 150+i*30, 500, 20))
                     for i, m in enumerate(members)]
            labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
            detail_texts = labels('编组详情', '挑战目标', '战斗效果', '回合1')
            formation_texts = labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果', '战斗开始')+named
            source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic',
                          title='公主连结 国服 合成斗技场', pages=[dict(cid=1, part='合集', duration=5)])
            index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((2, 1728), np.float32))
            capture = Mock()
            capture.read.side_effect = [(True, np.full((540, 960, 3), v, np.uint8)) for v in (30, 50, 70, 90)]
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.frame_texts', side_effect=[detail_texts, formation_texts, formation_texts, []]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles', side_effect=lambda *a, **k: [] if k.get('count') else ([m['rectangle'] for m in members] if int(a[0][0,0,0]) == 90 else [])), \
                 patch('pcrscript.tasks.strategy_video.combat_team', side_effect=[[], [], [], members]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.formation_team', side_effect=[[], members, members]):
                report = parse_video_source(source, dict(task_type='stadium', stage='1', parsed_dir=folder), index,
                    api=Mock(), ocr=Mock(), media_fetcher=lambda *a, **k: (Path(folder)/'synthetic.avi', dict(duration=5)))
            parties = parties_for_round(report, 1)
            self.assertEqual(len(parties), 1)
            self.assertEqual(len(parties[0].members), 2)
            self.assertEqual(parties_for_round(report, 2), [])

    def test_compilation_dim_start_keeps_names_until_two_clear_combat_frames(self):
        import cv2 as cv
        with TemporaryDirectory() as folder:
            members = [dict(name=f'合成角色{i}',rectangle=[554+120*i,394,96,96],score=.99) for i in range(2)]
            labels = lambda *names:[GuideText(n,1,(10,10,100,20)) for n in names]
            detail = labels('编组详情','挑战目标','战斗效果','回合10')
            form = labels('队伍编组','当前的成员','对战对手的队伍','战斗效果')
            timer = [GuideText('1:30',1,(630,60,50,20))]
            source = dict(bvid='BVSYNTHETIC',url='https://example.com/synthetic',title='国服斗技场合集',
                          pages=[dict(cid=1,part='合集',duration=6)])
            index = SimpleNamespace(names=[m['name'] for m in members],matrix=np.ones((2,1728),np.float32))
            frames = [np.full((540,960,3),v,np.uint8) for v in (30,40,50,60,70,80,90)]
            cv.rectangle(frames[2],(120,28),(380,34),(0,28,36),-1)
            cv.rectangle(frames[2],(540,28),(800,34),(0,28,36),-1)
            capture = Mock()
            capture.read.side_effect = [(True,f) for f in frames]
            media_fetcher = Mock(return_value=(Path(folder)/'synthetic.avi',dict(duration=6)))
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture',return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.sample_seconds',return_value=[1,2,3,4,5,5.25,5.5]), \
                 patch('pcrscript.tasks.strategy_video.frame_texts',side_effect=[detail,form,timer,[],[],[GuideText('WIN',.99,(450,100,400,100))],[GuideText('WIN',.99,(450,100,400,100))]]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles',side_effect=[[],[],[],[m['rectangle'] for m in members],[m['rectangle'] for m in members],[],[]]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',side_effect=[[],[],[],members,members,[],[]]), \
                 patch('pcrscript.tasks.strategy_video.formation_team',side_effect=[[],members,[],[],[]]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields',return_value=[]):
                report = parse_video_source(source,dict(task_type='stadium',stage='10',parsed_dir=folder,refresh_media=True),index,
                    api=Mock(),ocr=Mock(),media_fetcher=media_fetcher)
            self.assertTrue(media_fetcher.call_args.kwargs['refresh'])
            self.assertEqual(len(report['parties']),1)
            self.assertEqual(report['parties'][0]['scope'],{'round':10})
            self.assertEqual([r['outcome'] for r in report['parties'][0]['source_results']], ['win', 'win'])
            frames = report['parties'][0]['frames']
            self.assertEqual(len(frames),3)
            dim_at = report['pages'][0]['stadium_observations'][2]['seconds']
            self.assertNotIn(dim_at,[f['seconds'] for f in frames])

    def test_short_dim_combat_is_confirmed_before_next_regular_result_sample(self):
        with TemporaryDirectory() as folder:
            members=[dict(name=f'合成角色{i}',rectangle=[190+120*i,392,98,99],score=.99) for i in range(5)]
            labels=lambda *names:[GuideText(n,1,(10,10,100,20)) for n in names]
            detail=labels('编组详情','挑战目标','战斗效果','回合18')
            form=labels('队伍编组','当前的成员','对战对手的队伍','战斗效果')
            source=dict(bvid='BVSYNTHETIC',url='https://example.com/synthetic',title='国服斗技场',
                        pages=[dict(cid=1,part='R18',duration=9)])
            index=SimpleNamespace(names=[m['name'] for m in members],matrix=np.ones((5,1728),np.float32))
            capture=Mock()
            capture.read.side_effect=[(True,np.full((540,960,3),v,np.uint8)) for v in (30,40,50,60,70,80,90)]
            boxes=[m['rectangle'] for m in members]
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture',return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.sample_seconds',return_value=[1,2,2.25,4.75,5.75,6.75,7.75]), \
                 patch('pcrscript.tasks.strategy_video.probe_stadium_transition'), \
                 patch('pcrscript.tasks.strategy_video.frame_texts',side_effect=[detail,form,form,[],[],[],labels('WIN')]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles',side_effect=[[],[],[],boxes,boxes,boxes,[]]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',side_effect=[[],[],[],[],members,members,[]]), \
                 patch('pcrscript.game_ui.battle_stadium.combat_rectangles',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.formation_team',side_effect=[[],members,members,[],[]]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields',return_value=[]):
                report=parse_video_source(source,dict(task_type='stadium',stage='18',parsed_dir=folder),index,
                    api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(Path(folder)/'synthetic.avi',dict(duration=9)))
            self.assertEqual(len(parties_for_round(report,18,allow_local_trials=True)),1)
            times=[call.args[1]/1000 for call in capture.set.call_args_list]
            self.assertEqual(times,[1,2,2.25,4.75,5,5.5,7.75])
            proofs=report['parties'][0]['frames']
            self.assertNotIn(4.75,[f['seconds'] for f in proofs])

    def test_other_round_equipment_conditions_do_not_block_confirmed_first_round(self):
        with TemporaryDirectory() as folder:
            members = [dict(name=f'合成角色{i}', rectangle=[554+120*i, 394, 96, 96], score=.99) for i in range(2)]
            labels = lambda *names: [GuideText(n, 1, (10, 10, 100, 20)) for n in names]
            detail = lambda number: labels('编组详情', '挑战目标', '战斗效果', f'回合{number}')
            form = labels('队伍编组', '当前的成员', '对战对手的队伍', '战斗效果')
            equipment = labels('选择装备', '特别装备替换确认', '替换特别装备。', '关闭', '装备确定')
            source = dict(bvid='BVSYNTHETIC', url='https://example.com/synthetic', title='国服斗技场合集',
                          pages=[dict(cid=1, part='合集', duration=10)])
            index = SimpleNamespace(names=[m['name'] for m in members], matrix=np.ones((2, 1728), np.float32))
            capture = Mock()
            capture.read.side_effect = [(True, np.full((540, 960, 3), v, np.uint8))
                                       for v in (30, 50, 70, 90, 110, 130, 150, 170)]
            with patch('pcrscript.tasks.strategy_video.cv.VideoCapture', return_value=capture), \
                 patch('pcrscript.tasks.strategy_video.sample_seconds', return_value=list(range(8))), \
                 patch('pcrscript.tasks.strategy_video.frame_texts', side_effect=[detail(1), form, form, [], detail(18), form, form, equipment]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles', side_effect=lambda im, **k: [m['rectangle'] for m in members] if im[0,0,0] == 90 else []), \
                 patch('pcrscript.tasks.strategy_video.combat_team', side_effect=[[], [], [], members, [], [], [], []]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields', return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.formation_team', side_effect=[[], members, members, [], members, members, []]):
                report = parse_video_source(source, dict(task_type='stadium', stage='1', parsed_dir=folder), index,
                    api=Mock(), ocr=Mock(), media_fetcher=lambda *a, **k: (Path(folder)/'synthetic.avi', dict(duration=10)))
            self.assertEqual(len(parties_for_round(report, 1, allow_local_trials=True)), 1)
            self.assertEqual(report['parties'][0]['global_requirements'], [])
            self.assertEqual(report['global_requirements'][0]['scope'], {'round': 18})
            # Intermediate formation 18 was never confirmed in combat.
            self.assertEqual(parties_for_round(report, 18, allow_local_trials=True), [])


class StadiumRosterTests(TestCase):
    def test_scan_excludes_enemy_strip_and_preserves_task_readiness_policy(self):
        from pcrscript.tasks.stadium_strategy import StadiumFormation
        roster = StadiumFormation.__new__(StadiumFormation)
        roster.ui = Mock()
        roster.ui.capture.return_value = formation()
        roster.occupied_slots = Mock(return_value=[])
        roster.avatars = SimpleNamespace(names=['合成角色'], query=lambda crops: ['合成角色']*len(crops))
        member = SimpleNamespace(name='合成角色')
        actual = SimpleNamespace(name='合成角色', identity_verified=True)
        roster.inspect = Mock(return_value=actual)
        roster.member_readiness = Mock(return_value=['专武状态未知'])
        with patch('pcrscript.tasks.event_formation.card_rectangles',
                   return_value=[(60,70,100,99),(60,177,100,99)]):
            ready, details = roster._select_by_scrolling(SimpleNamespace(members=[member]))
        self.assertFalse(ready)
        self.assertEqual(details['unready'], [{'character':'合成角色','reasons':['专武状态未知']}])
        roster.member_readiness.assert_called_once_with(member,actual)
        self.assertTrue(all(c.args[0] == (110,226) for c in roster.inspect.call_args_list))
        roster.ui.click.assert_not_called()
        self.assertTrue(all(c.args == ((797,250),(797,340)) for c in roster.ui.swipe.call_args_list))


class StadiumReplayTests(TaskReplayMixin, TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        robot = Mock(driver=Mock(), task_config={'BattleStadium': dict(output=str(self.root), state_dir=str(self.root/'state'))},
                     _task_output=None)
        self.task = BattleStadium(robot)
        self.task.ui = replay_ui(self.root)
        self.task.ui.number.side_effect = lambda s, roi: s.number(roi)
        self.task.ui.scrollbar.return_value = False
        self.event = Event(datetime(2026, 10, 9, 12, tzinfo=CN).timestamp(),
                           datetime(2026, 10, 17, 14, 59, 59, tzinfo=CN).timestamp(), '斗技场',
                           dict(schedule_id=7, battle_end=datetime(2026, 10, 13, 23, 59, 59, tzinfo=CN).timestamp()))
        clock = patch('pcrscript.tasks.task_battle_stadium.time.time', return_value=self.event.startTimestamp+3600)
        clock.start()
        self.addCleanup(clock.stop)
        sleep = patch('pcrscript.tasks.task_battle_stadium.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_source_work_honors_cooperative_stop_without_device_input(self):
        with RunSession('stadium-synthetic', root=self.root/'runs') as session:
            atomic_json(session.path/'control.json', dict(id='synthetic-stop', action='stop'))
            with self.assertRaises(RunCancelled):
                self.task.check()
            self.assertEqual(session.command_id, 'synthetic-stop')
        self.task.ui.click.assert_not_called()

    def test_cancelled_run_persists_status_without_discarding_pending_claim(self):
        self.task.state['pending_claim']={'targets':[3]}
        self.task.enter=Mock(side_effect=RunCancelled('synthetic stop'))
        with self.assertRaises(RunCancelled):
            self.task.run(self.event)
        report=json.loads((self.root/'report.json').read_text(encoding='utf-8'))
        state=json.loads(self.task.state_path.read_text(encoding='utf-8'))
        self.assertEqual(report['status'],'cancelled')
        self.assertEqual(state['pending_claim'],{'targets':[3]})
        self.task.ui.click.assert_not_called()

    def test_unknown_equipment_uses_read_only_character_proof_and_fresh_selection(self):
        self.task.event = self.event
        self.task.report['goals'] = {'1': field.challenge_goals(detail())}
        member = SimpleNamespace(name='合成角色', unique_level=None, unique2_stars=None)
        party = SimpleNamespace(members=[member])
        self.task.formation = Mock(observed={'合成角色': SimpleNamespace(
            name='合成角色', identity_verified=True, unique=None, unique2=None)}, unreleased={})
        self.task.formation.select.side_effect = [(False, {}), (True, {'order': ['合成角色']})]
        self.frames([formation(), formation()])
        with patch.object(self.task, 'open_detail', return_value=detail()), \
             patch('pcrscript.tasks.task_home.ToHomePage') as go_home, \
             patch('pcrscript.game_ui.character_equipment.inspect_unreleased_equipment', return_value={'unreleased': True}) as inspect:
            self.assertTrue(self.task.select_party(field.Round(1, 0, (195, 340)), party)[0])
        self.assertEqual(self.task.formation.select.call_count, 2)
        self.assertIn('合成角色', self.task.formation.unreleased)
        inspect.assert_called_once_with(self.task.ui, '合成角色')
        self.assertEqual(go_home.return_value.run.call_count, 2)
        self.assertNotIn('战斗开始', self.clicks())

    def test_missing_identity_does_not_attempt_equipment_trip(self):
        self.task.formation = Mock()
        self.task.formation.select.return_value = (False, {'unready': [
            {'reasons': ['未在搜索结果中确认该版本的角色']}]})
        with patch('pcrscript.tasks.task_home.ToHomePage') as go_home:
            self.assertFalse(self.task.select_party(field.Round(1, 0, (195, 340)), Mock())[0])
        go_home.assert_not_called()
        self.task.ui.click.assert_not_called()

    def test_source_advancement_excludes_old_candidates_and_keeps_remaining_budget(self):
        self.task.event = self.event
        old = SimpleNamespace(source='https://example.com/old')
        self.task.report['sources'] = {'1:0': {'parties': []}}
        with patch('pcrscript.tasks.task_battle_stadium.parties_for_round', return_value=[old]), \
             patch('pcrscript.tasks.strategy_video.acquire_strategies', return_value={'parties': []}) as acquire:
            self.task.acquire(1, exclude_sources={old.source})
        self.assertEqual(acquire.call_args.args[0]['max_videos'], 3)
        self.assertEqual(acquire.call_args.kwargs['exclude_sources'], {old.source})
        with patch('pcrscript.tasks.strategy_video.acquire_strategies') as acquire, \
             patch('pcrscript.tasks.task_battle_stadium.parties_for_round', return_value=[old]):
            self.assertEqual(self.task.acquire(1, exclude_sources={'a','b','c','d'}), [])
        acquire.assert_not_called()

    def test_unready_party_advances_source_without_spending_battle_attempt(self):
        h = home(unlocked=1,total=1)
        won = home(stars=3,unlocked=1,total=1,round_stars=(3,0,0))
        first = SimpleNamespace(source='https://example.com/first')
        second = SimpleNamespace(source='https://example.com/second')
        self.frames([h])
        self.task.collect = Mock(return_value=True)
        self.task.enter = Mock(side_effect=[h,h,won])
        self.task.find_round = Mock(side_effect=[(h,field.Round(1,0,(195,340))),
                                                (won,field.Round(1,3,(195,340)))])
        self.task.acquire = Mock(side_effect=[[first],[second]])
        self.task.report['sources'] = {'1:0': {
            'parsed_source_attempts': ['https://example.com/failed-parse'],
            'inspected_sources': ['https://example.com/incomplete-comments']}}
        def battle(row,party):
            if party is first:
                return False
            self.task.report['battles'] += 1
            return True
        self.task.battle = Mock(side_effect=battle)
        result = self.task.run(self.event)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.task.battle.call_count, 2)
        self.assertEqual(self.task.acquire.call_args.kwargs['exclude_sources'],
                         {first.source,'https://example.com/failed-parse',
                          'https://example.com/incomplete-comments'})

    def test_previously_unsuccessful_roster_does_not_end_new_source_search(self):
        self.task.event = self.event
        old = SimpleNamespace(source='https://example.com/old',members=[SimpleNamespace(name='合成角色甲')])
        fresh = SimpleNamespace(source='https://example.com/new',members=[SimpleNamespace(name='合成角色乙')])
        self.task.state['failed'] = [dict(round=1,build=[dict(name='合成角色甲')])]
        self.task.report['sources'] = {'1:0':dict(parties=[old])}
        def acquire(options, **kwargs):
            self.assertEqual(options['max_videos'],4)
            self.assertFalse(kwargs['accept'](dict(parties=[old])))
            self.assertTrue(kwargs['accept'](dict(parties=[old,fresh])))
            return dict(parties=[old,fresh])
        with patch('pcrscript.tasks.task_battle_stadium.parties_for_round',
                   side_effect=lambda report,*a,**k: report['parties']), \
             patch('pcrscript.tasks.strategy_video.acquire_strategies',side_effect=acquire):
            self.assertEqual(self.task.acquire(1),[fresh,old])
        # An unchanged roster is retained as a fallback, not permanently rejected.
        self.task.report['sources'] = {'1:0':dict(parties=[old])}
        with patch('pcrscript.tasks.task_battle_stadium.parties_for_round',
                   side_effect=lambda report,*a,**k: report['parties']), \
             patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value=dict(parties=[])):
            self.assertEqual(self.task.acquire(1),[old])

    def test_changed_round_stars_block_old_plan_before_detail_input(self):
        self.frames([home(stars=3, unlocked=2, round_stars=(3, 0, 0))])
        with self.assertRaisesRegex(Exception, '星级已变化'):
            self.task.open_detail(field.Round(1, 0, (195, 340)))
        self.task.ui.click.assert_not_called()

    def test_changed_allocation_priorities_reinspect_cached_verified_party_once(self):
        self.task.event=self.event
        self.task.options.update(auto_equip=True,auto_equip_priorities={'armor':'magic_defense'})
        party=SimpleNamespace(source='https://example.com/verified',members=[SimpleNamespace(name='合成角色甲')])
        old=dict(round=1,build=[dict(name='合成角色甲')],special={'priorities':{'armor':'hp'}})
        self.task.state['failed']=[old]
        self.task.report['sources']={'1:0':dict(parties=[party])}
        with patch('pcrscript.tasks.task_battle_stadium.parties_for_round',side_effect=lambda r,*a,**k:r['parties']), \
             patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value={'parties':[]}) as acquire:
            self.assertEqual(self.task.acquire(1),[party])
            acquire.assert_not_called()
            self.task.state['failed'].append(dict(old,special={'priorities':{'armor':'magic_defense'}}))
            self.assertEqual(self.task.acquire(1),[party])
            acquire.assert_called_once()
            self.assertFalse(acquire.call_args.kwargs['accept']({'parties':[party]}))

    def test_blocked_round_does_not_prevent_another_verified_unlocked_round(self):
        h = home(stars=5,unlocked=3,total=3,round_stars=(3,2,0))
        after = home(stars=8,unlocked=3,total=3,round_stars=(3,2,3))
        party = SimpleNamespace(source='https://example.com/verified')
        self.frames([h])
        self.task.collect = Mock(return_value=True)
        self.task.enter = Mock(side_effect=lambda: after if self.task.report['battles'] else h)
        self.task.find_round = Mock(side_effect=[(h,field.Round(2,2,(477,340))),
            (h,field.Round(3,0,(759,340))),(after,field.Round(3,3,(759,340))),(after,None)])
        self.task.acquire = Mock(side_effect=[[],[party]])
        def battle(row,candidate):
            self.assertEqual(row.number,3)
            self.assertIs(candidate,party)
            self.task.report['battles'] += 1
            return True
        self.task.battle = Mock(side_effect=battle)
        result = self.task.run(self.event)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['battles'],1)
        self.assertEqual(self.task.find_round.call_args.kwargs['exclude_rounds'],{2})
        self.assertIn('回合2尚未满星',result['pending'][0])

    def test_full_stars_and_received_rewards_skip_battles_and_cache_still_needs_live_proof(self):
        h = home(stars=9, unlocked=3, total=3, round_stars=(3, 3, 3))
        self.frames([h, h, reward_page(received=True), h, h])
        report = self.task.run(self.event)
        self.assertEqual(report['status'], 'already_complete')
        self.assertEqual(report['battles'], 0)
        self.assertEqual(self.clicks(), ['报酬', '取消'])

    def test_full_stars_do_not_prove_rewards_received(self):
        h = home(stars=9, unlocked=3, total=3)
        self.frames([h, h, reward_page(), h, h])
        result = self.task.run(self.event)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('累计报酬尚未全部领取', result['pending'][0])
        self.assertNotIn('战斗开始', self.clicks())

    def test_claim_needs_receipt_and_received_postcondition(self):
        self.task.event = self.event
        self.task.state_path = self.root/'state.json'
        h = home(stars=9, unlocked=3, total=3)
        unclaimed = reward_page(claimable=True)
        received = reward_page(received=True)
        self.frames([h, unclaimed, reward_receipt(), received, received, h, received, h])
        self.assertTrue(self.task.collect())
        self.assertEqual(self.clicks().count('全部收取'), 1)
        self.assertNotIn('pending_claim', self.task.state)
        self.assertEqual(self.task.report['history'][0]['outcome'], 'claim_verified')

    def test_blue_unmet_reward_rows_do_not_trigger_claim_or_block_progress(self):
        self.task.event = self.event
        h = home(stars=0, unlocked=1, total=3)
        self.frames([h, reward_page(claimable=True), h])
        self.assertFalse(self.task.collect())
        self.assertNotIn('全部收取', self.clicks())
        self.assertEqual(self.clicks(), ['报酬', '取消'])
        self.assertFalse(any(r['claimable'] for r in self.task.report['rewards']))

    def test_unresolved_claim_blocks_duplicate_submit(self):
        self.task.event = self.event
        self.task.state['pending_claim'] = dict(targets=[54])
        self.frames([home(stars=54), reward_page((48, 51, 54), claimable=True)])
        with self.assertRaisesRegex(Exception, '上次领奖尚未核对'):
            self.task.collect()
        self.assertNotIn('全部收取', self.clicks())

    def test_last_received_page_does_not_prove_missing_rewards_received(self):
        self.task.event = self.event
        self.frames([home(stars=54, unlocked=18), reward_page((48, 51, 54), received=True), home(stars=54)])
        self.assertFalse(self.task.collect())

    def test_received_rows_moved_to_tail_are_scanned_and_reconcile_claim(self):
        self.task.event = self.event
        self.task.state_path = self.root/'state.json'
        self.task.state['pending_claim'] = dict(targets=[3], receipt='synthetic.png')
        h = home(stars=3, unlocked=2, total=3)
        self.frames([h, reward_page((6, 9)), reward_page((3,), received=True), h])
        self.task.ui.scrollbar.side_effect = [False, True]
        self.assertFalse(self.task.collect())
        self.assertNotIn('pending_claim', self.task.state)
        self.assertEqual(self.task.report['history'][0]['outcome'], 'claim_verified')
        self.assertNotIn('全部收取', self.clicks())

    def test_paging_uses_observed_round_and_unknown_star_blocks_combat(self):
        first = home(unlocked=4, round_stars=(3, 3, 3))
        second = home(unlocked=4, first=4, round_stars=(1, 0, 0))
        self.frames([first, second])
        _, row = self.task.find_round()
        self.assertEqual((row.number, row.stars), (4, 1))
        self.assertIn((930, 230), self.clicks())
        self.frames([home(round_stars=(None, 0, 0))])
        with self.assertRaisesRegex(Exception, '星级未知'):
            self.task.find_round()

    def test_enter_closes_interrupted_readonly_character_dialog_before_navigation(self):
        dialog=screen(('角色详情',480,42),('确认',480,480),('★变更',850,480))
        self.frames([dialog,formation(),detail(),home()])
        self.task.enter()
        self.assertEqual(self.clicks(),['确认','取消','取消'])

    def test_enter_defocuses_native_search_before_cancelling_unstarted_party(self):
        native=screen(('队伍编组',480,42),('对战对手的队伍',460,80),
                      ('战斗效果',95,80),('确定',875,488))
        self.frames([native,formation(),detail(),home()])
        self.task.enter()
        self.assertEqual(self.clicks(),[(190,390),'取消','取消'])

    def test_untouched_unlocked_round_precedes_partial_and_explicit_round_is_kept(self):
        h=home(unlocked=3,total=3,round_stars=(2,0,3))
        self.frames([h])
        _,row=self.task.find_round()
        self.assertEqual(row.number,2)
        self.frames([h])
        _,row=self.task.find_round(1)
        self.assertEqual(row.number,1)
        self.frames([h])
        _,row=self.task.find_round(exclude_rounds={2})
        self.assertEqual(row.number,1)

    def test_unknown_battle_does_not_restart_and_verified_stars_reconcile(self):
        self.task.event = self.event
        self.task.state['pending_battle'] = dict(round=1, stars_before=0, signature='synthetic')
        self.frames([home()])
        with self.assertRaisesRegex(Exception, '星级变化未确认'):
            self.task.finish_battle()
        self.assertIn('pending_battle', self.task.state)
        self.frames([home(stars=3, unlocked=2, round_stars=(3, 0, 0))])
        self.task.finish_battle()
        self.assertNotIn('pending_battle', self.task.state)
        self.assertEqual(self.task.report['history'][-1]['stars_after'], 3)
        self.assertNotIn('战斗开始', self.clicks())

    def synthetic_party_boundary(self):
        """Shared formation's audited output; no real character or gear data."""
        self.task.event = self.event
        self.task.state_path = self.root/'state.json'
        names = [f'合成角色{i}' for i in range(5)]
        observed = {name: dict(name=name, level=100, rank=10, stars=5,
                    skill_level=100, unique=False, unique2=False, equipment=None)
                    for name in names}
        self.task.formation = Mock()
        self.task.formation.select.return_value = (True, dict(order=names, observed=observed))
        self.task.formation.inspect_current.return_value = [SimpleNamespace(name=n, identity_verified=True) for n in names]
        gear = dict(order=names, slots=[[False]*3 for _ in names], unknown=0,
                    items=np.zeros((5, 3, 192), dtype=int).tolist())
        assets = patch('pcrscript.game_ui.avatar_assets.ensure_avatar_index', return_value=(Mock(), {}))
        assets.start()
        self.addCleanup(assets.stop)
        special = patch('pcrscript.game_ui.special_equipment.inspect_special_equipment', return_value=gear)
        special.start()
        self.addCleanup(special.stop)
        return SimpleNamespace(source='https://example.com/synthetic'), gear

    def test_start_is_journaled_before_input_and_success_uses_live_stars(self):
        party, _ = self.synthetic_party_boundary()
        won = home(stars=3, unlocked=2, round_stars=(3, 0, 0))
        self.frames([home(), detail(), formation(), formation(), battle_result(), won, won])
        def input_boundary(button):
            if getattr(button, 'text', '') == '战斗开始':
                saved = json.loads(self.task.state_path.read_text(encoding='utf-8'))
                self.assertEqual(saved['pending_battle']['round'], 1)
                self.assertEqual(saved['pending_battle']['stars_before'], 0)
        self.task.ui.click.side_effect = input_boundary
        self.assertTrue(self.task.battle(field.Round(1, 0, (195, 340)), party))
        self.assertEqual(self.clicks().count('战斗开始'), 1)
        self.assertNotIn('pending_battle', self.task.state)
        self.assertEqual(self.task.report['history'][0]['stars_after'], 3)

    def test_unknown_special_equipment_never_reaches_start(self):
        party, gear = self.synthetic_party_boundary()
        gear['unknown'] = 1
        self.frames([home(), detail(), formation()])
        with self.assertRaisesRegex(Exception, '特别装备状态未知'):
            self.task.battle(field.Round(1, 0, (195, 340)), party)
        self.assertNotIn('战斗开始', self.clicks())
        self.assertNotIn('pending_battle', self.task.state)

    def test_goal_and_item_results_keep_distinct_evidence_for_the_same_battle(self):
        party, _ = self.synthetic_party_boundary()
        self.task.ui.save.side_effect = lambda name, frame: EventUI.save(self.task.ui,name,frame)
        goals = screen(('WIN',480,80),('下一步',830,480),blue=('下一步',))
        items = screen(('WIN',480,80),('获得道具',480,140),('下一步',830,480),blue=('下一步',))
        won = home(stars=3,unlocked=2,round_stars=(3,0,0))
        self.frames([home(),detail(),formation(),formation(),goals,items,won,won])
        self.assertTrue(self.task.battle(field.Round(1,0,(195,340)),party))
        record = self.task.report['history'][-1]
        self.assertEqual(len(record['result_images']),2)
        self.assertEqual(len(set(record['result_images'])),2)
        self.assertEqual(record['result'],record['result_images'][0])
        self.assertTrue(all(Path(path).is_file() for path in record['result_images']))

    def test_failed_loadout_is_not_retried_under_different_source(self):
        party, gear = self.synthetic_party_boundary()
        failed = home(stars=1, round_stars=(1, 0, 0))
        self.frames([home(), detail(), formation(), formation(), battle_result(), failed, failed])
        self.assertTrue(self.task.battle(field.Round(1, 0, (195, 340)), party))
        self.assertEqual(len(self.task.state['failed']), 1)
        # Read the persisted state as a later run would. Tiny image variation
        # and another guide URL must not authorize the same failed team.
        self.task.state = json.loads(self.task.state_path.read_text(encoding='utf-8'))
        gear['items'][0][0][0] = 1
        party.source = 'https://example.com/another-synthetic'
        self.frames([failed, detail(), formation(), formation(), detail(), failed])
        self.assertFalse(self.task.battle(field.Round(1, 1, (195, 340)), party))
        self.assertEqual(self.clicks().count('战斗开始'), 1)

    def test_changed_committed_special_loadout_allows_a_new_bounded_trial(self):
        from copy import deepcopy
        party, gear = self.synthetic_party_boundary()
        failed = home(stars=1, round_stars=(1, 0, 0))
        self.frames([home(), detail(), formation(), formation(), battle_result(), failed, failed])
        self.assertTrue(self.task.battle(field.Round(1, 0, (195, 340)), party))
        committed = deepcopy(gear)
        committed['slots'][0][0] = True
        committed['items'][0][0] = [80]*192
        self.task.options['auto_equip'] = True
        won = home(stars=3, unlocked=2, round_stars=(3, 0, 0))
        self.frames([failed, detail(), formation(), formation(), battle_result(), won, won])
        with patch('pcrscript.game_ui.special_equipment.auto_equip_special', return_value=committed) as equip:
            self.assertTrue(self.task.battle(field.Round(1, 1, (195, 340)), party))
        equip.assert_called_once_with(self.task.ui, gear['order'], priorities={})
        self.assertEqual(self.task.report['battles'], 2)
        self.assertEqual(self.task.report['history'][-1]['stars_after'], 3)
        self.assertEqual(self.task.report['audits'][-1]['details']['special_equipment_before'], gear)
        self.assertEqual(self.task.report['history'][-1]['context']['special'], committed)

    def test_auto_special_never_starts_with_unknown_slots_or_changed_members(self):
        party, gear = self.synthetic_party_boundary()
        self.task.options['auto_equip'] = True
        unknown = dict(gear, unknown=1)
        self.frames([home(), detail(), formation()])
        with patch('pcrscript.game_ui.special_equipment.auto_equip_special', return_value=unknown):
            with self.assertRaisesRegex(Exception, '分配后的状态未知'):
                self.task.battle(field.Round(1, 0, (195, 340)), party)
        self.frames([home(), detail(), formation(), formation()])
        self.task.formation.inspect_current.return_value = [SimpleNamespace(name='其他合成角色', identity_verified=True)]
        with patch('pcrscript.game_ui.special_equipment.auto_equip_special', return_value=gear):
            with self.assertRaisesRegex(Exception, '开战前成员或页面不一致'):
                self.task.battle(field.Round(1, 0, (195, 340)), party)
        self.assertNotIn('战斗开始', self.clicks())
        self.assertNotIn('pending_battle', self.task.state)
