from abc import ABCMeta, abstractmethod
from typing import Tuple
from win32 import win32gui, win32api
import ctypes
from win32.lib import win32con
from pythonwin import win32ui
import pywintypes
import numpy as np
import cv2 as cv
import subprocess
import os
import time
import enum

class WHType(enum.Enum):
    Image = 1
    Mouse = 2

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
    def get_screen_size(self) -> Tuple[int, int]:
        pass

    @abstractmethod
    def swipe(self, start: Tuple[int, int], end: Tuple[int, int], duration: int):
        pass
    
    def get_root_window_location(self) -> Tuple[int, int]:
        # 获取根窗口的位置坐标
        return (0,0)
    
    def get_scale(self):
        return 1


class ADBDriver(Driver):
    png = True

    def __init__(self, device_name):
        super().__init__()
        self.device_name = device_name
        self.device_width = 0
        self.device_height = 0

    def click(self, x, y):
        self._shell("input tap {} {}".format(x, y))

    def input(self, text):
        self._shell("input text {}".format(text))

    def screenshot(self, output="screen_shot.png"):
        if ADBDriver.png:
            self._shell("screencap -p /sdcard/opsd.png")
            output = "{}-{}".format(self.device_name, output)
            self._cmd("pull /sdcard/opsd.png {}".format(output))
            return cv.imread(output)
        else:
            # 该方式没有生成解析png和额外文件的读写过程，相对于-p方式会更快些。
            p = subprocess.Popen(f"adb -s {self.device_name} exec-out screencap", shell = True, stdout = subprocess.PIPE)
            #去掉前16个字符是由于多出来的部分，大概是记录元数据的例如头部是：FF FE
            image_buffer = p.stdout.read()[16:]
            image = np.frombuffer(image_buffer, np.uint8)
            width, height = self.get_screen_size()
            image.shape = (height, width, 4)
            return image[:,:,[2,1,0]]

    def get_screen_size(self) -> Tuple[int, int]:
        if self.device_width and self.device_height:
            return self.device_width, self.device_height
        self.device_width, self.device_height = map(lambda x: int(x), self._shell("wm size", True).split(":")[-1].split("x"))
        return self.device_width, self.device_height
    

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

class Win32Driver(ADBDriver):
    '''
    使用Win32API操作设备
    '''

    def click(self, x, y):
        try:
            hwin = self.get_hwnd(type=WHType.Mouse)
            ret = win32gui.GetWindowRect(hwin)
            bw,bh = self.get_screen_size()
            height = ret[3] - ret[1]
            width = ret[2] - ret[0]
            tx = int(x * width/bw)
            ty = int(y * height/bh)
            positon = win32api.MAKELONG(tx, ty)
            win32api.SendMessage(hwin, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, positon)
            win32api.SendMessage(hwin, win32con.WM_LBUTTONUP, win32con.MK_LBUTTON,positon)
        except Exception as e:
            self.reset_hwnd()
            print(f"fallback adb click:{e}")
            super().click(x,y)
    
    def swipe(self, start, end=None, duration=500):
        try:
            if not end:
                end = start
            hwin = self.get_hwnd(type=WHType.Mouse)
            ret = win32gui.GetWindowRect(hwin)
            bw,bh = self.get_screen_size()
            height = ret[3] - ret[1]
            width = ret[2] - ret[0]
            start_x = int(start[0] * width/bw)
            start_y = int(start[1] * height/bh)
            end_x = int(end[0] * width/bw)
            end_y = int(end[1] * height/bh)
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
            self.reset_hwnd()
            print(f"fallback adb swipe:{e}")
            super().swipe(start,end, duration)
    
    def screenshot(self, output="screen_shot.png"):
        try:
            hwin = self.get_hwnd(type=WHType.Image)
            width,height = self.get_screen_size()
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
            self.reset_hwnd()
            print(e)
            return super().screenshot(output=output)

    @abstractmethod
    def get_hwnd(self, type:WHType=WHType.Image):
        '''
        获取模拟器设备窗口句柄
        '''
        pass
    
    @abstractmethod
    def reset_hwnd(self):
        '''
        重置模拟器设备窗口句柄
        '''
        pass


