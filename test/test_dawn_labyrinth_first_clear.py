"""Synthetic first-entry safety and current-exploration regressions."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv

from pcrscript import Robot
from pcrscript.game_ui import dawn_labyrinth as maze
from pcrscript.game_ui.screen import EventUIError
from pcrscript.run_session import RunCancelled
from pcrscript.runtime import run_task_with_config
from pcrscript.tasks import DawnLabyrinthFirstClear
from pcrscript.tasks.dawn_labyrinth_party import LabyrinthFormation
from pcrscript.tasks.event_strategy import CharacterStatus
from pcrscript.tasks.party_variants import character_roles
from test_dawn_labyrinth import screen, home, guild, preview, catalogue, mission_home, missions, mission_receipt


def difficulty(selected=1):
    value = screen(('难度变更', 480, 42), ('难度1', 330, 123),
                   ('难度2', 330, 223), ('取消', 370, 480), ('变更', 588, 480), blue=('变更',))
    cv.rectangle(value.image, (274, 123+22+100*(selected-1)),
                 (291, 123+39+100*(selected-1)), (230, 155, 25), -1)
    return value


def departure(before=11, after=10):
    return screen(('公会选择确认', 480, 42),
                  ('将消耗1张迷宫通行证和【美食殿堂】一同出发。确定吗？', 480, 85),
                  ('持有迷宫通行证', 350, 427), (str(before), 565, 427), (str(after), 692, 427),
                  ('取消', 255, 475), ('出发', 705, 475), blue=('出发',))


def inventory_result():
    return screen(('难度1', 480, 27), ('RESULT', 480, 62), ('加入的角色', 160, 103),
                  ('已获得的迷宫遗物', 200, 285), ('下一步', 480, 497))


def score_result(clear=True):
    return screen(('难度1', 480, 27), ('RESULT', 480, 62), ('CLEAR' if clear else 'RETURN', 242, 110),
                  ('分数明细', 175, 236), ('难度奖励', 390, 425), ('关闭', 480, 497))


class FirstClearRecognitionTests(TestCase):
    def test_three_boss_team_tabs_require_one_gold_selection(self):
        value = screen(('队伍编组', 480, 42), ('队伍1', 98, 89),
                       ('队伍2', 216, 89), ('队伍3', 334, 89))
        self.assertIsNone(maze.selected_boss_team(value))
        cv.rectangle(value.image, (187, 82), (246, 97), (40, 190, 245), -1)
        self.assertEqual(maze.selected_boss_team(value), 2)
        cv.rectangle(value.image, (305, 82), (364, 97), (40, 190, 245), -1)
        self.assertIsNone(maze.selected_boss_team(value))

    def test_boss_pool_requires_verified_build_and_distinct_full_teams(self):
        core = ('佩可莉姆', '可可萝', '凯露')
        ready = {n: CharacterStatus(n, level=365, rank=38, stars=6, skill_level=365,
                                   identity_verified=True) for n in core}
        others = [f'合成伙伴{i}' for i in range(12)]
        ready.update({n: CharacterStatus(n, level=350, rank=38, stars=5, skill_level=350,
                                        identity_verified=True) for n in others})
        roles = {n: dict(role=7 if i == 0 else 1, score=50-i, single=1) for i, n in enumerate(others)}
        groups = LabyrinthFormation.plan_boss_parties(ready, roles)
        self.assertEqual(list(map(len, groups)), [5, 5, 5])
        self.assertEqual(len({n for g in groups for n in g}), 15)
        self.assertEqual(groups[0][:3], list(core))
        with self.assertRaises(EventUIError):
            LabyrinthFormation.plan_boss_parties({n:s for n,s in list(ready.items())[:9]}, roles)
        with self.assertRaises(EventUIError):
            LabyrinthFormation.require_boss_build(CharacterStatus('未知伙伴', level=350, rank=38,
                                                                  stars=5, skill_level=None))

    def test_boss_parties_pair_magic_support_and_keep_a_tank_for_physical_members(self):
        core = ('佩可莉姆', '可可萝', '凯露')
        names = core+('合成魔法破防', '合成魔法辅助', '合成物理辅助', '合成挑衅坦克',
                      '合成物理输出1', '合成物理输出2', '合成物理输出3', '合成物理输出4')
        ready = {n: CharacterStatus(n, level=365, rank=38, stars=6, skill_level=365,
                                   identity_verified=True) for n in names}
        roles = {n: dict(kind=1, damage=2, role=1, score=100, single=2) for n in names[3:]}
        roles['合成魔法破防'].update(kind=2, role=4, description='降低敌方魔防，提升我方魔法攻击力')
        roles['合成魔法辅助'].update(kind=2, role=5, description='提升我方魔法攻击力并回复技能值')
        roles['合成物理辅助'].update(kind=2, role=5, description='提升物理攻击力和物理攻击力')
        roles['合成挑衅坦克'].update(role=7, tank=True, damage=0, score=0)
        groups = LabyrinthFormation.plan_boss_parties(ready, roles)
        self.assertEqual(set(groups[0][3:]), {'合成魔法破防', '合成魔法辅助'})
        self.assertIn('合成挑衅坦克', groups[1])
        self.assertNotIn('合成物理辅助', groups[0])
        self.assertEqual(len({n for g in groups for n in g}), len(names))

    def test_public_roles_exclude_same_named_npc_units(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript('''
                    CREATE TABLE unit_profile(unit_id INTEGER);
                    CREATE TABLE unit_role_data(unit_id INTEGER,unit_role_id INTEGER);
                    CREATE TABLE unit_data(unit_id INTEGER,unit_name TEXT,atk_type INTEGER,search_area_width INTEGER);
                    CREATE TABLE unit_skill_data(unit_id INTEGER,union_burst INTEGER,main_skill_1 INTEGER,main_skill_2 INTEGER);
                    CREATE TABLE skill_data(skill_id INTEGER,description TEXT);
                    INSERT INTO unit_profile VALUES (1);
                    INSERT INTO unit_role_data VALUES (1,7);
                    INSERT INTO unit_data VALUES (1,'合成坦克',1,150),(2,'合成坦克',2,800);
                    INSERT INTO unit_skill_data VALUES (1,101,0,0),(2,102,0,0);
                    INSERT INTO skill_data VALUES (101,'对一名敌人造成物理伤害'),(102,'造成魔法伤害');
                ''')
            roles = character_roles(path)
            self.assertEqual(roles['合成坦克']['role'], 7)
            self.assertEqual(roles['合成坦克']['kind'], 1)

    def test_boss_requires_all_observed_mechanics_and_effects(self):
        description = ('所有的技能伤害无法回复技能值，对进行物理攻击的敌方全体赋予烧伤状态，'
                       '自身的物理防御力越高，伤害越大。自身的魔法防御力越高，伤害越大。'
                       '降低敌方全体生命值吸收量，对敌方全体造成魔法伤害，击退敌方全体（必中），'
                       '对前方一名敌人造成魔法固定伤害')
        effects = '坦克型物防下降魔防下降'
        self.assertTrue(maze.supported_boss('暗黑滴水嘴兽', 350, 60000000, effects, description))
        for change in ({'level': 351}, {'maximum_hp': 60000001}, {'effects': '物防下降'},
                       {'description': description.replace('魔法固定伤害', '')},
                       {'description': description+'物理伤害免疫'}):
            fields = dict(name='暗黑滴水嘴兽', level=350, maximum_hp=60000000, effects=effects, description=description)
            self.assertFalse(maze.supported_boss(**dict(fields, **change)))

    def test_every_enemy_info_button_is_found_when_one_level_is_unreadable(self):
        value = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457), ('Lv.380', 350, 320))
        for x in (176, 401, 626, 851):
            cv.circle(value.image, (x, 316), 14, (230, 230, 230), -1)
            cv.rectangle(value.image, (x-2, 306), (x+1, 309), (230, 120, 100), -1)
            cv.rectangle(value.image, (x-2, 313), (x+1, 325), (230, 120, 100), -1)
        self.assertEqual(len(maze.enemy_information(value)), 4)
        self.assertEqual([p[0] for p in maze.enemy_information(value)], [176, 400, 626, 850])
        value.image[:] = 0
        self.assertEqual(maze.enemy_information(value), [])

    def test_knockback_through_immunity_is_not_enemy_damage_immunity(self):
        self.assertTrue(maze.supported_normal_enemy(700000, '近身攻击、击退（在伤害免疫的情况下也会成功赋予）'))
        self.assertFalse(maze.supported_normal_enemy(700000, '魔物自身拥有伤害免疫'))
        self.assertFalse(maze.supported_normal_enemy(700000, '造成比例伤害'))
        self.assertTrue(maze.supported_normal_enemy(2200000, '近身攻击'))
        self.assertFalse(maze.supported_normal_enemy(3100000, '近身攻击'))

    def test_event_requires_explicit_free_rewards_and_rejects_costs(self):
        value = screen(('触发事件！', 480, 40), ('这里是公会管理协会', 480, 88),
                       ('随机印记×2', 340, 385), ('+阿尔法金币×200', 340, 400),
                       ('选择', 340, 445), blue=('选择',))
        self.assertIsNotNone(maze.free_event_choice(value))
        value.items.extend(screen(('消耗阿尔法金币', 480, 300)).items)
        self.assertIsNone(maze.free_event_choice(value))

    def test_relic_effect_must_be_entirely_positive_and_readable(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('还剩1次', 480, 122), ('物理/魔法攻击力+20%', 202, 392),
                       ('HP+10%', 480, 392), ('选择', 202, 464), ('选择', 480, 464), blue=('选择',))
        self.assertEqual(maze.positive_relic_choice(value).center[0], 480)
        value.items[4].text = 'HP-10%'
        self.assertEqual(maze.positive_relic_choice(value).center[0], 202)
        value.items[3].score = .94
        self.assertIsNone(maze.positive_relic_choice(value))

    def test_difficulty_requires_one_selected_radio(self):
        self.assertEqual(maze.selected_difficulty(difficulty()), 1)
        self.assertEqual(maze.selected_difficulty(difficulty(2)), 2)
        ambiguous = difficulty()
        cv.rectangle(ambiguous.image, (274, 245), (291, 262), (230, 155, 25), -1)
        self.assertIsNone(maze.selected_difficulty(ambiguous))

    def test_flat_lifesteal_relic_requires_enabled_choice_and_positive_amount(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('还剩1次', 480, 122), ('生命值吸收+10', 202, 392),
                       ('选择', 202, 464), blue=('选择',))
        self.assertEqual(maze.positive_relic_choice(value).center[0], 202)
        value.items[3].text = '生命值吸收-10'
        self.assertIsNone(maze.positive_relic_choice(value))
        value.items[3].text = '生命值吸收+10'
        value.image[:] = 0
        self.assertIsNone(maze.positive_relic_choice(value))

    def test_tp_relic_accepts_only_a_single_unconditional_positive_effect(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('还剩1次', 480, 122), ('技能值上升量+10', 202, 392),
                       ('战斗开始时技能值回复100', 480, 392),
                       ('选择', 202, 464), ('选择', 480, 464), blue=('选择',))
        self.assertEqual(maze.positive_relic_choice(value).center[0], 202)
        value.items[3].text = '技能值上升量-10'
        self.assertEqual(maze.positive_relic_choice(value).center[0], 480)
        value.items.extend(screen(('消耗金币100', 480, 410)).items)
        self.assertIsNone(maze.positive_relic_choice(value))

    def test_departure_requires_one_pass_and_verified_guild(self):
        ui = Mock()
        ui.number.side_effect = lambda s, roi: s.number(roi)
        self.assertEqual(maze.departure_preview(ui, departure()), (11, 10))
        for value in (departure(0, 0), departure(11, 9), departure(11, 11)):
            with self.assertRaises(EventUIError):
                maze.departure_preview(ui, value)
        value = departure()
        value.items[1].text = '将消耗1张迷宫通行证和【其他公会】一同出发。'
        with self.assertRaises(EventUIError):
            maze.departure_preview(ui, value)

    def test_unknown_identity_or_underleveled_partner_blocks_trial(self):
        valid = dict(name='合成伙伴', identity_verified=True, level=365, rank=38, stars=6, skill_level=365)
        LabyrinthFormation.require_build(CharacterStatus(**valid), 360)
        for change in ({'identity_verified': False}, {'level': None}, {'level': 359},
                       {'rank': None}, {'stars': 5}, {'skill_level': None}):
            with self.subTest(change=change), self.assertRaises(EventUIError):
                LabyrinthFormation.require_build(CharacterStatus(**dict(valid, **change)), 360)

    def test_invitation_animation_is_not_a_character_selection_button(self):
        self.assertTrue(maze.invitation_animation(screen(('合成伙伴', 790, 435))))
        self.assertFalse(maze.invitation_animation(screen(('合成伙伴', 790, 435), ('选择', 790, 490), ('角色选择', 480, 42))))


class LabyrinthFormationTests(TestCase):
    def test_neighboring_rows_recover_a_card_with_an_interrupted_border(self):
        value = screen(('队伍编组', 480, 42))
        cv.rectangle(value.image, (178, 281), (254, 348), (230, 155, 25), -1)
        with patch('pcrscript.tasks.dawn_labyrinth_party.card_rectangles', return_value=[(272, 266, 99, 99)]):
            rectangles = LabyrinthFormation.visible_cards(value)
        self.assertIn((166, 266, 100, 99), rectangles)
        self.assertIn((272, 266, 99, 99), rectangles)
        self.assertEqual(len(rectangles), 2)

    def test_roster_scroll_stops_as_soon_as_a_detail_dialog_appears(self):
        formation = object.__new__(LabyrinthFormation)
        formation.ui = Mock(capture=Mock(return_value=screen(('角色详情', 480, 42))))
        with self.assertRaises(EventUIError):
            formation.scroll_to_start()
        self.assertEqual(formation.ui.swipe.call_count, 1)

    def test_selected_count_uses_requested_members_not_all_visible_candidates(self):
        value = screen(('队伍编组', 480, 42))
        formation = object.__new__(LabyrinthFormation)
        formation.ui = Mock(capture=Mock(return_value=value))
        core = ('佩可莉姆', '可可萝', '凯露')
        formation.avatars = Mock(query=Mock(return_value=list(core)+['合成储备'+str(i) for i in range(5)]))
        formation.observed = {}
        formation.clear_current = Mock(return_value=value)
        formation.occupied_slots = Mock(return_value=[(96, 452), (205, 452), (314, 452)])
        formation.inspect = Mock(side_effect=lambda pos, **kwargs: CharacterStatus(
            kwargs['expected_name'], level=365, rank=38, stars=6, skill_level=365, identity_verified=True))
        rectangles = [(60+106*i, 177, 100, 99) for i in range(8)]
        with patch('pcrscript.tasks.dawn_labyrinth_party.card_rectangles', return_value=rectangles):
            party, result = formation.select_standard(360)
            self.assertEqual([member['name'] for member in party], list(core))
            self.assertIs(result, value)
            self.assertEqual(formation.ui.click.call_count, 3)
            formation.occupied_slots.return_value.pop()
            with self.assertRaises(EventUIError):
                formation.select_standard(360)


class FirstClearTaskTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        self.robot.configure({'DawnLabyrinthFirstClear': {'output': str(self.folder)}})
        self.task = DawnLabyrinthFirstClear(self.robot)
        self.task.ui = Mock(output=self.folder, last=None)
        self.task.ui.save.return_value = self.folder/'synthetic.png'
        self.task.ui.number.side_effect = lambda s, roi: s.number(roi)
        self.sleep = patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.time.sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.temp.cleanup()

    def frames(self, values):
        iterator = iter(values)
        def capture():
            value = next(iterator, values[-1])
            self.task.ui.last = value
            return value
        self.task.ui.capture.side_effect = capture

    def clicks(self):
        return [getattr(call.args[0], 'text', call.args[0]) for call in self.task.ui.click.call_args_list]

    def guild(self):
        value = guild(('难度变更', 843, 65), ('美食殿堂', 144, 352))
        cv.rectangle(value.image, (94, 398), (194, 446), (230, 155, 25), -1)
        return value

    def locked(self):
        value = self.guild()
        value.items.extend(screen(('通关1次难度1后可解锁。', 480, 267)).items)
        return value

    def test_zero_passes_without_first_clear_never_starts_an_entry(self):
        self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(), self.locked(), self.guild()])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.assertNotIn('选择', self.clicks())
        self.assertEqual(self.task.report['entries'], 0)
        self.assertNotIn('pending_spend', self.task.report)

    def test_zero_passes_already_cleared_catalogue_completes_without_spending(self):
        self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(),
                     catalogue(0, selected=False), self.guild(), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual((report['spent'], report['entries'], report['remaining_passes']), (0, 0, 0))
        self.assertNotIn('一键扫荡', self.clicks())
        self.assertNotIn('选择', self.clicks())

    def test_already_cleared_first_clear_claims_missions_with_zero_passes(self):
        self.frames([home(0), home(0), self.guild(), difficulty(), self.guild(),
                     catalogue(0, selected=False), self.guild(), mission_home(), mission_home(),
                     missions(), missions(), mission_receipt(), missions(claim=False), mission_home(badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['missions']['batches'], 1)
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks().count('全部收取'), 1)

    def test_resumed_clear_result_collects_missions_only_after_unlock_and_balance(self):
        self.frames([score_result(), home(10), self.guild(), difficulty(), self.guild(),
                     catalogue(10, selected=False), self.guild(), mission_home(10), mission_home(10),
                     missions(), missions(), mission_receipt(), missions(claim=False), mission_home(10, badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['missions']['batches'], 1)
        self.assertEqual(report['spent'], 0)
        self.assertLess(self.clicks().index('跳过'), self.clicks().index('全部收取'))

    def test_unlocked_difficulty_does_not_consume_another_entry(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(),
                     preview(11, 10), self.guild(), home(11)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['entries'], 0)
        self.assertEqual(report['spent'], 0)
        self.assertNotIn('pending_spend', report)
        self.assertEqual(self.clicks().count('出发'), 1)

    def test_failed_boss_requires_explicit_retry_option(self):
        value = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                       ('结束', 577, 507), ('重新挑战', 808, 507))
        self.frames([value])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.task.ui.click.assert_not_called()

    def test_resumed_result_requires_unlock_proof_and_never_spends_a_new_pass(self):
        self.frames([inventory_result(), home(10), self.guild(), difficulty(), self.guild(),
                     preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertTrue(report['settlement_resumed'])
        self.assertEqual(report['spent'], 0)
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks().count('出发'), 1)

    def test_partial_reward_result_is_not_treated_as_a_first_clear(self):
        self.frames([inventory_result(), home(10), self.guild(), difficulty(), self.guild(), self.locked(), self.guild()])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['entries'], 0)
        self.assertNotIn('already_cleared', report)

    def test_score_result_is_closed_and_clear_is_proven_by_game_unlock(self):
        self.frames([score_result(), home(10), self.guild(), difficulty(), self.guild(),
                     preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['boss_defeated'])
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks()[0], '关闭')

    def test_fresh_boss_clear_restores_difficulty_one_and_proves_unlock_before_completion(self):
        self.task.report.update(boss_defeated=True, entries=1,
                                pending_spend=dict(before=11, after=10, cost=1))
        self.task.exploration_verified = True
        self.frames([score_result(), home(10), self.guild(), difficulty(2), difficulty(1),
                     self.guild(), catalogue(10, selected=False), self.guild(), home(10)])
        self.task.explore(inventory_result())
        self.assertEqual(self.task.report['status'], 'complete')
        self.assertTrue(self.task.report['already_cleared'])
        self.assertEqual(self.task.report['spent'], 1)
        self.assertNotIn('pending_spend', self.task.report)
        self.assertIn('变更', self.clicks())
        self.assertEqual(self.clicks().count('出发'), 1)  # Read-only unlock probe.

    def test_chest_overlay_is_settled_before_inspecting_the_map_behind_it(self):
        receipt = screen(('宝箱开封结果', 480, 42), ('已开封从迷宫带回的宝箱。', 480, 85),
                         ('确认', 480, 480), ('黎明界迷宫', 130, 30), ('区域', 340, 30),
                         ('撤退', 680, 490), ('返回', 850, 490))
        self.frames([receipt, home(10), self.guild(), difficulty(), self.guild(),
                     preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertTrue(report['already_cleared'])
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks()[0], '确认')

    def test_unlock_overlay_closes_before_home_probe_without_new_departure(self):
        notice = home(10)
        notice.items.extend(screen(('难度解锁', 480, 146), ('难度2已解锁。', 480, 271),
                                   ('关闭', 480, 370)).items)
        self.frames([notice, home(10), self.guild(), difficulty(), self.guild(),
                     preview(10, 9), self.guild(), home(10)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['entries'], 0)
        self.assertEqual(self.clicks()[0], '关闭')

    def test_home_departure_resumes_saved_boss_formation_without_new_entry(self):
        formation = screen(('队伍编组', 480, 42), ('队伍1', 98, 89), ('队伍2', 216, 89),
                           ('队伍3', 334, 89), ('取消', 712, 453))
        cv.rectangle(formation.image, (69, 82), (128, 97), (40, 190, 245), -1)
        stage = screen(('首领战格子', 138, 56), ('挑战', 817, 457))
        self.frames([formation, formation, formation, stage])
        result = self.task.start(home(10))
        self.assertIs(result, stage)
        self.assertTrue(self.task.report['resumed'])
        self.assertEqual(self.task.report['entries'], 0)
        self.assertNotIn('pending_spend', self.task.report)
        self.assertEqual(self.clicks(), ['出发', '队伍1', '取消'])

    def test_damage_report_can_close_without_retrying_or_ending_exploration(self):
        report_screen = screen(('伤害报告', 480, 42), ('造成的伤害', 317, 76),
                               ('受到的伤害', 536, 76), ('确认', 478, 479))
        failure = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                         ('结束', 577, 507), ('重新挑战', 808, 507))
        self.frames([report_screen, failure])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(self.clicks(), ['确认'])
        self.assertEqual(report['entries'], 0)

    def test_retry_opens_one_formation_and_unknown_cost_is_not_confirmed(self):
        failure = screen(('战斗失败', 480, 64), ('第1战', 122, 140),
                         ('结束', 577, 507), ('重新挑战', 808, 507))
        self.task.options['retry_failed_boss'] = True
        self.frames([failure])
        with patch.object(self.task, 'wait', side_effect=EventUIError('合成的未知消费窗口')):
            report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertTrue(report['boss_retry'])
        self.assertEqual(self.clicks(), ['重新挑战'])
        self.assertEqual(report['entries'], 0)
        self.task.ui.click.reset_mock()
        with self.assertRaises(EventUIError):
            self.task.explore(failure)
        self.task.ui.click.assert_not_called()

    def test_clear_requires_boss_victory_and_matching_entry_balance(self):
        self.task.report.update(boss_defeated=True, pending_spend=dict(before=11, after=10, cost=1))
        with self.assertRaises(EventUIError):
            self.task.explore(home(11))
        self.assertIn('pending_spend', self.task.report)
        self.task.ui.click.assert_not_called()
        self.frames([self.guild(), difficulty(), self.guild(), catalogue(10, selected=False),
                     self.guild(), home(10)])
        self.task.explore(home(10))
        self.assertEqual(self.task.report['status'], 'complete')
        self.assertEqual(self.task.report['spent'], 1)
        self.assertNotIn('pending_spend', self.task.report)
        self.assertEqual(self.clicks().count('出发'), 1)
        self.assertNotIn('选择', self.clicks())

    def test_failed_battle_is_resolved_and_never_replayed(self):
        stage = screen(('战斗格子（普通）', 200, 55), ('挑战', 817, 455), blue=('挑战',))
        formation = screen(('队伍编组', 480, 42), ('战斗开始', 851, 453), blue=('战斗开始',))
        failure = screen(('战斗失败', 480, 64))
        self.frames([formation, failure])
        self.task.exploration_verified = True
        with patch.object(self.task, 'inspect_enemies', return_value=([dict(level=360)], stage)), \
                patch.object(self.task, 'get_formation', return_value=Mock(select_standard=Mock(return_value=([], formation)))), \
                patch('pcrscript.tasks.task_dawn_labyrinth_first_clear.EventCombat'):
            with self.assertRaises(EventUIError):
                self.task.fight(stage)
        self.assertEqual(self.task.report['battles'], 1)
        self.assertNotIn('pending_battle', self.task.report)
        self.assertEqual(self.task.report['history'][0]['outcome'], 'failed')
        self.assertEqual(self.clicks(), ['挑战', '战斗开始'])

    def test_shop_is_closed_once_and_exit_confirmed_without_purchase(self):
        shop = screen(('商店', 480, 42), ('可使用阿尔法金币购买道具。', 480, 78),
                      ('购买', 240, 260), ('用300更新', 330, 485), ('关闭', 818, 475))
        confirm = screen(('商店', 480, 42), ('可使用阿尔法金币购买道具。', 480, 78),
                         ('商店确认', 480, 147), ('将退出商店。', 480, 235),
                         ('确认', 590, 370), ('关闭', 818, 475), blue=('确认',))
        map_screen = screen(('黎明界迷宫', 130, 30), ('区域', 340, 30),
                            ('撤退', 680, 490), ('返回', 850, 490))
        self.frames([shop, confirm, map_screen])
        self.task.run()
        self.assertEqual(self.clicks(), ['关闭', '确认'])

    def test_confirm_persisted_before_single_entry_and_unknown_state_does_not_restart(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure(), screen(('未知页面', 480, 200))])
        def click(button):
            if getattr(button, 'center', (0, 0))[1] == 475:
                saved = json.loads((self.folder/'report.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['pending_spend']['cost'], 1)
        self.task.ui.click.side_effect = click
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['entries'], 1)
        self.assertEqual(report['pending_spend']['after'], 10)
        self.assertEqual(self.clicks().count('出发'), 2)  # Open guilds, then one committed entry.
        self.assertNotIn('战斗开始', self.clicks())

    def test_balance_mismatch_is_never_committed(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure(10, 9)])
        report = self.task.run()
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['entries'], 0)
        self.assertNotIn('pending_spend', report)

    def test_cancellation_at_departure_keeps_pending_confirmation(self):
        self.frames([home(11), home(11), self.guild(), difficulty(), self.guild(), self.locked(), self.guild(), departure()])
        def click(button):
            if getattr(button, 'center', (0, 0))[1] == 475:
                raise RunCancelled('synthetic cancellation')
        self.task.ui.click.side_effect = click
        with self.assertRaises(RunCancelled):
            self.task.run()
        saved = json.loads((self.folder/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['status'], 'cancelled')
        self.assertEqual(saved['pending_spend']['cost'], 1)

    def test_resumed_unknown_enemy_level_does_not_depart_or_fight(self):
        value = screen(('战斗格子（普通）', 200, 55), ('挑战', 817, 455), blue=('挑战',))
        self.frames([value])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertTrue(report['resumed'])
        self.assertEqual(report['entries'], 0)
        self.task.ui.click.assert_not_called()

    def test_resuming_other_difficulty_never_fights_or_selects_rewards(self):
        value = screen(('获得道具的机会！', 480, 50), ('请选择要获得的迷宫遗物。', 480, 92),
                       ('难度详情', 742, 220), ('设定', 818, 220), ('玩法', 742, 330),
                       ('2', 743, 200), ('菜单', 915, 40))
        self.frames([value])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertIn('不是已核验的难度1', report['pending'][0])
        self.assertFalse(self.task.exploration_verified)
        self.task.ui.click.assert_not_called()

    def test_resumed_difficulty_icon_tracks_menu_position(self):
        for x, y in ((742, 220), (722, 238), (742, 109)):
            value = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457),
                           ('难度详情', x, y), ('设定', x+76, y),
                           ('玩法', x, y+110), ('1', x, y-20), ('菜单', 894, 72))
            stage = screen(('战斗格子（普通）', 138, 56), ('挑战', 817, 457))
            self.frames([stage])
            self.assertIs(self.task.verify_exploration(value), stage)
            self.assertTrue(self.task.exploration_verified)
            self.task.ui.number.assert_called_with(value, (x-8, y-30, x+11, y-4))

    def test_difficulty_one_scrolls_back_when_unlock_selected_difficulty_two(self):
        hidden = screen(('难度变更', 480, 42), ('难度2', 330, 90),
                        ('取消', 370, 480), ('变更', 588, 480))
        self.frames([hidden, difficulty(2), difficulty(1), self.guild()])
        self.assertTrue(maze.guild_selection(self.task.difficulty_one(self.guild())))
        self.task.ui.swipe.assert_called_once_with((615, 165), (615, 395))
        self.assertEqual(self.clicks()[-1], '变更')

    def test_bad_options_fail_before_device_connection(self):
        for options in (None, [], {'timeout': True}, {'timeout': 7201}, {'max_battles': 0}, {'max_battles': 61}, {'retry_failed_boss': 1}):
            with self.subTest(options=options), patch('pcrscript.runtime.robot_from_config') as connect:
                with self.assertRaises(ValueError):
                    run_task_with_config({'DawnLabyrinthFirstClear': options}, 'dawn_labyrinth_first_clear')
                connect.assert_not_called()
