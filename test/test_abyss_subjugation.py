"""Synthetic UI/game boundaries; no account data, screenshots or network."""
from datetime import datetime, timedelta
from dataclasses import asdict
from contextlib import closing
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from pcrscript import Robot
from pcrscript.constants import SERVER_TIMEZONE
from pcrscript.game_ui import abyss_subjugation as field
from pcrscript.game_ui.screen import EventUIError, TextBox
from pcrscript.tasks import AbyssSubjugation, Event, EventNews
from pcrscript.tasks.event_battle import BattleResult
from pcrscript.tasks.event_strategy import CharacterStatus, EventParty, MemberRequirement
from pcrscript.tasks.subjugation_party import character_talents, require_event_talent
from pcrscript.tasks.party_preparation import party_fingerprint
from pcrscript.tasks.task_abyss_subjugation import validate_options, BossPartyUnavailable
from pcrscript.runtime import modify_task_list, run_task_with_config
from functools import partial
from ui_fixtures import screen as synthetic_screen

START = datetime(2026, 10, 2, 12, tzinfo=SERVER_TIMEZONE)
NOW = START+timedelta(hours=1)
EVENT = Event(START.timestamp(), datetime(2026, 10, 7, 4, 59, 59, tzinfo=SERVER_TIMEZONE).timestamp(),
              '深渊讨伐战', dict(abyss_id=1, boss_ticket_id=70001, talent_id=2, title='合成深渊'))

screen = partial(synthetic_screen, box_half_size=(24, 8), button_half_size=(50, 22))

def party():
    return EventParty('synthetic', '合成游戏保存队伍',
        [MemberRequirement('合成角色'+str(i), 100, 10, 5, True, False, True, 100) for i in range(5)],
        build_basis='local_trial', allow_deaths=5)


class BossSignatureTests(TestCase):
    def test_long_boss_name_keeps_adjacent_level_in_the_info_row(self):
        s=screen(('合成首领(多部位)',440,233),('等级.100',560,233),('弱点',630,233))
        ui=Mock()
        ui.read_region.return_value=screen()
        with patch.object(field,'boss_detail',return_value=True), \
             patch.object(field,'boss_health',return_value=(43747169,80000000)):
            self.assertEqual(field.boss_signature(ui,s),dict(
                boss='合成首领(多部位)',level=100,maximum_hp=80000000))
            s.items[1].score=.94
            self.assertIsNone(field.boss_signature(ui,s))
            ui.read_region.return_value=screen(('合成首领(多部位)等级.100',440,233))
            self.assertEqual(field.boss_signature(ui,s)['boss'],'合成首领(多部位)')

    def test_uncertain_level_label_needs_independent_matching_numeric_read(self):
        s=screen(('合成首领',440,233),('等级.100',495,233),('弱点',590,233))
        s.items[1].score=.92
        ui=Mock(number=Mock(return_value=100),read_region=Mock(return_value=screen()))
        with patch.object(field,'boss_detail',return_value=True), \
             patch.object(field,'boss_health',return_value=(43747169,80000000)):
            self.assertEqual(field.boss_signature(ui,s)['level'],100)
            for wrong in (None,90):
                ui.number.return_value=wrong
                self.assertIsNone(field.boss_signature(ui,s))

