from typing import List
import os
import re
import ast
from .driver import ADBDriver, Driver, DNDriver, MuMuDriver


class GeneralSimulator():
    '''
    通用模拟器
    '''

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
            return [DNDriver(device, self.path, i, click_by_mouse=self.fastclick) for i, device in enumerate(devices)]

class MuMuSimulator(GeneralSimulator):
    '''
    MuMu模拟器
    '''

    def __init__(self, path, port='16384', fastclick=False):
        super().__init__()
        self.path = path
        self.port = port
        self.fastclick = fastclick
    
    def _api(self, command):
        return os.popen(f'cmd /C ""{self.path}\shell\MuMuManager.exe" api {command}"').read()
    
    def _get_player_list(self):
        output = self._api('get_player_list')
        result = re.search(r'\[.*?\]', output)
        if result:
            return ast.literal_eval(result.group())
    
    def _check_player_started(self, index):
        output = self._api(f'-v {index} player_state')
        return output and 'start_finished' in output
    
    def _get_devices(self)->tuple[int, List[str]]:
        try:
            player_list:list = self._get_player_list()
            if player_list:
                for i in range(len(player_list)-1, -1, -1):
                    player = player_list[i]
                    if not self._check_player_started(player):
                        player_list.pop(i)
                return 1, player_list
            return 1, []
        except Exception as e:
            print(e)
            os.system(f"adb connect 127.0.0.1:{self.port}")
            return 0, super().get_devices()
    
    def get_devices(self) -> List[str]:
        return self._get_devices()

    def get_dirvers(self) -> List[Driver]:
        state, devices = self._get_devices()
        if state:
            return [MuMuDriver(f"MuMu-{device}", self.path, device, self.fastclick) for device in devices]
        else:
            return [ADBDriver(device) for device in devices]