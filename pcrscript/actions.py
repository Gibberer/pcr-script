from .constants import *
from typing import Tuple
import time

class Action:
    def __init__(self):
        super().__init__()
        self._done = False
        self.task = None
    
    def bindTask(self, task):
        self.task = task

    def do(self, screenshot, robot):
        self._done = True

    def done(self) -> bool:
        return self._done
    
    def _pos(self, robot, x, y) -> Tuple[int, int]:
        if self.task:
            device_width = robot.devicewidth
            device_height = robot.deviceheight
            base_width = self.task.define_width
            base_height = self.task.define_height
            return(int((x/base_width)*device_width), int((y/base_height)*device_height))
        return (x, y)

class MatchAction(Action):
    def __init__(self, template, matched_actions=None, unmatch_actions=None, delay=1, timeout=0, threshold=THRESHOLD, match_text=None):
        super().__init__()
        self.template = template
        self.matched_actions = matched_actions
        self.unmatch_action = unmatch_actions
        self.delay = delay
        self.threshold = threshold
        self.timeout = timeout
        self.starttime = 0
        self.match_text = match_text
        self.is_timeout = False

    def do(self, screenshot, robot):
        if self.starttime == 0:
            self.starttime = time.time()
        if self.delay > 0:
            time.sleep(self.delay)
        ret = None
        if self.match_text and robot.ocr:
            ret = robot.ocr.find_match_text_pos(screenshot, self.match_text)
        elif isinstance(self.template, list):
            for temp in self.template:
                ret = robot._find_match_pos(
                    screenshot, temp, threshold=self.threshold)
                if ret:
                    break
        else:
            ret = robot._find_match_pos(
                screenshot, self.template, threshold=self.threshold)
        if ret:
            if self.matched_actions:
                for action in self.matched_actions:
                    if hasattr(action, 'pos') and action.pos is None:
                        action.pos = ret
                    action.do(screenshot, robot)
            self._done = True
        elif self.unmatch_action:
            for action in self.unmatch_action:
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
    def __init__(self, template=None, pos=None, offset=(0, 0), threshold=THRESHOLD, mode=None, match_text=None):
        super().__init__()
        self.template = template
        self.pos = pos
        self.offset = offset
        self.threshold = threshold
        self.mode = mode
        self.match_text = match_text

    def do(self, screenshot, robot):
        if self.template or self.match_text:
            if self.match_text and robot.ocr:
                ret = robot.ocr.find_match_text_pos(screenshot, self.match_text)
            else:
                ret = robot._find_match_pos(
                    screenshot, self.template, threshold=self.threshold, mode=self.mode)
            if ret:
                offset = self._pos(robot, *self.offset)
                robot.driver.click(ret[0] + offset[0],
                                   ret[1] + offset[1])
                self._done = True
        else:
            if self.pos:
                pos = self._pos(robot, *self.pos)
                offset = self._pos(robot, *self.offset)
                robot.driver.click(pos[0] + offset[0],
                                   pos[1] + offset[1])
            self._done = True


class InputAction(Action):
    def __init__(self, text):
        super().__init__()
        self._text = text

    def do(self, screenshot, robot):
        robot.driver.input(self._text)
        self._done = True


class SwipeAction(Action):
    def __init__(self, start, end, duration = ''):
        super().__init__()
        self.start = start
        self.end = end
        self.duration = duration

    def do(self, screenshot, robot):
        robot.driver.swipe(self._pos(robot, *self.start), self._pos(robot, *self.end), self.duration)
        self._done = True


class IfCondition(CanSkipMatchAction):
    def __init__(self, condition_template, meet_actions: [Action] = None, unmeet_actions: [Action] = None, threshold=THRESHOLD):
        super().__init__()
        self._condition_template = condition_template
        self._threshold = threshold
        self._meet_actions = meet_actions
        self._unmeet_actions = unmeet_actions

    def do(self, screenshot, robot):
        ret = robot._find_match_pos(
            screenshot, self._condition_template, threshold=self._threshold)
        if ret:
            if self._meet_actions:
                for action in self._meet_actions:
                    action._done = False
                    if isinstance(action, SkipAction):
                        self.skip = True
                robot._action_squential(*self._meet_actions)
        else:
            if self._unmeet_actions:
                for action in self._unmeet_actions:
                    action._done = False
                    if isinstance(action, SkipAction):
                        self.skip = True
                robot._action_squential(*self._unmeet_actions)
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
                robot._action_squential(*self._meet_actions)
        else:
            if self._unmeet_actions:
                for action in self._unmeet_actions:
                    action._done = False
                robot._action_squential(*self._unmeet_actions)
        self._done = True