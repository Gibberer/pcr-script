import unittest
from unittest.mock import Mock, patch

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, EventUIError, TextBox
from pcrscript.tasks.task_shop import SHOP_TABS, ShopBuy, mana_receipt, parse_rule, selected_tab
from pcrscript.tasks import task_story
from pcrscript.tasks.task_story import GetQuestReward
from ui_fixtures import screen, replay_ui


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

    def test_purchase_waits_for_receipt_animation_without_repeating_spend(self):
        selection = screen(('批量购入100', 798, 439), ('1000', 873, 27))
        moving = screen(('购买完毕',480,88),('消耗玛那×100',480,118),
                        ('1000',502,349),('900',608,349),('确认',480,438))
        ready = screen(('购买完毕',480,42),('消耗玛那×100',480,78),
                       ('1000',502,370),('900',640,370),('确认',480,480))
        for settles in (True, False):
            with self.subTest(settles=settles):
                task = ShopBuy.__new__(ShopBuy)
                task.ui = Mock()
                task.shop = Mock()
                frames = iter([moving, ready if settles else moving])
                def wait(predicate, *args, **kwargs):
                    value = next(frames)
                    if not predicate(value):
                        raise EventUIError('synthetic timeout')
                    return value
                task.ui.wait.side_effect = wait
                if settles:
                    self.assertEqual(task.buy(9, selection),
                                     {'shop':'限定','cost':100,'balance_before':1000,'balance_after':900})
                else:
                    with self.assertRaisesRegex(EventUIError, '购买已提交'):
                        task.buy(9, selection)
                    task.shop.assert_not_called()
                self.assertEqual([c.args[0].text for c in task.ui.click.call_args_list],
                                 ['批量购入100', '确认'] if settles else ['批量购入100'])

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
            None if pattern in ("持有上限", "收取报酬|收取完成|持有上限",
                                '正在进行数据连接|连接中|加载中') else label(pattern, 480, 450))
        screen.blue_button.side_effect = lambda button: remaining["value"] > 0
        task = GetQuestReward.__new__(GetQuestReward)
        task.ui = Mock()

        def wait(predicate, *args, **kwargs):
            for _ in range(3):
                if predicate(screen):
                    return screen
            self.fail('synthetic observation did not become ready')

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

    def test_reward_animation_waits_for_close_without_repeating_claim(self):
        phase = ['home']
        remaining = [1]
        receipt_frames = [0]
        ui = replay_ui('cache/agent/synthetic-quest')
        ui.timeout = 10
        task = GetQuestReward.__new__(GetQuestReward)
        task.ui = ui
        def capture():
            if phase[0] == 'home':
                return screen(('任务',840,432))
            if phase[0] == 'receipt':
                receipt_frames[0] += 1
                if receipt_frames[0] <= 2:
                    return screen(('收取报酬',480,55))
                if receipt_frames[0] == 3:
                    return screen(('收取报酬',480,55),('关闭',480,438))
                return screen(('收取报酬',480,55),('关闭',480,480))
            return screen(('任务',80,30),('每日',385,26),('普通',540,26),('称号',705,26),
                          ('全部收取',840,436),
                          blue=(phase[0], '全部收取') if remaining[0] and phase[0]=='每日' else (phase[0],))
        def click(item):
            if item.text == '任务':
                phase[0] = '每日'
            elif item.text == '全部收取':
                remaining[0] -= 1
                phase[0] = 'receipt'
            elif item.text == '关闭':
                if receipt_frames[0] >= 4:
                    phase[0] = '每日'
            else:
                phase[0] = item.text
        ui.capture.side_effect = capture
        ui.click.side_effect = click
        ui.wait.side_effect = lambda *args, **kwargs: EventUI.wait(ui,*args,**kwargs)
        ticks = iter(range(1000))
        with patch.object(task_story.time,'sleep'), \
             patch.object(task_story.time,'monotonic',side_effect=lambda: next(ticks)):
            report = task.run()
        self.assertEqual(report['status'],'complete')
        self.assertEqual(report['claimed_tabs'],['每日'])
        self.assertEqual([call.args[0].text for call in ui.click.call_args_list],
                         ['任务','全部收取','关闭','普通','称号'])
        self.assertEqual(receipt_frames[0],5)

    def test_reward_overlay_cannot_reuse_background_task_tabs(self):
        page = screen(('任务',80,30),('每日',385,26),('普通',540,26),('称号',705,26))
        overlay = screen(('任务',80,30),('每日',385,26),('普通',540,26),('称号',705,26),
                         ('收取报酬',480,55),('关闭',480,480))
        task = GetQuestReward.__new__(GetQuestReward)
        task.ui = Mock()
        def wait(predicate, *args, **kwargs):
            self.assertFalse(predicate(overlay))
            self.assertTrue(predicate(page))
            return page
        task.ui.wait.side_effect = wait
        self.assertIs(task.quest(),page)

    def test_mission_description_does_not_count_as_a_receipt_heading(self):
        page = screen(('任务',80,30),('每日',385,26),('普通',540,26),('称号',705,26),
                      ('收取报酬10次吧',480,100))
        task = GetQuestReward.__new__(GetQuestReward)
        task.ui = Mock()
        task.ui.wait.side_effect = lambda predicate,*args,**kwargs: self.assertTrue(predicate(page)) or page
        self.assertIs(task.quest(),page)


if __name__ == "__main__":
    unittest.main()
