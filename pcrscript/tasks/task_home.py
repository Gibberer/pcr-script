from .image import ImageTask
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot

from .registry import register

@register("tohomepage")
class ToHomePage(ImageTask):
    '''
    前往游戏首页
    '''

    def run(self, click_pos=(90, 500), timeout=60):
        action = MatchAction(ImageTemplate('shop', consecutive_hit=2), unmatch_actions=(
            ClickAction(ImageTemplate('btn_close') | ImageTemplate('btn_cancel') | ImageTemplate('btn_close_2')),
            ClickAction(pos=click_pos),
        ), timeout=timeout)
        self.action_squential(action, show_progress=False, net_error_check=False)
        if action.is_timeout:
            raise RuntimeError('未能在时限内返回首页，任务未开始；请检查当前页面或弹窗')
