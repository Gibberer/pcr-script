"""Offline calendar, one-time receipts and independent layout routing."""
from datetime import datetime, timedelta
from contextlib import closing
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path
import cv2 as cv
import numpy as np

from pcrscript.news import _query_revival_event, _iso_datetime
from pcrscript.tasks import Event, EventNews, RevivalEventOnce
from pcrscript.tasks.revival_state import RevivalState
from pcrscript.game_ui.event_layout import event_layout
from test_event import frame
from test_event import ReplayUI
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pcrscript.tasks.event_battle import EventCombat
from pcrscript.game_ui.equipment import EquipmentBadges
from pcrscript.tasks.revival_map import RevivalMap
from pcrscript.tasks.task_revival_event import RevivalEventOnce
from pcrscript.game_ui.screen import EventUIError


class RevivalTests(unittest.TestCase):
    def test_completed_receipt_skips_all_ui(self):
        event = Event(10,20,'复刻',{'event_id':11})
        with TemporaryDirectory() as root:
            RevivalState(root, 'a', event).save({'status':'complete'})
            robot = SimpleNamespace(driver=Mock())
            robot.driver.get_screen_size.return_value = (960,540)
            runner = RevivalEventOnce(robot,event,{'account_key':'a','state_dir':root,'output':root})
            runner.enter = Mock(side_effect=AssertionError('completed task must not enter game'))
            self.assertEqual(runner.run()['status'],'already_complete')

    def test_list_revival_keeps_partial_receipt_when_boss_is_blocked(self):
        import time
        event = Event(time.time()-60,time.time()+600,'未来复刻',{'event_id':12})
        with TemporaryDirectory() as root:
            robot = SimpleNamespace(driver=Mock())
            robot.driver.get_screen_size.return_value = (960,540)
            runner = RevivalEventOnce(robot,event,{'account_key':'a','state_dir':root,'output':root})
            runner.enter = Mock(side_effect=lambda: setattr(runner,'layout','list'))
            for name in ('stories','memoirs','missions','exchange'):
                setattr(runner,name,Mock())
            with patch('pcrscript.tasks.event_battle.EventBattles') as battles:
                battles.return_value.bosses.side_effect = lambda: runner.report['pending'].append('缺少当期作业')
                report = runner.run()
            self.assertEqual(report['status'],'partial')
            self.assertFalse(RevivalState(root,'a',event).complete)
            runner.exchange.assert_called_once()

    def exchange_runner(self, frames):
        ui = ReplayUI(frames)
        runner = SimpleNamespace(ui=ui, check_deadline=Mock(), log=Mock())
        flow = RevivalMap(runner)
        flow.hub = Mock()
        return flow, ui

    @staticmethod
    def exchange_frame(balance, consume=100):
        return frame(('讨伐证交换',120,30),('讨伐证',780,444),
                     (str(balance),906,444),(f'{consume}次交换',830,360),(f'使用{consume}张',830,399))

    def test_exchange_remainder_and_zero_confirmation(self):
        flow, ui = self.exchange_runner([self.exchange_frame(84,84), self.exchange_frame(0)])
        flow.exchange(already_open=True)
        self.assertEqual(ui.clicks,['84次交换'])
        flow.hub.assert_called_once()

    def test_exchange_unexpected_debit_stops_before_next_click(self):
        flow, ui = self.exchange_runner([self.exchange_frame(184), self.exchange_frame(85,85)])
        with self.assertRaises(EventUIError):
            flow.exchange(already_open=True)
        self.assertEqual(ui.clicks,['100次交换'])
        flow.hub.assert_not_called()

    def test_exchange_does_not_skip_nonempty_pool(self):
        flow, ui = self.exchange_runner([frame(('当前的列表',480,42),('剩余0/2',650,117),('剩余5/418',650,282))])
        with self.assertRaises(EventUIError):
            flow.exchange(already_open=True)
        self.assertEqual(ui.clicks,[])

    def test_special_completion_scrolls_the_boss_list(self):
        flow, ui = self.exchange_runner([frame(('普通',760,145)),frame(('表演赛',760,260))])
        ui.swipe = Mock()
        self.assertTrue(flow.special_complete())
        ui.swipe.assert_called_once_with((820,285),(820,145))

    def test_special_header_number_is_not_a_kill_counter(self):
        flow, ui = self.exchange_runner([])
        ui.number = Mock(return_value=255)
        flow.r.options = {}
        flow.r.event = SimpleNamespace(name='测试活动')
        flow.r.report = {'pending':[]}
        flow.special_complete = Mock(return_value=False)
        flow.boss_detail = Mock(return_value=frame(('特别难度/阶段1',320,45)))
        flow.home = Mock()
        with patch('pcrscript.tasks.revival_map.load_parties',return_value=[]):
            flow.sourced_boss('特别','special')
        ui.number.assert_not_called()
        self.assertTrue(flow.r.report['pending'])

    def test_exchange_waits_for_connection_before_reading_old_balance(self):
        connecting = self.exchange_frame(184)
        connecting.items.extend(frame(('正在进行数据连接',800,25)).items)
        flow, ui = self.exchange_runner([self.exchange_frame(184),connecting,self.exchange_frame(84,84),self.exchange_frame(0)])
        with patch('pcrscript.tasks.revival_map.time.sleep'):
            flow.exchange(already_open=True)
        self.assertEqual(ui.clicks,['100次交换','84次交换'])

    def test_story_list_reward_hint_is_not_a_reward_dialog(self):
        screen = frame(('活动剧情一览',480,42),('可以获得奖励道具',480,90),('终章',400,160))
        flow, ui = self.exchange_runner([screen]*4)
        ui.swipe = Mock()
        ui.expect_click = Mock()
        flow.r.story_dialog = Mock(return_value=True)
        flow.read_stories(already_open=True)
        flow.r.story_dialog.assert_not_called()
        ui.expect_click.assert_called_once_with('关闭',(350,445,615,515),exact=True)

    def test_hard_trial_authorization_is_single_use_and_event_scoped(self):
        detail = frame(('BOSS详情',100,45),('混沌发电机',320,250),('50',700,42),('0',909,42))
        for authorized, already_started in ((10171,True),(10172,False),(None,False)):
            with self.subTest(authorized=authorized,started=already_started):
                ui = ReplayUI([detail])
                runner = SimpleNamespace(ui=ui,event=Event(0,1,'复刻',{'event_id':10171}),
                    options={'hard_trial_event_id':authorized},
                    state=SimpleNamespace(data={'hard_trial_started':already_started}))
                with self.assertRaises(EventUIError):
                    RevivalMap(runner).hard_trial_from_detail()
                self.assertEqual(ui.clicks,[])

    def test_paused_set_matches_two_enabled_members(self):
        s = frame()
        patch = cv.imread(str(Path(__file__).parent/'fixtures/story_event/paused_set.png'))
        for i in range(5):
            x = round(306+87.5*i)
            s.image[190:217,x+23:x+49] = patch[:,i*26:(i+1)*26]
        self.assertEqual([bool(EventCombat.paused_instant(s,i)) for i in range(5)],
                         [False,True,False,False,True])

    def test_victory_during_set_configuration_is_not_retreat_failure(self):
        ui = ReplayUI([frame(('WIN!',480,150)), frame(('伤害报告',850,35))])
        combat = EventCombat(SimpleNamespace(ui=ui))
        combat.match = Mock(return_value=None)
        self.assertEqual(combat.retreat('SET检查期间结束').outcome, 'settled')
        self.assertEqual(ui.clicks, [])

    def test_filled_orbs_are_information_frame_not_stars(self):
        card = np.zeros((100,100,3), np.uint8)
        card[69:100,:45] = cv.imread(str(Path(__file__).parent/'fixtures/story_event/badge_filled_orbs.png'))
        badges = EquipmentBadges()
        self.assertEqual(badges.read(card,(0,0,100,100)), (False,False))
        card[85:92,19:26] = 0
        self.assertIsNone(badges.read(card,(0,0,100,100)))

    def test_concurrent_event_does_not_hide_revival(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.create_function('ISO', 1, _iso_datetime)
            db.execute('CREATE TABLE hatsune_schedule(event_id, original_event_id, start_time, end_time)')
            db.execute('CREATE TABLE event_story_data(value,title)')
            now = datetime.now()
            start, end = [(now+timedelta(days=d)).strftime('%Y/%m/%d %H:%M:%S') for d in (-1, 1)]
            db.executemany('INSERT INTO hatsune_schedule VALUES(?,?,?,?)', [
                (10, 0, start, end), (11, 9, start, end), (12, 9, end, end)])
            db.execute('INSERT INTO event_story_data VALUES(11,?)', ('复刻标题',))
            event = _query_revival_event(db)
            self.assertEqual(event.extras['event_id'], 11)
            self.assertEqual(event.name, '复刻标题')
            self.assertIs(RevivalEventOnce.valid(EventNews(revival=event))[0], RevivalEventOnce)
            db.execute('DELETE FROM hatsune_schedule WHERE event_id=11')
            self.assertIsNone(_query_revival_event(db))
            self.assertIsNone(RevivalEventOnce.valid(EventNews()))

    def test_receipts_scope_and_partial_resume(self):
        event = Event(10, 20, '复刻', {'event_id': 11})
        with TemporaryDirectory() as root:
            state = RevivalState(root, 'account-a', event)
            state.save({'status': 'partial'})
            self.assertFalse(RevivalState(root, 'account-a', event).complete)
            state.save({'status': 'complete'})
            self.assertTrue(RevivalState(root, 'account-a', event).complete)
            self.assertFalse(RevivalState(root, 'account-b', event).complete)
            self.assertFalse(RevivalState(root, 'account-a', Event(30,40,'复刻',{'event_id':11})).complete)

    def test_live_layout_is_not_calendar_edition(self):
        self.assertEqual(event_layout(frame(('活动关卡·首领',140,30))), 'list')
        self.assertEqual(event_layout(frame(('讨伐证交换',830,455),('普通',760,82),('困难',890,82))), 'map')
        self.assertIsNone(event_layout(frame(('复刻',320,435))))


if __name__ == '__main__':
    unittest.main()
