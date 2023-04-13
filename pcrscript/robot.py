from time import sleep
from .driver import Driver
from .actions import *
from .constants import *
from .error import NetError
import cv2 as cv
import numpy as np
import time
from typing import Iterable, Tuple
from .tasks import taskKeyMapping, BaseTask
import functools
import random
import collections
import copy
import re


def trace(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self._log("start {}".format(func.__name__.lstrip('_')))
        ret = func(self, *args, **kwargs)
        self._log("end {}".format(func.__name__.lstrip('_')))
        return ret
    return wrapper


num = 0


class Robot:
    def __init__(self, driver: Driver, name=None):
        super().__init__()
        self.ocr = None
        self.driver = driver
        self.devicewidth, self.deviceheight = driver.getScreenSize()
        global num
        if not name:
            name = "Robot#{}".format(num)
            num += 1
        self._name = name

    @trace
    def changeaccount(self, account, password, logpath=None):
        if logpath:
            with open(logpath, 'a') as f:
                f.write("{}:{}\n".format(self._name, account))
        while True:
            screenshot = self.driver.screenshot()
            if self._find_match_pos(screenshot, 'welcome_main_menu'):
                # 当前是欢迎页，执行登录操作
                actions = (
                    MatchAction('btn_change_account', matched_actions=[
                                ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(850, 30))], delay=0),
                    SleepAction(0.5),
                    ClickAction(pos=self._pos(354,374)),
                    SleepAction(0.5),
                    ClickAction(template='symbol_bilibili_logo'),
                    ClickAction(template='edit_account'),
                    InputAction(account),
                    ClickAction(template='edit_password'),
                    InputAction(password),
                    ClickAction(template='btn_login'),
                    SleepAction(5)  # 延迟下，后续需要判断是否出现用户协议弹窗
                )
                self._action_squential(*actions)
                # 执行登录操作之后判断是否出现用户协议
                while self._find_match_pos(self.driver.screenshot(), 'user_agreement_symbol'):
                    self._action_squential(
                        ClickAction(pos=self._pos(704, 334)),  # 滑动到底部
                        SleepAction(2),
                        ClickAction(pos=self._pos(536, 388)),  # 点击同意
                        SleepAction(2)
                    )
                break
            else:
                # 在游戏里退出账号
                ret = self._find_match_pos(screenshot, 'btn_close')
                if ret:
                    self.driver.click(*ret)
                ret = self._find_match_pos(screenshot, 'tab_main_menu')
                if ret:
                    self._action_squential(
                        ClickAction(pos=ret),
                        ClickAction(template='btn_back_welcome'),
                        ClickAction(template='btn_ok_blue')
                    )
                ret = self._find_match_pos(
                    screenshot, 'btn_back_welcome')
                if ret:
                    self._action_squential(
                        ClickAction(template='btn_back_welcome'),
                        ClickAction(template='btn_ok_blue')
                    )
                ClickAction(pos=self._pos(50, 300)).do(screenshot, self)
            time.sleep(3)

    @trace
    def work(self, tasklist=None):
        tasklist = tasklist[:]
        pretasks = []
        taskcount = len(tasklist)
        for i in range(taskcount - 1, -1, -1):
            if tasklist[i][0] in ('real_name_auth', 'landsol_cup'):
                pretasks.insert(0, tasklist[i])
                tasklist.pop(i)
        if pretasks:
            for funcname, *args in pretasks:
                getattr(self, "_" + funcname)(*args)
        self._tohomepage()
        # 第一次进入的时候等下公告
        time.sleep(3)
        ClickAction(template='btn_close').do(self.driver.screenshot(), self)
        if tasklist:
            for funcname, *args in tasklist:
                if funcname in taskKeyMapping:
                    self._runTask(funcname, taskKeyMapping[funcname], args)
                else:
                    self._call_function(funcname, args)

    def _runTask(self, taskname, taskclass: BaseTask, args):
        self._log(f"start task: {taskname}")
        try:
            task = taskclass(self)
            if args:
                task.run(*args)
            else:
                task.run()
        except Exception as e:
            print(e)
            if isinstance(e, NetError):
                self._tohomepage(click_pos=(60, 300))
                self._runTask(taskname, taskclass, args)
        self._log(f"end task: {taskname}")
    
    def _call_function(self, funcname, args):
        try:
            getattr(self, "_" + funcname)(*args)
        except Exception as e:
            print(e)
            if isinstance(e, NetError):
                self._tohomepage(click_pos=(60, 300))
                self._call_function(funcname, args)

    def _log(self, msg: str):
        print("{}: {}".format(self._name, msg))

    @trace
    def _landsol_cup(self):
        '''
        兰德索尔杯
        '''
        start_time = time.time()
        self._action_squential(
            MatchAction('landsol_cup_symbol', unmatch_actions=[
                        ClickAction(pos=self._pos(53, 283))], timeout=30),
            SleepAction(1)
        )
        if time.time() - start_time > 45:
            return
        pos = random.choice(((199, 300), (400, 300), (590, 300), (790, 300)))
        self._action_squential(
            ClickAction(pos=self._pos(*pos)),
            SleepAction(2),
            ClickAction(pos=self._pos(838, 494))
        )

    @trace
    def _real_name_auth(self, ids):
        '''
        实名认证
        Paramters:
        ---------
        ids: 从配置文件中读取的内容
        '''
        r = random.choice(ids)
        _id = r['id']
        name = r['name']
        start_time = time.time()
        self._action_squential(MatchAction('edit_real_name', matched_actions=[
                               ClickAction(), InputAction(name)], timeout=20))
        if time.time() - start_time > 20:
            return
        self._action_squential(
            ClickAction(template='edit_id_card'),
            InputAction(_id),
            ClickAction(template='btn_submit'),
            ClickAction(template='btn_confirm')
        )

    @trace
    def _tohomepage(self, click_pos=(90, 500), timeout=0):
        '''
        进入游戏主页面
        '''
        self._action_squential(MatchAction('shop', unmatch_actions=(
            ClickAction(template='btn_close'),
            ClickAction(template="btn_ok_blue"),
            ClickAction(template="btn_download"),
            ClickAction(template='btn_skip'),
            ClickAction(template='btn_cancel'),
            ClickAction(template='select_branch_first'),
            ClickAction(pos=self._pos(*click_pos)),
        ), timeout=timeout), net_error_check=False)

    @trace
    def _close_ub_animation(self):
        '''
        关闭ub动画
        '''
        self._action_squential(
            ClickAction(template='tab_main_menu'),
            ClickAction(template='btn_setting'),
            ClickAction(template='page_battle'),
            MatchAction('page_battle_selected'),
            ClickAction(pos=self._pos(772, 239)),
            ClickAction(pos=self._pos(772, 370)),
            ClickAction(template='btn_close')
        )

    @trace
    def _get_quest_reward(self):
        '''
        获取任务奖励
        '''
        self._action_squential(
            SleepAction(1),
            ClickAction(template='quest'),
            SleepAction(3),
            MatchAction('btn_all_rec', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5),
            MatchAction('btn_ok', matched_actions=[ClickAction()], timeout=3),
            MatchAction('btn_cancel', matched_actions=[
                        ClickAction()], timeout=3)
        )


    @trace
    def _shop_buy(self, rule):
        '''
        商店购买
        Paramters:
        ---
        rule: 规则
        '''
        actions = []
        # 首先进入商店页
        actions.append(ClickAction(template='shop'))
        actions.append(MatchAction(template='symbol_shop', unmatch_actions=[
                       ClickAction(pos=self._pos(77, 258)), ClickAction(template='shop')]))
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
            if self.ocr and 'buy_equip' in value and value['buy_equip']:
                first = value['first_equip']
                end = value['end_equip']
                threshold = value['buy_threshold']
                for i in range(first, end + 1):
                    items.append(Item(i, threshold))
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
                                SwipeAction(start=self._pos(580, 377),
                                            end=self._pos(580, 114), duration=5000),
                                SleepAction(1)
                            ]
                        else:
                            tab_actions += [
                                SwipeAction(start=self._pos(580, 380),
                                            end=self._pos(580, 180), duration=300),
                                SleepAction(1)
                            ]
                        line += 1
                        swipe_time += 1
                if line == last_line:
                    click_pos = SHOP_ITEM_LOCATION_FOR_LAST_LINE[(
                        item.pos - 1) % line_count]
                else:
                    click_pos = SHOP_ITEM_LOCATION[(item.pos - 1) % line_count]

                if item.threshold <= 0:
                    tab_actions += [
                        ClickAction(pos=self._pos(*click_pos)),
                        SleepAction(0.1)
                    ]
                else:
                    def condition_function(screenshot, item, click_pos):
                        rb = self._pos(click_pos[0], click_pos[1] + 120)
                        lt = self._pos(click_pos[0] - 110, click_pos[1] + 90)
                        roi = screenshot[lt[1]:rb[1], lt[0]:rb[0]]
                        ret = self.ocr.recognize(roi)
                        print(ret)
                        if ret:
                            if len(ret) > 1:
                                ret = ret[1]
                            else:
                                ret = ret[0]
                                ret = re.sub(
                                    r'[;:孑持自有数敫敖致方敛寺故敌氮故女效^]', "", ret)
                            ret = ret.replace("|", "1").replace("&", "8")
                            ret = ret.strip()
                            if not ret.isdigit():
                                return False
                            count = int(ret)
                            if count < item.threshold:
                                return True
                        return False

                    tab_actions += [
                        SleepAction(swipe_time * 1 + 1),
                        CustomIfCondition(condition_function, item, click_pos, meet_actions=[
                                          ClickAction(pos=self._pos(*click_pos))]),
                        SleepAction(0.8),
                    ]
            tab_actions += [
                ClickAction(pos=self._pos(700, 438)),
                SleepAction(0.2),
                MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()], timeout=2),
                SleepAction(1.5),
                MatchAction(template='btn_ok_blue',matched_actions=[ClickAction()], timeout=2),
                SleepAction(1.5)
            ]
            tab_main_actions += tab_actions
            if times[tab]:
                for i in range(times[tab] - 1):
                    copy_tab_actions = [
                        ClickAction(pos=self._pos(550, 440)),
                        SleepAction(0.2),
                        ClickAction(template='btn_ok_blue'),
                        SleepAction(1)
                    ]
                    copy_tab_actions += copy.deepcopy(tab_actions)
                    tab_main_actions += copy_tab_actions
            if tab == 8:
                # 限定tab，判断下对应tab是否为可点击状态
                meet_actions = [ClickAction(pos=self._pos(*SHOP_TAB_LOCATION[tab - 1]))] + tab_main_actions
                actions += [
                    SleepAction(1),
                    IfCondition("limit_tab_enable_symbol", meet_actions= meet_actions),
                    SleepAction(1)
                    ]
            else:
                actions += [
                    ClickAction(pos=self._pos(*SHOP_TAB_LOCATION[tab - 1])),
                    SleepAction(1)
                    ]
                actions += tab_main_actions
        self._action_squential(*actions)

    @trace
    def _buy_mana(self, count):
        '''
        购买mana
        '''
        # 先确认进入mana购买界面
        self._action_squential(
            SleepAction(1),
            ClickAction(pos=self._pos(187, 63)),
            MatchAction('icon_mana', unmatch_actions=[
                        ClickAction(pos=self._pos(50, 300))])
        )
        one = self._pos(*[598, 478])
        mul = self._pos(*[818, 477])
        actions = []
        if count >= 1:
            actions.append(ClickAction(pos=one))
            actions.append(SleepAction(.5))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(SleepAction(3))
        if count >= 10:
            actions.append(ClickAction(pos=mul))
            actions.append(SleepAction(.5))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(SleepAction(13))
        if count >= 20:
            actions.append(ClickAction(pos=mul))
            actions.append(SleepAction(.5))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(SleepAction(13))
        actions.append(ClickAction('btn_cancel'))
        self._action_squential(*actions)

    @trace
    def _buy_power(self, count):
        '''
        购买体力
        '''
        actions = []
        for _ in range(count):
            actions.append(SleepAction(1))
            actions.append(ClickAction(pos=self._pos(320, 30)))
            actions.append(ClickAction(template='btn_ok_blue'))
            actions.append(ClickAction(template='btn_ok'))
        self._action_squential(*actions)

    @trace
    def _get_power(self):
        '''
        公会之家领体力
        '''
        self._action_squential(
            ClickAction(template='tab_society_home'),
            MatchAction('guilde_home_symbol', timeout=8),
            SleepAction(1),
            ClickAction(pos=self._pos(900, 428)),
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5),
            SleepAction(3)
        )

    @trace
    def _saodang(self, chapter=1, level=1, count=1):
        self._enter_advanture()
        level_pos = self._move_to_chapter(chapter - 1)
        pos = level_pos[level - 1]
        actions = []
        actions.append(ClickAction(pos=self._pos(*pos)))
        actions.append(MatchAction('btn_challenge'))
        if count == -1:  # click forever change to long press
            actions.append(SwipeAction(
                self._pos(877, 330), self._pos(877, 330), 9000))
        else:
            for _ in range(count):
                actions.append(ClickAction(pos=self._pos(877, 330)))
        self._action_squential(*actions, delay=0)
        actions = []
        actions.append(ClickAction(pos=self._pos(757, 330)))
        actions.append(ClickAction(template='btn_ok_blue'))
        actions.append(ClickAction(template='btn_skip_ok'))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_ok'))
        actions.append(SleepAction(1))
        actions.append(MatchAction(template='btn_ok',
                                   matched_actions=[ClickAction()], timeout=3))
        actions.append(SleepAction(1))
        actions.append(MatchAction(template='btn_ok',
                                   matched_actions=[ClickAction()], timeout=3))
        actions.append(MatchAction(template='btn_cancel', matched_actions=[
            ClickAction(), SleepAction(1)], timeout=1))  # 限时商店
        actions.append(SleepAction(2))
        actions.append(ClickAction(pos=self._pos(666, 457)))
        self._action_squential(*actions)

    @trace
    def _saodang_hard(self, start, end, difficulty=Difficulty.HARD, explicits=None):
        '''
        扫荡hard图，由于hard固定每个level3个所以1-1定义为1 2-1定义为4这样来算
        Paramters
        ------
        start: 开始
        end: 结束
        explicits:['1-3','13-1','13-2']传入明确的关卡信息
        '''
        if isinstance(difficulty, int):
            difficulty = Difficulty(difficulty)
        self._enter_advanture(difficulty)
        if explicits:
            self.__saodang_hard_explicit_mode(difficulty, explicits)
            return
        chapter_index, level = divmod(start - 1, 3)
        if difficulty == Difficulty.VERY_HARD:
            self._move_to_chapter(
                chapter_index, symbols=VH_CHAPTER_SYMBOLS, chapters=VH_CHAPTERS)
        else:
            self._move_to_chapter(chapter_index)
        if difficulty == Difficulty.VERY_HARD:
            chapter_pos = VH_CHAPTER_POS
        else:
            chapter_pos = HARD_CHAPTER_POS
        self._action_squential(
            ClickAction(pos=self._pos(
                *chapter_pos[chapter_index*3 + level])),
            MatchAction('btn_challenge', threshold=0.9*THRESHOLD),
        )
        _range = range(
            start - 1, end) if start <= end else range(start, end - 1, -1)
        next_pos = (939, 251) if start <= end else (36, 251)
        for _ in _range:
            self._action_squential(
                SwipeAction(self._pos(877, 330), self._pos(877, 330), 2000),
                ClickAction(pos=self._pos(757, 330)),
                ClickAction(template='btn_ok_blue'),
                MatchAction(template='symbol_restore_power',
                            matched_actions=[
                                ClickAction(pos=self._pos(370, 370)),
                                SleepAction(2),
                                ClickAction(pos=self._pos(680, 454)),
                                SleepAction(2),
                                ThrowErrorAction("No power!!!")],
                            timeout=2),
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
                            ClickAction(pos=self._pos(121,240)), SleepAction(1)], timeout=1),  # 限时商店
                ClickAction(pos=self._pos(*next_pos)),
                SleepAction(2),
            )
        self._action_squential(
            SleepAction(2),
            ClickAction(pos=self._pos(666, 457))
        )

    def __saodang_hard_explicit_mode(self, difficulty, levels):
        chapters = HARD_CHAPTER_POS
        for level in levels:
            chapter, section = map(lambda x: int(x), level.split('-'))
            self._move_to_chapter(chapter-1)
            self._action_squential(
                ClickAction(pos=self._pos(
                    *chapters[(chapter - 1)*3 + section - 1])),
                *self.__saodang_oneshot_actions()
            )

    def __saodang_oneshot_actions(self, duration=2000):
        return [
            MatchAction('btn_challenge', threshold=0.75),
            SwipeAction(self._pos(877, 330), self._pos(877, 330), duration),
            ClickAction(pos=self._pos(757, 330)),
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
            ClickAction(pos=self._pos(666, 457))
        ]

    @trace
    def _adventure(self, chapter, start, end=None, totalcount=1, checkguide=False):
        '''
        刷冒险
        Parameters
        ---------
        chapter: 冒险章节
        start: 起始关卡
        end: 结束关卡
        checkguide: 是否做跳过教程检测
        '''
        # 从主页进入冒险页面
        self._enter_advanture()
        self._guotu(chapter, start, end, totalcount, checkguide)

    def _guotu(self, chapter, start, end, totalcount, checkguide, symbols=CHAPTER_SYMBOLS, chapters=CHAPTERS):
        chapter = chapter - 1
        if not end:
            end = start
        chapter_symbol = symbols[chapter]
        check_auto = True
        count = 0
        while count < totalcount:
            level_pos = self._move_to_chapter(
                chapter, symbols=symbols, chapters=chapters)
            for i in range(start - 1, end):
                pos = level_pos[i]
                self._combat(pos, check_auto=check_auto)
                check_auto = False
                self._action_squential(
                    MatchAction(chapter_symbol, timeout=10),
                    SleepAction(3)
                )
                ClickAction(template='btn_close').do(
                    self.driver.screenshot(), self)
                if checkguide:
                    time.sleep(2)
                    self._skip_guide(chapter + 1, i + 1)
                level_pos = chapters[chapter][i]
            count += (end - start) + 1

    def _enter_advanture(self, difficulty=Difficulty.NORMAL, activity=False):
        actions = []
        actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close'), ClickAction(pos=self._pos(15, 300))]))
        actions.append(SleepAction(2))
        if activity:
            actions.append(ClickAction(template='story_activity_symbol'))
        else:
            actions.append(ClickAction(
                template='btn_main_plot', threshold=0.8*THRESHOLD))
        actions.append(SleepAction(2))
        unmatch_actions = []
        if activity:
            unmatch_actions += [
                IfCondition('btn_activity_plot',
                            threshold=0.8*THRESHOLD,
                            meet_actions=[ClickAction(
                                template='btn_activity_plot')],
                            unmeet_actions=[ClickAction(pos=self._pos(15, 283)), MatchAction('btn_close', matched_actions=[ClickAction()], timeout=1)])]
        if difficulty == Difficulty.NORMAL:
            unmatch_actions = [ClickAction(
                template='btn_normal', threshold=0.9)] + unmatch_actions
            actions.append(MatchAction('btn_normal_selected',
                                       unmatch_actions=unmatch_actions))
        elif difficulty == Difficulty.HARD:
            unmatch_actions = [ClickAction(
                template="btn_hard", threshold=0.9)] + unmatch_actions
            actions.append(MatchAction('btn_hard_selected',
                                       unmatch_actions=unmatch_actions))
        else:
            unmatch_actions = [ClickAction(
                template="btn_very_hard", threshold=0.9)] + unmatch_actions
            actions.append(MatchAction('btn_very_hard_selected',
                                       unmatch_actions=unmatch_actions))
        self._action_squential(*actions)

    def _move_to_chapter(self, chapter_index, symbols=CHAPTER_SYMBOLS, chapters=CHAPTERS):
        chapter_symbol = symbols[chapter_index]
        # 移动到选中目标的关卡
        ret = self._find_match_template(symbols, timeout=10)
        if not ret:
            return
        pos, _ = ret
        actions = []
        if chapter_index > pos:
            actions.append(MatchAction(chapter_symbol, unmatch_actions=[
                           ClickAction(pos=self._pos(928, 271)), SleepAction(3)], timeout=15))
        elif chapter_index < pos:
            actions.append(MatchAction(chapter_symbol, unmatch_actions=[
                           ClickAction(pos=self._pos(36, 271)), SleepAction(3)], timeout=15))
        # 确保移动到对应页面
        actions.append(SleepAction(1))
        self._action_squential(*actions)
        if chapter_index >= len(chapters):
            chapter_index = -1
        level_pos = chapters[chapter_index][0]
        if pos == chapter_index:
            # 修正level pos
            ret = self._find_match_pos(self.driver.screenshot(), 'peco')
            if ret:
                bar = ret[0] + 15
                for i, pos in enumerate(level_pos):
                    if pos[0] > bar:
                        level_pos = chapters[chapter_index][i]
                        break
        return level_pos

    @ trace
    def _skip_guide(self, chapter, level):
        if chapter == 1:
            if level in (4, 6) and self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                if level == 4:
                    self._skip_guide_1_4()
                if level == 6:
                    self._skip_guide_1_6()
        elif chapter == 2:
            if level in (1, 2, 5, 8, 12) and self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                if level == 1:
                    self._skip_guide_2_1()
                if level == 2:
                    self._skip_guide_2_2()
                if level == 5:
                    self._skip_guide_2_5()
                if level == 8:
                    self._skip_guide_2_8()
                if level == 12:
                    self._skip_guide_2_12()
        elif chapter == 3:
            if level in (1,) and self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                if level == 1:
                    self._skip_guide_3_1()

    def _find_match_template(self, templates, timeout=15, delay=1) -> Tuple[int, str]:
        start_time = time.time()
        while True:
            if delay > 0:
                time.sleep(delay)
            screenshot = self.driver.screenshot()
            for i, template in enumerate(templates):
                ret = self._find_match_pos(screenshot, template)
                if ret:
                    return i, template
            if time.time() - start_time > timeout:
                break

    @ trace
    def _combat(self, trigger_pos, check_auto=False):
        '''
        处理战斗界面相关
        '''
        actions = []
        if trigger_pos:
            actions.append(ClickAction(pos=self._pos(*trigger_pos)))
        actions.append(ClickAction(template='btn_challenge'))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_combat_start'))
        actions.append(SleepAction(5))
        if check_auto:
            actions.append(MatchAction(template='btn_caidan', matched_actions=[ClickAction(template='btn_speed'),
                                                                               ClickAction(template='btn_auto')], timeout=10))
        actions.append(SleepAction(35))
        actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]))
        actions.append(SleepAction(1))
        actions.append(ClickAction('btn_next_step'))
        self._action_squential(*actions)

    @ trace
    def _join_guild(self, guild_name):
        '''
        加入行会
        '''
        self._action_squential(
            MatchAction('guild', matched_actions=[ClickAction()], timeout=5),
            SleepAction(1),
            MatchAction(template='join_guild_symbol', unmatch_actions=[
                        ClickAction(pos=self._pos(50, 300))], timeout=10),
            ClickAction(pos=self._pos(50, 300)),
            SleepAction(3)
        )
        ret = self._find_match_pos(
            self.driver.screenshot(), 'join_guild_symbol')
        if not ret:
            self._log('Join guild failed: maybe already have guild')
            return
        actions = []
        actions.append(ClickAction(pos=self._pos(860, 78)))
        actions.append(MatchAction(
            'btn_cancel', matched_actions=[SleepAction(1)]))
        actions.append(ClickAction(pos=self._pos(281, 142)))
        actions.append(ClickAction(pos=self._pos(380, 182)))
        actions.append(InputAction(guild_name))
        actions.append(ClickAction(pos=self._pos(585, 434)))
        actions.append(SleepAction(1))  # 收起软键盘
        actions.append(ClickAction(pos=self._pos(585, 434)))
        actions.append(SleepAction(3))
        actions.append(ClickAction(pos=self._pos(672, 160)))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_join'))
        actions.append(ClickAction(template='btn_ok_blue'))
        actions.append(SleepAction(1))
        actions.append(ClickAction(template='btn_ok_blue'))
        actions.append(SleepAction(5))
        self._action_squential(*actions)

    @trace
    def _explore(self):
        '''
        处理探索的每日信息
        '''
        self._action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(template='explore'),
            MatchAction('explore_symbol', matched_actions=[
                ClickAction(offset=self._pos(100, 200))], timeout=5),
            ClickAction(pos=self._pos(594, 242)),  # 经验关卡
            SleepAction(3),
            ClickAction(pos=self._pos(712, 143)),
            MatchAction('btn_challenge'),
            ClickAction(pos=self._pos(757, 330)),
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            ClickAction(pos=self._pos(480, 480)),
            # SleepAction(3),
            # ClickAction(pos=self._pos(813, 230)),  # 玛娜关卡
            SleepAction(3),
            ClickAction(pos=self._pos(712, 143)),
            MatchAction('btn_challenge'),
            ClickAction(pos=self._pos(757, 330)),
            SleepAction(0.5),
            ClickAction(template='btn_ok_blue'),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            ClickAction(pos=self._pos(480, 480)),
            SleepAction(3)
        )

    @trace
    def _research(self):
        actions = [
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(template='research'),
            MatchAction('research_symbol', matched_actions=[
                ClickAction(offset=self._pos(100, 200))], timeout=5),
        ]
        # 圣迹2级
        actions += [
            ClickAction(pos=self._pos(587, 231)),
            SleepAction(1),
            ClickAction(pos=self._pos(718, 146)),
            *self.__saodang_oneshot_actions(),
            SleepAction(1),
            ClickAction(pos=self._pos(37, 33)),
            SleepAction(1)
        ]
        # 神殿2级
        actions += [
            ClickAction(pos=self._pos(800, 240)),
            SleepAction(1),
            ClickAction(pos=self._pos(718, 146)),
            *self.__saodang_oneshot_actions(),
            SleepAction(1)
        ]
        # # 神殿1级
        # actions += [
        #     ClickAction(pos=self._pos(718, 259)),
        #     *self.__saodang_oneshot_actions()
        # ]
        self._action_squential(*actions)

    @trace
    def _arena(self):
        self._action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(pos=self._pos(587, 411)),
            SleepAction(3),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=1),
            ClickAction(pos=self._pos(295, 336)),
            MatchAction(template='btn_ok', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=self._pos(665, 186)),
            SleepAction(3),
            ClickAction(pos=self._pos(849, 454)),
            SleepAction(2),
            MatchAction(template='btn_arena_skip', matched_actions=[ClickAction()], timeout=5),
            MatchAction(['btn_next_step_small', 'btn_next_step'], matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
        )

    @trace
    def _princess_arena(self):
        self._action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
            SleepAction(2),
            ClickAction(pos=self._pos(836, 409)),
            SleepAction(3),
            MatchAction(template='btn_cancel', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=1),
            ClickAction(pos=self._pos(295, 336)),
            MatchAction(template='btn_ok', matched_actions=[
                ClickAction(), SleepAction(1)], timeout=2),
            ClickAction(pos=self._pos(665, 186)),
            SleepAction(3),
            ClickAction(pos=self._pos(849, 454)),
            SleepAction(1),
            ClickAction(pos=self._pos(849, 454)),
            SleepAction(1),
            ClickAction(pos=self._pos(849, 454)),
            SleepAction(2),
            MatchAction(template='btn_arena_skip', matched_actions=[ClickAction()], timeout=10),
            MatchAction(['btn_next_step_small', 'btn_next_step'], matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close')]),
        )

    @trace
    def _dungeon_saodang(self, difficulty=6, monster_team=1, boss_group='1', boss_team='2,3', withdraw=False, skipable=True):
        '''
        大号用来过地下城
        '''
        level = [7, 0, 0, 5, 5, 5, 5][difficulty-1]
        actions = []
        actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close')]))
        actions.append(SleepAction(2))
        actions.append(ClickAction(template='dungeon'))
        actions.append(SleepAction(2))
        if difficulty <= 3:
            actions.append(ClickAction(pos=self._pos(10, 248)))
            dungeon_pos = DUNGEON_LOCATION[difficulty - 1]
        else:
            actions.append(ClickAction(pos=self._pos(944, 248)))
            dungeon_pos = DUNGEON_LOCATION[difficulty - 4]
        actions.append(SleepAction(2))
        actions.append(MatchAction('dungeon_symbol', matched_actions=[
                       ClickAction(offset=self._pos(*dungeon_pos))], timeout=5))  # 确认进入地下城
        if skipable:
            actions.append(IfCondition("btn_dungeon_skip", meet_actions=[
                ClickAction("btn_dungeon_skip"),
                SleepAction(0.5),
                MatchAction(template='btn_skip_ok', matched_actions=[
                            ClickAction()], timeout=2, delay=0.1),
                SleepAction(0.5),
                MatchAction(template='btn_ok', matched_actions=[
                            ClickAction()], timeout=2, delay=0.1),
                ThrowErrorAction("Skip dungeon done!!"), # 跳过后续流程
            ]))
        actions.append(MatchAction(
            'btn_ok_blue', matched_actions=[ClickAction()], timeout=5))
        actions.append(SleepAction(3))
        actions.append(MatchAction('in_dungeon_symbol'))
        actions.append(SleepAction(3))
        for i in range(1, level + 1):
            if i == level:
                # boss 关卡
                pos = DUNGEON_LEVEL_POS[difficulty - 1][i - 1]
                boss_team = boss_team.split(',')
                for team in boss_team:
                    if not team:
                        continue
                    team = int(team)
                    meet_actions = [
                        ClickAction(pos=self._pos(*pos)),
                        SleepAction(3),
                        ClickAction(
                            template='btn_challenge_dungeon'),
                        SleepAction(3),
                        ClickAction(pos=self._pos(
                            866, 86)),  # 点击我的队伍
                        SleepAction(3),
                    ]
                    if boss_group:
                        meet_actions += [
                            ClickAction(pos=self._pos(
                                *TEAM_GROUP_LOCATION[(int(boss_group) - 1) % len(TEAM_GROUP_LOCATION)])),
                            SleepAction(2),
                        ]
                    if team <= 3:
                        meet_actions += [
                            ClickAction(pos=self._pos(
                                *TEAM_LOCATION[team - 1]))
                        ]
                    elif team <= 6:
                        meet_actions += [
                            SleepAction(1),
                            SwipeAction(self._pos(440, 419),
                                        self._pos(440, 140),400),
                            SleepAction(1),
                            ClickAction(pos=self._pos(
                                *TEAM_LOCATION[(team - 3 - 1)]))
                        ]
                    elif team <= 9:
                        meet_actions += [
                            SleepAction(1),
                            SwipeAction(self._pos(440, 419),
                                        self._pos(440, 140),400),
                            SleepAction(1),
                            SwipeAction(self._pos(440, 419),
                                        self._pos(440, 140),400),
                            SleepAction(1),
                            ClickAction(pos=self._pos(
                                *TEAM_LOCATION[(team - 6 - 1)]))
                        ]
                    else:
                        meet_actions += [
                            SleepAction(1),
                            SwipeAction(self._pos(440, 419),
                                        self._pos(440, 140),400),
                            SleepAction(1),
                            SwipeAction(self._pos(440, 419),
                                        self._pos(440, 140),400),
                            SleepAction(1),
                            SwipeAction(self._pos(440, 419),
                                        self._pos(440, 140),400),
                            SleepAction(1),
                            ClickAction(pos=self._pos(796, 371))  # 暂时特殊给到
                        ]
                    meet_actions += [
                        SleepAction(2),
                        ClickAction(pos=self._pos(
                            832, 453)),  # 进战斗界面
                        SleepAction(10),
                        MatchAction('btn_damage_report', unmatch_actions=[
                            ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]),
                        SleepAction(3),
                        ClickAction(pos=self._pos(800, 500)),
                        SleepAction(5),
                        MatchAction(template='btn_ok', matched_actions=[
                                    ClickAction(), SleepAction(8)], timeout=2),
                        SleepAction(3),
                    ]
                    actions.append(IfCondition(
                        'in_dungeon_symbol', meet_actions=meet_actions))
            else:
                pos = DUNGEON_LEVEL_POS[difficulty - 1][i - 1]
                actions.append(ClickAction(pos=self._pos(*pos)))
                actions.append(SleepAction(3))
                actions.append(ClickAction(
                    template='btn_challenge_dungeon'))
                if i == 1:
                    actions.append(SleepAction(3))
                    actions.append(ClickAction(
                        pos=self._pos(866, 86)))  # 点击我的队伍
                    actions.append(SleepAction(3))
                    actions.append(ClickAction(
                        pos=self._pos(*TEAM_LOCATION[monster_team-1])))
                actions.append(SleepAction(3))
                actions.append(ClickAction(
                    pos=self._pos(832, 453)))  # 进入战斗
                actions.append(SleepAction(10))
                actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                    ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]))
                actions.append(SleepAction(8))
                actions.append(ClickAction(template='btn_ok'))
                actions.append(SleepAction(5))
        if withdraw:
            actions.append(MatchAction('in_dungeon_symbol'))
            actions.append(ClickAction(template='btn_withdraw'))
            actions.append(ClickAction(template='btn_ok_blue'))
        self._action_squential(*actions)

    @ trace
    def _dungeon_mana(self, difficulty=1, level=0, support=1, withdraw=True):
        '''
        进入地下城，送mana
        '''
        actions = []
        actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close')]))
        actions.append(SleepAction(2))
        actions.append(ClickAction(template='dungeon'))
        actions.append(SleepAction(2))
        if difficulty == 1:
            actions.append(ClickAction(pos=self._pos(10, 248)))
            dungeon_pos = DUNGEON_LOCATION[difficulty - 1]
        else:
            actions.append(ClickAction(pos=self._pos(944, 248)))
            dungeon_pos = DUNGEON_LOCATION[difficulty - 2]
        actions.append(SleepAction(2))
        actions.append(MatchAction('dungeon_symbol', matched_actions=[
                       ClickAction(offset=self._pos(*dungeon_pos))], timeout=5))  # 确认进入地下城
        actions.append(MatchAction(
            'btn_ok_blue', matched_actions=[ClickAction()], timeout=5))
        actions.append(SleepAction(3))
        actions.append(MatchAction('in_dungeon_symbol'))
        actions.append(ClickAction(pos=self._pos(
            DUNGEON_LEVEL_POS[difficulty - 1][0])))
        actions.append(ClickAction(template='btn_challenge_dungeon'))
        actions.append(SleepAction(1))  # 选择4个人物
        actions.append(ClickAction(pos=self._pos(105, 170)))
        actions.append(ClickAction(pos=self._pos(224, 170)))
        actions.append(ClickAction(pos=self._pos(315, 170)))
        actions.append(ClickAction(pos=self._pos(432, 170)))
        actions.append(ClickAction(pos=self._pos(478, 89)))  # 点击支援
        actions.append(SleepAction(1))
        yoffset = 110 * ((support - 1) // 8)
        xoffset = 100 * ((support - 1) % 8)
        actions.append(ClickAction(
            pos=self._pos(105 + xoffset, 170 + yoffset)))
        actions.append(ClickAction(pos=self._pos(832, 453)))  # 进入战斗
        actions.append(MatchAction(
            'btn_ok_blue', matched_actions=[ClickAction()], timeout=5))
        actions.append(SleepAction(3))
        if level == 0:
            actions.append(MatchAction(
                'btn_caidan', matched_actions=[ClickAction()]))
            actions.append(ClickAction(template='btn_give_up'))
            actions.append(ClickAction(template='btn_give_up_blue'))
            actions.append(SleepAction(3))
        else:
            for i in range(1, level + 1):
                if i != 1:
                    pos = DUNGEON_LEVEL_POS[difficulty - 1][i - 1]
                    actions.append(ClickAction(pos=self._pos(*pos)))
                    actions.append(ClickAction(
                        template='btn_challenge_dungeon'))
                    actions.append(SleepAction(1))
                    actions.append(ClickAction(
                        pos=self._pos(832, 453)))  # 进入战斗
                actions.append(SleepAction(10))
                actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                    ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]))
                actions.append(SleepAction(6))
                actions.append(ClickAction(template='btn_ok'))
                actions.append(SleepAction(3))

        if withdraw:
            actions.append(MatchAction('in_dungeon_symbol'))
            actions.append(ClickAction(template='btn_withdraw'))
            actions.append(ClickAction(template='btn_ok_blue'))
        self._action_squential(*actions)

    @ trace
    def _guild_battle(self, count=1, support=1):
        '''
        公会战
        '''
        self._action_squential(
            ClickAction(template="tab_adventure"),
            ClickAction(template="btn_guild_battle"),
            MatchAction("guild_battle_symbol", unmatch_actions=[ClickAction(
                template='btn_close'), ClickAction(template='btn_ok')], threshold=0.6),
            MatchAction("shop", unmatch_actions=[
                        ClickAction(template='btn_close'), ClickAction(template='btn_ok'), ClickAction(pos=self._pos(480, 46))], timeout=10),
        )
        actions = []
        retry_count = 0
        activate_boss_pos = None
        while retry_count < 10 and not activate_boss_pos:
            activate_boss_pos = self._find_match_pos(
                self.driver.screenshot(), 'guild_boss_indicator', threshold=0.6)
            sleep(0.2)
            retry_count += 1
        self._log(
            f"get activate boss pos {activate_boss_pos[0]} , {activate_boss_pos[1]}")
        boss_pos = (activate_boss_pos[0], activate_boss_pos[1]+110)
        for i in range(count):
            actions.append(ClickAction(pos=self._pos(*boss_pos)))
            actions.append(SleepAction(2))
            if i == 0:
                actions.append(MatchAction("shop",
                                           unmatch_actions=[ClickAction(template='btn_close'), ClickAction(pos=self._pos(480, 46))], timeout=3))
            actions.append(ClickAction(template="btn_challenge"))
            # 移除当前队伍人物
            if i == 0:
                actions.append(ClickAction(pos=self._pos(87, 447)))
            else:
                for j in range(5):
                    actions.append(ClickAction(
                        pos=self._pos(87 + 110 * j, 447)))
            actions.append(SleepAction(3))
            actions.append(ClickAction(pos=self._pos(478, 89)))  # 点击支援
            actions.append(SleepAction(1))
            yoffset = 110 * ((support + i - 1) // 8)
            xoffset = 100 * ((support + i - 1) % 8)
            actions.append(ClickAction(
                pos=self._pos(105 + xoffset, 170 + yoffset)))
            actions.append(ClickAction(pos=self._pos(832, 453)))  # 进入战斗
            actions.append(MatchAction(
                'btn_ok_blue', matched_actions=[ClickAction()], timeout=5))
            actions.append(MatchAction(
                'btn_battle', matched_actions=[ClickAction()], timeout=3))
            actions.append(SleepAction(20))
            actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
                ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]))
            actions.append(SleepAction(5))
        self._action_squential(*actions)

    @ trace
    def _skip_guide_1_4(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            ClickAction(template='btn_no_voice'),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction('chapter1', unmatch_actions=[
                        ClickAction(pos=self._pos(480, 220))])
        )

    @ trace
    def _skip_guide_1_6(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            ClickAction(template='btn_no_voice'),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction(template='btn_menu', matched_actions=[
                        ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(480, 270))]),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            SleepAction(1),
            MatchAction(template='btn_skip_ok', matched_actions=[
                        ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(480, 270))]),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction('chapter1', unmatch_actions=[
                        ClickAction(pos=self._pos(480, 220))])
        )

    @ trace
    def _skip_guide_2_1(self):
        self._action_squential(
            self._create_skip_guide_action(),
            SleepAction(1),
            ClickAction(template='btn_menu'),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            self._create_skip_guide_action(),
            ClickAction(template="btn_close")
        )
        # 回首页，这里稍微绕下远
        self._tohomepage()
        # 再回到冒险页面
        self._enter_advanture()

    @ trace
    def _skip_guide_2_2(self):
        self._action_squential(
            self._create_skip_guide_action(),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=10)  # 为了点几下屏幕没有好的标志位
        )
        # 再回到冒险页面
        self._enter_advanture()

    @ trace
    def _skip_guide_2_5(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=5)  # 为了点几下屏幕没有好的标志位
        )
        # 回首页，这里稍微绕下远
        self._tohomepage()
        # 再去冒险
        self._enter_advanture()

    @ trace
    def _skip_guide_2_8(self):
        self._action_squential(
            self._create_skip_guide_action(
                template='arrow_down_short', offset=(0, 50)),
        )
        # 回首页，这里稍微绕下远
        self._tohomepage()
        # 再去冒险
        self._enter_advanture()

    @ trace
    def _skip_guide_2_12(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(template='arrow_down_dungeon'),
            MatchAction('btn_menu', matched_actions=[
                        ClickAction()], unmatch_actions=[ClickAction(pos=self._pos(480, 270))]),
            ClickAction(template='btn_skip_with_text'),
            ClickAction(template='btn_skip_ok'),
            MatchAction('in_dungeon_symbol', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))]),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=5),
            SleepAction(1),
            ClickAction(pos=self._pos(806, 432)),
            ClickAction(template='btn_ok_blue'),
        )
        # 回首页，这里稍微绕下远
        self._tohomepage(timeout=10)
        self._action_squential(
            MatchAction('to_activity', matched_actions=[
                        ClickAction()], timeout=5),
            SleepAction(3),
            ClickAction(pos=self._pos(362, 374))
        )
        # 再去冒险
        self._enter_advanture()
        self._action_squential(
            MatchAction('btn_close', matched_actions=[
                        ClickAction()], timeout=5)
        )

    @ trace
    def _skip_guide_3_1(self):
        self._action_squential(
            self._create_skip_guide_action(),
            self._create_skip_guide_action(),
            MatchAction('quest', unmatch_actions=[
                        ClickAction(pos=self._pos(310, 50))], timeout=5)  # 为了点几下屏幕没有好的标志位
        )
        # 再去冒险
        self._enter_advanture()

    def _create_skip_guide_action(self, template='arrow_down', offset=(0, 100), threshold=(7/8)*THRESHOLD) -> Action:
        return MatchAction(template, matched_actions=[ClickAction(offset=(
            self._pos(*offset))), SleepAction(3)], unmatch_actions=[ClickAction(pos=self._pos(100, 180))], threshold=threshold)

    def _pos(self, x, y) -> Tuple[int, int]:
        return(int((x/BASE_WIDTH)*self.devicewidth), int((y/BASE_HEIGHT)*self.deviceheight))

    def _roi(self, left, top, right, bottom) -> Tuple[int, int, int, int]:
        return (*self._pos(left, top), *self._pos(right, bottom))

    def _action_squential(self, *actions: Iterable[Action], delay=0.2, net_error_check=True):
        for action in actions:
            action_start_time = time.time()
            while not action.done():
                screenshot = self.driver.screenshot()
                action.do(screenshot, self)
                if delay > 0:
                    time.sleep(delay)
                if net_error_check and time.time() - action_start_time > 10:
                    # 如果一个任务检测超过10s，校验是否存在网络异常
                    net_error = self._find_match_pos(screenshot, "btn_return_title_blue")
                    if not net_error:
                        net_error = self._find_match_pos(screenshot, "btn_return_title_white")
                    if net_error:
                        self.driver.click(*net_error)
                        raise NetError()

    def _find_match_pos(self, screenshot, template, threshold=THRESHOLD, mode=None, base_width=BASE_WIDTH, base_height=BASE_HEIGHT) -> Tuple[int, int]:
        return self._find_match_pos_list(screenshot, template, threshold, mode, base_width, base_height, 1)
    
    def _find_match_pos_list(self, screenshot, template, threshold=THRESHOLD, mode=None, base_width=BASE_WIDTH, base_height=BASE_HEIGHT, ret_count=0, for_test=False) -> Iterable[Tuple[int,int]]:
        name = template
        source: np.ndarray
        if isinstance(screenshot, np.ndarray):
            source = screenshot
        else:
            source = cv.imread(screenshot)
        template: np.ndarray = cv.imread("images/{}.png".format(template))
        # 这里需要对template resize，template是在960x540的设备上截屏的
        height, width = source.shape[:2]
        theight, twidth = template.shape[:2]
        fx = width/base_width
        fy = height/base_height
        template = cv.resize(template, None, fx=fx, fy=fy,
                             interpolation=cv.INTER_AREA)
        theight, twidth = template.shape[:2]
        if mode:
            if mode == 'binarization':
                source = cv.cvtColor(source, cv.COLOR_BGR2GRAY)
                _, source = cv.threshold(source, 220, 255, cv.THRESH_BINARY)
                template = cv.cvtColor(template, cv.COLOR_BGR2GRAY)
                _, template = cv.threshold(template, 220, 255, cv.THRESH_BINARY)
            elif mode == 'canny':
                source = cv.Canny(source, 180, 220)
                template = cv.Canny(template, 180, 220)
        ret = cv.matchTemplate(source, template, cv.TM_CCOEFF_NORMED)
        if ret_count == 1:
            min_val, max_val, min_loc, max_loc = cv.minMaxLoc(ret)
            # self._log("{}:{}:{}".format(name, max_val, threshold))
            if max_val > threshold:
                return (max_loc[0] + twidth/2, max_loc[1] + theight/2)
            else:
                return None
        else:
            index_array = np.where(ret > threshold)
            matched_points = []
            for x, y in zip(*index_array[::-1]):
                duplicate = False
                for point in matched_points:
                    if abs(point[0] - x) < 8 and abs(point[1] - y) < 8:
                        duplicate = True
                    break
                if not duplicate:
                    matched_points.append((x,y))
            if matched_points:
                if for_test:
                    matched_points = list(map(lambda point: ((point[0] + twidth/2, point[1] + theight/2),ret[point[1],point[0]]), matched_points))
                else:
                    matched_points = list(map(lambda point: (point[0] + twidth/2, point[1] + theight/2), matched_points))
                if ret_count > 0:
                    return matched_points[:ret_count]
                else:
                    return matched_points
            else:
                return None
