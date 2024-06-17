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
from abc import ABC, abstractmethod

from .extras import BilibiliApi, get_character_icon

class Member(BaseModel):
    id:int
    instant:bool = False
    star:int = 5 

class Strategy(BaseModel):
    source:str
    party:list[Member]


_root_path = Path("cache/strategy/")
class LunaTowerStrategist:
    save_path = _root_path/'saved_luna_tower_strategies.txt'

    def __init__(self) -> None:
        self.strategies:dict[str, list[Strategy]] = None
        self._library = _BilibiliLibrary([296496909], _LunaTowerQuery())
    
    def _make_strategies(self):
        self.strategies = self._library.make_strategies()
        if self.strategies:
            _save_strategies(LunaTowerStrategist.save_path, self.strategies)
    
    def gather_information(self):
        saved_strategies = _load_strategies(LunaTowerStrategist.save_path)
        if saved_strategies and saved_strategies.last_update_time > datetime.now() - timedelta(days=15):
            self.strategies = saved_strategies.strategy_dict
        else:
            self._make_strategies()

    def get_strategy(self, level:str) -> list[Strategy]:
        if not self.strategies:
            raise RuntimeError("没有获取到策略信息")
        strategy = self.strategies.get(level, None)
        if not strategy:
            self._make_strategies()
            strategy = self.strategies.get(level, None)
        return strategy
    
    def search_strategy(self, query:str) -> list[Strategy]:
        if not self.strategies:
            raise RuntimeError("没有获取到策略信息")
        ret = []
        for key, strategy in self.strategies.items():
            if query in key:
                ret += strategy
        return ret

class SecretDungeonStrategist:
    save_path = _root_path/'saved_secret_dungeon_strategies.txt'

    def __init__(self) -> None:
        self.strategies:dict[str, list[Strategy]] = None
        self._library = _BilibiliLibrary([296496909], _SecretDungeonQuery(), detect_in_thread=False)
    
    def _make_strategies(self):
        self.strategies = self._library.make_strategies()
        if self.strategies:
            _save_strategies(SecretDungeonStrategist.save_path, self.strategies)
    
    def gather_information(self):
        saved_strategies = _load_strategies(SecretDungeonStrategist.save_path)
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

def _load_strategies(path:Path)->_PerisitStrategies:
    if path.exists():
        with path.open(encoding="utf-8") as f:
            return _PerisitStrategies.model_validate_json(f.read())

def _save_strategies(path:Path, strategies:dict[int, list[Strategy]]):
    perisit_strategies = _PerisitStrategies(strategy_dict=strategies, last_update_time=datetime.now())
    with path.open(mode="w", encoding='utf-8') as f:
        f.write(perisit_strategies.model_dump_json())

class _Detector:

    def __init__(self, dsize, threshold) -> None:
        self.dsize = dsize
        self.threshold = threshold
    
    def detect(self, directory:Path) -> list[Member]:
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
                if id in [1217, 1218]:
                    continue
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
                return [ Member(id=id) for id in ids]
            
