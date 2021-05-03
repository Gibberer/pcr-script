import sys
import os.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import collections
import re
import time
import threading
import yaml
import numpy as np
from pcrscript.ocr import Ocr
from pcrscript.driver import Driver
from pcrscript.constants import *
from pcrscript import *
from typing import Iterable, Tuple
from cv2 import cv2 as cv


UB_ERROR_CHECK_DURATION = 2
UB_THRESHOLD = 0.85
INTERVAL = 0.5
LONG_INTERVAL = 1
SP_REGIONS = (
    (677, 518, 763, 525),
    (557, 518, 645, 525),
    (438, 518, 524, 525),
    (317, 518, 404, 525),
    (197, 518, 284, 525),
)
UB_LOCATIONS = (
    (718, 446),
    (597, 446),
    (483, 446),
    (361, 446),
    (239, 446),
)


class AutoBattle:

    def __init__(self, driver: Driver):
        self._driver = driver
        self._ocr = Ocr(['en'], gpu=False, recog_network='english_g2')
        self._devicewidth, self._deviceheight = driver.getScreenSize()
        self._running = False
        self._pause = False
        self._thread = None
        self._condition: threading.Condition = threading.Condition(
            threading.Lock())
        self._imagecache = {}
        self._config = None
        self._operations = collections.defaultdict(list)
        self._pending = []

    def load(self, config_file):
        with open(config_file, encoding='utf-8') as f:
            self._config = yaml.load(f, Loader=yaml.FullLoader)
            self._operations.clear()
            for operation in self._config['operation_list']:
                seconds, location = operation.split()
                self._operations[int(float(seconds))].append(int(location) - 1)

    def start(self):
        if self._thread:
            self.stop()
        if self._config is None:
            raise Exception("load config file first")
        self._running = True
        self._pause = False
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
        self._waitinput()

    def pause(self):
        self._pause = True
        self._waitinput()

    def resume(self):
        self._pause = False
        with self._condition:
            self._condition.notify()
        self._waitinput()

    def stop(self):
        self._running = False
        with self._condition:
            self._condition.notify()
        if self._thread:
            print("等待当前任务结束")
            self._thread.join()
            self._thread = None

    def _waitinput(self):
        opt = input('输入操作:').lower()
        if opt == 's':
            self.stop()
        elif opt == 'r':
            self.resume()
        elif opt == 'p':
            self.pause()
        else:
            print("未知操作")
            self._waitinput()

    def _run(self):
        last_seconds,remain_seconds = None, None
        while self._running:
            starttime = time.time()
            screenshot = self._driver.screenshot()
            if self._pause:
                self._dopause(screenshot)
                with self._condition:
                    self._condition.wait()
            else:
                self._doresume(screenshot)
            self._errorcheck(screenshot)
            last_seconds = remain_seconds
            remain_seconds = self._readtime(screenshot)
            if not remain_seconds:
                self._waitnext(starttime)
                continue
            sp = self._readsp(screenshot)
            if self._pending:
                for i in range(len(self._pending) - 1, -1, -1):
                    tseconds, loc, trigger = self._pending[i]
                    if tseconds - remain_seconds > UB_ERROR_CHECK_DURATION:
                        self._pending.pop(i)
                    elif trigger and sp[loc] < UB_THRESHOLD:
                        self._pending.pop(i)
            if self._pending:
                for tseconds, loc, trigger in self._pending:
                    self._clickub(loc)
            if self._pending:
                print(self._pending)
            if last_seconds != remain_seconds:
                newoperations = self._operations[remain_seconds]
                if newoperations:
                    for loc in newoperations:
                        trigger = False
                        if sp[loc] >= UB_THRESHOLD:
                            trigger = True
                            self._clickub(loc)
                        else:
                            trigger = False
                        self._pending.append((remain_seconds, loc, trigger))

            self._waitnext(starttime)

    def _waitnext(self, starttime):
        consume = time.time() - starttime
        if consume < INTERVAL:
            time.sleep(INTERVAL - consume)

    def _dopause(self, screenshot):
        self._driver.click(*self._pos(900, 27))

    def _doresume(self, screenshot):
        ret = self._find_match_pos(screenshot, "btn_return")
        if ret:
            self._driver.click(*ret)

    def _errorcheck(self, screenshot):
        pass

    def _find_match_pos(self, screenshot, template, threshold=THRESHOLD) -> Tuple[int, int]:
        name = template
        source: np.ndarray
        if isinstance(screenshot, np.ndarray):
            source = screenshot
        else:
            source = cv.imread(screenshot)
        templatepath = "images/{}.png".format(template)
        if templatepath in self._imagecache:
            template = self._imagecache[templatepath]
        else:
            template = cv.imread(templatepath)
            height, width = source.shape[:2]
            fx = width/BASE_WIDTH
            fy = height/BASE_HEIGHT
            template = cv.resize(template, None, fx=fx, fy=fy,
                                 interpolation=cv.INTER_AREA)
            self._imagecache[templatepath] = template
        theight, twidth = template.shape[:2]
        ret = cv.matchTemplate(source, template, cv.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv.minMaxLoc(ret)
        if max_val > threshold:
            return (max_loc[0] + twidth/2, max_loc[1] + theight/2)
        else:
            return None

    def _clickub(self, index):
        x, y = self._pos(*UB_LOCATIONS[index])
        self._driver.click(x, y)

    def _readsp(self, screenshot):
        '''
        返回当前5个角色对应的能量条状态
        '''
        ret = [0] * len(SP_REGIONS)
        for i in range(len(SP_REGIONS)):
            roi = self._roi(*SP_REGIONS[i])
            img = screenshot[roi[1]:roi[3], roi[0]:roi[2]]
            _, img = cv.threshold(img, 80, 255, cv.THRESH_BINARY)
            center = (img.shape[0] - 1) // 2
            for j in range(img.shape[1]):
                if (img[center, j] == 0).all():
                    ret[i] = float(j) / img.shape[1]
                    break
                ret[i] = 1
        return ret

    def _readtime(self, screenshot):
        ret = self._readtext(screenshot, 809, 15, 841, 35)
        if not ret:
            return None
        text = ret[0]
        text = text.strip()
        minute, seconds = None, None
        if len(text) == 4:
            # '1.24' '1:24' '1;24'
            text = re.sub(r'[.;|]', ':', text)
            splits = text.split(":")
            if len(splits) >= 2:
                minute = splits[0]
                seconds = splits[1]
        elif len(text) == 3:
            # '124' '001'
            minute = text[:1]
            seconds = text[1:]
        if minute and seconds and minute.isdigit() and seconds.isdigit():
            return 60 * int(minute) + int(seconds)
        else:
            print(f"error parse:{ret[0]}")
            return None

    def _readtext(self, screenshot, left, top, right, bottom):
        roi = self._roi(left, top, right, bottom)
        img = screenshot[roi[1]:roi[3], roi[0]:roi[2]]
        return self._ocr.recognize(img)

    def _showimg(self, img):
        cv.imshow('window', img)
        if cv.waitKey(25) & 0xFF == ord('q'):
            cv.destroyAllWindows()

    def _pos(self, x, y) -> Tuple[int, int]:
        return(int((x/BASE_WIDTH)*self._devicewidth), int((y/BASE_HEIGHT)*self._deviceheight))

    def _roi(self, left, top, right, bottom) -> Tuple[int, int, int, int]:
        return (*self._pos(left, top), *self._pos(right, bottom))


if __name__ == '__main__':
    drivers = DNSimulator2("").get_dirvers()
    auto_battle = AutoBattle(drivers[0])
    auto_battle.load("autobattle_config.yml")
    auto_battle.start()
