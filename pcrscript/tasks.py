from abc import ABCMeta, abstractmethod
import time
import copy
from typing import TYPE_CHECKING
import collections
import numpy as np
import sqlite3
import re
from typing import Optional
from dataclasses import dataclass, field
import os

from .constants import *
from pcrscript.actions import *
from .templates import Template,ImageTemplate,CharaIconTemplate,BrightnessTemplate
from .strategist import Member

if TYPE_CHECKING:
    from pcrscript import Robot

_registedTasks = {}

def find_taskclass(name:str)->'BaseTask':
    '''
    根据名称获取task类
    '''
    return _registedTasks.get(name, None)

def register(name):
    def wrap(cls):
        if name in _registedTasks:
            raise Exception(f"Task:{name} already registed.")
        _registedTasks[name] = cls
        cls.name = name
        return cls
    return wrap

#======一些可复用task序列

def _combat_actions(check_auto=False, combat_duration=35, interval=1):
    actions = []
    actions.append(ClickAction(template='btn_challenge'))
    actions.append(SleepAction(1))
    actions.append(ClickAction(template='btn_combat_start'))
    actions.append(MatchAction(template='btn_blue_settle',matched_actions=[ClickAction(),SleepAction(1),ClickAction(template='btn_combat_start')], timeout=5))
    actions.append(IfCondition('symbol_restore_power', 
                               meet_actions=[
                                ClickAction(pos=(370, 370)),
                                SleepAction(2),
                                ClickAction(pos=(680, 454)),
                                SleepAction(2),
                                ThrowErrorAction("No power!!!")]))
    if check_auto:
        actions.append(MatchAction(template='btn_menu_text', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
    actions.append(SleepAction(combat_duration))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'), ClickAction(pos=(200, 250))], delay=interval))
    actions.append(SleepAction(3))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'),ClickAction(template='btn_ok_blue')]))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'),ClickAction(template='btn_ok_blue')], timeout=3))
    return actions       

def _clean_oneshot_actions(duration=0):
    return [
            MatchAction('btn_challenge'),
            SwipeAction((877, 360), (877, 360), duration) if duration > 0 else SleepAction(0.5),
            ClickAction(pos=(757, 360)),
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            SleepAction(0.5),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            ClickAction(template='btn_ok'),
            SleepAction(1),
            MatchAction(template='btn_ok',
                        matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_ok',
                        matched_actions=[ClickAction(), SleepAction(1)], timeout=1),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=1),  # 限时商店
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=1),  # 可能有二次弹窗
            SleepAction(2),
            ClickAction(pos=(666, 457))
        ]

def _enter_adventure_actions(difficulty=Difficulty.NORMAL, campaign=False):
    actions = []
    actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'), ClickAction(pos=(15, 200))]))
    actions.append(SleepAction(2))
    if campaign:
        actions.append(MatchAction(template=['story_campaign_symbol', 'story_campaign_reprint_symbol'], matched_actions=[ClickAction()]))
    else:
        actions.append(ClickAction(ImageTemplate('btn_main_plot',threshold=0.8*THRESHOLD)))
    actions.append(SleepAction(2))
    unmatch_actions = [ClickAction(ImageTemplate('btn_close', threshold=0.6)),
                       ClickAction('btn_skip_blue'),
                       ClickAction('btn_novocal_blue'),
                       ClickAction('symbol_menu_in_story'),
                       ClickAction('btn_skip_in_story')]
    if campaign:
        unmatch_actions += [
            IfCondition(ImageTemplate('symbol_campaign_home',threshold=0.8*THRESHOLD),
                        meet_actions=[ClickAction(pos=(560, 170))],
                        unmeet_actions=[ClickAction(pos=(15, 200))])]
    if difficulty == Difficulty.NORMAL:
        unmatch_actions = [ClickAction(
            template=ImageTemplate('btn_normal', threshold=0.9))] + unmatch_actions
        actions.append(MatchAction('btn_normal_selected',
                                   unmatch_actions=unmatch_actions))
    elif difficulty == Difficulty.HARD:
        unmatch_actions = [ClickAction(
            template=ImageTemplate("btn_hard", threshold=0.9))] + unmatch_actions
        actions.append(MatchAction('btn_hard_selected',
                                   unmatch_actions=unmatch_actions))
    else:
        unmatch_actions = [ClickAction(
            template=ImageTemplate("btn_very_hard", threshold=0.9))] + unmatch_actions
        actions.append(MatchAction('btn_very_hard_selected',
                                   unmatch_actions=unmatch_actions))
    return actions

#======

class BaseTask(metaclass=ABCMeta):

    def __init__(self, robot:'Robot'):
        self.robot = robot
        self.driver = robot.driver
        self.define_width = BASE_WIDTH
        self.define_height = BASE_HEIGHT
        self.num_step = 1
        self.total_step = 1
        self.show_progress = True
    
    def set_progress(self, total_step=1, num_step=1, show_progress=True):
        self.total_step = total_step
        self.num_step = num_step
        self.show_progress = show_progress

    def action_squential(self, *actions: Action, show_progress:bool=None, net_error_check:bool=True, title=None):
        for action in actions:
            action.bindTask(self)
        if show_progress is None:
            show_progress = self.show_progress
        self.robot.action_squential(*actions, net_error_check=net_error_check, show_progress=show_progress, progress_index=self.num_step, total_step=self.total_step, title=title)
        self.num_step += 1
    
    def action_once(self, action: Action):
        action.bindTask(self)
        action.do(self.robot.driver.screenshot(), self.robot)
        return action.done()

    def template_match(self, screenshot, template:Template):
        template.set_define_size(self.define_width, self.define_height)
        return template.match(screenshot)
    
    def in_region(self, r, pos):
        return (r[0] < pos[0] < r[2]) and (r[1] < pos[1] < r[3])
    
    def center_region(self, r):
        return (int((r[0]+r[2])/2), int((r[1]+r[3])/2))
    
    def adapted_region(self, r, w, h):
        hscale = w/self.define_width
        vscale = h/self.define_height
        return (int(r[0]*hscale), int(r[1]*vscale), int(r[2]*hscale), int(r[3]*vscale))

    def __call__(self, *args, **kwds):
        return self.run(*args)

    @abstractmethod
    def run(self, *args):
        pass

