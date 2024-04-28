from .constants import *
from typing import Tuple,TYPE_CHECKING
from .templates import Template,ImageTemplate
import time

if TYPE_CHECKING:
    from pcrscript import Robot
    from tasks import BaseTask
class Action:
    def __init__(self):
        super().__init__()
        self._done = False
        self.task:'BaseTask' = None
    
    def bindTask(self, task):
        self.task = task
        return self

    def do(self, screenshot, robot:'Robot'):
        self._done = True

    def done(self) -> bool:
        return self._done
    
    def _pos(self, robot:'Robot', x, y) -> Tuple[int, int]:
        if self.task:
            device_width = robot.devicewidth
            device_height = robot.deviceheight
            base_width = self.task.define_width
            base_height = self.task.define_height
            return(int((x/base_width)*device_width), int((y/base_height)*device_height))
        return (x, y)

    def _match(self, screenshot, template:Template)->Template:
        if self.task:
            template.set_define_size(self.task.define_width, self.task.define_height)
        return template.match(screenshot)

class MatchAction(Action):
    def __init__(self, template, matched_actions:list['Action']=None, unmatch_actions:list['Action']=None, delay=1, timeout=0):
        super().__init__()
        self.template = template
        self.matched_actions = matched_actions
        self.unmatch_action = unmatch_actions
        self.delay = delay
        self.timeout = timeout
        self.starttime = 0
        self.is_timeout = False

    def do(self, screenshot, robot):
        if self.starttime == 0:
            self.starttime = time.time()
        if self.delay > 0:
            time.sleep(self.delay)
        ret = None
        if not isinstance(self.template, list):
            self.template = [self.template]
        for template in self.template:
            if not isinstance(template, Template):
                template = ImageTemplate(template)
            ret = self._match(screenshot, template)
            if ret:
                break
        if ret:
            if self.matched_actions:
                for action in self.matched_actions:
                    action.bindTask(self.task)
                    if hasattr(action, 'pos') and action.pos is None:
                        # 将基于屏幕获取的坐标转换为定义的坐标
                        device_width = robot.devicewidth
                        device_height = robot.deviceheight
                        base_width = self.task.define_width
                        base_height = self.task.define_height
                        action.pos = (int((ret[0]/device_width)*base_width), int((ret[1]/device_height)*base_height))
                    action.do(screenshot, robot)
            self._done = True
        elif self.unmatch_action:
            for action in self.unmatch_action:
                action.bindTask(self.task)
                action.do(screenshot, robot)
                if isinstance(action, CanSkipMatchAction):
                    if action.skip:
                        self._done = True
                        break
        if self.timeout > 0:
            if time.time() - self.starttime > self.timeout:
                self.is_timeout = True
                self._done = True


class CanSkipMatchAction(Action):
    def __init__(self, skip=False):
        super().__init__()
        self.skip = skip


class SkipAction(CanSkipMatchAction):
    def __init__(self):
        super().__init__(True)


class ThrowErrorAction(SkipAction):
    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    def do(self, *args):
        raise Exception(self.msg)
        self._done = True


class SleepAction(Action):
    def __init__(self, duration):
        super().__init__()
        self.duration = duration

    def do(self, *args):
        time.sleep(self.duration)
        self._done = True


class ClickAction(Action):
    def __init__(self, template=None, pos=None, offset=(0, 0), roi=None, timeout=0):
        super().__init__()
        self.template = template
        self.pos = pos
        self.offset = offset
        self.timeout = timeout
        self.starttime = 0
        self.roi = roi

    def do(self, screenshot, robot):
        if self.starttime == 0:
            self.starttime = time.time()
        if self.template:
            if not isinstance(self.template, Template):
                self.template = ImageTemplate(self.template)
            ret = self._match(screenshot, self.template)
            if ret:
                ignore = False
                if self.roi:
                    lt = self._pos(robot, self.roi[0], self.roi[1])
                    rb = self._pos(robot, self.roi[2], self.roi[3])
                    if ret[0] < lt[0] or ret[0] > rb[0] or ret[1] < lt[1] or ret[1] > rb[1]:
                        ignore = True
                if not ignore:
                    offset = self._pos(robot, *self.offset)
                    robot.driver.click(ret[0] + offset[0], ret[1] + offset[1])
                self._done = True
        else:
            if self.pos:
                pos = self._pos(robot, *self.pos)
                offset = self._pos(robot, *self.offset)
                robot.driver.click(pos[0] + offset[0],
                                   pos[1] + offset[1])
            self._done = True
        if self.timeout > 0:
            if time.time() - self.starttime > self.timeout:
                self._done = True


class InputAction(Action):
    def __init__(self, text):
        super().__init__()
        self._text = text

    def do(self, screenshot, robot):
        robot.driver.input(self._text)
        self._done = True


class SwipeAction(Action):
    def __init__(self, start, end, duration = 200):
        super().__init__()
        self.start = start
        self.end = end
        self.duration = duration

    def do(self, screenshot, robot):
        robot.driver.swipe(self._pos(robot, *self.start), self._pos(robot, *self.end), self.duration)
        self._done = True


class IfCondition(CanSkipMatchAction):
    def __init__(self, condition_template, meet_actions: list[Action] = None, unmeet_actions: list[Action] = None):
        super().__init__()
        self._condition_template = condition_template
        self._meet_actions = meet_actions
        self._unmeet_actions = unmeet_actions

    def do(self, screenshot, robot):
        if not isinstance(self._condition_template, Template):
            self._condition_template = ImageTemplate(self._condition_template)
        ret = self._match(screenshot, self._condition_template)
        if ret:
            if self._meet_actions:
                for action in self._meet_actions:
                    action._done = False
                    action.bindTask(self.task)
                    if isinstance(action, SkipAction):
                        self.skip = True
                robot.action_squential(*self._meet_actions)
        else:
            if self._unmeet_actions:
                for action in self._unmeet_actions:
                    action._done = False
                    action.bindTask(self.task)
                    if isinstance(action, SkipAction):
                        self.skip = True
                robot.action_squential(*self._unmeet_actions)
        self._done = True

class CustomIfCondition(Action):

    def __init__(self, condition_function, *args, meet_actions=None, unmeet_actions=None):
        super().__init__()
        self._condition_function = condition_function
        self._args = args
        self._meet_actions = meet_actions
        self._unmeet_actions = unmeet_actions

    def do(self, screenshot, robot):
        ret = self._condition_function(screenshot, *self._args)
        if ret:
            if self._meet_actions:
                for action in self._meet_actions:
                    action._done = False
                    action.bindTask(self.task)
                robot.action_squential(*self._meet_actions)
        else:
            if self._unmeet_actions:
                for action in self._unmeet_actions:
                    action._done = False
                    action.bindTask(self.task)
                robot.action_squential(*self._unmeet_actions)
        self._done = True