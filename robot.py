from driver import Driver
from cv2 import cv2 as cv
import numpy as np
import time
from typing import Iterable
import functools
import random

BASE_WIDTH = 960
BASE_HEIGHT = 540
THRESHOLD = 0.8  # 如果使用960x540 匹配度一般在0.95以上,默认为0.8,,如果在480x270上可以调成0.65试试


class Action:
    def __init__(self):
        super().__init__()
        self._done = False

    def do(self, screenshot, robot):
        self._done = True

    def done(self) -> bool:
        return self._done


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
    def changeaccount(self, account, password, logpath=None):
        if logpath:
            with open(logpath, 'a') as f:
                f.write("{}:{}\n".format(self._name, account))
        while True:
            screenshot = self.driver.screenshot()
            if self._find_match_pos(screenshot, 'welcome_main_menu'):
                # 当前是欢迎页，执行登录操作
                actions = (
                    MatchAction('edit_account', matched_actions=[ClickAction(), InputAction(
                        account)], unmatch_actions=[ClickAction(pos=self._pos(900, 25))]),
                    ClickAction(template='edit_password'),
                    InputAction(password),
                    ClickAction(template='btn_login')
                )
                self._action_squential(*actions)
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
            time.sleep(3)

    @trace
    def work(self, tasklist=None):
        # self._real_name_auth()
        self._tohomepage()
        # 第一次进入的时候等下公告
        time.sleep(5)
        ClickAction(template='btn_close').do(self.driver.screenshot(), self)
        self._get_quest_reward()  # 先领取体力
        self._tohomepage()
        self._close_ub_animation()  # 关闭ub动画
        self._tohomepage()
        self._advanture_1(10, 10, 1, checkguide=True)  # 冒险一章刷10次
        self._tohomepage()
        self._get_quest_reward()  # 刷10次后再领下任务

    def _log(self, msg: str):
        print("{}: {}".format(self._name, msg))

    @trace
    def _real_name_auth(self):
        '''
        实名认证
        '''
        if 'IDS' not in locals():
            self.IDS = []
            with open('IDS.txt', mode='r', encoding='utf-8') as f:
                self.IDS = [line.strip('\n').split(' ')
                            for line in f.readlines()]
        _id, name = random.choice(self.IDS)
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
    def _tohomepage(self):
        '''
        进入游戏主页面
        '''
        self._action_squential(MatchAction('shop', unmatch_actions=(
            ClickAction(template='btn_close'),
            ClickAction(template='tab_home_page'),
            ClickAction(pos=self._pos(50, 300)),
        )))

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
            ClickAction(template = 'quest'),
            ClickAction(template= 'btn_all_rec'),
            MatchAction('btn_close', matched_actions=[
                                ClickAction()], timeout=5)
        )

    @trace
    def _get_gift(self):
        '''
        领取礼物
        '''
        pass

    @trace
    def _advanture_1(self, left, right, totalcount, checkguide=False):
        '''
        冒险主线关卡第一章
        '''
        level_pos = [(106, 281), (227, 237), (314, 331), (379, 235), (479, 294),
                     (545, 376), (611, 305), (622, 204), (749, 245), (821, 353)]
        self._action_squential(
            MatchAction('tab_adventure', matched_actions=[ClickAction()], unmatch_actions=[
                        ClickAction(template='btn_close')]),
            ClickAction(template='btn_main_plot'),
            MatchAction('chapter1', unmatch_actions=[
                        ClickAction(template="arrow_left")], timeout=10)
        )
        # 进入第一章
        check_auto = True
        count = 0
        while count < totalcount:
            for i in range(left - 1, right):
                pos = level_pos[i]
                self._combat(pos, check_auto=check_auto)
                check_auto = False
                if checkguide:
                    time.sleep(5)
                    if i == 3:
                        # ignore guide here
                        if self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                            self._skip_guide_1_4()
                    if i == 5:
                        if self._find_match_pos(self.driver.screenshot(), 'kkr_guide'):
                            self._skip_guide_1_6()
                    if i in [6, 7, 8]:
                        ClickAction(template='btn_close').do(
                            self.driver.screenshot(), self)
                else:
                    # 有可能好感度弹的剧情提示
                    time.sleep(3)
                    ClickAction(template='btn_close').do(
                        self.driver.screenshot(), self)
                self._action_squential(
                    MatchAction('chapter1', unmatch_actions=[
                        ClickAction(template="arrow_left")], timeout=10)
                )
            count += (right - left) + 1

    @trace
    def _combat(self, trigger_pos, check_auto=False):
        '''
        处理战斗界面相关
        '''
        actions = []
        actions.append(ClickAction(pos=self._pos(*trigger_pos)))
        actions.append(ClickAction(template='btn_challenge'))
        actions.append(ClickAction(template='btn_combat_start'))
        actions.append(SleepAction(5))
        if check_auto:
            actions.append(MatchAction(template='btn_caidan', matched_actions=[ClickAction(template='btn_speed'),
                                                                              ClickAction(template='btn_auto')], timeout=10))
        actions.append(SleepAction(35))
        actions.append(MatchAction('btn_next_step', matched_actions=[ClickAction()], unmatch_actions=[
            ClickAction(template='btn_close'), ClickAction(pos=self._pos(200, 250))]))
        actions.append(ClickAction('btn_next_step'))
        self._action_squential(*actions)

    @trace
    def _skip_guide_1_4(self):
        '''
        跳过1-4的引导
        '''
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

    @trace
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

    def _create_skip_guide_action(self) -> Action:
        return MatchAction('arrow_down', matched_actions=[ClickAction(offset=(
            self._pos(0, 100))), SleepAction(3)], unmatch_actions=[ClickAction(pos=self._pos(480, 270))], threshold=(7/8)*THRESHOLD)

    def _pos(self, x, y) -> (int, int):
        return(int((x/BASE_WIDTH)*self.devicewidth), int((y/BASE_HEIGHT)*self.deviceheight))

    def _action_squential(self, *actions: Iterable[Action], delay=1):
        for action in actions:
            while not action.done():
                action.do(self.driver.screenshot(), self)
                if delay > 0:
                    time.sleep(delay)

    def _find_match_pos(self, screenshot, template, threshold=THRESHOLD) -> (int, int):
        name = template
        source: np.ndarray = cv.imread(screenshot)
        template: np.ndarray = cv.imread("images/{}.png".format(template))
        # 这里需要对template resize，template是在960x540的设备上截屏的
        height, width = source.shape[:2]
        theight, twidth = template.shape[:2]
        fx = width/BASE_WIDTH
        fy = height/BASE_HEIGHT
        template = cv.resize(template, None, fx=fx, fy=fy,
                             interpolation=cv.INTER_AREA)
        theight, twidth = template.shape[:2]
        ret = cv.matchTemplate(source, template, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(ret)
        # self._log("{}:{}:{}".format(name, max_val, threshold))
        if max_val > threshold:
            return (max_loc[0] + twidth/2, max_loc[1] + theight/2)
        else:
            return None


class MatchAction(Action):
    def __init__(self, template, matched_actions=None, unmatch_actions=None, delay=0, timeout=0, threshold=THRESHOLD):
        super().__init__()
        self.template = template
        self.matched_actions = matched_actions
        self.unmatch_action = unmatch_actions
        self.delay = delay
        self.threshold = threshold
        self.timeout = timeout
        self.starttime = 0

    def do(self, screenshot, robot: Robot):
        if self.starttime == 0:
            self.starttime = time.time()
        if self.delay > 0:
            time.sleep(self.delay)
        ret = robot._find_match_pos(
            screenshot, self.template, threshold=self.threshold)
        if ret:
            if self.matched_actions:
                for action in self.matched_actions:
                    action.pos = ret
                    action.do(screenshot, robot)
            self._done = True
        elif self.unmatch_action:
            for action in self.unmatch_action:
                action.do(screenshot, robot)
        if self.timeout > 0:
            if time.time() - self.starttime > self.timeout:
                self._done = True


class SleepAction(Action):
    def __init__(self, duration):
        super().__init__()
        self.duration = duration

    def do(self, *args):
        time.sleep(self.duration)
        self._done = True


class ClickAction(Action):
    def __init__(self, template=None, pos=None, offset=(0, 0), threshold=THRESHOLD):
        super().__init__()
        self.template = template
        self.pos = pos
        self.offset = offset
        self.threshold = threshold

    def do(self, screenshot, robot: Robot):
        if self.template:
            ret = robot._find_match_pos(screenshot, self.template, threshold=self.threshold)
            if ret:
                robot.driver.click(ret[0] + self.offset[0],
                                   ret[1] + self.offset[1])
                self._done = True
        else:
            if self.pos:
                robot.driver.click(self.pos[0] + self.offset[0],
                                   self.pos[1] + self.offset[1])
            self._done = True


class InputAction(Action):
    def __init__(self, text):
        super().__init__()
        self._text = text

    def do(self, screenshot, robot: Robot):
        robot.driver.input(self._text)
        self._done = True