@dataclass
class Event:
    startTimestamp: float
    endTimestamp: float
    name: str
    extras: dict = field(default_factory=lambda:{})

    def __str__(self) -> str:
        start = time.localtime(self.startTimestamp)
        end = time.localtime(self.endTimestamp)
        return (
            f"{self.name}:{start.tm_mon}/{start.tm_mday} - {end.tm_mon}/{end.tm_mday}"
        )

@dataclass
class EventNews:
    freeGacha: Optional[Event] = None  # 免费扭蛋
    tower: Optional[Event] = None  # 露娜塔
    dropItemNormal: Optional[Event] = None  # 普通关卡掉落活动
    dropItemHard: Optional[Event] = None # 困难关卡掉落活动
    hatsune: Optional[Event] = None  # 剧情活动
    clanBattle: Optional[Event] = None  # 公会战
    secretDungeon: Optional[Event] = None # 特别地下城

class TimeLimitTask(BaseTask):
    '''
    时限任务
    '''
    
    @staticmethod
    @abstractmethod
    def valid(event_news:EventNews, args:list=None)->tuple[BaseTask, list]:
        pass
    
    @staticmethod
    def event_valid(event: Event):
        if not event:
            return False
        return event.startTimestamp <= time.time() <= event.endTimestamp

    @staticmethod
    def event_first_day(event: Event):
        if not event:
            return False
        current_time = time.time()
        if current_time > event.startTimestamp:
            return (
                time.localtime(current_time).tm_mday
                == time.localtime(event.startTimestamp).tm_mday
            )
        return False
    
    @staticmethod
    def event_last_day(event: Event):
        if not event:
            return False
        return 0 < event.endTimestamp - time.time() < 86400

#======以下部分为具体task列表,其中task在配置文件中的名称为@register("name")的name部分。
@register("tohomepage")
class ToHomePage(BaseTask):
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

@register("get_gift")
class GetGift(BaseTask):
    '''
    获取礼物
    '''

    def run(self, exclude_stamina=True):
        actions = []
        if not exclude_stamina:
            actions = [
                SleepAction(1),
                ClickAction(template='gift'),
                SleepAction(3),
                MatchAction('btn_all_rec', matched_actions=[
                        ClickAction(pos=(360,480)),SleepAction(0.5),ClickAction()], timeout=3),
                MatchAction('btn_ok_blue', matched_actions=[
                        ClickAction()], timeout=3),
                MatchAction('btn_ok', matched_actions=[ClickAction()], timeout=3),
                MatchAction('btn_cancel', matched_actions=[
                        ClickAction()], timeout=3)
            ]
        else:
            actions = [
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
            ]
        self.action_squential(*actions)

@register("free_gacha")
class FreeGacha(TimeLimitTask):
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

@register("normal_gacha")
class NormalGacha(BaseTask):
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

@register("luna_tower_clean")
class LunaTowerClean(TimeLimitTask):
    '''
    露娜塔 回廊扫荡
    '''

    @staticmethod
    def valid(event_news: EventNews, args=None) -> tuple:
        if LunaTowerClean.event_valid(event_news.tower) and not LunaTowerClean.event_first_day(event_news.tower):
            return LunaTowerClean, args

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=(50, 300))]),
            SleepAction(1),
            ClickAction(template="btn_luna_tower_entrance"),
            MatchAction(template="symbol_luna_tower"),
            SleepAction(2),
            MatchAction(template='symbol_luna_tower_lock',matched_actions=[ThrowErrorAction("回廊未解锁")],timeout=5),
            ClickAction(pos=(815, 375)),
            SleepAction(0.5),
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
@register("common_adventure")
class CommonAdventure(BaseTask):
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
@register("shop_buy")
class ShopBuy(BaseTask):
    '''
    商店购买药水、道具等
    '''

    def run(self, rule:dict):
        '''
        rule: 购买规则
        '''
        actions = []
        # 首先进入商店页
        actions.append(ClickAction(template='shop'))
        actions.append(MatchAction(template='symbol_shop', unmatch_actions=[
                       ClickAction(pos=(77, 258)), ClickAction(template='shop')]))
        actions.append(SleepAction(1))
        tabs = collections.defaultdict(dict)
        for key, value in rule.items():
            if isinstance(key, int):
                tabs[key]['items'] = value
            else:
                tabs[int(key.split("_")[0])].update(value)
        Item = collections.namedtuple(
            "Item", ["pos", "threshold"], defaults=[0, -1])
        times = collections.defaultdict(int)
        item_total_count = collections.defaultdict(lambda:-1)
        for key in tabs:
            value = tabs[key]
            tabs[key] = []
            items = tabs[key]
            if 'items' in value:
                for normal_item in value['items']:
                    items.append(Item(normal_item))
            items.sort(key=lambda item: item.pos)
            if 'time' in value:
                times[key] = value['time']
            if 'total_item_count' in value:
                item_total_count[key] = value['total_item_count']
        for tab, items in tabs.items():
            tab_main_actions = []

            tab_actions = []

            line_count = 4
            line = 1
            slow_swipe = False
            for item in items:
                if item.threshold > 0:
                    slow_swipe = True
                    break
            last_line = 100000
            if slow_swipe:
                last_line = item_total_count[tab]
            for item in items:
                swipe_time = 0
                if item.pos > line * line_count:
                    for _ in range(int((item.pos - line * line_count - 1) / line_count) + 1):
                        if slow_swipe:
                            tab_actions += [
                                SwipeAction(start=(580, 377),
                                            end=(580, 114), duration=5000),
                                SleepAction(1)
                            ]
                        else:
                            tab_actions += [
                                SwipeAction(start=(580, 380),
                                            end=(580, 180), duration=300),
                                SleepAction(1)
                            ]
                        line += 1
                        swipe_time += 1
                if tab in (1, 9) and item.pos < 0:
                    click_pos = (860,126) # 全选按钮
                elif line == last_line:
                    click_pos = SHOP_ITEM_LOCATION_FOR_LAST_LINE[(
                        item.pos - 1) % line_count]
                else:
                    click_pos = SHOP_ITEM_LOCATION[(item.pos - 1) % line_count]

                if item.threshold <= 0:
                    if tab in (1, 9):
                        tab_actions += [
                            ClickAction(pos=(690, 125)),
                            SleepAction(0.5),
                        ]
                    tab_actions += [
                        ClickAction(pos=click_pos),
                        SleepAction(0.1)
                    ]
                else:
                    def condition_function(screenshot, item, click_pos):
                        return False

                    tab_actions += [
                        SleepAction(swipe_time * 1 + 1),
                        CustomIfCondition(condition_function, item, click_pos, meet_actions=[
                                          ClickAction(pos=click_pos)]),
                        SleepAction(0.8),
                    ]
            tab_actions += [
                ClickAction(pos=(700, 438)),
                SleepAction(0.2),
                MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()], timeout=2),
                SleepAction(1.5),
                MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()], timeout=2),
                SleepAction(1.5)
            ]
            tab_main_actions += tab_actions
            if times[tab]:
                for _ in range(times[tab] - 1):
                    copy_tab_actions = [
                        ClickAction(pos=(550, 440)),
                        SleepAction(0.2),
                        ClickAction(template='btn_ok_blue'),
                        SleepAction(1)
                    ]
                    copy_tab_actions += copy.deepcopy(tab_actions)
                    tab_main_actions += copy_tab_actions
            actions += [
                ClickAction(pos=SHOP_TAB_LOCATION[tab - 1]),
                SleepAction(1)
            ]
            actions += tab_main_actions
        self.action_squential(*actions)
