"""Compatibility command for the registered revival_event task."""
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
    args = parser.parse_args()
    print_report(run_task_from_config(args.config, 'revival_event_once'))


if __name__ == '__main__':
    with RunSession('revival_event'):
        main()
