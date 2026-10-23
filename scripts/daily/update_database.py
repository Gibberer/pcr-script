"""Update static task prerequisites without connecting to a game device."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from pcrscript.masterdata import DATABASE, ensure_masterdata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DATABASE)
    parser.add_argument('--force', action='store_true', help='立即查询资源版本，不等待缓存到期')
    parser.add_argument('--offline', action='store_true', help='只检查24小时内已验证的本地缓存')
    args = parser.parse_args()
    if args.force and args.offline:
        parser.error('--force 与 --offline 不能同时使用')
    print(json.dumps(ensure_masterdata(args.output, force=args.force, offline=args.offline),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