@register("quick_clean")
class QuickClean(TimeLimitTask):
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
@register("clear_campaign_first_time")
class ClearCampaignFirstTime(TimeLimitTask):
    '''
    剧情活动首次过图
    '''

    @staticmethod
    def valid(event_news: EventNews, args=None) -> tuple:
        if ClearCampaignFirstTime.event_first_day(event_news.hatsune):
            return ClearCampaignFirstTime, args

    def run(self, exhaust_power=False):
        self.total_step = '∞'
        self.action_squential(*_enter_adventure_actions(difficulty=Difficulty.NORMAL, campaign=True))
        pre_pos = (-100,-100)
        step = 0
        retry_count = 0
        while True:
            time.sleep(1)
            screenshot = self.robot.driver.screenshot()
            self._ignore_niggled_scene(screenshot)
            character_pos = self.template_match(screenshot, ImageTemplate('character', threshold=0.7))
            if not character_pos:
                # 点击屏幕重新判断
                self.action_once(ClickAction(pos=(20, 100)))
                pos = self.template_match(screenshot, ImageTemplate("symbol_campaign_home"))
                if pos:
                    self.action_once(ClickAction(pos=(560, 170)))
                continue
            else:
                lock_ret = self.template_match(screenshot, ImageTemplate('symbol_lock'))
                if not lock_ret:
                    print('未发现解锁符号，执行正常活动清理步骤')
                    break
                if self._is_same_pos(pre_pos, character_pos):
                    # 位置相同，说明下一关需要挑战boss关卡
                    print(f"位置未发生变化可能下一步是{'普通'if step == 0 else '困难'}boss关卡{f'(重试{retry_count}次)' if retry_count > 0 else ''}")
                    if step == 0:
                        # 普通关卡
                        self.action_squential(ClickAction(template=ImageTemplate('normal', threshold=0.7), timeout=5))
                    else:
                        self.action_squential(ClickAction(template=ImageTemplate('hard', threshold=0.7), timeout=5))
                    match_action = MatchAction(template='btn_challenge', timeout=5)
                    self.action_squential(match_action)
                    if not match_action.is_timeout:
                        actions = _combat_actions(combat_duration=3, interval=0.2)
                        self.action_squential(*actions)
                        if step == 0:
                            # 移动到困难章节
                            time.sleep(5)
                            self.action_squential(MatchAction('btn_hard_selected',
                                                unmatch_actions=[ClickAction(template="btn_hard"),
                                                    ClickAction(pos=(20, 100))]))
                            time.sleep(3)
                            step = 1
                        pre_pos = character_pos
                        retry_count = 0
                    else:
                        if retry_count >= 2:
                            pre_pos = (-1, -1)
                            retry_count = 0
                        else:
                            retry_count += 1
                else:
                    self.robot.driver.click(character_pos[0], character_pos[1] + self.robot.deviceheight * 0.1)
                    match_action = MatchAction(template='btn_challenge', timeout=5)
                    self.action_squential(match_action)
                    if not match_action.is_timeout:
                        actions = _combat_actions(combat_duration=15)
                        actions += [SleepAction(2)]
                        self.action_squential(*actions)
                        pre_pos = character_pos
        # 首次过图处理完毕，执行正常活动清体力任务步骤
        ToHomePage(self.robot).run()
        CampaignClean(self.robot).run(hard_chapter=True, exhaust_power=exhaust_power)
        

    def _is_same_pos(self, pre_pos, pos):
        px,py = pre_pos
        x,y = pos
        return  (x - 5 <= px <= x + 5) and (y - 5 <= py <= y + 5)
    
    def _ignore_niggled_scene(self, screenshot):
        templates = [
            'btn_close',
            'btn_skip_blue',
            'btn_novocal_blue',
            'symbol_menu_in_story',
            'btn_skip_in_story',
            'btn_blue_settle',
            'btn_cancel',
        ]
        for template in templates:
            pos = self.template_match(screenshot, ImageTemplate(template))
            if pos:
                self.robot.driver.click(*pos)
                break
