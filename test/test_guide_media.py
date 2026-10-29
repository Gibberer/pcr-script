"""Synthetic CDN failures; no public video or account data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
import time

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
        self.chunk_size = size
        yield b'test'


class _Http:
    def get(self, url, **kwargs):
        if url.endswith('/64'):
            raise requests.ConnectionError('signed URL must not be persisted')
        self.response = _Response()
        return self.response


class _SlowResponse(_Response):
    def __init__(self, clock):
        self.clock = clock

    def iter_content(self, size):
        yield b'x'
        self.clock[0] = 61
        yield b'y'


class _SlowHttp:
    def __init__(self, clock):
        self.clock = clock

    def get(self, url, **kwargs):
        return _SlowResponse(self.clock) if url.endswith('/64') else _Response()


class _RangeHttp:
    def __init__(self, *, corrupt=None):
        self.payload = b'x'*(2*1024**2+73)
        self.ranges = []
        self.corrupt = corrupt

    def get(self, url, *, headers, **kwargs):
        first, last = map(int, headers['Range'].removeprefix('bytes=').split('-'))
        self.ranges.append((first, last))
        last = min(last, len(self.payload)-1)
        response = _Response()
        response.status_code = 206
        total = len(self.payload)
        if self.corrupt == 'offset':
            first += 1
        if self.corrupt == 'total' and first:
            total += 1
        if self.corrupt == 'ignored' and first:
            response.status_code = 200
        response.headers = {'Content-Length': str(last-first+1),
                            'Content-Range': f'bytes {first}-{last}/{total}'}
        data = self.payload[first:last+1]
        if self.corrupt == 'short':
            data = data[:-1]
        response.iter_content = lambda size: iter([data])
        return response


class GuideMediaTests(TestCase):
    def test_small_stream_can_be_requested_without_restarting_large_streams(self):
        with TemporaryDirectory() as folder, patch('pcrscript.extras.guide_media.video_info',
                return_value=dict(width=640,height=360,duration=10)):
            api = _Api()
            fetch_video(api, 'BVsynthetic', {'cid': 1, 'duration': 10}, Path(folder), http=_Http(), preferred_quality=16)
            self.assertEqual(api.qualities, [16])

    def test_explicit_refresh_replaces_valid_cached_media_only_after_download(self):
        with TemporaryDirectory() as folder, patch('pcrscript.extras.guide_media.video_info',
                return_value=dict(width=1280,height=720,duration=10)):
            path = Path(folder)/'BVsynthetic'/'1.mp4'
            path.parent.mkdir()
            path.write_bytes(b'old-valid')
            api = _Api()
            cached, info = fetch_video(api,'BVsynthetic',dict(cid=1,duration=10),Path(folder),http=_Http())
            self.assertEqual(api.qualities,[])
            self.assertEqual(cached.read_bytes(),b'old-valid')
            self.assertTrue(info['cache_hit'])
            updated, info = fetch_video(api,'BVsynthetic',dict(cid=1,duration=10),Path(folder),http=_Http(),refresh=True)
            self.assertEqual(api.qualities,[64,32])
            self.assertEqual(updated.read_bytes(),b'test')
            self.assertFalse(info['cache_hit'])

    def test_failed_refresh_preserves_existing_media_and_removes_partial_files(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'BVsynthetic'/'1.mp4'
            path.parent.mkdir()
            path.write_bytes(b'old-valid')
            http = Mock(get=Mock(side_effect=requests.ConnectionError('synthetic')))
            with self.assertRaises(RuntimeError):
                fetch_video(_Api(),'BVsynthetic',dict(cid=1,duration=10),Path(folder),http=http,refresh=True)
            self.assertEqual(path.read_bytes(),b'old-valid')
            self.assertFalse(list(Path(folder).rglob('*.part')))

    def test_verified_ranges_publish_only_the_complete_video(self):
        with TemporaryDirectory() as folder:
            http = _RangeHttp()
            with patch('pcrscript.extras.guide_media.video_info', return_value={
                    'width': 854, 'height': 480, 'duration': 10}):
                path, info = fetch_video(_Api(), 'BVsynthetic', {'cid': 1, 'duration': 10},
                                        Path(folder), http=http)
            self.assertEqual(path.read_bytes(), http.payload)
            self.assertEqual(info['bytes'], len(http.payload))
            self.assertEqual([r[0] for r in http.ranges], [0, 1024**2, 2*1024**2])

    def test_corrupt_or_incomplete_ranges_never_publish_media(self):
        for corrupt in ('offset', 'total', 'ignored', 'short'):
            with self.subTest(corrupt=corrupt), TemporaryDirectory() as folder:
                with self.assertRaises(RuntimeError), patch('pcrscript.extras.guide_media.video_info') as decode:
                    fetch_video(_Api(), 'BVsynthetic', {'cid': 1}, Path(folder), http=_RangeHttp(corrupt=corrupt))
                decode.assert_not_called()
                self.assertFalse(list(Path(folder).rglob('*.mp4')))
                self.assertFalse(list(Path(folder).rglob('*.part')))

    def test_invalid_media_url_is_not_exposed_in_diagnostics(self):
        secret='https://example.com/synthetic?signature=private-value'
        with TemporaryDirectory() as folder:
            http=Mock()
            http.get.side_effect=requests.exceptions.InvalidURL(secret)
            with self.assertRaises(RuntimeError) as caught:
                fetch_video(_Api(),'BVsynthetic',{'cid':1},Path(folder),http=http)
            self.assertIn('InvalidURL',str(caught.exception))
            self.assertNotIn(secret,str(caught.exception))

    def test_trickle_stream_cannot_hide_download_deadline(self):
        requests_seen=[]
        stopped=Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests_seen.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', '500')
                self.end_headers()
                try:
                    for _ in range(500):
                        if stopped.is_set():
                            break
                        self.wfile.write(b'x')
                        self.wfile.flush()
                        stopped.wait(.05)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker=Thread(target=server.serve_forever,daemon=True)
            worker.start()
            api=_Api()
            api.getVideoPlay=lambda **kwargs: {'code':0,'data':{'durl':[
                {'url':f'http://127.0.0.1:{server.server_port}/synthetic'}]}}
            try:
                with TemporaryDirectory() as folder:
                    started=time.monotonic()
                    with self.assertRaises(RuntimeError):
                        fetch_video(api,'BVsynthetic',{'cid':1},Path(folder),max_seconds=3)
                    self.assertLess(time.monotonic()-started,4.5)
                    self.assertTrue(requests_seen,'The deadline must bound an actual network read')
                    self.assertFalse(list(Path(folder).rglob('*.part')))
                    self.assertFalse(list(Path(folder).rglob('*.mp4')))
            finally:
                stopped.set()
                server.shutdown()
                worker.join(timeout=2)

    def test_falls_back_to_smaller_stream_after_cdn_failure(self):
        with TemporaryDirectory() as folder:
            api = _Api()
            http = _Http()
            with patch('pcrscript.extras.guide_media.video_info', return_value={
                'width': 854, 'height': 480, 'duration': 10}):
                path, info = fetch_video(api, 'BVsynthetic', {'cid': 1, 'duration': 10},
                                         Path(folder), http=http, max_seconds=30)
            self.assertEqual(api.qualities, [64, 32])
            self.assertLessEqual(http.response.chunk_size, 8192)
            self.assertEqual(info['quality'], 32)
            self.assertEqual(path.read_bytes(), b'test')

    def test_abandons_cdn_without_meaningful_byte_progress(self):
        with TemporaryDirectory() as folder:
            clock = [0.0]
            api = _Api()
            with (patch('pcrscript.extras.guide_media.time.monotonic', side_effect=lambda: clock[0]),
                  patch('pcrscript.extras.guide_media.video_info', return_value={
                      'width': 854, 'height': 480, 'duration': 10})):
                path, info = fetch_video(api, 'BVsynthetic', {'cid': 1, 'duration': 10},
                                         Path(folder), http=_SlowHttp(clock), max_seconds=300)
            self.assertEqual(api.qualities, [64, 32])
            self.assertEqual(info['quality'], 32)
            self.assertEqual(path.read_bytes(), b'test')
            self.assertFalse(list(Path(folder).rglob('*.part')))

    def test_standard_stream_remains_available_after_two_higher_quality_failures(self):
        with TemporaryDirectory() as folder:
            api = _Api()
            http = Mock()
            http.get.side_effect = [requests.ConnectionError(),requests.ConnectionError(),_Response()]
            with patch('pcrscript.extras.guide_media.video_info',return_value={
                    'width':640,'height':360,'duration':10}):
                path,info = fetch_video(api,'BVsynthetic',{'cid':1,'duration':10},
                                       Path(folder),http=http,max_seconds=30)
            self.assertEqual(api.qualities,[64,32,16])
            self.assertEqual(info['quality'],16)
            self.assertEqual(path.read_bytes(),b'test')
            self.assertFalse(list(Path(folder).rglob('*.part')))

    def test_standard_stream_has_reserved_time_after_two_trickling_streams(self):
        clock = [0.0]
        class Trickle(_Response):
            headers = {'Content-Length':'0'}
            def iter_content(self,size):
                while True:
                    clock[0] += 2
                    yield b'x'
        class Standard(_Response):
            def iter_content(self,size):
                for byte in b'test':
                    clock[0] += 2
                    yield bytes([byte])
        http = Mock()
        http.get.side_effect = lambda url,**kwargs: Standard() if url.endswith('/16') else Trickle()
        with TemporaryDirectory() as folder, \
             patch('pcrscript.extras.guide_media.time.monotonic',side_effect=lambda:clock[0]), \
             patch('pcrscript.extras.guide_media.video_info',return_value={'width':640,'height':360,'duration':10}):
            api = _Api()
            path,info = fetch_video(api,'BVsynthetic',{'cid':1,'duration':10},
                                   Path(folder),http=http,max_seconds=30)
            self.assertEqual(api.qualities,[64,32,16])
            self.assertEqual(info['quality'],16)
            self.assertEqual(path.read_bytes(),b'test')
            self.assertLessEqual(clock[0],30)
            self.assertFalse(list(Path(folder).rglob('*.part')))

    def test_standard_endpoint_failure_refreshes_playback_once_within_deadline(self):
        with TemporaryDirectory() as folder:
            api = _Api()
            http = Mock()
            http.get.side_effect = [requests.ConnectionError()]*3+[_Response()]
            with patch('pcrscript.extras.guide_media.video_info',return_value={
                    'width':640,'height':360,'duration':10}):
                path,info = fetch_video(api,'BVsynthetic',{'cid':1,'duration':10},
                                       Path(folder),http=http,max_seconds=30)
            self.assertEqual(api.qualities,[64,32,16,16])
            self.assertEqual(info['quality'],16)
            self.assertEqual(path.read_bytes(),b'test')
            self.assertFalse(list(Path(folder).rglob('*.part')))
