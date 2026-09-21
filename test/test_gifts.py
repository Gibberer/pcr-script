"""Offline boundaries for inventory destruction, gift recovery and scaling."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock, patch

import numpy as np
import cv2 as cv

from pcrscript.tasks.task_gifts import GetGift, inventory, stamina_excluded
from pcrscript.game_ui.screen import EventUI, EventUIError, EventScreen, TextBox


def screen(*items):
    return EventScreen(np.zeros((540, 960, 3), np.uint8), [
        TextBox(text, 1, [[x-15, y-8], [x+15, y-8], [x+15, y+8], [x-15, y+8]])
        for text, x, y in items])


class GiftTests(TestCase):
    def test_live_checkbox_fixture_and_unchecked_box(self):
        s = screen()
        self.assertFalse(stamina_excluded(s))
        s.image[458:492, 343:379] = cv.imread(str(Path(__file__).parent / "fixtures/gifts/exclude_stamina.png"))
        self.assertTrue(stamina_excluded(s))

    def test_local_ocr_recovers_missed_dismantle_button(self):
        with TemporaryDirectory() as folder:
            driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
            driver.screenshot.return_value = np.zeros((540, 960, 3), np.uint8)
            ui = EventUI(driver, folder)
            s = ui.capture()
            roi = (485, 450, 695, 509)
            s.image[450:509, 485:695] = cv.imread(str(Path(__file__).parent / "fixtures/gifts/confirm_dismantle.png"))
            button = ui.read_region(s, roi).find("分解", roi, exact=True)
            self.assertIsNotNone(button)
            self.assertTrue(s.blue_button(button))

    def test_missing_or_low_confidence_inventory_is_not_zero(self):
        for text in ("", "5001/5000", "0/0", "5000/?"):
            with self.subTest(text=text), self.assertRaises(EventUIError):
                inventory(screen((text, 552, 87)))
        s = screen(("5000/5000", 552, 87))
        s.items[0].score = .9
        with self.assertRaises(EventUIError):
            inventory(s)
        self.assertEqual(inventory(screen(("4950/5000", 552, 87))), (4950, 5000))

    def test_repeated_gift_limit_only_recovers_once(self):
        with TemporaryDirectory() as folder:
            g = GetGift(SimpleNamespace(driver=Mock(get_screen_size=Mock(return_value=(960, 540)))), {"output": folder})
            g.open_gifts = Mock()
            g.free_space = Mock(return_value=True)
            gifts = screen(("全部收取", 800, 477))
            gifts.blue_button = Mock(return_value=True)
            g.gift_list = Mock(return_value=gifts)
            g.ui.wait = Mock(side_effect=[screen(("收取礼物", 480, 42)), screen(("持有上限", 480, 148))] * 2)
            g.ui.expect_click = Mock()
            g.ui.click = Mock()
            g.ui.save = Mock()
            self.assertEqual(g.run()["status"], "partial")
            g.free_space.assert_called_once()

    def test_enough_space_does_not_auto_select_or_dismantle(self):
        with TemporaryDirectory() as folder:
            g = GetGift(SimpleNamespace(driver=Mock(get_screen_size=Mock(return_value=(960, 540)))), {"output": folder})
            g.home = Mock(return_value=screen(("商店", 690, 455)))
            g.ui = Mock()
            g.ui.wait.return_value = screen(("一键分解", 850, 31), ("4250/5000", 552, 87))
            self.assertTrue(g.free_space())
            self.assertEqual(g.report["dismantled"], 0)
            labels = [c.args[0] for c in g.ui.expect_click.call_args_list]
            self.assertEqual(labels, ["特别装备", "特别装备分解"])

    def test_unknown_inventory_never_confirms_dismantle(self):
        with TemporaryDirectory() as folder:
            g = GetGift(SimpleNamespace(driver=Mock(get_screen_size=Mock(return_value=(960, 540)))), {"output": folder})
            g.home = Mock(return_value=screen(("商店", 690, 455)))
            g.ui = Mock()
            g.ui.wait.return_value = screen(("一键分解", 850, 31))
            with self.assertRaises(EventUIError):
                g.free_space()
            self.assertEqual(len(g.ui.click.call_args_list), 1)  # Shop only.

    def test_other_item_limit_does_not_dismantle_nonfull_ex_inventory(self):
        with TemporaryDirectory() as folder:
            g = GetGift(SimpleNamespace(driver=Mock(get_screen_size=Mock(return_value=(960, 540)))), {"output": folder})
            g.home = Mock(return_value=screen(("商店", 690, 455)))
            g.ui = Mock()
            g.ui.wait.return_value = screen(("一键分解", 850, 31), ("4950/5000", 552, 87))
            self.assertFalse(g.free_space(require_full=True))
            self.assertEqual(g.report["dismantled"], 0)
            self.assertEqual(len(g.ui.click.call_args_list), 1)

    def test_invalid_target_rejected_before_actions(self):
        for target in (0, 499, 1001):
            with TemporaryDirectory() as folder:
                driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
                with self.assertRaises(ValueError):
                    GetGift(SimpleNamespace(driver=driver), {"output": folder, "free_slots": target})
                driver.click.assert_not_called()


class ResolutionTests(TestCase):
    def test_actual_capture_size_scales_click_and_swipe_after_resize(self):
        with TemporaryDirectory() as folder, patch("pcrscript.game_ui.screen.time.sleep"):
            driver = Mock(get_screen_size=Mock(return_value=(960, 540)))
            ui = EventUI(driver, folder)
            for width, height in ((960, 540), (1280, 720), (1920, 1080), (1200, 800)):
                with self.subTest(size=(width, height)):
                    driver.screenshot.return_value = np.zeros((height, width, 3), np.uint8)
                    s = ui.capture(ocr=False)
                    self.assertEqual(s.image.shape, (540, 960, 3))
                    ui.click((480, 270))
                    driver.click.assert_called_with(width//2, height//2)
                    ui.swipe((0, 0), (480, 270), 450)
                    driver.swipe.assert_called_with((0, 0), (width//2, height//2), 450)


if __name__ == "__main__":
    main()