@register("campaign_clean")
class CampaignClean(TimeLimitTask):
    '''
    剧情活动扫荡
    '''
    @staticmethod
    def valid(event_news: EventNews, args: list = None) -> tuple[BaseTask, list]:
        if CampaignClean.event_valid(event_news.hatsune):
            if CampaignClean.event_first_day(event_news.hatsune):
                return ClearCampaignFirstTime, None
            elif event_news.hatsune.extras["original_event_id"] != 0 and event_news.dropItemNormal:
                return None
            else:
                return CampaignClean, args


    def run(self, hard_chapter=True, exhaust_power=True):
        '''
        Parameters:
            hard_chapter: 是否扫荡困难关卡
            exhaust_power: 是否在普通关卡中用光所有体力
        '''
        self.total_step = '∞'
        if hard_chapter:
            self.action_squential(*_enter_adventure_actions(difficulty=Difficulty.HARD, campaign=True))
            actions = [
                MatchAction(template='btn_close', matched_actions=[
                            ClickAction(), SleepAction(2)], timeout=3),
                SleepAction(2),
                # 清困难本
                ClickAction(template=ImageTemplate('1-1', threshold=0.6, mode='binarization'), offset=(0, -20)),  # 点击第一个活动困难本
                MatchAction(ImageTemplate('btn_challenge', threshold=0.9*THRESHOLD)),
            ]
            # 1-1可能误识别为其他关卡
            for _ in range(4):
                actions += [
                    ClickAction(pos=(33, 275)),
                    SleepAction(0.5)
                ]
            for _ in range(5):
                actions += [
                    ClickAction(pos=(757, 330)),
                    SleepAction(0.5),
                    ClickAction(template='btn_ok_blue', timeout=10), # 加入超时防止卡住（可能不能稳定识别1-1）
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
                    IfCondition("btn_challenge", meet_actions=[], 
                                unmeet_actions=[MatchAction(template='btn_cancel', matched_actions=[ClickAction(), SleepAction(1)], timeout=1)]), # 限时商店
                    ClickAction(pos=(939, 251)),
                    SleepAction(2)
                ]
            actions += [
                ClickAction(pos=(666, 457)),
                SleepAction(2)
            ]
            # 高难
            actions += [
                ClickAction(template=ImageTemplate('very', threshold=0.6, mode='binarization'), 
                            offset=(0, -40), timeout=5),
                ClickAction(pos=(860,270)), # 如果timeout尝试点击该位置   
                SleepAction(1),         
            ]
            actions += _combat_actions(combat_duration=3, interval=0.5)
            self.action_squential(*actions)
        if exhaust_power:
            if hard_chapter:
                ToHomePage(self.robot).run()
            self.action_squential(*_enter_adventure_actions(difficulty=Difficulty.NORMAL, campaign=True))
            actions = []
            if not hard_chapter:
                actions += [
                    MatchAction(template='btn_close', matched_actions=[
                                ClickAction(), SleepAction(2)], timeout=3)
                ]
            actions += [
                ClickAction(template=ImageTemplate('15', threshold=0.6, mode='binarization'),
                            offset=(0, -20),timeout=10),
                SleepAction(1),
                IfCondition("character", meet_actions=[ClickAction("character"), SleepAction(1)]), # 找不到对应关卡符号时，使用人物标记查找
                *_clean_oneshot_actions(duration=6000),
                SleepAction(2)
            ]
            self.action_squential(*actions)
        self.action_squential(SleepAction(2))
        # 领取任务
        self.action_squential(
            SleepAction(1),
            MatchAction(template=ImageTemplate('symbol_campaign_quest') | ImageTemplate('symbol_campaign_quest_1'),
                        unmatch_actions=[ClickAction(pos=(5, 150)), 
                                         ClickAction(template='quest'),
                                         ClickAction(template="btn_cancel"),
                                         ClickAction(template="symbol_guild_down_arrow", offset=(0, 70))]),
            SleepAction(3),
            MatchAction('btn_all_rec', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_ok', matched_actions=[ClickAction()], timeout=3),
            MatchAction('btn_cancel', matched_actions=[
                        ClickAction()], timeout=3)
        )

@register('campaign_reward_exchange')
class CampaignRewardExchange(TimeLimitTask):
    '''
    活动收尾：
    1. 消耗所有Boss挑战券
    2. 观看活动剧情
    3. 观看信赖度剧情（如果存在）
    4. 交换所有讨伐券
    '''

    @staticmethod
    def valid(event_news: EventNews, args: list = None) -> tuple[BaseTask, list]:
        if CampaignRewardExchange.event_last_day(event_news.hatsune):
            return CampaignRewardExchange, args
    
    def _story(self):
        entry_action = MatchAction('btn_campaign_story_entry', matched_actions=[ClickAction()] ,timeout=5)
        self.action_squential(
            MatchAction(ImageTemplate('symbol_campaign_home') & ImageTemplate('btn_campaign_story_entry'), unmatch_actions=[
                ClickAction(pos=(33,31))
            ], delay=0.5, timeout=15),
            entry_action,
            SleepAction(3),
            title="剧情奖励"
        )
        if entry_action.is_timeout:
            self.action_squential(
                ClickAction(pos=(870, 345)),
                SleepAction(3),
                title="剧情入口超时点击"
            )
        screenshot = self.driver.screenshot()
        symbol_new = self.template_match(screenshot, ImageTemplate('symbol_new_campaign_story'))
        if symbol_new:
            self.driver.click(symbol_new[0], symbol_new[1] + int(screenshot.shape[0]*.05))
            con_match_times = 0
            while True:
                time.sleep(1)
                screenshot = self.driver.screenshot()
                if ignore := self.template_match(screenshot, ImageTemplate('btn_close', roi=(262,115,687,434))):
                    self.driver.click(*ignore)
                    continue
                if novocal := self.template_match(screenshot, ImageTemplate('btn_novocal_blue')):
                    self.driver.click(*novocal)
                    continue
                if ignore := self.template_match(screenshot, ImageTemplate('btn_close') | ImageTemplate('btn_skip_blue')):
                    self.driver.click(*ignore)
                    continue
                if self.template_match(self.driver.screenshot(), ImageTemplate('symbol_menu_in_story')):
                    self.action_squential(MatchAction(template='btn_skip_in_story', 
                                unmatch_actions=[ClickAction(template='symbol_menu_in_story'), ClickAction(template='select_branch_first'),], 
                                matched_actions=[ClickAction()],
                                timeout=5))
                    continue
                if self.template_match(screenshot, ImageTemplate('symbol_campaign_home')):
                    if (con_match_times := con_match_times+1) > 2:
                        # 完成一次剧情读取会先显示活动主界面之后再弹出新的剧情引导弹窗，避免恰好在弹出弹窗前截图导致的误判断认为剧情已全部阅读完毕
                        break
                else:
                    con_match_times = 0
                self.action_once(ClickAction(pos=(250, 60)))
        else:
            self.action_once(ClickAction('btn_close'))
    
    def _hard(self):
        self.action_squential(
            *_enter_adventure_actions(difficulty=Difficulty.HARD, campaign=True),
            # btn_challenge 的额外匹配用于当匹配不到困难标签时手动点击困难保证任务可以继续进行
            ClickAction(template=ImageTemplate('hard', threshold=0.6, mode='binarization') | ImageTemplate('btn_challenge'), offset=(0, -40)),
            SleepAction(1),
            *_clean_oneshot_actions(duration=6000),
            title="清空券"
        )
    
    def _exchange(self):
        self.action_squential(
            MatchAction('btn_reward_exchange', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template="btn_close")]),
            MatchAction('symbol_reward_exchange'),
            SleepAction(1),
            ClickAction(pos=(830,380)),
            SleepAction(1),
            title="交换阶段"
        )
        while True:
            time.sleep(0.5)
            screenshot = self.driver.screenshot()
            if self.template_match(screenshot, ImageTemplate('symbol_reward_exchange')):
                if self.template_match(screenshot, ~BrightnessTemplate((740, 336, 920, 415), 200)):
                    break
                # 抽取下一轮
                self.action_once(ClickAction(pos=(830,380)))
                continue
            if reset := self.template_match(screenshot, ImageTemplate('btn_reset_reward')):
                self.driver.click(*reset)
                continue
            if click := self.template_match(screenshot, ImageTemplate('btn_ok') | ImageTemplate('btn_ok_blue')
                                            | ImageTemplate('btn_check_reward')
                                            | ImageTemplate('btn_reset_reward_in_dialog')
                                            | ImageTemplate('btn_exchange_again_blue')
                                            | ImageTemplate('btn_exchange_again_white')):
                self.driver.click(*click)
                time.sleep(0.5)
                continue
    
    def _confidence(self):
        time.sleep(1)
        btn_confidence = self.template_match(self.driver.screenshot(), ImageTemplate('btn_confidence'))
        if not btn_confidence:
            return
        self.driver.click(*btn_confidence)
        while True:
            time.sleep(0.5)
            screenshot = self.driver.screenshot()
            if self.template_match(screenshot, ImageTemplate('symbol_confidence_home') & ImageTemplate('symbol_help')):
                new = self.template_match(screenshot, ImageTemplate('symbol_new_confidence'))
                if not new:
                    # 返回活动首页
                    self.action_once(ClickAction(pos=(30, 35)))
                    time.sleep(5)
                    break
                self.driver.click(new[0], int(new[1] + screenshot.shape[0] * 0.1))
                continue
            if self.template_match(screenshot, ImageTemplate('symbol_confidence_home')):
                # 信赖度二级页面
                if new := self.template_match(screenshot, ImageTemplate('symbol_new_confidence_inner')):
                    self.driver.click(*new)
                    continue
                self.action_once(ClickAction(pos=(30, 35)))
                continue
            if novocal := self.template_match(screenshot, ImageTemplate('btn_novocal_blue')):
                self.driver.click(*novocal)
                continue
            if ignore := self.template_match(screenshot, ImageTemplate('btn_close') | ImageTemplate('btn_skip_blue') | ImageTemplate('select_branch_first')):
                self.driver.click(*ignore)
                continue
            self.action_once(ClickAction(pos=(14, 200)))
            

    def run(self):
        self.total_step = '∞'
        # 以下流程顺序有关联，不能随意切换
        self._hard()
        self._story()
        self._confidence()
        self._exchange()

