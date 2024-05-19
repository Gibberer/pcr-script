import requests
import brotli
import sqlite3
from datetime import datetime
import os
import yaml

from pcrscript.tasks import EventNews, Event



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

def _query_event_duration(conn:sqlite3.Connection, table:str, desc:str=None, select:str=None, condition:str=None, event_producer=None):
    cursor = conn.cursor()
    current_time = datetime.now().isoformat(' ', 'seconds')
    if not select:
        select = "start_time,end_time"
    if not condition:
        condition = f'ISO(end_time) > "{current_time}" and ISO(start_time) <= "{current_time}"'
    cursor.execute(f'SELECT {select} FROM {table} WHERE {condition}')
    result = cursor.fetchall()
    cursor.close()
    if result:
        if event_producer:
            return event_producer(result[0])
        else:
            start_time, end_time = result[0]
            start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
            end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
            return Event(start_time, end_time, desc)


def _query_free_gacha_event(conn: sqlite3.Connection):
    current_time = datetime.now().isoformat(' ', 'seconds')
    return _query_event_duration(conn, 'campaign_freegacha', '免费扭蛋十连', 
                                 condition=f'ISO(end_time) > "{current_time}" and freegacha_10 = 1 and ISO(start_time) <= "{current_time}"')

def _query_hatsune_event(conn: sqlite3.Connection):

    def gen_result(result):
        start_time, end_time, original_event_id = result
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        if original_event_id > 0:
            name = "剧情活动（复刻）"
        else:
            name = "剧情活动"
        return Event(start_time, end_time, name, {"original_event_id":original_event_id})
    return _query_event_duration(conn, 'hatsune_schedule', select='start_time,end_time,original_event_id', event_producer=gen_result)


def _query_tower_event(conn: sqlite3.Connection):
    return _query_event_duration(conn, 'tower_schedule', desc='露娜塔')

def _query_drop_normal_event(conn: sqlite3.Connection):
    def gen_event(result):
        start_time, end_time, value = result
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, f"普通关卡{int(value/1000)}倍掉落", {"value":value})
    current_iso_time = datetime.now().isoformat(' ', 'seconds')
    return _query_event_duration(conn, 'campaign_schedule', select='start_time,end_time,value',
                                 condition=f'ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}" and campaign_category=31',
                                 event_producer=gen_event)

def _query_drop_hard_event(conn: sqlite3.Connection):
    def gen_event(result):
        start_time, end_time, value = result
        start_time = datetime.timestamp(datetime.strptime(start_time, _time_format))
        end_time = datetime.timestamp(datetime.strptime(end_time, _time_format))
        return Event(start_time, end_time, f"困难关卡{int(value/1000)}倍掉落", {"value":value})
    current_iso_time = datetime.now().isoformat(' ', 'seconds')
    return _query_event_duration(conn, 'campaign_schedule', select='start_time,end_time,value',
                                 condition=f'ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}" and campaign_category=32',
                                 event_producer=gen_event)

def _query_secret_dungeon(conn: sqlite3.Connection):
    return _query_event_duration(conn, 'secret_dungeon_schedule', desc="特别地下城")

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
            secret_dungeon = _query_secret_dungeon(conn)
        return EventNews(freeGacha=free_gacha, hatsune=hatsune, tower=tower, dropItemNormal=drop_normal, 
                         dropItemHard=drop_hard, secretDungeon=secret_dungeon)
    except Exception as e:
        print(f"parse db file failed, filter all event special task. Case: {e}")
        return EventNews()