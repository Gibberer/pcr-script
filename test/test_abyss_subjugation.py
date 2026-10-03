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
from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.tasks import AbyssSubjugation, Event, EventNews
from pcrscript.tasks.event_battle import BattleResult
from pcrscript.tasks.event_strategy import CharacterStatus, EventParty, MemberRequirement
from pcrscript.tasks.subjugation_party import audit_current, character_talents, require_event_talent, current_party
from pcrscript.tasks.task_abyss_subjugation import validate_options
from pcrscript.runtime import modify_task_list, run_task_with_config


START = datetime(2026, 10, 2, 12, tzinfo=SERVER_TIMEZONE)
NOW = START+timedelta(hours=1)
EVENT = Event(START.timestamp(), datetime(2026, 10, 7, 4, 59, 59, tzinfo=SERVER_TIMEZONE).timestamp(),
              '深渊讨伐战', dict(abyss_id=1, boss_ticket_id=70001, talent_id=2, title='合成深渊'))


def screen(*labels, blue=(), yellow=()):
    img = np.full((540, 960, 3), 245, np.uint8)
    items = []
    for text, x, y in labels:
        items.append(TextBox(text, .999, [[x-24, y-8], [x+24, y-8], [x+24, y+8], [x-24, y+8]]))
        if text in blue:
            cv.rectangle(img, (x-50, y-22), (x+50, y+22), (230, 155, 25), -1)
    for x1, y1, x2, y2 in yellow:
        cv.rectangle(img, (x1, y1), (x2, y2), (25, 200, 245), -1)
    return EventScreen(img, items)


