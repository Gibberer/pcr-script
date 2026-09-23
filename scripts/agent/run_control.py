"""Inspect, pause, resume or preserve evidence of a daily run (no emulator calls)."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from pcrscript.run_session import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'pause', 'resume', 'snapshot'])
    parser.add_argument('--run', help='运行目录；省略时仅允许唯一的活跃运行')
    parser.add_argument('--wait', type=float, default=10)
    args = parser.parse_args()
    candidates = []
    for path in Path('cache/daily/runs').glob('*/status.json'):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if state['state'] in ('running', 'paused') and time.time()-state['heartbeat'] < 10:
                candidates.append(path.parent)
        except (OSError, ValueError, KeyError):
            continue
    if args.run:
        run = Path(args.run)
    elif len(candidates) == 1:
        run = candidates[0]
    else:
        print(json.dumps({'active_runs': [str(p) for p in candidates]}, ensure_ascii=False))
        if args.action != 'status':
            raise SystemExit('请用 --run 指定唯一运行目录')
        return
    status = lambda: json.loads((run/'status.json').read_text(encoding='utf-8'))
    state = status()
    if args.action != 'status':
        if state['state'] not in ('running', 'paused') or time.time()-state['heartbeat'] >= 10:
            raise SystemExit('运行已结束或心跳失联，不能发送控制命令')
        if args.action == 'resume' and state['state'] == 'running':
            try:
                previous = json.loads((run/'control.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                previous = {}
            if previous.get('action') == 'pause' and previous.get('id') != state.get('command_id'):
                raise SystemExit('暂停请求尚未确认；请先核查状态，不能将运行中状态当作已恢复')
        if (args.action == 'pause' and state['state'] == 'paused') or (
                args.action == 'resume' and state['state'] == 'running'):
            print(json.dumps(dict(run=str(run), **state), ensure_ascii=False, indent=2))
            return
        command = dict(id=uuid.uuid4().hex, action=args.action, requested_at=time.time())
        atomic_json(run/('snapshot-request.json' if args.action == 'snapshot' else 'control.json'), command)
        deadline = time.monotonic()+args.wait
        while time.monotonic() < deadline:
            state = status()
            key = 'snapshot_id' if args.action == 'snapshot' else 'command_id'
            if state.get(key) == command['id']:
                break
            time.sleep(.1)
        else:
            print(json.dumps(state, ensure_ascii=False, indent=2))
            raise SystemExit('控制请求尚未确认；不可视为已暂停。可用 snapshot 保存当前线程栈和最近截图')
    print(json.dumps(dict(run=str(run), **state), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
