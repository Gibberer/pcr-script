from .image import ImageTask
from typing import TYPE_CHECKING

import cv2 as cv

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot

from .registry import register


class TaskPageNavigation(Action):
    """Exit known task selectors before applying the legacy home/login actions."""

    def __init__(self, *fallback):
        super().__init__()
        self.fallback = fallback
        self.ui = None

    def do(self, screenshot, robot):
        from ..game_ui.screen import EventUI, EventUIError
        from ..game_ui.dawn_labyrinth import navigation_exit as maze_exit
        from ..game_ui.recollection import navigation_exit as recollection_exit
        from ..game_ui.abyss_subjugation import navigation_exit as subjugation_exit
        from ..game_ui.event_layout import navigation_exit as story_exit
        from ..game_ui.battle_stadium import navigation_exit as stadium_exit
        from ..game_ui.collaboration_raid import navigation_exit as collaboration_exit
        from ..game_ui.tower import navigation_exit as tower_exit
        from ..game_ui.navigation import exploration_list_exit, battle_result_exit
        if self.ui is None:
            output = getattr(robot, '_task_output', None) or 'cache/daily/navigation'
            self.ui = EventUI(robot.driver, output)
        screen = self.ui.observe(screenshot)
        target = (exploration_list_exit(screen) or battle_result_exit(screen) or maze_exit(screen)
                  or recollection_exit(screen) or subjugation_exit(screen)
                  or stadium_exit(screen) or story_exit(screen) or collaboration_exit(screen) or tower_exit(screen))
        if target is not None:
            self.ui.click(target)
            return
        if screen.find('当前的列表', (300, 15, 660, 65), exact=True):
            raise EventUIError('联动报酬列表未确认两类报酬均已抽空，不能自动返回首页')
        if screen.find(r'\d:\d{2}', (750, 0, 850, 55)) and screen.find('菜单', (840, 0, 960, 65), exact=True):
            raise EventUIError('存在未结算战斗，不能自动返回首页')
        login_area = (250, 70, 710, 455)
        if screen.find('正在进行数据连接|加载中[.。…]*', exact=True):
            return
        record = screen.find('登录记录', login_area, exact=True)
        switch = screen.find('切换其他账号', login_area, exact=True)
        credential = screen.find('请输入手机号|账号密码|bilibili游戏', (200, 50, 760, 480), exact=True)
        if record is not None or switch is not None or credential is not None:
            logins = screen.all('^登录$', login_area)
            if (record is not None and switch is not None and len(logins) == 1
                    and min(record.score,switch.score,logins[0].score) >= .95
                    and record.center[1] < logins[0].center[1] < switch.center[1]):
                self.ui.click(logins[0])
                return
            raise EventUIError('登录窗口未确认可用的已保存账号，已停止自动点击；请在游戏内完成登录')
        if not screen.items:
            for action in self.fallback:
                if isinstance(action, ClickAction) and action.template is not None and action.pos is None:
                    action.bindTask(self.task).do(screenshot, robot)
            return
        if screen.find('正在进行数据连接|加载中[.。…]*', exact=True):
            return
        start = screen.find('点击屏幕开始游戏', (260, 450, 710, 535), exact=True)
        menu = screen.find('主菜单', (0, 460, 200, 540), exact=True)
        if start is not None and menu is not None and min(start.score, menu.score) >= .95:
            self.ui.click(start)
            return
        if start is not None:
            return
        for action in self.fallback:
            action.bindTask(self.task).do(screenshot, robot)
            if isinstance(action, CanSkipMatchAction) and action.skip:
                break


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
            from ..game_ui.screen import ocr_engine
            self._ocr = ocr_engine()
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
        action = MatchAction(ImageTemplate('shop', consecutive_hit=2), unmatch_actions=[TaskPageNavigation(
            SkipLoginStamp(),
            ClickAction(ImageTemplate('btn_close') | ImageTemplate('btn_cancel') | ImageTemplate('btn_close_2')),
            ClickAction(pos=click_pos),
        )], timeout=timeout)
        self.action_squential(action, show_progress=False, net_error_check=False)
        if action.is_timeout:
            raise RuntimeError('未能在时限内返回首页，任务未开始；请检查当前页面或弹窗')
