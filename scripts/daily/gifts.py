"""Compatibility command for the registered gifts task."""
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
    parser.add_argument('--include-stamina', action='store_true')
    args = parser.parse_args()
    print_report(run_task_from_config(args.config, 'get_gift', not args.include_stamina))


if __name__ == '__main__':
    with RunSession('gifts'):
        main()
