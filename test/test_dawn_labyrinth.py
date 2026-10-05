"""Synthetic UI regressions; no account images, real strategies or device access."""
import json
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import Mock, patch

import cv2 as cv

from pcrscript import Robot
from ui_fixtures import screen, replay_ui, TaskReplayMixin
from dawn_labyrinth_fixtures import (home, guild, preview, separate_guilds, named_preview, result,
                                     mission_home, missions, mission_receipt, catalogue, bulk)
from pcrscript.game_ui import dawn_labyrinth as maze
from pcrscript.game_ui.screen import EventUIError
from pcrscript.run_session import RunCancelled
from pcrscript.runtime import run_task_with_config
from pcrscript.tasks import DawnLabyrinth


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


class LabyrinthTaskTests(TaskReplayMixin, TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        self.robot.configure({'DawnLabyrinth': {'output': str(self.folder),
                                               'state_dir': str(self.folder / 'state'),
                                               'account_key': 'synthetic-account'}})
        self.task = DawnLabyrinth(self.robot)
        self.task.ui = replay_ui(self.folder)
        self.sleep = patch('pcrscript.tasks.task_dawn_labyrinth.time.sleep')
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.temp.cleanup()

    def test_entry_leaves_known_subjugation_detail_before_opening_maze(self):
        self.frames([screen(('BOSS详情', 109, 52), ('模拟战', 748, 109), ('实战', 866, 109),
                            ('取消', 668, 469), ('挑战', 840, 469)),
                     screen(('深渊讨伐战', 135, 30), ('冒险', 537, 526)),
                     screen(('冒险', 100, 30), ('黎明界迷宫', 800, 365)), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete', report)
        self.assertEqual(self.clicks(), ['取消', '冒险', '黎明界迷宫'])
        self.assertEqual(report['spent'], 0)

    def test_subjugation_confirmation_overlay_is_preserved(self):
        self.frames([screen(('BOSS详情', 109, 52), ('模拟战', 748, 109), ('实战', 866, 109),
                            ('取消', 668, 469), ('挑战', 840, 469),
                            ('扫荡券确认', 480, 150), ('确认', 588, 373))])
        self.assertEqual(self.task.run()['status'], 'blocked')
        self.task.ui.click.assert_not_called()

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
                     missions(), mission_home(), missions(), missions(),
                     mission_receipt(), missions(claim=False), mission_home(badge=False)])
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

    def test_mission_receipt_is_persisted_before_closing_and_restart(self):
        self.frames([mission_home(), missions(), missions(), mission_receipt()])
        def click(button):
            if getattr(button, 'text', '') == '关闭':
                state = json.loads(self.task.state_path.read_text(encoding='utf-8'))
                self.assertIn('receipt', state['pending_mission_claim'])
                raise RunCancelled('synthetic receipt close cancellation')
        self.task.ui.click.side_effect = click
        with self.assertRaises(RunCancelled):
            self.task.run()
        report = self.restart([mission_home(badge=False)])
        self.assertEqual(report['status'], 'complete', report)
        self.assertNotIn('pending_mission_claim', report)
        self.assertNotIn('全部收取', self.clicks())

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
                self.robot.task_config['DawnLabyrinth']['account_key'] = f'synthetic-{after}'
                self.task = DawnLabyrinth(self.robot)
                self.task.ui = replay_ui(self.folder)
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

    def test_submitted_sweep_without_result_does_not_reopen_in_the_same_run(self):
        self.frames([home(1), guild(), preview(1, 0), home(1)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent']), ('partial', 0), report)
        self.assertIs(report['pending_spend']['submitted'], True)
        self.assertNotIn('result_evidence', report['pending_spend'])
        self.assertEqual(self.clicks().count('出发'), 1)
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
                self.assertIs(saved['pending_spend']['submitted'], True)
                self.assertIs(saved['pending_spend']['submission_tracked'], True)
                raise RunCancelled('synthetic stop after dispatch')
        self.task.ui.click.side_effect = click
        with self.assertRaises(RunCancelled):
            self.task.run()
        saved = json.loads((self.folder / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['pending_spend']['before'], 3)
        self.assertEqual(saved['status'], 'cancelled')
        self.assertEqual(self.clicks().count('跳过'), 2)

    def restart(self, frames):
        self.task = DawnLabyrinth(self.robot)
        self.task.ui = replay_ui(self.folder)
        self.frames(frames)
        return self.task.run()

    def test_unsubmitted_sweep_recovers_from_home_without_counting_cancelled_cost(self):
        for mode in ('direct', 'catalogue', 'bulk'):
            with self.subTest(mode=mode):
                self.robot.task_config['DawnLabyrinth']['account_key'] = 'synthetic-'+mode
                self.task = DawnLabyrinth(self.robot)
                self.task.ui = replay_ui(self.folder)
                self.task.ui.number.side_effect = lambda s, roi: s.number(roi)
                values = ([home(1), guild(), preview(1, 0)] if mode == 'direct' else
                          [home(1), guild(), catalogue(1), catalogue(1, selected=False),
                           catalogue(1), catalogue(1), bulk(1, 1)])
                self.frames(values)
                save = self.task.save_report
                interrupted = False
                def stop_after_journal():
                    nonlocal interrupted
                    save()
                    pending = self.task.report.get('pending_spend', {})
                    if (not interrupted and pending.get('submitted') is False
                            and (mode == 'catalogue' or not pending.get('catalogue'))):
                        interrupted = True
                        raise RunCancelled('synthetic stop before dispatch phase')
                with patch.object(self.task, 'save_report', side_effect=stop_after_journal):
                    with self.assertRaises(RunCancelled):
                        self.task.run()
                saved = json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_spend']
                self.assertIs(saved['submitted'], False)
                self.assertIs(saved['submission_tracked'], True)
                self.assertEqual(self.clicks().count('挑战'), 0)
                self.assertEqual(self.clicks().count('跳过'), 1)
                report = self.restart([home(1), home(1), home(1), guild(), preview(1, 0), result(), home(0)])
                self.assertEqual((report['status'], report['spent'], report['sweeps']), ('complete', 1, 1), report)
                self.assertEqual(report['history'][0]['outcome'], 'cancelled_unsubmitted_sweep')
                self.assertIn('unsubmitted_balance', report['history'][0])
                self.assertNotIn('pending_spend', report)
                self.assertEqual(self.clicks().count('跳过'), 2)
                self.assertEqual(json.loads(self.task.state_path.read_text(encoding='utf-8')), {})

    def test_sweep_recovers_a_stop_after_submission_journal_before_actual_input(self):
        for mode in ('direct', 'bulk'):
            with self.subTest(mode=mode):
                self.robot.task_config['DawnLabyrinth']['account_key'] = 'synthetic-dispatch-'+mode
                self.task = DawnLabyrinth(self.robot)
                self.task.ui = replay_ui(self.folder)
                self.task.ui.number.side_effect = lambda s, roi: s.number(roi)
                self.frames([home(1), guild(), preview(1, 0)] if mode == 'direct' else
                            [home(1), guild(), catalogue(1), catalogue(1, selected=False),
                             catalogue(1), catalogue(1), bulk(1, 1)])
                save = self.task.save_report
                interrupted = False
                def stop_after_journal():
                    nonlocal interrupted
                    save()
                    if not interrupted and self.task.report.get('pending_spend', {}).get('submitted') is True:
                        interrupted = True
                        raise RunCancelled('synthetic stop after dispatch journal, before input')
                with patch.object(self.task, 'save_report', side_effect=stop_after_journal):
                    with self.assertRaises(RunCancelled):
                        self.task.run()
                saved = json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_spend']
                self.assertIs(saved['submitted'], True)
                self.assertIs(saved['submission_tracked'], True)
                self.assertEqual(self.clicks().count('挑战'), 0)
                self.assertEqual(self.clicks().count('跳过'), 1)
                report = self.restart([home(1), home(1), home(1), guild(), preview(1, 0), result(), home(0)])
                self.assertEqual((report['status'], report['spent'], report['sweeps']), ('complete', 1, 1), report)
                self.assertEqual(report['history'][0]['outcome'], 'cancelled_unsubmitted_sweep')
                self.assertEqual(report['history'][0]['remaining'], 1)
                self.assertNotIn('pending_spend', report)
                self.assertEqual(self.clicks().count('出发'), 1)
                self.assertEqual(self.clicks().count('跳过'), 2)
                self.assertEqual(json.loads(self.task.state_path.read_text(encoding='utf-8')), {})

    def test_sweep_recovery_needs_three_stable_nonloading_home_balances(self):
        loading = home(1)
        loading.items.extend(screen(('正在进行数据连接', 480, 250)).items)
        unknown = home(1)
        unknown.items[-1].score = .94
        modal = home(1)
        modal.items.extend(screen(('确认', 480, 480)).items)
        cases = [(submitted, changed) for submitted in (False, True)
                 for changed in (home(0), loading, unknown, modal, guild())]
        for index, (submitted, changed) in enumerate(cases):
            with self.subTest(index=index, submitted=submitted):
                self.robot.task_config['DawnLabyrinth']['account_key'] = f'synthetic-changed-{index}'
                self.task = DawnLabyrinth(self.robot)
                self.task.ui = replay_ui(self.folder)
                pending = dict(before=1, after=0, cost=1, submitted=submitted, submission_tracked=True)
                self.task.report['pending_spend'] = pending
                self.task.save_report()
                report = self.restart([home(1), home(1), changed])
                self.assertEqual((report['status'], report['spent']), ('partial', 0), report)
                self.assertEqual(report['pending_spend'], pending)
                self.task.ui.click.assert_not_called()
                self.assertEqual(json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_spend'], pending)

    def test_unchanged_home_balance_cannot_release_legacy_or_invalid_submission_phase(self):
        for index, flags in enumerate((dict(submitted=True),
                                       dict(submitted=False), {},
                                       dict(submitted=False, submission_tracked=False),
                                       dict(submitted=None, submission_tracked=True),
                                       dict(submitted=1, submission_tracked=True))):
            with self.subTest(flags=flags):
                self.robot.task_config['DawnLabyrinth']['account_key'] = f'synthetic-legacy-{index}'
                self.task = DawnLabyrinth(self.robot)
                pending = dict(before=1, after=0, cost=1, **flags)
                self.task.report['pending_spend'] = pending
                self.task.ui = Mock(output=self.folder)
                self.task.save_report()
                for _ in range(2):
                    report = self.restart([home(1)])
                    self.assertEqual((report['status'], report['spent']), ('partial', 0), report)
                    self.assertEqual(report['pending_spend'], pending)
                    self.task.ui.click.assert_not_called()

    def test_result_observation_is_durable_before_close_and_blocks_unchanged_home_recovery(self):
        generic = screen(('报酬确认', 480, 42), ('关闭', 480, 480))
        for index, (resumed, receipt) in enumerate((r, s) for r in (False, True) for s in (result(), generic)):
            with self.subTest(resumed=resumed, receipt=receipt.items[0].text):
                self.robot.task_config['DawnLabyrinth']['account_key'] = f'synthetic-result-proof-{index}'
                self.task = DawnLabyrinth(self.robot)
                self.task.ui = replay_ui(self.folder)
                if resumed:
                    self.task.report['pending_spend'] = dict(before=1, after=0, cost=1,
                                                            submitted=True, submission_tracked=True)
                    self.task.save_report()
                self.frames([receipt] if resumed else [home(1), guild(), preview(1, 0), receipt])
                def stop_before_close(button):
                    if getattr(button, 'text', '') in ('确认', '关闭'):
                        saved = json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_spend']
                        self.assertIn('result_evidence', saved)
                        self.assertEqual('receipt' in saved, receipt.items[0].text == '跳过结果')
                        raise RunCancelled('synthetic stop after result proof, before close')
                self.task.ui.click.side_effect = stop_before_close
                with self.assertRaises(RunCancelled):
                    self.task.run()
                pending = json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_spend']
                for _ in range(2):
                    report = self.restart([home(1), home(1), home(1)])
                    self.assertEqual((report['status'], report['spent']), ('partial', 0), report)
                    self.assertEqual(report['pending_spend'], pending)
                    self.task.ui.click.assert_not_called()
                report = self.restart([result(), home(0)])
                self.assertEqual((report['status'], report['spent'], report['sweeps']), ('complete', 1, 1), report)
                self.assertNotIn('pending_spend', report)
                self.assertNotIn('出发', self.clicks())

    def test_new_run_keeps_unresolved_consumption_and_never_spends_again(self):
        self.frames([home(3), guild(), preview(), home(2)])
        self.assertEqual(self.task.run()['status'], 'partial')
        report = self.restart([home(2), guild(), preview(2, 0), result(), home(0)])
        self.assertEqual(report['status'], 'partial', report)
        self.assertEqual(report['pending_spend']['before'], 3)
        self.assertNotIn('出发', self.clicks())
        self.assertNotIn('任务', self.clicks())

    def test_new_run_recovers_receipt_and_balance_without_new_consumption(self):
        self.frames([home(3), guild(), preview(3, 0), home(0)])
        self.assertEqual(self.task.run()['status'], 'partial')
        report = self.restart([result(), home(0)])
        self.assertEqual(report['status'], 'complete', report)
        self.assertNotIn('pending_spend', report)
        self.assertEqual(report['history'][0]['outcome'], 'recovered_sweep')
        self.assertNotIn('出发', self.clicks())

    def test_new_run_does_not_repeat_an_unconfirmed_mission_claim(self):
        # Legacy records contain no task proof; they cannot authorize replay.
        self.task.report['pending_mission_claim']=dict(preview='synthetic.png')
        self.task.save_report()
        report = self.restart([mission_home(), missions(), missions(), mission_receipt(),
                               missions(claim=False), mission_home(badge=False)])
        self.assertEqual(report['status'], 'partial', report)
        self.assertIn('pending_mission_claim', report)
        self.assertNotIn('全部收取', self.clicks())

    def interrupted_mission_claim(self):
        ready=missions(title='完成合成迷宫任务')
        self.frames([mission_home(),ready,ready])
        def click(button):
            if getattr(button,'text','')=='全部收取':
                raise RunCancelled('synthetic interruption before delivery')
        self.task.ui.click.side_effect=click
        with self.assertRaises(RunCancelled):
            self.task.run()
        return ready

    def test_claim_interrupted_before_delivery_recovers_stable_unchanged_task_page(self):
        ready=self.interrupted_mission_claim()
        saved=json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_mission_claim']
        self.assertEqual(saved['missions_view'],maze.mission_claim_snapshot(ready))
        self.assertEqual(saved['passes_before'],0)
        report=self.restart([mission_home(),ready,ready,ready,ready,mission_receipt(),
                             missions(claim=False),mission_home(badge=False)])
        self.assertEqual(report['status'],'complete',report)
        self.assertEqual(self.clicks().count('全部收取'),1)
        self.assertEqual(report['history'][0]['outcome'],'recovered_unclaimed_missions')
        self.assertNotIn('pending_mission_claim',report)
        self.assertEqual(json.loads(self.task.state_path.read_text(encoding='utf-8')), {})

    def test_claim_recovery_requires_original_content_and_unchanged_pass_balance(self):
        ready=self.interrupted_mission_claim()
        for balance,view in ((1,ready),(0,missions(title='另一合成迷宫任务'))):
            with self.subTest(balance=balance,view=view.text()):
                report=self.restart([mission_home(balance),view,view])
                self.assertEqual(report['status'],'partial',report)
                self.assertIn('pending_mission_claim',report)
                self.assertNotIn('全部收取',self.clicks())
                self.assertNotIn('出发',self.clicks())

    def test_claim_recovery_preserves_pending_when_fresh_page_is_loading_or_changes(self):
        ready=self.interrupted_mission_claim()
        loading=missions(title='完成合成迷宫任务')
        loading.items.extend(screen(('正在进行数据连接',480,300)).items)
        for fresh in (loading,missions(title='不同的合成任务'),missions(claim=False)):
            with self.subTest(view=fresh.text()):
                report=self.restart([mission_home(),ready,ready,fresh])
                self.assertEqual(report['status'],'partial',report)
                self.assertIn('pending_mission_claim',report)
                self.assertNotIn('全部收取',self.clicks())

    def test_claim_snapshot_requires_confident_task_content_and_enabled_claim_controls(self):
        ready=missions(title='完成合成迷宫任务')
        self.assertIsNotNone(maze.mission_claim_snapshot(ready))
        self.assertIsNone(maze.mission_claim_snapshot(missions(title=None)))
        self.assertIsNone(maze.mission_claim_snapshot(missions(claim=False,title='完成合成迷宫任务')))
        ready.items[-3].score=.94
        self.assertIsNone(maze.mission_claim_snapshot(ready))

    def test_missing_or_low_confidence_task_snapshot_blocks_before_journal_and_claim(self):
        missing=missions(title=None)
        low=missions();low.items[-3].score=.94
        for view in (missing,low):
            with self.subTest(view=view.text()):
                report=self.restart([mission_home(),view,view])
                self.assertEqual(report['status'],'blocked',report)
                self.assertNotIn('pending_mission_claim',report)
                self.assertNotIn('全部收取',self.clicks())
                self.assertEqual(json.loads(self.task.state_path.read_text(encoding='utf-8')), {})

    def test_later_claim_interruption_uses_balance_observed_after_prior_reward(self):
        first=missions(title='完成合成迷宫任务1')
        second=missions(title='完成合成迷宫任务2')
        self.frames([mission_home(),first,first,mission_receipt(),second,
                     mission_home(1),second,second])
        claims=0
        def click(button):
            nonlocal claims
            if getattr(button,'text','')=='全部收取':
                claims+=1
                if claims==2:raise RunCancelled('synthetic later-claim interruption')
        self.task.ui.click.side_effect=click
        with self.assertRaises(RunCancelled):
            self.task.run()
        saved=json.loads(self.task.state_path.read_text(encoding='utf-8'))['pending_mission_claim']
        self.assertEqual(saved['passes_before'],1)
        self.assertEqual(saved['missions_view'],maze.mission_claim_snapshot(second))
        report=self.restart([mission_home(1),second,second,second,second,mission_receipt(),
            missions(claim=False),mission_home(1,badge=False),guild(),preview(1,0),
            result(),mission_home(0,badge=False)])
        self.assertEqual(report['status'],'complete',report)
        self.assertEqual(report['history'][0]['outcome'],'recovered_unclaimed_missions')
        self.assertEqual(self.clicks().count('全部收取'),1)
        self.assertEqual(report['spent'],1)

    def test_later_claim_rechecks_original_task_after_observing_the_balance(self):
        first=missions(title='完成合成迷宫任务1')
        second=missions(title='完成合成迷宫任务2')
        changed=missions(title='不同的合成任务')
        self.frames([mission_home(),first,first,mission_receipt(),second,
                     mission_home(1),changed,changed])
        report=self.task.run()
        self.assertEqual(report['status'],'partial',report)
        self.assertEqual(self.clicks().count('全部收取'),1)
        self.assertNotIn('pending_mission_claim',report)
        self.assertNotIn('出发',self.clicks())

    def test_new_run_uses_a_saved_receipt_and_counts_it_against_the_budget(self):
        self.frames([home(3), guild(), preview(), result(), home(1)])
        self.assertEqual(self.task.run()['status'], 'partial')
        self.robot.task_config['DawnLabyrinth']['max_passes'] = 1
        report = self.restart([home(2)])
        self.assertEqual((report['status'], report['spent'], report['remaining_passes']), ('partial', 1, 2))
        self.assertNotIn('pending_spend', report)
        self.assertNotIn('出发', self.clicks())

    def test_new_run_cancels_a_matching_unsubmitted_confirmation_before_retry(self):
        self.frames([home(1), guild(), preview(1, 0)])
        self.task.ui.click.side_effect = lambda button: (
            (_ for _ in ()).throw(RunCancelled('synthetic stop'))
            if getattr(button, 'center', (0, 0))[1] == 480 else None)
        with self.assertRaises(RunCancelled):
            self.task.run()
        self.robot.task_config['DawnLabyrinth']['max_passes'] = 1
        report = self.restart([preview(1, 0), home(1), guild(), preview(1, 0), result(), home(0)])
        self.assertEqual(report['status'], 'complete', report)
        self.assertEqual(report['history'][0]['outcome'], 'cancelled_sweep')
        self.assertEqual(report['spent'], 1)
        self.assertEqual(self.clicks()[0], '取消')

    def test_new_run_does_not_use_an_unrelated_reward_receipt_as_sweep_proof(self):
        self.frames([home(1), guild(), preview(1, 0), home(0)])
        self.assertEqual(self.task.run()['status'], 'partial')
        report = self.restart([screen(('报酬确认', 480, 42), ('关闭', 480, 480)), home(0)])
        self.assertEqual(report['status'], 'partial', report)
        self.assertIn('pending_spend', report)
        self.assertNotIn('出发', self.clicks())

    def test_new_run_recovers_pending_claim_from_a_receipt(self):
        self.frames([mission_home(), missions(), missions(), missions()])
        ticks = count(0, 10)
        with patch('pcrscript.tasks.task_dawn_labyrinth.time.monotonic', side_effect=lambda: next(ticks)):
            self.assertEqual(self.task.run()['status'], 'partial')
        report = self.restart([mission_receipt(), missions(claim=False), mission_home(badge=False)])
        self.assertEqual(report['status'], 'complete', report)
        self.assertNotIn('pending_mission_claim', report)
        self.assertNotIn('全部收取', self.clicks())

    def test_new_run_recovers_an_empty_mission_list_before_spending(self):
        self.frames([mission_home(), missions(), missions(), missions()])
        ticks = count(0, 10)
        with patch('pcrscript.tasks.task_dawn_labyrinth.time.monotonic', side_effect=lambda: next(ticks)):
            self.assertEqual(self.task.run()['status'], 'partial')
        report = self.restart([mission_home(badge=False), missions(claim=False), missions(claim=False),
                               mission_home(badge=False)])
        self.assertEqual(report['status'], 'complete', report)
        self.assertEqual(report['history'][0]['outcome'], 'recovered_empty_missions')
        self.assertNotIn('全部收取', self.clicks())

    def test_pending_records_are_isolated_by_account(self):
        self.frames([home(1), guild(), preview(1, 0), home(0)])
        self.assertEqual(self.task.run()['status'], 'partial')
        original = self.task.state_path
        self.robot.task_config['DawnLabyrinth']['account_key'] = 'other-synthetic-account'
        report = self.restart([home(0)])
        self.assertEqual(report['status'], 'complete')
        self.assertIn('pending_spend', json.loads(original.read_text(encoding='utf-8')))

    def test_pending_claim_blocks_new_pass_spending_before_claim_recovery(self):
        self.task.report['pending_mission_claim'] = dict(preview='synthetic.png')
        self.task.save_report()
        report = self.restart([mission_home(2), missions(), missions()])
        self.assertEqual(report['status'], 'partial', report)
        self.assertNotIn('出发', self.clicks())
        self.assertNotIn('全部收取', self.clicks())

    def test_claim_recovery_follow_up_receipts_survive_the_final_mission_check(self):
        self.task.report['pending_mission_claim'] = dict(preview='synthetic.png', receipt='synthetic.png')
        self.task.save_report()
        report = self.restart([mission_home(), missions(), missions(), mission_receipt(),
                               missions(claim=False), mission_home(1, badge=False)])
        self.assertEqual(report['status'], 'partial', report)
        self.assertEqual((report['spent'], report['missions']['batches']), (0, 1))
        self.assertEqual(len(report['missions']['receipts']), 1)
        self.assertNotIn('出发', self.clicks())
        self.assertIn('任务奖励增加了通行证', report['pending'][0])

    def test_malformed_state_fails_before_any_new_game_input(self):
        path = self.task.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        for invalid in ([], {'pending_spend': {}}, {'pending_spend': {'before': 3, 'after': 2, 'cost': 2}}):
            with self.subTest(state=invalid):
                path.write_text(json.dumps(invalid), encoding='utf-8')
                with self.assertRaises(ValueError):
                    DawnLabyrinth(self.robot)
                self.task.ui.click.assert_not_called()

    def test_separate_sweep_selection_uses_only_enabled_sweep_control(self):
        choices = screen(('黎明界迷宫', 130, 30), ('请选择跳过的公会', 480, 88),
                         ('美食殿堂', 144, 352), ('合成公会', 413, 352),
                         ('跳过', 144, 422), ('选择', 413, 422), blue=('跳过', '选择'))
        self.frames([home(1), guild(), choices, named_preview('美食殿堂'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertNotIn('选择', self.clicks())

    def test_separate_selector_prefers_food_hall_over_the_leftmost_guild(self):
        self.frames([home(1), guild(), separate_guilds('合成公会', '美食殿堂'),
                     named_preview('美食殿堂'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        chosen = [call.args[0].center for call in self.task.ui.click.call_args_list
                  if getattr(call.args[0], 'center', (0, 0))[1] == 422]
        self.assertEqual(chosen, [(413, 422)])

    def test_known_food_hall_can_be_selected_when_another_card_name_is_unreadable(self):
        choices = separate_guilds('美食殿堂', '合成公会')
        choices.items = [item for item in choices.items if item.text != '合成公会']
        self.frames([home(1), guild(), choices, named_preview('美食殿堂'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        chosen = [call.args[0].center for call in self.task.ui.click.call_args_list
                  if getattr(call.args[0], 'center', (0, 0))[1] == 422]
        self.assertEqual(chosen, [(144, 422)])

    def test_separate_selector_normalizes_the_preferred_guild_label(self):
        self.frames([home(1), guild(), separate_guilds('合成公会', '美食 殿堂'),
                     named_preview('美食殿堂'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        chosen = [call.args[0].center for call in self.task.ui.click.call_args_list
                  if getattr(call.args[0], 'center', (0, 0))[1] == 422]
        self.assertEqual(chosen, [(413, 422)])

    def test_separate_selector_searches_later_pages_before_spending(self):
        self.frames([home(1), guild(), separate_guilds('合成公会'),
                     separate_guilds('合成公会二', '美食殿堂'),
                     named_preview('美食殿堂'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        chosen = [call.args[0].center for call in self.task.ui.click.call_args_list
                  if getattr(call.args[0], 'center', (0, 0))[1] == 422]
        self.assertEqual(chosen, [(413, 422)])
        self.task.ui.swipe.assert_called_once_with((830, 300), (200, 300))

    def test_disabled_middle_pages_do_not_trigger_early_fallback(self):
        names = ('合成公会', '灰显公会一', '灰显公会二', '美食殿堂')
        pages = [separate_guilds(name, disabled=(name,) if index in (1, 2) else ())
                 for index, name in enumerate(names)]
        position = 0
        chosen = []
        def capture():
            value = named_preview(chosen[0]) if chosen else pages[position]
            self.task.ui.last = value
            return value
        def swipe(start, end):
            nonlocal position
            position = min(len(pages)-1, max(0, position+(1 if start[0] > end[0] else -1)))
        def click(button):
            self.assertEqual(button.center[1], 422)
            chosen.append(names[position])
        self.task.ui.capture.side_effect = capture
        self.task.ui.swipe.side_effect = swipe
        self.task.ui.click.side_effect = click
        confirmation = self.task.select_sweep_guild(pages[0])
        self.assertEqual(chosen, ['美食殿堂'])
        self.assertTrue(maze.sweep_guild_evidence(confirmation, '美食殿堂'))
        self.assertEqual(self.task.ui.swipe.call_count, 3)

    def test_separate_selector_fallback_is_reacquired_after_bounded_search(self):
        first = separate_guilds('合成公会')
        last = separate_guilds('合成公会二', '美食殿堂', disabled=('美食殿堂',))
        self.frames([home(1), guild(), first, last, last, first,
                     named_preview('合成公会'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        self.assertEqual(self.task.ui.swipe.call_args_list[-1].args, ((200, 300), (830, 300)))
        chosen = [call.args[0].center for call in self.task.ui.click.call_args_list
                  if getattr(call.args[0], 'center', (0, 0))[1] == 422]
        self.assertEqual(chosen, [(144, 422)])

    def test_separate_selector_search_and_fallback_navigation_are_bounded(self):
        first = separate_guilds('合成公会零')
        pages = [first]+[separate_guilds('合成公会'+str(i)) for i in range(1, 6)]
        self.frames([home(1), guild(), *pages, first, named_preview('合成公会零'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')
        directions = [call.args for call in self.task.ui.swipe.call_args_list]
        self.assertEqual(directions, [((830, 300), (200, 300))]*5+[((200, 300), (830, 300))])

    def test_separate_selector_missing_fallback_never_clicks_cached_coordinates(self):
        first = separate_guilds('合成公会')
        last = separate_guilds('合成公会二')
        self.frames([home(1), guild(), first, last, last])
        report = self.task.run()
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['spent'], 0)
        self.assertNotIn('pending_spend', report)
        self.assertFalse(any(getattr(call.args[0], 'center', (0, 0))[1] == 422
                             for call in self.task.ui.click.call_args_list))
        self.assertLessEqual(self.task.ui.swipe.call_count, 10)

    def test_separate_selector_rejects_unknown_or_conflicting_card_labels(self):
        missing = separate_guilds('美食殿堂')
        missing.items = [item for item in missing.items if item.text != '美食殿堂']
        low = separate_guilds('美食殿堂')
        low.items[2].score = .94
        conflicting = separate_guilds('美食殿堂')
        conflicting.items.extend(screen(('合成公会', 150, 335)).items)
        numeric = separate_guilds('123')
        for choices in (missing, low, conflicting, numeric):
            with self.subTest(choices=choices.text()):
                self.task.ui.click.reset_mock()
                self.frames([home(1), guild(), choices, named_preview('美食殿堂'), result(), home(0)])
                report = self.task.run()
                self.assertEqual(report['status'], 'blocked')
                self.assertEqual(report['spent'], 0)
                self.assertNotIn('pending_spend', report)
                self.assertFalse(any(getattr(call.args[0], 'center', (0, 0))[1] == 422
                                     for call in self.task.ui.click.call_args_list))

    def test_separate_selector_requires_the_selected_guild_on_confirmation(self):
        self.frames([home(1), guild(), separate_guilds('美食殿堂'),
                     named_preview('合成公会'), result(), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['spent'], 0)
        self.assertNotIn('pending_spend', report)

    def test_invalid_options_fail_before_device_connection(self):
        for options in (None, [], {'max_passes': 0}, {'max_passes': 100}, {'max_passes': True},
                        {'timeout': -1}, {'timeout': '600'}, {'timeout': 3601}):
            with self.subTest(options=options), patch('pcrscript.runtime.robot_from_config') as connect:
                with self.assertRaises(ValueError):
                    run_task_with_config({'DawnLabyrinth': options}, 'dawn_labyrinth')
                connect.assert_not_called()

    def test_choice_requires_explicit_sweep_instruction(self):
        choices = separate_guilds('美食殿堂', action='选择')
        self.frames([home(1), guild(), choices, named_preview('美食殿堂'), result(), home(0)])
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

    def test_catalogue_normalizes_food_hall_and_keeps_confirmation_identity_consistent(self):
        self.task.ui.number.side_effect = lambda value, roi: value.number(roi)
        def multiple(selected=False):
            value = catalogue(1, selected=selected)
            value.items[1].text = '合成公会'
            value.items.extend(screen(('美食 殿堂', 92, 242), ('黎明界迷宫', 115, 269)).items)
            if selected:
                value.image[148:180, 832:869] = 245
                cv.rectangle(value.image, (832, 238), (868, 269), (230, 155, 25), -1)
            return value
        def click(position):
            if isinstance(position, tuple) and position[0] == 849:
                self.assertEqual(position, (849, 255))
        self.task.ui.click.side_effect = click
        self.frames([home(1), guild(), multiple(), multiple(), multiple(True), multiple(True),
                     bulk(1, guild_name='美食殿堂'), result(), home(0)])
        report = self.task.run()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['spent'], 1)
        self.assertEqual(report['history'][0]['guild'], '美食殿堂')

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
                self.assertIs(saved['pending_spend']['submitted'], True)
                self.assertIs(saved['pending_spend']['submission_tracked'], True)
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

    def test_full_card_unlock_hint_does_not_block_an_eligible_sweep(self):
        choices = separate_guilds('合成灰显公会', '美食殿堂', disabled=('合成灰显公会',))
        choices.items.extend(screen(('通关1次难度1后可解锁', 144, 315)).items)
        self.frames([home(1), guild(), choices, named_preview('美食殿堂'), result(), home(0)])
        report = self.task.run()
        self.assertEqual((report['status'], report['spent']), ('complete', 1))
        self.assertIsNone(maze.locked_notice(choices))
        self.assertEqual([call.args[0].center for call in self.task.ui.click.call_args_list
                          if getattr(call.args[0], 'center', (0, 0))[1] == 422], [(413, 422)])

    def test_locked_guild_card_does_not_block_an_eligible_sweep(self):
        choices = separate_guilds('美食殿堂')
        choices.items.extend(screen(('未通关', 680, 300)).items)
        self.assertIsNone(maze.locked_notice(choices))
        self.frames([home(1), guild(), choices, named_preview('美食殿堂'), result(), home(0)])
        self.assertEqual(self.task.run()['status'], 'complete')

if __name__ == '__main__':
    main()
