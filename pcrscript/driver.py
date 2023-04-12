from abc import ABCMeta, abstractmethod
from typing import Tuple
from win32 import win32gui, win32api, win32console
import ctypes
from win32.lib import win32con
from pythonwin import win32ui
import pywintypes
import numpy as np
import matplotlib.pyplot as plt
import cv2 as cv
import os
from . import constants
import time


class Driver(metaclass=ABCMeta):
    @abstractmethod
    def click(self, x, y):
        pass

    @abstractmethod
    def input(self, text):
        pass

    @abstractmethod
    def screenshot(self, output="screen_shot.png"):
        pass

    @abstractmethod
    def getScreenSize(self) -> Tuple[int, int]:
        pass

    @abstractmethod
    def swipe(self, start: Tuple[int, int], end: Tuple[int, int], duration: int):
        pass
    
    def getRootWindowLocation(self) -> Tuple[int, int]:
        # 获取根窗口的位置坐标
        return (0,0)
    
    def getScale(self):
        return 1


class ADBDriver(Driver):
    def __init__(self, device_name):
        super().__init__()
        self.device_name = device_name

    def click(self, x, y):
        self._shell("input tap {} {}".format(x, y))

    def input(self, text):
        self._shell("input text {}".format(text))

    def screenshot(self, output="screen_shot.png"):
        # 每次要花1-2秒
        self._shell("screencap -p /sdcard/opsd.png")
        output = "{}-{}".format(self.device_name, output)
        self._cmd("pull /sdcard/opsd.png {}".format(output))
        return output

    def getScreenSize(self) -> Tuple[int, int]:
        return map(lambda x: int(x), self._shell("wm size", True).split(":")[-1].split("x"))
    

    def swipe(self, start, end=None, duration=500):
        if not end:
            end = start
        self._shell("input swipe {} {} {} {} {}".format(
            *start, *end, duration))

    def _shell(self, cmd, ret=False):
        return self._cmd("shell {}".format(cmd))

    def _cmd(self, cmd, ret=False):
        cmd = "adb -s {} {}".format(self.device_name, cmd)
        if ret:
            os.system(cmd)
        else:
            return os.popen(cmd).read()



