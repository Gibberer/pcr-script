import yaml
import os
import subprocess
import time
from typing import Optional
from dataclasses import dataclass, field
from pcrscript import DNSimulator2, Robot, ocr
import requests
import brotli
import sqlite3
from datetime import datetime


@dataclass
class Event:
    startTimestamp: float
    endTimestamp: float
    name: str
    extras: dict = field(default_factory=lambda:{})

    def __str__(self) -> str:
        start = time.localtime(self.startTimestamp)
        end = time.localtime(self.endTimestamp)
        return (
            f"{self.name}:{start.tm_mon}/{start.tm_mday} - {end.tm_mon}/{end.tm_mday}"
        )


@dataclass
class EventNews:
    freeGacha: Optional[Event] = None  # 免费扭蛋
    tower: Optional[Event] = None  # 露娜塔
    dropItemNormal: Optional[Event] = None  # 普通关卡掉落活动
    hatsune: Optional[Event] = None  # 剧情活动
    clanBattle: Optional[Event] = None  # 公会战


def is_emulator_online(dnpath):
    if not dnpath:
        return False
    command_result = os.popen(f"{dnpath}\ldconsole.exe list2").read()
    if command_result:
        infos = list(map(lambda x: x.split(","), command_result.split("\n")))
        if infos and int(infos[0][2]) > 0 and int(infos[0][4]) == 1:
            return True
    return False


def open_leidian_emulator(dnpath):
    # 开启雷电模拟器
    # 检查当前运行的程序有没有雷电模拟器
    running_process = os.popen("wmic process get description").read()
    running_process = list(
        map(lambda name: name.rstrip(), running_process.split("\n\n"))
    )
    if "dnplayer.exe" not in running_process:
        subprocess.Popen(f"{dnpath}\dnplayer.exe", shell=True)
        time.sleep(5)
    retry_count = 0
    while retry_count < 10:
        if is_emulator_online(dnpath):
            print("the emulator is ready.")
            break
        else:
            print("no emulator detected, wait for 20 seconds")
            time.sleep(20)
            retry_count += 1
    if retry_count >= 10:
        print("exit can't found device")
        return -1
    else:
        print("try start princess connect application")
        if dnpath:
            os.system(
                f"{dnpath}\ldconsole.exe runapp --index 0 --packagename com.bilibili.priconne"
            )
            exit_code = 0
        else:
            os.system(
                f'adb -s {DNSimulator2("").get_devices()[0]} shell monkey -p com.bilibili.priconne 1'
            )
            exit_code = 1
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
    current_time = datetime.now().strftime(_time_format)
    cursor.execute(
        f'SELECT start_time,end_time FROM campaign_freegacha WHERE end_time > "{current_time}" and freegacha_10 = 1 and start_time <= "{current_time}"'
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
    current_time = datetime.now().strftime(_time_format)
    cursor.execute(
        f'SELECT start_time,end_time, original_event_id FROM hatsune_schedule WHERE end_time > "{current_time}" and start_time <= "{current_time}"'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time, original_event_id = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, "剧情活动", {"original_event_id":original_event_id})


def _query_tower_event(conn: sqlite3.Connection):
    cursor = conn.cursor()
    current_time = datetime.now().strftime(_time_format)
    cursor.execute(
        f'SELECT start_time,end_time FROM tower_schedule WHERE end_time > "{current_time}" and start_time <= "{current_time}"'
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
    current_time = datetime.now().strftime(_time_format)
    cursor.execute(
        f'SELECT start_time,end_time,value  FROM campaign_schedule WHERE end_time > "{current_time}" and start_time <= "{current_time}" and campaign_category=31'
    )
    result = cursor.fetchall()
    cursor.close()
    if result:
        start_time, end_time, value = result[0]
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, f"普通关卡{int(value/1000)}倍掉落", {"value":value})


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
            free_gacha = _query_free_gacha_event(conn)
            hatsune = _query_hatsune_event(conn)
            tower = _query_tower_event(conn)
            drop_normal = _query_drop_normal_event(conn)
        return EventNews(freeGacha=free_gacha, hatsune=hatsune, tower=tower, dropItemNormal=drop_normal)
    except Exception:
        print("parse db file failed, filter all event special task")
        return EventNews()


def event_valid(current_time, event: Event):
    if not event:
        return False
    return event.startTimestamp <= current_time <= event.endTimestamp


def event_first_day(current_time, event: Event):
    if current_time > event.startTimestamp:
        return (
            time.localtime(current_time).tm_mday
            == time.localtime(event.startTimestamp).tm_mday
        )
    return False


def modify_task_list(news: EventNews, task_list: list):
    current = time.time()
    for i in range(len(task_list) - 1, -1, -1):
        name = task_list[i][0]
        if name == "choushilian":
            if not event_valid(current, news.freeGacha):
                # 无免费十连活动，移除任务
                task_list.pop(i)
        elif name == "activity_saodang":
            if not event_valid(current, news.hatsune):
                # 无剧情活动，移除任务
                task_list.pop(i)
            else:
                if event_first_day(current, news.hatsune):
                    # 剧情活动第一天，需要清图,替换任务
                    task_list.pop(i)
                    task_list.insert(i, ["clear_activity_first_time"]) # 该任务未测试，等待下次剧情活动开始进行验证
                elif news.hatsune.extras["original_event_id"] != 0 and news.dropItemNormal:
                    # 如果是复刻活动，并且有掉落双倍则不在剧情活动清空体力
                    task_list.pop(i)
                else:
                    # 正常在剧情活动清空体力
                    pass
        elif name == "luna_tower_saodang":
            if not event_valid(current, news.tower):
                # 无露娜塔，移除任务
                task_list.pop(i)
            else:
                if event_first_day(current, news.tower):
                    # 露娜塔第一天，需要开启回廊
                    task_list.pop(i)


def run_script(config, use_adb):
    drivers = DNSimulator2(config["Extra"]["dnpath"], useADB=use_adb).get_dirvers()
    if not drivers:
        print("Device not found.")
        return
    # 使用第一个设备
    robot = Robot(drivers[0])
    if config["Extra"]["ocr"]:
        robot.ocr = ocr.Ocr()
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
    return_code = open_leidian_emulator(dnpath)
    if return_code < 0:
        print("open leidian emulator failed")
    else:
        if return_code == 0:
            print("leidian emulator install path is configured, use leidian console.")
        else:
            print("leidian emulator install path not found, use ADB command.")
        run_script(config, return_code != 0)
