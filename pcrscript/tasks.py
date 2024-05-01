from abc import ABCMeta, abstractmethod
from .constants import *
from pcrscript.actions import *
from typing import TYPE_CHECKING
from .templates import Template,ImageTemplate
import time

if TYPE_CHECKING:
    from pcrscript import Robot

# 可使用的任务列表
registedTasks = {}

def register(name):
    def wrap(cls):
        if name in registedTasks:
            raise Exception(f"Task:{name} already registed.")
        registedTasks[name] = cls
        return cls
    return wrap

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
        actions.append(MatchAction(template='btn_menu_text', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
    actions.append(SleepAction(combat_duration))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'), ClickAction(pos=(200, 250))], delay=interval))
    actions.append(SleepAction(1))
    actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
        ClickAction(template='btn_close'),ClickAction(template='btn_cancel'),ClickAction(template='btn_ok_blue')]))
    return actions

def _get_clean_oneshot(duration=2000):
    return [
            MatchAction('btn_challenge'),
            SwipeAction((877, 330), (877, 330), duration),
            ClickAction(pos=(757, 330)),
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


class BaseTask(metaclass=ABCMeta):

    def __init__(self, robot:'Robot'):
        self.robot = robot
        self.define_width = BASE_WIDTH
        self.define_height = BASE_HEIGHT

    def action_squential(self, *actions: Action):
        for action in actions:
            action.bindTask(self)
        self.robot.action_squential(*actions)
    
    def action_once(self, action: Action):
        action.bindTask(self)
        action.do(self.robot.driver.screenshot(), self.robot)
        return action.done()

    def template_match(self, screenshot, template:Template):
        template.set_define_size(self.define_width, self.define_height)
        return template.match(screenshot)

    @abstractmethod
    def run(self, *args):
        pass

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
class FreeGacha(BaseTask):
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
                    ClickAction(template="btn_ok_blue", timeout=5),
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
class LunaTowerClean(BaseTask):
    '''
    露娜塔 回廊扫荡
    '''

    def run(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=(50, 300))]),
            SleepAction(1),
            ClickAction(template="btn_luna_tower_entrance"),
            MatchAction(template="symbol_luna_tower"),
            MatchAction(template='symbol_luna_tower_lock',matched_actions=[ThrowErrorAction("回廊未解锁")],timeout=2),
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
@register("common_adventure")
class CommonAdventure(BaseTask):
    '''
    通用的过图任务，执行内容为：
    1. 寻找当前人物的位置
    2. 点击人物
    3. 进入战斗页面，开始战斗直到结束
    4. -> 1 循环
    '''

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
                    actions = _get_combat_actions(combat_duration=estimate_combat_duration)
                    actions += [SleepAction(2)]
                    self.action_squential(*actions)
            else:
                self.action_squential(MatchAction(template=ImageTemplate(character_symbol, threshold=0.7), unmatch_actions=[ClickAction(template='btn_cancel'), ClickAction(template='btn_close')]))
@register("quick_clean")
class QuickClean(BaseTask):
    '''
    快速扫荡任务
    '''
    _pos = ((100, 80), (220, 80), (340, 80), (450, 80), (570, 80), (690, 80), (810, 80))
    def run(self, pos=0):
        if pos <= 0 or pos > len(QuickClean._pos):
            print(f"不支持的预设选项:{pos}")
            return
        pref_pos = QuickClean._pos[pos - 1]
        # 进入冒险图
        self.robot._enter_adventure()
        actions = [
            ClickAction(pos=(920, 144)),
            SleepAction(2),
            ClickAction(pos=pref_pos),
            SleepAction(1),
            ClickAction(pos=(815, 480)),
            MatchAction(template="btn_challenge",matched_actions=[ClickAction()], unmatch_actions=[
                IfCondition("symbol_restore_power", meet_actions=[
                    ThrowErrorAction("No Power!!!")
                ], unmeet_actions=[
                    MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()],timeout=0.1)
                ]),
                ClickAction("btn_ok"),
                ClickAction("btn_not_store_next"),
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
@register("clear_campaign_first_time")
class ClearCampaignFirstTime(BaseTask):
    '''
    剧情活动首次过图
    '''
    def run(self, exhaust_power=False):
        self.robot._enter_adventure(difficulty=Difficulty.NORMAL, campaign=True)
        pre_pos = (-100,-100)
        step = 0
        retry_count = 0
        while True:
            time.sleep(1)
            screenshot = self.robot.driver.screenshot()
            self._ignore_niggled_scene(screenshot)
            character_pos = self.template_match(screenshot, ImageTemplate('character'))
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
                        actions = _get_combat_actions(combat_duration=3, interval=0.2)
                        actions += [SleepAction(2)]
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
                        actions = _get_combat_actions(combat_duration=15)
                        actions += [SleepAction(2)]
                        self.action_squential(*actions)
                        pre_pos = character_pos
        # 首次过图处理完毕，执行正常活动清体力任务步骤
        self.robot._tohomepage()
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
class CampaignClean(BaseTask):
    '''
    剧情活动扫荡
    '''
    def run(self, hard_chapter=True, exhaust_power=True):
        if hard_chapter:
            self.robot._enter_adventure(difficulty=Difficulty.HARD, campaign=True)
            actions = [
                MatchAction(template='btn_close', matched_actions=[
                            ClickAction(), SleepAction(2)], timeout=3),
                SleepAction(2),
                # 清困难本
                ClickAction(template=ImageTemplate('1-1', threshold=0.6, mode='binarization'), offset=(0, -20)),  # 点击第一个活动困难本
                MatchAction(ImageTemplate('btn_challenge', threshold=0.9*THRESHOLD)),
            ]
            for _ in range(5):
                actions += [
                    SwipeAction((877, 330),(877, 330), 2000),
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
            actions += _get_combat_actions(combat_duration=3, interval=0.5)
            self.action_squential(*actions)
        if exhaust_power:
            if hard_chapter:
                self.robot._tohomepage()
            self.robot._enter_adventure(difficulty=Difficulty.NORMAL, campaign=True)
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
                *_get_clean_oneshot(duration=6000),
                SleepAction(2)
            ]
            self.action_squential(*actions)
        self.action_squential(SleepAction(2))
        # 领取任务
        self.action_squential(
            SleepAction(1),
            MatchAction(template='symbol_campaign_quest',
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
@register("clear_story")    
class ClearStory(BaseTask):
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
            SleepAction(1.5),
            ClickAction(pos=(587, 411)),
            SleepAction(1.5),
            ClickAction(pos=(590, 240)),
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
            SleepAction(1.5),
            ClickAction(pos=(587, 411)),
            SleepAction(1.5),
            ClickAction(pos=(810, 240)),
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
            *_get_clean_oneshot(),
            SleepAction(1),
            ClickAction(pos=(37, 33)),
            SleepAction(1)
        ]
        # 神殿2级
        actions += [
            ClickAction(pos=(800, 240)),
            SleepAction(1),
            ClickAction(pos=(718, 146)),
            *_get_clean_oneshot(),
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
                            ClickAction(ImageTemplate("btn_ok_blue") | ImageTemplate("btn_ok") 
                                        | ImageTemplate("btn_skip_ok") | ImageTemplate("btn_close"),
                                        roi=(350,0,960,540))
                        ]),
            SleepAction(1),
            ClickAction(pos=(270, 480)), # 关闭
        )