class _YoloDetector:

    def __init__(self, pt:Path, save=True) -> None:
        from ultralytics import YOLO
        self.model = YOLO(pt)
        self.save = save
    
    def save_result(self, result, target):
        result = result.cpu().numpy()
        for box in result.boxes:
            (x1, y1, x2, y2) = box.xyxy[0].astype(int)
            cv.rectangle(result.orig_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = result.names[box.cls[0]]
            label_str = "{}: {:.2f}%".format(label, box.conf[0] * 100)
            (text_width, text_height), baseline = cv.getTextSize(label_str, cv.FONT_HERSHEY_SIMPLEX, 0.5, 2)
            cv.rectangle(result.orig_img, (x1, y1 - text_height - baseline), (x1 + text_width, y1), (0, 255, 0), thickness=cv.FILLED)
            cv.putText(result.orig_img, label_str, (x1, y1 - baseline), cv.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        _,img = cv.imencode(".png", result.orig_img)
        img.tofile(target)

    def detect(self, directory:Path) -> list[Member]:
        pictures = directory.glob('*.png')
        for picture in pictures:
            frame:np.ndarray = cv.imdecode(np.fromfile(str(picture), dtype=np.uint8), cv.IMREAD_COLOR)
            result = self.model.predict(frame, verbose=False)[0]
            if self.save:
                icon_dir = directory/f"{picture.stem}"
                icon_dir.mkdir(parents=True, exist_ok=True)
                self.save_result(result, f"{icon_dir}/{picture.name}")
            ids = []
            for cls in result.boxes.cls:
                id = int(result.names[int(cls)])
                if id in [1217, 1218]:
                    continue
                ids.append(id)
            if len(ids) == 5:
                return [Member(id=id) for id in ids]
            
class _Query(ABC):
    
    @abstractmethod
    def filter_search_result(self, search_result)->bool:
        pass
    
    @abstractmethod
    def filter_video_info(self, video_info)->bool:
        pass
    
    @abstractmethod
    def parse_page(self, video_info, page)->str:
        pass
            
class _LunaTowerQuery(_Query):

    def filter_search_result(self, search_result) -> bool:
        title = search_result['title']
        return '公主连结' in title and '露娜塔' in title
    
    def filter_video_info(self, video_info) -> bool:
        return True
    
    def parse_page(self, video_info, page) -> str:
        level = re.findall(r'【(.*?)】', page['part'])
        if not level:
            level = re.findall(r'\d+', page['part'])
        if not level:
            return None
        level = level[0]
        if level == '回廊':
            level = f"{level}-{page['cid']}"
        return level

class _SecretDungeonQuery(_Query):

    def filter_search_result(self, search_result) -> bool:
        title = search_result['title']
        if '公主连结' not in title:
            return False
        return '特别地下城' in title or '特殊地下城' in title
    
    def filter_video_info(self, video_info) -> bool:
        return True
    
    def parse_page(self, video_info, page) -> str:
        level = re.findall(r'\d+?F-?\d*', page['part'])
        if level:
            return level[0]

class _BilibiliLibrary:
    '''
    从Bilibili网站获取攻略信息
    '''
    resouce_path = _root_path/'resource'

    def __init__(self, mids:list[int], query:_Query, detect_in_thread=False) -> None:
        self.api:BilibiliApi = None
        self.mids = mids
        self.query = query
        self._lock = Lock()
        self._collections = None
        # self._detector = _Detector((960,540), 8)
        self._detector = _YoloDetector(Path("cache/pcr_character.pt"))
        self._thread_detect = detect_in_thread
    
    def _get_target_folder(self, mid, bvid, level)->Path:
        return _BilibiliLibrary.resouce_path/f'{mid}'/f'{bvid}'/f'{level}'
    
    def _detect_and_save(self, mid, bvid, level, lock=False):
        target_folder = self._get_target_folder(mid, bvid, level)
        members = self._detector.detect(target_folder)
        if not members:
            return
        if lock:
            with self._lock:
                self._collections[mid][level].append(Strategy(source=bvid, party=members))
        else:
            self._collections[mid][level].append(Strategy(source=bvid, party=members))
    
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
                    for i,t in enumerate([10,15,20,25,30]):
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
                if self.query.filter_search_result(video):
                    candiate_videos.append(video)
            if not candiate_videos:
                continue
            candiate_videos.sort(key=lambda video: video['created'], reverse=True)
            target_video = candiate_videos[0]
            info = self.api.getVideoInfo(avid=target_video['aid'], bvid=target_video['bvid'])
            if not self.query.filter_video_info(info):
                continue
            bvid = info['data']['bvid']
            avid = info['data']['aid']
            for page in info['data']['pages']:
                cid = page['cid']
                level = self.query.parse_page(info, page)
                if not level:
                    continue
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

