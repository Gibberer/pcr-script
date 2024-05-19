import numpy as np
import cv2 as cv
import os
import collections
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import TypeAlias

Icon:TypeAlias = np.ndarray
KeyPoint:TypeAlias = tuple
KeyPointDesc:TypeAlias = np.ndarray

class _CharacterStorage:
    
    def __init__(self, root) -> None:
        self._root = root
        self._dict = None
        self._lock = Lock()
    
    def _create_dict(self, files):
        sift = cv.SIFT_create()
        for file in files:
            if '_' in file or '.' not in file:
                continue
            icon_id = file[:6]
            if icon_id in ['170161']:
                continue
            chara_id = int(icon_id[:4])
            if chara_id < 1000 or chara_id > 2000:
                continue
            if chara_id in [1217, 1218]:
                continue
            icon = cv.imread(os.path.join(self._root, file))
            kp, des = sift.detectAndCompute(icon,None)
            with self._lock:
                self._dict[chara_id].append((icon, kp, des))

    def _ensure_dict(self):
        if self._dict:
            return
        self._dict = collections.defaultdict(list)
        files = os.listdir(self._root)
        cpu_count = os.cpu_count()
        pool = ThreadPoolExecutor(cpu_count)
        chunk = int(len(files)/cpu_count)
        for i in range(0, cpu_count):
            pool.submit(self._create_dict,files[i*chunk:chunk*(i+1)])
        pool.shutdown()


    def get_character_icon(self, id:int):
        self._ensure_dict()
        return self._dict.get(id, None)


_storage = _CharacterStorage("cache/character/")

def get_character_icon(id:str|int) -> list[tuple[Icon, KeyPoint, KeyPointDesc]]:
    '''
    :param id: 角色id
    :returns:
        - icon 图片列表，一个角色对应多张图标例如3星前和后
        - keypoint 图片特征点
        - description 特征点描述
    '''
    return _storage.get_character_icon(int(id))