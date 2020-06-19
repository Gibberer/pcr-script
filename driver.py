from abc import ABCMeta, abstractmethod
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

