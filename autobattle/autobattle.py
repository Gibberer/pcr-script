import sys
import collections
import re
import time
import threading
import numpy as np
import yaml
from pcrscript.ocr import Ocr
from pcrscript.driver import Driver
from pcrscript.constants import *
from pcrscript import *
from typing import Iterable, Tuple
from cv2 import cv2 as cv


UB_ERROR_CHECK_DURATION = 3
UB_MIN_CHECK_DURATION = 1
UB_THRESHOLD = 0.85
UB_THRESHOLD_LOWER_BOUND = 0.4
INTERVAL = 0.1
LONG_INTERVAL = 1
SP_REGIONS = (
    (680, 520, 762, 527),
    (562, 520, 644, 527),
    (444, 520, 523, 527),
    (324, 520, 403, 527),
    (199, 520, 283, 527),
)
UB_LOCATIONS = (
    (718, 400),
    (597, 400),
    (483, 400),
    (361, 400),
    (239, 400),
)

class Task:

    def __init__(self, expecttime, loc, createtime):
        self.expecttime = expecttime
        self.createtime = createtime
        self.loc = loc
        self.triggertime = -1
        self.delay = 0


class AutoBattle:

    def __init__(self, driver: Driver):
        print("初始化...")
        self._driver = driver
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
        self._jobs = []
        self._lastsp = [0] * len(SP_REGIONS)
        self._listener = None
        self._cur_seconds = 0
        self._cur_time = 0

    def load(self, config_file):
        print("加载配置文件中...")
        global UB_THRESHOLD
        global UB_ERROR_CHECK_DURATION
        global INTERVAL
        global LONG_INTERVAL
        with open(config_file, encoding='utf-8') as f:
            self._config = yaml.load(f, Loader=yaml.FullLoader)
            self._jobs.clear()
            self._operations.clear()
            if 'ub_check_threshold' in self._config:
                UB_THRESHOLD = float(self._config['ub_check_threshold'])
            if 'ub_check_timeout' in self._config:
                UB_ERROR_CHECK_DURATION = float(self._config['ub_check_timeout'])
            if 'click_interval' in self._config:
                INTERVAL = float(self._config['click_interval'])
            if 'read_time_interval' in self._config:
                LONG_INTERVAL = float(self._config['read_time_interval'])
            if 'listen_mouse_event' in self._config and self._config['listen_mouse_event']:
                from pynput.mouse import Listener

                def on_click(x,y, button, pressed):
                    wx, wy = self._driver.getRootWindowLocation()
                    tx, ty = x - wx, y - wy
                    if tx < 0 or tx > self._devicewidth or ty < 0 or ty > self._deviceheight:
                        # 设备外区域忽略
                        pass
                    else:
                        if (150 < tx < 800) and (350 < ty < 500):
                            # ub区域
                            no = int(5 - (tx - 150) / 150)
                            cur_time = time.time()
                            print(f"点击第{no}位，当前时间：{self._cur_seconds}，偏移时间: {cur_time - self._cur_time}")
                        else:
                            pass 
                
                self._listener = Listener(on_click=on_click)

            for name,operations in self._config['job_list'].items():
                self._jobs.append((name, operations))
            if 'use_ocr' in self._config and self._config['use_ocr']:
                self._ocr = Ocr(['en'], gpu=self._config['gpu'], recog_network='english_g2')
            else:
                self._ocr = None
                self._precache_time_template()            

    def start(self):
        print("准备启动脚本")
        if self._thread:
            self.stop()
        if self._config is None:
            raise Exception("load config file first")
        self._running = True
        self._pause = False
        self._thread = threading.Thread(target=self._run)
        self._thread.start()
        if self._listener:
            self._listener.start()
        print("AutoBattle script run key commands:\n\033[1mp\033[0m  Pause.\n\033[1mr\033[0m  Resume.\n\033[1ms\033[0m  Stop.\n\033[1mc\033[0m  Show config list.")
        self._waitinput()

    def pause(self):
        print("执行暂停操作")
        self._pause = True

    def resume(self):
        print("执行恢复操作")
        self._pause = False
        with self._condition:
            self._condition.notify()

    def stop(self):
        print("执行停止操作")
        self._running = False
        with self._condition:
            self._condition.notify()
        if self._thread:
            self._thread.join()
            self._thread = None
        if self._listener:
            self._listener.stop()
    
    def choiceConfig(self, no):
        name, operations = self._jobs[no]
        self._operations.clear()
        for operation in operations:
            splits = operation.split()
            seconds = int(float(splits[0]))
            location = int(splits[1]) - 1
            delay = 0
            if len(splits) > 2:
                delay = float(splits[2])
            self._operations[seconds].append((location, delay))
        print(f"已选择{name}, 按r恢复运行")


    def _waitinput(self):            
        while True:
            sys.stdout.flush()
            opt = sys.stdin.readline().strip()
            if opt == 's':
                self.stop()
                break
            elif opt == 'r':
                self.resume()
            elif opt == 'p':
                self.pause()
            elif opt.isdigit():
                if self._pending:
                    self._pending.clear()
                self.choiceConfig(int(opt))
            elif opt == 'c':
                if self._pause:
                    self._showconfiglist()
                else:
                    print("请先暂停")
            else:
                if opt:
                    print(f"收到未知操作符:{opt}")
                else:
                    print(f"收到EOF信息")
        

    def _run(self):
        last_seconds,remain_seconds = None, None
        remain_seconds_time = 0
        last_readtime = 0
        battle_start_time = 0
        symbol_error_count = 0
        sp = None
        while self._running:
            sys.stdout.flush()
            starttime = time.time()
            screenshot = self._driver.screenshot()
            if not self._operations:
                self._pause = True
                print("选择配置：")
                self._showconfiglist()
            if self._pause:
                self._dopause(screenshot)
                if remain_seconds:
                    print(f"当前时间{remain_seconds}，偏移时间：{starttime - remain_seconds_time}")
                with self._condition:
                    self._condition.wait()
            else:
                self._doresume(screenshot)
            # has_symbol = self._find_match_pos(screenshot, "btn_auto")
            # if not has_symbol:
            #     symbol_error_count += 1
            #     if symbol_error_count > 20:
            #         symbol_error_count = 0
            #         self._pending.clear()
            #         print("当前不处于战斗界面，已暂停")
            #         self._pause = True
            #         with self._condition:
            #             self._condition.wait()
            # elif battle_start_time == 0:
            #     battle_start_time = starttime
            #     print("已处于战斗界面，开始执行任务")
            self._errorcheck(screenshot)
            last_seconds = remain_seconds
            if not remain_seconds or starttime - last_readtime >= LONG_INTERVAL:
                _read_time = self._readtime(screenshot)
                if _read_time:
                    last_readtime = time.time()
                    if last_seconds != None:
                        expect_time = last_seconds - 1
                        if (_read_time > last_seconds) or ( _read_time < expect_time - 3):
                            print(f"读取到错误的时间，期望:{expect_time},实际读取:{_read_time}")
                            self._waitnext(starttime)
                            continue
                    remain_seconds = _read_time
            if not remain_seconds:
                self._waitnext(starttime)
                continue 
            
            sp = self._readsp(screenshot)
            if sp == None:
                self._waitnext(starttime)
                continue
            if self._pending:
                for i in range(len(self._pending) - 1, -1, -1):
                    task = self._pending[i]
                    if task.expecttime - remain_seconds > UB_ERROR_CHECK_DURATION:
                        # 过期
                        self._pending.pop(i)
                        self._logtask(task, isexpired=True)
                    elif task.triggertime >= 0 and sp[task.loc] <= UB_THRESHOLD_LOWER_BOUND:
                        # 释放UB成功
                        if task.expecttime - remain_seconds >= UB_MIN_CHECK_DURATION: 
                            self._pending.pop(i)
                            self._logtask(task)
                if self._pending:        
                    for task in self._pending:
                        clickable = True
                        if task.triggertime < 0:
                            if starttime - task.createtime - task.delay>= 0 and sp[task.loc] >= UB_THRESHOLD:
                                task.triggertime = starttime
                            elif task.delay > 0:
                                clickable = False
                        if clickable:
                            self._clickub(task.loc) 
                          
            if last_seconds != remain_seconds:
                print(f"剩余时间: {remain_seconds}")
                self._cur_time = starttime
                self._cur_seconds = remain_seconds
                remain_seconds_time = starttime
                newoperations = []
                if last_seconds and last_seconds - remain_seconds > 1:
                    print(f"Error:{last_seconds} - {remain_seconds}中的时间未解析到")
                    for i in range(last_seconds - 1, remain_seconds - 1, -1):
                        newoperations += self._operations[i]
                else:
                    newoperations = self._operations[remain_seconds]
                if newoperations:
                    for loc, delay in newoperations:
                        task = Task(remain_seconds, loc, starttime)
                        task.delay = delay
                        if delay == 0 and sp[loc] >= UB_THRESHOLD:
                            self._clickub(loc)
                            task.triggertime = starttime
                        self._pending.append(task)

            self._waitnext(starttime)

    
    def _showconfiglist(self):
        for i, job in enumerate(self._jobs):
            print(f"{i}:{job[0]}")


    def _logtask(self,task, isexpired=False):
        no = task.loc + 1
        targettime = task.expecttime
        offset = task.triggertime - task.createtime
        if isexpired:
            print(f"确认{no}UB释放超时，指定时间点为{targettime}，指定偏移{task.delay},触发真实时间偏移{offset}")
        else:
            print(f"确认{no}UB释放成功，指定时间点为{targettime}，指定偏移{task.delay},触发真实时间偏移{offset}")


    def _waitnext(self, starttime):
        consume = time.time() - starttime
        if consume < INTERVAL:
            time.sleep(INTERVAL - consume)
        else:
            # print(f"卡帧：{consume}")
            pass

    def _dopause(self, screenshot):
        self._driver.click(*self._pos(900, 27))

    def _doresume(self, screenshot):
        ret = self._find_match_pos(screenshot, "btn_return")
        if ret:
            self._driver.click(*ret)

    def _errorcheck(self, screenshot):
        pass

    def _find_match_pos(self, screenshot, template, threshold=THRESHOLD, directory="images") -> Tuple[int, int]:
        name = template
        source: np.ndarray
        if isinstance(screenshot, np.ndarray):
            source = screenshot
        else:
            source = cv.imread(screenshot)
        templatepath = f"{directory}/{template}.png"
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
    
    def _similar(self, src:np.ndarray, template, directory="images"):
        # 判断余弦相似度
        templatepath = f"{directory}/{template}.png"
        if templatepath in self._imagecache:
            template = self._imagecache[templatepath]
        else:
            template = cv.imread(templatepath)
            fx = self._devicewidth/BASE_WIDTH
            fy = self._deviceheight/BASE_HEIGHT
            template = cv.resize(template, None, fx=fx, fy=fy,
                                 interpolation=cv.INTER_AREA)
            self._imagecache[templatepath] = template
        src = cv.cvtColor(src, cv.COLOR_BGR2GRAY)
        template = cv.cvtColor(template, cv.COLOR_BGR2GRAY)
        _, src = cv.threshold(src, 200, 255, cv.THRESH_BINARY)
        _, template = cv.threshold(template, 200, 255, cv.THRESH_BINARY)
        x = src.astype(np.int32).flatten()
        y = template.astype(np.int32).flatten()
        return np.dot(x,y)/(np.linalg.norm(x)*np.linalg.norm(y))

    def _clickub(self, index):
        x, y = self._pos(*UB_LOCATIONS[index])
        self._driver.click(x, y)
        time.sleep(0.015)

    def _readsp(self, screenshot):
        '''
        返回当前5个角色对应的能量条状态
        '''
        ret = [0] * len(SP_REGIONS)
        error_detected = False
        for i in range(len(SP_REGIONS)):
            roi = self._roi(*SP_REGIONS[i])
            img = screenshot[roi[1]:roi[3], roi[0]:roi[2]]
            center = (img.shape[0] - 1) // 2
            found = 0
            for j in range(img.shape[1]):
                color = img[center, j]
                gray = self._gray(color)
                if gray < 60:
                    ret[i] = float(j) / img.shape[1]
                    found = 1
                    break
                elif color[0] >= 145 and 125 <= color[1] <= 230 and 40 <= color[2] <= 70:
                    pass
                else:
                    cv.imwrite(f"{i}_a.png", img)
                    found = 2
                    break
            if found == 0:
                ret[i] = 1
            elif found != 1:
                ret[i] = self._lastsp[i]
        self._lastsp = ret
        return ret
    
    def _gray(self, color):
        return color[0] * 0.299 + color[1] * 0.587 + color[2] * 0.114

    def _readtime(self, screenshot):
        if self._ocr is None:
            return self._readtime_from_template(screenshot, 809, 15, 841, 35)
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
    
    def _precache_time_template(self):
        for i in range(1, 91):
            path = f'autobattle/images/time/{i}.png'
            template = cv.imread(path)
            fx = self._devicewidth/BASE_WIDTH
            fy = self._deviceheight/BASE_HEIGHT
            template = cv.resize(template, None, fx=fx, fy=fy,
                                 interpolation=cv.INTER_AREA)
            self._imagecache[path] = template


    def _readtime_from_template(self, screenshot, left, top, right, bottom):
        start = time.time()
        roi = self._roi(left, top, right, bottom)
        img = screenshot[roi[1]:roi[3], roi[0]:roi[2]]
        cur = None
        cur_max_value = 0
        for i in range(1, 91):
            ret = self._similar(img, f"{i}", directory="autobattle/images/time")
            if ret > cur_max_value:
                cur_max_value = ret
                cur = i
        if cur_max_value < 0.9:
            return None
        return int(cur)


    def _showimg(self, img):
        cv.imshow('window', img)
        if cv.waitKey(25) & 0xFF == ord('q'):
            cv.destroyAllWindows()

    def _pos(self, x, y) -> Tuple[int, int]:
        return(int((x/BASE_WIDTH)*self._devicewidth), int((y/BASE_HEIGHT)*self._deviceheight))

    def _roi(self, left, top, right, bottom) -> Tuple[int, int, int, int]:
        return (*self._pos(left, top), *self._pos(right, bottom))
