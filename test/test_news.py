"""Synthetic schedule and database-update regressions; no network or game data."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch
import sqlite3

import brotli

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


class NewsDatabaseTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = self.root / 'redive_cn.db'
        self.old = self.database('old.db', 1)
        self.new = self.database('new.db', 2)
        self.target.write_bytes(self.old)
        self.config = {'version': 1}

    def database(self, name, value):
        path = self.root / name
        with closing(sqlite3.connect(path)) as conn:
            conn.execute('CREATE TABLE marker (value INTEGER)')
            conn.execute('INSERT INTO marker VALUES (?)', (value,))
            conn.commit()
        data = path.read_bytes()
        path.unlink()
        return data

    @contextmanager
    def remote(self, data=None, version=2):
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [brotli.compress(self.new if data is None else data)]
        with patch.object(news.requests, 'post') as post, patch.object(news.requests, 'get', return_value=response) as get:
            post.return_value.json.return_value = {'data': {'truthVersion': version}}
            yield post, get, response

    def test_missing_database_is_downloaded_even_when_version_matches(self):
        self.target.unlink()
        with self.remote(version=1) as (_, get, _):
            news._upgrade_db_file(self.config, str(self.root), self.target.name)
        self.assertEqual(self.target.read_bytes(), self.new)
        get.assert_called_once()

    def test_empty_database_is_downloaded_even_when_version_matches(self):
        self.target.write_bytes(b'')
        with self.remote(version=1):
            news._upgrade_db_file(self.config, str(self.root), self.target.name)
        self.assertEqual(self.target.read_bytes(), self.new)

    def test_current_database_does_not_download_again(self):
        with self.remote(version=1) as (_, get, _):
            news._upgrade_db_file(self.config, str(self.root), self.target.name)
        get.assert_not_called()
        self.assertEqual(self.target.read_bytes(), self.old)

    def test_invalid_download_preserves_database_and_version(self):
        for data in (b'not a SQLite database', b''):
            with self.subTest(data=data), self.remote(data=data):
                with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                    news._upgrade_db_file(self.config, str(self.root), self.target.name)
            self.assertEqual(self.target.read_bytes(), self.old)
            self.assertEqual(self.config, {'version': 1})
            self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_failed_download_leaves_version_retryable(self):
        with self.remote() as (_, _, response):
            response.iter_content.side_effect = news.requests.ConnectionError('interrupted download')
            with self.assertRaises(news.requests.ConnectionError):
                news._upgrade_db_file(self.config, str(self.root), self.target.name)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.config, {'version': 1})
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_failed_publication_preserves_old_database_and_version(self):
        with self.remote(), patch.object(news.os, 'replace', side_effect=PermissionError('database busy')):
            with self.assertRaises(PermissionError):
                news._upgrade_db_file(self.config, str(self.root), self.target.name)
        self.assertEqual(self.target.read_bytes(), self.old)
        self.assertEqual(self.config, {'version': 1})
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_successful_update_closes_database_before_publication(self):
        with self.remote() as (post, get, _):
            news._upgrade_db_file(self.config, str(self.root), self.target.name)
        self.assertEqual(self.target.read_bytes(), self.new)
        self.assertEqual(self.config, {'version': 2})
        self.assertEqual(list(self.root.iterdir()), [self.target])
        post.return_value.raise_for_status.assert_called_once()
        self.assertIn('timeout', post.call_args.kwargs)
        self.assertIn('timeout', get.call_args.kwargs)

    def test_build_news_releases_sqlite_connection(self):
        class StopQuery(Exception):
            pass

        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        with patch.object(news.sqlite3, 'connect', return_value=connection), \
                patch.object(news, '_query_free_gacha_event', side_effect=StopQuery):
            with self.assertRaises(StopQuery):
                news._build_event_news(str(self.root), self.target.name)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')
