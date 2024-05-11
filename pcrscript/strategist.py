from pydantic import BaseModel
from datetime import datetime,timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import cv2 as cv
import numpy as np
import collections
import av
import re
import os

from .extras import BilibiliApi, get_character_icon

class Strategy(BaseModel):
    source:str
    party:list[int]

class LunaTowerStrategist:

    def __init__(self) -> None:
        self.strategies:dict[str, list[Strategy]] = None
        self._library = _LunaTowerLibrary([296496909])
    
    def _make_strategies(self):
        self.strategies = self._library.make_strategies()
        if self.strategies:
            _save_strategies(self.strategies)
    
    def gather_information(self):
        saved_strategies = _load_strategies()
        if saved_strategies and saved_strategies.last_update_time > datetime.now() - timedelta(days=15):
            self.strategies = saved_strategies.strategy_dict
        else:
            self._make_strategies()

    def find_strategy(self, level:str) -> list[Strategy]:
        if not self.strategies:
            raise RuntimeError("没有获取到策略信息")
        strategy = self.strategies.get(level, None)
        if not strategy:
            self._make_strategies()
            strategy = self.strategies.get(level, None)
        return strategy

class _PerisitStrategies(BaseModel):
    strategy_dict : dict[str, list[Strategy]]
    last_update_time: datetime

_root_path = Path("cache/strategy/")
_saved_strategies_path = _root_path/'saved_strategies.txt'

def _load_strategies()->_PerisitStrategies:
    if _saved_strategies_path.exists():
        with _saved_strategies_path.open(encoding="utf-8") as f:
            return _PerisitStrategies.model_validate_json(f.read())

def _save_strategies(strategies:dict[int, list[Strategy]]):
    perisit_strategies = _PerisitStrategies(strategy_dict=strategies, last_update_time=datetime.now())
    with _saved_strategies_path.open(mode="w", encoding='utf-8') as f:
        f.write(perisit_strategies.model_dump_json())

class _Detector:

    def __init__(self, dsize, threshold) -> None:
        self.dsize = dsize
        self.threshold = threshold
    
    def detect(self, directory:Path):
        pictures = directory.glob('*.png')
        sift = cv.SIFT_create()
        flann = cv.FlannBasedMatcher({'algorithm':1, 'trees':5}, {'checks':50})
        for picture in pictures:
            frame:np.ndarray = cv.imdecode(np.fromfile(str(picture), dtype=np.uint8), cv.IMREAD_COLOR)
            frame = cv.resize(frame, self.dsize)
            kp2,des2 = sift.detectAndCompute(frame,None)
            ids = []
            save = []
            images = []
            for id in range(1001,1918):
                icons = get_character_icon(id)
                if not icons:
                    continue
                for icon,kp1,des1 in icons:
                    matches = flann.knnMatch(des1,des2,k=2)
                    good = 0
                    for m,n in matches:
                        if m.distance < 0.7*n.distance:
                            good+=1
                    if good >= self.threshold:
                        save.append((id, good))
                        images.append((id, icon))
                        ids.append(id)
            # save result
            with open(directory/f"{picture.stem}.txt", 'w') as f:
                f.write(str(save))
            # save matched icons
            icon_dir = directory/f"{picture.stem}"
            icon_dir.mkdir(parents=True, exist_ok=True)
            for id, icon in images:
                _,icon_arr = cv.imencode(".png", icon)
                icon_arr.tofile(f"{icon_dir}/{id}.png")
            if len(ids) == 5:
                return ids
            
class _YoloDetector:

    def __init__(self, pt:Path) -> None:
        from ultralytics import YOLO
        self.model = YOLO(pt)

    def detect(self, directory:Path):
        pictures = directory.glob('*.png')
        for picture in pictures:
            frame:np.ndarray = cv.imdecode(np.fromfile(str(picture), dtype=np.uint8), cv.IMREAD_COLOR)
            result = self.model.predict(frame, verbose=False)[0]
            if len(result.boxes.cls) == 5:
                return [ result.names[int(cls)] for cls in result.boxes.cls]
            


