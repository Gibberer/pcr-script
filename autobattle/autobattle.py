import sys
import os.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cv2 import cv2 as cv
from typing import Iterable, Tuple
from pcrscript import *
from pcrscript.constants import *
from pcrscript.driver import Driver
from pcrscript.ocr import Ocr
import yaml
import threading
import time


INTERVAL = 0.1
LONG_INTERVAL = 1

class AutoBattle:
    
    def __init__(self, driver:Driver):
        self._driver = driver
        self._ocr = Ocr(['en'], gpu=False, recog_network='english_g2')
        self._devicewidth, self._deviceheight = driver.getScreenSize()
        self._running = False
        self._pause = False
        self._thread = None
        self._condition : threading.Condition = threading.Condition(threading.Lock())
        self._imagecache = {}

    def start(self):
        if self._thread:
            self.stop()
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
            ret = self._readtext(screenshot, 804,15,836,35)
            if ret:
                print(ret)
            else:
                print("None")
            consume = time.time() - starttime
            print(f"Consume:{consume}")
            if consume < INTERVAL:
                time.sleep(INTERVAL - consume)

    
    def _dopause(self, screenshot):
        pass

    def _doresume(self, screenshot):
        pass
    
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
    
    def _readtext(self, screenshot, left, top, right, bottom):
        roi = self._roi(left, top, right, bottom)
        img = screenshot[roi[1]:roi[3],roi[0]:roi[2]]
        # ret, img = cv.threshold(img, 220, 255, cv.THRESH_BINARY)
        # cv.imshow('window', img)
        # if cv.waitKey(25) & 0xFF == ord('q'):
        #     cv.destroyAllWindows()
        return self._ocr.recognize(img)

    def _pos(self, x, y) -> Tuple[int, int]:
        return(int((x/BASE_WIDTH)*self._devicewidth), int((y/BASE_HEIGHT)*self._deviceheight))

    def _roi(self, left, top, right, bottom) -> Tuple[int, int, int, int]:
        return (*self._pos(left, top), *self._pos(right, bottom))
    
if __name__ == '__main__':
    with open("daily_config.yml", encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    drivers = DNSimulator2(config['Extra']['dnpath']).get_dirvers()
    AutoBattle(drivers[0]).start()