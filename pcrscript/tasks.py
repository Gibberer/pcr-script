from abc import ABCMeta, abstractmethod
from .constants import *
from pcrscript.actions import *
from typing import Iterable, TYPE_CHECKING
import numpy as np
import time

if TYPE_CHECKING:
    from pcrscript import Robot

def _get_combat_actions(check_auto=False, combat_duration=35, interval=1):
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
        actions.append(MatchAction(template='btn_caidan', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
    actions.append(SleepAction(combat_duration))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'), ClickAction(pos=(200, 250))], delay=interval))
    actions.append(SleepAction(1))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel')]))
    return actions

    

class BaseTask(metaclass=ABCMeta):

    def __init__(self, robot:'Robot'):
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


class ChouShiLian(BaseTask):
    '''
    抽取免费十连
    '''

    def run(self, multi=False):
        draw_actions = [
            SleepAction(0.5),
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
            IfCondition(condition_template="symbol_gacha_free", meet_actions=[
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
            ]),
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
            MatchAction(template="guild_symbol",matched_actions=[ClickAction()],
                        unmatch_actions=[ClickAction(template="btn_close"),ClickAction(template="btn_ok"), SleepAction(0.5)]),
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
        self.robot._enter_adventure()
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

class ClearActivityFirstTime(BaseTask):
    '''
    剧情活动首次过图
    '''
    def run(self, exhaust_power=False):
        self.robot._enter_adventure(difficulty=Difficulty.NORMAL, activity=True)
        pre_pos = (-100,-100)
        step = 0
        while True:
            time.sleep(0.5)
            screenshot = self.robot.driver.screenshot()
            self._ignore_niggled_scene(screenshot)
            peco_pos = self.robot._find_match_pos(screenshot, template='peco', threshold=0.7)
            if not peco_pos:
                # 点击屏幕重新判断
                self.action_once(ClickAction(pos=(20, 100)))
                continue
            else:
                if self._is_same_pos(pre_pos, peco_pos):
                    # 位置相同，说明下一关需要挑战boss关卡
                    if step == 0:
                        # 普通关卡
                        self.action_squential(ClickAction(template='normal', threshold=0.6, mode='binarization'))
                    else:
                        self.action_squential(ClickAction(template='hard', threshold=0.6, mode='binarization'))
                    match_action = MatchAction(template='btn_challenge', timeout=5)
                    self.action_squential(match_action)
                    if not match_action.is_timeout:
                        actions = _get_combat_actions(combat_duration=3, interval=0.2)
                        actions += [SleepAction(2)]
                        self.action_squential(*actions)
                        if step == 0:
                            # 移动到困难章节
                            time.sleep(5)
                            self.action_squential(MatchAction('btn_hard_selected',
                                                unmatch_actions=[ClickAction(
                                                    template="btn_hard", threshold=0.9)]))
                            time.sleep(3)
                            step = 1
                else:
                    lock_ret = self.robot._find_match_pos_list(screenshot, template='symbol_lock')
                    if not lock_ret:
                        print('未发现解锁符号，执行正常活动清理步骤')
                        break
                    self.robot.driver.click(peco_pos[0], peco_pos[1] + self.robot.deviceheight * 0.1)
                    match_action = MatchAction(template='btn_challenge', timeout=5)
                    self.action_squential(match_action)
                    if not match_action.is_timeout:
                        actions = _get_combat_actions(combat_duration=15)
                        actions += [SleepAction(2)]
                        self.action_squential(*actions)
                pre_pos = peco_pos
        # 首次过图处理完毕，执行正常活动清体力任务步骤
        self.robot._tohomepage()
        ActivitySaodang().run(hard_chapter=True, exhaust_power=exhaust_power)
        

    def _is_same_pos(self, pre_pos, pos):
        px,py = pre_pos
        x,y = pos
        return  (x - 40 <= px <= x + 40) and (y - 40 <= py <= y + 40)
    
    def _ignore_niggled_scene(self, screenshot):
        print("check ignore")
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
            pos = self.robot._find_match_pos(screenshot, template=template)
            if pos:
                self.robot.driver.click(*pos)

class ActivitySaodang(BaseTask):
    '''
    剧情活动扫荡
    '''
    def run(self, hard_chapter=True, exhaust_power=True):
        if hard_chapter:
            self.robot._enter_adventure(difficulty=Difficulty.HARD, activity=True)
            actions = [
                MatchAction(template='btn_close', matched_actions=[
                            ClickAction(), SleepAction(2)], timeout=3),
                SleepAction(2),
                # 清困难本
                ClickAction(template='1-1', offset=(0, -20),
                            threshold=0.6, mode='binarization'),  # 点击第一个活动困难本
                MatchAction('btn_challenge', threshold=0.9*THRESHOLD),
            ]
            for _ in range(5):
                actions += [
                    SwipeAction((877, 330),(877, 330), 2000),
                    ClickAction(pos=(757, 330)),
                    SleepAction(0.5),
                    ClickAction(template='btn_ok_blue', timeout=10), # 加入超时防止卡住（应为不能稳定点击到1-1）
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
                ClickAction(template='very', offset=(0, -40),
                            threshold=0.6, mode='binarization',timeout=5),
                ClickAction(pos=(860,270)), # 如果timeout尝试点击该位置   
                SleepAction(1),         
            ]
            actions += _get_combat_actions(combat_duration=3, interval=0.5)
            self.action_squential(*actions)
        if exhaust_power:
            if hard_chapter:
                self.robot._tohomepage()
            self.robot._enter_adventure(difficulty=Difficulty.NORMAL, activity=True)
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
                time.sleep(0.5)
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

class Explore(BaseTask):
    '''
    每日探索
    '''
    def run(self, *args):
        self.action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(template='explore'),
            MatchAction('explore_symbol', matched_actions=[
                ClickAction(offset=(100, 200))], timeout=5),)
        self.action_squential(
            ClickAction(pos=(594, 242)),  # 经验关卡
            SleepAction(3),)
        # 处理经验关卡
        self._execute_process()
        # 处理玛娜关卡
        self._execute_process()

    def _execute_process(self):
        target_pos = (712, 143)
        times = 0
        while True:
            screenshot = self.robot.driver.screenshot()
            lock_symbol = self.robot._find_match_pos(screenshot, 'symbol_lock')
            if lock_symbol:
                ret = self.robot._find_match_pos_list(screenshot, 'symbol_explore_unlock_level')
                if ret:
                    ret.sort(key=lambda pos: pos[1])
                    target_pos = ret[0]
                break
            else:
                level_lock_symbol = self.robot._find_match_pos(screenshot, 'symbol_explore_lock_level')
                if level_lock_symbol and times == 0:
                    # 未解锁关卡执行解锁操作,只处理一次
                    times += 1
                    self.action_squential(ClickAction(pos=target_pos), *_get_combat_actions(combat_duration=15))
                else:
                    if times > 0:
                        ret = self.robot._find_match_pos_list(screenshot, 'symbol_explore_unlock_level')
                        if ret:
                            ret.sort(key=lambda pos: pos[1])
                            target_pos = ret[0]
                    break
                    
        # 扫荡流程
        self.action_squential(
            ClickAction(pos=target_pos),
            MatchAction('btn_challenge'),
            ClickAction(pos=(757, 330)),
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            ClickAction(pos=(480, 480)), # 这是一个引导弹窗，如果经验关卡没票了会自动移动到玛娜关卡
            SleepAction(3)
        )

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
    "clear_activity_first_time": ClearActivityFirstTime,
    "explore":Explore,
    }
