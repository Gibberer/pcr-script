"""Synthetic UI/provider fixtures; no account portraits or game evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import Mock
from unittest.mock import patch

import cv2 as cv
import numpy as np

from pcrscript.game_ui.screen import EventScreen, EventUI, EventUIError, TextBox
from pcrscript.game_ui.team_battle_filter import (CAPACITY, HiddenFilter, SLOTS, TRACK,
                                                  cards, checked, restricted_cards, same_selection, selection)
from pcrscript.tasks.task_team_battle import TeamBattle, TaskDeadline
from pcrscript.tasks.event_formation import EventFormation


def label(text, x, y, score=1):
    return TextBox(text, score, [[x-30,y-8],[x+30,y-8],[x+30,y+8],[x-30,y+8]])


def face(identity, width, height):
    return np.random.default_rng(identity).integers(30, 240, (height, width, 3), dtype=np.uint8)


class FilterUI:
    """Rendered pages respond to production clicks, scrolls, and OCR crops."""
    scrollbar_bounds = staticmethod(EventUI.scrollbar_bounds)

    def __init__(self, original=(), pages=None):
        self.applied = list(original)
        self.selected = list(original)
        self.pages = pages or [[(1, True), (2, False)], [(3, True)]]
        self.page = 0
        self.modal = False
        self.inputs = []
        self.yellow = set()
        self.drop = 0
        self.late = 0
        self.frames = 0

    def capture(self, ocr=True):
        image = np.full((540,960,3), 245, np.uint8)
        if not self.modal:
            return EventScreen(image, [label('推荐编组', 480,42),label('高级',620,164)])
        items = [label('隐藏筛选',480,42),label('取消',370,479),label('显示更新',590,479)]
        # Like the game's pulsing banner: with late=n it shows on one of n+1 frames.
        pulse = self.frames % (self.late+1) == 0
        self.frames += 1
        for index, (identity, restricted) in enumerate(self.pages[self.page]):
            x, y = 90+index*102, 176
            cv.rectangle(image, (x-45,y-44), (x+45,y+44), (0,0,0), 1)
            image[y-40:y+40,x-40:x+40] = face(identity,80,80)
            # Observed game: selected cards keep the pulsing banner.
            if restricted and pulse:
                image[y+24:y+45,x-40:x+40] = 60
                items.append(label('限制实战使用',x,y+35))
            if identity in self.yellow:
                # Orange or blonde hair stays inside the card border.
                image[y-43:y-18,x+15:x+42] = (0,220,255)
            if identity in self.selected:
                # The tick's arm crosses the right border into the gap.
                image[y-46:y-24,x+20:x+54] = (0,220,255)
        for index, (x,y) in enumerate(SLOTS):
            image[y-35:y+36,x-35:x+36] = 195
            if index < len(self.selected):
                image[y-30:y+30,x-30:x+30] = face(self.selected[index],60,60)
        start = 135+round(273*self.page/max(1,len(self.pages)-1))
        image[start:start+23,560:569] = (240,160,30)
        return EventScreen(image,items)

    def expect_click(self, pattern, roi, exact=False):
        self.inputs.append(pattern)
        if pattern == '隐藏角色':
            self.selected = self.applied.copy()
            self.modal = True
        elif pattern in ('显示更新','取消'):
            if pattern == '显示更新':
                self.applied = self.selected.copy()
            self.modal = False
        else:
            raise AssertionError(pattern)

    def click(self, position):
        self.inputs.append(position)
        if self.drop:
            self.drop -= 1
            return
        if position in SLOTS:
            self.selected.pop(SLOTS.index(position))
            return
        x,y = position
        identity = self.pages[self.page][round((x-90)/102)][0]
        self.selected.append(identity)

    def wait(self, predicate, description, timeout=None):
        screen = self.capture()
        if not predicate(screen):
            raise EventUIError(description+'超时')
        return screen

    def read_region(self, screen, roi, **options):
        return screen

    def swipe(self, start, end, duration=450):
        assert start[0] == end[0] == 245
        self.page += 1 if start[1] > end[1] else -1


class HiddenFilterTests(unittest.TestCase):
    def setUp(self):
        sleep = patch('pcrscript.game_ui.team_battle_filter.time.sleep')
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_pulsing_banners_are_sampled_over_several_frames(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI(original=[9])
            # Banners are hidden on two of every three frames, including the
            # first frame read after opening and after each scroll.
            ui.late = 2
            ui.frames = 1
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            self.assertEqual(controller.apply()['added'],2)
            self.assertEqual(ui.applied,[9,1,3])

    def test_task_restores_filter_before_reopening_and_checking_selected_five(self):
        class TaskUI(FilterUI):
            def __init__(self, output, changed=False):
                super().__init__([9])
                self.output = Path(output)
                self.state = 'detail'
                self.changed = changed
                self.challenge_preferences = None

            def capture(self, ocr=True):
                if self.modal:
                    return super().capture()
                image = np.full((540,960,3),240,np.uint8)
                if self.state == 'detail':
                    return EventScreen(image,[label('魔物详情',105,42)])
                if self.state == 'formation':
                    seed = 99 if self.changed and self.challenge_preferences is not None else 50
                    for index,(x,y) in enumerate(EventFormation.slots):
                        image[415:505,x-48:x+48] = face(seed+index,96,90)
                    return EventScreen(image,[label('队伍编组',480,42)])
                for index,x in enumerate((224,312,402,491,581)):
                    image[220:268,x-22:x+22] = face(50+index,44,48)
                return EventScreen(image,[label('推荐编组',480,42),label('高级',622,165),
                    label('使用',712,277),label('保存队伍',855,226),label('70000000',120,272),
                    label('参考伤害',110,251),label('讨伐时间',86,299),label('0:19',151,299)])

            def expect_click(self, pattern, roi, exact=False):
                if pattern == '推荐编组':
                    self.state = 'list'
                elif pattern == '关闭':
                    self.state = 'detail'
                elif pattern == '取消' and not self.modal:
                    self.state = 'list'
                elif pattern == '挑战':
                    self.challenge_preferences = self.applied.copy()
                    self.state = 'formation'
                else:
                    return super().expect_click(pattern,roi,exact)

            def click(self, position):
                if isinstance(position,TextBox):
                    if position.text == '使用':
                        self.state = 'formation'
                    return
                super().click(position)

            def save(self,*a,**k):
                return self.output/'synthetic.png'

        for changed in (False,True):
            with self.subTest(changed=changed), TemporaryDirectory() as folder:
                ui = TaskUI(folder,changed)
                task = TeamBattle.__new__(TeamBattle)
                task.ui = ui
                task.formation = EventFormation.__new__(EventFormation)
                task.teams = {}
                task.spent = set()
                task.report = {'remaining_normal':2}
                task.recommendation_rows = []
                task.tried = set()
                task.tried_teams = set()
                task.check_deadline = lambda:None
                task.hidden_filter = HiddenFilter(ui,Path(folder)/'hidden.json')
                with patch('pcrscript.tasks.task_team_battle.time.sleep'):
                    if changed:
                        with self.assertRaisesRegex(EventUIError,'五人队伍改变'):
                            task.recommendation(boss_hp=70_000_000)
                    else:
                        self.assertEqual(task.recommendation(boss_hp=70_000_000),'team-1')
                self.assertEqual(ui.challenge_preferences,[9])
                self.assertEqual(ui.applied,[9])
                self.assertFalse(task.hidden_filter.journal())

    def test_apply_scroll_and_restore_original_preferences(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI(original=[9])
            controller = HiddenFilter(ui, Path(folder)/'filter.json')
            result = controller.apply()
            self.assertEqual(result, dict(original=1,added=2,capacity_limited=False,scanned_to_end=True))
            self.assertEqual(ui.applied,[9,1,3])
            self.assertTrue(controller.journal())
            controller.restore()
            self.assertEqual(ui.applied,[9])
            self.assertFalse(controller.journal())

    def test_existing_checked_role_is_not_toggled_off_and_return_to_top(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI(original=[1])
            ui.page = 1
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            result = controller.apply()
            self.assertEqual(result['added'],1)
            self.assertEqual(ui.applied,[1,3])
            controller.restore()
            self.assertEqual(ui.applied,[1])

    def test_capacity_reports_incomplete_search_and_preserves_original(self):
        with TemporaryDirectory() as folder:
            original = list(range(20,20+CAPACITY-1))
            ui = FilterUI(original)
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            result = controller.apply()
            self.assertTrue(result['capacity_limited'])
            self.assertFalse(result['scanned_to_end'])
            self.assertEqual(result['added'],1)
            self.assertEqual(ui.applied,original+[1])
            controller.restore()
            self.assertEqual(ui.applied,original)
            # From the end, overflow hides the last restricted role instead.
            result = controller.apply(from_end=True)
            self.assertTrue(result['capacity_limited'])
            self.assertEqual(ui.applied,original+[3])
            controller.restore()
            self.assertEqual(ui.applied,original)

    def test_overflowing_restrictions_try_second_subset_before_stopping(self):
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock()
        task.spent = {'team-1'}
        task.report = {}
        task.save_report = Mock()
        task.hidden_filter = Mock()
        task.hidden_filter.apply.side_effect = lambda from_end=False: dict(
            added=10, capacity_limited=True, scanned_to_end=False)
        task._recommendation = Mock(side_effect=[None, 'team-2'])
        task.open_formation = Mock(return_value=object())
        task.team = Mock(return_value='team-2')
        self.assertEqual(task.filtered_recommendation(boss_hp=70_000_000), 'team-2')
        self.assertEqual([call.kwargs for call in task.hidden_filter.apply.call_args_list],
                         [{'from_end': False}, {'from_end': True}])
        self.assertEqual(task.hidden_filter.restore.call_count, 2)
        task._recommendation = Mock(return_value=None)
        task.hidden_filter.reset_mock()
        with self.assertRaisesRegex(TaskDeadline,'前后两组筛选'):
            task.filtered_recommendation(boss_hp=70_000_000)
        self.assertEqual(task.hidden_filter.restore.call_count, 2)

    def test_interrupted_click_before_reply_is_recoverable_on_next_instance(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI(original=[9])
            path = Path(folder)/'filter.json'
            original_click = ui.click
            def interrupt(position):
                original_click(position)
                # Model a process stopping after applying a selection update.
                ui.applied = ui.selected.copy()
                raise RuntimeError('interrupted')
            ui.click = interrupt
            with self.assertRaisesRegex(RuntimeError,'interrupted'):
                HiddenFilter(ui,path).apply()
            ui.click = original_click
            ui.modal = False
            HiddenFilter(ui,path).restore()
            self.assertEqual(ui.applied,[9])

    def test_external_preference_change_is_not_overwritten(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI(original=[9])
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            controller.apply()
            ui.applied[0] = 8
            with self.assertRaisesRegex(EventUIError,'外部修改'):
                controller.restore()
            self.assertTrue(controller.journal())
            self.assertEqual(ui.applied[0],8)

    def test_no_restricted_roles_requires_confirmed_bottom_and_restores(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI(pages=[[(1,False)],[(2,False)]])
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            result = controller.apply()
            self.assertEqual(result['added'],0)
            self.assertTrue(result['scanned_to_end'])
            controller.restore()
            self.assertEqual(ui.applied,[])

    def test_yellow_corner_on_unselected_restricted_card_is_still_hidden(self):
        # Orange or blonde hair occupies the tick corner; the banner decides.
        with TemporaryDirectory() as folder:
            ui = FilterUI()
            ui.yellow = {1, 3}
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            self.assertEqual(controller.apply()['added'],2)
            self.assertEqual(ui.applied,[1,3])

    def test_dropped_taps_are_repeated_only_after_unchanged_frame(self):
        with TemporaryDirectory() as folder, patch.object(FilterUI,'wait',autospec=True) as wait:
            def single_frame(ui, predicate, description, timeout=None):
                screen = ui.capture()
                if not predicate(screen):
                    raise EventUIError(description+'超时')
                return screen
            wait.side_effect = single_frame
            ui = FilterUI(original=[9])
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            ui.drop = 1
            self.assertEqual(controller.apply()['added'],2)
            self.assertEqual(ui.applied,[9,1,3])
            # Card 1 twice (dropped then accepted), card 3 once on the next page.
            self.assertEqual(ui.inputs.count((90,176)),3)
            ui.drop = 1
            controller.restore()
            self.assertEqual(ui.applied,[9])
            self.assertFalse(controller.journal())
            # Three dropped taps keep the journal for the next run.
            controller.apply()
            ui.drop = 3
            with self.assertRaisesRegex(EventUIError,'移除临时隐藏角色'):
                controller.restore()
            self.assertTrue(controller.journal())

    def test_bad_journal_does_not_silently_skip_recovery(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'filter.json'
            for data in ('{','[]',json.dumps({'version':1,'original':[[999]*1728],'maximum':1})):
                path.write_text(data,encoding='utf-8')
                with self.assertRaises(EventUIError):
                    HiddenFilter(FilterUI(),path).journal()

    def test_grid_detection_ignores_partial_cards_and_selection_gaps(self):
        ui = FilterUI([1])
        ui.modal = True
        ui.yellow = {2}
        screen = ui.capture()
        # As in the game, the tick breaks the selected card's border.
        self.assertEqual(cards(screen),[(192,176)])
        self.assertTrue(checked(screen,90,176))
        self.assertFalse(checked(screen,192,176))
        x,y = SLOTS[2]
        screen.image[y-30:y+30,x-30:x+30] = face(3,60,60)
        with self.assertRaisesRegex(EventUIError,'不连续'):
            selection(screen)

    def test_packed_banners_recover_missed_text_with_one_engine_call(self):
        ui = FilterUI()
        ui.modal = True
        screen = ui.capture()
        # Simulate merged/missed full-frame OCR. Local provider sees the packed
        # strips, including a low-confidence false badge on the second card.
        screen.items = []
        provider = Mock()
        provider.read_region.return_value = EventScreen(np.zeros((66,88,3),np.uint8),
            [label('限制实战使用',44,12,.99),label('限制实战使用',44,45,.7)])
        self.assertEqual(restricted_cards(provider,screen,[(90,176),(192,176)]),[(90,176)])
        provider.read_region.assert_called_once()
        # One misread glyph still marks the card; the not-owned badge never does.
        provider.read_region.return_value = EventScreen(np.zeros((66,88,3),np.uint8),
            [label('限初实战使用',44,12,.93),label('未持有',44,45,.99)])
        self.assertEqual(restricted_cards(provider,screen,[(90,176),(192,176)]),[(90,176)])
        packed, roi = provider.read_region.call_args.args
        self.assertEqual(roi,(0,0,88,66))
        np.testing.assert_array_equal(packed.image[:25],screen.image[198:223,46:134])

    def test_selected_white_or_gray_portrait_is_preserved_as_occupied(self):
        ui = FilterUI()
        ui.modal = True
        screen = ui.capture()
        x,y = SLOTS[0]
        gray = np.random.default_rng(44).integers(50,240,(60,60,1),dtype=np.uint8)
        screen.image[y-30:y+30,x-30:x+30] = np.repeat(gray,3,axis=2)
        self.assertEqual(len(selection(screen)),1)

    def test_stuck_scroll_is_an_error_instead_of_candidate_exhaustion(self):
        with TemporaryDirectory() as folder:
            ui = FilterUI()
            ui.swipe = lambda *a,**k:None
            controller = HiddenFilter(ui,Path(folder)/'filter.json')
            with self.assertRaisesRegex(EventUIError,'滚动'):
                controller.apply()
            self.assertTrue(controller.journal())
            controller.close(False)
            controller.restore()
            self.assertEqual(ui.applied,[])

    def test_stage_scope_blocks_high_and_unknown_before_mode_change(self):
        task = TeamBattle.__new__(TeamBattle)
        task.ui = Mock(read_region=Mock(side_effect=lambda s,*a,**k:s))
        for stage in ('第1阶段','第2阶段','第3阶段','A阶段','阶段C'):
            task.require_low_stage(EventScreen(np.zeros((540,960,3),np.uint8),[label(stage,85,130)]))
        for stage in ('第4阶段','第10阶段','D阶段','阶段E','未知'):
            with self.assertRaises(TaskDeadline):
                task.require_low_stage(EventScreen(np.zeros((540,960,3),np.uint8),[label(stage,85,130)]))


if __name__ == '__main__':
    unittest.main()