@register("clear_story")    
class ClearStory(BaseTask):

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

@register("get_quest_reward")
class GetQuestReward(BaseTask):
    '''
    领取任务奖励
    '''

    def run(self):
        self.action_squential(
            SleepAction(1),
            MatchAction(template='quest', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(pos=(15, 200))]),
            SleepAction(3),
            MatchAction('btn_all_rec', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_ok', matched_actions=[ClickAction()], timeout=3),
            MatchAction('btn_cancel', matched_actions=[
                        ClickAction()], timeout=3)
        )

@register("arena")
class Arena(BaseTask):
    '''
    竞技场
    '''

    def run(self):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(3),
            ClickAction(pos=(587, 411)),
            SleepAction(1.5),
            ClickAction(pos=(590, 400)),
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
class PrincessArena(BaseTask):
    '''
    公主竞技场
    '''

    def run(self):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(3),
            ClickAction(pos=(587, 411)),
            SleepAction(1.5),
            ClickAction(pos=(810, 400)),
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
class Research(BaseTask):
    '''
    圣迹调查
    '''

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(template='research'),
            MatchAction('research_symbol', matched_actions=[
                ClickAction(offset=(100, 200))], timeout=5),
        ]
        # 圣迹2级
        actions += [
            ClickAction(pos=(587, 231)),
            SleepAction(1),
            ClickAction(pos=(718, 146)),
            *_clean_oneshot_actions(),
            SleepAction(1),
            ClickAction(pos=(37, 33)),
            SleepAction(1)
        ]
        # 神殿2级
        actions += [
            ClickAction(pos=(800, 240)),
            SleepAction(1),
            ClickAction(pos=(718, 146)),
            *_clean_oneshot_actions(),
            SleepAction(1)
        ]
        self.action_squential(*actions)