class _LunaTowerLibrary:
    resouce_path = _root_path/'resource'

    def __init__(self, mids:list[int], detect_in_thread=False) -> None:
        self.api:BilibiliApi = None
        self.mids = mids
        self._lock = Lock()
        self._collections = None
        # self._detector = _Detector((960,540), 8)
        self._detector = _YoloDetector(Path("cache/pcr_character.pt"))
        self._thread_detect = detect_in_thread
    
    def _get_target_folder(self, mid, bvid, level)->Path:
        return _LunaTowerLibrary.resouce_path/f'{mid}'/f'{bvid}'/f'{level}'
    
    def _detect_and_save(self, mid, bvid, level, lock=False):
        target_folder = self._get_target_folder(mid, bvid, level)
        ids = self._detector.detect(target_folder)
        if not ids:
            return
        if lock:
            with self._lock:
                self._collections[mid][level].append(Strategy(source=bvid, party=ids))
        else:
            self._collections[mid][level].append(Strategy(source=bvid, party=ids))
    
    def _download_and_detect(self, mid, bvid, avid, level, cid):
        try:
            target_folder = self._get_target_folder(mid, bvid, level)
            target_folder.mkdir(parents=True, exist_ok=True)
            pictures = list(target_folder.glob('*.png'))
            if len(pictures) == 0:
                api = self.api
                play_info = api.getVideoPlay(cid, bvid=bvid, avid=avid)
                url = play_info['data']['durl'][0]['url']
                options = {
                    'cookies':api.headers['Cookie'],
                    'referer':api.headers['Referer'],
                    'user_agent':api.headers['User-Agent'],
                }
                with av.open(url, options=options) as container:
                    video = container.streams.video[0]
                    for i,t in enumerate([10,15,20]):
                        container.seek(int(t/video.time_base)+video.start_time, backward=True, stream=video)
                        frame = next(container.decode(video))
                        frame.to_image().save(target_folder/f'frame{i}.png')
            if self._thread_detect:
                self._detect_and_save(mid, bvid, level, lock=True)
        except Exception as e:
            print(e)
    
    def _fetch(self):
        get_character_icon(1001) # 确保使用线程池之前角色图标已经初始化完毕
        pool = ThreadPoolExecutor(max_workers=os.cpu_count())
        if not self.api:
            self.api = BilibiliApi()
        post_detect_args = [] 
        for mid in self.mids:
            videos = self.api.searchUserVideo(mid=mid)['data']['list']['vlist']
            candiate_videos = []
            for video in videos:
                title = video['title']
                if '公主连结' in title and '露娜塔' in title:
                    candiate_videos.append(video)
            if not candiate_videos:
                continue
            candiate_videos.sort(key=lambda video: video['created'], reverse=True)
            target_video = candiate_videos[0]
            info = self.api.getVideoInfo(avid=target_video['aid'], bvid=target_video['bvid'])
            bvid = info['data']['bvid']
            avid = info['data']['aid']
            for page in info['data']['pages']:
                cid = page['cid']
                level = re.findall(r'【(.*?)】', page['part'])[0]
                if level == '回廊':
                    level = f"{level}-{target_video['created']}"
                pool.submit(self._download_and_detect, mid, bvid, avid, level, cid)
                if not self._thread_detect:
                    post_detect_args.append((mid, bvid, avid, level, cid))
        pool.shutdown()
        if post_detect_args:
            for mid, bvid, avid, level, cid in post_detect_args:
                self._detect_and_save(mid, bvid, level)


    def make_strategies(self)->dict[int,list[Strategy]]:
        self._collections = {mid:collections.defaultdict(list[Strategy]) for mid in self.mids}
        self._fetch()
        ret = collections.defaultdict(list[Strategy])
        for mid in self.mids:
            for key,value in self._collections[mid].items():
                ret[key] += value
        return ret

