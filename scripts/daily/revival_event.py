"""Run the active revival once; check the calendar before opening an emulator."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import yaml
from pcrscript import DNSimulator, Robot
from pcrscript.news import fetch_event_news
from pcrscript.daily.revival_event import RevivalEventRunner
from pcrscript.daily.revival_state import RevivalState


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='daily_config.yml')
    args = parser.parse_args()
    event = fetch_event_news().revival
    if not event:
        print(json.dumps({'status': 'unavailable'}, ensure_ascii=False))
        return
    config = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    options = config.get('RevivalEvent', {})
    # Explicit account scope allows receipt checks before even enumerating windows.
    account = options.get('account_key')
    if account is not None and RevivalState(options.get('state_dir', 'cache/daily/revival_state'), account, event).complete:
        print(json.dumps({'status': 'already_complete', 'event_id': event.extras['event_id']}))
        return
    dnpath = config.get('Extra', {}).get('dnpath')
    if not dnpath:
        raise SystemExit('请配置 Extra.dnpath；复刻任务不使用 ADB')
    drivers = DNSimulator(dnpath, useADB=False).get_dirvers()
    if not drivers:
        raise SystemExit('未发现雷电窗口')
    report = RevivalEventRunner(Robot(drivers[0], show_progress=False), event, options).run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['status'] not in ('complete', 'already_complete', 'unavailable'):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
