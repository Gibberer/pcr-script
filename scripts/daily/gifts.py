"""Collect gifts and recover full EX inventory through saved auto-dismantle rules."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import yaml
from scripts._game import runner_from_config
from pcrscript.daily.gifts import GiftRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="daily_config.yml")
    parser.add_argument("--include-stamina", action="store_true")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    robot = runner_from_config(args.config).robot
    result = GiftRunner(robot, config.get("Gift", {})).run(not args.include_stamina)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
