import requests
import functools
import urllib.parse
import hashlib
import time
from pathlib import Path

BILIBILI_HOST = "https://bilibili.com"
SEARCH_API = "https://api.bilibili.com/x/web-interface/wbi/search/all/v2"
SEARCH_USER_VIDEO_API = "https://api.bilibili.com/x/space/wbi/arc/search"
VIDEO_URL_API = "https://api.bilibili.com/x/player/wbi/playurl"
VIDEO_INFO_API = "https://api.bilibili.com/x/web-interface/view"

_cookie_path = Path("cache/cookie")

class BilibiliApi:
    mixinKeyEncTab = (
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    )

    def __init__(self) -> None:
        self.headers = {
            'Referer': 'https://www.bilibili.com/',
            'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        }
        if _cookie_path.exists() and _cookie_path.stat().st_size > 1:
            with _cookie_path.open(encoding="utf-8") as f:
                cookie = f.read()
        else:
            r = requests.get(BILIBILI_HOST, headers=self.headers)
            cookie = r.headers["Set-Cookie"]
        self.headers["Cookie"] = cookie
        self._img_key, self._sub_key = self._initWbiKeys()

    def _initWbiKeys(self):
        resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=self.headers)
        resp.raise_for_status()
        json_content = resp.json()
        img_url: str = json_content['data']['wbi_img']['img_url']
        sub_url: str = json_content['data']['wbi_img']['sub_url']
        img_key = img_url.rsplit('/', 1)[1].split('.')[0]
        sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
        return img_key, sub_key

    def _getMixinKey(self, orig:str):
        return functools.reduce(lambda s, i: s + orig[i], BilibiliApi.mixinKeyEncTab, '')[:32]

    def _encWbi(self, params:dict):
        mixin_key = self._getMixinKey(self._img_key + self._sub_key)
        curr_time = round(time.time())
        params['wts'] = curr_time
        params = dict(sorted(params.items()))
        params = {
            k : ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
            for k, v in params.items()
        }
        query = urllib.parse.urlencode(params)
        wbi_sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
        params['w_rid'] = wbi_sign
        return params
    
    def _get(self, url, params=None, sign=True):
        params = self._encWbi(params) if sign else params
        r =  requests.get(url, params=params, headers=self.headers)
        r.raise_for_status()
        return r
    
    def search(self, keyword):
        '''
        综合搜索
        '''
        return self._get(SEARCH_API, {'keyword':keyword}).json()
    
    def searchUserVideo(self, mid, order="pubdate"):
        '''
        用户投稿视频
        该接口有风控，使用自动获取的cookie很容易被风控掉
        '''
        params = {
            "mid":mid, "order":order, "pn":1, "ps":25,
            "dm_cover_img_str": "QU5HTEUgKE5WSURJQSwgTlZJRElBIEdlRm9yY2UgR1QgNzMwICgweDAwMDAxMjg3KSBEaXJlY3QzRDExIHZzXzVfMCBwc181XzAsIEQzRDExKUdvb2dsZSBJbmMuIChOVklESU",
            "dm_img_inter": '{"ds":[{"t":2,"c":"Y2xlYXJmaXggZy1zZWFyY2ggc2VhcmNoLWNvbnRhaW5lcg","p":[1269,1,698],"s":[101,563,618]},{"t":2,"c":"c2VjdGlvbiB2aWRlbyBsb2FkaW5nIGZ1bGwtcm93cw","p":[800,26,1365],"s":[188,2930,1892]}],"wh":[4183,3491,9],"of":[309,618,309]}',
            "dm_img_list": "[]",
            "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
            }
        return self._get(SEARCH_USER_VIDEO_API, params=params).json()
    
    def getVideoInfo(self, bvid=None, avid=None):
        '''
        获取视频信息
        '''
        params = {}
        if bvid:
            params['bvid'] = bvid
        if avid:
            params['avid'] = avid
        return self._get(VIDEO_INFO_API, params, sign=False).json()

    def getVideoPlay(self, cid, bvid=None, avid=None, qn=64):
        '''
        获取视频播放信息
        '''
        params = {
            "avid":avid,
            "bvid":bvid,
            "cid":cid,
            "qn":qn,
        }
        return self._get(VIDEO_URL_API, params).json()