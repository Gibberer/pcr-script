from abc import ABCMeta, abstractmethod
from .constants import *
from pcrscript.actions import *
from typing import Iterable
import time


def _get_combat_actions(check_auto=False, combat_duration=35):
    actions = []
    actions.append(ClickAction(template='btn_challenge'))
    actions.append(SleepAction(1))
    actions.append(ClickAction(template='btn_combat_start'))
    actions.append(SleepAction(5))
    if check_auto:
        actions.append(MatchAction(template='btn_caidan', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
    actions.append(SleepAction(combat_duration))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'), ClickAction(pos=(200, 250))]))
    actions.append(SleepAction(1))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel')]))
    return actions

    

class BaseTask(metaclass=ABCMeta):

    def __init__(self, robot):
        self.robot = robot
        self.define_width = BASE_WIDTH
        self.define_height = BASE_HEIGHT

    def action_squential(self, *actions: Iterable[Action]):
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


class LunaTowerSaodang(BaseTask):

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=(50, 300))]),
            SleepAction(2),
            ClickAction(pos=(320, 425)),
            MatchAction(template="symbol_luna_tower"),
            SleepAction(2),
            SwipeAction(start=(890, 376), end=(890, 376), duration=2000),
            ClickAction(pos=(815, 375)),
            ClickAction(template='btn_ok_blue'),
            MatchAction(template='btn_skip_ok', matched_actions=[ClickAction()], timeout=2, delay=0.1),
            SleepAction(1),
            MatchAction(template='btn_ok', matched_actions=[ClickAction()], timeout=2, delay=0.1),
            SleepAction(1),
            MatchAction(template='btn_ok', matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_ok', matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_cancel', matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            ]
        self.action_squential(*actions)

class CommonAdventure(BaseTask):
    '''
    通用的过图任务，执行内容为：
    1. 寻找当前人物的位置
    2. 点击人物
    3. 进入战斗页面，开始战斗直到结束
    4. -> 1 循环
    '''

    def run(self, charactor_symbol="peco", estimate_combat_duration=30):
        '''
        :param charactor_symbol 当前使用角色在冒险地图上的图片特征（取脸部或身体部分即可，不要截到背景）
        :param estimate_combat_duration 预估一次战斗的时间（正确设置可以减少cpu的消耗)
        '''
        while True:
            screenshot = self.robot.driver.screenshot()
            pos = self.robot._find_match_pos(screenshot, charactor_symbol, threshold=0.7)
            if pos :
                # 通过图片匹配的位置信息是真实的坐标，不需要转换
                self.robot.driver.click(pos[0], pos[1] + self.robot.deviceheight * 0.1)
                match_action = MatchAction(template='btn_challenge', timeout=5)
                self.action_squential(match_action)
                if not match_action.is_timeout:
                    actions = _get_combat_actions(combat_duration=estimate_combat_duration)
                    actions += [SleepAction(2)]
                    self.action_squential(*actions)
            else:
                self.action_squential(MatchAction(template='peco', threshold=0.7, unmatch_actions=[ClickAction(template='btn_cancel'), ClickAction(template='btn_close')]))

class QuickSaodang(BaseTask):
    '''
    快速扫荡任务
    '''
    _pos = ((100, 80), (220, 80), (340, 80), (450, 80), (570, 80), (690, 80), (810, 80))
    def run(self, pos=0):
        if pos <= 0 or pos > len(QuickSaodang._pos):
            print(f"不支持的预设选项:{pos}")
            return
        pref_pos = QuickSaodang._pos[pos - 1]
        # 进入冒险图
        self.robot._entre_advanture()
        actions = [
            ClickAction(pos=(920, 144)),
            SleepAction(1),
            ClickAction(pos=pref_pos),
            SleepAction(0.5),
            ClickAction(pos=(815, 480)),
            MatchAction(template="btn_challenge",matched_actions=[ClickAction()], unmatch_actions=[
                IfCondition("symbol_restore_power", meet_actions=[
                    ThrowErrorAction("No Power!!!")
                ], unmeet_actions=[
                    MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()],timeout=0.1)
                ])
            ]),
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

# 声明任务对应的配置任务名
taskKeyMapping={
    "get_gift": GetGift,
    "choushilian": ChouShiLian,
    "normal_gacha": NormalGacha,
    "role_intensify": RoleIntensify,
    "guild_like": GuildLike,
    "luna_tower_saodang": LunaTowerSaodang,
    "common_adventure": CommonAdventure,
    "quick_saodang": QuickSaodang,
    }
