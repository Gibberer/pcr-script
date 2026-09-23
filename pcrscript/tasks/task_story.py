from .image import ImageTask
from .base import BaseTask
from pcrscript.run_session import clock as time
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot

from .registry import register
from ..game_ui.screen import EventUI, EventUIError

@register("clear_story", requires_home=True)
class ClearStory(ImageTask):

    def __init__(self, robot: 'Robot'):
        super().__init__(robot)
        self.show_progress = False

    '''
    清new剧情
    逻辑：
    根据游戏内“new”标签判断是否有未读的剧情，直至所有“new”标签消失
    '''
    def run(self):
        mismatch_cnt = 0
        while True:
            screenshot = self.robot.driver.screenshot()
            if self.have_dialog(screenshot):
                self.skip_dialog()
            elif self.in_story_read_page(screenshot):
                self.skip_reading_page()
            elif self.in_story_tab(screenshot):
                if self.in_main_story_list(screenshot):
                    self.resolve_main_list()
                elif self.in_sub_story_list(screenshot):
                    self.resolve_sub_list()
                elif mismatch_cnt > 2:
                    mismatch_cnt = 0
                    self.resolve_other_list()
                else:
                    mismatch_cnt += 1
            else:
                # try move to story tab
                self.action_once(ClickAction(template='tab_story'))
            time.sleep(0.5)

    def resolve_main_list(self):
        new_story_list = self._read_template_pos_list('symbol_main_new_story')
        if new_story_list:
            # 排除特别剧情部分
            new_story_list = list(filter(lambda pos:pos[0]< 770, new_story_list))
        if not new_story_list:
            raise Exception("未检测到未读的剧情，终止任务")
        self.robot.driver.click(*new_story_list[0])

    def resolve_sub_list(self):
        new_story_list = self._read_template_pos_list('symbol_sub_new_story', retry_limit=1)
        if not new_story_list:
            new_story_list = self._read_template_pos_list('symbol_sub_new_story_1', retry_limit=1)
        if new_story_list:
            # 排除掉错误的位置
            new_story_list = list(filter(lambda pos:pos[0] < 800, new_story_list))
        if new_story_list:
            self.robot.driver.click(*new_story_list[0])
        else:
            screenshot = self.robot.driver.screenshot()
            if self.in_story_read_page(screenshot) or self.have_dialog(screenshot):
                return
            if self._can_scroll(screenshot):
                self.action_once(SwipeAction((700, 350), (700, 150)))
                time.sleep(1)
                self.resolve_sub_list()
            else:
                # 返回上一级页面
                self.action_once(ClickAction(template='btn_back'))

    def resolve_other_list(self):
        self.resolve_sub_list()

    def skip_reading_page(self):
        self.action_squential(MatchAction(template='btn_skip_in_story',
                                unmatch_actions=[ClickAction(template='symbol_menu_in_story'), ClickAction(template='select_branch_first'),],
                                matched_actions=[ClickAction()],
                                timeout=5))

    def skip_dialog(self):
        self.action_once(ClickAction(template='btn_close'))
        is_click_skip_btn = self.action_once(ClickAction(template='btn_skip_blue'))
        self.action_once(ClickAction(template='btn_novocal_blue'))
        time.sleep(1)
        if is_click_skip_btn:
            time.sleep(1.5)
            # 处理剧情有视频的情况
            self.action_once(ClickAction(pos=(150, 250)))

    def in_main_story_list(self, screenshot):
        return self.template_match(screenshot, ImageTemplate('symbol_main_story'))

    def in_sub_story_list(self, screenshot):
        return self.template_match(screenshot, ImageTemplate('symbol_sub_story'))

    def in_story_tab(self, screenshot):
        return self.template_match(screenshot, ImageTemplate('symbol_story'))

    def have_dialog(self, screenshot):
        return self.template_match(screenshot, ImageTemplate('symbol_dialog'))

    def in_story_read_page(self, screenshot):
        return self.template_match(screenshot, ImageTemplate('symbol_menu_in_story'))

    def _can_scroll(self, screenshot):
        sample_pos = self._to_canonical_pos((916, 427))
        sample_color = screenshot[sample_pos[1],sample_pos[0]]
        return sample_color[0] < 200

    def _to_canonical_pos(self, pos):
        device_height = self.robot.deviceheight
        device_width = self.robot.devicewidth
        return (int(pos[0]/(device_width/self.define_width)), int(pos[1]/(device_height/self.define_height)))

    def _read_template_pos_list(self, template, retry_limit=3, retry_interval=1.5):
        times = 0
        while times < retry_limit:
            screenshot = self.robot.driver.screenshot()
            ret = self.template_match(screenshot, ImageTemplate(template, ret_count=-1))
            if ret:
                # 根据y轴排序
                ret.sort(key=lambda pos: pos[1])
                return ret
            times += 1
            time.sleep(retry_interval)


@register("get_quest_reward", requires_home=True)
class GetQuestReward(BaseTask):
    """Claim completed rewards on every home quest tab."""

    TABS = ("每日", "普通", "称号")

    def __init__(self, robot):
        super().__init__(robot)
        output = getattr(robot, "_task_output", None) or "cache/daily/quests"
        self.ui = EventUI(robot.driver, output)

    @staticmethod
    def active_tab(screen, item):
        x, y = item.center
        blue, green, red = map(int, screen.image[min(539, y + 8), x])
        return blue - red > 75 and blue - green > 45

    def quest(self):
        return self.ui.wait(lambda s: s.find("任务", (45, 0, 150, 58), exact=True)
                            and all(s.find(name, (300, 7, 800, 46), exact=True)
                                    for name in self.TABS), "任务页面")

    def run(self):
        home = self.ui.wait(lambda s: s.find("任务", (790, 390, 890, 470), exact=True), "首页任务入口")
        self.ui.click(home.find("任务", (790, 390, 890, 470), exact=True))
        self.quest()
        report = {"claimed_tabs": [], "empty_tabs": []}
        for name in self.TABS:
            s = self.quest()
            tab = s.find(name, (300, 7, 800, 46), exact=True)
            if not self.active_tab(s, tab):
                self.ui.click(tab)
                s = self.ui.wait(lambda s: (item := s.find(name, (300, 7, 800, 46), exact=True))
                                 is not None and self.active_tab(s, item), f"切换到{name}任务")
            for attempt in range(3):
                button = s.find("全部收取", (730, 405, 950, 468), exact=True)
                if button is None:
                    raise EventUIError(f"{name}任务页缺少全部收取按钮")
                if not s.blue_button(button):
                    if attempt == 0:
                        report["empty_tabs"].append(name)
                    break
                self.ui.save(f"quest_{name}_before_claim", s)
                self.ui.click(button)
                result = self.ui.wait(lambda s: s.find("收取报酬|收取完成|持有上限", (230, 15, 730, 170)),
                                      f"{name}任务领奖结果", timeout=25)
                if result.find("持有上限", (230, 15, 730, 170)):
                    raise EventUIError(f"{name}任务奖励遇到持有上限，未继续领取")
                close = result.find("关闭|确认", (350, 435, 605, 515), exact=True)
                if close is None:
                    raise EventUIError(f"{name}任务奖励弹窗无法关闭")
                self.ui.click(close)
                time.sleep(1)
                s = self.quest()
                if name not in report["claimed_tabs"]:
                    report["claimed_tabs"].append(name)
            else:
                s = self.quest()
                button = s.find("全部收取", (730, 405, 950, 468), exact=True)
                if button is None or s.blue_button(button):
                    raise EventUIError(f"{name}任务连续三次领奖后仍有可领项")
        return report
