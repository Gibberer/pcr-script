from .image import ImageTask
from pcrscript.run_session import clock as time
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot
    from ..strategist import Member

from .base import TimeLimitTask, EventNews
from .registry import register
from ._actions import _combat_actions, _enter_adventure_actions

@register("common_adventure")
class CommonAdventure(ImageTask):
    '''
    通用的过图任务，执行内容为：
    1. 寻找当前人物的位置
    2. 点击人物
    3. 进入战斗页面，开始战斗直到结束
    4. -> 1 循环
    '''
    def __init__(self, robot: 'Robot'):
        super().__init__(robot)
        self.show_progress = False

    def run(self, character_symbol="character", estimate_combat_duration=30):
        '''
        :param charactor_symbol 当前使用角色在冒险地图上的图片特征（取脸部或身体部分即可，不要截到背景）
        :param estimate_combat_duration 预估一次战斗的时间
        '''
        while True:
            screenshot = self.robot.driver.screenshot()
            pos = self.template_match(screenshot, ImageTemplate(character_symbol, threshold=0.7))
            if pos :
                # 通过图片匹配的位置信息是真实的坐标，不需要转换
                self.robot.driver.click(pos[0], pos[1] + self.robot.deviceheight * 0.1)
                match_action = MatchAction(template='btn_challenge', timeout=5)
                self.action_squential(match_action)
                if not match_action.is_timeout:
                    actions = _combat_actions(combat_duration=estimate_combat_duration)
                    actions += [SleepAction(2)]
                    self.action_squential(*actions)
            else:
                self.action_squential(MatchAction(template=ImageTemplate(character_symbol, threshold=0.7), unmatch_actions=[ClickAction(template='btn_cancel'), ClickAction(template='btn_close')]))


@register("quick_clean")
class QuickClean(ImageTask, TimeLimitTask):
    '''
    快速扫荡任务
    '''
    @staticmethod
    def valid(event_news: EventNews, args=None) -> tuple:
        if not event_news.dropItemNormal and event_news.dropItemHard:
            return QuickClean, [3]
        return QuickClean, args

    _pos = ((100, 80), (220, 80), (340, 80), (450, 80), (570, 80), (690, 80), (810, 80))
    def run(self, pos=0):
        if pos <= 0 or pos > len(QuickClean._pos):
            print(f"不支持的预设选项:{pos}")
            return
        # 分两个步骤1进入冒险图2执行快速扫荡
        self.set_progress(total_step=2)
        pref_pos = QuickClean._pos[pos - 1]
        # 进入冒险图
        self.action_squential(*_enter_adventure_actions())
        actions = [
            ClickAction(pos=(920, 144)),
            SleepAction(2),
            ClickAction(pos=pref_pos),
            SleepAction(1),
            ClickAction(pos=(815, 480)),
            SleepAction(2),
            IfCondition("symbol_restore_power", meet_actions=[
                    ClickAction(template='btn_cancel', timeout=1),
                    ThrowErrorAction("No Power!!!")
                ]),
            MatchAction(template="btn_challenge",matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction('btn_ok_blue'),
                ClickAction("btn_ok"),
                ClickAction("btn_not_store_next"),
            ], timeout=8),
            MatchAction(template='btn_skip_ok', matched_actions=[
                            ClickAction()], timeout=2, delay=0.1),
            SleepAction(1),
            MatchAction(template='btn_ok', matched_actions=[
                            ClickAction()], timeout=2, delay=0.1),
            SleepAction(1),
            MatchAction(template='btn_cancel', matched_actions=[
                                ClickAction(pos=(121,240)), SleepAction(1)], timeout=1),  # 限时商店
            ClickAction(pos=(580, 480)), # 取消按钮退出
        ]
        self.action_squential(*actions)


@register("adventure_daily")
class AdventureDaily(ImageTask):
    '''
    探险
    '''

    def _create_event_template(self) -> ImageTemplate:
        return ImageTemplate("symbol_adventure_event") | ImageTemplate("symbol_adventure_event_1") | ImageTemplate("symbol_adventure_event_special")

    def check_current_has_event(self):
        action = MatchAction(self._create_event_template(), timeout=3)
        self.action_squential(action, show_progress=False)
        return not action.is_timeout

    def adventure_scene_skip(self):
        center_pos = (self.define_width//2, self.define_height//2)
        self.action_squential(
            ClickAction(pos=(235,325)), # 选择左侧分支
            SleepAction(1.5),
            ClickAction(pos=(235, 325)), # 确认左侧分支
            SleepAction(1.5),
            ClickAction("btn_skip", timeout=5), # 点击跳过按钮
            SleepAction(5),
            ClickAction(pos=center_pos), # 确认奖励
            SleepAction(5),
            IfCondition("symbol_adventure_adventure_event", meet_actions=[CustomCallAction(self.adventure_scene_skip)]), # 循环确认
            show_progress=False)



    def run(self):
        receive_action = MatchAction('btn_adventure_receive',matched_actions=[ClickAction()], unmatch_actions=[ClickAction("btn_adventure")], timeout=10)
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction('btn_close')]),
            receive_action,
            title="确认一键归来"
        )
        if not receive_action.is_timeout:
            self.action_squential(
                MatchAction('btn_adventure_rerun', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(ImageTemplate('btn_adventure_skip') | ImageTemplate('select_branch_first')),
                        ClickAction(pos=(50, 300))
                    ], timeout=20),
                SleepAction(5),
                ClickAction('btn_adventure_depart'),
                SleepAction(2),
                ClickAction('btn_ok', timeout=3),
                SleepAction(2),
                ClickAction('btn_close', timeout=3),
                title="执行回收"
            )
        time.sleep(3)
        # try clear event in adventure scene
        while self.check_current_has_event():
            '''
            1. 确认画面中是否包含Event图标（有两种Event且配色不同） -> 2.
            2. 点击Event图标会移动画面并将Event事件放置于画面中间，点击进入Event页面 -> 3.
            3. 点击跳过按钮或等待动画结束，普通Event -> 4. 特殊Event -> 5.
            4. 点击画面确认由Event获取到的奖励内容 -> 6.
            5. 出现选择分支，点击任意分支经过一段动画演出 -> 4.
            6. 一段结束动画演出后回到最初画面 -> 1.
            '''
            center_pos = (self.define_width//2, self.define_height//2)
            self.action_squential(
                ClickAction(self._create_event_template()),
                SleepAction(1),
                ClickAction(pos=center_pos),
                SleepAction(1),
                ClickAction("btn_skip", timeout=5),
                # Special Event, 需要做一次选项选择并且消耗更长的时间通过动画
                MatchAction("select_branch_first", matched_actions=[ClickAction(), SleepAction(6), ClickAction(pos=center_pos), SleepAction(4)], timeout=5),
                # 另一种带选择的特殊Event
                IfCondition("symbol_adventure_adventure_event",
                            meet_actions=[CustomCallAction(self.adventure_scene_skip)]),
                SleepAction(6),
                ClickAction(pos=center_pos),
                SleepAction(5),
                title="清理Event"
            )
