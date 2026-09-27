"""Bounded public video retrieval with atomic publication and decode checks."""
from __future__ import annotations

import json
from pathlib import Path
import time
from uuid import uuid4

import cv2 as cv
import requests


def video_info(path: Path) -> dict:
    capture = cv.VideoCapture(str(path))
    try:
        fps = capture.get(cv.CAP_PROP_FPS)
        frames = capture.get(cv.CAP_PROP_FRAME_COUNT)
        ok, _ = capture.read()
        if not ok or fps <= 0 or frames < 1:
            raise ValueError('视频无法解码')
        return dict(width=int(capture.get(cv.CAP_PROP_FRAME_WIDTH)),
                    height=int(capture.get(cv.CAP_PROP_FRAME_HEIGHT)), duration=frames/fps)
    finally:
        capture.release()


def fetch_video(api, bvid: str, page: dict, directory: Path, *, http=requests,
                timeout: float = 20, max_bytes: int = 250*1024**2,
                max_seconds: float = 180, check=lambda: None) -> tuple[Path, dict]:
    directory = Path(directory)/bvid
    directory.mkdir(parents=True, exist_ok=True)
    cid = int(page['cid'])
    path = directory/f'{cid}.mp4'
    expected = float(page.get('duration', 0))
    if path.exists():
        try:
            info = video_info(path)
            if expected <= 0 or abs(info['duration']-expected) < max(3, expected*.03):
                return path, dict(info, cache_hit=True)
        except ValueError:
            pass
    # Never forward local browser/login cookies to video CDNs.
    headers = {'Referer': f'https://www.bilibili.com/video/{bvid}/',
               'User-Agent': api.headers.get('User-Agent', 'Mozilla/5.0')}
    started = time.monotonic()
    errors = []
    for requested_quality in (64, 32):
        check()
        if time.monotonic()-started >= max_seconds:
            break
        play = api.getVideoPlay(cid=cid, bvid=bvid, qn=requested_quality)
        data = play.get('data', {})
        media = data.get('durl', [])
        if play.get('code') != 0 or len(media) != 1:
            errors.append('公开播放信息不可用或视频分段格式暂不支持')
            continue
        # Reserve part of the bounded download window for a smaller stream
        # when every high-quality CDN endpoint fails mid-transfer.
        phase_end = started + max_seconds * (.65 if requested_quality == 64 else 1)
        for url in ([media[0].get('url')]+media[0].get('backup_url', []))[:3]:
            check()
            if not url or time.monotonic() >= phase_end:
                continue
            temporary = path.with_suffix('.'+uuid4().hex+'.part')
            try:
                size = 0
                with http.get(url, headers=headers, timeout=(min(timeout, 15), timeout), stream=True) as response:
                    response.raise_for_status()
                    length = int(response.headers.get('Content-Length', 0))
                    if length > max_bytes:
                        raise ValueError('视频超出下载大小限制')
                    with temporary.open('wb') as output:
                        for chunk in response.iter_content(65536):
                            check()
                            size += len(chunk)
                            if size > max_bytes or time.monotonic() > phase_end:
                                raise ValueError('视频下载达到时间/大小边界')
                            output.write(chunk)
                    if length and size != length:
                        raise ValueError('视频下载不完整')
                info = video_info(temporary)
                if expected > 0 and abs(info['duration']-expected) >= max(3, expected*.03):
                    raise ValueError('解码视频时长与来源不符')
                temporary.replace(path)
                report = dict(info, cache_hit=False, cid=cid, bvid=bvid, fetched_at=time.time(),
                              bytes=size, quality=data.get('quality'))
                path.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                return path, report
            except (requests.RequestException, ValueError, OSError) as error:
                # Network exceptions can contain signed CDN URLs, so keep
                # only their class names in persisted diagnostics.
                errors.append('ValueError:'+str(error) if isinstance(error, ValueError)
                              else type(error).__name__)
            finally:
                temporary.unlink(missing_ok=True)
    raise RuntimeError('视频下载未完成：'+','.join(errors))
