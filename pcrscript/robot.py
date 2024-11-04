import functools
import random
import time
from tqdm import tqdm

from .driver import Driver
from .actions import *
from .constants import *
from .tasks import find_taskclass, BaseTask, ToHomePage
from .templates import ImageTemplate


def trace(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        self._log("start {}".format(func.__name__.lstrip('_')))
        ret = func(self, *args, **kwargs)
        self._log("end {}".format(func.__name__.lstrip('_')))
        return ret
    return wrapper


num = 0

class NetError(Exception):
    def __str__(self):
        return "发生网络异常!!!"

class _DummyTask(BaseTask):

    def run(self, *args):
        pass
    
class Robot:
    def __init__(self, driver: Driver, name=None, show_progress=True):
        super().__init__()
        self.driver = driver
        self.devicewidth, self.deviceheight = driver.get_screen_size()
        self.show_progress = show_progress
        self._dummy_task = _DummyTask(self)
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
            dialog = None
            for name in ('app_no_responed','btn_close','btn_download','btn_cancel'):
                dialog = self.__find_match_pos(screenshot, name)
                if dialog:
                    self.driver.click(*dialog)
                    break
            if dialog:
                time.sleep(1)
                continue
            if self.__find_match_pos(screenshot, 'welcome_main_menu'):
                if account:
                    # 当前是欢迎页，执行登录操作
                    actions = (
                        MatchAction('btn_change_account', matched_actions=[
                                    ClickAction()], unmatch_actions=[ClickAction(pos=(850, 30))], delay=0),
                        SleepAction(0.5),
                        ClickAction(pos=(354,374)),
                        SleepAction(0.5),
                        ClickAction(template='symbol_bilibili_logo'),
                        ClickAction(template='edit_account'),
                        InputAction(account),
                        ClickAction(template='edit_password'),
                        InputAction(password),
                        ClickAction(template='btn_login'),
                        SleepAction(5)  # 延迟下，后续需要判断是否出现用户协议弹窗
                    )
                    self.__action_squential(*actions)
                    # 执行登录操作之后判断是否出现用户协议
                    while self.__find_match_pos(self.driver.screenshot(), 'user_agreement_symbol'):
                        self.__action_squential(
                            ClickAction(pos=(704, 334)),  # 滑动到底部
                            SleepAction(2),
                            ClickAction(pos=(536, 388)),  # 点击同意
                            SleepAction(2)
                        )
                    break
                else:
                    self.__action_squential(ClickAction(pos=(30,200)))
                    break
            else:
                # 在游戏里退出账号
                ret = self.__find_match_pos(screenshot, 'tab_main_menu')
                if ret:
                    self.__action_squential(
                        ClickAction(pos=ret),
                        SleepAction(1),
                        ClickAction(template='btn_back_welcome'),
                        SleepAction(1),
                        ClickAction(template='btn_ok_blue')
                    )
                ret = self.__find_match_pos(
                    screenshot, 'btn_back_welcome')
                if ret:
                    self.__action_squential(
                        ClickAction(template='btn_back_welcome'),
                        SleepAction(1),
                        ClickAction(template='btn_ok_blue')
                    )
                ClickAction(pos=(50, 300)).do(screenshot, self)
            time.sleep(3)

    def _first_enter_check(self):
        pos = random.choice(((199, 300), (400, 300), (590, 300), (790, 300)))
        self.__action_squential(MatchAction(ImageTemplate('shop', consecutive_hit=3), unmatch_actions=(
            ClickAction(template = ImageTemplate('btn_close') | ImageTemplate('btn_ok_blue')
                        | ImageTemplate('btn_download') | ImageTemplate('btn_skip')
                        | ImageTemplate('btn_cancel') | ImageTemplate('select_branch_first')
                        | ImageTemplate('app_no_responed')),
            ClickAction(pos=(30, 200)),
            ClickAction(pos=(90, 500)),
            # 处理兰德索尔杯的情况
            IfCondition(condition_template="symbol_landsol_cup", meet_actions=[
                ClickAction(pos=pos),
                SleepAction(2),
                ClickAction(pos=(838, 494))
            ])
        ), timeout=0), net_error_check=False)
        time.sleep(3)
        ClickAction(template='btn_close').bindTask(self._dummy_task).do(self.driver.screenshot(), self)

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
        self._log("======:已进入游戏首页:======")
        if tasklist:
            for funcname, *args in tasklist:
                task = find_taskclass(funcname)
                if task:
                    self._run_task(funcname, task, args)
                else:
                    self._call_function(funcname, args)

    def _run_task(self, taskname, taskclass: BaseTask, args):
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
                self.__tohomepage(click_pos=(60, 300))
                self._run_task(taskname, taskclass, args)
        self._log(f"end task: {taskname}")
    
    def _call_function(self, funcname, args):
        try:
            getattr(self, "_" + funcname)(*args)
        except Exception as e:
            print(e)
            if isinstance(e, NetError):
                self.__tohomepage(click_pos=(60, 300))
                self._call_function(funcname, args)

    def _log(self, msg: str):
        print("{}: {}".format(self._name, msg))

    def action_squential(self, *actions: Action, delay=0.2, net_error_check=True, show_progress=False, progress_index=None, total_step=1, title=None):
        if self.show_progress and show_progress:
            progress = tqdm(actions, unit="a", bar_format='{desc}|{bar}| {n_fmt}/{total_fmt} [{elapsed}, {rate_fmt}{postfix}]')
            if title:
                progress.set_description(f"{self._name} {title}")
            elif progress_index is not None:
                progress.set_description(f"{self._name} step({progress_index}/{total_step})")
            else:
                progress.set_description(f"{self._name}")
            actions = progress
        for action in actions:
            action_start_time = time.time()
            while not action.done():
                screenshot = self.driver.screenshot()
                action.do(screenshot, self)
                if delay > 0:
                    time.sleep(delay)
                if net_error_check and time.time() - action_start_time > 10:
                    # 如果一个任务检测超过10s，校验是否存在网络异常
                    net_error = self.__find_match_pos(screenshot, "btn_return_title_blue")
                    if not net_error:
                        net_error = self.__find_match_pos(screenshot, "btn_return_title_white")
                    if net_error:
                        self.driver.click(*net_error)
                        raise NetError()
                    
    def __tohomepage(self, click_pos=(90, 500), timeout=0):
        ToHomePage(self).run(click_pos=click_pos, timeout=timeout)
    
    def __action_squential(self, *actions: Action, delay=0.2, net_error_check=True):
        for action in actions:
            action.bindTask(self._dummy_task)
        self.action_squential(*actions, delay=delay, net_error_check=net_error_check)
    
    def __find_match_pos(self, screenshot, template):
        return ImageTemplate(template).set_define_size(BASE_WIDTH, BASE_HEIGHT).match(screenshot)
