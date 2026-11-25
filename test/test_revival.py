"""Offline calendar, one-time receipts and independent layout routing."""
import re
from pcrscript.game_ui.screen import normalized
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
from pcrscript.tasks.event_strategy import EventParty
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

    def test_exchange_below_one_batch_uses_single_exchange(self):
        single = self.exchange_frame(1, 100)
        single.items.extend(frame(('1次交换',558,358),('使用1张',577,399)).items)
        single.blue_button = lambda item: item is not None and '1次' in item.text
        flow, ui = self.exchange_runner([single, self.exchange_frame(0)])
        flow.exchange(already_open=True)
        self.assertEqual(ui.clicks, ['1次交换'])

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
        with patch('pcrscript.tasks.revival_map.boss_parties', return_value=([], None)):
            flow.sourced_boss('特别','special')
        ui.number.assert_not_called()
        self.assertTrue(flow.r.report['pending'])

    def test_very_hard_borrows_special_phase_one_parties(self):
        flow, ui = self.exchange_runner([])
        ui.number = Mock(return_value=0)
        flow.r.options = {}
        flow.r.event = SimpleNamespace(name='测试活动　副标题')
        flow.r.report = {'pending':[]}
        flow.boss_detail = Mock(return_value=frame(('BOSS详情',100,45)))
        flow.home = Mock()
        sp = EventParty('sp', 'src', [], max_attempts=1)
        calls = []
        def parties(options, **kw):
            calls.append((kw['area'], kw['difficulty'], kw['mode']))
            return ([sp] if kw['difficulty'] == 'special' else []), None
        detail = frame(('BOSS详情',100,45))
        flow.boss_detail = Mock(return_value=detail)
        detail.blue_button = Mock(return_value=False)
        with patch('pcrscript.tasks.revival_map.boss_parties', side_effect=parties):
            flow.sourced_boss('高难','very_hard')
        self.assertEqual(calls, [('测试活动','very_hard',1),('测试活动','special',1)])
        self.assertIn('高难挑战不可用，未购买或追加消费', flow.r.report['pending'])

    def sweep_flow(self, frames):
        flow, ui = self.exchange_runner(frames)
        ui.expect_click = lambda pattern, roi, **kw: ui.clicks.append(pattern)
        ui.read_region = lambda s, roi, **kw: s
        return flow, ui

    @staticmethod
    def stage_detail(left, *extra):
        return frame(('一日店长的轨迹1-5',300,52),('剩余挑战次数',820,413),(f'{left}/3',880,413),
                     ('取消',667,455),*extra)

    def test_hard_stage_sweep_spends_exactly_the_remaining_attempts(self):
        plan = self.stage_detail(2, ('MAX',880,333), ('使用2张',757,333))
        plan.blue_button = Mock(return_value=True)
        confirm = frame(('扫荡券确认',480,150),('消耗券',320,307),('2',458,307),('取消',370,370),('确认',590,370))
        # The detail behind the receipt already reads 0/3 before it closes.
        progress = self.stage_detail(0, ('第2次',300,200), ('跳过完毕',480,480))
        receipt = frame(('扫荡结果',480,40),('扫荡完成',480,200),('确认',480,480),('剩余挑战次数',820,413),('0/3',880,413))
        flow, ui = self.sweep_flow([plan, plan, confirm, progress, receipt, self.stage_detail(0)])
        with patch('pcrscript.tasks.revival_map.time.sleep'):
            self.assertEqual(flow.sweep_stage(self.stage_detail(2), '1-5'), 2)
        self.assertEqual(ui.clicks, ['MAX','使用2张','确认','跳过完毕','确认'])

    def test_hard_stage_sweep_refuses_mismatched_ticket_cost(self):
        plan = self.stage_detail(2, ('MAX',880,333), ('使用2张',757,333))
        plan.blue_button = Mock(return_value=True)
        confirm = frame(('扫荡券确认',480,150),('消耗券',320,307),('3',458,307),('取消',370,370),('确认',590,370))
        flow, ui = self.sweep_flow([plan, plan, confirm])
        with patch('pcrscript.tasks.revival_map.time.sleep'), self.assertRaises(EventUIError):
            flow.sweep_stage(self.stage_detail(2), '1-5')
        self.assertEqual(ui.clicks, ['MAX','使用2张','取消'])

    def test_hard_stage_without_attempts_is_left_untouched(self):
        flow, ui = self.sweep_flow([])
        self.assertEqual(flow.sweep_stage(self.stage_detail(0), '1-5'), 0)
        self.assertEqual(ui.clicks, [])

    def test_hard_stage_sweep_capped_by_stamina_never_refills(self):
        plan = self.stage_detail(3, ('MAX',880,333), ('使用0张',757,333))
        flow, ui = self.sweep_flow([plan, plan])
        from pcrscript.tasks.revival_map import StaminaShort
        with patch('pcrscript.tasks.revival_map.time.sleep'), self.assertRaises(StaminaShort):
            flow.sweep_stage(self.stage_detail(3), '1-5')
        self.assertEqual(ui.clicks, ['MAX','取消'])

    def test_hard_sweep_walks_stages_with_the_detail_arrow(self):
        # The map OCR only found 1-3; the arrows reach 1-1 and walk to the end.
        def detail(n, left=0):
            return frame((f'一日店长的轨迹1-{n}',300,52),('剩余挑战次数',820,413),(f'{left}/3',880,413),('取消',667,455))
        flow, ui = self.sweep_flow([detail(3), detail(2), detail(1), detail(2), detail(3), frame()])
        flow.scan_pages = Mock(return_value=[(None, {(1, 3): SimpleNamespace(center=(380, 380))})])
        flow.home = Mock()
        flow.r.report = {'pending': []}
        with patch('pcrscript.tasks.revival_map.event_layout', side_effect=lambda f: None if f.items else 'map'):
            flow.sweep_hard()
        self.assertEqual(ui.clicks, ['困难', (380, 325), (25, 275), (25, 275), (940, 275), (940, 275), (940, 275)])
        flow.home.assert_called_once()

    def test_visible_special_row_marks_very_hard_cleared(self):
        flow, ui = self.exchange_runner([frame(('特别',740,157))])
        self.assertFalse(flow.special_complete())
        self.assertTrue(flow.special_open)

    def test_special_progress_counts_phase_and_cleared_enemies(self):
        phase1 = frame(('特别难度/阶段1',260,47),('Lv.270',230,280),('Lv.270',380,280))
        phase2 = frame(('特别难度/阶段2',260,47),('已攻略',240,280),('Lv.270',380,280))
        self.assertEqual(RevivalMap.sp_progress(phase1), (1, 0, None))
        self.assertEqual(RevivalMap.sp_progress(phase2), (2, 1, None))
        self.assertIsNone(RevivalMap.sp_progress(frame(('BOSS详情',100,45)))[0])

    def test_home_follows_dimmed_hub_guide_to_special_row(self):
        hub = frame(('活动关卡',555,200),('讨伐证交换',570,340),('首领挑战券',750,120),('特别',740,157))
        flow, ui = self.exchange_runner([hub]*4+[frame(('BOSS详情',100,45))])
        flow.dialog = Mock(return_value=False)
        flow.r.entry_dialog = flow.r.story_dialog = Mock(return_value=False)
        flow.r.check_deadline = Mock()
        ui.expect_click = Mock(side_effect=StopIteration)
        with self.assertRaises(StopIteration):
            flow.home()
        self.assertEqual(ui.clicks, ['活动关卡','活动关卡','特别','活动关卡'])

    def test_later_special_phase_borrows_phase_one_parties(self):
        flow, ui = self.exchange_runner([])
        flow.r.options = {}
        flow.r.event = SimpleNamespace(name='测试活动')
        flow.r.report = {'pending':[]}
        flow.special_complete = Mock(return_value=False)
        detail = frame(('特别难度/阶段2',260,47))
        detail.blue_button = Mock(return_value=False)
        flow.boss_detail = Mock(return_value=detail)
        flow.home = Mock()
        calls = []
        def parties(options, **kw):
            calls.append((kw['difficulty'], kw['mode']))
            return ([EventParty('sp', 'src', [], max_attempts=1)] if kw['mode'] == 1 else []), None
        with patch('pcrscript.tasks.revival_map.boss_parties', side_effect=parties):
            flow.sourced_boss('特别','special')
        self.assertEqual(calls, [('special',2),('special',1)])
        self.assertIn('特别挑战不可用，未购买或追加消费', flow.r.report['pending'])

    def test_exchange_waits_for_connection_before_reading_old_balance(self):
        connecting = self.exchange_frame(184)
        connecting.items.extend(frame(('正在进行数据连接',800,25)).items)
        flow, ui = self.exchange_runner([self.exchange_frame(184),connecting,self.exchange_frame(84,84),self.exchange_frame(0)])
        with patch('pcrscript.tasks.revival_map.time.sleep'):
            flow.exchange(already_open=True)
        self.assertEqual(ui.clicks,['100次交换','84次交换'])

    def test_memory_reading_view_turns_to_new_page_then_returns(self):
        title = ('阿尔凯斯炼金堂 业务日志', 200, 30)
        unread = frame(title, ('新内容', 915, 205), ('下页', 915, 297), ('前往一览', 905, 470))
        read = frame(title, ('上页', 45, 297), ('前往一览', 905, 470))
        flow, ui = self.exchange_runner([unread, read, frame()])
        flow.memory_title = re.escape(normalized('阿尔凯斯炼金堂 业务日志'))
        flow.dialog = Mock(return_value=False)
        flow.r.story_dialog = Mock(return_value=False)
        ui.expect_click = lambda pattern, roi, **kw: ui.clicks.append(pattern)
        with patch('pcrscript.tasks.revival_map.time.sleep'), self.assertRaises(StopIteration):
            flow.read_stories(memories=True, already_open=True)
        self.assertEqual(ui.clicks, [(915, 255), '前往一览'])

    def test_story_download_prompt_takes_voiceless_data(self):
        prompt = frame(('活动剧情一览',480,42),('即将下载新增数据。',480,200),('是否播放语音？',480,230),
                       ('无语音',370,400),('有语音',590,400))
        flow, ui = self.exchange_runner([prompt])
        flow.dialog = Mock(return_value=False)
        flow.r.story_dialog = Mock(return_value=False)
        ui.expect_click = Mock(side_effect=StopIteration)
        with self.assertRaises(StopIteration):
            flow.read_stories(already_open=True)
        ui.expect_click.assert_called_once_with('无语音', (200, 250, 760, 520), exact=True)

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
        # Any edition's boss: no recorded boss name or level is required.
        detail = frame(('BOSS详情',100,45),('合成首领',320,250),('0',909,42))
        ui = ReplayUI([detail])
        runner = SimpleNamespace(ui=ui,event=Event(0,1,'复刻',{'event_id':10171}),
            options={'hard_trial_event_id':10171},report={'pending':[]},
            state=SimpleNamespace(data={'hard_trial_started':True}))
        with self.assertRaises(EventUIError):
            RevivalMap(runner).hard_trial_from_detail()
        self.assertEqual(ui.clicks,[])
        for authorized in (10172, None):
            with self.subTest(authorized=authorized):
                ui = ReplayUI([detail])
                runner = SimpleNamespace(ui=ui,event=Event(0,1,'复刻',{'event_id':10171}),
                    options={'hard_trial_event_id':authorized},report={'pending':[]},
                    state=SimpleNamespace(data={'hard_trial_started':False}))
                flow = RevivalMap(runner)
                flow.home = Mock(return_value=detail)
                # Unauthorized: recorded as pending, the rest of the event continues.
                flow.hard_trial_from_detail()
                self.assertEqual(ui.clicks,[])
                self.assertIn('困难首领未讨伐', runner.report['pending'][0])

    def test_modal_list_with_close_button_is_not_a_map_dialogue(self):
        from pcrscript.game_ui.event_layout import map_dialogue
        from pcrscript.game_ui.screen import EventScreen, TextBox
        image = np.full((540,960,3),245,np.uint8)
        image[394:413,200:355] = (180,105,255)  # Pink nameplate (BGR).
        def labels(*items):
            return [TextBox(t,1,[[x-20,y-8],[x+20,y-8],[x+20,y+8],[x-20,y+8]]) for t,x,y in items]
        self.assertTrue(map_dialogue(EventScreen(image,labels(('是啊……',230,435)))))
        self.assertFalse(map_dialogue(EventScreen(image,labels(('活动剧情一览',480,35),('关闭',480,480)))))

    def test_stamina_shortage_cancels_auto_advance_without_refill(self):
        from pcrscript.tasks.revival_map import StaminaShort
        short = frame(('自动推进设定',480,42),('自动推进至活动关卡1-5（困难难度）时，最多消耗以下体力。',480,125),
                      ('消耗体力',300,157),('若要推进至活动关卡1-5（困难难度），必须回复体力。',480,185),
                      ('取消',260,480),('不回复直接开始',480,480),('回复',700,480))
        ui = Mock()
        ui.capture.return_value = short
        flow = RevivalMap(SimpleNamespace(ui=ui))
        with self.assertRaises(StaminaShort):
            flow.auto_advance()
        ui.expect_click.assert_called_once_with('取消',(150,450,370,520),exact=True)
        ui.click.assert_not_called()

    def test_map_stage_count_is_read_live_not_per_edition(self):
        flow = RevivalMap(SimpleNamespace(ui=ReplayUI([])))
        # Outlined labels: full-frame OCR misses 1-10, a tile re-read finds it.
        first = frame(('1-1',140,400),('1-2',335,355),('1-3',410,215))
        last = frame(('1-8',422,401),('1-9',546,284))
        flow.ui.read_region = Mock(side_effect=lambda s, roi, **kw: frame(('1-10',656,372))
                                   if s is last and roi[0] <= 656 <= roi[2] and roi[1] <= 372 <= roi[3] else frame())
        self.assertEqual(sorted(flow.stage_labels(last)),[(1,8),(1,9),(1,10)])
        self.assertEqual(flow.map_signature(flow.stage_labels(last)),((1,10),16))
        pages = iter([first, last, last])
        flow.home = Mock(side_effect=lambda: next(pages))
        flow.ui.swipe = Mock()
        seen = list(flow.scan_pages((760,250),(220,250)))
        # Stops once the labels stop moving.
        self.assertEqual(len(seen),3)
        self.assertEqual(flow.ui.swipe.call_count,2)

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

    def test_entry_label_missed_by_full_frame_is_reread(self):
        event = Event(10,20,'复刻',{'event_id':11})
        with TemporaryDirectory() as root:
            robot = SimpleNamespace(driver=Mock())
            robot.driver.get_screen_size.return_value = (960,540)
            runner = RevivalEventOnce(robot,event,{'account_key':'a','state_dir':root,'output':root})
            menu = frame(('冒险',95,28),('主线关卡',548,204),('剧情活动',410,438),('冒险',532,515))
            ui = ReplayUI([menu, menu])
            ui.read_region = Mock(return_value=frame(('复刻',322,438),('剧情活动',410,438)))
            runner.ui = ui
            with self.assertRaises(StopIteration):  # Replay ends after the entry click.
                runner.enter()
            self.assertEqual(ui.clicks, ['冒险', '复刻'])

    def test_live_layout_is_not_calendar_edition(self):
        self.assertEqual(event_layout(frame(('活动关卡·首领',140,30))), 'list')
        self.assertEqual(event_layout(frame(('讨伐证交换',830,455),('普通',760,82),('困难',890,82))), 'map')
        self.assertIsNone(event_layout(frame(('复刻',320,435))))


if __name__ == '__main__':
    unittest.main()