@register("schedule")
class Schedule(BaseTask):
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


class TeamFormation(BaseTask):
    '''
    设置队伍编组
    '''
    current_team_region = (30, 400, 590, 510)
    current_team_region_separated = [
        (47,405,147,500),
        (156,405,252,500),
        (267,405,364,500),
        (376,405,471,500),
        (486,405,580,500),
    ]
    chara_mapping = None

    def _gen_chara_mapping(self):
        if TeamFormation.chara_mapping:
            return TeamFormation.chara_mapping
        ret = {}
        try:
            db_potential = "cache/redive_cn.db"
            if not os.path.exists(db_potential):
                from .news import fetch_event_news
                fetch_event_news()
            with sqlite3.connect(db_potential) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT unit_id, unit_name FROM unit_profile")
                for id, name in cursor.fetchall():
                    ret[int(id/100)] = name
                cursor.close()
                TeamFormation.chara_mapping = ret
        except Exception as e:
            print("获取角色名失败", e)
        return ret

    def _in_team_formation(self):
        for _ in range(3):
            screenshot = self.driver.screenshot()
            if self.template_match(screenshot, ImageTemplate("symbol_team_formation")):
                return True
            time.sleep(2)
    
    def _check_current_form(self, form:list[Member])->tuple[list[int], list[int]]:
        screenshot = self.driver.screenshot()
        h,w,_ = screenshot.shape
        mask = np.zeros((h,w), dtype=np.uint8)
        team_region = self.adapted_region(TeamFormation.current_team_region, w, h)
        mask[team_region[1]:team_region[3],team_region[0]:team_region[2]] = 0xFF
        add_ids = [mem.id for mem in form]
        remove_regions = [self.adapted_region(region, w, h) for region in TeamFormation.current_team_region_separated]
        for index in range(len(add_ids)-1,-1,-1):
            id = add_ids[index]
            pos = self.template_match(screenshot, CharaIconTemplate(id, mask=mask))
            if pos:
                add_ids.pop()
                for i, region in enumerate(remove_regions):
                    if self.in_region(region, pos):
                        remove_regions.pop(i)
                        break
        return add_ids, remove_regions

    def run(self, formation:list[Member])->bool:
        if not formation:
            print("未设置期望编组")
            return
        if not self._in_team_formation():
            print("未在编队界面")
            return
        add_ids, remove_regions = self._check_current_form(formation)
        for region in remove_regions:
            pos = self.center_region(region)
            self.driver.click(*pos)
            time.sleep(0.5)
        if add_ids:
            # 使用搜索功能
            self.set_progress(total_step=2*len(add_ids))
            name_mapping = self._gen_chara_mapping()
            self.action_squential(SwipeAction(start=(480, 150), end=(480,350)), SleepAction(1))
            for id in add_ids:
                self.action_squential(
                    ClickAction(pos=(480, 135)),
                    SleepAction(0.5),
                    InputAction(name_mapping[id]),
                    SleepAction(0.5),
                    ClickAction(pos=(110, 220)), # 丧失焦点
                    SleepAction(0.5),
                    ClickAction(template=CharaIconTemplate(id)), # 选择匹配人物
                    ClickAction(pos=(690, 135)),
                )
        add_ids, remove_regions = self._check_current_form(formation)
        if add_ids or remove_regions:
            # 如果还存在需要操作的步骤说明未变更为预期队伍组合，可能账号没有预期编队的角色。
            return False
        return True

    
class TeamFormationEx(TeamFormation):
    '''
    多个队伍编队
    '''

    def run(self, formations:list[list[Member]]):
        if not formations:
            print("未设置期望编组")
            return
        if not self._in_team_formation():
            print("未在编队界面")
            return
        self.set_progress(total_step="∞")
        
        for i in range(len(formations)):
            for region in TeamFormationEx.current_team_region_separated:
                pos = self.center_region(region)
                self.driver.click(*pos)
                time.sleep(0.5)
            if i + 1 < len(formations):
                self.action_squential(
                    ClickAction(pos=(834, 448)),
                    SleepAction(1),
                )
        for _ in range(len(formations) - 1):
            self.action_squential(
                ClickAction(pos=(673, 441)),
                SleepAction(1),
            )
            
        for i,formation in enumerate(formations):
            member = formation[0]
            if member.id >= 1000:
                add_ids, remove_regions = self._check_current_form(formation)
                for region in remove_regions:
                    pos = self.center_region(region)
                    self.driver.click(*pos)
                    time.sleep(0.5)
                if add_ids:
                    # 使用搜索功能
                    name_mapping = self._gen_chara_mapping()
                    self.action_squential(SwipeAction(start=(480, 185), end=(480,350)), SleepAction(1))
                    for id in add_ids:
                        self.action_squential(
                            ClickAction(pos=(480, 200)),
                            SleepAction(0.5),
                            InputAction(name_mapping[id]),
                            SleepAction(0.5),
                            ClickAction(pos=(110, 290)), # 丧失焦点
                            SleepAction(0.5),
                            ClickAction(template=CharaIconTemplate(id)), # 选择匹配人物
                            ClickAction(pos=(690, 200)),
                        )
                add_ids, remove_regions = self._check_current_form(formation)
                if add_ids or remove_regions:
                    # 如果还存在需要操作的步骤说明未变更为预期队伍组合，可能账号没有预期编队的角色。
                    return False
            else:
                # 非法formation，可能队伍不需要，随便点击几个角色加入
                actions = []
                for j in range((i-1)*4,i*4):
                    actions.append(ClickAction(pos=(112 + j*100, 250)))
                    actions.append(SleepAction(1))
                self.action_squential(*actions)
            if i + 1 < len(formations):
                self.action_squential(
                    ClickAction(pos=(834, 448)),
                    SleepAction(0.5),
                )
        return True

