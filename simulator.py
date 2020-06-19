from driver import ADBDriver, Driver
import os
class Simulator():
    
    def __init__(self):
        super().__init__()
        self.connect()

    def connect(self):
        # mumu 模拟器这么连接
        # os.system("adb connect 127.0.0.1:7555")
        pass

    def get_dirvers(self)->Driver:
        lines = os.popen("adb devices").readlines()
        if not lines or len(lines) < 2:
            print("没有设备信息：{}".format(lines[0] if lines else "None"))
            return None
        devices = []
        for line in lines[1:]:
            if '\t' in line:
                name, status = line.split('\t')
                if 'device' in status:
                    devices.append(ADBDriver(name))
        return devices