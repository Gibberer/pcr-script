from .image import ImageTask
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot
    from ..strategist import Member

from .registry import register

@register("tohomepage")
class ToHomePage(ImageTask):
    '''
    前往游戏首页
    '''

    def run(self, click_pos=(90, 500), timeout=0):
        self.action_squential(
            MatchAction(ImageTemplate('shop', consecutive_hit=2), unmatch_actions=(
            ClickAction(ImageTemplate('btn_close') | ImageTemplate('btn_ok_blue')
                        | ImageTemplate('btn_download') | ImageTemplate('btn_skip')
                        | ImageTemplate('btn_cancel') | ImageTemplate('select_branch_first')
                        | ImageTemplate('app_no_responed') | ImageTemplate('btn_close_2')),
            ClickAction(pos=click_pos),
        ),timeout=timeout), show_progress=False, net_error_check=False)