class Combat(BaseTask):
    '''
    普通战斗场景任务
    '''
    unit_regions = (
        (678,400,763,485),
        (557,400,643,485),
        (438,400,522,485),
        (315,400,402,485),
        (196,400,282,485),
    )

    def _check_dead_count(self, screenshot:np.ndarray, member_num):
        dead_count = 0
        for region in Combat.unit_regions[:member_num]:
            if not self.template_match(screenshot, BrightnessTemplate(region, 80)):
                dead_count += 1
        return dead_count

    def run(self, form:list[Member]|list[list[Member]]=None, giveup=1, member_num=5):
        '''
        Args:
            form: 提供队伍组合信息。
            giveup: 如果战斗中死亡人数大于{giveup}的数值时，放弃战斗，该数值默认为1。
            member_num: 参与战斗的人数，如果已经提供了{form}那么本参数不发生效果。
        '''
        self.set_progress(total_step=3)
        self.action_squential(
            MatchAction(template='btn_challenge', matched_actions=[ClickAction()], timeout=1),
        )
        if form:
            if isinstance(form[0], list):
                ret = TeamFormationEx(self.robot).run(form)
                form = form[0] # 暂时战斗中操作不支持多队伍
            else:
                ret = TeamFormation(self.robot).run(form)
            member_num = len(form)
            if not ret:
                print("编组失败")
                return False
        self.action_squential(
            ClickAction(template='btn_combat_start'),
            MatchAction(template='btn_blue_settle',matched_actions=[ClickAction(),SleepAction(1),ClickAction(template='btn_combat_start')], timeout=3),
            IfCondition('symbol_restore_power', 
                               meet_actions=[
                                ClickAction(pos=(370, 370)),
                                SleepAction(2),
                                ClickAction(pos=(680, 454)),
                                SleepAction(2),
                                ThrowErrorAction("No power!!!")]),
            MatchAction(template='btn_menu_text'),
        )
        success = True
        set_instant = False
        while True:
            screenshot = self.driver.screenshot()
            if self.template_match(screenshot, ImageTemplate('btn_next_step')):
                break
            pos = self.template_match(screenshot, ImageTemplate('btn_close') | ImageTemplate('btn_cancel'))
            if pos:
                self.driver.click(*pos)
            self.action_once(ClickAction(pos=(200, 250)))
            if self.template_match(screenshot, ImageTemplate('btn_menu_text')):
                if self._check_dead_count(screenshot, member_num) >= giveup:
                    success = False
                    self.action_squential(
                        ClickAction(pos=(900, 25)),
                        SleepAction(1),
                        ClickAction('btn_giveup'),
                        SleepAction(0.5),
                        ClickAction('btn_giveup_blue')
                        )
                    break
                if form and not set_instant:
                    regions = [self.adapted_region(region, screenshot.shape[1], screenshot.shape[0]) for region in Combat.unit_regions]
                    for i,mem in enumerate(form):
                        if mem.instant:
                            region = regions[i]
                            self.driver.click((region[0]+region[2])//2, (region[1]+region[3])//2)
                            time.sleep(0.2)
                    set_instant = True
            time.sleep(0.5)
        if success:
            self.action_squential(
                MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                    ClickAction(template=ImageTemplate('btn_close') | ImageTemplate('btn_cancel')),]),
                SleepAction(1),
                MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                    ClickAction(template=ImageTemplate('btn_close') | ImageTemplate('btn_cancel') | ImageTemplate('btn_ok_blue')),])
            )
        return success

