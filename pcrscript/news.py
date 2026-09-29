import requests
import brotli
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml

from pcrscript.constants import SERVER_TIMEZONE
from pcrscript.tasks import EventNews, Event



def _upgrade_db_file(config, db_dir, db_file):
    response = requests.post("https://wthee.xyz/pcr/api/v1/db/info/v2", json={"regionCode":"cn"}, timeout=(10, 30))
    response.raise_for_status()
    remote_version = int(response.json()["data"]["truthVersion"])
    target = Path(db_dir) / db_file
    if (config.get("version", 0) >= remote_version
            and target.is_file() and target.stat().st_size > 0):
        return
    # Keep the last usable database until the entire replacement is validated.
    # Stage on the same filesystem so publication is a single atomic replace.
    with TemporaryDirectory(prefix='.db-update-', dir=db_dir) as staging:
        compressed_file = Path(staging) / 'database.br'
        with requests.get("https://wthee.xyz/db/redive_cn.db.br", stream=True, timeout=(10, 60)) as r:
            r.raise_for_status()
            with compressed_file.open("wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        db = brotli.decompress(compressed_file.read_bytes())
        if not db.startswith(b'SQLite format 3\0'):
            raise ValueError('下载内容不是 SQLite 数据库')
        candidate = Path(staging) / 'database.db'
        candidate.write_bytes(db)
        with closing(sqlite3.connect(candidate)) as conn:
            if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise sqlite3.DatabaseError('下载的数据库完整性检查失败')
        os.replace(candidate, target)
        config["version"] = remote_version


_time_format = "%Y/%m/%d %H:%M:%S"

def _event_timestamp(value):
    return datetime.strptime(value, _time_format).replace(tzinfo=SERVER_TIMEZONE).timestamp()

def _query_event_duration(conn:sqlite3.Connection, table:str, desc:str=None, select:str=None, condition:str=None, event_producer=None):
    cursor = conn.cursor()
    current_time = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
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
            start_time = _event_timestamp(start_time)
            end_time = _event_timestamp(end_time)
            return Event(start_time, end_time, desc)


def _query_free_gacha_event(conn: sqlite3.Connection):
    current_time = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    return _query_event_duration(conn, 'campaign_freegacha', '免费扭蛋十连', 
                                 condition=f'ISO(end_time) > "{current_time}" and freegacha_10 = 1 and ISO(start_time) <= "{current_time}"')

def _query_hatsune_event(conn: sqlite3.Connection):

    def gen_result(result):
        start_time, end_time, original_event_id = result
        start_time = _event_timestamp(start_time)
        end_time = _event_timestamp(end_time)
        if original_event_id > 0:
            name = "剧情活动（复刻）"
        else:
            name = "剧情活动"
        return Event(start_time, end_time, name, {"original_event_id":original_event_id})
    return _query_event_duration(conn, 'hatsune_schedule', select='start_time,end_time,original_event_id', event_producer=gen_result)


def _query_revival_event(conn: sqlite3.Connection):
    """Query revivals independently: another active event must not hide one."""
    now = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    row = conn.execute(
        'SELECT event_id, original_event_id, start_time, end_time FROM hatsune_schedule '
        'WHERE original_event_id > 0 AND ISO(start_time) <= ? AND ISO(end_time) > ? '
        'ORDER BY start_time DESC, event_id DESC LIMIT 1', (now, now)).fetchone()
    if row is None:
        return None
    event_id, original_id, start, end = row
    title = conn.execute('SELECT title FROM event_story_data WHERE value=?', (event_id,)).fetchone()
    return Event(_event_timestamp(start), _event_timestamp(end),
                 title[0].replace('\\n', ' ') if title else '剧情活动（复刻）',
                 {'event_id': event_id, 'original_event_id': original_id})


def _query_tower_event(conn: sqlite3.Connection):
    return _query_event_duration(conn, 'tower_schedule', desc='露娜塔')

def _query_drop_normal_event(conn: sqlite3.Connection):
    def gen_event(result):
        start_time, end_time, value = result
        start_time = _event_timestamp(start_time)
        end_time = _event_timestamp(end_time)
        return Event(start_time, end_time, f"普通关卡{int(value/1000)}倍掉落", {"value":value})
    current_iso_time = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    return _query_event_duration(conn, 'campaign_schedule', select='start_time,end_time,value',
                                 condition=f'ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}" and campaign_category=31',
                                 event_producer=gen_event)

def _query_drop_hard_event(conn: sqlite3.Connection):
    def gen_event(result):
        start_time, end_time, value = result
        start_time = _event_timestamp(start_time)
        end_time = _event_timestamp(end_time)
        return Event(start_time, end_time, f"困难关卡{int(value/1000)}倍掉落", {"value":value})
    current_iso_time = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    return _query_event_duration(conn, 'campaign_schedule', select='start_time,end_time,value',
                                 condition=f'ISO(end_time) > "{current_iso_time}" and ISO(start_time) <= "{current_iso_time}" and campaign_category=32',
                                 event_producer=gen_event)

def _query_secret_dungeon(conn: sqlite3.Connection):
    try:
        return _query_event_duration(conn, 'secret_dungeon_schedule', desc="特别地下城")
    except Exception:
        # 暂时找到的老版本数据库还没有特别地下城，实际脚本也不用这个内容暂时忽略
        return None


def _query_clan_battle(conn: sqlite3.Connection):
    """The schedule row lasts until next month; the battle itself is five days.

    The five-day span matches the current CN in-game calendar. The task still
    verifies the live entrance and challenge counter before doing anything.
    """
    now = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    try:
        row = conn.execute(
            'SELECT clan_battle_id, start_time, end_time FROM clan_battle_schedule '
            'WHERE ISO(start_time) <= ? AND ISO(end_time) > ? '
            'ORDER BY start_time DESC, clan_battle_id DESC LIMIT 1', (now, now)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):
            return None
        raise
    if row is None:
        return None
    battle_id, start, schedule_end = row
    begin = datetime.strptime(start, _time_format).replace(tzinfo=SERVER_TIMEZONE)
    battle_end = begin.replace(hour=0, minute=0, second=0) + timedelta(days=5, seconds=-1)
    if datetime.now(SERVER_TIMEZONE) > battle_end:
        return None
    return Event(begin.timestamp(), battle_end.timestamp(), '团队战',
                 {'clan_battle_id': battle_id, 'schedule_end': schedule_end})

def _iso_datetime(date):
    return str(datetime.strptime(date, _time_format))

def _build_event_news(cache_path, db_file):
    with closing(sqlite3.connect(os.path.join(cache_path, db_file))) as conn:
        conn.create_function('ISO', 1, _iso_datetime)
        free_gacha = _query_free_gacha_event(conn)
        hatsune = _query_hatsune_event(conn)
        revival = _query_revival_event(conn)
        tower = _query_tower_event(conn)
        drop_normal = _query_drop_normal_event(conn)
        drop_hard = _query_drop_hard_event(conn)
        secret_dungeon = _query_secret_dungeon(conn)
        clan_battle = _query_clan_battle(conn)
    return EventNews(freeGacha=free_gacha, hatsune=hatsune, tower=tower, dropItemNormal=drop_normal, 
                         dropItemHard=drop_hard, secretDungeon=secret_dungeon, revival=revival,
                         clanBattle=clan_battle)

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
        return _build_event_news(cache_path, db_file)
    except Exception as e:
        print(f"parse db file failed, filter all event special task. Case: {e}")
        print("try repair db table names and rebuild event info")
        try_repair_db(cache_path, db_file)
        return _build_event_news(cache_path, db_file)
    

def try_repair_db(cache_path, db_file):
    meta_file = os.path.join("other", "redive_cn_meta.db")
    target_file = os.path.join(cache_path, db_file)
    repair_tools = os.path.join(cache_path, "db_repair_tools.exe")
    if not os.path.exists(target_file) or not os.path.exists(meta_file):
        return
    if not os.path.exists(repair_tools):
        response = requests.get("https://github.com/peterli110/pcr-hash-table-rename/releases/download/v1.3/pcr_hash_rename_tool_windows_amd64.exe", stream=True)
        with response as r:
            r.raise_for_status()
            with open(repair_tools, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
    os.system(f".\{repair_tools} -n {target_file} -r {meta_file} -g {target_file}")
