from unittest import TestCase
from unittest.mock import Mock

import numpy as np

from pcrscript.game_ui.screen import EventScreen, TextBox
from pcrscript.tasks.task_character_bond import gift_grades, gift_counts, verified_gift_counts


def item(text, x, y):
    return TextBox(text, 1.0, [[x-8, y-8], [x+8, y-8], [x+8, y+8], [x-8, y+8]])


class GiftPreviewTests(TestCase):
    def test_reads_two_distinct_levels_and_each_consumed_stack(self):
        screen = EventScreen(np.zeros((540, 960, 3), dtype=np.uint8), [
            item('品级1', 340, 225), item('品级8', 540, 225),
            item('×96', 405, 374), item('×162', 485, 374),
        ])
        self.assertEqual(gift_grades(screen), (1, 8))
        self.assertEqual(gift_counts(screen), [96, 162])

    def test_missing_level_or_cost_remains_unknown(self):
        screen = EventScreen(np.zeros((540, 960, 3), dtype=np.uint8), [item('品级8', 540, 225)])
        self.assertIsNone(gift_grades(screen))
        self.assertEqual(gift_counts(screen), [])

    def test_small_gift_count_requires_localized_read_of_visible_icon(self):
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        image[326:367, 363:417] = (20, 50, 230)
        screen = EventScreen(image, [])
        ui = Mock(read_region=Mock(return_value=EventScreen(image, [item('x140', 405, 376)])))
        self.assertEqual(verified_gift_counts(ui, screen), [140])
        ui.read_region.assert_called_once()
