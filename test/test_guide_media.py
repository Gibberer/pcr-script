"""Synthetic CDN failures; no public video or account data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import requests

from pcrscript.extras.guide_media import fetch_video


class _Api:
    headers = {'User-Agent': 'test'}

    def __init__(self):
        self.qualities = []

    def getVideoPlay(self, *, cid, bvid, qn):
        self.qualities.append(qn)
        return {'code': 0, 'data': {'quality': qn, 'durl': [{'url': f'https://cdn.invalid/{qn}'}]}}


class _Response:
    headers = {'Content-Length': '4'}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        yield b'test'


class _Http:
    def get(self, url, **kwargs):
        if url.endswith('/64'):
            raise requests.ConnectionError('signed URL must not be persisted')
        return _Response()


class GuideMediaTests(TestCase):
    def test_falls_back_to_smaller_stream_after_cdn_failure(self):
        with TemporaryDirectory() as folder:
            api = _Api()
            with patch('pcrscript.extras.guide_media.video_info', return_value={
                'width': 854, 'height': 480, 'duration': 10}):
                path, info = fetch_video(api, 'BVsynthetic', {'cid': 1, 'duration': 10},
                                         Path(folder), http=_Http(), max_seconds=30)
            self.assertEqual(api.qualities, [64, 32])
            self.assertEqual(info['quality'], 32)
            self.assertEqual(path.read_bytes(), b'test')
