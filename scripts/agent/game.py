"""Agent-only background observations and explicit UI probes; never schedule this."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from scripts._game import runner_from_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="daily_config.yml")
    parser.add_argument("--audit", action="store_true", help="核对本期 SP＋模式1的第一套作业，不开战")
    parser.add_argument("--click", nargs=2, type=int)
    parser.add_argument("--swipe", nargs=4, type=int)
    parser.add_argument("--input", help="向已聚焦的游戏输入框写入文本")
    parser.add_argument("--name", default="inspect")
    args = parser.parse_args()
    from pcrscript.run_session import assert_inspection_allowed
    assert_inspection_allowed()
    runner = runner_from_config(args.config, "cache/agent/story_event")
    if args.audit:
        if args.click or args.swipe or args.input:
            parser.error("配队审查不能与手动探查动作同时使用")
        from pcrscript.tasks.event_battle import EventBattles
        from pcrscript.tasks.event_strategy import load_parties
        if not runner.enter():
            raise SystemExit("当前没有可审查的新版剧情活动")
        title = runner.home().text((0, 160, 940, 460))
        parties = load_parties(runner.options.get("teams", "cache/game/strategies/event_teams.yml"), title, "special_plus", 1)
        if not parties:
            raise SystemExit("本活动没有可审查的队伍配置")
        runner.quests(bosses=True)
        runner.ui.expect_click(r"特别战斗\+", (740, 200, 930, 400), exact=True)
        runner.ui.expect_click("挑战", (740, 430, 945, 515), exact=True)
        ready, details = EventBattles(runner).formation.select(parties[0])
        report = {"ready": ready, "party": parties[0].name, "details": details}
        runner.home()
        (runner.ui.output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        if args.click:
            runner.ui.click(args.click)
        if args.swipe:
            runner.ui.swipe(args.swipe[:2], args.swipe[2:])
        if args.input:
            runner.ui.driver.input(args.input)
            time.sleep(1)
        screen = runner.ui.capture()
        path = runner.ui.save(args.name, screen)
        report = {"screenshot": str(path), "text": screen.text()}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