@register("luna_tower_climbing")
class LunaTowerClimbing(TimeLimitTask):
    '''
    爬露娜塔
    '''
    class State(Enum):
        CONTINUE = 1
        BREAK = 2
        LEVEL = 3
        CORRIDOR = 4
        EX = 5

    @staticmethod
    def valid(event_news: EventNews, args=None) -> tuple:
        if LunaTowerClimbing.event_first_day(event_news.tower):
            return LunaTowerClimbing, args
    
    level_recognize_region = (334, 78, 414, 117)

    def _parse_level(self, ocr_result):
        results = ocr_result[0]
        if not results:
            return None
        for result in results:
            levels = re.findall(r'\d+', result[1][0])
            if levels:
                for level in levels:
                    if int(level) > 10:
                        return level
        
    def _goto_luna_clean(self):
        ToHomePage(self.robot).run()
        LunaTowerClean(self.robot).run()
    
    def _system_recommend_party(self, combat:Combat)->bool:
        self.action_squential(
            MatchAction("btn_use_blue", matched_actions=[ClickAction()], unmatch_actions=[ClickAction("btn_pass_party")]),
            SleepAction(1),
            ClickAction("btn_check_battle"),
            SleepAction(1),
        )
        return combat.run()
    
    def _check_state(self, screenshot) -> 'LunaTowerClimbing.State':
        if not hasattr(self, '_check_state_times'):
            self._check_state_times = 0
        if self.template_match(screenshot, ImageTemplate("symbol_luna_tower_lock") & ImageTemplate("btn_pass_party")):
            self._check_state_times = 0
            return LunaTowerClimbing.State.LEVEL
        match_special = 0
        while self.template_match(screenshot, ImageTemplate("btn_pass_party")) and match_special < 3:
            match_special += 1
            time.sleep(1)
        if match_special >= 3:
            self._check_state_times = 0
            h,w,_ = screenshot.shape
            ex_pass = False
            corridor_pass = False
            ex_region = self.adapted_region((70, 336, 247, 408), w, h)
            if not self.template_match(screenshot, BrightnessTemplate((776, 356, 849, 389), 130)):
                corridor_pass = True
            pass_poses = self.template_match(screenshot, ImageTemplate("symbol_pass", ret_count=-1))
            if pass_poses:
                for pos in pass_poses:
                    if self.in_region(ex_region, pos):
                        ex_pass = True
            if not corridor_pass:
                return LunaTowerClimbing.State.CORRIDOR
            if not ex_pass:
                return LunaTowerClimbing.State.EX
            return LunaTowerClimbing.State.BREAK
        if self._check_state_times > 3:
            self._check_state_times = 0
            return LunaTowerClimbing.State.BREAK
        else:
            self._check_state_times += 1
            return LunaTowerClimbing.State.CONTINUE

    
    def run(self, allow_system_recommend=False):
        try:
            from .strategist import LunaTowerStrategist
            from paddleocr import PaddleOCR
            from paddleocr.paddleocr import logger
            import logging
            logger.setLevel(logging.ERROR)
        except Exception as e:
            print("当前缺失依赖，该任务需要安装额外依赖才能运行")
            print(e)
            return
        self.total_step = '∞'
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=(50, 300))]),
            SleepAction(1),
            ClickAction(template="btn_luna_tower_entrance"),
            MatchAction(template="symbol_luna_tower", unmatch_actions=[ClickAction(template='btn_close')]),
        )
        identify_frame = self.driver.screenshot()
        state = self._check_state(identify_frame)
        if state == LunaTowerClimbing.State.CONTINUE or state == LunaTowerClimbing.State.BREAK:
            print("当前没有未解锁层数，应执行回廊扫荡")
            self._goto_luna_clean()
            return
        strategist = LunaTowerStrategist()
        start = time.time()
        print("开始拉取策略信息...")
        strategist.gather_information()
        print(f"生成露娜塔策略耗时：{time.time() - start}")
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", gpu=False)
        h,w,_ = identify_frame.shape
        level_region = self.adapted_region(LunaTowerClimbing.level_recognize_region, w, h)
        combat = Combat(self.robot)
        while True:
            screenshot = self.driver.screenshot()
            if not self.template_match(screenshot, ImageTemplate("symbol_luna_tower")):
                time.sleep(1)
                continue
            state = self._check_state(screenshot)
            strategies = None
            if state == LunaTowerClimbing.State.CONTINUE:
                time.sleep(1)
                continue
            elif state == LunaTowerClimbing.State.BREAK:
                break
            elif state == LunaTowerClimbing.State.LEVEL:
                level = self._parse_level(ocr.ocr(screenshot[level_region[1]:level_region[3],level_region[0]:level_region[2]], cls=False))
                print(f"当前处理露娜塔层级: {level}")
                strategies = strategist.get_strategy(level)
            elif state == LunaTowerClimbing.State.EX:
                print(f"当前处理露娜塔EX")
                if self.template_match(screenshot, ImageTemplate("symbol_corridor")):
                    self.action_once(ClickAction(template="btn_luna_floor_ex"))
                    time.sleep(1)
                strategies = strategist.search_strategy("EX")
                if strategies:
                    tmp = []
                    for strategy in strategies:
                        strategy = strategy.model_copy()
                        # 目前策略获取所能获取的信息不包含多个队伍以及是否存在立即释放模式
                        # 但是在Luna塔EX层中通常为一个队伍并且为全Set所以这里特殊修改下
                        for member in strategy.party:
                            member.instant = True
                        strategy.party = [strategy.party, [Member(id=0, instant=True)], [Member(id=0, instant=True)]]
                        tmp.append(strategy)
                    strategies = tmp
            elif state == LunaTowerClimbing.State.CORRIDOR:
                print(f"当前处理露娜塔回廊")
                strategies = strategist.search_strategy("回廊")
            if not strategies:
                if allow_system_recommend:
                    print("无策略信息，尝试使用系统推荐组合")
                    self._system_recommend_party(combat)
                else:
                    raise RuntimeError("无处理对应层的策略信息")
            else:
                combat_success = False
                for strategy in strategies:
                    for _ in range(2):
                        self.action_squential(ClickAction(pos=(815,430)), SleepAction(1))
                        combat_success = combat.run(form=strategy.party)
                        if combat_success:
                            break
                if not combat_success:
                    # 使用系统推荐队伍 or 退出任务
                    if not allow_system_recommend or not self._system_recommend_party(combat): 
                        raise RuntimeError("所有尝试组合皆推塔失败，退出任务")
            time.sleep(1)

        self._goto_luna_clean()

@register("adventure_daily")
class AdventureDaily(BaseTask):
    '''
    探险
    '''

    def check_current_has_event(self):
        action = MatchAction(ImageTemplate("symbol_adventure_event") | ImageTemplate("symbol_adventure_event_1"), timeout=3)
        self.action_squential(action, show_progress=False)
        return not action.is_timeout


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
                ClickAction("symbol_adventure_event"),
                SleepAction(1),
                ClickAction(pos=center_pos),
                ClickAction("btn_skip", timeout=5),
                # Special Event, 需要做一次选项选择并且消耗更长的时间通过动画
                MatchAction("select_branch_first", matched_actions=[ClickAction(), SleepAction(6), ClickAction(pos=center_pos), SleepAction(4)], timeout=5),
                SleepAction(6),
                ClickAction(pos=center_pos),
                SleepAction(5),
                title="清理Event"
            )