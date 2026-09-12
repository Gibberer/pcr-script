"""Build a reusable avatar matrix from public JP icons and local CN unit IDs.

No model training is needed. --all also preloads JP characters which have no
CN name yet; default downloads only characters referenced by event teams.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
from pathlib import Path
import sqlite3
import time

import cv2 as cv
import numpy as np
import requests
import yaml

import sys
import os
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from pcrscript.game_ui.avatars import AvatarIndex, face_crop
from pcrscript.game_ui.screen import normalized


SOURCE = "https://redive.estertion.win/icon/unit/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--teams", default="config/event_teams.yml")
    parser.add_argument("--database", default="cache/redive_cn.db")
    parser.add_argument("--icons", default="cache/character")
    parser.add_argument("--output", default="cache/game/avatars")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as db:
        units = {int(id)//100: normalized(name) for id, name in db.execute("SELECT unit_id,unit_name FROM unit_profile")
                 if 100100 <= int(id) < 200000}
    if args.all:
        listing = requests.get(SOURCE, timeout=30)
        listing.raise_for_status()
        icons = sorted({int(v) for v in re.findall(r'(?<!\d)(1\d{5})\.webp', listing.text)
                        if int(v) % 100 in (11, 31, 61)})
        for icon in icons:
            units.setdefault(icon//100, f"unit:{icon//100}")
        entries = [(icon//100, icon % 100) for icon in icons]
    else:
        data = yaml.safe_load(Path(args.teams).read_text(encoding="utf-8"))
        names = {normalized(m["name"]) for e in data["events"] for key in ("special", "special_plus")
                 for p in e.get(key, []) for m in p["members"]}
        units = {id: name for id, name in units.items() if name in names}
        absent = names-set(units.values())
        if absent:
            raise SystemExit("本地角色数据库缺少："+", ".join(absent))
        entries = [(unit, v) for unit in units for v in (11, 31, 61)]
    directory = Path(args.icons)
    directory.mkdir(parents=True, exist_ok=True)

    def fetch(entry):
        unit, variant = entry
        icon_id = unit*100+variant
        path = directory/f"{icon_id}.webp"
        if not path.exists():
            response = requests.get(SOURCE+path.name, timeout=20)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            picture = cv.imdecode(np.frombuffer(response.content, np.uint8), cv.IMREAD_COLOR)
            if picture is None or picture.shape[0] < 64:
                raise ValueError(f"头像响应不是有效图片：{icon_id}")
            path.write_bytes(response.content)
        return unit, path

    index = AvatarIndex(args.output, load_existing=False)
    failures = []
    loaded = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, entry) for entry in entries]
        for future in futures:
            try:
                item = future.result()
                if item is None:
                    continue
                unit, path = item
                picture = cv.imread(str(path))
                for pad in (0, 2):
                    art = cv.copyMakeBorder(picture, pad, pad, pad, pad, cv.BORDER_REFLECT)
                    index.add(units[unit], face_crop(art, (0, 0, art.shape[1], art.shape[0])), persist=False)
                loaded += 1
            except Exception as error:
                failures.append(str(error))
    index.save()
    report = {"source": SOURCE, "icons": loaded, "identities": len(set(index.names)),
              "features": len(index.names), "failures": failures}
    (index.path/"source.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
