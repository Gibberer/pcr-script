from abc import ABCMeta, abstractmethod
from win32 import win32gui, win32api, win32console
from win32.lib import win32con
from pythonwin import win32ui
import numpy as np
import matplotlib.pyplot as plt
from cv2 import cv2 as cv
import os
import config
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
    def getScreenSize(self) -> (int, int):
        pass


class ADBDriver(Driver):
    def __init__(self, device_name):
        super().__init__()
        self.device_name = device_name

    def click(self, x, y):
        self._shell("input tap {} {}".format(x, y))
        # print("click {} {}".format(x,y))

    def input(self, text):
        self._shell("input text {}".format(text))

    def screenshot(self, output="screen_shot.png"):
        # 每次要花1-2秒
        self._shell("screencap -p /sdcard/opsd.png")
        output = "{}-{}".format(self.device_name, output)
        self._cmd("pull /sdcard/opsd.png {}".format(output))
        return output

    def getScreenSize(self) -> (int, int):
        return map(lambda x: int(x), self._shell("wm size", True).split(":")[-1].split("x"))

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

    def __init__(self, device_name, dnpath, index):
        super().__init__(device_name)
        self.dnpath = dnpath
        self.index = index

    def input(self, text):
        '''
        adb 不支持中文使用dnconsole接口
        '''
        contain_hanzi = False
        for char in text:
            if '\u4e00' <= char <= '\u9fa5':
                contain_hanzi = True
                break
        if contain_hanzi:
            os.system(
                '{}\dnconsole.exe action --index {} --key call.input --value "{}"'.format(self.dnpath, self.index, text))
        else:
            super().input(text)

    def screenshot(self, output='screen_shot.png'):
        window_title = '雷电模拟器'
        if self.index > 0:
            window_title = "{}-{}".format(window_title, self.index)
        width,height = config.BASE_WIDTH,config.BASE_HEIGHT
        toolbar_height = 35
        try:
            hwin = win32gui.FindWindow('LDPlayerMainFrame',window_title)
            hwindc = win32gui.GetWindowDC(hwin)
            srcdc = win32ui.CreateDCFromHandle(hwindc)
            memdc = srcdc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(srcdc, width, height)
            memdc.SelectObject(bmp)
            memdc.BitBlt((0, 0), (width, height), srcdc, (0, toolbar_height), win32con.SRCCOPY)
            signedIntsArray = bmp.GetBitmapBits(True)
            img = np.frombuffer(signedIntsArray, dtype='uint8')
            img.shape = (height, width, 4)
            srcdc.DeleteDC()
            memdc.DeleteDC()
            win32gui.ReleaseDC(hwin, hwindc)
            win32gui.DeleteObject(bmp.GetHandle())
            return img[:,:,:3]
        except:
            return super().screenshot(output=output)


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
