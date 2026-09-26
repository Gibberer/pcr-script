"""Synthetic daily login board navigation; no device input."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

import cv2 as cv
import numpy as np

from pcrscript.actions import ClickAction, MatchAction
from pcrscript.tasks.task_home import SkipLoginStamp
from pcrscript.templates import BooleanTemplate


class LoginStampTests(TestCase):
    def test_stamp_board_skips_and_does_not_click_behind_overlay(self):
        icon = cv.imread('images/btn_skip.png')
        image = np.zeros((540, 960, 3), np.uint8)
        image[15:15+icon.shape[0], 880:880+icon.shape[1]] = icon
        driver = Mock()
        robot = SimpleNamespace(driver=driver, devicewidth=960, deviceheight=540)
        skip = SkipLoginStamp()
        skip._ocr = Mock(return_value=SimpleNamespace(txts=['应援', '印', '章']))
        action = MatchAction(BooleanTemplate(False),
                             unmatch_actions=(skip, ClickAction(pos=(90, 500))))
        action.bindTask(SimpleNamespace(define_width=960, define_height=540))
        action.do(image, robot)
        driver.click.assert_called_once_with(913.5, 38.0)

    def test_skip_icon_without_login_board_text_is_ignored(self):
        icon = cv.imread('images/btn_skip.png')
        image = np.zeros((540, 960, 3), np.uint8)
        image[15:15+icon.shape[0], 880:880+icon.shape[1]] = icon
        driver = Mock()
        robot = SimpleNamespace(driver=driver)
        skip = SkipLoginStamp()
        skip._ocr = Mock(return_value=SimpleNamespace(txts=['剧情画面']))
        skip.do(image, robot)
        self.assertFalse(skip.skip)
        driver.click.assert_not_called()
