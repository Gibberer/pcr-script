from abc import ABCMeta, abstractmethod
from .constants import *
from pcrscript.actions import *
from typing import Iterable


class BaseTask(metaclass=ABCMeta):

    def __init__(self, robot):
        self.robot = robot
        self.define_width = BASE_WIDTH
        self.define_height = BASE_HEIGHT

    
    def action_squential(self, *actions:Iterable[Action]):
        for action in actions:
            action.bindTask(self)
        self.robot._action_squential(*actions)

    @abstractmethod
    def run(self, *args):
        pass


class GetGift(BaseTask):
    '''
    获取礼物
    '''
    
    def run(self):
        self.action_squential(
            SleepAction(1),
            ClickAction(template='gift'),
            SleepAction(3),
            MatchAction('btn_all_rec', matched_actions=[
                        ClickAction()], timeout=3),
            MatchAction('btn_ok_blue', matched_actions=[
                        ClickAction()], timeout=3),
            MatchAction('btn_ok', matched_actions=[ClickAction()], timeout=3),
            MatchAction('btn_cancel', matched_actions=[
                        ClickAction()], timeout=3)
        )

class ChouShiLian(BaseTask):
    '''
    抽取免费十连
    '''

    def run(self, multi=False):
        draw_actions = [
            ClickAction(template='btn_ok_blue'),
            MatchAction('btn_skip', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(pos=(50, 300))])
        ]
        self.action_squential(
            ClickAction(template='niudan'),
            MatchAction('btn_setting_blue', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(template='btn_close')], timeout=5),
            MatchAction('btn_role_detail', unmatch_actions=[
                        ClickAction(template='btn_close')]),
            ClickAction(pos=(871, 355)),
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
        )


class NormalGacha(BaseTask):
    '''
    普通扭蛋
    '''
    def run(self):
        self.action_squential(
            ClickAction(template='niudan'),
            MatchAction('btn_setting_blue', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(template='btn_close')], timeout=5),
            MatchAction('btn_role_detail', unmatch_actions=[
                        ClickAction(template='btn_close')]),
            ClickAction(pos=(877, 72)),
            SleepAction(2),
            ClickAction(pos=(722, 347)),
            ClickAction(template='btn_ok_blue'),
            MatchAction('btn_ok', matched_actions=[ClickAction()],
                        unmatch_actions=[
                        ClickAction(pos=(50, 300)),
                        ]),
            MatchAction('btn_setting_blue', matched_actions=[
                        ClickAction()], timeout=5),
        )


class RoleIntensify(BaseTask):
    '''
        角色强化默认前五个
    '''

    def run(self):
        self.action_squential(
            ClickAction(template='tab_role'),
            SleepAction(1),
            MatchAction('role_symbol'),
            SleepAction(1),
            ClickAction(pos=(177, 142)),
            SleepAction(1),
            MatchAction('role_intensify_symbol'),
            SleepAction(1)
        )
        # 已经进入强化页面
        actions = []
        for _ in range(5):
            actions.append(ClickAction(pos=(247, 337)))
            actions.append(MatchAction('btn_cancel', matched_actions=[
                           ClickAction(offset=(230, 0)), SleepAction(6)], timeout=3))
            actions.append(MatchAction('btn_ok', matched_actions=[
                           ClickAction(), SleepAction(3)], timeout=3))
            actions.append(ClickAction(pos=(374, 438)))
            actions.append(MatchAction(template='btn_ok_blue', matched_actions=[ClickAction(
            )], unmatch_actions=[ClickAction(template='btn_ok')], timeout=5, threshold=1.2*THRESHOLD))
            actions.append(SleepAction(1))
            actions.append(ClickAction(pos=(938, 268)))
            actions.append(SleepAction(1))
        self.action_squential(*actions)

class GuildLike(BaseTask):

    def run(self, no=1):
        x = 829
        y = 110 * (no - 1) + 196
        self.action_squential(
            SleepAction(2),
            MatchAction(template="guild", matched_actions=[ClickAction()],
            unmatch_actions=[ClickAction(template="btn_close"), SleepAction(0.5)]),
            SleepAction(2),
            MatchAction("guild_symbol"),
            SleepAction(1),
            ClickAction(pos=(234, 349)),
            SleepAction(3),
            ClickAction(pos=(x, y)),
            MatchAction("btn_ok_blue", matched_actions=[
                        ClickAction()], timeout=5),
        )



# 声明任务对应的配置任务名
taskKeyMapping = {
    "get_gift": GetGift,
    "choushilian": ChouShiLian,
    "normal_gacha": NormalGacha,
    "role_intensify": RoleIntensify,
    "guild_like": GuildLike
    }





