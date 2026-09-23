"""Run one registered task without editing the daily list."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts._game import run_task_from_config, print_report
from pcrscript.run_session import RunSession

import json
from pcrscript.tasks.registry import registered_tasks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=registered_tasks())
    parser.add_argument('--config', default='daily_config.yml' if Path('daily_config.yml').exists() else 'runtime_defaults.yml')
    parser.add_argument('--args', default='[]', help='Task positional arguments as a JSON list')
    args = parser.parse_args()
    try:
        values = json.loads(args.args)
    except ValueError as error:
        parser.error(str(error))
    if not isinstance(values, list):
        parser.error('--args 必须是 JSON 列表')
    with RunSession(args.task):
        print_report(run_task_from_config(args.config, args.task, *values))


if __name__ == '__main__':
    main()
