"""Shared launch setup for daily and agent command-line tools."""
from pathlib import Path
import yaml

from pcrscript import DNSimulator, Robot
from pcrscript.daily.story_event import StoryEventRunner


def runner_from_config(path, output=None):
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    dnpath = config.get("Extra", {}).get("dnpath")
    if not dnpath:
        raise SystemExit("请在 Extra.dnpath 设置雷电路径；此入口不使用 ADB")
    drivers = DNSimulator(dnpath, useADB=False).get_dirvers()
    if not drivers:
        raise SystemExit("未发现雷电窗口，请在与模拟器相同的 Windows 会话运行")
    options = dict(config.get("StoryEvent", {}))
    if output:
        options["output"] = output
    return StoryEventRunner(Robot(drivers[0], show_progress=False), options)
