import functools
import random
import copy
import sys
from typing import Any
from pathlib import Path
from .run_session import clock as time, wrap_driver, emit, failure, task_directory, task_result, RunCancelled
from tqdm import tqdm

from .driver import Driver
from .actions import *
from .constants import *
from .tasks import find_taskclass, ImageTask, ToHomePage
from .tasks.base import TaskExecutionRecord
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

class _DummyTask(ImageTask):

    def run(self, *args):
        pass

class Robot:
    def __init__(self, driver: Driver, name=None, show_progress=True):
        super().__init__()
        self.driver = wrap_driver(driver)
        self.devicewidth, self.deviceheight = driver.get_screen_size()
        self.show_progress = show_progress
        self.task_config: dict[str, Any] = {}
        self.task_results: list[TaskExecutionRecord] = []
        self._task_output: Path | None = None
        self._in_work = False
        self._dummy_task = _DummyTask(self)
        global num
        if not name:
            name = "Robot#{}".format(num)
            num += 1
        self._name = name

    def update_screenshot_size(self, screenshot):
        """Keep legacy image actions aligned with the current captured frame."""
        shape = getattr(screenshot, 'shape', None)
        if not isinstance(shape, tuple):
            return  # Test doubles without pixels keep the driver's reported size.
        if len(shape) < 2 or shape[0] <= 0 or shape[1] <= 0:
            raise RuntimeError('设备截图为空，不能换算点击坐标')
        self.deviceheight, self.devicewidth = shape[:2]

    @trace
    def changeaccount(self, account=None, password=None, logpath=None):
        if logpath:
            with open(logpath, 'a') as f:
                f.write("{}:{}\n".format(self._name, account))
        if not account:
            # Daily runs keep the current account. A game that is already open
            # may start on any page, so navigate home instead of logging out.
            screenshot = self.driver.screenshot()
            if self.__find_match_pos(screenshot, 'welcome_main_menu'):
                self.__action_squential(ClickAction(pos=(30, 200)))
            else:
                ToHomePage(self).run(timeout=60)
            return
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
    def work(self, tasklist: list[list[Any]] | None = None) -> list[TaskExecutionRecord]:
        # Old configurations used parameterless homepage rows as separators.
        # Entry requirements now belong to each dispatched task; keep explicit
        # custom-coordinate/timeout requests for backward compatibility.
        tasklist = [row for row in (tasklist or []) if row != ['tohomepage']]
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
            self._in_work = True
            try:
                for index, (funcname, *args) in enumerate(tasklist, 1):
                    emit('progress', scope='task', current=index - 1, total=len(tasklist), name=funcname)
                    self._run_task(funcname, args)
                    emit('progress', scope='task', current=index, total=len(tasklist), name=funcname)
            finally:
                self._in_work = False
                emit('progress', scope='action', clear=True)
        return self.task_results

    def configure(self, config: dict[str, Any]) -> None:
        self.task_config = copy.deepcopy(config)

    def run_task(self, taskname: str, *args: Any, **kwargs: Any) -> Any:
        """Shared dispatch for a daily list or one task, preserving its result.

        Tasks declare their entry requirements. OCR flows with their own safe
        navigation and current-map tasks keep control of their starting page.
        """
        taskclass = find_taskclass(taskname)
        legacy = getattr(self, '_' + taskname, None) if taskclass is None else None
        directory = task_directory(taskname)
        previous_output = self._task_output
        self._task_output = directory
        started = time.monotonic()
        record: TaskExecutionRecord = {'task': taskname, 'status': 'running'}
        if not self._in_work:
            emit('progress', scope='task', current=0, total=1, name=taskname)
        emit('progress', scope='action', clear=True)
        self._log(f'start task: {taskname}')
        try:
            if taskclass is None and not callable(legacy):
                raise ValueError(f'未知任务: {taskname}')
            if taskclass is not None and taskclass.requires_home is True:
                self._log('准备任务：自动返回首页')
                ToHomePage(self).run(timeout=60)
            result = taskclass(self).run(*args, **kwargs) if taskclass else legacy(*args, **kwargs)
            # Old tasks have no postcondition report. Do not claim verified success.
            record['status'] = result.get('status', 'finished') if isinstance(result, dict) else 'finished'
            record['report'] = result
            return result
        except RunCancelled:
            record['status'] = 'cancelled'
            raise
        except Exception as error:
            record.update(status='error', error=str(error))
            failure(error)
            raise
        finally:
            record['duration_seconds'] = round(time.monotonic()-started, 3)
            self._task_output = previous_output
            self.task_results.append(record)
            task_result(record, directory)
            emit('progress', scope='action', clear=True)
            if not self._in_work and record['status'] not in ('error', 'cancelled'):
                emit('progress', scope='task', current=1, total=1, name=taskname)
            self._log(f'end task: {taskname} ({record["status"]})')

    def _run_task(self, taskname: str, args: list[Any]) -> Any:
        try:
            return self.run_task(taskname, *args)
        except Exception as e:
            print(e)

    def _log(self, msg: str):
        emit("task", message=msg)
        print("{}: {}".format(self._name, msg))

    def action_squential(self, *actions: Action, delay=0.2, net_error_check=True, show_progress=False, progress_index=None, total_step=1, title=None):
        label = title or (f'步骤 {progress_index}/{total_step}' if progress_index is not None else '界面操作')
        action_total = len(actions)
        emit('progress', scope='action', current=0, total=action_total, label=label)
        if self.show_progress and show_progress and getattr(sys.stderr, 'isatty', lambda: False)():
            progress = tqdm(actions, unit="a", bar_format='{desc}|{bar}| {n_fmt}/{total_fmt} [{elapsed}, {rate_fmt}{postfix}]')
            if title:
                progress.set_description(f"{self._name} {title}")
            elif progress_index is not None:
                progress.set_description(f"{self._name} step({progress_index}/{total_step})")
            else:
                progress.set_description(f"{self._name}")
            actions = progress
        for index, action in enumerate(actions, 1):
            emit("action", action=type(action).__name__, template=str(getattr(action, "template", "")))
            action_start_time = time.monotonic()
            while not action.done():
                screenshot = self.driver.screenshot()
                self.update_screenshot_size(screenshot)
                action.do(screenshot, self)
                if delay > 0:
                    time.sleep(delay)
                if net_error_check and time.monotonic() - action_start_time > 10:
                    # 如果一个任务检测超过10s，校验是否存在网络异常
                    net_error = self.__find_match_pos(screenshot, "btn_return_title_blue")
                    if not net_error:
                        net_error = self.__find_match_pos(screenshot, "btn_return_title_white")
                    if net_error:
                        self.driver.click(*net_error)
                        raise NetError()
            emit('progress', scope='action', current=index, total=action_total, label=label)

    def __tohomepage(self, click_pos=(90, 500), timeout=0):
        ToHomePage(self).run(click_pos=click_pos, timeout=timeout)

    def __action_squential(self, *actions: Action, delay=0.2, net_error_check=True):
        for action in actions:
            action.bindTask(self._dummy_task)
        self.action_squential(*actions, delay=delay, net_error_check=net_error_check)

    def __find_match_pos(self, screenshot, template):
        return ImageTemplate(template).set_define_size(BASE_WIDTH, BASE_HEIGHT).match(screenshot)