class DNADBDriver(ADBDriver):
    '''
    基于ADB的雷电模拟器扩展驱动
    '''

    def __init__(self, device_name, dnpath, index, click_by_mouse=False):
        super().__init__(device_name)
        self.dnpath = dnpath
        self.index = index
        self.click_by_mouse = click_by_mouse
        self.binded_hwnd_id = None
        self.binded_hwnd = None
        self.window_title = None
        self.window_width = -1
        self.window_height = -1
        self.scale = 1
        self._init_window_info()
    

    def _init_window_info(self):
        if os.path.exists(f'{self.dnpath}/ldconsole.exe'):
            output = os.popen(f"{self.dnpath}/ldconsole.exe list2").read()
            if output:
                infos = list(map(lambda x : x.split(','), output.split('\n')))
                if len(infos) > self.index:
                    info = infos[self.index]
                    self.window_title = info[1]
                    self.binded_hwnd_id = int(info[3])
                    self.window_width = int(info[7])
                    self.window_height = int(info[8])
        # 获取缩放信息
        shcore = ctypes.windll.shcore
        monitor = win32api.MonitorFromPoint((0,0),1)
        scale = ctypes.c_int()
        shcore.GetScaleFactorForMonitor(
            monitor.handle,
            ctypes.byref(scale)
        )
        self.scale = float(scale.value / 100)
    
    def getScreenSize(self) -> Tuple[int, int]:
        if self.window_width > 0 and self.window_height > 0:
            return (self.window_width, self.window_height)
        return super().getScreenSize()

    def swipe(self, start, end=None, duration=500):
        if self.click_by_mouse:
            try:
                if not end:
                    end = start
                hwin = self._get_binded_hwnd()
                ret = win32gui.GetWindowRect(hwin)
                height = ret[3] - ret[1]
                width = ret[2] - ret[0]
                start_x = int(start[0] * width/constants.BASE_WIDTH)
                start_y = int(start[1] * height/constants.BASE_HEIGHT)
                end_x = int(end[0] * width/constants.BASE_WIDTH)
                end_y = int(end[1] * height/constants.BASE_HEIGHT)
                start_position = win32api.MAKELONG(start_x, start_y)
                end_position = win32api.MAKELONG(end_x, end_y)
                win32api.SendMessage(hwin, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, start_position)
                # linear tween
                total_duration = duration
                while duration > 100:
                    duration -= 100
                    time.sleep(0.1)
                    rate = duration/total_duration
                    mx = int(rate*start_x + (1-rate)*end_x)
                    my = int(rate*start_y + (1-rate)*end_y)
                    win32api.SendMessage(hwin, win32con.WM_MOUSEMOVE, 0, win32api.MAKELONG(mx,my))
                if duration > 0:
                    time.sleep(0.1)
                win32api.SendMessage(hwin, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON, end_position)
            except Exception as e:
                self._clear_cached_hwnd()
                print(f"fallback adb swipe:{e}")
                super().swipe(start,end, duration)
        else:
            super().swipe(start,end, duration)
    
    def click(self, x, y):
        if self.click_by_mouse:
            try:
                hwin = self._get_binded_hwnd()
                ret = win32gui.GetWindowRect(hwin)
                height = ret[3] - ret[1]
                width = ret[2] - ret[0]
                tx = int(x * width/constants.BASE_WIDTH)
                ty = int(y * height/constants.BASE_HEIGHT)
                positon = win32api.MAKELONG(tx, ty)
                win32api.SendMessage(hwin, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, positon)
                win32api.SendMessage(hwin, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON,positon)
            except Exception as e:
                self._clear_cached_hwnd()
                print(f"fallback adb click:{e}")
                super().click(x,y)
        else:
            super().click(x, y)

    def input(self, text):
        '''
        adb 不支持中文使用dnconsole接口
        '''
        if self.click_by_mouse:
            try:
                os.system(
                    '{}\ldconsole.exe action --index {} --key call.input --value "{}"'.format(self.dnpath, self.index, text))
            except Exception as e:
                print(f"fallback adb input:{e}")
                super().input(text)
        else:
            contain_hanzi = False
            for char in text:
                if '\u4e00' <= char <= '\u9fa5':
                    contain_hanzi = True
                    break
            if contain_hanzi:
                os.system(
                    '{}\ldconsole.exe action --index {} --key call.input --value "{}"'.format(self.dnpath, self.index, text))
            else:
                super().input(text)

    def screenshot(self, output='screen_shot.png'):
        width, height = constants.BASE_WIDTH, constants.BASE_HEIGHT
        try:
            hwin = self._get_binded_hwnd()
            hwindc = win32gui.GetWindowDC(hwin)
            srcdc = win32ui.CreateDCFromHandle(hwindc)
            memdc = srcdc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(srcdc, width, height)
            memdc.SelectObject(bmp)
            memdc.BitBlt((0, 0), (width, height), srcdc,
                         (0, 0), win32con.SRCCOPY)
            signedIntsArray = bmp.GetBitmapBits(True)
            img = np.frombuffer(signedIntsArray, dtype='uint8')
            img.shape = (height, width, 4)
            srcdc.DeleteDC()
            memdc.DeleteDC()
            win32gui.ReleaseDC(hwin, hwindc)
            win32gui.DeleteObject(bmp.GetHandle())
            return img[:, :, :3]
        except Exception as e:
            self._clear_cached_hwnd()
            print(e)
            return super().screenshot(output=output)
    
    def getRootWindowLocation(self):
        window_title = self._getWindowTitle()
        try:
            hwin = win32gui.FindWindow('LDPlayerMainFrame', window_title)
            ret = win32gui.GetWindowRect(hwin)
            return (ret[0], ret[1] + self._getDnToolbarHeight())
        except:
            return super().getRootWindowLocation()
    
    def _getDnToolbarHeight(self):
        return 27
    
    def _get_binded_hwnd(self):
        if self.binded_hwnd:
            return self.binded_hwnd
        if self.binded_hwnd_id:
            self.binded_hwnd = pywintypes.HANDLE(self.binded_hwnd_id)
            return self.binded_hwnd
        try:
            window_title = self._getWindowTitle()
            hwin = win32gui.FindWindow('LDPlayerMainFrame', window_title)
            def winfun(hwnd, lparam):
                subtitle = win32gui.GetWindowText(hwnd)
                if subtitle == 'TheRender':
                    self.binded_hwnd = hwnd
            win32gui.EnumChildWindows(hwin, winfun, None)
            return self.binded_hwnd
        except Exception as e:
            print(e)
            return None

    def _clear_cached_hwnd(self):
        self.binded_hwnd = None
        self.binded_hwnd_id = None

    def _getWindowTitle(self):
        if self.window_title:
            return self.window_title
        window_title = "雷电模拟器"
        if self.index > 0:
            window_title = "{}-{}".format(window_title, self.index)
        return window_title
    
    def getScale(self):
        return self.scale

# if __name__ == "__main__":
#     # test win 32 grap screen
#     while True:
#         width= 960
#         height = 575
#         hwin = win32gui.FindWindow('LDPlayerMainFrame','雷电模拟器')
#         hwindc = win32gui.GetWindowDC(hwin)
#         srcdc = win32ui.CreateDCFromHandle(hwindc)
#         memdc = srcdc.CreateCompatibleDC()
#         bmp = win32ui.CreateBitmap()
#         bmp.CreateCompatibleBitmap(srcdc, width, height-35)
#         memdc.SelectObject(bmp)
#         memdc.BitBlt((0, 0), (width, height-35), srcdc, (0, 35), win32con.SRCCOPY)
#         signedIntsArray = bmp.GetBitmapBits(True)
#         img = np.frombuffer(signedIntsArray, dtype='uint8')
#         img.shape = (height-35, width, 4)
#         srcdc.DeleteDC()
#         memdc.DeleteDC()
#         win32gui.ReleaseDC(hwin, hwindc)
#         win32gui.DeleteObject(bmp.GetHandle())
#         cv.imshow('window', img)
#         if cv.waitKey(25) & 0xFF == ord('q'):
#             cv.destroyAllWindows()
#             break