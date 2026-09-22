"""Bulk upgrade safety and dispatch checks; no live game access."""
import tempfile
from unittest import TestCase
from unittest.mock import Mock

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.tasks.task_character_upgrade import UpgradeAllCharacters, selected_count


def screen(count=None, enabled=False):
    items = [TextBox('一键强化', 1, [[400,30],[500,30],[500,50],[400,50]]),
             TextBox('自动选择', 1, [[790,100],[900,100],[900,120],[790,120]]),
             TextBox('确认', 1, [[550,470],[620,470],[620,490],[550,490]])]
    if count is not None:
        items.append(TextBox(f'{count}/20', 1, [[880,65],[930,65],[930,85],[880,85]]))
    s = EventScreen(np.zeros((540,960,3), dtype=np.uint8), items)
    s.blue_button = Mock(return_value=enabled)
    return s


class CharacterUpgradeTests(TestCase):
    def task(self, root, observed):
        robot = Mock()
        robot.driver.get_screen_size.return_value = (960,540)
        task = UpgradeAllCharacters(robot, {'output':root, 'max_batches':2})
        task.ui = Mock()
        task.bulk = Mock(side_effect=observed)
        return task

    def test_unknown_count_is_not_zero(self):
        self.assertIsNone(selected_count(screen()))
        self.assertEqual(selected_count(screen(0)), 0)
        self.assertEqual(selected_count(screen(20)), 20)

    def test_game_no_candidates_notice_skips_without_spending(self):
        s = screen()
        s.items += [TextBox('角色一览',1,[[40,10],[180,10],[180,50],[40,50]]),
                    TextBox('没有可一键强化的角色。',1,[[300,250],[650,250],[650,285],[300,285]])]
        with tempfile.TemporaryDirectory() as root:
            task = self.task(root, [])
            task.ui.capture.return_value = s
            self.assertFalse(task.enter())
            task.ui.click.assert_not_called()

    def test_zero_requires_second_read_and_disabled_confirmation(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.task(root, [screen(0),screen(0),screen(0)])
            task.batches('auto')
            self.assertTrue(task.report['auto_exhausted'])
            self.assertFalse(task.report['history'])

    def test_zero_with_enabled_confirmation_stops(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.task(root, [screen(0),screen(0),screen(0,True)])
            with self.assertRaises(EventUIError):
                task.batches('auto')
            self.assertNotIn('auto_exhausted',task.report)

    def test_disabled_nonempty_batch_never_confirms_spend(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.task(root, [screen(20),screen(20)])
            with self.assertRaises(EventUIError):
                task.batches('auto')
            task.ui.click.assert_not_called()

    def test_no_completion_without_result_dialog(self):
        with tempfile.TemporaryDirectory() as root:
            task = self.task(root, [screen(20),screen(20,True)])
            task.ui.wait.side_effect = [screen(20),EventUIError('timeout')]
            with self.assertRaises(EventUIError):
                task.batches('auto')
            self.assertEqual(task.report['history'], [])
