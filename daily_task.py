import yaml
import os
import subprocess
import time
from pcrscript import DNSimulator2

def is_emulator_online(dnpath):
    if not dnpath:
        return False
    command_result = os.popen(f'{dnpath}\ldconsole.exe list2').read()
    if command_result:
        infos = list(map(lambda x : x.split(','), command_result.split('\n')))
        if infos and int(infos[0][2]) > 0 and int(infos[0][4]) == 1:
            return True
    return False

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
    retry_count = 0
    while retry_count < 10:
        if is_emulator_online(dnpath):
            print("检测到模拟器，准备开始")
            break
        else:
            print("未检测到设备，等待20秒再次检测")
            time.sleep(20)
            retry_count += 1
    if retry_count >= 10:
        print("exit can't found device")
        exit(-1)
    else:
        print("try start princess connect application")
        if dnpath:
            os.system(f'{dnpath}\ldconsole.exe runapp --index 0 --packagename com.bilibili.priconne')
            exit_code = 0
        else:
            os.system(f'adb -s {DNSimulator2("").get_devices()[0]} shell monkey -p com.bilibili.priconne 1')
            exit_code = 1
        time.sleep(30)
        exit(exit_code)


    
    
    
