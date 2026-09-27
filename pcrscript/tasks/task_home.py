from .image import ImageTask
from typing import TYPE_CHECKING

import cv2 as cv

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot

from .registry import register


class SkipLoginStamp(CanSkipMatchAction):
    """Skip the observed daily stamp board before ordinary home navigation."""

    def __init__(self):
        super().__init__()
        self._ocr = None

    def do(self, screenshot, robot):
        self.skip = False
        button = ImageTemplate('btn_skip', threshold=.86,
                               roi=(850, 0, 950, 80)).match(screenshot)
        if button is None:
            return
        if self._ocr is None:
            from rapidocr import RapidOCR
            self._ocr = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                          "EngineConfig.onnxruntime.inter_op_num_threads": 1})
        image = cv.resize(screenshot, (960, 540), interpolation=cv.INTER_AREA)
        result = self._ocr(image)
        text = ''.join(result.txts or [])
        if not ('应援' in text and '章' in text) and not ('欢迎回来' in text and 'Goal' in text):
            return
        robot.driver.click(*button)
        self.skip = True

@register("tohomepage")
class ToHomePage(ImageTask):
    '''
    前往游戏首页
    '''

    def run(self, click_pos=(90, 500), timeout=60):
        action = MatchAction(ImageTemplate('shop', consecutive_hit=2), unmatch_actions=(
            SkipLoginStamp(),
            ClickAction(ImageTemplate('btn_close') | ImageTemplate('btn_cancel') | ImageTemplate('btn_close_2')),
            ClickAction(pos=click_pos),
        ), timeout=timeout)
        self.action_squential(action, show_progress=False, net_error_check=False)
        if action.is_timeout:
            raise RuntimeError('未能在时限内返回首页，任务未开始；请检查当前页面或弹窗')
