import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
import os

from pcrscript.constants import SERVER_TIMEZONE
from pcrscript.tasks import EventNews, Event



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
    cursor.execute(f'SELECT {select} FROM {table} WHERE {condition} ORDER BY ISO(start_time) DESC, ISO(end_time) DESC')
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
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):
            return None
        raise


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

def _query_abyss_subjugation(conn: sqlite3.Connection):
    """Use the event's own CN schedule, including its 05:00 closing boundary."""
    now = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    try:
        row = conn.execute(
            'SELECT abyss_id, boss_ticket_id, talent_id, title, start_time, end_time '
            'FROM abyss_schedule WHERE ISO(start_time) <= ? AND ISO(end_time) > ? '
            'ORDER BY ISO(start_time) DESC, abyss_id DESC LIMIT 1', (now, now)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):
            return None
        raise
    if row is None:
        return None
    event_id, ticket_id, talent_id, title, start, end = row
    return Event(_event_timestamp(start), _event_timestamp(end), '深渊讨伐战',
                 dict(abyss_id=event_id, boss_ticket_id=ticket_id, talent_id=talent_id,
                      title=title.replace('\\n', ' ')))


def _iso_datetime(date):
    return str(datetime.strptime(date, _time_format))


def _query_battle_stadium(conn: sqlite3.Connection):
    """CN dome schedule separates battle end from the reward closing time."""
    now = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    try:
        row = conn.execute(
            'SELECT schedule_id, start_time, end_time, close_time FROM dome_schedule_data '
            'WHERE ISO(start_time) <= ? AND ISO(close_time) > ? '
            'ORDER BY ISO(start_time) DESC, schedule_id DESC LIMIT 1', (now, now)).fetchone()
    except sqlite3.OperationalError as error:
        if 'no such table' in str(error):
            return None
        raise
    if row is None:
        return None
    event_id, start, end, close = row
    return Event(_event_timestamp(start), _event_timestamp(close), '斗技场',
                 dict(schedule_id=event_id, battle_end=_event_timestamp(end)))


def _query_collaboration_raid(conn: sqlite3.Connection):
    now = datetime.now(SERVER_TIMEZONE).replace(tzinfo=None).isoformat(' ', 'seconds')
    row = conn.execute(
        'SELECT schedule_id,mre_id,event_type,boss_ticket_id,gacha_ticket_id,start_time,end_time '
        'FROM mre_schedule WHERE ISO(start_time)<=? AND ISO(end_time)>? '
        'ORDER BY ISO(start_time) DESC,schedule_id DESC LIMIT 1', (now, now)).fetchone()
    if row is None:
        return None
    schedule, identity, kind, boss_ticket, reward_ticket, start, end = row
    return Event(_event_timestamp(start), _event_timestamp(end), '联动讨伐',
                 dict(schedule_id=schedule, mre_id=identity, event_type=kind,
                      boss_ticket_id=boss_ticket, gacha_ticket_id=reward_ticket))


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
        abyss_subjugation = _query_abyss_subjugation(conn)
        battle_stadium = _query_battle_stadium(conn)
        collaboration = _query_collaboration_raid(conn)
    return EventNews(freeGacha=free_gacha, hatsune=hatsune, tower=tower, dropItemNormal=drop_normal, 
                         dropItemHard=drop_hard, secretDungeon=secret_dungeon, revival=revival,
                         clanBattle=clan_battle, abyssSubjugation=abyss_subjugation,
                         battleStadium=battle_stadium, collaborationRaid=collaboration)

def fetch_event_news() -> EventNews:
    """One shared static snapshot; updating never requires a game connection."""
    from .masterdata import DATABASE, ensure_masterdata
    source = ensure_masterdata()
    if source.get('warning'):
        print(source['warning'])
    value = _build_event_news(DATABASE.parent, DATABASE.name)
    value.source = source
    return value
