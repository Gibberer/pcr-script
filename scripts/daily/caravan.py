"""Compatibility command for the registered caravan task."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts._game import run_task_from_config, print_report
from pcrscript.run_session import RunSession

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='daily_config.yml')
    parser.add_argument('--timeout', type=int)
    parser.add_argument('--max-rolls', type=int)
    args = parser.parse_args()
    options = {k: v for k, v in dict(timeout=args.timeout, max_rolls=args.max_rolls).items() if v is not None}
    if any(value <= 0 for value in options.values()):
        parser.error('运行时限与批次上限必须大于0')
    print_report(run_task_from_config(args.config, 'caravan', option_overrides=options))


if __name__ == '__main__':
    with RunSession('caravan'):
        main()
