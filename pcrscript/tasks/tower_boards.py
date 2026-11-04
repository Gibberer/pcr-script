"""Tower top rosters from CN guide boards; each still has to pass a free simulation."""
from __future__ import annotations

import json
from pathlib import Path
import re

import cv2 as cv
import requests

from ..extras.guide_media import fetch_video
from ..game_ui.guide_vision import read_text
from ..game_ui.screen import normalized
from ..run_session import atomic_json, clock as time
from .strategy_tables import board_hint, guide_board_rows

BOARD_VERSION = 1
MAX_VIDEOS = 4
MAX_PAGES = 3


def queries(floor):
    return [f'公主连结 国服 露娜塔 {floor} 顶层 作业', '公主连结 国服 露娜塔 顶层 磨血']


def wanted_page(part):
    """Ordinary top boards only: EX is a separate three-team fight and cannot be ground down."""
    text = normalized(part).upper().replace('不是EX', '').replace('非EX', '')
    return 'EX' not in text and bool(re.search('磨血|顶层|塔顶', part))


def wanted_video(title, floor):
    ordinary = normalized(title).upper().replace('不是EX', '').replace('非EX', '')
    return (bool(re.search('露娜塔|露娜之塔', title)) and '国服' in title
            and (str(floor) in title or bool(re.search('顶层|塔顶|磨血', title)))
            and ('EX' not in ordinary or bool(re.search('普通|道中', title))))


def search_videos(api, floor, root, *, check=lambda: None):
    path = root/f'search_{floor}_v{BOARD_VERSION}.json'
    try:
        saved = json.loads(path.read_text(encoding='utf-8'))
        if 0 <= time.time()-saved['at'] < 86400:
            return saved['videos']
    except (OSError, ValueError, KeyError, TypeError):
        pass
    found = {}
    for query in queries(floor):
        check()
        groups = api.search(query).get('data', {}).get('result') or []
        for group in groups:
            if group.get('result_type') != 'video':
                continue
            for item in group.get('data', []):
                title = re.sub(r'<[^>]+>', '', str(item.get('title', '')))
                if re.fullmatch(r'BV[0-9A-Za-z]{10}', str(item.get('bvid', ''))) and wanted_video(title, floor):
                    found.setdefault(item['bvid'])
    # The search's own relevance order; the newest uploads are often single fight recordings.
    videos = list(found)
    atomic_json(path, dict(at=time.time(), videos=videos))
    return videos


def read_board(path, duration, ocr, index, *, check=lambda: None, frames=8, reads=4):
    """Rows repeated on two frames of a page; corner animations do not disturb the grid."""
    capture = cv.VideoCapture(str(path))
    seen = {}
    plain = 0
    try:
        for i in range(frames):
            check()
            capture.set(cv.CAP_PROP_POS_MSEC, float(duration)*1000*(i+.5)/frames)
            ok, raw = capture.read()
            if not ok:
                continue
            frame = cv.resize(raw, (1280, 720))
            texts = read_text(frame, ocr)
            if not board_hint(texts):
                # A fight recording never turns into a board; spare the remaining frames.
                plain += 1
                if plain >= 3 and not seen:
                    break
                continue
            for row in guide_board_rows(frame, texts, index):
                entry = seen.setdefault(tuple(row['names']), dict(names=row['names'], instant=row['instant'], count=0))
                entry['count'] += 1
            reads -= 1
            if not reads:
                break
    finally:
        capture.release()
    return [dict(names=r['names'], instant=r['instant']) for r in seen.values() if r['count'] >= 2]


def index_size(index):
    names = getattr(index, 'names', None)
    return len(names) if isinstance(names, (list, tuple)) else None


def plans_from_rows(rows, part, source):
    """A grind board fights the boss; a route board's rows may also chip the shadows."""
    goals = [(2, 'boss_damage'), (3, 'boss_damage')]
    if '磨血' not in part:
        goals.append((1, 'shadows'))
    plans = []
    for row in rows:
        names = [normalized(n) for n in row['names']]
        flags = row['instant'] or [True]*5
        for phase, goal in goals:
            plans.append(dict(phase=phase, goal=goal, names=names, instant=dict(zip(names, flags)), stars={},
                source=source, trial_reason='国服练度表阵容的本账号免费试验（'+part+'）'))
    return plans


def board_plans(options, floor, index, *, api=None, ocr=None, check=lambda: None, media_fetcher=fetch_video):
    """Returns (plans, notes); an unavailable source never blocks the other candidates."""
    root = Path(options.get('guide_cache', 'cache/game/strategies/tower_guides'))/'boards'
    root.mkdir(parents=True, exist_ok=True)
    notes = []
    plans = {}
    def api_client():
        from ..extras.bilibili_api import BilibiliApi
        return BilibiliApi(timeout=20, browser_session=True)
    try:
        api = api or api_client()
        videos = list(options.get('board_videos') or search_videos(api, floor, root, check=check))
    except (requests.RequestException, RuntimeError, ValueError, OSError, AttributeError) as error:
        return [], ['国服练度表搜索失败：'+str(error)[:200]]
    if ocr is None:
        from ..game_ui.screen import ocr_engine
        ocr = ocr_engine()
    for bvid in videos[:MAX_VIDEOS]:
        check()
        try:
            data = api.getVideoInfo(bvid=bvid).get('data') or {}
            pages = [p for p in data.get('pages', []) if wanted_page(p.get('part', ''))]
            # The author's own daily plan comes before a route that assumes other knives.
            pages.sort(key=lambda p: '磨血' not in p.get('part', ''))
            for page in pages[:MAX_PAGES]:
                check()
                saved = root/f"{bvid}_{page['cid']}_v{BOARD_VERSION}.json"
                try:
                    rows = json.loads(saved.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    rows = None
                if rows == []:
                    rows = None  # Saved before the index was recorded; read it once more.
                elif isinstance(rows, dict):
                    # An empty read holds only for the portrait index it was made with.
                    rows = [] if rows.get('index') == index_size(index) is not None else None
                if not isinstance(rows, list):
                    path, media = media_fetcher(api, bvid, page, Path(options.get('media_dir', 'cache/game/strategies/media')), check=check)
                    rows = read_board(path, page.get('duration') or media['duration'], ocr, index, check=check)
                    atomic_json(saved, rows if rows else dict(rows=[], index=index_size(index)))
                source = 'https://www.bilibili.com/video/'+bvid+'/'
                for plan in plans_from_rows(rows, page.get('part', ''), source):
                    key = (plan['phase'], tuple(sorted(plan['instant'].items())))
                    plans.setdefault(key, plan)
                notes.append(f"{bvid} {page.get('part', '')}：{len(rows)} 支")
        except (requests.RequestException, RuntimeError, ValueError, OSError, KeyError) as error:
            notes.append(f'{bvid} 解析失败：'+str(error)[:200])
    return list(plans.values()), notes
