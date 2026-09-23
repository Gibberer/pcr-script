from .image import ImageTask
from typing import TYPE_CHECKING

from ..constants import *
from pcrscript.actions import *

if TYPE_CHECKING:
    from pcrscript import Robot

from .base import TimeLimitTask, EventNews
from .registry import register

@register("free_gacha", requires_home=True)
class FreeGacha(ImageTask, TimeLimitTask):
    '''
    抽取免费十连
    '''
    @staticmethod
    def valid(event_news:EventNews, args=None):
        if FreeGacha.event_valid(event_news.freeGacha):
            return FreeGacha, args

    def run(self, multi=False):
        draw_actions = [
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            MatchAction('btn_skip', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(pos=(50, 300))])
        ]
        self.action_squential(
            ClickAction(template='icon_gacha'),
            MatchAction('btn_setting_blue', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(template='btn_close')], timeout=5),
            MatchAction('btn_role_detail', unmatch_actions=[
                        ClickAction(template='btn_close'),ClickAction(template='icon_gacha')]),
            # 校验下是否有“免费”标签，没有的话就跳过
            IfCondition(condition_template="symbol_gacha_free", meet_actions=[
                ClickAction(pos=(871, 355)),
                SleepAction(0.5),
                IfCondition("symbol_reward_select", meet_actions=[
                    ClickAction(pos=(600, 265)),
                    SleepAction(0.5),
                    ClickAction(template="btn_ok_blue", timeout=5),
                    SleepAction(0.5),
                    ClickAction(template="btn_close"),
                    SleepAction(0.5),
                    ClickAction(pos=(871, 355)),
                ]), # 处理附奖扭蛋必须选择的情况
                *draw_actions,
                MatchAction('btn_ok', matched_actions=[ClickAction()],
                            unmatch_actions=[
                            ClickAction(pos=(50, 300)),
                            IfCondition('btn_draw_again', meet_actions=[
                                ClickAction(template='btn_draw_again'),
                                *draw_actions
                            ]) if multi else IfCondition('btn_cancel', meet_actions=[
                                ClickAction(template='btn_cancel'),
                                SkipAction()
                            ])
                            ]),
                MatchAction('btn_setting_blue', matched_actions=[
                            ClickAction()], timeout=5),
            ]),
        )


@register("normal_gacha", requires_home=True)
class NormalGacha(ImageTask):
    '''
    普通扭蛋
    '''

    def run(self):
        self.action_squential(
            ClickAction(template='icon_gacha'),
            MatchAction('btn_setting_blue', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(template='btn_close')], timeout=3),
            MatchAction('btn_role_detail', unmatch_actions=[
                        ClickAction(template='btn_close')]),
            ClickAction(pos=(877, 72)),
            MatchAction('btn_ok_blue',
                        matched_actions=[ClickAction()],
                        unmatch_actions=[ClickAction(pos=(722, 347))]),
            MatchAction('btn_ok',
                        matched_actions=[ClickAction()],
                        unmatch_actions=[ClickAction(pos=(50, 300)),]),
            MatchAction('btn_setting_blue', matched_actions=[
                        ClickAction()], timeout=5),
        )
