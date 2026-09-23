"""Shared configuration and registered-task dispatch for command-line tools."""
from pathlib import Path
from typing import Any, Type
import copy
import json
import yaml

from pcrscript import DNSimulator, GeneralSimulator, Robot
from pcrscript.driver import ADBDriver, Driver
from pcrscript.tasks import EventNews, TimeLimitTask, find_taskclass
from pcrscript.news import fetch_event_news
from pcrscript.run_session import clock as time
from pcrscript.run_session import task_directory, task_result


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
    if any(not isinstance(extra.get(key, ""), str) for key in ("dnpath", "adb_path", "adb_serial")):
        raise ValueError("Extra.dnpath、adb_path 和 adb_serial 必须是字符串")
    dnpath = str(extra.get("dnpath") or "").strip()
    if dnpath:
        drivers = DNSimulator(dnpath, useADB=False).get_dirvers() or []
        if not drivers:
            raise RuntimeError("未发现雷电窗口，请在与模拟器相同的 Windows 会话运行")
        return drivers[0]
    adb_path = str(extra.get("adb_path") or "adb").strip()
    devices = GeneralSimulator(adb_path).get_devices() or []
    serial = str(extra.get("adb_serial") or "").strip()
    if serial:
        if serial not in devices:
            raise RuntimeError(f"ADB 设备 {serial} 未连接或未授权")
        return ADBDriver(serial, adb_path)
    if not devices:
        raise RuntimeError("未找到已连接且授权的 ADB 设备；请检查 adb devices")
    if len(devices) != 1:
        raise RuntimeError("存在多个 ADB 设备，请在 Extra.adb_serial 指定目标序列号")
    return ADBDriver(devices[0], adb_path)


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
    args, kwargs, report = task_class.prepare(config, *args, **kwargs)
    if report is not None:
        task_result(dict(task=task_name, status=report['status'], report=report,
                         duration_seconds=0.0), task_directory(task_name))
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
    retry_count = 0
    while retry_count < 10:
        if simulator.online():
            # simulator.move_to_screen(1)
            print("the emulator is ready.")
            break
        else:
            print("no emulator detected, wait for 20 seconds")
            time.sleep(20)
            retry_count += 1
    if retry_count >= 10:
        print("exit cannot found device")
        return -1
    else:
        print("try start princess connect application")
        time.sleep(10)
        exit_code = simulator.open_app("com.bilibili.priconne")
        return exit_code

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


def run_script(config: dict[str, Any], use_adb: bool = False) -> None:
    # Keep the legacy argument for callers; the configured transport selects the driver.
    robot = Robot(select_driver(config))
    robot.configure(config)
    news = fetch_event_news()
    print("当前进行的活动:")
    for value in news.__dict__.values():
        if value:
            print(value)
    task_list: list = next(iter(config["Task"].values()))  # 这里设置一个全量的任务列表
    # 根据当前进行的活动修改原始任务
    modify_task_list(news, task_list)
    # 日常沿用当前账号；从欢迎页进入，或从已打开的游戏页面返回首页。
    robot.changeaccount()
    robot.work(task_list)
