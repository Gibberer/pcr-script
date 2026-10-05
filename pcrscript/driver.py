from abc import ABCMeta, abstractmethod
from contextlib import contextmanager
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
import re

class WHType(enum.Enum):
    Image = 1
    Mouse = 2

class Driver(metaclass=ABCMeta):
    supports_unicode_input = True

    @abstractmethod
    def click(self, x, y):
        pass

    @abstractmethod
    def input(self, text):
        pass

    @abstractmethod
    def screenshot(self, output="screen_shot.png") -> np.ndarray:
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
    supports_unicode_input = False

    def __init__(self, device_name, adb_path="adb", *, unicode_console_path="", unicode_console_index=0):
        super().__init__()
        self.device_name = device_name
        self.adb_path = adb_path
        self.unicode_console_path = unicode_console_path
        self.unicode_console_index = unicode_console_index
        self.supports_unicode_input = bool(unicode_console_path)
        self.device_width = 0
        self.device_height = 0

    def click(self, x, y):
        self._run("shell", "input", "tap", str(x), str(y))

    def input(self, text):
        if self.unicode_console_path and not text.isascii():
            subprocess.run([self.unicode_console_path, "action", "--index",
                            str(self.unicode_console_index), "--key", "call.input",
                            "--value", text], check=True, timeout=15,
                           stdin=subprocess.DEVNULL, capture_output=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return
        self._run("shell", "input", "text", text)

    def screenshot(self, output="screen_shot.png"):
        self._assert_adb_allowed()
        result = self._run("exec-out", "screencap", "-p")
        image = cv.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"ADB 设备 {self.device_name} 截图无效")
        self.device_height, self.device_width = image.shape[:2]
        return image

    def get_screen_size(self) -> Tuple[int, int]:
        if self.device_width and self.device_height:
            return self.device_width, self.device_height
        try:
            response = self._run("shell", "wm", "size").stdout.decode("utf-8", errors="replace")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            response = ""
        matches = re.findall(r"(\d+)x(\d+)", response)
        if not matches:
            image = self.screenshot()
            return image.shape[1], image.shape[0]
        self.device_width, self.device_height = map(int, matches[-1])
        return self.device_width, self.device_height
    

    def swipe(self, start, end=None, duration=500):
        if not end:
            end = start
        self._run("shell", "input", "swipe", *map(str, (*start, *end, duration)))

    def _run(self, *args):
        return subprocess.run([self.adb_path, "-s", self.device_name, *args], capture_output=True, check=True, timeout=30)

    def _shell(self, cmd, ret=False):
        return self._cmd("shell {}".format(cmd))

    def _cmd(self, cmd, ret=False):
        cmd = '"{}" -s {} {}'.format(self.adb_path, self.device_name, cmd)
        if ret:
            os.system(cmd)
        else:
            return os.popen(cmd).read()

    def _assert_adb_allowed(self):
        pass