def party():
    return EventParty('synthetic', '合成游戏保存队伍',
        [MemberRequirement('合成角色'+str(i), 100, 10, 5, True, False, True, 100) for i in range(5)],
        build_basis='local_trial', allow_deaths=5)


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
                dark_portraits=self.simulation_deaths) for i in (4, 2, 0)]
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
        task.choose_saved = Mock(return_value=(party(), ['合成角色'+str(i) for i in range(5)]))
        task.formation.owned_candidates = Mock(return_value=[m.name for m in party().members])
        task.prepare_party = Mock(return_value={'slots': [[True]*3 for _ in range(5)], 'empty': 0, 'unknown': 0})
        task.formation.select = Mock(side_effect=lambda selected: (True, dict(order=[m.name for m in selected.members])))
        task.combat.run = game.combat
        patch('pcrscript.tasks.task_abyss_subjugation.current_party',
              side_effect=EventUIError('合成当前编组不可用')).start()
        return task

    def referenced_task(self, game, damage=40000000, **options):
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
        self.assertEqual(game.tickets, 0)
        self.assertEqual(game.sweeps[-1], ('boss', 0, '极难', 3))
        self.assertEqual(sum(1 for call in task.choose_saved.call_args_list if call.args[0] == [1, 1]), 1)
        self.assertNotIn('pending', task.state)

    def test_public_guide_is_audited_before_native_or_role_candidates(self):
        game = Game()
        task = self.task(game)
        seed = party()
        seed.source = 'https://example.com/synthetic-guide'
        task.source_parties = Mock(side_effect=lambda kind, *args, **kwargs: [seed] if kind == 'outpost' else [])
        with patch('pcrscript.tasks.task_abyss_subjugation.guide_party',
                   return_value=(seed, [m.name for m in seed.members])) as audit:
            report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(report['normal_team']['candidate'], 'guide')
        audit.assert_called_once()
        task.choose_saved.assert_not_called()
        self.assertEqual(game.normal_commits, 6)

    def test_cached_trial_reaudits_unknown_equipment_without_bypassing_build_checks(self):
        game = Game()
        task = self.task(game)
        task.event = EVENT
        seed = party()
        task.normal_party = seed
        task.formation.select.side_effect = None
        task.formation.select.return_value = (False, {'unready': ['专武状态未知']})
        task.formation.populate_candidates = Mock(return_value=(True, {}))
        order = [m.name for m in seed.members]
        reopen = Mock()
        with patch.object(task.formation, 'source_trial', return_value=(party(), {'order':order, 'observed':[asdict(CharacterStatus(m.name, **{key:getattr(m,key) for key in ('level','rank','stars','skill_level','unique','unique2')}, identity_verified=True)) for m in party().members]})) as audit:
            selected, actual_order = task.choose_normal_party(reopen, set())
        self.assertEqual(actual_order, order)
        self.assertEqual(selected.members, seed.members)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[1]['names'], order)
        mismatched = party()
        mismatched.members[0].unique2 = True
        with patch.object(task.formation, 'source_trial', return_value=(mismatched, {'order':order, 'observed':[asdict(CharacterStatus(m.name, **{key:getattr(m,key) for key in ('level','rank','stars','skill_level','unique','unique2')}, identity_verified=True)) for m in mismatched.members]})):
            with self.assertRaisesRegex(EventUIError, '攻略要求不符'):
                task.choose_normal_party(reopen, set())
        self.assertEqual(game.normal_commits+game.real_battles, 0)

    def test_verified_outpost_failure_changes_candidate_once_without_replaying_failed_party(self):
        game = Game()
        game.outpost_wins = False
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game)
        alternative = party()
        alternative.members[0].name = '合成替代角色'
        task.character_talents['合成替代角色'] = 2
        selected = [False]
        def choose(candidate, reopen):
            if not selected[0]:
                selected[0] = True
                return party(), [m.name for m in party().members]
            game.outpost_wins = True
            return alternative, [m.name for m in alternative.members]
        task.choose_saved.side_effect = choose
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(task.choose_saved.call_count, 2)
        self.assertEqual(len(report['unspent_actions']), 1)
        self.assertEqual(len(report['normal_trials']), 1)
        self.assertEqual(game.normal_commits, 6)
        self.assertEqual(report['stamina_spent'], 300)
        self.assertEqual(task.normal_party.members[0].name, '合成替代角色')
        self.assertEqual(len(task.state['failed_outpost_teams']['difficulties']['普通']), 1)

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
        self.assertIn('normal_party', task.state)

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

    def test_normal_candidate_rejection_falls_back_then_reuses_one_party(self):
        game = Game()
        task = self.task(game)
        def choose(candidate, reopen):
            if candidate == [1, 1]:
                raise EventUIError('合成非活动属性队伍')
            return party(), ['合成角色'+str(i) for i in range(5)]
        task.choose_saved.side_effect = choose
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(report['normal_team']['candidate'], [1, 2])
        self.assertEqual(task.choose_saved.call_count, 2)
        self.assertEqual(len([r for r in report['candidate_rejections'] if r.get('kind') != 'boss']), 2)

    def test_subsequent_day_uses_only_sweeps_and_needs_no_avatar_audit(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.boss_clears = {(i, d) for i in range(3) for d in field.BOSS_DIFFICULTIES}
        task = self.task(game, allow_local_trials=False)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'complete', report['pending'])
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(game.sweeps[-1], ('boss', 0, '极难', 12))
        task.choose_saved.assert_not_called()
        task.formation.select.assert_not_called()

    def test_boss_can_simulate_the_current_party_before_loading_saves(self):
        game = Game()
        game.boss_clears = {(0, '普通')}
        game.tickets = 3
        task = self.task(game)
        selected = party()
        reference = dict(boss='合成首领0', health=(80000000, 80000000), tickets_before=3)
        with patch('pcrscript.tasks.task_abyss_subjugation.audit_current',
                   return_value=(selected, [m.name for m in selected.members])) as audit:
            actual, order = task.simulate_boss(0, '困难', reference)
        self.assertIs(actual, selected)
        self.assertEqual(order, [m.name for m in selected.members])
        audit.assert_called_once()
        task.choose_saved.assert_not_called()
        self.assertEqual(game.tickets, 3)
        self.assertEqual(game.real_battles, 0)

        task.normal_party = selected
        task.choose_normal_party = Mock(return_value=(selected, order))
        failed = tuple(sorted(m.name for m in selected.members))
        task.state['failed_outpost_teams'] = dict(day=task.day(), difficulties={'高难': [list(failed)]})
        with patch('pcrscript.tasks.task_abyss_subjugation.audit_current') as audit:
            actual, _ = task.simulate_boss(0, '困难', reference)
        self.assertIs(actual, selected)
        task.choose_normal_party.assert_called_once()
        self.assertEqual(task.choose_normal_party.call_args.args[1], {failed})
        audit.assert_not_called()
        self.assertEqual(game.tickets, 3)
        self.assertEqual([m['name'] for m in task.state['normal_party']['members']], order)
        self.assertNotIn('pending', task.state)

    def test_failed_simulation_does_not_spend_boss_tickets(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.simulation_wins = False
        report = self.task(game).run(EVENT)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(game.tickets, 12)
        self.assertEqual(game.real_battles, 0)

    def test_positive_damage_without_a_source_reference_preserves_the_ticket(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
        game.simulation_wins = False
        game.simulation_damage = 40000000
        task = self.task(game)
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(game.tickets, 1)
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(task.simulation_count, 1)  # Duplicate saved rosters are not replayed.
        self.assertFalse(report['simulations'][0]['readiness']['accepted'])
        self.assertTrue(all(d == 0 for d in game.allowed_deaths))

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
            result, _ = task.choose_normal_party(Mock(), set())
        self.assertIs(result, second)
        self.assertEqual(calls, [('first', False), ('second', False)])
        task.choose_saved.assert_not_called()

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
            result, _ = task.choose_normal_party(Mock(), set())
        self.assertIs(result, second)
        self.assertEqual(calls, [('first', False), ('second', False)])
        task.choose_saved.assert_not_called()

    def test_wiped_trial_cannot_spend_even_when_damage_exceeds_the_reference(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 1
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
        report = self.referenced_task(game, damage=370000000).run(EVENT)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['simulations'][0]['readiness']['expected_damage'], 80000000)
        self.assertEqual(game.tickets, 1)

    def test_actual_shortfall_does_not_repeat_the_same_party_with_more_tickets(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        game.attempts = dict.fromkeys(field.DIFFICULTIES, 0)
        game.tickets = 3
        game.simulation_wins = False
        game.simulation_damage = 40000000
        game.real_damage = 10000000
        report = self.referenced_task(game).run(EVENT)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(game.real_battles, 1)
        self.assertEqual(game.tickets, 2)
        self.assertEqual(len(report['real_rejections']), 1)
        self.assertFalse(game.task.state.get('pending'))

    def test_survival_adjustment_delegates_to_deep_area_formation(self):
        game = Game()
        task = self.task(game)
        selected = party()
        order = [m.name for m in selected.members]
        task.formation.observed = {m.name: CharacterStatus(m.name,
            **{k: getattr(m, k) for k in ('level', 'rank', 'stars', 'skill_level', 'unique', 'unique2')},
            identity_verified=True) for m in selected.members}
        task.formation.alternative_trial = Mock(return_value=(party(), dict(order=order)))
        failed = {tuple(sorted(order))}
        reopen = Mock()
        candidate = task.boss_alternative(selected, order, failed,
            dict(action='change_survival', reason='合成持续减员'), reopen)
        self.assertIsNotNone(candidate)
        call = task.formation.alternative_trial.call_args
        self.assertTrue(call.args[0].is_boss)
        self.assertEqual(call.args[1]['order'], order)
        self.assertIs(call.args[2], failed)
        self.assertIs(call.kwargs['survival'], True)
        reopen.assert_called_once()

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

    def test_resumed_first_clear_keeps_its_verified_party(self):
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
        self.assertEqual(task.state['normal_party'], winner)
        self.assertEqual(task.normal_party.members[0].name, winner['members'][0]['name'])
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

    def test_cached_party_wrong_event_talent_is_blocked_before_simulation_or_real_spend(self):
        game = Game()
        game.outpost_clears = set(field.DIFFICULTIES)
        task = self.task(game)
        task.character_talents['合成角色0'] = 1
        task.state['normal_party'] = asdict(party())
        task.state_path = self.root/'state'/(sha256(b'synthetic|1').hexdigest()[:24]+'.json')
        task.save()
        report = task.run(EVENT)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(game.real_battles, 0)
        self.assertEqual(report['simulations'], [])
        self.assertEqual(game.tickets, 12)
        self.assertIn('加成属性', ' '.join(report['pending']))

    def test_unknown_live_equipment_blocks_the_auditor(self):
        game = Game()
        task = self.task(game)
        game.page = 'formation'
        task.avatars_ready = True
        task.formation.occupied_slots = Mock(return_value=[(1, 1)]*5)
        task.formation.inspect_current = Mock(return_value=[CharacterStatus(
            '合成角色'+str(i), level=100, rank=10, stars=5, skill_level=100,
            unique=None if i == 0 else True, unique2=False, identity_verified=True) for i in range(5)])
        with patch('pcrscript.tasks.subjugation_party.recover_equipment') as recover, \
             self.assertRaisesRegex(EventUIError, '专武状态未知'):
            audit_current(task, Mock())
        recover.assert_called_once_with(task, ['合成角色0'])
        self.assertEqual(game.normal_commits+game.real_battles, 0)

    def test_current_party_is_audited_and_full_identity_must_match_the_five_faces(self):
        game = Game()
        game.page = 'formation'
        task = self.task(game)
        task.event = EVENT
        actual = [CharacterStatus(m.name, level=m.level, rank=m.rank, stars=m.stars,
                                  skill_level=m.skill_level, unique=m.unique, unique2=m.unique2,
                                  identity_verified=True) for m in party().members]
        task.formation.occupied_slots = Mock(return_value=[(1, 1)]*5)
        task.formation.avatars.query = Mock(return_value=[m.name for m in actual])
        task.formation.inspect_current = Mock(return_value=actual)
        selected, order = current_party(task, Mock())
        self.assertEqual(selected.source, '游戏当前编组')
        self.assertEqual(order, [m.name for m in actual])
        self.assertEqual(len(task.report['party_audits']), 1)
        actual[0].name += '(礼服)'
        task.character_talents[actual[0].name] = 2
        with self.assertRaisesRegex(EventUIError, '完整衣装与预核验不符'):
            current_party(task, Mock())

    def test_current_and_saved_party_audit_uses_shared_opt_in_training(self):
        game = Game()
        task = self.task(game)
        task.options['allow_five_star_upgrade'] = True
        task.avatars_ready = True
        chosen = party()
        order = [m.name for m in chosen.members]
        before, after = dict(order=order, observed=[]), dict(order=order, observed=[], refreshed=True)
        task.formation.current_trial = Mock(return_value=(chosen,before))
        reopen = Mock()
        with patch('pcrscript.tasks.subjugation_party.upgrade_party_stars',
                   return_value=(chosen,after)) as train:
            result, actual_order = audit_current(task,reopen)
        self.assertIs(result,chosen)
        self.assertEqual(actual_order,order)
        self.assertIs(train.call_args.kwargs['reopen'],reopen)
        self.assertEqual(task.report['party_audits'],[before,after])
        self.assertEqual(game.normal_commits+game.real_battles, 0)

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
        require_event_talent(task)
        require_event_talent(task, party())
        wrong = party()
        wrong.members[0].name = '合成角色0(礼服)'
        with self.assertRaises(EventUIError):
            require_event_talent(task, wrong)
        wrong.members[0].name = '未知角色'
        with self.assertRaises(EventUIError):
            require_event_talent(task, wrong)

    def test_local_trial_build_is_pinned_between_simulation_and_real_selection(self):
        task = self.task(Game())
        formation = task.formation
        formation.pin_build = True
        required = party().members[0]
        changed = CharacterStatus(required.name, level=80, rank=8, stars=3,
                                  skill_level=80, unique=False, unique2=False, identity_verified=True)
        resolved = formation.resolve_requirement(required, changed)
        self.assertIs(resolved, required)
        self.assertTrue(formation.member_readiness(resolved, changed))
        formation.pin_build = False
        self.assertFalse(formation.member_readiness(required, changed))

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

    def test_configuration_rejects_unsafe_or_ambiguous_values(self):
        for options in ({'max_stamina': True}, {'max_boss_tickets': -1}, {'preview_only': 1},
                        {'normal_team': [1, 3]}, {'boss_teams': [[1, 1], [1, 1]]}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                validate_options(options)
