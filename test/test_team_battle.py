from datetime import datetime, timedelta, timezone
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, EventUIError, TextBox
from pcrscript.game_ui.team_battle import Boss, boss_detail, can_repeat, can_repeat_clear_time, map_bosses, meets_reference, parse_remaining_time, priority, recommendation_damage, recommendation_time, result_damage, validate_counter_transition
from pcrscript.news import _query_clan_battle
from pcrscript.tasks.base import Event
from pcrscript.tasks.task_team_battle import BossChanged, ORPHAN_EXTENSION, REBUILD_EXTENSION, TaskDeadline, TeamBattle, validate_options


def box(text, x, y):
    return TextBox(text, 1.0, [[x-18, y-8], [x+18, y-8], [x+18, y+8], [x-18, y+8]])


def read_region_fixture(screen, roi, **options):
    # Numeric engine output only; banner reads remain separate observations.
    return screen if options.get('classify') is False else EventScreen(screen.image, [])


class TeamBattleTests(unittest.TestCase):
    def test_three_double_kills_validate_every_counter_transition(self):
        counts = (3, 0)
        for normal_left in (2, 1, 0):
            after = (normal_left, 1)
            validate_counter_transition(counts, after, extension=False, won=True, returned=77)
            with self.assertRaises(EventUIError):
                validate_counter_transition(counts, (normal_left, 0), extension=False, won=True, returned=77)
            counts = after
            after = (normal_left, 0)
            validate_counter_transition(counts, after, extension=True, won=True)
            with self.assertRaises(EventUIError):
                validate_counter_transition(counts, counts, extension=True, won=True)
            counts = after
        self.assertEqual(counts, (0, 0))
    def test_repeat_rules_cover_entire_timer_range_and_reject_unknown_values(self):
        # Independently model an elapsed battle and the game's capped bonus.
        for spent in range(1, 91):
            returned = min(90, 90-spent+20)
            safe = spent+8 <= returned
            self.assertEqual(can_repeat_clear_time(spent), safe)
            self.assertEqual(can_repeat(returned), safe)
        for value in (None, True, '59', -1, 91):
            self.assertFalse(can_repeat(value))
        self.assertEqual(validate_options({})['max_simulations'], 0)
        for value in (-1, True, '0', 401):
            with self.assertRaises(ValueError):
                validate_options({'max_simulations': value})

    def test_all_decision_numbers_use_upright_crop_and_keep_unknowns_unknown(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        full = EventScreen(image, [box('讨伐时间', 86, 299), box('参考伤害', 110, 251),
                                  box('0:20', 870, 453), box('0:20', 151, 299),
                                  box('6000000', 120, 272)])
        ui = Mock()
        ui.read_region.return_value = EventScreen(image, [box('1:17', 870, 453)])
        self.assertEqual(parse_remaining_time(full, ui), 77)
        ui.read_region.assert_called_with(full, (825, 435, 925, 470), classify=False)
        for text in ('1:31', '0:99'):
            ui.read_region.return_value = EventScreen(image, [box(text, 870, 453)])
            self.assertIsNone(parse_remaining_time(full, ui))
        ui.read_region.return_value = EventScreen(image, [box('0:33', 151, 299)])
        self.assertEqual(recommendation_time(full, 277, ui), 33)
        ui.read_region.return_value = EventScreen(image, [box('90000000', 120, 272)])
        self.assertEqual(recommendation_damage(full, 277, ui), 90_000_000)
        ui.read_region.return_value = EventScreen(image, [])
        self.assertIsNone(recommendation_time(full, 277, ui))
        self.assertIsNone(recommendation_damage(full, 277, ui))

    def test_boss_hp_uses_real_region_pipeline_with_numeric_direction_disabled(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        broken = EventScreen(image, [box('魔物详情', 105, 42), box('测试首领', 330, 282),
                                    box('00000006/00000006', 600, 315)])
        with TemporaryDirectory() as folder:
            ui = EventUI(None, folder)
            def engine(patch_image, **options):
                self.assertEqual(patch_image.shape[:2], (90, 645))
                text = '00000006/00000006' if options['use_cls'] else '90000000/90000000'
                return SimpleNamespace(txts=[text], scores=[.99],
                                       boxes=[[[0, 0], [600, 0], [600, 87], [0, 87]]])
            ui._ocr = Mock(side_effect=engine)
            observed = boss_detail(broken, Boss(2, 11, 480), ui)
            self.assertEqual(observed.current_hp, 90_000_000)
            ui._ocr.assert_called_once()

    def test_boss_hp_is_read_upright_before_candidate_comparison(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        broken = EventScreen(image, [box('魔物详情', 105, 42), box('测试首领', 330, 282),
                                    box('00000006/00000006', 600, 315)])
        upright = EventScreen(image, [box('90000000/90000000', 600, 315)])
        ui = Mock(read_region=Mock(return_value=upright))
        observed = boss_detail(broken, Boss(2, 11, 480), ui)
        self.assertEqual((observed.current_hp, observed.maximum_hp), (90000000, 90000000))
        ui.read_region.assert_called_once_with(broken, (490, 300, 705, 330), classify=False)
        with self.assertRaisesRegex(EventUIError, '方向或格式'):
            boss_detail(broken, Boss(2, 11, 480))
        ui.read_region.return_value = EventScreen(image, [])
        with self.assertRaisesRegex(EventUIError, '无法识别'):
            boss_detail(broken, Boss(2, 11, 480), ui)

    def test_boss_scan_reuses_each_fresh_map_and_detail_observation(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        mapped = EventScreen(image, [box('团队战', 105, 35), box('剩余挑战次数', 350, 406),
                                    box('讨伐信息', 240, 450), box('第2轮', 125, 278),
                                    box('第2轮', 290, 339)])
        def detail(name):
            return EventScreen(image, [box('魔物详情', 105, 42), box(name, 330, 282),
                                       box('100/100', 600, 303), box('取消', 657, 460)])
        with TemporaryDirectory() as folder:
            task = TeamBattle.__new__(TeamBattle)
            task.ui = EventUI(None, folder)
            task.ui.read_region = Mock(side_effect=lambda screen, roi, **kwargs: screen)
            task.ui.capture = Mock(side_effect=[detail('首领甲'), mapped, detail('首领乙'), mapped])
            task.ui.click = Mock()
            task.ui.expect_click = Mock(side_effect=AssertionError('不应重复读取已核实的详情'))
            task.check_deadline = Mock()
            bosses = task.all_bosses(mapped)
            self.assertEqual([b.name for b in bosses], ['首领甲', '首领乙'])
            self.assertEqual(task.ui.capture.call_count, 4)
            self.assertEqual([getattr(c.args[0], 'text', c.args[0]) for c in task.ui.click.call_args_list],
                             [(125, 270), '取消', (290, 270), '取消'])
            # A separately requested pre-battle detail must still get a new map.
            task.map = Mock(return_value=mapped)
            task.ui.capture.side_effect = [detail('首领甲')]
            task.open_boss(bosses[0])
            task.map.assert_called_once()

    def test_reward_refresh_discards_partially_read_boss_list(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        def mapped(lap):
            return EventScreen(image, [box('团队战', 105, 35), box('剩余挑战次数', 350, 406),
                                       box('讨伐信息', 240, 450), box(f'第{lap}轮', 125, 278)])
        task = TeamBattle.__new__(TeamBattle)
        fresh = Boss(0, 2, 125, 42, 42, '首领')
        task.ui = Mock()
        task.map = Mock(return_value=mapped(2))
        task.open_boss = Mock(side_effect=[BossChanged('行会报酬刷新'), (fresh, EventScreen(image, []))])
        self.assertEqual(task.all_bosses(mapped(1)), [fresh])
        self.assertEqual([c.args[0].lap for c in task.open_boss.call_args_list], [1, 2])
        task.ui.expect_click.assert_called_once_with('取消', (560, 425, 755, 505), exact=True)

    def test_defeated_target_notice_recovers_to_map_without_battle_clicks(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        notice = EventScreen(image, [box('错误提示', 480, 147),
                                    box('该怪物已被讨伐。', 480, 267), box('确认', 480, 372)])
        listed = EventScreen(image, [box('推荐编组', 480, 42), box('高级', 622, 165)])
        detail = EventScreen(image, [box('魔物详情', 105, 42)])
        mapped = EventScreen(image, [box('团队战', 105, 35), box('剩余挑战次数', 350, 406),
                                    box('讨伐信息', 240, 450)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = [listed, detail, mapped]
        self.assertTrue(task.recover_defeated_boss(notice))
        task.ui.click.assert_called_once_with(notice.items[2])
        self.assertEqual([c.args[0] for c in task.ui.expect_click.call_args_list], ['关闭', '取消'])
        task.ui.reset_mock()
        task.ui.capture.side_effect = [notice, listed, detail, mapped, mapped]
        task.check_deadline = Mock()
        self.assertIs(task.enter(), mapped)
        task.ui.click.assert_called_once_with(notice.items[2])
        task.ui.reset_mock()
        notice.items[1].text = '未知错误'
        self.assertFalse(task.recover_defeated_boss(notice))
        task.ui.click.assert_not_called()

    def test_known_incomplete_real_formation_returns_without_starting_battle(self):
        image = np.zeros((540, 960, 3), np.uint8)
        missing = EventScreen(image, [box('队伍编组', 480, 42),
                                     box('编组成员不足5名角色。', 740, 415), box('取消', 710, 453)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.report = {'simulations': [{}]}
        task.formation = Mock()
        task.formation.occupied_slots.return_value = [0, 1, 2, 3]
        task.map = Mock()
        self.assertTrue(task.reject_incomplete_real_team(missing))
        self.assertEqual([c.args[0] for c in task.ui.expect_click.call_args_list], ['取消', '取消'])
        task.ui.click.assert_not_called()
        task.map.assert_called_once()
        task.ui.reset_mock()
        task.formation.occupied_slots.return_value = list(range(5))
        self.assertFalse(task.reject_incomplete_real_team(missing))
        task.ui.expect_click.assert_not_called()
        # The unformed slot can be red enough to pass the saturation heuristic.
        missing.items.append(box('未编组', 96, 452))
        self.assertTrue(task.reject_incomplete_real_team(missing))
        task.ui.reset_mock()
        task.formation.occupied_slots.return_value = [0, 1, 2, 3]
        unknown = EventScreen(image, [box('队伍编组', 480, 42), box('未知错误', 740, 415)])
        self.assertFalse(task.reject_incomplete_real_team(unknown))
        task.ui.expect_click.assert_not_called()
        task.formation.occupied_slots.return_value = []
        empty = EventScreen(image, [box('队伍编组', 480, 42),
                                   box('总战力', 440, 389), box('0', 578, 389)])
        task.ui.number.return_value = 0
        self.assertTrue(task.reject_incomplete_real_team(empty))

    def test_restart_restores_same_boss_preference_only_within_device_event_and_day(self):
        with TemporaryDirectory() as folder:
            event = Event(100, 1_000_000, '团队战')
            def task(device='synthetic', event=event, now=200_000):
                value = TeamBattle.__new__(TeamBattle)
                value.options = {'state_dir': folder}
                value.driver = SimpleNamespace(device_name=device)
                value.extension_target = None
                with patch('pcrscript.tasks.task_team_battle.time.time', return_value=now):
                    value.load_extension_target(event)
                return value
            first = task()
            first.remember_extension_target(Boss(0, 1, 125, 42, 42, '首领甲'))
            restored = task()
            same = Boss(0, 2, 125, 42, 42, '首领甲')
            older = Boss(1, 1, 290, 42, 42, '首领乙')
            self.assertEqual(restored.extension_candidates([older, same]), [same, older])
            self.assertIsNone(task(device='other').extension_target)
            self.assertIsNone(task(event=Event(101, 1_000_000, '团队战')).extension_target)
            self.assertIsNone(task(now=200_000+86400).extension_target)
            restored.remember_extension_target()
            self.assertIsNone(task().extension_target)
            self.assertEqual(task().extension_candidates([same, older]), [older, same])

    def test_map_includes_high_round_badges_but_not_stage_header(self):
        items = [box('团队战', 105, 35), box('剩余挑战次数', 350, 406),
                 box('讨伐信息', 240, 450), box('第1轮', 280, 60)]
        items += [box('第1轮', x, y) for x, y in
                  zip((125, 290, 480, 625, 840), (278, 339, 256, 347, 241))]
        bosses = map_bosses(EventScreen(np.zeros((540, 960, 3), np.uint8), items))
        self.assertEqual(sorted(b.lane for b in bosses), list(range(5)))

    def test_challenge_count_never_treats_unknown_or_overflow_as_available(self):
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        for value in (None, -1, 4, 10):
            task.ui.number.return_value = value
            with self.assertRaisesRegex(EventUIError, '次数无法确认'):
                task.count(Mock(), (557, 394, 587, 414))
        for value in (0, 1, 2, 3):
            task.ui.number.return_value = value
            self.assertEqual(task.count(Mock(), (557, 394, 587, 414)), value)

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
        self.assertFalse(can_repeat(50))  # 30s left + 20s bonus; first kill took 60s.
        self.assertFalse(can_repeat(58))
        self.assertTrue(can_repeat(59))
        self.assertTrue(can_repeat(90))


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
        restricted.items[-1].text = '限制实战'
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
        task.ui.swipe.assert_called_once_with((120, 395), (120, 210), duration=450)
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
        task.check_deadline = Mock()
        self.assertTrue(task.recommendation_at_end(before, up=True))
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertFalse(task.scroll_recommendations(up=True))
        task.ui.swipe.assert_called_once_with((120, 395), (120, 210), duration=450)

    def test_middle_list_swipe_failure_is_not_candidate_exhaustion(self):
        def listed(top):
            image = np.full((540,960,3), 220, np.uint8)
            image[top:top+35,920:925] = (220,130,50)
            return EventScreen(image, [box('推荐编组',480,42),box('高级',622,165)])
        middle = listed(240)
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.return_value = middle
        task.ui.wait.return_value = middle
        task.check_deadline = Mock()
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            with self.assertRaisesRegex(EventUIError, '未按候选耗尽处理'):
                task.scroll_recommendations(up=True)
        self.assertEqual(task.ui.swipe.call_count, 2)
        task.ui.swipe.reset_mock()
        task.ui.wait.side_effect = [middle, listed(290)]
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertTrue(task.scroll_recommendations(up=True))
        self.assertEqual(task.ui.swipe.call_count, 2)

    def test_recommendation_updates_list_after_scanning_to_bottom(self):
        def listed(damage=None):
            image = np.full((540, 960, 3), 220, np.uint8)
            top = 375 if damage is None else 194
            image[top:top+35,920:925] = (220,130,50)
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
        modal_image = np.zeros((540, 960, 3), np.uint8)
        modal_image[379:410, 346:381] = (230,155,25)
        modal = EventScreen(modal_image, [box('确认使用延长时间',480,42), box('0:50',330,195)])
        state = {'screen': initial}
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = lambda: state['screen']
        task.ui.read_region.side_effect = read_region_fixture
        def wait(predicate, purpose, **kwargs):
            self.assertTrue(predicate(state['screen']), purpose)
            return state['screen']
        task.ui.wait.side_effect = wait
        def expect_click(label, *args, **kwargs):
            if label == '列表更新':
                state['screen'] = updated
            elif label == '挑战' and args[0] == (590, 145, 700, 215):
                state['screen'] = formation
        task.ui.expect_click.side_effect = expect_click
        def click(button):
            if getattr(button, 'text', None) == '使用':
                state['screen'] = modal
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
            self.assertEqual(task.recommendation(boss_hp=70_000_000, use_extension=True,
                                                returned_time=50), 'team-1')
        task.ui.swipe.assert_not_called()
        task.ui.expect_click.assert_any_call('列表更新', (780, 445, 925, 510), exact=True)
        task.ui.expect_click.assert_any_call('挑战', (590,145,700,215), exact=True)
        task.ui.click.assert_any_call((363,393))
        self.assertEqual(task.extension_time, 50)

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

    def test_damage_only_simulation_never_starts_normal_attack(self):
        # The task covers A/B/C stages only: normal attacks must kill even
        # on a damaged boss, so a met damage target is not enough.
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = float('inf')
        task.options = {'max_simulations': 1, 'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        task.teams = {'team-1': {'labels': (), 'reference_damage': 30_000_000,
                                 'estimated_seconds': 90}}
        task.prepare_boss = Mock()
        task.recommendation = Mock(return_value='team-1')
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(return_value={'win': False, 'reference_met': True, 'actual_damage': 35_671_598})
        task.save_report = Mock()
        task.open_formation = Mock()
        boss = Boss(0, 7, 125, 70_000_000, 90_000_000, '首领')
        with self.assertRaises(TaskDeadline):
            task.try_boss(boss, 3, 0)
        task.battle.assert_called_once()
        task.open_formation.assert_not_called()
        self.assertEqual(task.report['candidate_rejections'], {'模拟未通过击杀或双刀校验': 1})

    def test_repeated_failed_simulations_leave_boss_as_out_of_scope(self):
        self.assertEqual(validate_options({})['max_boss_failures'], 3)
        for value in (-1, 101, True, 1.5):
            with self.assertRaises(ValueError):
                validate_options({'max_boss_failures': value})
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = float('inf')
        task.options = {'max_simulations': 0, 'max_boss_failures': 3, 'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        names = [f'team-{i}' for i in range(1, 6)]
        task.teams = {key: {'labels': (), 'reference_damage': 70_000_000} for key in names}
        task.prepare_boss = Mock()
        task.recommendation = Mock(side_effect=names)
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(return_value={'win': False, 'reference_met': False})
        task.save_report = Mock()
        task.open_formation = Mock()
        task.log = Mock()
        self.assertIsNone(task.try_boss(Boss(0, 7, 125, 70_000_000, 70_000_000, '合成首领'), 3, 0))
        self.assertEqual(task.battle.call_count, 3)
        task.open_formation.assert_not_called()
        self.assertEqual(task.report['candidate_rejections']['超出低难度前提的连续模拟失败'], 1)

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
        with self.assertRaisesRegex(TaskDeadline, '程序设置的模拟搜索轮数上限'):
            task.try_boss(boss, 3, 0)
        task.battle.assert_called_once()
        task.prepare_boss.assert_called_once_with(boss, True)
        task.recommendation.assert_called_once_with(boss_hp=70_000_000, boss_full=True)
        # A full boss must still be killed even if a lower damage reference
        # was met. This used to bypass the double-kill requirement.
        task.report = {'simulations': [], 'battles': []}
        task.battle.reset_mock()
        task.battle.return_value = {'win': False, 'reference_met': True, 'actual_damage': 35_671_598}
        with self.assertRaises(TaskDeadline):
            task.try_boss(boss, 3, 0)
        task.battle.assert_called_once()
        self.assertEqual(task.report['candidate_rejections'], {'模拟未通过击杀或双刀校验': 1})

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
        # A failed rehearsal simulation keeps searching like a real run.
        with self.assertRaises(TaskDeadline):
            task.try_boss(boss, 3, 0, simulation_only=True)
        task.battle.return_value = {'win': True, 'remaining': 70}
        task.options = {'max_simulations': 0}
        row = task.try_boss(boss, 3, 0, simulation_only=True)
        self.assertEqual(row['team_key'], 'team-1')
        self.assertEqual(task.battle.call_count, 2)
        task.open_formation.assert_not_called()
        self.assertEqual(len(task.report['simulations']), 2)

    def test_rehearsal_treats_each_passing_team_as_spent(self):
        task = TeamBattle.__new__(TeamBattle)
        task.options = {'max_real_attacks': 3}
        task.report = {'simulations': [], 'battles': [], 'pending': []}
        task.spent = set()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(0, 0))
        boss = Boss(0, 7, 125, 70_000_000, 70_000_000, '首领')
        task.wait_bosses = Mock(return_value=(object(), [boss]))
        task.save_report = Mock()
        task.report_progress = Mock()
        spent_seen = []
        def try_boss(target, cp, extension, *, simulation_only):
            self.assertTrue(simulation_only)
            spent_seen.append(set(task.spent))
            key = f'team-{len(spent_seen)}'
            return {'boss': target.name, 'lane': 0, 'lap': 7, 'team_key': key, 'team': (), 'remaining': 70}
        task.try_boss = Mock(side_effect=try_boss)
        report = task.rehearse()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(spent_seen, [set(), {'team-1'}, {'team-1', 'team-2'}])
        self.assertEqual(len(report['rehearsal']), 3)
        task.try_boss = Mock(return_value=None)
        task.spent = set()
        task.report = {'simulations': [], 'battles': [], 'pending': [], 'candidate_rejections': {'x': 1}}
        report = task.rehearse()
        self.assertEqual(report['status'], 'partial')
        self.assertIn('模拟预演第1刀', report['pending'][0])

    def test_free_search_continues_past_twelve_failures_before_any_real_attack(self):
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = float('inf')
        task.options = {'max_simulations': 0, 'max_boss_failures': 0, 'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        names = [f'team-{i}' for i in range(1, 14)]
        task.teams = {key: {'labels': (), 'reference_damage': 70_000_000} for key in names}
        task.prepare_boss = Mock()
        task.recommendation = Mock(side_effect=names)
        task.equipped = Mock(return_value={'slots': []})
        modes = []
        def battle(simulate, *args, **kwargs):
            modes.append(simulate)
            if len(modes) <= 12:
                self.assertTrue(simulate)
                self.assertNotIn('in_flight', task.report)
                return {'win': False, 'reference_met': False}
            return {'win': True, 'remaining': 77}
        task.battle = Mock(side_effect=battle)
        task.save_report = Mock()
        task.open_formation = Mock(return_value=object())
        task.team = Mock(return_value='team-13')
        task.used_member_marked = Mock(return_value=False)
        task.ui = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(2, 1))
        result = task.try_boss(Boss(0, 7, 125, 70_000_000, 70_000_000, '合成首领'), 3, 0)
        self.assertTrue(result['win'])
        self.assertEqual(modes, [True]*13+[False])
        self.assertEqual(len(task.report['simulations']), 13)
        self.assertEqual(task.report['attempts'], 1)
        task.options['max_simulations'] = 1
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        task.recommendation.side_effect = ['team-13']
        task.battle.side_effect = [{'win': True, 'remaining': 77}, {'win': True, 'remaining': 77}]
        task.counts.return_value = (2, 0)
        with self.assertRaisesRegex(EventUIError, '次数变化与预期不符'):
            task.try_boss(Boss(0, 7, 125, 70_000_000, 70_000_000, '合成首领'), 3, 0)
        self.assertTrue(task.report['in_flight']['result']['win'])
        self.assertEqual(task.report['battles'], [])
        self.assertEqual(task.battle.call_args.args[0], False)

    def test_free_simulation_search_still_obeys_execution_deadline(self):
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = -1
        task.options = {'max_simulations': 0}
        task.recommendation = Mock()
        task.battle = Mock()
        with self.assertRaises(TaskDeadline):
            task.try_boss(Boss(0, 7, 125, 100, 100, '合成首领'), 3, 0)
        task.recommendation.assert_not_called()
        task.battle.assert_not_called()

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
            {'win': True, 'elapsed_wall': 100, 'remaining': None},
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

    def test_first_normal_rejects_bonus_inflated_return_before_spending(self):
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = float('inf')
        task.options = {'max_simulations': 2, 'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        task.teams = {key: {'labels': (), 'reference_damage': 70_000_000}
                      for key in ('slow', 'fast')}
        task.prepare_boss = Mock()
        task.recommendation = Mock(side_effect=['slow', 'fast'])
        task.equipped = Mock(return_value={'slots': []})
        task.battle = Mock(side_effect=[
            {'win': True, 'remaining': 50, 'elapsed_wall': 68},
            {'win': True, 'remaining': 70, 'elapsed_wall': 48},
            {'win': True, 'remaining': 70, 'elapsed_wall': 49},
        ])
        task.save_report = Mock()
        task.open_formation = Mock(return_value=object())
        task.team = Mock(return_value='fast')
        task.used_member_marked = Mock(return_value=False)
        task.ui = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(2, 1))
        boss = Boss(0, 7, 125, 70_000_000, 70_000_000, '首领')
        row = task.try_boss(boss, 3, 0)
        self.assertEqual(row['team_key'], 'fast')
        self.assertEqual([(c.args[0], c.args[1]) for c in task.battle.call_args_list],
                         [(True, 'slow'), (True, 'fast'), (False, 'fast')])
        self.assertEqual([c.args[1] for c in task.prepare_boss.call_args_list], [True, True, False])
        task.open_formation.assert_called_once_with(use_extension=False, returned_time=None)
        self.assertEqual(task.report['attempts'], 1)

    def test_rebuilt_extension_retries_simulation_and_preserves_new_team_for_real(self):
        task = TeamBattle.__new__(TeamBattle)
        task.deadline = float('inf')
        task.options = {'max_simulations': 2, 'battle_timeout': 220}
        task.report = {'simulations': [], 'battles': [], 'attempts': 0}
        task.teams = {key: {'labels': (), 'reference_damage': 70_000_000}
                      for key in ('new-1', 'new-2')}
        task.prepare_boss = Mock()
        def recommendation(**kwargs):
            task.extension_time = 50
            return next(choices)
        choices = iter(['new-1', 'new-2'])
        task.recommendation = Mock(side_effect=recommendation)
        task.equipped = Mock(return_value={'slots': []})
        def formation(**kwargs):
            task.extension_time = 50
            return object()
        task.open_formation = Mock(side_effect=formation)
        task.team = Mock(return_value='new-2')
        task.battle = Mock(side_effect=[
            {'win': False, 'reference_met': False, 'actual_damage': 30_000_000},
            {'win': True, 'remaining': None, 'elapsed_wall': 95},
            {'win': True, 'remaining': None, 'elapsed_wall': 96},
        ])
        task.save_report = Mock()
        task.ui = Mock()
        task.map = Mock(return_value=object())
        task.counts = Mock(return_value=(2, 0))
        boss = Boss(0, 8, 125, 70_000_000, 70_000_000, '首领')
        row = task.try_boss(boss, 2, 1, REBUILD_EXTENSION)
        self.assertEqual(row['team_key'], 'new-2')
        self.assertEqual((row['cp_before'], row['cp_after'], row['extension_after']), (2, 2, 0))
        self.assertEqual([(c.args[0], c.args[1]) for c in task.battle.call_args_list],
                         [(True, 'new-1'), (True, 'new-2'), (False, 'new-2')])
        self.assertTrue(all(c.kwargs['preserve_team'] and c.kwargs['use_extension']
                            for c in task.open_formation.call_args_list))
        self.assertEqual([c.kwargs['returned_time'] for c in task.open_formation.call_args_list], [50])
        self.assertEqual([c.kwargs['returned_time'] for c in task.recommendation.call_args_list], [None, 50])

    def test_extension_checkbox_preserves_requested_team_and_validates_return_time(self):
        for preserve in (False, True):
            for checked in (False, True):
                image = np.zeros((540, 960, 3), np.uint8)
                if checked:
                    image[379:410, 346:381] = (230, 155, 25)
                modal = EventScreen(image, [box('确认使用延长时间',480,42), box('0:50',330,195)])
                formation = EventScreen(image, [box('队伍编组',480,42)])
                task = TeamBattle.__new__(TeamBattle)
                task.ui = Mock()
                task.ui.wait.side_effect = [modal, formation]
                task.ui.capture.return_value = formation
                with patch('pcrscript.tasks.task_team_battle.time.sleep'):
                    self.assertIs(task.open_formation(use_extension=True, returned_time=50,
                                                     preserve_team=preserve), formation)
                self.assertEqual(task.ui.click.call_count, int(checked == preserve))
                if checked == preserve:
                    task.ui.click.assert_called_once_with((363,393))
                self.assertEqual(task.extension_time, 50)

    def test_enter_closes_only_identified_interrupted_simulation_result(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        result = EventScreen(image, [box('RESULT',480,60),
            box('模拟战的战斗结果不会显示在团队战成绩中。',480,455), box('下一步',805,490)])
        mapped = EventScreen(image, [box('团队战',105,35), box('剩余挑战次数',350,406),
                                    box('讨伐信息',240,450)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = [result, mapped]
        task.check_deadline = Mock()
        self.assertIs(task.enter(), mapped)
        task.ui.click.assert_called_once_with(result.items[2])
        panel = EventScreen(image, [box('特别装备设定',480,42),box('取消',147,480)])
        task.ui.capture.side_effect = [panel, mapped]
        task.ui.click.reset_mock()
        self.assertIs(task.enter(), mapped)
        task.ui.expect_click.assert_called_once_with('取消',(35,445,265,520),exact=True)
        task.ui.click.assert_not_called()
        result.items.pop(1)
        task.ui.click.reset_mock()
        task.ui.capture.side_effect = [result, mapped]
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertIs(task.enter(), mapped)
        task.ui.click.assert_not_called()

    def test_stage_scope_blocks_high_and_unknown_before_mode_change(self):
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock(read_region=Mock(side_effect=lambda s,*a,**k:s))
        image = np.zeros((540,960,3),np.uint8)
        for stage in ('第1阶段','第2阶段','第3阶段','A阶段','阶段C'):
            task.require_low_stage(EventScreen(image,[box(stage,85,130)]))
        for stage in ('第4阶段','第10阶段','D阶段','阶段E','未知'):
            with self.assertRaises(TaskDeadline):
                task.require_low_stage(EventScreen(image,[box(stage,85,130)]))

    def test_settled_real_result_is_left_and_dropped_next_tap_repeated(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        result = EventScreen(image, [box('WIN!',480,130), box('伤害比例',405,492), box('下一步',805,490)])
        mapped = EventScreen(image, [box('团队战',105,35), box('剩余挑战次数',350,406),
                                    box('讨伐信息',240,450), box('第14轮',290,338)])
        running = EventScreen(image, [box('WIN!',480,130), box('伤害比例',405,492),
                                     box('下一步',805,490), box('菜单',900,30)])
        self.assertIsNone(TeamBattle.settled_result_next(running))
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.check_deadline = Mock()
        task.ui.capture.side_effect = [result, mapped]
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertIs(task.enter(), mapped)
        task.ui.click.assert_called_once_with(result.items[2])
        # The first tap was dropped: the result is still shown, tap again.
        task.ui.click.reset_mock()
        task.ui.capture.side_effect = [result, result, mapped]
        task.popup = Mock(return_value=False)
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertIs(task.map_after_battle(), mapped)
        task.ui.click.assert_called_once_with(result.items[2])

    def test_enter_logs_in_from_title_screen_through_home_navigation(self):
        image = np.full((540, 960, 3), 240, np.uint8)
        title = EventScreen(image, [box('点击屏幕开始游戏',485,480), box('主菜单',70,505)])
        mapped = EventScreen(image, [box('团队战',105,35), box('剩余挑战次数',350,406),
                                    box('讨伐信息',240,450)])
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.ui.capture.side_effect = [title, mapped]
        task.check_deadline = Mock()
        task.robot = Mock()
        with patch('pcrscript.tasks.task_home.ToHomePage') as home:
            self.assertIs(task.enter(), mapped)
        home.assert_called_once_with(task.robot)
        home.return_value.run.assert_called_once_with(timeout=180)
        task.ui.click.assert_not_called()

    def test_extension_keeps_same_boss_priority_and_considers_known_residual_hp(self):
        task = TeamBattle.__new__(TeamBattle)
        task.extension_target = {'lane': 0, 'lap': 7}
        residual = Boss(0, 8, 125, 40_000_000, 70_000_000, '首领甲')
        full = Boss(1, 7, 290, 70_000_000, 70_000_000, '首领乙')
        unknown = Boss(2, 7, 480)
        self.assertEqual(task.extension_candidates([full, unknown, residual]), [residual, full])

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
        for text in ('已参加团队战', '限制实战使用'):
            marked = EventScreen(image, [box(text, 95, 494)])
            self.assertTrue(task.used_member_marked(marked))
            # Tiny restriction text missed by full-frame OCR still rejects.
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
        screen.items.append(box('未编组', 96, 452))
        self.assertIsNone(task.team(screen))

    def test_spent_member_match_uses_portraits_when_names_are_missing(self):
        task = TeamBattle.__new__(TeamBattle)
        face = np.array([1., 0.])
        other = np.array([0., 1.])
        task.teams = {'old': {'labels': ('甲',), 'portraits': (face,), 'centered': (face,)},
                      'new': {'labels': (None,), 'portraits': (face,), 'centered': (face,)},
                      'costume': {'labels': ('甲',), 'portraits': (other,), 'centered': (other,)}}
        task.spent = {'old'}
        self.assertTrue(task.unavailable_team('new'))
        self.assertFalse(task.unavailable_team('costume'))
        task.teams['new'].pop('centered')
        with self.assertRaisesRegex(EventUIError, '身份特征不完整'):
            task.unavailable_team('new')

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
        task.ui.read_region.side_effect = read_region_fixture
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
                task.ui.read_region.side_effect = read_region_fixture
                task.formation = EventFormation.__new__(EventFormation)
                task.report = {}
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
                reason = '参考伤害超过当前血量' if rejected[0] > 70_000_000 else '参考耗时不满足双刀预算'
                self.assertEqual(task.report['candidate_rejections'], {reason: 1})

    def test_normal_attack_skips_damage_only_row_before_simulation(self):
        from pcrscript.tasks.event_formation import EventFormation

        def recommendation(damage, seconds, colour=(25, 80, 220)):
            image = np.full((540, 960, 3), 240, np.uint8)
            for x in (224, 312, 402, 491, 581):
                image[220:268, x-22:x+22] = colour
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
        for full in (True, False):
            with self.subTest(full=full):
                damage_only = recommendation(30_000_000, 90)
                kill = recommendation(70_000_000, 20)
                state = {'screen': damage_only, 'used': []}
                task = TeamBattle.__new__(TeamBattle)
                task.ui = Mock()
                task.ui.capture.side_effect = lambda: state['screen']
                def wait(predicate, purpose, **kwargs):
                    self.assertTrue(predicate(state['screen']), purpose)
                    return state['screen']
                def click(button):
                    if button.text == '使用':
                        state['used'].append(state['screen'])
                        state['screen'] = formation
                task.ui.wait.side_effect = wait
                task.ui.click.side_effect = click
                task.ui.swipe.side_effect = lambda *args, **kwargs: state.update(screen=kill)
                task.ui.read_region.side_effect = read_region_fixture
                task.formation = EventFormation.__new__(EventFormation)
                task.report = {}
                task.teams = {}
                task.recommendation_rows = []
                task.tried = set()
                task.tried_teams = set()
                task.spent = set()
                task.check_deadline = Mock()
                with patch('pcrscript.tasks.task_team_battle.time.sleep'):
                    key = task.recommendation(boss_hp=70_000_000, boss_full=full)
                # Kill-only normal attacks: a damaged boss also skips the row.
                self.assertEqual(task.teams[key]['reference_damage'], 70_000_000)
                self.assertEqual(state['used'], [kill])
                self.assertEqual(task.report.get('candidate_rejections', {}), {'参考伤害不足以击杀': 1})

                # A pale but complete row is checked on the formation page
                # instead of being rejected from portrait colour alone.
                pale = recommendation(70_000_000, 20, colour=(225, 225, 225))
                state.update(screen=pale, used=[])
                task.recommendation_rows = []
                task.tried = set()
                task.tried_teams = set()
                task.teams = {}
                task.report = {}
                self.assertFalse(TeamBattle.recommendation_owned(pale, pale.find('使用')))
                with patch('pcrscript.tasks.task_team_battle.time.sleep'):
                    key = task.recommendation(boss_hp=70_000_000, boss_full=full)
                self.assertIsNotNone(key)
                self.assertEqual(state['used'], [pale])
                self.assertEqual(task.report['gray_portrait_checks'], {'formation_checked': 1})
                self.assertNotIn('candidate_rejections', task.report)

    def test_spent_portrait_match_ignores_shared_frame_brightness(self):
        from pcrscript.game_ui.avatars import feature
        from pcrscript.tasks.task_team_battle import centered_feature
        first = np.full((42, 62, 3), 235, np.uint8)
        first[8:16, 10:22] = (120, 150, 200)
        second = np.full((42, 62, 3), 235, np.uint8)
        second[26:34, 40:52] = (120, 150, 200)
        noisy = np.clip(first.astype(int)+np.random.default_rng(5).integers(-6, 7, first.shape),
                        0, 255).astype(np.uint8)
        # The legacy fixed-offset cosine alone confuses the two characters.
        self.assertGreaterEqual(float(feature(first) @ feature(second)), .92)

        def team(*crops):
            return dict(labels=(None,)*len(crops), portraits=tuple(feature(c) for c in crops),
                        centered=tuple(centered_feature(c) for c in crops))
        task = TeamBattle.__new__(TeamBattle)
        task.teams = {'old': team(first), 'other': team(second), 'same': team(noisy)}
        task.spent = {'old'}
        self.assertFalse(task.unavailable_team('other'))
        self.assertTrue(task.unavailable_team('same'))

    def test_team_grouping_does_not_alias_bright_but_different_portraits(self):
        from pcrscript.tasks.event_formation import EventFormation
        from pcrscript.game_ui.avatars import feature
        slots = EventFormation.slots
        def formation(lower=False, shared=False, noise=False):
            image = np.zeros((540, 960, 3), np.uint8)
            for i, (x, _) in enumerate(slots):
                image[415:494, x-38:x+38] = (30, 60, 200)
                crop = np.full((42, 62, 3), 235, np.uint8)
                if lower and not (shared and i == 0):
                    crop[26:34, 40:52] = (120, 150, 200)
                else:
                    crop[8:16, 10:22] = (120, 150, 200)
                if noise:
                    crop = np.clip(crop.astype(int)+np.random.default_rng(i).integers(-3, 4, crop.shape),
                                   0, 255).astype(np.uint8)
                image[428:470, x-30:x+32] = crop
            return EventScreen(image, [box('队伍编组', 480, 42)])
        first, other = formation(), formation(lower=True)
        x = slots[0][0]
        self.assertGreaterEqual(float(feature(first.image[428:470,x-30:x+32]) @
                                      feature(other.image[428:470,x-30:x+32])), .92)
        task = TeamBattle.__new__(TeamBattle)
        task.formation = EventFormation.__new__(EventFormation)
        task.teams = {}
        task.spent = set()
        old = task.team(first)
        self.assertEqual(task.team(formation(noise=True)), old)
        task.spent.add(old)
        new = task.team(other)
        self.assertNotEqual(new, old)
        self.assertFalse(task.unavailable_team(new))
        self.assertTrue(task.unavailable_team(task.team(formation(lower=True, shared=True))))

    def test_tried_bright_recommendation_does_not_hide_a_different_party(self):
        from pcrscript.tasks.event_formation import EventFormation
        def row(lower):
            image = np.full((540, 960, 3), 240, np.uint8)
            for x in (224, 312, 402, 491, 581):
                crop = np.full((40, 44, 3), 235, np.uint8)
                crop[26:34, 29:39] = (120,150,200) if lower else (235,235,235)
                if not lower:
                    crop[8:16, 5:15] = (120,150,200)
                image[224:264, x-22:x+22] = crop
            return EventScreen(image, [box('推荐编组',480,42), box('高级',622,165),
                box('使用',712,277), box('保存队伍',855,226), box('参考伤害',110,251),
                box('70000000',120,272), box('讨伐时间',86,299), box('0:20',151,299)])
        old, listed = row(False), row(True)
        image = np.zeros((540,960,3), np.uint8)
        for x, _ in EventFormation.slots:
            image[415:505,x-48:x+48] = (20,20,170)
        formation = EventScreen(image, [box('队伍编组',480,42)])
        state = {'screen': listed}
        task = TeamBattle.__new__(TeamBattle)
        task.formation = EventFormation.__new__(EventFormation)
        task.teams, task.spent, task.tried_teams = {}, set(), set()
        task.recommendation_rows = []
        prior = task.recommendation_signature(old, old.find('使用'))
        task.tried = {f'{prior}-70000000-20'}
        task.report = {}
        task.check_deadline = Mock()
        task.ui = Mock()
        task.ui.capture.side_effect = lambda: state['screen']
        task.ui.read_region.side_effect = read_region_fixture
        def click(button):
            if button.text == '使用':
                state['screen'] = formation
        def wait(predicate, label, **kwargs):
            self.assertTrue(predicate(state['screen']), label)
            return state['screen']
        task.ui.click.side_effect = click
        task.ui.wait.side_effect = wait
        with patch('pcrscript.tasks.task_team_battle.time.sleep'):
            self.assertIsNotNone(task.recommendation(boss_hp=70_000_000, boss_full=True))
        task.ui.swipe.assert_not_called()
        self.assertEqual(len(task.recommendation_rows), 2)

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
