"""Synthetic schedule and database-update regressions; no network or game data."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from pcrscript import news
from pcrscript.tasks import Event, TimeLimitTask


CN = timezone(timedelta(hours=8))
TOKYO = timezone(timedelta(hours=9))


class NewsScheduleTests(TestCase):
    def test_event_display_keeps_server_dates_across_host_timezones(self):
        event = Event(news._event_timestamp('2026/09/29 00:30:00'),
                      news._event_timestamp('2026/09/30 23:30:00'), 'synthetic')
        for host in (TOKYO, timezone.utc, timezone(timedelta(hours=-7))):
            with self.subTest(host=host), \
                    patch('pcrscript.tasks.base.time.localtime',
                          side_effect=lambda stamp: datetime.fromtimestamp(stamp, host).timetuple()):
                self.assertEqual(str(event), 'synthetic:9/29 - 9/30')

    def test_all_schedules_use_server_time_on_a_tokyo_computer(self):
        start, end = '2026/09/29 05:00:00', '2026/09/29 06:00:00'
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.create_function('ISO', 1, news._iso_datetime)
            for table, extra, rows in (
                ('campaign_freegacha', ', freegacha_10 INTEGER', [(1,)]),
                ('hatsune_schedule', ', original_event_id INTEGER', [(0,)]),
                ('tower_schedule', '', [()]),
                ('campaign_schedule', ', value INTEGER, campaign_category INTEGER', [(2000, 31), (3000, 32)]),
                ('secret_dungeon_schedule', '', [()]),
            ):
                conn.execute(f'CREATE TABLE {table} (start_time TEXT, end_time TEXT{extra})')
                for row in rows:
                    values = (start, end, *row)
                    conn.execute(f'INSERT INTO {table} VALUES ({",".join("?" for _ in values)})', values)
            for hour, minute, active in ((4, 59, False), (5, 0, True), (5, 30, True), (6, 0, False)):
                instant = datetime(2026, 9, 29, hour, minute, tzinfo=CN)

                class TokyoClock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        value = instant.astimezone(tz or TOKYO)
                        return value if tz else value.replace(tzinfo=None)

                    def timestamp(self):
                        return datetime.timestamp(self if self.tzinfo else self.replace(tzinfo=TOKYO))

                with patch.object(news, 'datetime', TokyoClock):
                    for query in (news._query_free_gacha_event, news._query_hatsune_event,
                                  news._query_tower_event, news._query_drop_normal_event,
                                  news._query_drop_hard_event, news._query_secret_dungeon):
                        with self.subTest(query=query.__name__, hour=hour, minute=minute):
                            event = query(conn)
                            self.assertEqual(event is not None, active)
                            if event:
                                self.assertEqual(event.startTimestamp, datetime(2026, 9, 29, 5, tzinfo=CN).timestamp())
                                self.assertEqual(event.endTimestamp, datetime(2026, 9, 29, 6, tzinfo=CN).timestamp())

    def test_first_day_uses_full_server_date_including_the_start_instant(self):
        start = datetime(2026, 9, 29, 5, tzinfo=CN)
        event = Event(start.timestamp(), (start + timedelta(days=40)).timestamp(), 'synthetic')
        for now, expected in ((start, True), (start.replace(hour=23, minute=30), True),
                              (start - timedelta(seconds=1), False),
                              (start + timedelta(days=1), False),
                              (start.replace(month=10), False)):
            with self.subTest(now=now), patch('pcrscript.tasks.base.time.time', return_value=now.timestamp()), \
                    patch('pcrscript.tasks.base.time.localtime', side_effect=lambda stamp: datetime.fromtimestamp(stamp, TOKYO).timetuple()):
                self.assertEqual(TimeLimitTask.event_first_day(event), expected)


class AbyssSubjugationScheduleTests(TestCase):
    def database(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.create_function('ISO', 1, news._iso_datetime)
        conn.execute('CREATE TABLE abyss_schedule '
                     '(abyss_id INTEGER, boss_ticket_id INTEGER, talent_id INTEGER, '
                     'title TEXT, start_time TEXT, end_time TEXT)')
        conn.executemany('INSERT INTO abyss_schedule VALUES(?,?,?,?,?,?)', [
            (1, 70001, 1, '合成旧活动', '2026/9/2 12:00:00', '2026/9/7 4:59:59'),
            (2, 70002, 2, '合成活动', '2026/10/2 12:00:00', '2026/10/7 4:59:59'),
            (3, 70003, 3, '合成未来活动', '2026/11/2 12:00:00', '2026/11/7 4:59:59'),
        ])
        return conn

    def test_active_event_uses_actual_window_and_ticket_identity(self):
        conn = self.database()
        for instant, active in ((datetime(2026, 10, 2, 11, 59, 59, tzinfo=CN), False),
                                (datetime(2026, 10, 2, 12, tzinfo=CN), True),
                                (datetime(2026, 10, 7, 4, 59, 58, tzinfo=CN), True),
                                (datetime(2026, 10, 7, 4, 59, 59, tzinfo=CN), False),
                                (datetime(2026, 10, 7, 5, tzinfo=CN), False)):
            class TokyoClock(datetime):
                @classmethod
                def now(cls, tz=None):
                    value = instant.astimezone(tz or TOKYO)
                    return value if tz else value.replace(tzinfo=None)
            with self.subTest(instant=instant), patch.object(news, 'datetime', TokyoClock):
                event = news._query_abyss_subjugation(conn)
                self.assertEqual(event is not None, active)
                if event:
                    self.assertEqual(event.extras, dict(abyss_id=2, boss_ticket_id=70002,
                                                      talent_id=2, title='合成活动'))
                    self.assertEqual(event.startTimestamp, datetime(2026, 10, 2, 12, tzinfo=CN).timestamp())
                    self.assertEqual(event.endTimestamp, datetime(2026, 10, 7, 4, 59, 59, tzinfo=CN).timestamp())

    def test_missing_optional_table_skips_only_this_event(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            self.assertIsNone(news._query_abyss_subjugation(conn))
            conn.execute('CREATE TABLE abyss_schedule (broken INTEGER)')
            with self.assertRaises(sqlite3.OperationalError):
                news._query_abyss_subjugation(conn)


class NewsDatabaseTests(TestCase):
    def test_build_news_releases_sqlite_connection(self):
        class StopQuery(Exception):
            pass

        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        with patch.object(news.sqlite3, 'connect', return_value=connection), \
                patch.object(news, '_query_free_gacha_event', side_effect=StopQuery):
            with self.assertRaises(StopQuery):
                news._build_event_news('.', 'synthetic.db')
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')


class CollaborationScheduleTests(TestCase):
    def test_local_schedule_keeps_ticket_types_and_exact_boundaries(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.create_function('ISO', 1, news._iso_datetime)
            conn.execute('CREATE TABLE mre_schedule (schedule_id INTEGER,mre_id INTEGER,event_type INTEGER,'
                         'boss_ticket_id INTEGER,gacha_ticket_id INTEGER,start_time TEXT,end_time TEXT)')
            conn.execute('INSERT INTO mre_schedule VALUES (1,2,1,73001,72001,?,?)',
                         ('2026/10/23 11:00:00','2026/11/2 10:59:59'))
            for instant, active in [(datetime(2026,10,23,10,59,59,tzinfo=CN),False),
                                    (datetime(2026,10,23,11,tzinfo=CN),True),
                                    (datetime(2026,11,2,10,59,59,tzinfo=CN),False)]:
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return instant.astimezone(tz or TOKYO)
                with patch.object(news, 'datetime', Clock):
                    event = news._query_collaboration_raid(conn)
                self.assertEqual(event is not None,active)
                if event:
                    self.assertEqual(event.extras['boss_ticket_id'],73001)
                    self.assertEqual(event.extras['gacha_ticket_id'],72001)

    def test_bad_optional_table_is_unknown_instead_of_closed(self):
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.execute('CREATE TABLE secret_dungeon_schedule (broken INTEGER)')
            with self.assertRaises(sqlite3.OperationalError):
                news._query_secret_dungeon(conn)
