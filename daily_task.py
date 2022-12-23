import yaml
import os
import subprocess
import time
from pcrscript import DNSimulator2

def restart_adb_server():
    subprocess.run("adb kill-server")
    subprocess.run("adb start-server")

if __name__ == '__main__':
    with open('daily_config.yml', encoding='utf-8') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    dnpath = config['Extra']['dnpath']
    # 开启雷电模拟器
    # 检查当前运行的程序有没有雷电模拟器
    running_process = os.popen('wmic process get description').read()
    running_process = list(map(lambda name:name.rstrip(),running_process.split('\n\n')))
    if 'dnplayer.exe' not in running_process:
        subprocess.Popen(f'{dnpath}\dnplayer.exe', shell=True)
        time.sleep(5)
    simulator = DNSimulator2(dnpath)
    retry_count = 0
    while retry_count < 10:
        devices = simulator.get_devices()
        if not devices:
            print("未检测到设备，等待20秒再次检测")
            time.sleep(20)
            restart_adb_server()
            retry_count += 1
        else:
            print(f"target device: {devices[0]}")
            break
    if retry_count == 10:
        print("exit can't found device")
        exit(1)
    else:
        print("try start princess connect application")
        os.system(f'adb -s {simulator.get_devices()[0]} shell monkey -p com.bilibili.priconne 1')
        time.sleep(30)
        exit(0)


    
    
    
