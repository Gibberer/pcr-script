from datetime import datetime, timedelta, timezone
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, EventUIError, TextBox
from pcrscript.game_ui.team_battle import Boss, can_repeat, map_bosses, meets_reference, priority, recommendation_damage, recommendation_time, result_damage
from pcrscript.news import _query_clan_battle
from pcrscript.tasks.task_team_battle import BossChanged, ORPHAN_EXTENSION, TaskDeadline, TeamBattle, validate_options


def box(text, x, y):
    return TextBox(text, 1.0, [[x-18, y-8], [x+18, y-8], [x+18, y+8], [x-18, y+8]])


class TeamBattleTests(unittest.TestCase):
    def test_lanes_and_repeat_budget(self):
        self.assertEqual(validate_options({})['timeout'], 3600)
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
        task.ui.capture.return_value = listed
        task.check_deadline = Mock()
        task.tried = set()
        task.recommendation_rows = []
        with self.assertRaisesRegex(EventUIError, '进入角色页面'):
            task.recommendation()
        task.ui.swipe.assert_called_once_with((120, 360), (120, 260), duration=250)
        task.ui.expect_click.assert_called_once()
        self.assertEqual(task.tried, set())

    def test_recommendation_scrollbar_ignores_animated_rows_at_bottom(self):
        image = np.full((540, 960, 3), 200, np.uint8)
        image[372:412, 920:925] = (220, 130, 50)
        changed = image.copy()
        changed[230:270, 185:230] = (25, 80, 220)
        items = [box('推荐编组', 480, 42), box('高级', 622, 165)]
        before = EventScreen(image, items)
        after = EventScreen(changed, items)
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.return_value = before
        task.ui.wait.return_value = after
        self.assertTrue(task.recommendation_at_end(before, up=True))
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertFalse(task.scroll_recommendations(up=True))
        task.ui.swipe.assert_called_once_with((120, 360), (120, 260), duration=250)

    def test_recommendation_updates_list_after_scanning_to_bottom(self):
        def listed(damage=None):
            image = np.full((540, 960, 3), 220, np.uint8)
            items = [box('推荐编组', 480, 42), box('高级', 622, 165),
                     box('列表更新', 840, 476)]
            if damage is not None:
                for x in (224, 312, 402, 491, 581):
                    image[220:266, x-22:x+22] = (25, 80, 220)
                items += [box('使用', 711, 277), box('参考伤害', 111, 251),
                          box(str(damage), 122, 272), box('讨伐时间', 86, 299),
                          box('0:19', 151, 299)]
            return EventScreen(image, items)

        initial = listed()
        updated = listed(70_000_000)
        formation = EventScreen(np.zeros((540, 960, 3), np.uint8),
                                [box('队伍编组', 480, 42)])
        state = {'screen': initial}
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = lambda: state['screen']
        def wait(predicate, purpose, **kwargs):
            self.assertTrue(predicate(state['screen']), purpose)
            return state['screen']
        task.ui.wait.side_effect = wait
        def expect_click(label, *args, **kwargs):
            if label == '列表更新':
                state['screen'] = updated
        task.ui.expect_click.side_effect = expect_click
        def click(button):
            if button.text == '使用':
                state['screen'] = formation
        task.ui.click.side_effect = click
        task.formation_ready = Mock(side_effect=lambda screen: screen is formation)
        task.ensure_recommendation_unsaved = Mock()
        task.recommendation_restricted = Mock(return_value=False)
        task.team = Mock(return_value='team-1')
        task.unavailable_team = Mock(return_value=False)
        task.used_member_marked = Mock(return_value=False)
        task.check_deadline = Mock()
        task.teams = {'team-1': {'labels': ('甲',), 'portraits': ()}}
        task.recommendation_rows = []
        task.tried = set()
        task.tried_teams = set()
        task.spent = set()
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertEqual(task.recommendation(boss_hp=70_000_000), 'team-1')
        self.assertEqual(task.ui.swipe.call_count, 4)
        task.ui.expect_click.assert_any_call('列表更新', (780, 445, 925, 510), exact=True)

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
        task.deadline = float('inf')
        task.options = {'max_simulations': 1, 'battle_timeout': 220}
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
        task.deadline = float('inf')
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
        task.deadline = float('inf')
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

    def test_existing_extension_uses_game_selected_team_after_restart(self):
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = float('inf')
        task.options = {'max_simulations': 1, 'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        task.teams = {'team-1': {'labels': ('a', 'b', 'c', 'd', 'e')}}
        task.prepare_boss = Mock()
        def formation(**kwargs):
            task.extension_time = 70
            return object()
        task.open_formation = Mock(side_effect=formation)
        task.team = Mock(return_value='team-1')
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(side_effect=[
            {'win': True, 'elapsed_wall': 35, 'remaining': None},
            {'win': True, 'elapsed_wall': 36, 'remaining': None},
        ])
        task.save_report = Mock()
        task.ui = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(1, 0))
        boss = Boss(0, 12, 125, 70_000_000, 70_000_000, '首领')
        row = task.try_boss(boss, 1, 1, ORPHAN_EXTENSION)
        self.assertTrue(row['win'])
        self.assertEqual(row['cp_after'], 1)
        self.assertEqual(row['extension_after'], 0)
        self.assertEqual(task.open_formation.call_args_list[1].kwargs['returned_time'], 70)

    def test_deadline_returns_partial_report_without_starting_another_action(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_real_attacks': 3, 'simulation_only': False}
        task.report = {'status': 'running', 'pending': [], 'simulations': [],
                       'battles': [], 'attempts': 0, 'normal_attacks': 0,
                       'extension_attacks': 0}
        task.event_valid = Mock(return_value=True)
        task.enter = Mock(return_value=object())
        task.check_deadline = Mock(side_effect=TaskDeadline('预算结束'))
        task.map = Mock()
        task.save_report = Mock()
        result = task.run(event=object())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['pending'], ['预算结束'])
        task.map.assert_not_called()

    def test_remaining_attempts_are_not_reported_complete_at_attack_limit(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_real_attacks': 1, 'simulation_only': False}
        task.report = {'status': 'running', 'pending': [], 'simulations': [],
                       'battles': [], 'attempts': 2, 'normal_attacks': 1,
                       'extension_attacks': 1}
        task.event_valid = Mock(return_value=True)
        task.enter = Mock(return_value=object())
        task.check_deadline = Mock()
        task.report_progress = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(1, 0))
        task.save_report = Mock()
        result = task.run(event=object())
        self.assertEqual(result['status'], 'partial')
        self.assertIn('仍有未完成挑战次数', result['pending'])

    def test_existing_extension_is_attempted_before_remaining_normal_attack(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_real_attacks': 1, 'simulation_only': False}
        task.report = {'status': 'running', 'pending': [], 'simulations': [],
                       'battles': [], 'attempts': 0, 'normal_attacks': 0,
                       'extension_attacks': 0}
        task.carry = None
        task.spent = set()
        task.event_valid = Mock(return_value=True)
        task.enter = Mock(return_value=object())
        task.check_deadline = Mock()
        task.report_progress = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(side_effect=[(1, 1), (1, 1), (0, 0)])
        boss = Boss(0, 12, 125, 70_000_000, 70_000_000, '首领')
        task.wait_bosses = Mock(return_value=(object(), [boss]))
        task.try_boss = Mock(return_value={'win': True, 'team_key': 'team-1'})
        task.save_report = Mock()
        result = task.run(event=object())
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['extension_attacks'], 1)
        self.assertEqual(task.try_boss.call_args.args[3], ORPHAN_EXTENSION)

    def test_nonlethal_extension_is_counted_once_and_does_not_retry_stale_counter(self):
        for carried in (False, True):
            with self.subTest(carried=carried):
                task = TeamBattle.__new__(TeamBattle)
                task.options = {'max_real_attacks': 1, 'simulation_only': False}
                task.report = {'status': 'running', 'pending': [], 'simulations': [],
                               'battles': [], 'attempts': 1, 'normal_attacks': 1,
                               'extension_attacks': 0}
                task.carry = ({'lane': 0, 'lap': 12, 'team_key': 'team-1',
                               'remaining': 70} if carried else None)
                task.spent = set()
                task.event_valid = Mock(return_value=True)
                task.enter = Mock(return_value=object())
                task.check_deadline = Mock()
                task.report_progress = Mock()
                task.map = Mock(return_value=object())
                task.counts = Mock(side_effect=[(1, 1), (1, 1), (1, 0), (1, 0)])
                bosses = [Boss(0, 13, 125, 70_000_000, 70_000_000, '首领甲'),
                          Boss(1, 12, 290, 70_000_000, 70_000_000, '首领乙')]
                task.wait_bosses = Mock(return_value=(object(), bosses))
                task.try_boss = Mock(return_value={'win': False, 'team_key': 'team-1'})
                task.save_report = Mock()

                result = task.run(event=object())

                self.assertEqual(result['status'], 'partial')
                self.assertEqual(result['extension_attacks'], 1)
                self.assertEqual(result['remaining_extension'], 0)
                self.assertEqual(task.spent, {'team-1'})
                self.assertIsNone(task.carry)
                self.assertEqual(task.try_boss.call_count, 1)
                self.assertIn('延长挑战实战未击败首领', result['pending'][0])

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

    def test_red_fire_portraits_are_not_participation_banners(self):
        image = np.zeros((540, 960, 3), np.uint8)
        image[482:505, 48:144] = (20, 20, 170)
        screen = EventScreen(image, [])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.read_region.return_value = screen
        self.assertFalse(task.used_member_marked(screen))
        marked = EventScreen(image, [box('已参加团队战', 95, 494)])
        self.assertTrue(task.used_member_marked(marked))
        # Tiny participation text missed by full-frame OCR still rejects.
        task.ui.read_region.return_value = marked
        self.assertTrue(task.used_member_marked(screen))

    def test_five_portraits_identify_team_despite_missing_or_changed_ocr_names(self):
        from pcrscript.tasks.event_formation import EventFormation
        image = np.zeros((540, 960, 3), np.uint8)
        slots = EventFormation.slots
        for x, _ in slots:
            image[415:494, x-38:x+38] = (30, 60, 200)
        names = ['甲', '乙', '丙', '丁', '戊']
        full = [box(name, x-26, 416) for name, (x, _) in zip(names, slots)]
        screen = EventScreen(image, [box('队伍编组', 480, 42), full[1], full[3], full[4]])
        task = TeamBattle.__new__(TeamBattle)
        task.formation = EventFormation.__new__(EventFormation)
        task.teams = {}
        task.ui = Mock()
        key = task.team(screen)
        self.assertEqual(task.teams[key]['labels'], (None, '乙', None, '丁', '戊'))
        task.ui.read_region.assert_not_called()
        self.assertEqual(task.team(EventScreen(image, [box('队伍编组', 480, 42), *full])), key)
        self.assertEqual(task.teams[key]['labels'], tuple(names))
        self.assertEqual(task.team(EventScreen(image, [box('队伍编组', 480, 42)])), key)
        # Names cannot disguise a changed portrait (including another costume).
        changed = image.copy()
        changed[428:470, slots[2][0]-30:slots[2][0]+32] = (200, 60, 30)
        self.assertNotEqual(task.team(EventScreen(changed, [box('队伍编组', 480, 42), *full])), key)
        # A genuinely empty slot must still block, regardless of OCR labels.
        image[415:494, slots[2][0]-38:slots[2][0]+38] = 0
        self.assertIsNone(task.team(screen))

    def test_unreadable_names_are_reported_unknown_without_rejecting_five_portraits(self):
        from pcrscript.tasks.event_formation import EventFormation
        image = np.full((540, 960, 3), (30, 60, 200), np.uint8)
        screen = EventScreen(image, [box('队伍编组', 480, 42)])
        task = TeamBattle.__new__(TeamBattle)
        task.formation = EventFormation.__new__(EventFormation)
        task.teams = {}
        task.ui = Mock()
        key = task.team(screen)
        self.assertEqual(task.teams[key]['labels'], (None,)*5)
        task.ui.read_region.assert_not_called()

    def test_spent_member_match_uses_portraits_when_names_are_missing(self):
        task = TeamBattle.__new__(TeamBattle)
        face = np.array([1., 0.])
        other = np.array([0., 1.])
        task.teams = {'old': {'labels': ('甲',), 'portraits': (face,)},
                      'new': {'labels': (None,), 'portraits': (face,)},
                      'costume': {'labels': ('甲',), 'portraits': (other,)}}
        task.spent = {'old'}
        self.assertTrue(task.unavailable_team('new'))
        self.assertFalse(task.unavailable_team('costume'))

    def test_recommendation_identity_survives_scroll_and_checkbox_changes(self):
        task = TeamBattle.__new__(TeamBattle)
        task.recommendation_rows = []
        rng = np.random.default_rng(73)
        faces = [rng.integers(0, 256, (40, 44, 3), dtype=np.uint8) for _ in range(5)]
        def row(y, pictures, checked):
            image = np.zeros((540, 960, 3), np.uint8)
            for x, face in zip((224, 312, 402, 491, 581), pictures):
                image[y-53:y-13, x-22:x+22] = face
            image[y-20:y, 840:870] = checked
            return EventScreen(image, []), box('使用', 712, y)
        first = task.recommendation_signature(*row(277, faces, 0))
        self.assertEqual(task.recommendation_signature(*row(337, faces, 255)), first)
        other = list(faces)
        other[2] = 255-other[2]
        self.assertNotEqual(task.recommendation_signature(*row(337, other, 0)), first)
        self.assertIsNone(task.recommendation_signature(*row(200, faces, 0)))

    def test_recommendation_accepts_full_fire_team_with_one_missing_ocr_name(self):
        from pcrscript.tasks.event_formation import EventFormation
        image = np.full((540, 960, 3), 240, np.uint8)
        for x in (224, 312, 402, 491, 581):
            image[220:266, x-22:x+22] = (25, 80, 220)
        listed = EventScreen(image, [box('推荐编组', 480, 42), box('高级', 622, 165),
                                      box('使用', 712, 277), box('保存队伍', 855, 226),
                                      box('参考伤害', 110, 251), box('70000000', 120, 272),
                                      box('讨伐时间', 86, 299), box('0:19', 151, 299)])
        fire = np.zeros_like(image)
        for x, _ in EventFormation.slots:
            fire[415:505, x-48:x+48] = (20, 20, 170)
        names = [box(name, x-26, 416) for name, (x, _) in
                 zip(('甲', '乙', '丙', '丁', '戊'), EventFormation.slots)]
        formation = EventScreen(fire, [box('队伍编组', 480, 42), *names[1:]])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.return_value = listed
        task.ui.wait.side_effect = [listed, formation]
        task.ui.read_region.side_effect = [EventScreen(image, []),
                                           EventScreen(fire, [])]
        task.formation = EventFormation.__new__(EventFormation)
        task.teams = {}
        task.recommendation_rows = []
        task.tried = set()
        task.tried_teams = set()
        task.spent = set()
        task.check_deadline = Mock()
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            key = task.recommendation(boss_hp=70_000_000)
        self.assertEqual(task.teams[key]['labels'], (None, '乙', '丙', '丁', '戊'))
        self.assertEqual(task.teams[key]['reference_damage'], 70_000_000)
        task.ui.swipe.assert_not_called()
        self.assertEqual(task.tried_teams, {key})


    def test_rejected_record_does_not_hide_same_portraits_with_valid_damage_or_time(self):
        from pcrscript.tasks.event_formation import EventFormation

        def recommendation(damage, seconds):
            image = np.full((540, 960, 3), 240, np.uint8)
            for x in (224, 312, 402, 491, 581):
                image[220:268, x-22:x+22] = (25, 80, 220)
            # Make the changed reference column visible to the scroll-end check.
            image[270:280, 80:130] = (damage//1_000_000, seconds, 0)
            return EventScreen(image, [box('推荐编组', 480, 42), box('高级', 622, 165),
                                       box('使用', 712, 277), box('保存队伍', 855, 226),
                                       box('参考伤害', 110, 251), box(str(damage), 120, 272),
                                       box('讨伐时间', 86, 299),
                                       box(f'{seconds//60}:{seconds%60:02d}', 151, 299)])

        image = np.zeros((540, 960, 3), np.uint8)
        for x, _ in EventFormation.slots:
            image[415:505, x-48:x+48] = (20, 20, 170)
        formation = EventScreen(image, [box('队伍编组', 480, 42)])
        for rejected in ((80_000_000, 10), (70_000_000, 60)):
            with self.subTest(rejected=rejected):
                accepted = recommendation(70_000_000, 20)
                state = {'screen': recommendation(*rejected)}
                task = TeamBattle.__new__(TeamBattle)
                task.ui = Mock()
                task.ui.capture.side_effect = lambda: state['screen']
                def wait(predicate, purpose, **kwargs):
                    self.assertTrue(predicate(state['screen']), purpose)
                    return state['screen']
                def click(button):
                    if button.text == '使用':
                        state['screen'] = formation
                task.ui.wait.side_effect = wait
                task.ui.click.side_effect = click
                task.ui.swipe.side_effect = lambda *args, **kwargs: state.update(screen=accepted)
                task.ui.read_region.side_effect = lambda screen, roi: EventScreen(screen.image, [])
                task.formation = EventFormation.__new__(EventFormation)
                task.teams = {}
                task.recommendation_rows = []
                task.tried = set()
                task.tried_teams = set()
                task.spent = set()
                task.check_deadline = Mock()
                with patch('pcrscript.tasks.task_team_battle.time.sleep'):
                    key = task.recommendation(boss_hp=70_000_000)
                self.assertIsNotNone(key)
                self.assertEqual(task.teams[key]['reference_damage'], 70_000_000)
                self.assertEqual(task.teams[key]['estimated_seconds'], 20)
                self.assertEqual(task.ui.swipe.call_count, 1)
                self.assertEqual(task.tried_teams, {key})

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
