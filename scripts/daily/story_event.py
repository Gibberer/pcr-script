"""Scheduled story-event cleanup only. No exploration or party-audit modes."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts._game import runner_from_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="daily_config.yml")
    parser.add_argument("--only", choices=["all", "stories", "memoirs", "missions", "sweep", "exchange"], default="all")
    args = parser.parse_args()
    runner = runner_from_config(args.config)
    if args.only == "all":
        report = runner.run()
    else:
        try:
            if runner.enter():
                getattr(runner, args.only)()
                runner.report["status"] = "partial" if runner.report["pending"] else "complete"
            else:
                runner.report["status"] = "unavailable"
        except Exception as error:
            runner.report["status"] = "error"
            runner.report["pending"].append(str(error))
            runner.ui.save("error")
            raise
        finally:
            (runner.ui.output / "report.json").write_text(json.dumps(runner.report, ensure_ascii=False, indent=2), encoding="utf-8")
        report = runner.report
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
