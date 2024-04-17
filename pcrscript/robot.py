from .driver import Driver
from .actions import *
from .constants import *
from .error import NetError
import cv2 as cv
import numpy as np
import time
from typing import Iterable, Tuple
from .tasks import registedTasks, BaseTask
import functools
import random
import collections
import copy


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
        self.driver = driver
        self.devicewidth, self.deviceheight = driver.getScreenSize()
        global num
        if not name:
            name = "Robot#{}".format(num)
            num += 1
        self._name = name

    @trace
    def changeaccount(self, account=None, password=None, logpath=None):
        if logpath:
            with open(logpath, 'a') as f:
                f.write("{}:{}\n".format(self._name, account))
        while True:
            screenshot = self.driver.screenshot()
            if self._find_match_pos(screenshot, 'welcome_main_menu'):
                if account:
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
                    self._action_squential(ClickAction(pos=self._pos(30,200)))
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
                        SleepAction(1),
                        ClickAction(template='btn_back_welcome'),
                        SleepAction(1),
                        ClickAction(template='btn_ok_blue')
                    )
                ret = self._find_match_pos(
                    screenshot, 'btn_back_welcome')
                if ret:
                    self._action_squential(
                        ClickAction(template='btn_back_welcome'),
                        SleepAction(1),
                        ClickAction(template='btn_ok_blue')
                    )
                ClickAction(pos=self._pos(50, 300)).do(screenshot, self)
            time.sleep(3)

    def _first_enter_check(self):
        pos = random.choice(((199, 300), (400, 300), (590, 300), (790, 300)))
        self._action_squential(MatchAction('shop', unmatch_actions=(
            ClickAction(template='btn_close'),
            ClickAction(template="btn_ok_blue"),
            ClickAction(template="btn_download"),
            ClickAction(template='btn_skip'),
            ClickAction(template='btn_cancel'),
            ClickAction(template='select_branch_first'),
            ClickAction(pos=self._pos(90, 500)),
            # 处理兰德索尔杯的情况
            IfCondition(condition_template="symbol_landsol_cup", meet_actions=[
                ClickAction(pos=self._pos(*pos)),
                SleepAction(2),
                ClickAction(pos=self._pos(838, 494))
            ])
        ), timeout=0), net_error_check=False)
        time.sleep(3)
        ClickAction(template='btn_close').do(self.driver.screenshot(), self)

    @trace
    def work(self, tasklist=None):
        tasklist = tasklist[:]
        pretasks = []
        taskcount = len(tasklist)
        for i in range(taskcount - 1, -1, -1):
            if tasklist[i][0] in ('real_name_auth', 'landsol_cup'):
                if tasklist[i][0] != 'landsol_cup':
                    pretasks.insert(0, tasklist[i])
                tasklist.pop(i)
        if pretasks:
            for funcname, *args in pretasks:
                getattr(self, "_" + funcname)(*args)
        self._first_enter_check()
        self._log("进入游戏首页")
        if tasklist:
            for funcname, *args in tasklist:
                if funcname in registedTasks:
                    self._runTask(funcname, registedTasks[funcname], args)
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
                if tab in (1, 8) and item.pos < 0:
                    click_pos = (860,126) # 全选按钮
                elif line == last_line:
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

    def _enter_adventure(self, difficulty=Difficulty.NORMAL, campaign=False):
        actions = []
        actions.append(MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close'), ClickAction(pos=self._pos(15, 200))]))
        actions.append(SleepAction(2))
        if campaign:
            actions.append(MatchAction(template=['story_campaign_symbol', 'story_campaign_reprint_symbol'], matched_actions=[ClickAction()]))
        else:
            actions.append(ClickAction(
                template='btn_main_plot', threshold=0.8*THRESHOLD))
        actions.append(SleepAction(2))
        unmatch_actions = [ClickAction('btn_close', threshold=0.6),
                           ClickAction('btn_skip_blue'),
                           ClickAction('btn_novocal_blue'),
                           ClickAction('symbol_menu_in_story'),
                           ClickAction('btn_skip_in_story')]
        if campaign:
            unmatch_actions += [
                IfCondition('symbol_campaign_home',
                            threshold=0.8*THRESHOLD,
                            meet_actions=[ClickAction(pos=self._pos(560, 170))],
                            unmeet_actions=[ClickAction(pos=self._pos(15, 200))])]
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
                _, source = cv.threshold(source, 220, 255, cv.THRESH_BINARY_INV)
                template = cv.cvtColor(template, cv.COLOR_BGR2GRAY)
                _, template = cv.threshold(template, 220, 255, cv.THRESH_BINARY_INV)
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
