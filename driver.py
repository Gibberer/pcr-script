from abc import ABCMeta, abstractmethod
from simulator import DNSimulator
import os

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
    def getScreenSize(self)->(int,int):
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
        self._shell("screencap -p /sdcard/opsd.png")
        output = "{}-{}".format(self.device_name,output)
        self._cmd("pull /sdcard/opsd.png {}".format(output))
        return output

    def getScreenSize(self)->(int,int):
        return map(lambda x:int(x),self._shell("wm size", True).split(":")[-1].split("x"))

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
    def __init__(self, device_name, dnsimulator:DNSimulator, index):
        super().__init__(device_name)
        self.index = index
        self.dnsimulator = dnsimulator
    
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
            self.dnsimulator.dninput(text)
        else:
            super().input(text)
    
    def screenshot(self, output='screen_shot.png'):
        #TODO use win32api
        return super().screenshot(output=output)

