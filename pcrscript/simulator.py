from typing import List
from .driver import ADBDriver, Driver, DNADBDriver
import os


class GeneralSimulator():
    '''
    通用模拟器
    '''

    def __init__(self): 
        super().__init__()

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
            return [ADBDriver(device) for device in devices]


class DNSimulator(GeneralSimulator):
    '''
    雷电模拟器使用win32api
    '''

    def __init__(self, path, fastclick=False, useADB=True):
        super().__init__()
        self.path = path
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
