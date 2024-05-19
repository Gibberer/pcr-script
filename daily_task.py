import yaml
import os
import time
from pcrscript import DNSimulator, Robot, GeneralSimulator
from pcrscript.tasks import EventNews, TimeLimitTask, find_taskclass
from pcrscript.news import fetch_event_news
from typing import Type

def open_leidian_emulator(dnpath):
    # 开启雷电模拟器
    # 检查当前运行的程序有没有雷电模拟器
    simulator = DNSimulator(dnpath, useADB=False)
    simulator.start()
    retry_count = 0
    while retry_count < 10:
        if simulator.online():
            print("the emulator is ready.")
            break
        else:
            print("no emulator detected, wait for 20 seconds")
            time.sleep(20)
            retry_count += 1
    if retry_count >= 10:
        print("exit cannot found device")
        return -1
    else:
        print("try start princess connect application")
        exit_code = simulator.open_app("com.bilibili.priconne")
        time.sleep(30)
        return exit_code

def modify_task_list(news: EventNews, task_list: list):
    for i in range(len(task_list) - 1, -1, -1):
        task_class = find_taskclass(task_list[i][0])
        if not issubclass(task_class, TimeLimitTask):
            continue
        valid_class,args = None,None
        task_class:Type[TimeLimitTask] = task_class
        ret = task_class.valid(news, task_list[i][1:])
        if ret:
            valid_class = ret[0]
            if len(ret) > 1:
                args = ret[1]
        if not valid_class:
            task_list.pop(i)
        else:
            task_list.pop(i)
            if args:
                task_list.insert(i, [valid_class.name, *args])
            else:
                task_list.insert(i, [valid_class.name])


def run_script(config, use_adb):
    drivers = DNSimulator(config["Extra"]["dnpath"], useADB=use_adb).get_dirvers()
    if not drivers:
        print("Device not found.")
        return
    # 使用第一个设备
    robot = Robot(drivers[0])
    news = fetch_event_news()
    print("当前进行的活动:")
    for value in news.__dict__.values():
        if value:
            print(value)
    task_list: list = next(iter(config["Task"].values()))  # 这里设置一个全量的任务列表
    # 根据当前进行的活动修改原始任务
    modify_task_list(news, task_list)
    # 对于日常脚本不需要切换账号（提供账号），只是返回游戏欢迎页面
    robot.changeaccount()
    robot.work(task_list)

if __name__ == "__main__":
    with open("daily_config.yml", encoding="utf-8") as f:
        config = yaml.load(f, Loader=yaml.FullLoader)
    dnpath = config["Extra"]["dnpath"]
    if dnpath:
        return_code = open_leidian_emulator(dnpath)
        if return_code < 0:
            print("open leidian emulator failed")
        else:
            print("leidian emulator install path is configured, use leidian console.")
            run_script(config, False)
    else:
        print("leidian emulator install path not found, use ADB command.")
        os.system(
                f'adb -s {GeneralSimulator().get_devices()[0]} shell monkey -p com.bilibili.priconne 1'
            )
        time.sleep(30)
        run_script(config, True)
        
