from abc import ABCMeta, abstractmethod
from .constants import *
from pcrscript.actions import *
from typing import Iterable
import numpy as np
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
    
    def action_once(self, action: Action):
        action.bindTask(self)
        action.do(self.robot.driver.screenshot(), self.robot)
        return action.done()

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
            unmatch_actions=[ClickAction(template="btn_close"),ClickAction(template="btn_ok"), SleepAction(0.5)]),
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
            SleepAction(1),
            ClickAction(template="btn_luna_tower_entrance"),
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

class ActivitySaodang(BaseTask):
    '''
    剧情活动扫荡
    '''
    def run(self, hard_chapter=True, exhaust_power=True):
        if hard_chapter:
            self.robot._entre_advanture(difficulty=Difficulty.HARD, activity=True)
            actions = [
                MatchAction(template='btn_close', matched_actions=[
                            ClickAction(), SleepAction(2)], timeout=3),
                SleepAction(2),
                # 清困难本
                ClickAction(template='1-1', offset=(0, -20),
                            threshold=0.5, mode='binarization'),  # 点击第一个活动困难本
                MatchAction('btn_challenge', threshold=0.9*THRESHOLD),
            ]
            for _ in range(5):
                actions += [
                    SwipeAction((877, 330),(877, 330), 2000),
                    ClickAction(pos=(757, 330)),
                    ClickAction(template='btn_ok_blue'),
                    MatchAction(template='symbol_restore_power',
                                matched_actions=[
                                    ClickAction(pos=(370, 370)),
                                    SleepAction(2),
                                    ClickAction(pos=(680, 454)),
                                    SleepAction(2),
                                    ThrowErrorAction("No power!!!")],
                                timeout=1),
                    MatchAction(template='btn_skip_ok', matched_actions=[
                                ClickAction()], timeout=2, delay=0.1),
                    SleepAction(1),
                    MatchAction(template='btn_ok', matched_actions=[
                                ClickAction()], timeout=2, delay=0.1),
                    SleepAction(1),
                    MatchAction(template='btn_ok',
                                matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
                    MatchAction(template='btn_ok',
                                matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
                    MatchAction(template='btn_cancel', matched_actions=[
                                ClickAction(pos=(121,240)), SleepAction(1)], timeout=1),  # 限时商店
                    ClickAction(pos=(939, 251)),
                    SleepAction(2)
                ]
            actions += [
                ClickAction(pos=(666, 457)),
                SleepAction(2)
            ]
            # 高难
            actions += [
                ClickAction(template='very', offset=(0, -40),
                            threshold=0.6, mode='binarization')
            ]
            actions += _get_combat_actions()
            self.action_squential(*actions)
        if exhaust_power:
            if hard_chapter:
                self.robot._tohomepage()
            self.robot._entre_advanture(difficulty=Difficulty.NORMAL, activity=True)
            actions = []
            if not hard_chapter:
                actions += [
                    MatchAction(template='btn_close', matched_actions=[
                                ClickAction(), SleepAction(2)], timeout=3)
                ]
            actions += [
                ClickAction(template="15", offset=(0, -20),
                            threshold=0.6, mode="binarization"),
                SleepAction(2),
                *(getattr(self.robot, "_Robot__saodang_oneshot_actions")(duration=6000)),
                SleepAction(2)
            ]
            self.action_squential(*actions)
        self.action_squential(SleepAction(2))
        self.robot._get_quest_reward()
    
class ClearStory(BaseTask):
    '''
    清new剧情
    '''
    def run(self):
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
                else:
                    self.resolve_other_list()
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
                time.sleep(0.5)
                self.resolve_sub_list()
            else:
                # 返回上一级页面
                self.action_once(ClickAction(template='btn_back'))

    def resolve_other_list(self):
        self.resolve_sub_list()

    def skip_reading_page(self):
        self.action_squential(MatchAction(template='btn_skip_in_story', 
                                unmatch_actions=[ClickAction(template='symbol_menu_in_story')], 
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
        return self.robot._find_match_pos(screenshot, 'symbol_main_story')

    def in_sub_story_list(self, screenshot):
        return self.robot._find_match_pos(screenshot, 'symbol_sub_story')
    
    def in_story_tab(self, screenshot):
        return not self.robot._find_match_pos(screenshot, 'tab_story')
    
    def have_dialog(self, screenshot):
        return self.robot._find_match_pos(screenshot, 'symbol_dialog')

    def in_story_read_page(self, screenshot):
        return self.robot._find_match_pos(screenshot, 'symbol_menu_in_story')
    
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
            ret = self.robot._find_match_pos_list(self.robot.driver.screenshot(),template)
            if ret:
                # 根据y轴排序
                ret.sort(key=lambda pos: pos[1])
                return ret
            times += 1
            time.sleep(retry_interval)

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
    "activity_saodang": ActivitySaodang,
    "clear_story":ClearStory,
    }
