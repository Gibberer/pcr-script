"""Shared configuration and registered-task dispatch for command-line tools."""
from pathlib import Path
from typing import Any, Type
from collections import Counter
import copy
import json
import subprocess
import yaml

from pcrscript import DNSimulator, GeneralSimulator, Robot
from pcrscript.driver import ADBDriver, Driver
from pcrscript.tasks import EventNews, TimeLimitTask, find_taskclass
from pcrscript.news import fetch_event_news
from pcrscript.run_session import clock as time
from pcrscript.run_session import emit, task_directory, task_result, daily_result


def load_config(path: str | Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("任务配置必须是 YAML 映射")
    return config


def select_driver(config: dict[str, Any]) -> Driver:
    """Use LeiDian's background driver when configured; otherwise use ADB."""
    extra = config.get("Extra", {})
    if not isinstance(extra, dict):
        raise ValueError("Extra 必须是配置对象")
    if any(not isinstance(extra.get(key, ""), str) for key in ("dnpath", "adb_path", "adb_serial", "adb_unicode_console_path")):
        raise ValueError("Extra.dnpath、adb_path、adb_serial 和 adb_unicode_console_path 必须是字符串")
    dnpath = str(extra.get("dnpath") or "").strip()
    if dnpath:
        simulator = DNSimulator(dnpath, useADB=False)
        drivers = simulator.get_dirvers() or []
        if not drivers:
            raise RuntimeError(simulator.discovery_error())
        driver = drivers[0]
        driver.adb_path = str(extra.get('adb_path') or 'adb').strip()
        bundled_adb = Path(dnpath)/'adb.exe'
        if driver.adb_path == 'adb' and bundled_adb.is_file():
            driver.adb_path = str(bundled_adb)
        driver.adb_fallback_serial = str(extra.get('adb_serial') or '').strip()
        return driver
    adb_path = str(extra.get("adb_path") or "adb").strip()
    unicode_console_path = str(extra.get("adb_unicode_console_path") or "").strip()
    unicode_console_index = extra.get("adb_unicode_console_index", 0)
    if type(unicode_console_index) is not int or unicode_console_index < 0:
        raise ValueError("Extra.adb_unicode_console_index 必须为非负整数")
    if unicode_console_path and not Path(unicode_console_path).is_file():
        raise ValueError("Extra.adb_unicode_console_path 未找到文件")
    devices = GeneralSimulator(adb_path).get_devices() or []
    serial = str(extra.get("adb_serial") or "").strip()
    if serial:
        if serial not in devices:
            raise RuntimeError(f"ADB 设备 {serial} 未连接或未授权")
        return ADBDriver(serial, adb_path, unicode_console_path=unicode_console_path,
                         unicode_console_index=unicode_console_index)
    if not devices:
        raise RuntimeError("未找到已连接且授权的 ADB 设备；请检查 adb devices")
    if len(devices) != 1:
        raise RuntimeError("存在多个 ADB 设备，请在 Extra.adb_serial 指定目标序列号")
    return ADBDriver(devices[0], adb_path, unicode_console_path=unicode_console_path,
                     unicode_console_index=unicode_console_index)


def robot_from_config(config: dict[str, Any]) -> Robot:
    robot = Robot(select_driver(config), show_progress=False)
    robot.configure(config)
    return robot


def run_task_from_config(path: str | Path, task_name: str, *args: Any,
                         option_overrides: dict[str, Any] | None = None,
                         **kwargs: Any) -> Any:
    return run_task_with_config(load_config(path), task_name, *args,
                                option_overrides=option_overrides, **kwargs)


def run_task_with_config(config: dict[str, Any], task_name: str, *args: Any,
                         option_overrides: dict[str, Any] | None = None,
                         **kwargs: Any) -> Any:
    """Dispatch from in-memory options; no configuration file is required."""
    config = copy.deepcopy(config)
    task_class = find_taskclass(task_name)
    if task_class is None:
        raise ValueError(f"未知任务: {task_name}")
    if option_overrides:
        if task_class.config_section is None:
            raise ValueError(f"任务 {task_name} 不接受配置段参数")
        options = copy.deepcopy(config.get(task_class.config_section, {}))
        options.update(option_overrides)
        config[task_class.config_section] = options
    emit('progress', scope='task', current=0, total=1, name=task_name)
    emit('progress', scope='action', label='检查任务条件', unit='task')
    args, kwargs, report = task_class.prepare(config, *args, **kwargs)
    if report is not None:
        task_result(dict(task=task_name, status=report['status'], report=report,
                         duration_seconds=0.0), task_directory(task_name))
        emit('progress', scope='action', clear=True)
        emit('progress', scope='task', current=1, total=1, name=task_name)
        return report
    return robot_from_config(config).run_task(task_name, *args, **kwargs)


def print_report(report: Any) -> None:
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if isinstance(report, dict) and report.get('status') in ('partial', 'error', 'blocked'):
        raise SystemExit(2)


def open_leidian_emulator(dnpath: str) -> int:
    # 开启雷电模拟器
    # 检查当前运行的程序有没有雷电模拟器
    simulator = DNSimulator(dnpath, useADB=False)
    simulator.start()
    last_error = None
    for attempt in range(10):
        try:
            if simulator.online():
                print("the emulator is ready.")
                break
            last_error = None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            last_error = error
            detail = (f'退出码 0x{error.returncode & 0xffffffff:08X}'
                      if isinstance(error, subprocess.CalledProcessError) else '查询超过 15 秒')
            print(f'雷电模拟器设备查询 list2 失败（{detail}），启动检查 {attempt + 1}/10', flush=True)
        if attempt < 9:
            print("no emulator detected, wait for 20 seconds")
            time.sleep(20)
    else:
        if last_error is not None:
            raise RuntimeError(f'雷电模拟器启动检查已达 10 次上限，最后一次设备查询失败（{detail}）') from last_error
        print("exit cannot found device")
        return -1
    print("try start princess connect application")
    time.sleep(10)
    return simulator.open_app("com.bilibili.priconne")

def modify_task_list(news: EventNews, task_list: list[list[Any]]) -> None:
    for i in range(len(task_list) - 1, -1, -1):
        task_class = find_taskclass(task_list[i][0])
        if not issubclass(task_class, TimeLimitTask):
            continue
        valid_class,args = None,None
        task_class:Type[TimeLimitTask] = task_class
        ret = task_class.valid(news, task_list[i][1:])
        if ret:
            valid_class = ret[0]
            if len(ret) > 1:
                args = ret[1]
        if not valid_class:
            task_list.pop(i)
        else:
            task_list.pop(i)
            if args:
                task_list.insert(i, [valid_class.name, *args])
            else:
                task_list.insert(i, [valid_class.name])


def summarize_daily(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate execution endings from tasks with verified postconditions."""
    tasks = []
    for index, record in enumerate(records, 1):
        item = dict(index=index, task=record['task'], status=record['status'])
        report = record.get('report')
        reasons = [record['error']] if record.get('error') else []
        if isinstance(report, dict):
            if report.get('reason'):
                reasons.append(report['reason'])
            pending = report.get('pending') or []
            reasons.extend([pending] if isinstance(pending, str) else pending)
        if reasons:
            item['reasons'] = reasons
        tasks.append(item)
    counts = dict(Counter(item['status'] for item in tasks))
    verified = bool(tasks) and all(item['status'] in ('complete', 'already_complete', 'unavailable')
                                   for item in tasks)
    status = ('error' if counts.get('error') else
              'cancelled' if counts.get('cancelled') else
              'partial' if counts.get('partial') or counts.get('blocked') else
              'complete' if verified else 'finished')
    return dict(status=status, verified=verified, counts=counts, tasks=tasks)


def run_script(config: dict[str, Any], use_adb: bool = False) -> dict[str, Any]:
    # Keep the legacy argument for callers; the configured transport selects the driver.
    emit('progress', scope='action', label='连接设备并读取活动情报', unit='task')
    robot = Robot(select_driver(config))
    robot.configure(config)
    news = fetch_event_news()
    print("当前进行的活动:")
    for value in news.__dict__.values():
        if value:
            print(value)
    task_list = copy.deepcopy(next(iter(config["Task"].values())))
    # 根据当前进行的活动修改原始任务
    modify_task_list(news, task_list)
    # 日常沿用当前账号；从欢迎页进入，或从已打开的游戏页面返回首页。
    emit('progress', scope='action', label='进入游戏首页', unit='task')
    robot.changeaccount()
    report = summarize_daily(robot.work(task_list))
    daily_result(report)
    return report
