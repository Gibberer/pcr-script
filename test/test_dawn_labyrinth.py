"""Synthetic UI regressions; no account images, real strategies or device access."""
import copy
import json
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from pcrscript import Robot
from pcrscript.game_ui import dawn_labyrinth as maze
from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.run_session import RunCancelled
from pcrscript.runtime import run_task_with_config
from pcrscript.tasks import DawnLabyrinth
from pcrscript.tasks.task_dawn_labyrinth import validate_options


def screen(*labels, blue=()):
    image = np.full((540, 960, 3), 245, np.uint8)
    items = []
    for text, x, y in labels:
        items.append(TextBox(text, .999, [[x-25, y-10], [x+25, y-10],
                                         [x+25, y+10], [x-25, y+10]]))
        if text in blue:
            cv.rectangle(image, (x-50, y-24), (x+50, y+24), (230, 155, 25), -1)
    return EventScreen(image, items)


def home(passes=3):
    return screen(('黎明界迷宫', 130, 30), ('出发', 590, 302),
                  ('持有通行证', 555, 337), (f'{passes}/99', 660, 337))


def guild(*extra):
    return screen(('黎明界迷宫', 130, 30), ('请选择要同行的公会。', 480, 88),
                  ('跳过', 912, 65), ('选择', 144, 422), *extra)


def preview(before=3, after=2):
    return screen(('跳过确认', 480, 42), ('通行证持有数', 350, 330),
                  (str(before), 635, 330), ('→', 665, 330), (str(after), 695, 330),
                  ('跳过', 585, 480), ('取消', 370, 480), blue=('跳过',))


def result():
    return screen(('跳过结果', 480, 42), ('获得了以下报酬', 480, 130), ('确认', 480, 480))


def mission_home(passes=0, badge=True):
    value = home(passes)
    value.items.extend(screen(('任务', 874, 257)).items)
    if badge:
        cv.ellipse(value.image, (927, 226), (21, 10), 0, 0, 360, (110, 40, 245), -1)
    return value


def missions(claim=True, selected=True):
    return screen(('任务', 480, 42), ('全部', 190, 88), ('普通', 480, 88), ('公会', 774, 88),
                  ('已超过持有数上限的道具将被送往礼物箱。', 480, 427),
                  ('取消', 367, 475), ('全部收取', 592, 475),
                  blue=tuple((['全部'] if selected else [])+(['全部收取'] if claim else [])))


def mission_receipt():
    return screen(('收取报酬', 480, 42), ('获得了以下报酬。', 480, 80),
                  ('合成奖励', 450, 210), ('关闭', 480, 480))


def catalogue(before=3, quantity=1, selected=True, after=None):
    after = before-quantity if selected and after is None else after
    value = screen(('可跳过的公会一览', 480, 42), ('美食殿堂', 92, 152),
                   ('黎明界迷宫', 115, 179), ('解除所有勾选', 850, 110),
                   ('通行证', 85, 430), (str(before), 250, 432),
                   (str(after) if after is not None else '-', 353, 432),
                   ('通行证使用数量', 540, 420), (str(quantity), 766, 414),
                   ('MIN', 642, 414), ('MAX', 884, 414),
                   ('取消', 584, 477), ('一键扫荡', 810, 476), blue=('一键扫荡',))
    if selected:
        cv.rectangle(value.image, (832, 148), (868, 179), (230, 155, 25), -1)
    return value


def bulk(before=3, cost=1, row_quantity=None, total=None, guild_name='美食殿堂'):
    return screen(('键扫荡确认', 480, 42),
                  ('即将消耗通行证，对以下公会及难度执行跳过操作。确定吗？', 480, 80),
                  (guild_name, 92, 119), ('黎明界迷宫', 115, 146),
                  (str(cost if row_quantity is None else row_quantity), 880, 144),
                  ('合计扫荡次数', 840, 365), ('消耗通行证', 108, 405),
                  ('通行证', 300, 405), (str(cost), 254, 405), (str(before), 465, 405),
                  (str(cost if total is None else total), 884, 398),
                  ('取消', 370, 480), ('挑战', 588, 480), blue=('挑战',))


