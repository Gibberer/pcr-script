"""Shared configuration and registered-task dispatch for command-line tools."""
from pathlib import Path
from typing import Any
import copy
import json
import yaml

from pcrscript import DNSimulator, Robot
from pcrscript.tasks import find_taskclass
from pcrscript.tasks.base import TaskReport
from pcrscript.tasks.task_story_event import CampaignClean
from pcrscript.run_session import task_directory, task_result


def load_config(path: str | Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("任务配置必须是 YAML 映射")
    return config


def robot_from_config(config: dict[str, Any]) -> Robot:
    dnpath = config.get("Extra", {}).get("dnpath")
    if not dnpath:
        raise SystemExit("请在 Extra.dnpath 设置雷电路径；此入口不使用 ADB")
    drivers = DNSimulator(dnpath, useADB=False).get_dirvers()
    if not drivers:
        raise SystemExit("未发现雷电窗口，请在与模拟器相同的 Windows 会话运行")
    robot = Robot(drivers[0], show_progress=False)
    robot.configure(config)
    return robot


def run_task_from_config(path: str | Path, task_name: str, *args: Any,
                         option_overrides: dict[str, Any] | None = None,
                         **kwargs: Any) -> Any:
    config = load_config(path)
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


def runner_from_config(path: str | Path, output: str | None = None) -> CampaignClean:
    """Agent inspection compatibility; production entry points use run_task_from_config."""
    config = load_config(path)
    robot = robot_from_config(config)
    options = dict(config.get('StoryEvent', {}))
    if output:
        options['output'] = output
    return CampaignClean(robot, options)
