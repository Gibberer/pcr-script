from datetime import datetime, timedelta, timezone
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, EventUIError, TextBox
from pcrscript.game_ui.team_battle import Boss, can_repeat, map_bosses, meets_reference, priority, recommendation_damage, recommendation_time, result_damage
from pcrscript.news import _query_clan_battle
from pcrscript.tasks.task_team_battle import BossChanged, TeamBattle, validate_options


def box(text, x, y):
    return TextBox(text, 1.0, [[x-18, y-8], [x+18, y-8], [x+18, y+8], [x-18, y+8]])


class TeamBattleTests(unittest.TestCase):
    def test_lanes_and_repeat_budget(self):
        items = [box('团队战', 105, 35), box('剩余挑战次数', 360, 400),
                 box('讨伐信息', 240, 450)]
        items += [box(f'第{lap}轮', x, y) for x, y, lap in
                  zip((125, 290, 480, 625, 840), (335, 335, 335, 335, 280), (2, 3, 4, 4, 5))]
        bosses = map_bosses(EventScreen(np.zeros((540, 960, 3), np.uint8), items))
        self.assertEqual([(b.lane, b.lap) for b in bosses], list(enumerate((2, 3, 4, 4, 5))))
        self.assertGreater(priority(Boss(0, 2, 125, 42, 42), 2),
                           priority(Boss(4, 5, 840, 42, 42), 2))
        self.assertTrue(can_repeat(49))
        self.assertFalse(can_repeat(48))


    def test_recommendation_time_and_empty_portrait(self):
        image = np.full((540, 960, 3), 180, np.uint8)
        for x in (224, 312, 402, 491, 581):
            image[220:266, x-22:x+22] = (25, 80, 220)
        items = [box('使用', 711, 277), box('讨伐时间', 86, 299), box('0:17', 151, 299),
                 box('参考伤害', 111, 251), box('42000000', 122, 272)]
        screen = EventScreen(image, items)
        button = screen.find('使用', (625, 195, 800, 425), exact=True)
        self.assertEqual(recommendation_time(screen, button.center[1]), 17)
        self.assertEqual(recommendation_damage(screen, button.center[1]), 42_000_000)
        self.assertTrue(TeamBattle.recommendation_owned(screen, button))
        restricted = EventScreen(image, items+[box('限制实战使用', 310, 256)])
        self.assertFalse(TeamBattle.recommendation_owned(restricted, button))
        image[220:266, 380:424] = (180, 180, 180)
        self.assertFalse(TeamBattle.recommendation_owned(EventScreen(image, items), button))

    def test_recommendation_clears_save_checkbox_before_using_team(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        saved = image.copy()
        saved[257:273, 847:863] = (230, 145, 35)
        items = [box('推荐编组', 480, 42), box('高级', 622, 165),
                 box('保存队伍', 855, 226), box('使用', 712, 277)]
        checked = EventScreen(saved, items)
        unchecked = EventScreen(image, items)
        button = checked.find('使用', (625, 195, 800, 425), exact=True)
        self.assertEqual(TeamBattle.recommendation_save_state(checked, button),
                         ((855, 265), True))
        self.assertEqual(TeamBattle.recommendation_save_state(unchecked, button),
                         ((855, 265), False))
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.wait.return_value = unchecked
        task.ensure_recommendation_unsaved(checked, button)
        task.ui.click.assert_called_once_with((855, 265))
        predicate = task.ui.wait.call_args.args[0]
        self.assertTrue(predicate(unchecked))
        task.ui.reset_mock()
        task.ensure_recommendation_unsaved(unchecked, button)
        task.ui.click.assert_not_called()

    def test_recommendation_swipes_damage_column_and_stops_on_character_page(self):
        image = np.zeros((540, 960, 3), np.uint8)
        listed = EventScreen(image, [box('推荐编组', 480, 42), box('高级', 622, 165),
                                     box('使用', 712, 407)])
        character = EventScreen(image, [box('角色强化', 105, 30)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.wait.side_effect = [listed, character]
        task.ui.capture.side_effect = [listed, listed]
        task.check_deadline = Mock()
        task.tried = set()
        with self.assertRaisesRegex(EventUIError, '进入角色页面'):
            task.recommendation()
        task.ui.swipe.assert_called_once_with((120, 360), (120, 260), duration=250)
        task.ui.expect_click.assert_called_once()
        self.assertEqual(task.tried, set())

    def test_formation_waits_for_detail_transition(self):
        image = np.zeros((540, 960, 3), np.uint8)
        transitioning = EventScreen(image, [box('队伍编组', 480, 42), box('魔物详情', 105, 52)])
        stable = EventScreen(image, [box('队伍编组', 480, 42)])
        self.assertFalse(TeamBattle.formation_ready(transitioning))
        self.assertTrue(TeamBattle.formation_ready(stable))

    def test_chest_overlay_does_not_count_as_clear_map(self):
        items = [box('团队战', 105, 35), box('剩余挑战次数', 360, 400),
                 box('讨伐信息', 240, 450)]
        dark = EventScreen(np.full((540, 960, 3), 40, np.uint8), items)
        clear = EventScreen(np.full((540, 960, 3), 190, np.uint8), items)
        self.assertFalse(TeamBattle.map_clear(dark))
        self.assertTrue(TeamBattle.map_clear(clear))

    def test_guild_stage_transition_waits_for_new_lap_and_closes_notice(self):
        image = np.zeros((540, 960, 3), np.uint8)
        notice = EventScreen(image, [box('首领魔物等级（难度）提升', 480, 145),
                                     box('关闭', 480, 370)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        self.assertTrue(task.popup(notice))
        task.ui.click.assert_called_once()

        chests = EventScreen(image, [box('已击败！', x, 260) for x in (125, 290, 480, 625)])
        next_lap = EventScreen(image, [box('第7轮', 125, 335)])
        boss = Boss(0, 7, 125, 100, 100, '首领')
        task.deadline = float('inf')
        task.all_bosses = Mock(side_effect=[[], [boss]])
        task.map = Mock(return_value=next_lap)
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            screen, bosses = task.wait_bosses(chests)
        self.assertIs(screen, next_lap)
        self.assertEqual(bosses, [boss])
        task.map.assert_called_once()

    def test_partial_simulation_result_is_recorded_without_real_attack(self):
        image = np.zeros((540, 960, 3), np.uint8)
        formation = EventScreen(image, [box('模拟战开始', 850, 455)])
        formation.blue_button = Mock(return_value=True)
        result = EventScreen(image, [box('RESULT', 480, 60), box('伤害合计', 85, 25),
                                     box('35671598×3.0', 155, 50),
                                     box('模拟战的战斗结果不会显示在团队战成绩中。', 480, 455),
                                     box('伤害比例', 390, 490), box('50.96%', 520, 490),
                                     box('下一步', 805, 490)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = [formation, result]
        task.ui.blue_button.return_value = True
        task.ui.save.return_value = 'partial.png'
        task.options = {'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': []}
        task.check_deadline = Mock()
        task.map_after_battle = Mock()
        outcome = task.battle(True, (), reference_damage=70_000_000, boss_hp=70_000_000)
        self.assertFalse(outcome['win'])
        self.assertFalse(outcome['reference_met'])
        self.assertEqual(outcome['actual_damage'], 35_671_598)
        self.assertEqual(outcome['damage_ratio'], 50.96)
        self.assertEqual(task.ui.click.call_count, 2)
        task.map_after_battle.assert_called_once()

    def test_partial_real_result_is_recorded_after_reference_met(self):
        image = np.zeros((540, 960, 3), np.uint8)
        formation = EventScreen(image, [box('战斗开始', 850, 455)])
        formation.blue_button = Mock(return_value=True)
        result = EventScreen(image, [box('RESULT', 480, 60), box('伤害合计', 85, 25),
                                     box('34000000×3.0', 155, 50),
                                     box('伤害比例', 390, 490), box('48.57%', 520, 490),
                                     box('下一步', 805, 490)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = [formation, result]
        task.ui.save.return_value = 'real-partial.png'
        task.options = {'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': []}
        task.check_deadline = Mock()
        task.map_after_battle = Mock()
        outcome = task.battle(False, (), reference_damage=30_000_000, boss_hp=70_000_000)
        self.assertFalse(outcome['win'])
        self.assertTrue(outcome['reference_met'])
        self.assertEqual(outcome['actual_damage'], 34_000_000)
        task.map_after_battle.assert_called_once()

    def test_reference_damage_rule_distinguishes_kill_from_damage_target(self):
        self.assertFalse(meets_reference(35_671_598, 70_000_000, 70_000_000, False))
        self.assertTrue(meets_reference(35_671_598, 30_000_000, 70_000_000, False))
        self.assertFalse(meets_reference(29_000_000, 30_000_000, 70_000_000, False))
        self.assertTrue(meets_reference(None, 70_000_000, 70_000_000, True))
        self.assertFalse(meets_reference(35_671_598, None, 70_000_000, False))
        result = EventScreen(np.zeros((540, 960, 3), np.uint8),
                             [box('伤害合计', 85, 25), box('35671598×3.0', 155, 50)])
        self.assertEqual(result_damage(result), 35_671_598)

    def test_damage_target_met_can_proceed_after_simulation(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_simulations': 1}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        task.teams = {'team-1': {'labels': (), 'reference_damage': 30_000_000,
                                 'estimated_seconds': 90}}
        task.tried = set()
        task.spent = set()
        task.prepare_boss = Mock()
        task.recommendation = Mock(return_value='team-1')
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(side_effect=[
            {'win': False, 'reference_met': True, 'actual_damage': 35_671_598},
            {'win': False, 'reference_met': True, 'actual_damage': 34_000_000},
        ])
        task.save_report = Mock()
        task.open_formation = Mock(return_value=object())
        task.team = Mock(return_value='team-1')
        task.used_member_marked = Mock(return_value=False)
        task.ui = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(2, 0))
        boss = Boss(0, 7, 125, 70_000_000, 70_000_000, '首领')
        row = task.try_boss(boss, 3, 0)
        self.assertFalse(row['win'])
        self.assertEqual(row['cp_after'], 2)
        self.assertEqual(task.battle.call_count, 2)
        self.assertEqual(task.battle.call_args_list[0].kwargs['reference_damage'], 30_000_000)

    def test_damage_target_missed_never_starts_real_attack(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_simulations': 1}
        task.report = {'simulations': [], 'battles': []}
        task.teams = {'team-1': {'labels': (), 'reference_damage': 70_000_000}}
        task.tried = set()
        task.prepare_boss = Mock()
        task.recommendation = Mock(return_value='team-1')
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(return_value={'win': False, 'reference_met': False,
                                          'actual_damage': 35_671_598})
        task.save_report = Mock()
        boss = Boss(0, 7, 125, 70_000_000, 70_000_000, '首领')
        self.assertIsNone(task.try_boss(boss, 3, 0))
        task.battle.assert_called_once()
        task.prepare_boss.assert_called_once_with(boss, True)

    def test_simulation_only_stops_before_real_formation(self):
        self.assertTrue(validate_options({'simulation_only': True})['simulation_only'])
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_simulations': 1}
        task.report = {'simulations': [], 'battles': []}
        task.teams = {'team-1': {'labels': (), 'reference_damage': 70_000_000}}
        task.tried = set()
        task.prepare_boss = Mock()
        task.recommendation = Mock(return_value='team-1')
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(return_value={'win': False, 'reference_met': False,
                                         'actual_damage': 35_671_598})
        task.save_report = Mock()
        task.open_formation = Mock()
        boss = Boss(0, 7, 125, 70_000_000, 70_000_000, '首领')
        self.assertFalse(task.try_boss(boss, 3, 0, simulation_only=True)['win'])
        task.battle.assert_called_once()
        task.open_formation.assert_not_called()
        self.assertEqual(len(task.report['simulations']), 1)

    def test_changed_boss_discards_old_simulation_and_rechecks_map(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_real_attacks': 1, 'simulation_only': False}
        task.report = {'status': 'running', 'pending': [], 'simulations': [],
                       'battles': [], 'attempts': 0, 'normal_attacks': 0,
                       'extension_attacks': 0}
        task.carry = None
        task.spent = set()
        task.event_valid = Mock(return_value=True)
        task.enter = Mock(return_value=object())
        screen = object()
        task.map = Mock(return_value=screen)
        task.counts = Mock(side_effect=[(1, 0), (1, 0), (1, 0), (1, 0), (0, 0)])
        boss = Boss(0, 7, 125, 70_000_000, 70_000_000, '首领')
        task.wait_bosses = Mock(return_value=(screen, [boss]))
        task.try_boss = Mock(side_effect=[BossChanged('首领血量变化'),
                                          {'win': False, 'team_key': 'team-2'}])
        task.check_deadline = Mock()
        task.save_report = Mock()
        task.ui = Mock()
        result = task.run(event=object())
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(task.try_boss.call_count, 2)
        self.assertEqual(task.map.call_count, 3)
        self.assertEqual(result['normal_attacks'], 1)

    def test_single_digit_count_retries_at_three_times_scale(self):
        ui = EventUI(None)
        ui._ocr = Mock(side_effect=[SimpleNamespace(txts=None, scores=None),
                                    SimpleNamespace(txts=('11',), scores=(.74,)),
                                    SimpleNamespace(txts=('1',), scores=(.996,))])
        screen = EventScreen(np.zeros((540, 960, 3), np.uint8), [])
        self.assertEqual(ui.number(screen, (397, 391, 431, 424)), 1)
        self.assertEqual(ui._ocr.call_count, 3)

    def test_used_character_is_rejected_even_in_simulation_formation(self):
        image = np.zeros((540, 960, 3), np.uint8)
        self.assertFalse(TeamBattle.used_member_marked(EventScreen(image, [])))
        image[482:505, 48:144] = (20, 20, 170)
        self.assertTrue(TeamBattle.used_member_marked(EventScreen(image, [])))


    def test_clan_battle_schedule_only_covers_five_days(self):
        cn = timezone(timedelta(hours=8))
        start = (datetime.now(cn)-timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
        conn = sqlite3.connect(':memory:')
        conn.create_function('ISO', 1, lambda value: str(datetime.strptime(value, '%Y/%m/%d %H:%M:%S')))
        conn.execute('CREATE TABLE clan_battle_schedule (clan_battle_id INTEGER, start_time TEXT, end_time TEXT)')
        conn.execute('INSERT INTO clan_battle_schedule VALUES (?, ?, ?)',
                     (1, start.strftime('%Y/%m/%d %H:%M:%S'),
                      (start+timedelta(days=30)).strftime('%Y/%m/%d %H:%M:%S')))
        event = _query_clan_battle(conn)
        self.assertIsNotNone(event)
        expected_end = start.replace(hour=0)+timedelta(days=5, seconds=-1)
        self.assertEqual(event.endTimestamp, expected_end.timestamp())

    def test_older_event_database_without_schedule_skips_team_battle(self):
        conn = sqlite3.connect(':memory:')
        self.assertIsNone(_query_clan_battle(conn))
