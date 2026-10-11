"""Synthetic schedule transitions; no emulator or real account fixtures."""
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from pcrscript import Robot
from pcrscript.game_ui.screen import EventUI, EventUIError
from pcrscript.tasks.task_routines import Schedule
from ui_fixtures import replay_ui, screen


def book(done=8, total=9):
    return screen(('来自可可萝的通知',470,116), ('1/1',750,120), ('达成',725,210),
                  ('交给可可萝',475,297), (f'{done}/{total}',748,301),
                  ('探索',262,355), ('用掉经验值关卡剩余挑战次数吧',375,380),
                  ('执行',726,368), ('关闭',278,480), ('列表设定',459,480), ('一键自动',660,480),
                  blue=() if done == total else ('一键自动','执行'))


class ScheduleTests(TestCase):
    def run_frames(self, frames, upright=None, real_scroll=False):
        self.root = TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        ui = replay_ui(self.root.name)
        ui.timeout = 45
        ui.scrollbar_bounds.side_effect = EventUI.scrollbar_bounds
        ui.read_region.side_effect = lambda value, roi, classify: (upright or {}).get(id(value), value)
        robot = Robot(Mock(get_screen_size=Mock(return_value=(960,540))), show_progress=False)
        robot.driver.screenshot.return_value = frames[0].image
        if real_scroll:
            ui.driver = robot.driver
            ui.width, ui.height = 960, 540
            ui.swipe.side_effect = lambda *args, **kwargs: EventUI.swipe(ui, *args, **kwargs)
            ui.scrollbar.side_effect = lambda *args, **kwargs: EventUI.scrollbar(ui, *args, **kwargs)
        with patch('pcrscript.tasks.task_routines.EventUI', return_value=ui):
            task = Schedule(robot)
        values = iter(frames)
        def capture():
            value = next(values, frames[-1])
            ui.last = value
            return value
        ui.capture.side_effect = capture
        ui.wait.side_effect = lambda *args, **kwargs: EventUI.wait(ui, *args, **kwargs)
        def match(template, image):
            if template._name == 'symbol_schedule':
                return (731,49)
            if template._name == 'symbol_schedule_completed_mark':
                return (729,206)
            value = ui.last
            if template._name in ('btn_ok_blue','btn_ok','btn_skip_ok','btn_close'):
                item = value.find('确认|关闭', (350,0,960,540), exact=True)
                return item.center if item else None
            return None
        counter = iter(range(1000))
        with patch('pcrscript.templates.ImageTemplate.match', match), \
             patch('pcrscript.run_session.clock.sleep'), \
             patch('pcrscript.run_session.clock.monotonic', side_effect=lambda: next(counter)):
            self.task, self.ui = task, ui
            return task.run()

    def test_notice_stamp_and_intermediate_book_do_not_end_auto_execution(self):
        confirm = screen(('经验值关卡跳过确认',480,145), ('确认',589,372), blue=('确认',))
        receipt = screen(('获得道具',480,42), ('确认',480,480), blue=('确认',))
        report = self.run_frames([book(0), book(8), book(8), confirm, receipt, book(9)])
        self.assertEqual((report['status'], report['completed'], report['total']), ('complete',9,9))
        self.assertEqual(report['remaining_items'], [])
        self.assertEqual([call.args[0].text if hasattr(call.args[0],'text') else tuple(call.args[0])
                          for call in self.ui.click.call_args_list],
                         ['一键自动',(589,372),(480,480),'关闭'])

    def test_unfinished_schedule_is_bounded_and_not_replayed(self):
        report = self.run_frames([book(8)])
        self.assertEqual((report['status'], report['completed'], report['total']), ('partial',8,9))
        self.assertIn('经验值', report['remaining_items'][0])
        self.assertTrue(report['pending'])
        self.assertLess(self.ui.capture.call_count, 200)
        self.assertEqual([call.args[0].text for call in self.ui.click.call_args_list], ['一键自动'])

    def test_already_complete_schedule_does_not_start_auto_again(self):
        report = self.run_frames([book(9)])
        self.assertEqual(report['status'], 'already_complete')
        self.assertEqual([call.args[0].text for call in self.ui.click.call_args_list], ['关闭'])

    def test_notice_counter_cannot_replace_missing_schedule_counter(self):
        value = book(8)
        value.items = [item for item in value.items if item.text != '8/9']
        with self.assertRaisesRegex(EventUIError,'完成数未核实'):
            self.run_frames([value])
        self.ui.click.assert_not_called()

    def test_resource_refill_confirmation_is_not_accepted(self):
        confirmation = screen(('回复体力',480,145), ('确认',589,372), blue=('确认',))
        with self.assertRaisesRegex(EventUIError,'资源回复或重置'):
            self.run_frames([book(8),confirmation])
        self.assertEqual([call.args[0].text for call in self.ui.click.call_args_list], ['一键自动'])

    def test_foreground_dialog_blocks_underlying_completion_counter(self):
        value = book(9)
        value.image[:] //= 2
        self.assertFalse(Schedule.book(value))

    def test_settlement_scroll_position_is_restored_without_replaying_auto(self):
        lower = book(9)
        lower.items = [item for item in lower.items if item.text not in ('交给可可萝','9/9')]
        lower.image[290:437,774:781] = (230,155,25)
        report = self.run_frames([lower,book(9)])
        self.assertEqual((report['status'],report['completed']), ('already_complete',9))
        self.ui.scrollbar.assert_called_once()
        self.assertEqual(self.ui.scrollbar.call_args.args, (lower,(769,97,784,445),-1))
        self.assertEqual([call.args[0].text for call in self.ui.click.call_args_list], ['关闭'])

    def test_scroll_restore_during_auto_reads_the_whole_counter(self):
        lower = book(9)
        lower.items = [item for item in lower.items if item.text not in ('交给可可萝','9/9')]
        lower.image[290:437,774:781] = (230,155,25)
        report = self.run_frames([book(8), lower, book(9)])
        self.assertEqual((report['status'],report['completed']), ('complete',9))
        self.ui.scrollbar.assert_called_once()
        self.assertEqual(self.ui.scrollbar.call_args.args, (lower,(769,97,784,445),-1))

    def test_resized_scrollbar_stops_when_the_counter_is_visible_without_fallback(self):
        lower = book(9)
        lower.items = [item for item in lower.items if item.text not in ('交给可可萝','9/9')]
        lower.image[341:438,774:781] = (230,155,25)
        upper = book(9)
        upper.image[98:281,774:781] = (230,155,25)
        report = self.run_frames([book(0),lower,upper], real_scroll=True)
        self.assertEqual((report['status'],report['completed'],report['total']), ('complete',9,9))
        self.ui.driver.swipe.assert_called_once()
        self.assertFalse(self.ui.driver.swipe.call_args.kwargs.get('fallback',False))
        self.assertEqual([call.args[0].text for call in self.ui.click.call_args_list], ['一键自动','关闭'])

    def test_scroll_still_rejects_unchanged_list_or_counter_behind_a_dialog(self):
        lower = book(9)
        lower.items = [item for item in lower.items if item.text not in ('交给可可萝','9/9')]
        lower.image[341:438,774:781] = (230,155,25)
        dimmed = book(9)
        dimmed.image[:] //= 2
        for after in (lower,dimmed):
            with self.subTest(dimmed=after is dimmed), self.assertRaisesRegex(EventUIError,'未确认变化'):
                self.run_frames([book(0),lower,after], real_scroll=True)
            self.assertEqual([call.args[0].text for call in self.ui.click.call_args_list], ['一键自动'])

    def test_changed_total_does_not_claim_the_original_plan_complete(self):
        report = self.run_frames([book(8),book(10,10)])
        self.assertEqual(report['status'],'partial')
        self.assertTrue(any('总数发生变化' in reason for reason in report['pending']))

    def test_upright_crop_corrects_rotated_full_frame_digits(self):
        rotated = book(6,6)
        report = self.run_frames([book(8), rotated], upright={id(rotated):book(9)})
        self.assertEqual((report['status'],report['completed'],report['total']), ('complete',9,9))
        self.assertTrue(self.ui.read_region.call_count)
        for call in self.ui.read_region.call_args_list:
            self.assertIs(call.kwargs['classify'], False)
