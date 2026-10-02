"""Bounded public video retrieval with atomic publication and decode checks."""
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import time
from uuid import uuid4

import cv2 as cv
import requests
from urllib3.exceptions import HTTPError


def media_chunks(response):
    """Check deadlines after each socket read, even on a trickling CDN."""
    read = getattr(getattr(response, 'raw', None), 'read1', None)
    if not callable(read):
        # Alternate HTTP clients must also yield before a large buffer fills.
        yield from response.iter_content(1)
        return
    try:
        while chunk := read(8192, decode_content=False):
            yield chunk
    except HTTPError:
        raise requests.ConnectionError('媒体连接中断') from None


def _transfer(url, headers, temporary, timeout, max_bytes, http=requests, check=lambda: None):
    size = 0
    with http.get(url, headers=headers, timeout=(min(timeout, 15), timeout), stream=True) as response:
        response.raise_for_status()
        length = int(response.headers.get('Content-Length', 0))
        if length > max_bytes:
            raise ValueError('视频超出下载大小限制')
        with Path(temporary).open('wb') as output:
            for chunk in media_chunks(response):
                check()
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('视频超出下载大小限制')
                output.write(chunk)
        if length and size != length:
            raise ValueError('视频下载不完整')
    return size


def _transfer_worker(connection, url, headers, temporary, timeout, max_bytes):
    """A media-only worker: never imports configuration or controls a device."""
    try:
        connection.send(dict(size=_transfer(url, headers, temporary, timeout, max_bytes)))
    except Exception as error:
        # Signed playback URLs must not escape into logs or tracebacks.
        connection.send(dict(error='ValueError:'+str(error) if type(error) is ValueError
                             else type(error).__name__))
    finally:
        connection.close()


def bounded_transfer(url, headers, temporary, timeout, max_bytes, deadline, idle_limit, check):
    """Bound TLS reads too: a partial TLS record can outlive socket timeouts."""
    context = multiprocessing.get_context('spawn')
    receive, send = context.Pipe(duplex=False)
    worker = context.Process(target=_transfer_worker,
                             args=(send, url, headers, str(temporary), timeout, max_bytes), daemon=True)
    progress_size, progress_at = 0, time.monotonic()
    try:
        worker.start()
        send.close()
        while worker.is_alive():
            check()
            now = time.monotonic()
            size = temporary.stat().st_size if temporary.exists() else 0
            if size-progress_size >= 65536:
                progress_size, progress_at = size, now
            if now > deadline:
                raise ValueError('视频下载达到时间边界')
            if now-progress_at > idle_limit:
                raise ValueError('视频下载长时间无有效进展')
            worker.join(.1)
        if not receive.poll():
            raise ValueError('媒体下载进程未返回结果')
        result = receive.recv()
        if 'error' in result:
            raise ValueError('媒体传输失败：'+result['error'])
        return result['size']
    finally:
        if worker.pid is not None:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)
            worker.close()
        receive.close()
        send.close()


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
               'User-Agent': api.headers.get('User-Agent', 'Mozilla/5.0'),
               'Accept-Encoding': 'identity'}
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
                # Leave a CDN that sends only a trickle before it consumes the
                # whole multi-video search window.
                idle_limit = min(60, max_seconds*.4)
                if http is requests:
                    size = bounded_transfer(url, headers, temporary, timeout, max_bytes, phase_end, idle_limit, check)
                else:
                    # Retain custom clients used by synthetic fixtures.
                    progress_size, progress_at = 0, time.monotonic()
                    def transfer_check():
                        nonlocal progress_size, progress_at
                        check()
                        now = time.monotonic()
                        current_size = temporary.stat().st_size if temporary.exists() else 0
                        if current_size-progress_size >= 65536:
                            progress_size, progress_at = current_size, now
                        elif now-progress_at > idle_limit:
                            raise ValueError('视频下载长时间无有效进展')
                        if now > phase_end:
                            raise ValueError('视频下载达到时间边界')
                    size = _transfer(url, headers, temporary, timeout, max_bytes, http=http, check=transfer_check)
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
                errors.append('ValueError:'+str(error) if type(error) is ValueError
                              else type(error).__name__)
            finally:
                temporary.unlink(missing_ok=True)
    raise RuntimeError('视频下载未完成：'+','.join(errors))
