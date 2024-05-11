import yaml
import os
import time
from pcrscript import DNSimulator, Robot, GeneralSimulator
from pcrscript.tasks import EventNews, Event, TimeLimitTask, find_taskclass
import requests
import brotli
import sqlite3
from datetime import datetime

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


def _upgrade_db_file(config, db_dir, db_file):
    response = requests.get("https://redive.estertion.win/last_version_cn.json")
    remote_version = int(response.json()["TruthVersion"])
    if "version" in config:
        if remote_version > config["version"]:
            should_download = True
            config["version"] = remote_version
        else:
            should_download = False
    else:
        should_download = True
        config["version"] = remote_version
    if should_download:
        compressed_file = os.path.join(db_dir, "redive_cn.db.br")
        response = requests.get(
            "https://redive.estertion.win/db/redive_cn.db.br", stream=True
        )
        with response as r:
            r.raise_for_status()
            with open(compressed_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        with open(compressed_file, "rb") as f:
            db = brotli.decompress(f.read())
            with open(os.path.join(db_dir, db_file), "wb") as dbfile:
                dbfile.write(db)
        os.remove(compressed_file)


_time_format = "%Y/%m/%d %H:%M:%S"


def _query_free_gacha_event(conn: sqlite3.Connection):
    cursor = conn.cursor()
    current_time = datetime.now().isoformat(' ', 'seconds')
    cursor.execute(
        f'SELECT start_time,end_time FROM campaign_freegacha WHERE ISO(end_time) > "{current_time}" and freegacha_10 = 1 and ISO(start_time) <= "{current_time}"'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, "免费扭蛋十连")


def _query_hatsune_event(conn: sqlite3.Connection):
    cursor = conn.cursor()
    # 剧情活动的月份部分从2023年开始是不补零的, 直接使用字符串匹配不符合预期转换为标准时间比较
    current_iso_time = datetime.now().isoformat(' ', 'seconds')
    cursor.execute(
        f'SELECT start_time,end_time,original_event_id FROM hatsune_schedule WHERE ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}"'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time, original_event_id = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        if original_event_id > 0:
            name = "剧情活动（复刻）"
        else:
            name = "剧情活动"
        return Event(start_time, end_time, name, {"original_event_id":original_event_id})


def _query_tower_event(conn: sqlite3.Connection):
    cursor = conn.cursor()
    current_time = datetime.now().isoformat(' ', 'seconds')
    cursor.execute(
        f'SELECT start_time,end_time FROM tower_schedule WHERE ISO(end_time) > "{current_time}" and ISO(start_time) <= "{current_time}"'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, "露娜塔")

def _query_drop_normal_event(conn: sqlite3.Connection):
    cursor = conn.cursor()
    current_iso_time = datetime.now().isoformat(' ', 'seconds')
    cursor.execute(
        f'SELECT start_time,end_time,value  FROM campaign_schedule WHERE ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}" and campaign_category=31'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time, value = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, f"普通关卡{int(value/1000)}倍掉落", {"value":value})

def _query_drop_hard_event(conn: sqlite3.Connection):
    cursor = conn.cursor()
    current_iso_time = datetime.now().isoformat(' ', 'seconds')
    cursor.execute(
        f'SELECT start_time,end_time,value  FROM campaign_schedule WHERE ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}" and campaign_category=32'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time, value = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, f"困难关卡{int(value/1000)}倍掉落", {"value":value})

def _iso_datetime(date):
    return str(datetime.strptime(date, _time_format))

def fetch_event_news() -> EventNews:
    # 从redive.estertion.win抓国服信息
    cache_path = "cache"
    db_file = "redive_cn.db"
    if not os.path.exists(cache_path):
        os.makedirs(cache_path)
    config_path = os.path.join(cache_path, "db_config.yml")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            config = yaml.load(f, Loader=yaml.FullLoader)
    else:
        config = {}
    try:
        print("make sure the db version is up to date.")
        _upgrade_db_file(config, cache_path, db_file)
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)
    except Exception:
        print("fetch event news failed")
    try:
        with sqlite3.connect(os.path.join(cache_path, db_file)) as conn:
            conn.create_function('ISO', 1, _iso_datetime)
            free_gacha = _query_free_gacha_event(conn)
            hatsune = _query_hatsune_event(conn)
            tower = _query_tower_event(conn)
            drop_normal = _query_drop_normal_event(conn)
            drop_hard = _query_drop_hard_event(conn)
        return EventNews(freeGacha=free_gacha, hatsune=hatsune, tower=tower, dropItemNormal=drop_normal, dropItemHard=drop_hard)
    except Exception as e:
        print(f"parse db file failed, filter all event special task. Case: {e}")
        return EventNews()

def modify_task_list(news: EventNews, task_list: list):
    for i in range(len(task_list) - 1, -1, -1):
        task_class = find_taskclass(task_list[i][0])
        if not issubclass(task_class, TimeLimitTask):
            continue
        valid_class,args = None,None
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
        