class Game:
    def __init__(self):
        self.page = 'adventure'
        self.kind, self.difficulty, self.index = 'outpost', '普通', 0
        self.mode = 'real'
        self.quantity = 1
        self.stamina = 1000
        self.tickets = 0
        self.attempts = {d: 4 for d in field.DIFFICULTIES}
        self.outpost_clears = set()
        self.boss_clears = set()
        self.normal_commits = 0
        self.real_battles = 0
        self.sweeps = []
        self.clicks = []
        self.simulation_wins = True
        self.simulation_damage = 0
        self.simulation_deaths = 0
        self.simulation_end = 1
        self.allowed_deaths = []
        self.real_damage = None
        self.health = {}
        self.damage_records = {}
        self.outpost_wins = True
        self.lose_receipt = False
        self.corrupt_counter = False
        self.confirmation_cost_delta = 0
        self.entry_loading_frames = 0
        self.selector_scroll = 0
        self.task = None

    def capture(self, **kwargs):
        if self.lose_receipt and self.page == 'receipt':
            self.lose_receipt = False
            self.page = 'home'
            raise EventUIError('合成截图连接中断')
        if self.page == 'adventure':
            if self.entry_loading_frames:
                self.entry_loading_frames -= 1
                return screen(('冒险', 100, 30))
            return screen(('冒险', 100, 30), ('深渊讨伐战', 600, 300))
        if self.page == 'home':
            return screen(('深渊讨伐战', 135, 30), ('合成深渊', 100, 70),
                ('举办时间:10/0212:00～10/0704:59', 156, 101), ('前哨关卡', 153, 138),
                ('讨伐委托证', 770, 405), (str(self.tickets), 850, 405),
                ('体力', 680, 24), (str(self.stamina)+'/413', 742, 24),
                *[(d, 154, y) for d, y in zip(field.DIFFICULTIES, field.OUTPOST_Y)],
                *[(str(self.attempts[d])+'/4', 222, y+26) for d, y in zip(field.DIFFICULTIES, field.OUTPOST_Y)],
                *[('首领', x, 340) for x in (440, 627, 803)])
        if self.page == 'normal':
            q = '使用'+str(self.quantity)+'张'
            return screen(('前哨关卡', 110, 52), (self.difficulty, 255, 52),
                ('剩余挑战次数', 397, 459), (str(self.attempts[self.difficulty])+'/4', 555, 459),
                (str(self.stamina), 190, 459), (str(self.stamina-self.quantity*25), 300, 459),
                (q, 756, 377), ('取消', 668, 459), ('挑战', 840, 459),
                blue=(('挑战',) if self.attempts[self.difficulty] else ())
                     +((q,) if self.difficulty in self.outpost_clears and self.attempts[self.difficulty] else ()))
        if self.page == 'selector':
            names = ('极难', *field.DIFFICULTIES) if (self.index, '高难') in self.boss_clears else field.DIFFICULTIES
            rows = [(d, 109+i*99-self.selector_scroll*90) for i, d in enumerate(names)]
            rows = [(d, y) for d, y in rows if 75 <= y <= 399]
            locked = [(d, y) for d, y in rows if d != '普通'
                      and (self.index, field.BOSS_DIFFICULTIES[field.BOSS_DIFFICULTIES.index(d)-1]) not in self.boss_clears]
            return screen(('首领难度选择', 480, 42), ('关闭', 480, 480),
                *[(d, 476, y) for d, y in rows],
                *[('通关', 306, y-30) for d, y in rows if (self.index, d) in self.boss_clears],
                ('讨伐委托证', 333, 430), (str(self.tickets), 683, 430),
                yellow=[(260, y-38, 299, y+5) for _, y in locked])
        if self.page == 'boss':
            q = '使用'+str(self.quantity)+'张'
            cleared = (self.index, self.difficulty) in self.boss_clears
            return screen(('BOSS详情', 109, 52), (self.difficulty, 217, 52),
                ('模拟战', 748, 109), ('实战', 866, 109),
                ('现在的设定为模拟战。', 760, 375) if self.mode == 'simulation' else ('跳过伤害', 644, 333),
                ('合成首领'+str(self.index)+'等级.100', 398, 237),
                (str(self.health.get((self.index, self.difficulty), 80000000))+'/80000000', 610, 274),
                ('讨伐委托证张数', 670, 426), (str(self.tickets), 850, 426),
                (str(self.damage_records.get((self.index, self.difficulty), 80000000)) if cleared or (self.index, self.difficulty) in self.damage_records else '-', 875, 333),
                ('券', 627, 310), ('200', 802, 310),
                *((q, 756, 377),) if self.mode == 'real' else (),
                ('取消', 668, 469), ('挑战', 840, 469),
                blue=(('挑战',) if self.tickets or self.mode == 'simulation' else ())
                     +((q,) if cleared and self.mode == 'real' and self.tickets else ()),
                yellow=[(831, 94, 904, 118)] if self.mode == 'real' else [(711, 94, 785, 118)])
        if self.page == 'formation':
            return screen(('队伍编组', 480, 42), ('当前的成员', 110, 390),
                          ('取消', 715, 455), ('战斗开始', 855, 455), blue=('战斗开始',))
        if self.page in ('special', 'special_auto'):
            return screen(('自动特别装备设定' if self.page == 'special_auto' else '特别装备设定', 480, 42),
                          ('取消', 370 if self.page == 'special_auto' else 145, 479))
        if self.page == 'confirmation':
            cost_label = '消耗体力' if self.kind == 'outpost' else '消耗讨伐委托证'
            cost = self.quantity*25 if self.kind == 'outpost' else self.quantity
            return screen(('扫荡券确认', 480, 147), (cost_label, 300, 281),
                          (str(cost+self.confirmation_cost_delta), 466, 281), ('消耗券', 300, 307),
                          (str(self.quantity), 470, 307), ('取消', 370, 370), ('确认', 590, 370), blue=('确认',))
        if self.page == 'limited_shop':
            return screen(('限定商店', 480, 40), ('取消', 590, 475), ('一键购买', 800, 475))
        if self.page == 'failure':
            return screen(('战斗失败', 480, 42), ('前往深渊讨伐战', 810, 495))
        if self.page == 'receipt':
            return screen(('扫荡结果', 480, 42), ('关闭', 480, 480))
        raise AssertionError(self.page)

    def click(self, target, **kwargs):
        x, y = target.center if isinstance(target, TextBox) else target
        text = target.text if isinstance(target, TextBox) else ''
        self.clicks.append((self.page, text, x, y))
        if self.page == 'adventure':
            self.page = 'home'
        elif self.page == 'home':
            if text in field.DIFFICULTIES:
                self.kind, self.difficulty, self.page = 'outpost', text, 'normal'
                self.quantity = self.attempts[text] if text in self.outpost_clears else 1
            elif text == '首领':
                self.index = min(range(3), key=lambda i: abs((440, 627, 803)[i]-x))
                self.kind, self.page = 'boss', 'selector'
                self.selector_scroll = 0
        elif self.page == 'selector':
            if text == '关闭':
                self.page = 'home'
            elif text in field.BOSS_DIFFICULTIES:
                self.difficulty, self.page, self.quantity = text, 'boss', 1
        elif self.page in ('normal', 'boss'):
            if text == '取消':
                self.page = 'home'
            elif text in ('模拟战', '实战'):
                self.mode = 'simulation' if text == '模拟战' else 'real'
            elif text == '挑战':
                self.page = 'formation'
            elif text.startswith('使用'):
                self.page = 'confirmation'
            elif x in (831, 880):
                self.quantity += 1
            elif x in (676, 630):
                self.quantity -= 1
        elif self.page == 'formation':
            if text == '取消':
                self.page = 'normal' if self.kind == 'outpost' else 'boss'
            elif text == '战斗开始':
                self.page = 'battle'
        elif self.page in ('special', 'special_auto'):
            if text != '取消':
                raise AssertionError('Uncommitted equipment must only be cancelled')
            self.page = 'special' if self.page == 'special_auto' else 'formation'
        elif self.page == 'confirmation':
            if text == '取消':
                self.page = 'normal' if self.kind == 'outpost' else 'boss'
            else:
                plan = self.task.state['pending']
                if self.kind == 'outpost':
                    self.normal_commits += 1
                    if not self.corrupt_counter:
                        self.attempts[self.difficulty] -= self.quantity
                    self.stamina -= plan['stamina_cost']
                    self.tickets += self.quantity
                else:
                    self.tickets -= self.quantity
                self.sweeps.append((self.kind, self.index, self.difficulty, self.quantity))
                self.page = 'receipt'
        elif self.page == 'receipt':
            self.page = 'home'
        elif self.page == 'limited_shop':
            if text != '取消':
                raise AssertionError('limited shop must only be dismissed')
            self.page = 'home'
        elif self.page == 'failure':
            self.page = 'home'

    def combat(self, selected, order):
        self.assert_party(selected, order)
        self.allowed_deaths.append(selected.allow_deaths)
        if self.page != 'formation':
            raise AssertionError('shared combat must own the single start click')
        self.click(self.capture().find('战斗开始'))
        if self.kind == 'outpost':
            won = self.outpost_wins
            if won:
                self.normal_commits += 1
                self.attempts[self.difficulty] -= 1
                self.stamina -= 25
                self.tickets += 1
                self.outpost_clears.add(self.difficulty)
        elif self.mode == 'simulation':
            won = self.simulation_wins
            self.task._battle_samples = [dict(seconds=self.simulation_end+i,
                hp=80000000-self.simulation_damage, max_hp=80000000,
                dark_portraits=self.simulation_deaths,
                living_portraits=5-self.simulation_deaths) for i in (4, 2, 0)]
        else:
            self.real_battles += 1
            self.tickets -= 1
            key = (self.index, self.difficulty)
            damage = self.real_damage if self.real_damage is not None else 80000000
            remaining = self.health.get(key, 80000000)-damage
            if damage > 0:
                self.damage_records[key] = max(damage, self.damage_records.get(key, 0))
            won = remaining <= 0
            if won:
                self.boss_clears.add(key)
                self.health.pop(key, None)
            else:
                self.health[key] = remaining
        if self.kind == 'boss' and self.mode == 'simulation' and self.simulation_damage:
            self.task.combat_result_button(screen(('伤害合计', 100, 20),
                (str(self.simulation_damage), 140, 55), ('TIMEUP', 480, 100), ('下一步', 840, 470)))
        else:
            self.task.combat_result_button(screen(('WIN' if won else '战斗失败', 480, 100), ('下一步', 840, 470)))
        self.page = 'home'
        return BattleResult('failed' if self.kind == 'outpost' and not won else 'settled')

    def scroll_selector(self, screen, roi, direction):
        if self.page != 'selector' or (self.index, '高难') not in self.boss_clears:
            return False
        wanted = 0 if direction < 0 else 1
        changed = wanted != self.selector_scroll
        self.selector_scroll = wanted
        return changed

    def assert_party(self, selected, order):
        if selected.name != 'synthetic' or len(set(order)) != 5 or set(order) != {m.name for m in selected.members}:
            raise AssertionError('wrong synthetic party')