class LabyrinthRecognitionTests(TestCase):
    def test_missions_require_the_maze_popup_tabs_and_footer(self):
        self.assertTrue(maze.missions_page(missions()))
        self.assertFalse(maze.missions_page(home()))
        self.assertFalse(maze.missions_page(screen(('任务', 100, 30), ('全部收取', 592, 475))))
        value = missions()
        value.items = [item for item in value.items if item.text != '公会']
        self.assertFalse(maze.missions_page(value))

    def test_mission_badge_does_not_depend_on_ocr_of_the_digit(self):
        self.assertTrue(maze.mission_reward_hint(mission_home()))
        self.assertFalse(maze.mission_reward_hint(mission_home(badge=False)))
        self.assertFalse(maze.mission_reward_hint(missions()))

    def test_mission_receipt_requires_title_and_received_items_text(self):
        self.assertTrue(maze.mission_receipt(mission_receipt()))
        self.assertFalse(maze.mission_receipt(screen(('收取报酬', 480, 42), ('关闭', 480, 480))))

    def test_home_counter_including_zero_and_capacity(self):
        for value in (0, 1, 11, 99):
            with self.subTest(value=value):
                self.assertTrue(maze.home(home(value)))
                self.assertEqual(maze.held_passes(home(value)), value)

    def test_missing_conflicting_or_low_confidence_counter_is_unknown(self):
        for labels in [(), (('11/99', 650, 337), ('12/99', 700, 337)),
                       (('100/99', 650, 337),), (('11/98', 650, 337),)]:
            value = screen(('黎明界迷宫', 130, 30), ('持有通行证', 555, 337), *labels)
            self.assertIsNone(maze.held_passes(value))
        value = home()
        value.items[-1].score = .94
        self.assertIsNone(maze.held_passes(value))
        value = home()
        value.items[-2].score = .94
        self.assertIsNone(maze.held_passes(value))

    def test_counter_merged_with_label(self):
        value = screen(('黎明界迷宫', 130, 30), ('持有通行证11/99', 600, 337))
        self.assertEqual(maze.held_passes(value), 11)

    def test_regular_selection_cannot_start_exploration(self):
        self.assertTrue(maze.guild_selection(guild()))
        self.assertFalse(maze.sweep_guild_selection(guild()))
        self.assertFalse(maze.sweep_confirmation(guild()))

    def test_preview_accepts_only_labelled_ordered_balances(self):
        self.assertEqual(maze.pass_preview(preview()), (3, 2))
        merged = screen(('跳过确认', 480, 42), ('持有通行证11→10', 530, 330))
        self.assertEqual(maze.pass_preview(merged), (11, 10))
        ratio = screen(('跳过确认', 480, 42), ('通行证持有数11/99→10/99', 530, 330))
        self.assertEqual(maze.pass_preview(ratio), (11, 10))
        for before, after in [(0, 0), (3, 3), (3, 4), (100, 99), (3, -1)]:
            self.assertIsNone(maze.pass_preview(preview(before, after)))

    def test_preview_ignores_rewards_and_other_currency(self):
        value = screen(('跳过确认', 480, 42), ('迷宫通行证', 350, 140),
                       ('宝石持有数', 350, 330), ('3', 635, 330), ('2', 695, 330))
        self.assertIsNone(maze.pass_preview(value))
        value = preview()
        value.items.extend(screen(('100', 650, 260), ('20', 700, 260)).items)
        self.assertEqual(maze.pass_preview(value), (3, 2))
        value.items.append(screen(('1', 600, 330)).items[0])
        self.assertIsNone(maze.pass_preview(value))

    def test_catalogue_identifies_eligible_guild_and_checkbox(self):
        for checked in (True, False):
            value = catalogue(selected=checked)
            self.assertTrue(maze.sweep_guild_selection(value))
            guilds = maze.catalogue_guilds(value)
            self.assertEqual([g.text for g in guilds], ['美食殿堂'])
            self.assertEqual(maze.catalogue_selected(value, guilds[0]), checked)
        value = catalogue()
        value.items[2].text = '黎明界迷宫说明'
        self.assertEqual(maze.catalogue_guilds(value), [])

    def test_rotated_counter_is_reread_upright_with_capacity_and_confidence(self):
        value = home(9)
        value.items[-1].text = '66/6'
        ui = Mock(read_region=Mock(return_value=screen(('9/99', 660, 337))))
        self.assertEqual(maze.read_held_passes(ui, value), 9)
        ui.read_region.assert_called_once_with(value, (630, 318, 695, 355), classify=False)
        for label in ('9', '66/6', '9/98'):
            ui.read_region.return_value = screen((label, 660, 337))
            self.assertIsNone(maze.read_held_passes(ui, value))
        ui.read_region.return_value = screen(('0/99', 660, 337))
        self.assertEqual(maze.read_held_passes(ui, value), 0)
        ui.read_region.return_value.items[0].score = .94
        self.assertIsNone(maze.read_held_passes(ui, value))

    def test_ambiguous_counter_cannot_be_overridden_by_a_local_read(self):
        value = home(9)
        value.items.extend(screen(('8/99', 700, 337)).items)
        ui = Mock(read_region=Mock(return_value=screen(('9/99', 660, 337))))
        self.assertIsNone(maze.read_held_passes(ui, value))
        ui.read_region.assert_not_called()

    def test_region_read_preserves_classification_for_other_callers(self):
        from pcrscript.game_ui.screen import EventUI
        with TemporaryDirectory() as folder:
            ui = EventUI(Mock(), folder)
            ui._ocr = Mock(return_value=Mock(txts=['9/99'], scores=[.999],
                                            boxes=[[[30, 15], [150, 15], [150, 75], [30, 75]]]))
            read = ui.read_region(home(9), (630, 318, 695, 355), classify=False)
            self.assertEqual(read.items[0].text, '9/99')
            self.assertEqual(read.items[0].center, (660, 333))
            self.assertFalse(ui._ocr.call_args.kwargs['use_cls'])
            ui.read_region(home(9), (630, 318, 695, 355))
            self.assertTrue(ui._ocr.call_args.kwargs['use_cls'])

    def test_catalogue_preview_requires_single_guild_cost_and_explicit_zero(self):
        ui = Mock(number=lambda value, roi: value.number(roi))
        self.assertEqual(maze.catalogue_preview(ui, catalogue(3, 3)), (3, 0))
        self.assertEqual(maze.catalogue_preview(ui, catalogue(3, 1)), (3, 2))
        # Two selected guilds would cost twice the per-guild quantity.
        for value in (catalogue(6, 2, after=2), catalogue(selected=False),
                      catalogue(3, 4), catalogue(0, 1)):
            self.assertIsNone(maze.catalogue_preview(ui, value))
        value = catalogue(1, 1)
        value.items = [item for item in value.items if item.center != (353, 432)]
        self.assertIsNone(maze.catalogue_preview(ui, value))

    def test_bulk_confirmation_requires_matching_cost_row_and_total(self):
        ui = Mock(number=lambda value, roi: value.number(roi))
        self.assertTrue(maze.bulk_confirmation(bulk()))
        self.assertEqual(maze.bulk_preview(ui, bulk(3, 3)), (3, 0))
        self.assertEqual(maze.bulk_preview(ui, bulk(3, 1)), (3, 2))
        for value in (bulk(3, 0), bulk(3, 4), bulk(row_quantity=2), bulk(total=2)):
            self.assertIsNone(maze.bulk_preview(ui, value))
        value = bulk()
        value.items.extend(screen(('另一公会', 92, 219), ('黎明界迷宫', 115, 246)).items)
        self.assertIsNone(maze.bulk_preview(ui, value))

    def test_preview_missing_arrow_requires_two_separate_number_boxes(self):
        value = preview()
        value.items = [item for item in value.items if item.text != '→']
        self.assertEqual(maze.pass_preview(value), (3, 2))
        value.items[-3].score = .94  # The before balance.
        self.assertIsNone(maze.pass_preview(value))


class LabyrinthTaskTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        self.robot.configure({'DawnLabyrinth': {'output': str(self.folder)}})
        self.task = DawnLabyrinth(self.robot)
        self.task.ui = Mock(output=self.folder, last=None)
        self.task.ui.save.return_value = self.folder / 'synthetic.png'
        self.sleep = patch('pcrscript.tasks.task_dawn_labyrinth.time.sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.temp.cleanup()

    def frames(self, values):
        """Only replace observation/input; the production state machine executes."""
        iterator = iter(values)
        last = values[-1]
        def capture():
            value = next(iterator, last)
            self.task.ui.last = value
            return value
        self.task.ui.capture.side_effect = capture

    def clicks(self):
        return [getattr(call.args[0], 'text', call.args[0]) for call in self.task.ui.click.call_args_list]

    def test_zero_passes_claims_missions_with_receipt_and_empty_home_badge(self):
        self.frames([mission_home(), missions(), missions(), mission_receipt(),
                     missions(claim=False), mission_home(badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual((report['spent'], report['missions']['batches']), (0, 1))
        self.assertEqual(report['missions']['status'], 'complete')
        self.assertNotIn('pending_mission_claim', report)
        self.assertEqual(self.clicks(), ['任务', '全部', '全部收取', '关闭', '取消'])

    def test_sweep_claims_missions_after_resource_settlement(self):
        self.frames([home(1), guild(), preview(1, 0), result(), mission_home(),
                     missions(), missions(), mission_receipt(), missions(claim=False),
                     mission_home(badge=False)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent'], report['missions']['batches']), ('complete', 1, 1))
        self.assertLess(self.clicks().index('确认'), self.clicks().index('任务'))
        self.assertEqual(report['remaining_passes'], 0)

    def test_budget_limit_still_claims_missions_after_the_verified_sweep(self):
        self.task.options['max_passes'] = 1
        self.frames([home(3), guild(), preview(3, 2), result(), mission_home(2),
                     missions(), missions(), mission_receipt(), missions(claim=False),
                     mission_home(2, badge=False)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent'], report['missions']['batches']), ('partial', 1, 1))
        self.assertEqual(report['remaining_passes'], 2)

    def test_unconfirmed_sweep_never_opens_missions(self):
        self.frames([home(1), guild(), preview(1, 0), mission_home()])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertNotIn('任务', self.clicks())
        self.assertNotIn('全部收取', self.clicks())

    def test_missions_follow_up_rewards_require_a_new_receipt_each_time(self):
        self.frames([mission_home(), missions(), missions(), mission_receipt(),
                     missions(), mission_receipt(), missions(claim=False), mission_home(badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['missions']['batches'], 2)
        self.assertEqual(len(report['missions']['receipts']), 2)
        self.assertEqual(self.clicks().count('全部收取'), 2)

    def test_mission_receipt_timeout_preserves_pending_and_never_repeats_claim(self):
        self.frames([mission_home(), missions(), missions(), missions()])
        ticks = count(0, 10)
        with patch('pcrscript.tasks.task_dawn_labyrinth.time.monotonic', side_effect=lambda: next(ticks)):
            report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(self.clicks().count('全部收取'), 1)
        self.assertIn('pending_mission_claim', report)
        self.assertEqual(report['missions']['batches'], 0)
        self.assertEqual(report['missions']['status'], 'partial')

    def test_mission_claim_is_persisted_before_dispatch_and_cancellation(self):
        self.frames([mission_home(), missions(), missions()])
        def click(button):
            if getattr(button, 'text', '') == '全部收取':
                saved = json.loads((self.folder/'report.json').read_text(encoding='utf-8'))
                self.assertIn('pending_mission_claim', saved)
                raise RunCancelled('synthetic claim cancellation')
        self.task.ui.click.side_effect = click
        with self.assertRaises(RunCancelled):
            self.task.run()
        self.assertIn('pending_mission_claim', self.task.report)
        self.assertEqual(self.task.report['status'], 'cancelled')

    def test_mission_page_without_claimable_rewards_must_clear_the_home_badge(self):
        self.frames([mission_home(), missions(claim=False), missions(claim=False), mission_home()])
        report = self.task.run()
        self.assertNotEqual(report['status'], 'complete')
        self.assertNotIn('全部收取', self.clicks())

    def test_mission_rewards_that_add_passes_update_actual_balance_without_expanding_budget(self):
        self.frames([mission_home(), missions(), missions(), mission_receipt(),
                     missions(claim=False), mission_home(1, badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual((report['spent'], report['remaining_passes']), (0, 1))
        self.assertNotIn('出发', self.clicks())
        self.assertIn('任务奖励增加', report['pending'][0])

    def test_entry_closes_existing_mission_page_before_verifying_rewards(self):
        self.frames([missions(), mission_home(), missions(), missions(), mission_receipt(),
                     missions(claim=False), mission_home(badge=False)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks()[0], '取消')
        self.assertEqual(self.clicks().count('任务'), 1)

    def test_entry_reconciles_an_existing_receipt_without_repeating_the_claim(self):
        self.frames([mission_receipt(), missions(claim=False), mission_home(badge=False)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(len(report['resumed_mission_receipts']), 1)
        self.assertEqual(self.clicks(), ['关闭', '取消'])
        self.assertEqual(report['missions']['batches'], 0)

    def test_reward_collection_cannot_leave_a_pending_battle_or_spend(self):
        for key in ('pending_spend', 'pending_battle'):
            with self.subTest(key=key):
                self.task.report[key] = dict(unconfirmed=True)
                with self.assertRaises(EventUIError) as error:
                    self.task.collect_mission_rewards(mission_home())
                self.assertIn('未领取任务奖励', str(error.exception))
                self.task.ui.click.assert_not_called()
                self.task.report.pop(key)

    def test_full_flow_enters_from_adventure_and_consumes_all_passes(self):
        self.frames([screen(('冒险', 535, 515)),
                     screen(('冒险', 80, 30), ('黎明界迷宫', 868, 434)), home(2),
                     guild(), preview(2, 1), result(), home(1),
                     guild(), preview(1, 0), result(), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual((report['initial_passes'], report['remaining_passes'], report['spent'], report['sweeps']),
                         (2, 0, 2, 2))
        self.assertEqual(len(report['history']), 2)
        self.assertNotIn('pending_spend', report)
        self.assertNotIn('选择', self.clicks())
        self.assertEqual(self.clicks().count('跳过'), 4)  # Entry and confirmation, once each.

    def test_zero_passes_never_opens_departure(self):
        self.frames([home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.task.ui.click.assert_not_called()

    def test_unavailable_entry(self):
        self.frames([screen(('冒险', 80, 30))])
        self.assertEqual(self.task.run()['status'], 'unavailable')
        self.task.ui.click.assert_not_called()

    def test_locked_sweep_prompts_first_clear_without_spending(self):
        self.frames([home(), guild(), guild(('通关1次难度1后可解锁。', 760, 130))])
        report = self.task.run()
        self.assertEqual(report['status'], 'blocked')
        self.assertIn('dawn_labyrinth_first_clear', report['pending'][0])
        self.assertEqual(report['spent'], 0)
        self.assertNotIn('pending_spend', report)
        self.assertEqual(self.clicks(), ['出发', '跳过'])

    def test_running_exploration_is_not_withdrawn_or_reset(self):
        value = home()
        value.items[1].text = '继续探索'
        self.frames([value])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.task.ui.click.assert_not_called()

    def test_unknown_balance_is_never_zero(self):
        value = home()
        value.items.pop()
        self.frames([value])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.assertIsNone(self.task.report['remaining_passes'])
        self.task.ui.click.assert_not_called()

    def test_preview_must_match_current_balance(self):
        self.frames([home(3), guild(), preview(4, 3)])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.assertEqual(self.clicks(), ['出发', '跳过'])

    def test_preview_must_not_exceed_budget(self):
        self.task.options['max_passes'] = 1
        self.frames([home(3), guild(), preview(3, 1)])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.assertEqual(self.task.report['spent'], 0)
        self.assertEqual(self.clicks(), ['出发', '跳过'])

    def test_disabled_confirmation_is_not_clicked(self):
        value = preview()
        value.image[:] = 150
        self.frames([home(3), guild(), value])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.assertEqual(self.clicks(), ['出发', '跳过'])

    def test_purchase_or_reset_confirmation_is_rejected(self):
        for label in ('购买通行证', '消耗宝石回复', '重置迷宫进度'):
            with self.subTest(label=label):
                value = preview()
                value.items.append(screen((label, 480, 250)).items[0])
                self.task.ui.click.reset_mock()
                self.frames([home(3), guild(), value])
                self.assertEqual(self.task.run()['status'], 'blocked')
                self.assertEqual(self.clicks(), ['出发', '跳过'])

    def test_limit_leaves_remaining_passes_with_partial_report(self):
        self.task.options['max_passes'] = 1
        self.frames([home(3), guild(), preview(), result(), home(2)])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual((report['spent'], report['remaining_passes']), (1, 2))
        self.assertIn('消费上限', report['pending'][0])

    def test_multi_pass_preview_uses_exact_cost(self):
        self.frames([home(3), guild(), preview(3, 0), result(), home(0)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent'], report['sweeps']), ('complete', 3, 1))

    def test_stale_balance_waits_then_reconciles_without_second_confirmation(self):
        self.frames([home(1), guild(), preview(1, 0), result(), home(1), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks().count('跳过'), 2)

    def test_no_receipt_or_wrong_balance_retains_pending_spend(self):
        for after, receipt_seen in [(2, False), (1, True)]:
            with self.subTest(after=after):
                self.task.ui.click.reset_mock()
                frames = [home(3), guild(), preview()]
                if receipt_seen:
                    frames.append(result())
                self.frames(frames + [home(after)])
                report = self.task.run()
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(report['spent'], 0)
                self.assertEqual(report['pending_spend']['before'], 3)
                self.assertEqual(report['remaining_passes'], after)
                self.assertEqual(self.clicks().count('跳过'), 2)

    def test_unchanged_balance_timeout_never_repeats_consumption(self):
        self.frames([home(3), guild(), preview(), result(), home(3)])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertIn('pending_spend', report)
        self.assertEqual(self.clicks().count('跳过'), 2)

    def test_capacity_error_stops_without_dismantling(self):
        self.frames([home(3), guild(), preview(), screen(('持有上限', 480, 200), ('一键分解', 580, 480))])
        self.assertEqual(self.task.run()['status'], 'partial')
        self.assertNotIn('一键分解', self.clicks())
        self.assertIn('pending_spend', self.task.report)

    def test_cancellation_after_confirmation_persists_spend_and_propagates(self):
        self.frames([home(3), guild(), preview()])
        def click(button):
            if getattr(button, 'center', (0, 0))[1] == 480:
                saved = json.loads((self.folder / 'report.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['pending_spend']['cost'], 1)
                raise RunCancelled('synthetic stop after dispatch')
        self.task.ui.click.side_effect = click
        with self.assertRaises(RunCancelled):
            self.task.run()
        saved = json.loads((self.folder / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['pending_spend']['before'], 3)
        self.assertEqual(saved['status'], 'cancelled')
        self.assertEqual(self.clicks().count('跳过'), 2)

    def test_separate_sweep_selection_uses_only_enabled_sweep_control(self):
        choices = screen(('黎明界迷宫', 130, 30), ('请选择跳过的公会', 480, 88),
                         ('跳过', 144, 422), ('选择', 413, 422), blue=('跳过', '选择'))
        self.frames([home(1), guild(), choices, preview(1, 0), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertNotIn('选择', self.clicks())

    def test_invalid_options_fail_before_device_connection(self):
        for options in (None, [], {'max_passes': 0}, {'max_passes': 100}, {'max_passes': True},
                        {'timeout': -1}, {'timeout': '600'}, {'timeout': 3601}):
            with self.subTest(options=options), patch('pcrscript.runtime.robot_from_config') as connect:
                with self.assertRaises(ValueError):
                    run_task_with_config({'DawnLabyrinth': options}, 'dawn_labyrinth')
                connect.assert_not_called()

    def test_choice_requires_explicit_sweep_instruction(self):
        choices = screen(('黎明界迷宫', 130, 30), ('请选择要跳过的公会', 480, 88),
                         ('选择', 144, 422), blue=('选择',))
        self.frames([home(1), guild(), choices, preview(1, 0), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks().count('选择'), 1)

    def test_other_currency_on_ticket_row_cannot_form_a_preview(self):
        value = preview()
        value.items.append(screen(('宝石持有数', 580, 330)).items[0])
        self.assertIsNone(maze.pass_preview(value))

    def test_confirmation_named_confirm_still_requires_ticket_preview(self):
        value = preview(1, 0)
        value.items[-2].text = '确认'
        cv.rectangle(value.image, (535, 456), (635, 504), (230, 155, 25), -1)
        self.frames([home(1), guild(), value, result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks().count('跳过'), 1)

    def test_task_deadline_blocks_before_input(self):
        self.task.deadline = 0
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.task.ui.click.assert_not_called()
        self.task.ui.capture.assert_not_called()

    def test_receipt_returning_to_guild_page_reads_home_balance(self):
        self.frames([home(1), guild(), preview(1, 0), result(), guild(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertIn((30, 30), self.clicks())

    def test_catalogue_single_pass_clears_prior_selection_then_returns_to_balance(self):
        self.task.options['max_passes'] = 1
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        self.frames([home(3), guild(), catalogue(), catalogue(selected=False),
                     catalogue(), catalogue(), result(), catalogue(2), guild(), home(2)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent'], report['remaining_passes']), ('partial', 1, 2))
        self.assertEqual(self.clicks().count('一键扫荡'), 1)
        self.assertLess(self.clicks().index('解除所有勾选'), self.clicks().index((849, 165)))
        self.assertIn('MIN', self.clicks())
        self.assertIn('取消', self.clicks())
        self.assertNotIn('pending_spend', report)

    def test_catalogue_max_consumes_all_with_receipt_and_actual_zero(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        self.frames([home(3), guild(), catalogue(), catalogue(selected=False),
                     catalogue(), catalogue(3, 3), result(), home(0)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent'], report['sweeps']), ('complete', 3, 1))
        self.assertIn('MAX', self.clicks())
        self.assertEqual(self.clicks().count('一键扫荡'), 1)

    def test_catalogue_quantity_is_reduced_to_budget_before_confirming(self):
        self.task.options['max_passes'] = 2
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        self.frames([home(3), guild(), catalogue(), catalogue(selected=False),
                     catalogue(), catalogue(3, 3), catalogue(), catalogue(3, 2),
                     result(), home(1)])
        report = self.task.run()
        self.assertEqual((report['spent'], report['remaining_passes']), (2, 1))
        self.assertIn('MAX', self.clicks())
        self.assertIn('MIN', self.clicks())
        self.assertEqual(self.clicks().count((832, 414)), 1)

    def test_catalogue_secondary_confirmation_is_saved_and_clicked_only_once(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        self.frames([home(1), guild(), catalogue(1), catalogue(1, selected=False),
                     catalogue(1), catalogue(1), preview(1, 0), preview(1, 0), result(), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(self.clicks().count('一键扫荡'), 1)
        self.assertEqual(self.clicks().count('跳过'), 2)  # Entry and one final confirmation.

    def test_catalogue_secondary_confirmation_mismatch_never_dispatches(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        self.frames([home(3), guild(), catalogue(), catalogue(selected=False),
                     catalogue(), catalogue(3, 3), preview(3, 1)])
        report = self.task.run()
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['spent'], 0)
        self.assertIn('pending_spend', report)
        self.assertEqual(self.clicks().count('跳过'), 1)

    def test_bulk_confirmation_is_reconciled_with_catalogue_and_not_repeated(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        self.frames([home(3), guild(), catalogue(), catalogue(selected=False),
                     catalogue(), catalogue(3, 3), bulk(3, 3), bulk(3, 3), result(), home(0)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent']), ('complete', 3))
        self.assertEqual(self.clicks().count('挑战'), 1)
        self.assertEqual(self.clicks().count('一键扫荡'), 1)

    def test_bulk_changed_guild_or_cost_is_not_confirmed(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        for value in (bulk(3, 2), bulk(3, 3, guild_name='另一公会')):
            with self.subTest(text=value.text()):
                self.task.ui.click.reset_mock()
                self.frames([home(3), guild(), catalogue(), catalogue(selected=False),
                             catalogue(), catalogue(3, 3), value])
                report = self.task.run()
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(report['spent'], 0)
                self.assertNotIn('挑战', self.clicks())

    def test_entry_cancels_known_bulk_confirmation_before_fresh_balance(self):
        self.frames([bulk(), catalogue(), guild(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks(), ['取消', '取消', (30, 30)])

    def test_bulk_dispatch_persists_verified_cost_before_click(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        def click(button):
            if getattr(button, 'text', '') == '挑战':
                saved = json.loads((self.folder / 'report.json').read_text(encoding='utf-8'))
                self.assertEqual(saved['pending_spend']['cost'], 1)
                self.assertNotIn('catalogue', saved['pending_spend'])
                raise RunCancelled('synthetic dispatch cancellation')
        self.task.ui.click.side_effect = click
        self.frames([home(1), guild(), catalogue(1), catalogue(1, selected=False),
                     catalogue(1), catalogue(1), bulk(1, 1)])
        with self.assertRaises(RunCancelled):
            self.task.run()
        self.assertEqual(self.clicks().count('挑战'), 1)

    def test_entry_from_catalogue_closes_it_before_reading_zero_balance(self):
        self.frames([catalogue(), guild(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks(), ['取消', (30, 30)])

    def test_receipt_over_home_is_closed_before_balance_or_next_sweep(self):
        overlay = home(0)
        overlay.items.extend(screen(('报酬确认', 480, 42), ('关闭', 480, 480)).items)
        self.frames([home(1), guild(), preview(1, 0), result(), overlay, home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertIn('关闭', self.clicks())
        self.assertEqual(self.clicks().count('出发'), 1)

    def test_entry_settles_known_reward_overlay_before_zero_pass_noop(self):
        overlay = home(0)
        overlay.items.extend(screen(('报酬确认', 480, 42), ('关闭', 480, 480)).items)
        self.frames([overlay, home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.clicks(), ['关闭'])

    def test_locked_guild_card_does_not_block_an_eligible_sweep(self):
        choices = screen(('黎明界迷宫', 130, 30), ('请选择要跳过的公会', 480, 88),
                         ('跳过', 144, 422), ('未通关', 680, 300), blue=('跳过',))
        self.assertIsNone(maze.locked_notice(choices))
        self.frames([home(1), guild(), choices, preview(1, 0), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')

    def test_options_do_not_mutate_configuration(self):
        options = {'max_passes': 2}
        original = copy.deepcopy(options)
        self.assertEqual(validate_options(options)['timeout'], 600)
        self.assertEqual(options, original)


if __name__ == '__main__':
    main()