@contextmanager
def _physical_input_context():
    """Keep native capture, geometry and messages in physical pixels."""
    set_context = getattr(ctypes.windll.user32, 'SetThreadDpiAwarenessContext', None)
    previous = None
    if set_context is not None:
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = ctypes.c_void_p
        previous = set_context(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    try:
        yield
    finally:
        if previous:
            set_context(previous)


class Win32Driver(ADBDriver):
    '''
    使用Win32API操作设备
    '''

    @_physical_input_context()
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
            win32api.SendMessage(hwin, win32con.WM_MOUSEMOVE, 0, positon)
            time.sleep(.05)
            win32api.SendMessage(hwin, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, positon)
            time.sleep(.1)
            win32api.SendMessage(hwin, win32con.WM_LBUTTONUP, 0,positon)
        except Exception as e:
            self.reset_hwnd()
            print(f"fallback adb click:{e}")
            super().click(x,y)
    
    @_physical_input_context()
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
            win32api.SendMessage(hwin, win32con.WM_MOUSEMOVE, 0, start_position)
            time.sleep(.05)
            win32api.SendMessage(hwin, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, start_position)
            # linear tween
            total_duration = duration
            while duration > 100:
                duration -= 100
                time.sleep(0.1)
                rate = duration/total_duration
                mx = int(rate*start_x + (1-rate)*end_x)
                my = int(rate*start_y + (1-rate)*end_y)
                win32api.SendMessage(hwin, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, win32api.MAKELONG(mx,my))
            if duration > 0:
                time.sleep(0.1)
            win32api.SendMessage(hwin, win32con.WM_MOUSEMOVE, win32con.MK_LBUTTON, end_position)
            win32api.SendMessage(hwin, win32con.WM_LBUTTONUP, 0, end_position)
        except Exception as e:
            self.reset_hwnd()
            print(f"fallback adb swipe:{e}")
            super().swipe(start,end, duration)
    
    @_physical_input_context()
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
    supports_scrollbar_fallback = True

    def screenshot(self, output="screen_shot.png"):
        if getattr(self, '_use_background_capture', False):
            return self._scroll_fallback_driver().screenshot(output=output)
        frame = super().screenshot(output=output)
        after_input = getattr(self, '_native_input_pending', False)
        check = (not getattr(self, '_capture_consistency_checked', False)
                 or after_input or float(np.mean(frame)) < 5)
        self._capture_consistency_checked = True
        self._native_input_pending = False
        # GDI can retain a complete old page as well as a black loading frame.
        # Compare the first capture and input receipts with Android
        # on this exact instance. Once stale, never return to its old surface
        # during this driver session; input remains on the configured driver.
        if check:
            try:
                current = self._scroll_fallback_driver().screenshot(output=output)
                if isinstance(current, np.ndarray) and current.shape == frame.shape:
                    difference = np.abs(frame.astype(np.int16)-current.astype(np.int16))
                    # Cached pages can differ only in a balance or button cost.
                    # Prefer the verified current surface even for a small
                    # changed field; inputs are never replayed by this check.
                    stale = np.count_nonzero(difference.max(axis=2) > 16) > 50
                    if float(np.mean(frame)) < 5 or stale:
                        self._use_background_capture = True
                        return current
            except (RuntimeError, OSError, subprocess.SubprocessError):
                # A legitimate loading screen must still work without ADB.
                # Keep it and wait; never guess an ambiguous connection.
                pass
        return frame

    def __init__(self, device_name, dnpath, index, click_by_mouse=False):
        super().__init__(device_name)
        # Both LeiDian input paths accept Chinese through ldconsole, even
        # though the ADB base driver cannot type it on its own.
        self.supports_unicode_input = True
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

    def _cmd(self, cmd, ret=False):
        # 雷电模拟器窗口模式不得在截图/点击失败后偷偷切换到 ADB。
        self._assert_adb_allowed()
        return super()._cmd(cmd, ret)

    def _assert_adb_allowed(self):
        if self.click_by_mouse:
            raise RuntimeError("雷电模拟器窗口操作失败（已禁用 ADB 回退），请检查模拟器窗口是否存在")
    

    def _init_window_info(self):
        if os.path.exists(f'{self.dnpath}/ldconsole.exe'):
            from .leidian_console import query_list2
            output = query_list2(self.dnpath)
            if output:
                infos = list(map(lambda x : x.split(','), output.split('\n')))
                info = next((row for row in infos if len(row) >= 9 and row[0] == str(self.index)), None)
                if info:
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

    def swipe(self, start, end=None, duration=500, *, fallback=False):
        self._native_input_pending = True
        if fallback:
            self._scroll_fallback_driver().swipe(start, end, duration)
            return
        if self.click_by_mouse:
            super().swipe(start, end, duration)
        else:
            super(Win32Driver, self).swipe(start, end, duration)

    def _scroll_fallback_driver(self):
        """Bind an observed failed drag to a verified background connection."""
        if getattr(self, '_scroll_adb', None) is not None:
            return self._scroll_adb
        serial = getattr(self, 'adb_fallback_serial', '')
        if not serial:
            try:
                console = os.path.join(self.dnpath, 'ldconsole.exe')
                value = subprocess.check_output([console, 'adb', '--index', str(self.index),
                    '--command', 'get-serialno'], encoding='utf-8', errors='replace', timeout=15).strip()
                # A console query binds the serial to this exact instance.
                # Never infer it from a single phone or matching resolution.
                if not re.fullmatch(r'emulator-\d+|127\.0\.0\.1:\d+', value):
                    raise ValueError('instance serial unknown')
                serial = value
            except (AttributeError, ValueError, OSError, subprocess.SubprocessError) as error:
                raise RuntimeError('后台 ADB 回退未明确关联雷电实例；请指定 Extra.adb_serial') from error
        from .simulator import GeneralSimulator
        devices = GeneralSimulator(self.adb_path).get_devices()
        if serial not in devices:
            raise RuntimeError('指定的后台 ADB 回退设备未连接')
        driver = ADBDriver(serial, self.adb_path)
        if driver.get_screen_size() != self.get_screen_size():
            raise RuntimeError('后台 ADB 回退与雷电窗口尺寸不符')
        self._scroll_adb = driver
        return driver
    
    def click(self, x, y):
        self._native_input_pending = True
        if self.click_by_mouse:
            super().click(x, y)
        else:
            super(Win32Driver, self).click(x, y)

    def input(self, text):
        '''
        adb 不支持中文使用dnconsole接口
        '''
        self._native_input_pending = True
        if self.click_by_mouse:
            subprocess.run([os.path.join(self.dnpath, 'ldconsole.exe'), 'action',
                            '--index', str(self.index), '--key', 'call.input', '--value', text],
                           check=True, timeout=15, stdin=subprocess.DEVNULL,
                           capture_output=True,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
