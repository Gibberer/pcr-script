import unittest
from unittest.mock import Mock, patch

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.tasks.task_shop import SHOP_TABS, ShopBuy, mana_receipt, parse_rule, selected_tab
from pcrscript.tasks import task_story
from pcrscript.tasks.task_story import GetQuestReward


def label(text, x, y):
    return TextBox(text, 1.0, [[x - 25, y - 8], [x + 25, y - 8],
                               [x + 25, y + 8], [x - 25, y + 8]])


class ShopQuestTests(unittest.TestCase):
    def test_shop_rule_keeps_named_destinations_and_rejects_unchecked_refresh(self):
        self.assertEqual((SHOP_TABS[1], SHOP_TABS[9]), ("通常", "限定"))
        self.assertEqual(parse_rule({1: [-1], "9": [-1], "1_settings": {"time": 1}}),
                         {1: [-1], 9: [-1]})
        with self.assertRaisesRegex(ValueError, "自动刷新"):
            parse_rule({1: [-1], "1_settings": {"time": 2}})

    def test_selected_tab_uses_active_fill(self):
        image = np.full((540, 960, 3), 255, dtype=np.uint8)
        image[58, 130] = [239, 158, 82]
        screen = EventScreen(image, [])
        self.assertTrue(selected_tab(screen, label("通常", 130, 70)))
        self.assertFalse(selected_tab(screen, label("限定", 908, 70)))

    def test_purchase_does_not_confirm_mismatched_total(self):
        task = ShopBuy.__new__(ShopBuy)
        task.ui = Mock()
        purchase = label("批量购入2,784,000", 790, 438)
        selection = Mock()
        selection.find.side_effect = lambda pattern, *args, **kwargs: (
            purchase if pattern.startswith("批量购入") else None)
        confirmation = Mock()
        confirmation.find.return_value = None
        confirmation.text.return_value = "总计 2,000,000 玛那"
        task.ui.wait.return_value = confirmation
        with self.assertRaisesRegex(EventUIError, "总价"):
            task.buy(1, selection)
        task.ui.click.assert_called_once_with(purchase)

    def test_mana_receipt_checks_both_spend_and_balance(self):
        screen = EventScreen(np.zeros((540, 960, 3), dtype=np.uint8), [
            label("消耗玛那×2784000", 480, 78),
            label("510,289,942", 500, 370),
            label("507,505,942", 640, 370),
        ])
        self.assertEqual(mana_receipt(screen, 2784000, 510289942),
                         {"balance_before": 510289942, "balance_after": 507505942})
        with self.assertRaisesRegex(EventUIError, "回执"):
            mana_receipt(screen, 2784000, 510289941)

    def test_quest_tab_state_requires_blue_fill(self):
        image = np.full((540, 960, 3), 255, dtype=np.uint8)
        image[34, 540] = [165, 89, 49]
        screen = EventScreen(image, [])
        self.assertTrue(GetQuestReward.active_tab(screen, label("普通", 540, 26)))
        self.assertFalse(GetQuestReward.active_tab(screen, label("称号", 705, 26)))

    def test_quest_exactly_three_claims_finishes_when_button_dims(self):
        remaining = {"value": 3}
        screen = Mock()
        screen.find.side_effect = lambda pattern, *args, **kwargs: (
            None if pattern == "持有上限" else label(pattern, 480, 450))
        screen.blue_button.side_effect = lambda button: remaining["value"] > 0
        task = GetQuestReward.__new__(GetQuestReward)
        task.ui = Mock()

        def wait(predicate, *args, **kwargs):
            self.assertTrue(predicate(screen))
            return screen

        def click(item, *args, **kwargs):
            if item.text == "全部收取":
                remaining["value"] -= 1

        task.ui.wait.side_effect = wait
        task.ui.click.side_effect = click
        with patch.object(GetQuestReward, "active_tab", return_value=True), patch.object(task_story.time, "sleep"):
            result = task.run()
        self.assertEqual(remaining["value"], 0)
        self.assertEqual(result["claimed_tabs"], ["每日"])
        self.assertEqual(result["empty_tabs"], ["普通", "称号"])


if __name__ == "__main__":
    unittest.main()
