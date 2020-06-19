from driver import Driver
from cv2 import cv2 as cv
import numpy as np
import time
from typing import Iterable
import functools

class Action:
    def __init__(self):
        super().__init__()

    def do(self, screenshot):
        pass

    def done(self) -> bool:
        return False

def trace(func):
    @functools.wraps(func)
    def wrapper(self,*args, **kwargs):
        self._log("start {}".format(func.__name__))
        ret = func(self, *args, **kwargs)
        self._log("end {}".format(func.__name__))
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
    def changeaccount(self, account, password):
        change_btn_pos = (self.devicewidth//16 * 15), self.deviceheight//16
        while True:
            screenshot = self.driver.screenshot()
            if self._find_match_pos(screenshot, 'welcome_main_menu'):
                while True:
                    self._log("current is main menu try login")
                    self.driver.click(*change_btn_pos)
                    if self._find_match_pos(self.driver.screenshot(), 'edit_account'):
                        # login
                        actions = (InputAction('edit_account', self, account),
                                   InputAction('edit_password',self, password),
                                   ClickAction('btn_login', self)
                                   )
                        self._action_squential(actions)
                        break
                break
            elif self._find_match_pos(screenshot, 'tab_main_menu'):
                self._action_squential(self._clickactions("tab_main_menu", "btn_back_welcome","btn_ok_blue"))
            elif self._find_match_pos(screenshot, 'tab_main_menu_selected'):
                self._action_squential(self._clickactions("btn_back_welcome","btn_ok_blue"))
    @trace
    def work(self, tasklist=None):
        self._tohomepage()
    
    def _log(self, msg:str):
        print("{}: {}".format(self._name,msg))

    @trace
    def _tohomepage(self):
        while True:
            screenshot = self.driver.screenshot()
            if self._find_match_pos(screenshot, 'tab_home_page_selected'):
                break
            else:
                self._action_squence_once(screenshot, self._clickactions('btn_close','btn_skip','tab_home_page'))
                self.driver.click(self.devicewidth * 0.3,self.deviceheight//2)

    def _clickactions(self, *templates:Iterable[str]):
        return (ClickAction(template, self) for template in templates)

    def _action_squence_once(self, screenshot, actions:Iterable[Action]):
        for action in actions:
            action.do(screenshot)

    def _action_squential(self, actions: Iterable[Action]):
        for action in actions:
            while not action.done():
                action.do(self.driver.screenshot())

    def _find_match_pos(self, screenshot, template, threshold=0.8) -> (int, int):
        name = template
        source: np.ndarray = cv.imread(screenshot)
        template: np.ndarray = cv.imread("images/{}.png".format(template))
        # 这里需要对template resize，template是在960x540的设备上截屏的
        height, width = source.shape[:2]
        theight, twidth = template.shape[:2]
        fx = width/960
        fy = height/540
        template = cv.resize(template, None, fx=fx, fy=fy, interpolation=cv.INTER_AREA)
        theight, twidth = template.shape[:2]
        ret = cv.matchTemplate(source, template, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(ret)
        # self._log("{}:{}:{}".format(name,max_val,threshold))
        if max_val > threshold:
            return (max_loc[0] + twidth/2, max_loc[1] + theight/2)
        else:
            return None


class ClickAction(Action):
    def __init__(self, template, robot: Robot, limit = 10, delay = 0):
        super().__init__()
        self._template = template
        self._robot = robot
        self._done = False
        self._limit = limit
        self._delay = delay

    def do(self, screenshot):
        ret = self._robot._find_match_pos(screenshot, self._template)
        if ret:
            self._robot.driver.click(*ret)
            if self._delay > 0:
                time.sleep(self._delay)
            self._done = True
        self._limit -= 1
        if self._limit <= 0:
            self._done = True

    def done(self):
        return self._done


class InputAction(Action):
    def __init__(self, template, robot: Robot, text: str):
        super().__init__()
        self._template = template
        self._robot = robot
        self._text = text
        self._done = False

    def do(self, screenshot):
        ret = self._robot._find_match_pos(screenshot, self._template)
        if ret:
            self._robot.driver.click(*ret)
            self._robot.driver.input(self._text)
            self._done = True

    def done(self):
        return self._done
