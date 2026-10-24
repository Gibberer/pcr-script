"""Prepare a public, versioned avatar reference library without Agent inputs."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

import cv2 as cv
import numpy as np
import requests

from .avatars import AvatarIndex, face_crop
from ..run_session import atomic_json

ICON_SOURCE = 'https://redive.estertion.win/icon/unit/'
ASSET_VERSION = 1


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def identities(database: Path) -> dict[int, str]:
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True)) as connection:
        rows = connection.execute('SELECT unit_id, unit_name FROM unit_profile').fetchall()
    result = {int(uid)//100: re.sub(r'\s+', '', name).replace('（', '(').replace('）', ')')
              for uid, name in rows if 100100 <= int(uid) < 200000 and isinstance(name, str)}
    if not result:
        raise ValueError('角色数据库没有可用身份，未生成空索引')
    return result


def ensure_database(path: Path, *, http=requests, max_age_hours: float = 6,
                    timeout: float = 20, check=lambda: None) -> dict:
    """Use the same project-maintained static source as task prerequisites."""
    from ..masterdata import ensure_masterdata
    result = ensure_masterdata(path, http=http, max_age_hours=max_age_hours,
                               timeout=timeout, check=check)
    identities(Path(path))
    return result


def ensure_avatar_index(options: dict | None = None, *, http=requests, check=lambda: None) -> tuple[AvatarIndex, dict]:
    """Public references are separate from account observations/legacy feature files.

    An isolated directory/database is sufficient for a true empty-cache run.
    No path under scripts/agent or cache/agent is read by this function.
    """
    options = options or {}
    root = Path(options.get('directory', 'cache/game/avatars/reference'))
    database = Path(options.get('database', 'cache/redive_cn.db'))
    ttl = options.get('max_age_hours', 168)
    timeout = options.get('request_timeout', 20)
    if type(ttl) not in (int, float) or not 0 <= ttl <= 720:
        raise ValueError('头像缓存有效期必须为0到720小时')
    if type(timeout) not in (int, float) or not 1 <= timeout <= 60:
        raise ValueError('头像请求超时必须为1到60秒')
    root.mkdir(parents=True, exist_ok=True)
    saved = read_json(root/'manifest.json')
    if saved.get('version') == ASSET_VERSION and saved.get('complete') and 0 <= time.time()-saved.get('fetched_at', 0) < ttl*3600:
        try:
            index = AvatarIndex(root)
            if index.names and sha256((root/'index.npz').read_bytes()).hexdigest() == saved.get('index_sha256'):
                index.read_only = True
                return index, dict(saved, cache_hit=True)
        except (OSError, ValueError, KeyError):
            pass
    db_report = ensure_database(database, http=http, max_age_hours=ttl, timeout=timeout, check=check)
    units = identities(database)
    check()
    response = http.get(ICON_SOURCE, timeout=timeout)
    response.raise_for_status()
    icon_ids = sorted({int(v) for v in re.findall(r'(?<!\d)(1\d{5})\.webp', response.text)
                       if int(v) % 100 in (11, 31, 61)})
    if not icon_ids or len(icon_ids) > 6000:
        raise RuntimeError('公共头像目录为空或结构变化')
    directory = root/'icons'
    directory.mkdir(exist_ok=True)
    prior = {str(a['icon_id']): a for a in saved.get('assets', [])}

    def fetch(icon_id: int):
        check()
        path = directory/f'{icon_id}.webp'
        before = prior.get(str(icon_id), {})
        raw = path.read_bytes() if path.exists() else b''
        digest = sha256(raw).hexdigest()
        valid_local = bool(raw) and digest == before.get('sha256')
        headers = {}
        if valid_local:
            if before.get('etag'):
                headers['If-None-Match'] = before['etag']
            elif before.get('last_modified'):
                headers['If-Modified-Since'] = before['last_modified']
        # An expired manifest revalidates remote content, not just local hashes.
        response = http.get(ICON_SOURCE+path.name, timeout=timeout, headers=headers)
        if response.status_code != 304:
            response.raise_for_status()
            raw = response.content
            if len(raw) > 2*1024**2:
                raise ValueError('头像响应超出大小限制')
        elif not valid_local:
            raise ValueError('头像返回304但本地文件无效')
        image = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR)
        if image is None or min(image.shape[:2]) < 64:
            raise ValueError('头像不是有效图像')
        if not path.exists() or digest != sha256(raw).hexdigest():
            temporary = path.with_suffix('.'+uuid4().hex+'.tmp')
            temporary.write_bytes(raw)
            temporary.replace(path)
        name = units.get(icon_id//100, f'unit:{icon_id//100}')
        return image, dict(icon_id=icon_id, unit_id=icon_id//100*100+1, name=name,
                           source=ICON_SOURCE+path.name, sha256=sha256(raw).hexdigest(),
                           fetched_at=time.time(), etag=response.headers.get('ETag', before.get('etag')),
                           last_modified=response.headers.get('Last-Modified', before.get('last_modified')))

    index = AvatarIndex(root, load_existing=False)
    assets, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [(icon_id, pool.submit(fetch, icon_id)) for icon_id in icon_ids]
        for icon_id, future in futures:
            check()
            try:
                image, asset = future.result()
                for pad in (0, 2):
                    padded = cv.copyMakeBorder(image, pad, pad, pad, pad, cv.BORDER_REFLECT)
                    index.add(asset['name'], face_crop(padded, (0, 0, padded.shape[1], padded.shape[0])), persist=False)
                assets.append(asset)
            except (requests.RequestException, ValueError, OSError) as error:
                errors.append(dict(icon_id=icon_id, error=type(error).__name__))
    if not index.names:
        raise RuntimeError('头像获取失败，没有可用参考索引')
    # A partial update must not erase a previously complete public reference library.
    if (errors and saved.get('complete') and (root/'index.npz').exists()
            and sha256((root/'index.npz').read_bytes()).hexdigest() == saved.get('index_sha256')):
        old = AvatarIndex(root)
        old.read_only = True
        return old, dict(saved, cache_hit=True, stale=True, refresh_errors=errors)
    index.save()
    report = dict(version=ASSET_VERSION, fetched_at=time.time(), complete=not errors,
                  database=db_report, source=ICON_SOURCE, assets=assets, errors=errors,
                  features=len(index.names), identities=len(set(index.names)),
                  index_sha256=sha256((root/'index.npz').read_bytes()).hexdigest())
    atomic_json(root/'manifest.json', report)
    index.read_only = True
    return index, dict(report, cache_hit=False)