class DNDriver(Win32Driver):
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
    
    def get_screen_size(self) -> Tuple[int, int]:
        if self.window_width > 0 and self.window_height > 0:
            return (self.window_width, self.window_height)
        return super().get_screen_size()

    def swipe(self, start, end=None, duration=500):
        if self.click_by_mouse:
            super().swipe(start, end, duration)
        else:
            super(Win32Driver, self).swipe(start, end, duration)
    
    def click(self, x, y):
        if self.click_by_mouse:
            super().click(x, y)
        else:
            super(Win32Driver, self).click(x, y)

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
        
    
    def get_root_window_location(self):
        window_title = self._get_window_title()
        try:
            hwin = win32gui.FindWindow('LDPlayerMainFrame', window_title)
            ret = win32gui.GetWindowRect(hwin)
            return (ret[0], ret[1] + self._get_dn_tool_bar_height())
        except:
            return super().get_root_window_location()
    
    def _get_dn_tool_bar_height(self):
        return 27
    
    def get_hwnd(self, type:WHType=WHType.Image):
        if self.binded_hwnd:
            return self.binded_hwnd
        if self.binded_hwnd_id:
            self.binded_hwnd = pywintypes.HANDLE(self.binded_hwnd_id)
            return self.binded_hwnd
        try:
            window_title = self._get_window_title()
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
    
    def reset_hwnd(self):
        self.binded_hwnd = None
        self.binded_hwnd_id = None

    def _get_window_title(self):
        if self.window_title:
            return self.window_title
        window_title = "雷电模拟器"
        if self.index > 0:
            window_title = "{}-{}".format(window_title, self.index)
        return window_title
    
    def get_scale(self):
        return self.scale

class MuMuDriver(Win32Driver):
    
    def __init__(self, device_name, path, index, click_by_mouse=False):
        super().__init__(device_name)
        self.path = path
        self.index = index
        self.binded_hwnd = None
        self.binded_operation_hwnd = None
        self.click_by_mouse = click_by_mouse
    
    def click(self, x, y):
        if self.click_by_mouse:
            super().click(x, y)
        else:
            self._shell("input tap {} {}".format(x, y))
    
    def swipe(self, start, end=None, duration=500):
        if self.click_by_mouse:
            super().swipe(start, end, duration)
        else:
            if not end:
                end = start
            self._shell("input swipe {} {} {} {} {}".format(
                *start, *end, duration))
    
    def get_hwnd(self, type:WHType=WHType.Image):
        if type == WHType.Image and self.binded_hwnd:
            return self.binded_hwnd
        elif type == WHType.Mouse and self.binded_operation_hwnd:
            return self.binded_operation_hwnd
        try:
            if self.index == 0:
                window_title = "MuMu模拟器12"
            else:
                window_title = f"MuMu模拟器12-{self.index}"
            hwin = win32gui.FindWindow('Qt5156QWindowIcon', window_title)
            self.binded_operation_hwnd = win32gui.FindWindowEx(hwin, None, 'Qt5156QWindowIcon', 'MuMuPlayer')
            self.binded_hwnd = win32gui.FindWindowEx(self.binded_operation_hwnd, None, 'nemuwin', 'nemudisplay')
            if type == WHType.Image:
                return self.binded_hwnd
            elif type == WHType.Mouse:
                return self.binded_operation_hwnd
        except Exception as e:
            print(e)
            return None
    
    def reset_hwnd(self):
        self.binded_hwnd = None
        self.binded_operation_hwnd = None
    
    def get_screen_size(self) -> Tuple[int]:
        if self.device_width and self.device_height:
            return self.device_width, self.device_height
        self.device_height, self.device_width = map(lambda x: int(x), self._shell("wm size", True).split(":")[-1].split("x"))
        return self.device_width, self.device_height
    
    def _shell(self, cmd, ret=False):
        return os.popen(f'cmd /C ""{self.path}/shell/MuMuManager.exe" adb -v {self.index} shell {cmd}"').read()
    