"""Compatibility imports for CLI tools; production execution lives in pcrscript."""
from pathlib import Path
from pcrscript.runtime import load_config, robot_from_config, run_task_from_config, run_task_with_config, print_report
from pcrscript.tasks.task_story_event import CampaignClean


def runner_from_config(path: str | Path, output: str | None = None) -> CampaignClean:
    """Agent inspection compatibility; production entry points use run_task_from_config."""
    config = load_config(path)
    robot = robot_from_config(config)
    options = dict(config.get('StoryEvent', {}))
    if output:
        options['output'] = output
    return CampaignClean(robot, options)