class SubjugationTests(TestCase):
    def test_single_sweep_cost_recovers_only_one_high_confidence_glyph(self):
        for extra_glyph, confidence, expected in ((False, .99, 1), (False, .90, None), (True, .99, None)):
            with self.subTest(extra_glyph=extra_glyph, confidence=confidence):
                observed = screen(('消耗券', 300, 307))
                cv.rectangle(observed.image, (470, 302), (473, 312), (60, 60, 60), -1)
                if extra_glyph:
                    cv.rectangle(observed.image, (452, 302), (456, 312), (60, 60, 60), -1)
                local = screen(('1', 471, 307))
                local.items[0].score = confidence
                ui = Mock(number=Mock(return_value=None), read_region=Mock(return_value=local))
                self.assertEqual(field.sweep_cost(ui, observed, '消耗券'), expected)
                if extra_glyph:
                    ui.read_region.assert_not_called()

    def test_one_remaining_outpost_sweeps_after_thin_digit_recovery(self):
        game = Game()
        game.attempts = dict(普通=1, 困难=0, 高难=0)
        game.outpost_clears.update(field.DIFFICULTIES)
        original = game.capture
        def capture(**kwargs):
            observed = original(**kwargs)
            if game.page == 'confirmation':
                observed.items = [t for t in observed.items if tuple(t.center) != (470, 307)]
                cv.rectangle(observed.image, (470, 302), (473, 312), (60, 60, 60), -1)
            return observed
        game.capture = capture
        task = self.task(game, first_clear=False)
        task.ui.read_region = Mock(side_effect=lambda s, roi, **kwargs:
            screen(('1', 471, 307)) if roi == (452, 295, 479, 319) else s)
        report = task.run(EVENT)
        self.assertEqual(report['stamina_spent'], 25, report)
        self.assertEqual(game.attempts['普通'], 0)
        self.assertEqual(game.tickets, 1)
        self.assertEqual(len(report['history']), 1)
        self.assertIn((452, 295, 479, 319), [call.args[1] for call in task.ui.read_region.call_args_list])

    def test_navigation_cancel_requires_detail_controls_without_overlay(self):
        game = Game()
        for page in ('normal', 'boss'):
            with self.subTest(page=page):
                game.page = page
                observed = game.capture()
                self.assertEqual(field.detail_cancel(observed).text, '取消')
                observed.items.extend(screen(('确认', 588, 373)).items)
                self.assertIsNone(field.detail_cancel(observed))

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch('pcrscript.tasks.task_abyss_subjugation.time.time', return_value=NOW.timestamp()).start()
        patch('pcrscript.tasks.task_abyss_subjugation.time.sleep').start()

    def task(self, game, **options):
        robot = Robot(Mock(get_screen_size=Mock(return_value=(960, 540))), show_progress=False)
        options.setdefault('auto_collect_house_stamina', False)
        options.setdefault('discover_sources', False)
        robot.configure({'AbyssSubjugation': dict(output=str(self.root/'output'), state_dir=str(self.root/'state'),
                          account_key='synthetic', **options)})
        task = AbyssSubjugation(robot)
        task.avatars_ready = True
        task.event = EVENT
        task.character_talents = {'合成角色'+str(i): 2 for i in range(5)}
        game.task = task
        task.ui.capture = game.capture
        task.ui.click = game.click
        task.ui.swipe = lambda *args: None
        task.ui.scrollbar = game.scroll_selector
        task.ui.number = lambda s, roi: s.number(roi)
        task.ui.read_region = lambda s, roi, **kwargs: s
        task.ui.save = lambda name, s=None: self.root/(name+'.png')
        task.source_parties = Mock(side_effect=lambda *args, **kwargs: [party()])
        task.formation.owned_candidates = Mock(return_value=[m.name for m in party().members])
        task.prepare_party = Mock(return_value={'slots': [[True]*3 for _ in range(5)], 'empty': 0, 'unknown': 0})
        task.formation.select = Mock(side_effect=lambda selected: (True, dict(order=[m.name for m in selected.members])))
        task.combat.run = game.combat
        patch('pcrscript.tasks.task_abyss_subjugation.guide_party',
              side_effect=lambda task, seed, reopen, **kwargs: (seed, [m.name for m in seed.members])).start()
        return task

    def referenced_task(self, game, damage=40000000, **options):
        options.setdefault('boss_max_attacks', dict.fromkeys(field.BOSS_DIFFICULTIES, 2))
        task = self.task(game, **options)
        def sources(kind, boss='', boss_number=None, **kwargs):
            if kind != 'boss':
                return []
            seed = party()
            seed.damage_reference = dict(damage=damage, scope=dict(kind='boss', boss=boss, difficulty='极难'),
                evidence=[dict(source='https://example.com/synthetic', method='part_title', text='合成参考伤害')])
            return [seed]
        task.source_parties = sources
        patch('pcrscript.tasks.task_abyss_subjugation.guide_party',
              side_effect=lambda task, seed, reopen, **kwargs: (seed, [m.name for m in seed.members])).start()
        return task

    def test_first_run_clears_one_team_and_sweeps_all_outposts_then_bosses(self):
        game = Game()
        game.tickets = 3
        task = self.task(game)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.normal_commits, 6)  # one first-clear + one remaining sweep per difficulty
        self.assertEqual(game.attempts, dict.fromkeys(field.DIFFICULTIES, 0))
        self.assertEqual(report['stamina_spent'], 300)
        self.assertEqual(game.real_battles, 12)
        self.assertEqual([(h['difficulty'], h['index']) for h in report['history'] if h['kind'] == 'boss_battle'],
                         [(d, i) for d in field.BOSS_DIFFICULTIES for i in range(3)])
        self.assertEqual(game.tickets, 0)
        self.assertEqual(game.sweeps[-1], ('boss', 0, '极难', 3))
        self.assertEqual(set(report['outpost_parties']), set(field.DIFFICULTIES))
        self.assertEqual(task.source_parties.call_count, 15)
        self.assertNotIn('pending', task.state)

    def test_resume_cancels_equipment_settings_and_preview_without_committing(self):
        for page in ('special_auto', 'special'):
            with self.subTest(page=page):
                game = Game()
                game.page = page
                task = self.task(game, preview_only=True)
                report = task.run(EVENT)
                self.assertEqual(report['status'], 'preview', report['pending'])
                self.assertEqual(game.page, 'home')
                self.assertEqual(game.normal_commits+game.real_battles, 0)
                equipment_clicks = [c for c in game.clicks if c[0] in ('special_auto', 'special')]
                self.assertEqual([c[1] for c in equipment_clicks], ['取消']*(2 if page == 'special_auto' else 1))

    def test_second_run_targets_remaining_first_clears_before_sweeping(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in range(2) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.real_battles, 4)
        self.assertTrue(all(h['index'] == 2 for h in report['history'] if h['kind'] == 'boss_battle'))
        self.assertEqual(game.sweeps[-1], ('boss', 0, '极难', 8))
        for index in range(3):
            observed = task.source_targets[('boss', '普通', '合成首领'+str(index))]
            self.assertEqual(observed['scope']['difficulty'], '普通')
            self.assertEqual(observed['maximum_hp'], 80000000)
            self.assertTrue(observed['image'])

    def test_adventure_header_before_activity_entry_does_not_imply_unavailable(self):
        game = Game()
        game.entry_loading_frames = 3
        report = self.task(game, preview_only=True).run(EVENT)
        self.assertEqual(report['status'], 'preview', report['pending'])
        self.assertEqual(game.normal_commits+game.real_battles, 0)

        game.page = 'home'
        ready = game.capture()
        task = self.task(game)
        loading = screen(('冒险', 540, 526))
        entry = screen(('冒险', 100, 30), ('深渊讨伐战', 600, 300), ('冒险', 540, 526))
        task.ui.capture = Mock(side_effect=[loading, loading, entry, loading, loading, ready])
        task.ui.click = Mock()
        self.assertIs(task.enter(), ready)
        self.assertEqual(task.ui.click.call_count, 2)

    def test_cancel_waits_for_the_detail_to_close_without_repeating_the_tap(self):
        game = Game()
        game.page = 'boss'
        detail = game.capture()
        fading = game.capture()
        fading.find('取消').score = .8
        game.page = 'home'
        ready = game.capture()
        task = self.task(game)
        task.ui.capture = Mock(side_effect=[detail, fading, ready, ready])
        task.ui.click = Mock()
        self.assertIs(task.enter(), ready)
        task.ui.click.assert_called_once()
        self.assertEqual(task.ui.click.call_args.args[0].text, '取消')

    def test_daily_entry_leaves_expedition_or_maze_before_subjugation(self):
        from dawn_labyrinth_fixtures import catalogue, guild, home
        expedition = screen(('探险',90,30),('菜单',852,53),
                            ('冒险目的地',95,451),('冒险',538,526))
        maze_home = home()
        maze_home.items.extend(screen(('冒险',538,526)).items)
        for pages, expected in (([expedition], ['冒险']),
                                ([catalogue(),guild(),maze_home], ['取消',(30,30),'冒险'])):
            with self.subTest(start=pages[0].text()):
                game = Game()
                game.page = 'home'
                ready = game.capture()
                task = self.task(game)
                task.ui.capture = Mock(side_effect=[*pages,
                    screen(('冒险',100,30),('深渊讨伐战',600,300)), ready])
                task.ui.click = Mock()
                self.assertIs(task.enter(), ready)
                self.assertEqual([getattr(c.args[0],'text',c.args[0]) for c in task.ui.click.call_args_list],
                                 [*expected,'深渊讨伐战'])

    def test_blue_challenge_with_negative_preview_collects_existing_stamina_then_finishes(self):
        game = Game()
        game.stamina = 25
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game, auto_collect_house_stamina=True)
        def collect(ui, before):
            previous = game.stamina
            game.stamina += 300
            game.page = 'home'
            return dict(before=previous, after=game.stamina, received=300)
        with patch('pcrscript.game_ui.guild_house.collect_produced_stamina', side_effect=collect) as house:
            report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        house.assert_called_once()
        self.assertEqual(report['house_stamina']['before'], 0)
        self.assertEqual(report['stamina_spent'], 300)
        self.assertEqual(game.stamina, 25)
        self.assertEqual(game.real_battles, 0)
        self.assertNotIn('normal_party', task.state)

    def test_blue_challenge_without_enough_stamina_never_starts_battle(self):
        game = Game()
        game.stamina = 20
        report = self.task(game).run(EVENT)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(game.normal_commits+game.real_battles, 0)
        self.assertEqual(game.stamina, 20)
        self.assertIn('现有体力不足', ' '.join(report['pending']))

    def test_ticket_preview_requires_merged_preview_box_and_unambiguous_arithmetic(self):
        game = Game()
        game.page = 'boss'
        game.tickets = 10
        s = game.capture()
        ui = Mock(number=lambda s, roi: s.number(roi))
        self.assertEqual(field.tickets(ui, s), 10)
        s.items = [i for i in s.items if i.text != '10']
        s.items.append(TextBox('54', .999, [[843, 416], [920, 416], [920, 436], [843, 436]]))
        self.assertEqual(field.tickets(ui, s), 5)
        self.assertEqual(field.preview_balance('100', 1), None)
        self.assertEqual(field.preview_balance('10→9', 1), 10)

    def test_damage_record_before_first_kill_does_not_imply_clear(self):
        game = Game()
        game.page, game.tickets = 'boss', 7
        game.damage_records[(0, '普通')] = 33000000
        game.health[(0, '普通')] = 47000000
        task = self.task(game)
        self.assertFalse(field.cleared_boss(task.ui, game.capture()))
        task.event = EVENT
        self.assertFalse(task.boss_cleared(game.capture(), 0, '普通'))
        self.assertNotIn('boss_clears', task.state)

    def test_dark_blue_disabled_boss_sweep_cannot_authorize_a_clear(self):
        game = Game()
        game.page, game.tickets = 'boss', 7
        game.damage_records[(0, '普通')] = 33000000
        game.health[(0, '普通')] = 47000000
        task = self.task(game)
        detail = game.capture()
        cv.rectangle(detail.image, (680, 350), (842, 403), (190, 123, 65), -1)
        self.assertTrue(detail.blue_button(field.sweep_button(detail)))
        self.assertFalse(field.sweep_enabled(detail))
        self.assertFalse(field.cleared_boss(task.ui, detail))
        cv.rectangle(detail.image, (680, 350), (842, 403), (230, 155, 25), -1)
        self.assertTrue(field.sweep_enabled(detail))

    def test_legacy_clear_hint_is_rebuilt_from_live_progress_before_using_a_ticket(self):
        game = Game()
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(0, '普通'), (0, '困难')} | {(i, d) for i in (1, 2) for d in field.DIFFICULTIES}
        game.health[(0, '高难')] = 47000000
        game.damage_records[(0, '高难')] = 33000000
        game.tickets = 1
        task = self.task(game)
        key = sha256(('synthetic|'+str(EVENT.extras['abyss_id'])).encode()).hexdigest()[:24]
        state_path = Path(task.options['state_dir'])/(key+'.json')
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(dict(boss_clears={'0:高难':dict(name='合成首领0',maximum=80000000)})), encoding='utf-8')
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.real_battles, 1)
        self.assertTrue(report['bosses']['0:高难']['cleared'])
        self.assertEqual(task.state['clear_proof_version'], 1)

    def test_new_boss_tier_waits_for_the_previous_detail_to_finish_loading(self):
        game = Game()
        game.boss_clears = {(0, '普通')}
        task = self.task(game)
        task.event = EVENT
        capture = game.capture
        stale = [2]
        def loading(**kwargs):
            value = capture(**kwargs)
            if game.page == 'boss' and game.difficulty == '困难' and stale[0]:
                stale[0] -= 1
                for item in value.items:
                    if item.text == '困难':
                        item.text = '普通'
            return value
        task.ui.capture = loading
        detail = task.boss_detail(0, '困难')
        self.assertEqual(field.difficulty(detail), '困难')
        self.assertEqual(stale[0], 0)
        self.assertEqual(game.real_battles, 0)

    def test_high_clear_reorders_selector_and_requires_scroll_to_its_original_row(self):
        game = Game()
        game.boss_clears = {(0, d) for d in field.DIFFICULTIES}
        game.page = 'selector'
        task = self.task(game)
        initial = game.capture()
        self.assertTrue(field.boss_selector(initial))
        self.assertEqual(field.selector_difficulty(initial, '极难').center[1], 109)
        self.assertIsNone(field.selector_difficulty(initial, '高难'))
        detail = task.boss_detail(0, '高难')
        self.assertEqual(field.difficulty(detail), '高难')
        self.assertEqual(game.selector_scroll, 1)
        extreme = task.boss_detail(0, '极难')
        self.assertEqual(field.difficulty(extreme), '极难')
        self.assertEqual(game.selector_scroll, 0)

    def test_unreleased_extreme_needs_a_complete_unscrolled_three_tier_list(self):
        for condition in ('locked', 'missing_row', 'live_clear', 'saved_clear', 'scrollbar'):
            with self.subTest(condition=condition):
                game = Game()
                task = self.task(game)
                capture = game.capture
                def observed(**kwargs):
                    s = capture(**kwargs)
                    if game.page == 'selector':
                        if condition == 'missing_row':
                            s.items = [item for item in s.items if item.text != '普通']
                        if condition == 'live_clear':
                            s.items.extend(screen(('通关', 306, 277)).items)
                    return s
                task.ui.capture = observed
                task.ui.scrollbar = Mock(return_value=False)
                if condition == 'saved_clear':
                    task.state['boss_clears'] = {'0:高难': dict(name='合成首领0',maximum=80000000)}
                if condition == 'scrollbar':
                    task.ui.scrollbar_bounds = Mock(return_value=(100, 200))
                if condition == 'locked':
                    self.assertIsNone(task.boss_detail(0, '极难'))
                    task.ui.scrollbar.assert_not_called()
                else:
                    with self.assertRaisesRegex(EventUIError, '目标首领难度未完整显示'):
                        task.boss_detail(0, '极难')
                self.assertEqual(game.real_battles, 0)
        self.assertEqual(game.real_battles, 0)

    def test_scarce_tickets_finish_other_normal_bosses_before_newly_unlocked_extreme(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.boss_clears = {(0, d) for d in field.DIFFICULTIES}
        game.tickets = 2
        report = self.task(game).run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertFalse(report['all_bosses_cleared'])
        self.assertEqual([(h['index'], h['difficulty']) for h in report['history']], [(1, '普通'), (2, '普通')])
        self.assertNotIn((0, '极难'), game.boss_clears)

    def test_exhausted_guide_for_one_boss_does_not_skip_other_uncleared_bosses(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 2
        task = self.task(game)
        task.source_parties = Mock(side_effect=lambda kind, boss='', *args, **kwargs:
                                   [] if boss == '合成首领0' else [party()])
        report = task.run(EVENT)
        self.assertEqual([(h['index'], h['difficulty']) for h in report['history']], [(1, '普通'), (2, '普通')])
        self.assertTrue(any('首领1 普通' in reason for reason in report['pending']))
        self.assertFalse(report['all_bosses_cleared'])
        self.assertEqual(game.tickets, 0)

    def test_independent_boss_progress_never_continues_uncertain_consumption_or_ui(self):
        for error, pending in ((BossPartyUnavailable('合成无队伍'), True), (EventUIError('合成未知页面'), False)):
            with self.subTest(error=type(error).__name__):
                task = self.task(Game())
                if pending:
                    task.state['pending'] = dict(kind='boss_battle')
                task.clear_boss = Mock(side_effect=error)
                with self.assertRaises(EventUIError):
                    task.bosses()
                self.assertEqual(task.clear_boss.call_count, 1)

    def test_uncleared_high_tier_continues_other_high_bosses_but_defers_extreme(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.boss_clears = {(i, d) for i in range(3) for d in ('普通', '困难')} | {(0, '高难')}
        game.tickets = 10
        task = self.task(game)
        task.source_parties = Mock(side_effect=lambda kind, boss='', *args, **kwargs:
                                   [] if boss == '合成首领1' else [party()])
        report = task.run(EVENT)
        self.assertEqual([(h['index'], h['difficulty']) for h in report['history']], [(2, '高难')])
        self.assertTrue(any('高难尚未全部首通' in reason for reason in report['pending']))
        self.assertFalse(report['all_bosses_cleared'])
        self.assertFalse(any(d == '极难' for _, d in game.boss_clears))
        self.assertEqual(game.tickets, 9)

    def test_boss_entry_can_return_the_requested_detail_directly(self):
        game = Game()
        game.difficulty = '困难'
        task = self.task(game)
        click = game.click
        def direct(target, **kwargs):
            click(target, **kwargs)
            if game.page == 'selector':
                game.page = 'boss'
        task.ui.click = direct
        detail = task.boss_detail(0, '困难')
        self.assertEqual(field.difficulty(detail), '困难')
        self.assertEqual(field.boss_name(detail), '合成首领0')
        self.assertEqual(game.real_battles, 0)

    def test_small_tier_label_uses_cropped_evidence_without_guessing(self):
        detail = screen(('BOSS详情', 110, 52), ('模拟战', 748, 109), ('实战', 866, 109))
        ui = Mock()
        ui.read_region.return_value = screen(('困难', 219, 51))
        self.assertIsNone(field.difficulty(detail))
        self.assertEqual(field.difficulty(detail, ui), '困难')
        ui.read_region.return_value.items[0].score = .8
        self.assertIsNone(field.difficulty(detail, ui))
        ui.read_region.return_value = screen(('普通', 219, 51), ('困难', 230, 51))
        self.assertIsNone(field.difficulty(detail, ui))

    def test_final_ticket_partial_high_boss_progress_completes_daily_resource_use(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.boss_clears = {(0, '普通'), (0, '困难')}
        game.tickets = 1
        game.simulation_wins = False
        game.simulation_damage = game.real_damage = 40000000
        report = self.referenced_task(game).run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertFalse(report['all_bosses_cleared'])
        self.assertEqual(game.tickets, 0)
        self.assertEqual(game.real_battles, 1)
        self.assertNotIn((0, '高难'), game.boss_clears)
        self.assertFalse(game.task.state.get('pending'))

    def test_subsequent_day_uses_only_sweeps_and_needs_no_avatar_audit(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game, first_clear=False)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(game.sweeps[-1], ('boss', 0, '极难', 12))
        task.source_parties.assert_not_called()
        task.formation.select.assert_not_called()
        self.assertEqual([text for page,text,*_ in game.clicks if page == 'home' and text in field.DIFFICULTIES],
                         list(field.DIFFICULTIES))
        self.assertEqual([text for page,text,*_ in game.clicks if page == 'normal'], ['使用4张']*3)

    def test_cleared_outpost_sweep_still_obeys_stamina_and_budget_caps(self):
        for stamina, budget in ((1000,50),(60,400)):
            with self.subTest(stamina=stamina,budget=budget):
                game = Game()
                game.stamina = stamina
                game.outpost_clears = set(field.DIFFICULTIES)
                report = self.task(game,first_clear=False,max_stamina=budget).run(EVENT)
                self.assertEqual((report['stamina_spent'],game.stamina,game.tickets),(50,stamina-50,2))
                self.assertEqual(game.attempts['普通'],2)
                self.assertEqual(game.sweeps,[('outpost',0,'普通',2)])
                self.assertEqual(game.real_battles,0)

    def test_failed_simulation_does_not_spend_boss_tickets(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.simulation_wins = False
        report = self.task(game).run(EVENT)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(game.tickets, 12)
        self.assertEqual(game.real_battles, 0)

    def test_rotated_win_banner_is_rechecked_before_real_first_clear(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
        task = self.task(game)
        read_result = task.combat_result_button
        def misread(screen):
            for item in screen.items:
                if item.text == 'WIN':
                    item.text = 'NIM'
            screen.items.extend(synthetic_screen(('伤害报告', 870, 35)).items)
            return read_result(screen)
        task.combat_result_button = misread
        task.ui.read_region = lambda s, roi, **kw: (
            screen(('WIN!', 480, 150)) if roi == (275, 70, 685, 250) else s)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.real_battles, 1)
        self.assertEqual(game.tickets, 0)
        self.assertIn((0, '普通'), game.boss_clears)
        self.assertTrue(report['simulations'][0]['readiness']['accepted'])

    def test_win_requires_confident_banner_on_a_battle_result(self):
        for label, confidence, x, expected in (
                ('WIN!', .99, 480, True), ('WIN!', .94, 480, False),
                ('TIMEUP', .99, 480, False), ('NIM', .99, 480, False),
                ('WIN!', .99, 800, False)):
            with self.subTest(label=label, confidence=confidence, x=x):
                local = screen((label, x, 150))
                local.items[0].score = confidence
                ui = Mock(read_region=Mock(return_value=local))
                result = screen(('伤害报告', 870, 35), ('下一步', 840, 470))
                self.assertEqual(field.result_win(ui, result), expected)
                ui.read_region.assert_called_once_with(result, (275, 70, 685, 250), classify=False)
                for other in (screen(('WIN!', 480, 150)),
                              screen(('扫荡结果', 480, 50), ('WIN!', 480, 150), ('关闭', 840, 470))):
                    self.assertFalse(field.result_win(ui, other))

    def test_positive_damage_without_a_source_reference_preserves_the_ticket(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
        game.boss_clears = {(i, d) for i in (1, 2) for d in field.BOSS_DIFFICULTIES}
        game.simulation_wins = False
        game.simulation_damage = 40000000
        task = self.task(game)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(game.tickets, 1)
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(task.simulation_count, 1)  # Duplicate guide trials are not replayed.
        self.assertFalse(report['simulations'][0]['readiness']['accepted'])
        self.assertTrue(all(d == 0 for d in game.allowed_deaths))

    def test_surviving_trial_uses_tier_budget_without_inventing_source_damage(self):
        for difficulty, damage, cuts in (('普通', 70000000, 0), ('困难', 70000000, 0),
                                         ('高难', 40000000, 2), ('极难', 14000000, 6),
                                         ('极难', 12000000, 0)):
            with self.subTest(difficulty=difficulty, damage=damage):
                game = Game()
                game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
                game.outpost_clears = set(field.DIFFICULTIES)
                game.boss_clears = {(i, d) for i in (1, 2) for d in field.BOSS_DIFFICULTIES}
                game.boss_clears.update((0, d) for d in field.BOSS_DIFFICULTIES[:field.BOSS_DIFFICULTIES.index(difficulty)])
                game.tickets = max(cuts, 1)
                game.simulation_wins = False
                game.simulation_damage = game.real_damage = damage
                task = self.task(game)
                task.options['state_dir'] = str(self.root/f'{difficulty}-{damage}')
                report = task.run(EVENT)
                self.assertEqual(game.real_battles, cuts, report['pending'])
                self.assertEqual(game.tickets, 0 if cuts else 1)
                trial = report['simulations'][0]['readiness']
                self.assertEqual(trial['accepted'], bool(cuts))
                self.assertEqual(trial['source_reference'], {})
                if cuts:
                    self.assertEqual(trial['estimated_attacks'], cuts)
                    self.assertIn((0, difficulty), game.boss_clears)
                    self.assertEqual(task.state['boss_attacks']['0:'+difficulty]['spent'], cuts)

    def test_last_remaining_attack_uses_partial_hp_after_restart(self):
        game = Game()
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in (1, 2) for d in field.BOSS_DIFFICULTIES}
        game.boss_clears.update({(0, '普通'), (0, '困难')})
        game.simulation_wins = False
        game.simulation_damage = game.real_damage = 40000000
        estimates = []
        for _ in range(2):
            game.tickets = 1
            task = self.task(game)
            report = task.run(EVENT)
            self.assertEqual(game.tickets, 0, report['pending'])
            estimates.append(report['simulations'][0]['readiness']['estimated_attacks'])
        self.assertEqual(estimates, [2, 1])
        self.assertEqual(game.real_battles, 2)
        self.assertIn((0, '高难'), game.boss_clears)
        self.assertEqual(task.state['boss_attacks']['0:高难']['spent'], 2)

    def test_attack_cap_is_not_reset_by_restarting_or_changing_candidates(self):
        game = Game()
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in (1, 2) for d in field.BOSS_DIFFICULTIES}
        game.boss_clears.update({(0, '普通'), (0, '困难')})
        game.tickets, game.real_damage = 3, 40000000
        for _ in range(2):
            task = self.task(game, boss_max_attacks={'高难': 1})
            report = task.run(EVENT)
            self.assertEqual(game.real_battles, 1)
            self.assertEqual(game.tickets, 2)
            self.assertIn('达到1刀上限', str(report['pending']))
        self.assertEqual(task.simulation_count, 0)
        self.assertEqual(game.health[(0, '高难')], 40000000)

    def test_pending_boss_attack_is_counted_once_before_new_budget_checks(self):
        for receipt_failure in (False, True):
            with self.subTest(receipt_failure=receipt_failure):
                game = Game()
                game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
                game.boss_clears = {(0, '普通'), (0, '困难')}
                game.health[(0, '高难')] = 40000000
                game.tickets = 2
                task = self.task(game, preview_only=True)
                folder = self.root/str(receipt_failure)
                task.options['state_dir'] = str(folder)
                task.state['pending'] = dict(kind='boss_battle', index=0, difficulty='高难', quantity=1,
                    tickets_before=3, boss='合成首领0', health=[80000000, 80000000], day=task.day())
                task.state_path = folder/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
                task.save()
                if receipt_failure:
                    save = task.ui.save
                    def fail_receipt(name, s=None):
                        if name.startswith('after_'):
                            raise OSError('synthetic receipt failure')
                        return save(name, s)
                    task.ui.save = fail_receipt
                    with self.assertRaisesRegex(OSError, 'synthetic receipt failure'):
                        task.run(EVENT)
                    self.assertEqual(task.state['boss_attacks']['0:高难']['spent'], 1)
                    self.assertEqual(task.state['pending']['attack_budget']['spent'], 0)
                else:
                    self.assertEqual(task.run(EVENT)['tickets_spent'], 1)
                next_task = self.task(game, preview_only=True)
                next_task.options['state_dir'] = str(folder)
                self.assertEqual(next_task.run(EVENT)['tickets_spent'], int(receipt_failure))
                self.assertEqual(next_task.state['boss_attacks']['0:高难']['spent'], 1)
                self.assertNotIn('pending', next_task.state)
                self.assertEqual(game.real_battles, 0)

    def test_changed_special_equipment_after_simulation_blocks_real_ticket(self):
        from pcrscript.game_ui.special_equipment import loadout_items
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
        task = self.task(game)
        task.prepare_party = lambda *args, **kw: AbyssSubjugation.prepare_party(task, *args, **kw)
        team = party()
        task.formation.inspect_current = Mock(return_value=[CharacterStatus(m.name, identity_verified=True) for m in team.members])
        before = dict(order=[m.name for m in team.members], slots=[[True]*3 for _ in range(5)],
                      empty=0, unknown=0, items=loadout_items(np.full((540, 960, 3), 80, np.uint8)))
        after = dict(before, items=loadout_items(np.full((540, 960, 3), 180, np.uint8)))
        with patch('pcrscript.tasks.party_preparation.auto_equip_special', return_value=before) as equip, \
             patch('pcrscript.tasks.party_preparation.inspect_special_equipment', return_value=after):
            report = task.run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertIn('必须重新模拟', str(report['pending']))
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(game.tickets, 1)
        self.assertEqual(equip.call_count, 1)

    def test_later_source_is_tried_before_weakening_an_earlier_roster(self):
        task = self.task(Game())
        first, second = party(), party()
        first.name, second.name = 'first', 'second'
        second.members[0].instant = False
        task.source_parties = Mock(side_effect=[[first], [second]])
        calls = []
        def audit(runner, seed, reopen, *, allow_substitutions):
            calls.append((seed.name, allow_substitutions))
            if seed.name == 'first':
                raise EventUIError('合成攻略缺员')
            return seed, [m.name for m in seed.members]
        with patch('pcrscript.tasks.task_abyss_subjugation.guide_party', side_effect=audit):
            result, _ = task.choose_normal_party('普通', Mock(), set())
        self.assertIs(result, second)
        self.assertEqual(calls, [('first', False), ('second', False)])
        self.assertEqual(task.source_parties.call_count, 2)

    def test_wiped_trial_cannot_spend_even_when_damage_exceeds_the_reference(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
        game.boss_clears = {(i, d) for i in (1, 2) for d in field.BOSS_DIFFICULTIES}
        game.simulation_wins = False
        game.simulation_damage = 70000000
        game.simulation_deaths = 5
        task = self.referenced_task(game)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(game.tickets, 1)
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(task.simulation_count, 2)  # Only the shared one-time retry.
        self.assertTrue(all(not r['readiness']['accepted'] for r in report['simulations']))
        self.assertEqual(report['simulations'][-1]['result']['retry']['action'], 'change_survival')

    def test_large_damage_shortfall_and_early_settlement_preserve_resources(self):
        for damage, end in ((18000000, 1), (40000000, 40)):
            with self.subTest(damage=damage, end=end):
                game = Game()
                game.outpost_clears = set(field.DIFFICULTIES)
                game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
                game.tickets = 1
                game.simulation_wins = False
                game.simulation_damage, game.simulation_end = damage, end
                report = self.referenced_task(game).run(EVENT)
                self.assertEqual(report['status'], 'blocked')
                self.assertEqual(game.tickets, 1)
                self.assertEqual(game.real_battles, 0)

    def test_reference_above_lower_boss_hp_requires_simulated_kill(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
        game.simulation_wins = False
        game.simulation_damage = 70000000
        report = self.referenced_task(game, damage=370000000, boss_max_attacks={'普通': 1}).run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['simulations'][0]['readiness']['expected_damage'], 80000000)
        self.assertEqual(game.tickets, 1)

    def test_actual_shortfall_does_not_repeat_the_same_party_with_more_tickets(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 3
        game.boss_clears = {(i, d) for i in (1, 2) for d in field.BOSS_DIFFICULTIES}
        game.simulation_wins = False
        game.simulation_damage = 40000000
        game.real_damage = 10000000
        report = self.referenced_task(game).run(EVENT)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(game.real_battles, 1)
        self.assertEqual(game.tickets, 2)
        self.assertEqual(len(report['real_rejections']), 1)
        self.assertFalse(game.task.state.get('pending'))

    def test_partial_damage_uses_all_tickets_and_continues_remaining_bosses_next_day(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.simulation_wins = False
        game.simulation_damage = game.real_damage = 40000000
        first = self.referenced_task(game).run(EVENT)
        self.assertEqual(first['status'], 'complete', first['pending'])
        self.assertFalse(first['all_bosses_cleared'])
        self.assertEqual(game.real_battles, 12)
        self.assertEqual(len(game.boss_clears), 6)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 4)
        with patch('pcrscript.tasks.task_abyss_subjugation.time.time', return_value=(NOW+timedelta(days=1)).timestamp()):
            second = self.referenced_task(game).run(EVENT)
        self.assertEqual(second['status'], 'complete', second['pending'])
        self.assertTrue(second['all_bosses_cleared'])
        self.assertEqual(game.real_battles, 24)
        self.assertTrue(all(h['difficulty'] in ('高难', '极难') for h in second['history'] if h['kind'] == 'boss_battle'))
        self.assertFalse(any(h['kind'] == 'boss_sweep' for h in second['history']))
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 4)
        with patch('pcrscript.tasks.task_abyss_subjugation.time.time', return_value=(NOW+timedelta(days=2)).timestamp()):
            third = self.task(game).run(EVENT)
        self.assertEqual(third['status'], 'complete', third['pending'])
        self.assertEqual(game.real_battles, 24)
        self.assertEqual(game.sweeps[-1], ('boss', 0, '极难', 12))

    def test_spent_ticket_without_verified_progress_blocks_further_attacks(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.real_damage = 0
        first = self.task(game)
        first.run(EVENT)
        self.assertIn('pending', first.state)
        self.assertEqual(game.real_battles, 1)
        second = self.task(game)
        self.assertEqual(second.run(EVENT)['status'], 'blocked')
        self.assertEqual(game.real_battles, 1)

    def test_real_party_mismatch_does_not_spend_after_simulation(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        task = self.task(game)
        task.formation.select.side_effect = None
        task.formation.select.return_value = (False, dict(order=[]))
        task.run(EVENT)
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(game.tickets, 12)

    def test_known_outpost_failure_clears_only_unchanged_resources(self):
        game = Game()
        game.outpost_wins = False
        task = self.task(game)
        report = task.run(EVENT)
        self.assertNotEqual(report['status'], 'complete')
        self.assertEqual(game.normal_commits, 0)
        self.assertEqual(game.tickets, 0)
        self.assertEqual(game.attempts, dict.fromkeys(field.DIFFICULTIES, 4))
        self.assertNotIn('pending', task.state)
        self.assertEqual(len(report['unspent_actions']), 1)

    def test_missing_damage_and_disabled_sweep_never_imply_clear_or_strategy(self):
        game = Game()
        task = self.task(game)
        empty = screen(('跳过伤害', 644, 333), ('使用1张', 756, 377))
        self.assertIsNone(field.cleared_boss(task.ui, empty))
        cv.rectangle(empty.image, (903, 332), (910, 334), (60, 60, 60), -1)
        self.assertFalse(field.cleared_boss(task.ui, empty))
        bonus = screen(('初次通关额外分数', 100, 20), ('500000000', 140, 55))
        self.assertIsNone(field.result_damage(task.ui, bonus))

    def test_lost_receipt_recovers_counters_without_replaying_consumption(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        game.attempts.update(困难=0, 高难=0)
        game.lose_receipt = True
        first = self.task(game)
        self.assertEqual(first.run(EVENT)['status'], 'blocked')
        self.assertEqual(game.normal_commits, 1)
        self.assertIn('pending', first.state)
        second = self.task(game)
        report = second.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.normal_commits, 1)
        self.assertEqual(game.tickets, 0)

    def test_unknown_counter_keeps_pending_and_prevents_second_spend(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.corrupt_counter = True
        first = self.task(game)
        first.run(EVENT)
        self.assertEqual(game.normal_commits, 1)
        self.assertIn('pending', first.state)
        second = self.task(game)
        self.assertEqual(second.run(EVENT)['status'], 'blocked')
        self.assertEqual(game.normal_commits, 1)

    def test_cancelled_preview_recovers_without_charging_or_replaying_it(self):
        game = Game()
        game.page, game.quantity = 'confirmation', 3
        game.attempts.update(普通=3, 困难=0, 高难=0)
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game)
        task.event = EVENT
        task.state['pending'] = dict(kind='outpost_sweep', difficulty='普通', quantity=3,
            stamina_cost=75, attempts=dict(game.attempts), tickets_before=0, day=task.day())
        task.state_path = self.root/'state'/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
        task.save()
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(len(report['unspent_actions']), 1)
        self.assertEqual(game.normal_commits, 1)
        self.assertEqual(report['stamina_spent'], 75)

    def test_final_sweep_cost_mismatch_never_submits(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.confirmation_cost_delta = 1
        task = self.task(game)
        report = task.run(EVENT)
        self.assertEqual(game.normal_commits, 0)
        self.assertNotIn('pending', task.state)
        self.assertIn('扫荡最终体力消费不符', ' '.join(report['pending']))

    def test_resumed_failure_requires_unchanged_resources_before_clearing(self):
        game = Game()
        game.page = 'failure'
        task = self.task(game, preview_only=True)
        task.state['pending'] = dict(kind='outpost_battle', difficulty='困难', quantity=1,
            stamina_cost=25, attempts=dict(game.attempts), tickets_before=0, day=task.day())
        task.state_path = self.root/'state'/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
        task.save()
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'preview', report['pending'])
        self.assertEqual(report['stamina_spent'], 0)
        self.assertEqual(len(report['unspent_actions']), 1)
        self.assertNotIn('pending', task.state)

    def test_pending_paused_battle_resumes_without_starting_another(self):
        game = Game()
        game.page = 'home'
        ready = game.capture()
        task = self.task(game)
        task.state['pending'] = dict(kind='outpost_battle')
        panel = screen(('进行中战斗', 310, 134), ('主菜单', 480, 85), ('返回', 335, 433))
        combat = screen(('1:10', 800, 25), ('菜单', 900, 25))
        task.ui.capture = Mock(side_effect=[panel, panel, combat, combat, ready, ready])
        task.ui.click = Mock()
        self.assertIs(task.enter(), ready)
        task.ui.click.assert_called_once()
        self.assertEqual(task.ui.click.call_args.args[0].text, '返回')

        task.state.clear()
        task.ui.capture = Mock(return_value=panel)
        task.ui.click.reset_mock()
        with self.assertRaisesRegex(EventUIError, '未知的暂停战斗'):
            task.enter()
        task.ui.click.assert_not_called()

    def test_resumed_first_clear_reconciles_resources_without_restoring_an_old_party(self):
        game = Game()
        game.page, game.tickets = 'home', 1
        before = dict(game.attempts)
        game.attempts['普通'] = 3
        game.outpost_clears.add('普通')
        task = self.task(game, preview_only=True)
        winner = asdict(party())
        older = asdict(party())
        older['members'][0]['name'] = '旧合成角色'
        task.state.update(normal_party=older, pending=dict(kind='outpost_battle',
            difficulty='普通', quantity=1, stamina_cost=25, attempts=before,
            tickets_before=0, day=task.day(), normal_party=winner))
        task.state_path = self.root/'state'/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
        task.save()
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'preview', report['pending'])
        self.assertNotIn('normal_party', task.state)
        self.assertEqual(report['stamina_spent'], 25)
        self.assertNotIn('pending', task.state)
        self.assertEqual(game.normal_commits+game.real_battles, 0)

    def test_pending_outpost_across_server_reset_is_never_replayed(self):
        game = Game()
        game.attempts['普通'] = 3
        game.tickets = 1
        task = self.task(game)
        task.state['pending'] = dict(kind='outpost_battle', difficulty='普通', quantity=1,
            stamina_cost=25, attempts=dict.fromkeys(field.DIFFICULTIES, 4), tickets_before=0,
            day=(NOW-timedelta(days=1, hours=5)).date().isoformat())
        task.state_path = self.root/'state'/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
        task.save()
        self.assertEqual(task.run(EVENT)['status'], 'blocked')
        self.assertIn('pending', task.state)
        self.assertEqual(game.normal_commits+game.real_battles, 0)

    def test_known_limited_shop_is_cancelled_before_resuming(self):
        game = Game()
        game.page = 'limited_shop'
        report = self.task(game, preview_only=True).run(EVENT)
        self.assertEqual(report['status'], 'preview')
        self.assertEqual(game.clicks[0][1], '取消')

    def test_date_mismatch_and_expiry_do_not_consume(self):
        game = Game()
        task = self.task(game)
        different = Event(EVENT.startTimestamp, EVENT.endTimestamp, EVENT.name, dict(EVENT.extras, title='别的活动'))
        self.assertEqual(task.run(different)['status'], 'blocked')
        self.assertEqual(game.normal_commits+game.real_battles, 0)
        with patch('pcrscript.tasks.task_abyss_subjugation.time.time', return_value=EVENT.endTimestamp):
            self.assertEqual(self.task(game).run(EVENT)['status'], 'unavailable')

    def test_preview_and_stamina_budget_are_enforced(self):
        game = Game()
        task = self.task(game, preview_only=True)
        self.assertEqual(task.run(EVENT)['status'], 'preview')
        self.assertEqual(game.normal_commits+game.real_battles, 0)
        task = self.task(game, max_stamina=50)
        report = task.run(EVENT)
        self.assertEqual(report['stamina_spent'], 50)
        self.assertEqual(game.attempts['普通'], 2)
        self.assertEqual(report['status'], 'partial')

    def test_full_costume_talent_must_match_even_when_prefilter_identity_is_unknown(self):
        database = self.root/'synthetic.db'
        with closing(sqlite3.connect(database)) as c:
            c.executescript('CREATE TABLE unit_profile(unit_id INTEGER,unit_name TEXT);'
                            'CREATE TABLE unit_talent(setting_id INTEGER,unit_id INTEGER,talent_id INTEGER);')
            c.executemany('INSERT INTO unit_profile VALUES (?,?)', [(i, '合成角色'+str(i)) for i in range(5)])
            c.executemany('INSERT INTO unit_talent VALUES (?,?,?)', [(i, i, 2) for i in range(5)])
            c.execute('INSERT INTO unit_profile VALUES (100,"合成角色0（礼服）")')
            c.execute('INSERT INTO unit_talent VALUES (100,100,1)')
            c.commit()
        self.assertEqual(character_talents(database)['合成角色0(礼服)'], 1)
        game = Game()
        game.page = 'formation'
        task = self.task(game, avatars=dict(database=str(database)))
        task.event, task.avatars_ready = EVENT, True
        del task.character_talents
        task.formation.occupied_slots = Mock(return_value=[(1, 1)]*5)
        task.formation.avatars.query = Mock(return_value=[None]*5)
        require_event_talent(task, party())
        wrong = party()
        wrong.members[0].name = '合成角色0(礼服)'
        with self.assertRaises(EventUIError):
            require_event_talent(task, wrong)
        wrong.members[0].name = '未知角色'
        with self.assertRaises(EventUIError):
            require_event_talent(task, wrong)

    def test_all_prepared_builds_are_pinned_between_simulation_and_real_selection(self):
        task = self.task(Game())
        formation = task.formation
        formation.select = type(formation).select.__get__(formation)
        selected = party()
        required = selected.members[0]
        changed = CharacterStatus(required.name, level=80, rank=8, stars=3,
                                  skill_level=80, unique=False, unique2=False, identity_verified=True)
        def inspect(party):
            resolved = formation.resolve_requirement(required, changed)
            self.assertIs(resolved, required)
            self.assertTrue(formation.member_readiness(resolved, changed))
            return False, {}
        for basis in ('source', 'local_trial'):
            selected.build_basis = basis
            with self.subTest(basis=basis), \
                 patch.object(formation, 'quick_current', return_value=None), \
                 patch('pcrscript.tasks.event_formation.EventFormation.select', side_effect=inspect):
                self.assertFalse(formation.select(selected)[0])
                self.assertFalse(formation.pin_build)
        self.assertFalse(formation.member_readiness(required, changed))

    def test_missing_public_database_does_not_create_an_empty_account_catalog(self):
        missing = self.root/'missing.db'
        with self.assertRaisesRegex(EventUIError, '角色属性资料不可用'):
            character_talents(missing)
        self.assertFalse(missing.exists())

    def test_source_recovery_skips_missing_members_without_pinning_partial_build(self):
        from pcrscript.tasks.subjugation_party import SubjugationFormation
        formation = SubjugationFormation(Mock())
        selected = party()
        missing = selected.members[0].name
        def inspect(partial):
            self.assertFalse(formation.pin_build)
            self.assertEqual(len(partial.members), 4)
            self.assertNotIn(missing, [m.name for m in partial.members])
            return True, dict(order=[m.name for m in partial.members])
        with patch('pcrscript.tasks.event_formation.EventFormation.select', side_effect=inspect):
            ready, details = formation.select_source_members(selected, known_missing=[missing])
        self.assertFalse(ready)
        self.assertEqual(details['unready'][0]['character'], missing)

    def test_recent_audit_requires_same_equipment_before_reuse(self):
        game = Game()
        game.page = 'formation'
        task = self.task(game)
        task.formation.select = type(task.formation).select.__get__(task.formation)
        selected = party()
        actual = [CharacterStatus(m.name, level=m.level, rank=m.rank, stars=m.stars,
                                  unique=m.unique, unique2=m.unique2, skill_level=m.skill_level,
                                  identity_verified=True) for m in selected.members]
        with patch('pcrscript.tasks.abyss_party.AbyssFormation.quick_current', return_value=actual):
            self.assertTrue(task.formation.select(selected)[0])
            actual[0].unique = False
            with patch('pcrscript.tasks.event_formation.EventFormation.select', return_value=(False, {})) as inspect:
                self.assertFalse(task.formation.select(selected)[0])
                inspect.assert_called_once()

    def test_daily_filter_and_single_preflight_share_the_schedule(self):
        plan = [['abyss_subjugation'], ['schedule']]
        modify_task_list(EventNews(abyssSubjugation=EVENT), plan)
        self.assertEqual(plan, [['abyss_subjugation', EVENT], ['schedule']])
        modify_task_list(EventNews(), plan)
        self.assertEqual(plan, [['schedule']])
        with patch('pcrscript.news.fetch_event_news', return_value=EventNews()), \
                patch('pcrscript.runtime.robot_from_config') as connect:
            self.assertEqual(run_task_with_config({}, 'abyss_subjugation')['status'], 'unavailable')
            connect.assert_not_called()

    def test_missing_guides_never_fall_back_to_current_saved_or_cached_parties(self):
        game = Game()
        game.tickets = 1
        task = self.task(game, normal_team=[1, 1], boss_teams=[[1, 1]])
        task.source_parties = Mock(return_value=[])
        task.state.update(normal_party=asdict(party()))
        task.state_path = self.root/'state'/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
        task.save()
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(game.normal_commits+game.real_battles, 0)
        self.assertEqual(task.simulation_count, 0)
        self.assertEqual(game.tickets, 1)
        self.assertNotIn('normal_party', task.state)
        self.assertNotIn('normal_team', task.options)
        self.assertNotIn('boss_teams', task.options)
        task.formation.select.assert_not_called()
        task.formation.owned_candidates.assert_not_called()
        self.assertEqual(sum('首领' in reason and '攻略' in reason for reason in report['pending']), 3)

    def test_complete_guides_can_clear_without_allowing_account_trial_adaptations(self):
        game = Game()
        task = self.task(game, first_clear=True, allow_local_trials=False)
        seed = party()
        seed.build_basis = 'source'
        task.source_parties = Mock(return_value=[seed])
        with patch('pcrscript.tasks.task_abyss_subjugation.guide_party',
                   side_effect=lambda runner, seed, reopen, **kw: (seed, [m.name for m in seed.members])) as audit:
            report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.normal_commits, 6)
        self.assertGreater(game.real_battles, 0)
        self.assertTrue(all(not c.kwargs['allow_substitutions'] for c in audit.call_args_list))

    def test_first_clear_switch_blocks_new_battles_independently_of_source_trials(self):
        game = Game()
        game.tickets = 1
        task = self.task(game, first_clear=False, allow_local_trials=True)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(game.normal_commits+game.real_battles, 0)
        self.assertEqual(task.simulation_count, 0)
        task.source_parties.assert_not_called()

    def test_legacy_sweep_only_configuration_does_not_enable_new_source_battles(self):
        game = Game()
        game.tickets = 1
        task = self.task(game, normal_team=[1, 1], allow_local_trials=False)
        report = task.run(EVENT)
        self.assertIs(task.options['first_clear'], False)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(game.normal_commits+game.real_battles, 0)
        task.source_parties.assert_not_called()

    def test_minimal_legacy_sweep_only_options_require_explicit_first_clear_opt_in(self):
        self.assertIs(validate_options(dict(allow_local_trials=False))['first_clear'], False)
        self.assertIs(validate_options(dict(first_clear=True, allow_local_trials=False))['first_clear'], True)

    def test_failure_keeps_different_source_switches_eligible_and_resumes_the_same_stream(self):
        game = Game()
        game.outpost_wins = False
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game)
        first, second = party(), party()
        second.members[0].instant = not first.members[0].instant
        task.source_parties = Mock(return_value=[first, second])
        calls = []
        def audit(runner, seed, reopen, **kwargs):
            calls.append((game.difficulty, seed.members[0].instant))
            if seed is second:
                game.outpost_wins = True
            return seed, [m.name for m in seed.members]
        with patch('pcrscript.tasks.task_abyss_subjugation.guide_party', side_effect=audit):
            report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(len(report['normal_trials']), 1)
        self.assertEqual(task.source_parties.call_count, 3)  # One catalog for each target, including retries.
        self.assertEqual(task.state['failed_outpost_teams']['difficulties']['普通'], [party_fingerprint(first)])
        self.assertNotEqual(party_fingerprint(first), party_fingerprint(second))
        self.assertEqual(game.normal_commits, 6)
        self.assertEqual(report['stamina_spent'], 300)

    def test_source_batch_budget_is_retained_when_all_candidates_are_rejected(self):
        task = self.task(Game(), max_source_batches=2)
        task.source_parties = Mock(return_value=[])
        for _ in range(2):
            with self.assertRaisesRegex(EventUIError, '本期前哨攻略'):
                task.choose_normal_party('普通', Mock(), set())
        self.assertEqual(task.source_parties.call_count, 2)
        self.assertEqual([c.kwargs['advance'] for c in task.source_parties.call_args_list], [False, True])

    def test_simulation_failure_tries_next_guide_without_creating_an_unrelated_team(self):
        game = Game()
        game.tickets = 1
        game.simulation_wins = False
        task = self.task(game)
        first, second = party(), party()
        second.members[0].instant = not first.members[0].instant
        task.source_parties = Mock(return_value=[first, second])
        task.formation.alternative_trial = Mock(side_effect=AssertionError('No unscoped role-based team'))
        def audit(runner, seed, reopen, **kwargs):
            if seed is second:
                game.simulation_wins = True
            return seed, [m.name for m in seed.members]
        with patch('pcrscript.tasks.task_abyss_subjugation.guide_party', side_effect=audit):
            selected, _ = task.simulate_boss(0, '普通', dict(
                boss='合成首领0', health=(80000000, 80000000), tickets_before=1))
        self.assertIs(selected, second)
        self.assertEqual(task.simulation_count, 2)
        self.assertEqual(game.tickets, 1)
        self.assertEqual(game.real_battles, 0)
        task.formation.alternative_trial.assert_not_called()

    def test_equipment_recovery_retains_the_simulated_build_and_cannot_train(self):
        task = self.task(Game(), allow_five_star_upgrade=True)
        selected = party()
        order = [m.name for m in selected.members]
        for basis in ('source', 'local_trial'):
            selected.build_basis = basis
            task.formation.select.side_effect = [
                (False, dict(unready=['专武状态未知'])),
                (False, dict(unready=['装备Rank不符']))]
            with patch('pcrscript.tasks.task_abyss_subjugation.recover_equipment') as recover, \
                 patch('pcrscript.tasks.task_abyss_subjugation.guide_party') as source_audit:
                with self.assertRaisesRegex(EventUIError, '装备Rank不符'):
                    task.select_verified_party(selected, Mock())
                recover.assert_called_once_with(task, order)
                source_audit.assert_not_called()
        self.assertEqual(task.simulation_count, 0)
