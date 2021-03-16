from .constants import *
import time

class Action:
    def __init__(self):
        super().__init__()
        self._done = False

    def do(self, screenshot, robot):
        self._done = True

    def done(self) -> bool:
        return self._done
    

class MatchAction(Action):
    def __init__(self, template, matched_actions=None, unmatch_actions=None, delay=1, timeout=0, threshold=THRESHOLD):
        super().__init__()
        self.template = template
        self.matched_actions = matched_actions
        self.unmatch_action = unmatch_actions
        self.delay = delay
        self.threshold = threshold
        self.timeout = timeout
        self.starttime = 0

    def do(self, screenshot, robot):
        if self.starttime == 0:
            self.starttime = time.time()
        if self.delay > 0:
            time.sleep(self.delay)
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
    def __init__(self, template=None, pos=None, offset=(0, 0), threshold=THRESHOLD):
        super().__init__()
        self.template = template
        self.pos = pos
        self.offset = offset
        self.threshold = threshold

    def do(self, screenshot, robot):
        if self.template:
            ret = robot._find_match_pos(
                screenshot, self.template, threshold=self.threshold)
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

    def do(self, screenshot, robot):
        robot.driver.input(self._text)
        self._done = True


class SwipeAction(Action):
    def __init__(self, start, end, duration):
        super().__init__()
        self.start = start
        self.end = end
        self.duration = duration

    def do(self, screenshot, robot):
        robot.driver.swipe(self.start, self.end, self.duration)
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