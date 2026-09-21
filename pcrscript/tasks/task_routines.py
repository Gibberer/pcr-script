from .image import ImageTask
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *
from ..templates import ImageTemplate

if TYPE_CHECKING:
    from pcrscript import Robot
    from ..strategist import Member

from .registry import register
from ._actions import _clean_oneshot_actions

@register("arena")
class Arena(ImageTask):
    '''
    竞技场
    '''

    def run(self):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(3),
            ClickAction(pos=(550, 411)),
            SleepAction(1),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(295, 336)),
            MatchAction(template='btn_ok', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(665, 186)),
            SleepAction(3),
            ClickAction(pos=(849, 454)),
            SleepAction(2),
            MatchAction(template='btn_arena_skip', matched_actions=[ClickAction()], timeout=8),
            MatchAction(['btn_next_step_small', 'btn_next_step'], matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
        )


@register("princess_arena")
class PrincessArena(ImageTask):
    '''
    公主竞技场
    '''

    def run(self):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(3),
            ClickAction(pos=(705, 411)),
            SleepAction(1),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(295, 336)),
            MatchAction(template='btn_ok', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=(665, 186)),
            SleepAction(3),
            ClickAction(pos=(849, 454)),
            SleepAction(1),
            ClickAction(pos=(849, 454)),
            SleepAction(1),
            ClickAction(pos=(849, 454)),
            SleepAction(2),
            MatchAction(template='btn_arena_skip', matched_actions=[ClickAction()], timeout=20),
            MatchAction(['btn_next_step_small', 'btn_next_step'], matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
        )


@register("research")
class Research(ImageTask):
    '''
    圣迹调查
    '''

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(pos=(740, 150)),
            MatchAction('symbol_research', matched_actions=[
                ClickAction(offset=(100, 200))], timeout=5),
        ]
        # 圣迹2级
        actions += [
            ClickAction(pos=(587, 300)),
            SleepAction(2),
            ClickAction(pos=(718, 146)),
            *_clean_oneshot_actions(),
            SleepAction(1),
            ClickAction(pos=(37, 33)),
            SleepAction(1)
        ]
        # 神殿2级
        actions += [
            ClickAction(pos=(800, 300)),
            SleepAction(2),
            ClickAction(pos=(718, 146)),
            *_clean_oneshot_actions(),
            SleepAction(1)
        ]
        self.action_squential(*actions)


@register("schedule")
class Schedule(ImageTask):
    '''
    日程表
    '''

    def run(self):
        self.action_squential(
            MatchAction(template="symbol_schedule", unmatch_actions=[
                ClickAction("icon_schedule"),
                ClickAction("btn_cancel")
            ]), #确认进入日程表页面
            SleepAction(1),
            ClickAction(pos=(650, 480)), # 一键自动
            SleepAction(5),
            MatchAction(template="symbol_schedule_completed_mark",
                        unmatch_actions=[
                            ClickAction(ImageTemplate("btn_ok_blue") | ImageTemplate("btn_ok", threshold=0.95)
                                        | ImageTemplate("btn_skip_ok") | ImageTemplate("btn_close", threshold=0.9),
                                        roi=(350,0,960,540))
                        ], delay=2),
            SleepAction(1),
            ClickAction(pos=(270, 480)), # 关闭
        )
