"""Compatibility command for the registered story_event task."""
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
    parser.add_argument('--config', default='daily_config.yml' if Path('daily_config.yml').exists() else 'runtime_defaults.yml')
    parser.add_argument('--only', choices=['all', 'stories', 'memoirs', 'missions', 'sweep', 'exchange'], default='all')
    args = parser.parse_args()
    print_report(run_task_from_config(args.config, 'campaign_clean', only=args.only))


if __name__ == '__main__':
    with RunSession('story_event'):
        main()
