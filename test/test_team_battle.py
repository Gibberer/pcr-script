from datetime import datetime, timedelta, timezone
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, TextBox
from pcrscript.game_ui.team_battle import Boss, can_repeat, map_bosses, priority, recommendation_time
from pcrscript.news import _query_clan_battle
from pcrscript.tasks.task_team_battle import TeamBattle


def box(text, x, y):
    return TextBox(text, 1.0, [[x-18, y-8], [x+18, y-8], [x+18, y+8], [x-18, y+8]])


class TeamBattleTests(unittest.TestCase):
    def test_lanes_and_repeat_budget(self):
        items = [box('团队战', 105, 35), box('剩余挑战次数', 360, 400),
                 box('讨伐信息', 240, 450)]
        items += [box(f'第{lap}轮', x, 335) for x, lap in zip((125, 290, 480, 625, 840), (2, 3, 4, 4, 5))]
        bosses = map_bosses(EventScreen(np.zeros((540, 960, 3), np.uint8), items))
        self.assertEqual([(b.lane, b.lap) for b in bosses], list(enumerate((2, 3, 4, 4, 5))))
        self.assertGreater(priority(Boss(0, 2, 125, 42, 42), 2),
                           priority(Boss(4, 5, 840, 42, 42), 2))
        self.assertTrue(can_repeat(49))
        self.assertFalse(can_repeat(48))


    def test_recommendation_time_and_empty_portrait(self):
        image = np.full((540, 960, 3), 180, np.uint8)
        for x in (224, 312, 402, 491, 581):
            image[220:266, x-22:x+22] = (25, 80, 220)
        items = [box('使用', 711, 277), box('讨伐时间', 86, 299), box('0:17', 151, 299)]
        screen = EventScreen(image, items)
        button = screen.find('使用', (625, 195, 800, 425), exact=True)
        self.assertEqual(recommendation_time(screen, button.center[1]), 17)
        self.assertTrue(TeamBattle.recommendation_owned(screen, button))
        restricted = EventScreen(image, items+[box('限制实战使用', 310, 256)])
        self.assertFalse(TeamBattle.recommendation_owned(restricted, button))
        image[220:266, 380:424] = (180, 180, 180)
        self.assertFalse(TeamBattle.recommendation_owned(EventScreen(image, items), button))

    def test_formation_waits_for_detail_transition(self):
        image = np.zeros((540, 960, 3), np.uint8)
        transitioning = EventScreen(image, [box('队伍编组', 480, 42), box('魔物详情', 105, 52)])
        stable = EventScreen(image, [box('队伍编组', 480, 42)])
        self.assertFalse(TeamBattle.formation_ready(transitioning))
        self.assertTrue(TeamBattle.formation_ready(stable))

    def test_chest_overlay_does_not_count_as_clear_map(self):
        items = [box('团队战', 105, 35), box('剩余挑战次数', 360, 400),
                 box('讨伐信息', 240, 450)]
        dark = EventScreen(np.full((540, 960, 3), 40, np.uint8), items)
        clear = EventScreen(np.full((540, 960, 3), 190, np.uint8), items)
        self.assertFalse(TeamBattle.map_clear(dark))
        self.assertTrue(TeamBattle.map_clear(clear))

    def test_single_digit_count_retries_at_three_times_scale(self):
        ui = EventUI(None)
        ui._ocr = Mock(side_effect=[SimpleNamespace(txts=None, scores=None),
                                    SimpleNamespace(txts=('11',), scores=(.74,)),
                                    SimpleNamespace(txts=('1',), scores=(.996,))])
        screen = EventScreen(np.zeros((540, 960, 3), np.uint8), [])
        self.assertEqual(ui.number(screen, (397, 391, 431, 424)), 1)
        self.assertEqual(ui._ocr.call_count, 3)

    def test_used_character_is_rejected_even_in_simulation_formation(self):
        image = np.zeros((540, 960, 3), np.uint8)
        self.assertFalse(TeamBattle.used_member_marked(EventScreen(image, [])))
        image[482:505, 48:144] = (20, 20, 170)
        self.assertTrue(TeamBattle.used_member_marked(EventScreen(image, [])))


    def test_clan_battle_schedule_only_covers_five_days(self):
        cn = timezone(timedelta(hours=8))
        start = (datetime.now(cn)-timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
        conn = sqlite3.connect(':memory:')
        conn.create_function('ISO', 1, lambda value: str(datetime.strptime(value, '%Y/%m/%d %H:%M:%S')))
        conn.execute('CREATE TABLE clan_battle_schedule (clan_battle_id INTEGER, start_time TEXT, end_time TEXT)')
        conn.execute('INSERT INTO clan_battle_schedule VALUES (?, ?, ?)',
                     (1, start.strftime('%Y/%m/%d %H:%M:%S'),
                      (start+timedelta(days=30)).strftime('%Y/%m/%d %H:%M:%S')))
        event = _query_clan_battle(conn)
        self.assertIsNotNone(event)
        expected_end = start.replace(hour=0)+timedelta(days=5, seconds=-1)
        self.assertEqual(event.endTimestamp, expected_end.timestamp())

    def test_older_event_database_without_schedule_skips_team_battle(self):
        conn = sqlite3.connect(':memory:')
        self.assertIsNone(_query_clan_battle(conn))
