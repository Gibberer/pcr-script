from typing import List
from .driver import ADBDriver, Driver, DNADBDriver
import os
import types


class DNSimulator():
    '''
    雷电模拟器
    '''

    def __init__(self, path):  #example： N:\dnplayer2
        super().__init__()
        self.path = path

    def dninput(self, msg, index=0):
        os.system(
            '{}\ldconsole.exe action --index {} --key call.input --value "{}"'.format(self.path, index, msg))

    def get_devices(self) -> List[str]:
        lines = os.popen("adb devices").readlines()
        if not lines or len(lines) < 2:
            print("没有设备信息：{}".format(lines[0] if lines else "None"))
            return None
        devices = []
        for line in lines:
            if '\t' in line:
                name, status = line.split('\t')
                if 'device' in status:
                    devices.append(name)
        return devices

    def get_dirvers(self) -> List[Driver]:
        devices = self.get_devices()
        if devices:
            drivers = []
            for deivce in devices:
                driver = ADBDriver(deivce)
                input_func = driver.input
                input_code = compile('''def input(it, msg):
                        zhongwen = False
                        for char in msg:
                            if '\u4e00' <= char <= '\u9fa5':
                                zhongwen = True
                                break
                        if zhongwen:
                            self.dninput(msg,index)
                        else:
                            input_func(msg)
                ''', "<string>", "exec")
                input = types.FunctionType(input_code.co_consts[0], {
                                           'self': self, 'input_func': input_func, 'index': len(devices)}, 'input')
                driver.input = types.MethodType(input, driver)
                drivers.append(driver)
            return drivers


class DNSimulator2(DNSimulator):
    '''
    雷电模拟器使用win32api
    '''

    def __init__(self, path, fastclick=False, useADB=True):
        super().__init__(path)
        self.fastclick = fastclick
        self.useADB = useADB
        if not useADB:
            self.fastclick = True

    def get_devices(self) -> List[str]:
        if self.useADB:
            return super().get_devices()
        else:
            try:
                output = os.popen(f"{self.path}\ldconsole.exe list2").read()
                if output:
                    infos = list(map(lambda x : x.split(','), output.split('\n')))
                    return [info[0] for info in infos if len(info) > 1 and int(info[2]) > 0]
            except Exception as e:
                print(e)
                return super().get_devices()

    def get_dirvers(self) -> List[Driver]:
        devices = self.get_devices()
        if devices:
            return [DNADBDriver(device, self.path, i, click_by_mouse=self.fastclick) for i, device in enumerate(devices)]
