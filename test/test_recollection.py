"""Synthetic Recollection navigation and spending regressions; no real account data."""
from __future__ import annotations

from copy import deepcopy
from itertools import count
from pathlib import Path
import json
import time
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2 as cv
import numpy as np

from pcrscript import Robot
from pcrscript.game_ui import recollection as field
from pcrscript.game_ui.screen import EventScreen, EventUIError, TextBox
from pcrscript.tasks import Recollection, RecollectionFirstClear
from pcrscript.tasks.event_strategy import CharacterStatus
from pcrscript.tasks.event_battle import BattleResult
from pcrscript.tasks.recollection_flow import validate_options
from pcrscript.tasks.recollection_strategy import parties_for_floor, RecollectionFormation
from pcrscript.tasks.strategy_document import Evidence, empty_member, finalize
from pcrscript.tasks.strategy_video import (choose_pages, observed_scope, task_source_options,
    parse_video_source, RecollectionScopeContext, recollection_client_region)
from pcrscript.run_session import RunCancelled, ResumeUnsafe
from pcrscript.game_ui.guide_vision import GuideText


def screen(*labels, blue=()):
    img = np.full((540, 960, 3), 245, np.uint8)
    items = []
    for text, x, y in labels:
        items.append(TextBox(text, .999, [[x-25,y-9],[x+25,y-9],[x+25,y+9],[x-25,y+9]]))
        if text in blue:
            cv.rectangle(img, (x-50,y-24), (x+50,y+24), (230,155,25), -1)
    return EventScreen(img, items)


def detail(area, floor, cleared=False, remaining=3, tickets=100, claim=False):
    ordinary = area == field.AREAS['memory']
    s = screen(('追忆战' if ordinary else '追忆战·霸', 140,30),
               (f'{area}{floor}层', 200,92), ('难度变更',850,96), ('详情',692,278),
               ('初次通关',156,320 if ordinary else 393),
               ('挑战',820,350 if ordinary else 423),
               *((('已完成',156,350 if ordinary else 421),) if cleared else ()),
               *((('宝箱详情',485,423),('领取',632,430)) if ordinary else
                 (('剩余挑战次数',517,437),(f'{remaining}/3',678,437),('券',500,346),(str(tickets),566,368))),
               blue=('挑战','领取') if claim else ('挑战',))
    if ordinary:
        if not claim:
            cv.rectangle(s.image,(618,422),(638,436),(140,140,140),-1)
    return s


def source_party(area=field.AREAS['memory'], floor=9):
    members = [empty_member(f'合成角色{i}') for i in range(5)]
    for member in members:
        for key,value in dict(level=100,rank=10,stars=5,unique=True,unique2=False,skill_level=100,instant=True).items():
            member[key].add(value,Evidence('https://example.com/synthetic',method='synthetic'))
    return finalize(dict(task_type='recollection',source='https://example.com/synthetic',scope=dict(area=area,floor=floor),
        scope_verified=True,region='cn',target_region='cn',members=members,
        auto=dict(value=True,evidence=[dict(method='synthetic')],conflicts=[])))


class Game:
    """Small observable game model; the production task decides every navigation/spend."""
    def __init__(self):
        self.page = 'adventure'
        self.area = field.AREAS['memory']
        self.floor = 9
        self.max_floor = {self.area:9,field.AREAS['kaiser']:3,field.AREAS['zen']:4}
        self.cleared = {self.area:8,field.AREAS['kaiser']:2,field.AREAS['zen']:3}
        self.remaining = {field.AREAS['kaiser']:3,field.AREAS['zen']:3,field.AREAS['miroku']:3}
        self.tickets = 100
        self.quantity = 3
        self.selected = {field.AREAS['kaiser'],field.AREAS['zen']}
        self.claim = False
        self.commits = 0
        self.claims = 0
        self.clicks = []
        self.corrupt_preview = False
        self.lose_receipt = False

    def rows(self):
        return [area for area in (field.AREAS['kaiser'],field.AREAS['zen']) if self.remaining[area]>0 and self.cleared[area]>0]

    def capture(self, **kwargs):
        if self.page == 'adventure':
            return screen(('冒险',100,30),('追忆的战场',500,135))
        if self.page == 'home':
            return screen(('追忆的战场',160,30),('追忆战',210,375),('追忆战·霸',760,375))
        if self.page == 'index':
            s=screen(('追忆战·霸',140,30),('一键扫荡',825,431),
                     *[(label,x,y) for i,(area,count) in enumerate(self.remaining.items())
                       for label,x,y in ((area,250+230*i,353),(f'{count}/3',325+230*i,385))])
            cv.rectangle(s.image,(680,240),(720,290),(25,190,240),-1)
            return s
        if self.page == 'detail':
            return detail(self.area,self.floor,self.floor<=self.cleared[self.area],
                          self.remaining.get(self.area),self.tickets,self.claim)
        if self.page == 'selector':
            ordinary=self.area==field.AREAS['memory']
            return screen(*((('难度变更',480,42),('关闭',480,480)) if ordinary else
                            (('取消',370,480),('确认',590,480))),
                          *[(f'{self.area if ordinary else ""}{n}层',480,163+96*i if ordinary else 118+52*i)
                            for i,n in enumerate(range(self.max_floor[self.area],max(0,self.max_floor[self.area]-3),-1))])
        if self.page in ('catalogue','confirmation'):
            confirm=self.page=='confirmation'
            rows=self.rows()
            chosen=[a for a in rows if a in self.selected]
            total=self.quantity*len(chosen)
            if confirm:rows=chosen
            labels=[('一键扫荡确认' if confirm else '关卡一览',480,42),('取消',370,480)]
            for i,area in enumerate(rows):
                y=(118 if confirm else 85)+65*i
                labels += [(f'{area}{self.cleared[area]}层',180,y),(f'{self.remaining[area]}/3',468,y+27)]
                if confirm:labels.append((str(self.quantity+(1 if self.corrupt_preview and i==0 else 0)),878,y+27))
            if confirm:
                labels += [('将消耗扫荡券，执行以下关卡。确定吗？',480,80),('合计扫荡次数',840,350),
                           (str(total),878,382),(f'{len(rows)}处',715,380),(str(total),250,390),
                           (str(self.tickets),440,390),('挑战',588,480)]
            else:
                labels += [('1个关卡的使用券张数',620,376),(str(self.quantity),805,376),
                           (str(self.tickets),298,392),(str(self.tickets-total),411,392),('一键扫荡',592,480)]
            s=screen(*labels,blue=('挑战','一键扫荡'))
            if not confirm:
                for i,area in enumerate(rows):
                    if area in self.selected:cv.rectangle(s.image,(835,85+65*i),(867,113+65*i),(230,155,25),-1)
            return s
        if self.page == 'receipt':
            if self.lose_receipt:return screen(('未知状态',480,40))
            return screen(('扫荡结果',480,42),('获得了以下报酬',480,85),('关闭',480,480))
        if self.page == 'claim_receipt':
            return screen(('收取报酬',480,42),('获得了以下报酬',480,85),('关闭',480,480))
        if self.page == 'formation':
            return screen(('队伍编组',480,42),('取消',710,453),('战斗开始',850,453),blue=('战斗开始',))
        if self.page == 'failed':
            return screen(('战斗失败',480,50),('伤害报告',732,39),('前往追忆战·霸',809,493))
        raise AssertionError(self.page)

    def click(self, value, **kwargs):
        name=value.text if isinstance(value,TextBox) else None
        pos=value.center if name is not None else value
        self.clicks.append((self.page,name,pos))
        if self.page=='adventure' and name=='追忆的战场':self.page='home'
        elif self.page=='home':
            if name=='追忆战':self.area=field.AREAS['memory'];self.floor=self.max_floor[self.area];self.page='detail'
            elif name=='追忆战·霸':self.page='index'
        elif self.page=='index':
            if pos==(30,30):self.page='home'
            elif name=='一键扫荡':self.page='catalogue';self.selected=set(self.rows())
            elif name in self.max_floor:self.area=name;self.floor=self.max_floor[name];self.page='detail'
        elif self.page=='detail':
            if pos==(30,30):self.page='home' if self.area==field.AREAS['memory'] else 'index'
            elif name=='难度变更':self.page='selector'
            elif name=='挑战':self.page='formation'
            elif name=='领取' and self.claim:self.claim=False;self.claims+=1;self.page='claim_receipt'
        elif self.page=='selector':
            if name in ('关闭','取消','确认'):self.page='detail'
            elif name and name.endswith('层'):
                import re
                self.floor=int(re.search(r'(\d+)层',name)[1])
                if self.area==field.AREAS['memory']:self.page='detail'
        elif self.page=='catalogue':
            if name=='取消':self.page='index'
            elif name=='一键扫荡':self.page='confirmation'
            elif pos==(731,375):self.quantity-=1
            elif pos==(883,375):self.quantity+=1
            elif pos[0]==848:
                area=self.rows()[round((pos[1]-99)/65)]
                if area in self.selected:self.selected.remove(area)
                else:self.selected.add(area)
        elif self.page=='confirmation':
            if name=='取消':self.page='catalogue'
            elif name=='挑战':
                self.commits+=1
                for area in self.selected:self.remaining[area]-=self.quantity
                self.tickets-=self.quantity*len(self.selected);self.page='receipt'
        elif self.page in ('receipt','claim_receipt') and name=='关闭':
            self.page='detail' if self.page=='claim_receipt' else 'index'
        elif self.page=='formation' and name=='取消':self.page='detail'
        elif self.page=='failed' and name=='前往追忆战·霸':self.page='index'
        else:raise AssertionError((self.page,name,pos))

    def win(self,*args):
        self.cleared[self.area]=self.floor
        if self.area!=field.AREAS['memory']:self.remaining[self.area]-=1
        self.page='detail'
        return BattleResult('settled')


class UI:
    def __init__(self,game,output):self.game=game;self.output=Path(output);self.driver=Mock()
    def capture(self,**kwargs):return self.game.capture(**kwargs)
    def click(self,*args,**kwargs):return self.game.click(*args,**kwargs)
    def swipe(self,*args):pass
    def number(self,s,roi):return s.number(roi)
    def save(self,name,s=None):return self.output/(name+'.png')


class RecollectionTests(TestCase):
    def setUp(self):
        ticks=count()
        clock=patch('pcrscript.tasks.recollection_flow.time.monotonic',side_effect=lambda:next(ticks)*.1)
        sleep=patch('pcrscript.tasks.recollection_flow.time.sleep')
        clock.start();sleep.start()
        self.addCleanup(clock.stop);self.addCleanup(sleep.stop)
        special=patch('pcrscript.game_ui.special_equipment.inspect_special_equipment',return_value=dict(unknown=0))
        special.start();self.addCleanup(special.stop)

    def make_task(self,folder,game,cls=Recollection,**options):
        robot=Robot(Mock(get_screen_size=Mock(return_value=(960,540))),show_progress=False)
        areas=options.pop('areas',['memory'] if cls.first_clear else ['kaiser','zen'])
        robot.configure({cls.config_section:dict(output=folder,account_key='synthetic',state_dir=str(Path(folder)/'state'),areas=areas,**options)})
        task=cls(robot);task.ui=UI(game,folder)
        return task

    def test_first_dominion_floor_with_disabled_selector_needs_no_click(self):
        s=detail(field.AREAS['miroku'],1)
        cv.rectangle(s.image,(790,82),(912,109),(170,160,155),-1)
        self.assertTrue(field.single_floor(s))
        with TemporaryDirectory() as root:
            task=self.make_task(root,Game(),RecollectionFirstClear,areas=['miroku'])
            task.detail=Mock(return_value=s)
            task.ui.click=Mock()
            self.assertIs(task.select_floor(field.AREAS['miroku']),s)
            task.ui.click.assert_not_called()
            with self.assertRaises(EventUIError):
                task.select_floor(field.AREAS['miroku'],2)
        self.assertFalse(field.single_floor(detail(field.AREAS['miroku'],1)))
        self.assertFalse(field.single_floor(detail(field.AREAS['kaiser'],3)))

    def test_joint_entry_labels_allow_lower_confidence_purple_navigation_card(self):
        with TemporaryDirectory() as root:
            game=Game();game.page='home'
            task=self.make_task(root,game)
            original=game.capture
            def capture(**kwargs):
                s=original(**kwargs)
                if game.page=='home':s.items[-1].score=.938
                return s
            game.capture=capture
            self.assertTrue(field.dominion_index(task.index()))
            self.assertEqual(game.page,'index')
        s=screen(('追忆的战场',160,30),('追忆战',210,375),('追忆战·霸',760,375))
        s.items[-1].score=.89
        self.assertFalse(field.home(s))

    def test_navigation_waits_for_background_transition_without_reclicking_adventure(self):
        with TemporaryDirectory() as root:
            game=Game();game.page='detail';game.area=field.AREAS['kaiser'];game.floor=3
            task=self.make_task(root,game)
            remaining=0
            original_capture,original_click=game.capture,game.click
            def capture(**kwargs):
                nonlocal remaining
                if remaining:
                    remaining-=1
                    return screen(('新内容',620,495),('冒险',537,526),('角色',190,526))
                return original_capture(**kwargs)
            def click(value,**kwargs):
                nonlocal remaining
                original_click(value,**kwargs)
                if value==(30,30):remaining=3
            game.capture,game.click=capture,click
            self.assertTrue(field.home(task.enter()))
            self.assertEqual(game.page,'home')
            self.assertEqual([pos for _,_,pos in game.clicks],[(30,30),(30,30)])
            self.assertEqual((game.commits,game.tickets),(0,100))

    def test_daily_entry_verifies_claim_sweep_and_post_spend_counters(self):
        with TemporaryDirectory() as root:
            game=Game();game.claim=True
            task=self.make_task(root,game)
            report=task.run()
            self.assertEqual(report['status'],'complete',report)
            self.assertEqual((game.claims,game.commits,game.tickets),(1,1,94))
            self.assertEqual(report['spent'],6)
            self.assertEqual(report['remaining_attempts'][field.AREAS['kaiser']],0)
            self.assertFalse(task.state)
            again=self.make_task(root,game).run()
            self.assertEqual(again['status'],'already_complete')
            self.assertEqual(game.commits,1)

    def test_budget_selects_one_domain_and_one_ticket(self):
        with TemporaryDirectory() as root:
            game=Game();task=self.make_task(root,game,max_sweeps=1)
            report=task.run()
            self.assertEqual(report['spent'],1,report)
            self.assertEqual(game.remaining[field.AREAS['kaiser']],2)
            self.assertEqual(game.remaining[field.AREAS['zen']],3)
            self.assertEqual(game.commits,1)
            self.assertEqual(report['status'],'partial')

    def test_visible_zero_attempt_row_does_not_block_other_domain_sweep(self):
        with TemporaryDirectory() as root:
            game=Game();game.remaining[field.AREAS['kaiser']]=0
            game.rows=lambda:[field.AREAS['kaiser'],field.AREAS['zen']]
            original_click=game.click
            def click(value,**kwargs):
                original_click(value,**kwargs)
                if game.page=='catalogue':game.selected.discard(field.AREAS['kaiser'])
            game.click=click
            task=self.make_task(root,game)
            report=task.run()
            self.assertEqual(report['status'],'complete',report)
            self.assertEqual((game.commits,game.tickets),(1,97))
            self.assertEqual(report['spent'],3)
            self.assertEqual(report['history'][0]['targets'],
                             [dict(area=field.AREAS['zen'],floor=3,remaining=3)])
            self.assertEqual(game.remaining[field.AREAS['kaiser']],0)
            self.assertEqual(game.remaining[field.AREAS['zen']],0)

    def test_preview_checks_final_confirmation_without_consuming_or_claiming(self):
        with TemporaryDirectory() as root:
            game=Game();game.claim=True
            task=self.make_task(root,game,preview_only=True)
            report=task.run()
            self.assertEqual(report['status'],'prepared',report)
            self.assertEqual(report['sweep_preview']['cost'],6)
            self.assertEqual((game.claims,game.commits,game.tickets),(0,0,100))
            self.assertFalse(task.state)

    def test_locked_domain_does_not_count_as_unspent_budget(self):
        with TemporaryDirectory() as root:
            game=Game()
            task=self.make_task(root,game,max_sweeps=6,areas=['kaiser','zen','miroku'])
            report=task.run()
            self.assertEqual(report['status'],'complete',report)
            self.assertEqual(report['locked_areas'],[field.AREAS['miroku']])

    def test_final_preview_mismatch_blocks_before_spend(self):
        with TemporaryDirectory() as root:
            game=Game();game.corrupt_preview=True
            task=self.make_task(root,game)
            report=task.run()
            self.assertEqual(report['status'],'blocked')
            self.assertEqual(game.commits,0)
            self.assertNotIn('pending_sweep',task.state)

    def test_lost_receipt_is_not_replayed_and_can_reconcile_exact_balances(self):
        with TemporaryDirectory() as root:
            game=Game();game.lose_receipt=True
            task=self.make_task(root,game)
            self.assertEqual(task.run()['status'],'blocked')
            self.assertEqual(game.commits,1)
            self.assertIn('pending_sweep',task.state)
            game.page='index';game.lose_receipt=False
            again=self.make_task(root,game)
            report=again.run()
            self.assertEqual(report['status'],'complete',report)
            self.assertEqual(game.commits,1)
            self.assertFalse(again.state)

    def test_pending_spend_with_wrong_balance_blocks_retry(self):
        with TemporaryDirectory() as root:
            game=Game();game.lose_receipt=True
            task=self.make_task(root,game);task.run()
            game.page='index';game.tickets+=1
            again=self.make_task(root,game)
            self.assertEqual(again.run()['status'],'blocked')
            self.assertEqual(game.commits,1)
            self.assertIn('pending_sweep',again.state)

    def test_daily_interruption_preserves_pending_spend_and_reports_terminal_state(self):
        for error, status in ((RunCancelled, 'cancelled'), (ResumeUnsafe, 'blocked')):
            with self.subTest(error=error.__name__), TemporaryDirectory() as root:
                game=Game();task=self.make_task(root,game)
                pending=dict(cost=3, targets=[dict(area=field.AREAS['kaiser'],floor=2,remaining=3)])
                task.state['pending_sweep']=pending
                task.enter=Mock(side_effect=error('synthetic interruption'))
                with self.assertRaises(error):task.run()
                saved=json.loads(task.report_path.read_text(encoding='utf-8'))
                state=json.loads(task.state_path.read_text(encoding='utf-8'))
                self.assertEqual(saved['status'],status)
                self.assertEqual(state['pending_sweep'],pending)
                self.assertEqual(game.commits,0)

    def test_blocked_domain_evidence_is_saved_before_next_source_request(self):
        with TemporaryDirectory() as root:
            game=Game()
            task=self.make_task(root,game,RecollectionFirstClear,areas=['kaiser','zen'])
            calls=[]
            def acquire(options, **kwargs):
                calls.append(options['area'])
                if len(calls)==1:
                    return dict(status='blocked',parties=[],pending=['合成来源未明确设置'])
                saved=json.loads(task.report_path.read_text(encoding='utf-8'))
                self.assertEqual(saved['areas'][field.AREAS['kaiser']],
                                 dict(status='blocked',next_floor=3))
                self.assertEqual(saved['sources'][0]['area'],field.AREAS['kaiser'])
                self.assertEqual(saved['sources'][0]['report']['pending'],['合成来源未明确设置'])
                self.assertTrue(saved['pending'])
                self.assertEqual(saved['battles'],0)
                raise RunCancelled('synthetic stop during next source request')
            with patch('pcrscript.tasks.strategy_video.acquire_strategies',side_effect=acquire):
                with self.assertRaises(RunCancelled):task.run()
            self.assertEqual(calls,[field.AREAS['kaiser'],field.AREAS['zen']])
            self.assertEqual(json.loads(task.report_path.read_text(encoding='utf-8'))['status'],'cancelled')
            self.assertEqual(game.commits,0)
            self.assertEqual(game.remaining[field.AREAS['kaiser']],3)

    def test_first_clear_uses_exact_source_then_checks_live_completed_stamp(self):
        with TemporaryDirectory() as root:
            game=Game();task=self.make_task(root,game,RecollectionFirstClear)
            task.formation=Mock()
            names=[m['name'] for m in source_party()['members']]
            task.formation.select.return_value=(True,dict(order=names))
            task.formation.inspect_current.return_value=[CharacterStatus(n,identity_verified=True) for n in names]
            task.combat=Mock(run=Mock(side_effect=game.win))
            with patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value=dict(parties=[source_party()])), \
                 patch('pcrscript.game_ui.avatar_assets.ensure_avatar_index',return_value=(Mock(),{})):
                report=task.run()
            self.assertEqual(report['status'],'complete',report)
            self.assertEqual(report['battles'],1)
            self.assertTrue(report['history'][0]['progressed'])
            self.assertEqual(game.cleared[field.AREAS['memory']],9)
            self.assertFalse(task.state)

    def test_unknown_source_settings_never_open_a_battle(self):
        with TemporaryDirectory() as root:
            game=Game();task=self.make_task(root,game,RecollectionFirstClear)
            task.combat=Mock()
            raw=source_party();raw['members'][0]['unique']['value']=None
            with patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value=dict(parties=[raw])):
                report=task.run()
            self.assertEqual(report['status'],'blocked')
            task.combat.run.assert_not_called()
            self.assertFalse(any(name=='挑战' for _,name,_ in game.clicks))

    def test_repeated_formation_evidence_keeps_separate_battle_directories(self):
        with TemporaryDirectory() as root:
            game=Game();task=self.make_task(root,game,RecollectionFirstClear)
            party=parties_for_floor(dict(parties=[source_party()]),'记忆领域',9)[0]
            names=[m.name for m in party.members]
            task.formation=Mock()
            task.formation.select.side_effect=lambda p:(True,dict(order=names,
                observed=dict(synthetic=str(task.ui.output/'equipment_synthetic.png'))))
            task.formation.inspect_current.return_value=[CharacterStatus(n,identity_verified=True) for n in names]
            def failed_once(*args):
                game.page='detail'
                return BattleResult('settled')
            task.combat=Mock(run=Mock(side_effect=failed_once))
            first=task.battle('记忆领域',9,party)
            task.combat.run.side_effect=game.win
            second=task.battle('记忆领域',9,party)
            self.assertFalse(first['progressed'])
            self.assertTrue(second['progressed'])
            self.assertNotEqual(first['formation']['observed'],second['formation']['observed'])
            self.assertEqual(task.ui.output,Path(root))
            self.assertEqual(len(json.loads((Path(root)/'report.json').read_text())['history']),2)

    def test_unknown_special_equipment_does_not_start_or_leave_pending_battle(self):
        with TemporaryDirectory() as root:
            game=Game();task=self.make_task(root,game,RecollectionFirstClear)
            party=parties_for_floor(dict(parties=[source_party()]),field.AREAS['memory'],9)[0]
            task.formation=Mock()
            task.formation.select.return_value=(True,dict(order=[m.name for m in party.members]))
            task.combat=Mock()
            with patch('pcrscript.game_ui.special_equipment.inspect_special_equipment',return_value=dict(unknown=1)):
                with self.assertRaises(EventUIError):task.battle(field.AREAS['memory'],9,party)
            task.combat.run.assert_not_called()
            self.assertNotIn('pending_battle',task.state)

    def test_auto_equip_is_optional_and_requires_known_before_and_after_slots(self):
        cases=[(False,0,0,True),(True,0,0,True),(True,1,0,False),(True,0,1,False)]
        for enabled,before_unknown,after_unknown,can_battle in cases:
            with self.subTest(auto_equip=enabled,before=before_unknown,after=after_unknown), TemporaryDirectory() as root:
                game=Game();task=self.make_task(root,game,RecollectionFirstClear,auto_equip=enabled)
                party=parties_for_floor(dict(parties=[source_party()]),field.AREAS['memory'],9)[0]
                names=[m.name for m in party.members]
                task.formation=Mock()
                task.formation.select.return_value=(True,dict(order=names))
                task.formation.inspect_current.return_value=[CharacterStatus(n,identity_verified=True) for n in names]
                task.combat=Mock(run=Mock(side_effect=game.win))
                before=dict(unknown=before_unknown,empty=15,evidence='synthetic_before.png')
                after=dict(unknown=after_unknown,empty=0,evidence='synthetic_after.png')
                with patch('pcrscript.game_ui.special_equipment.inspect_special_equipment',return_value=before), \
                     patch('pcrscript.game_ui.special_equipment.auto_equip_special',return_value=after) as equip:
                    if can_battle:
                        result=task.battle(field.AREAS['memory'],9,party)
                        self.assertTrue(result['progressed'])
                        task.combat.run.assert_called_once()
                    else:
                        with self.assertRaises(EventUIError):task.battle(field.AREAS['memory'],9,party)
                        task.combat.run.assert_not_called()
                        self.assertNotIn('pending_battle',task.state)
                    self.assertEqual(equip.call_count,int(enabled and not before_unknown))
                if enabled and not before_unknown:
                    audit=task.report['audits'][0]['formation']
                    self.assertEqual(audit['special_equipment_before'],before)
                    self.assertEqual(audit['special_equipment'],after)

    def test_unsettled_first_clear_does_not_start_another_battle(self):
        with TemporaryDirectory() as root:
            game=Game();task=self.make_task(root,game,RecollectionFirstClear)
            task.state['pending_battle']=dict(area=field.AREAS['memory'],floor=9)
            task.combat=Mock();task.save()
            self.assertEqual(task.run()['status'],'blocked')
            task.combat.run.assert_not_called()
            self.assertIn('pending_battle',task.state)

    def test_failure_result_recovers_exact_counter_without_replaying_failed_party(self):
        with TemporaryDirectory() as root:
            game=Game();game.area=field.AREAS['kaiser'];game.floor=3;game.page='failed'
            raw=source_party(game.area,game.floor)
            party=parties_for_floor(dict(parties=[raw]),game.area,game.floor)[0]
            task=self.make_task(root,game,RecollectionFirstClear,areas=['kaiser'])
            task.state['pending_battle']=dict(area=game.area,floor=3,party=party.name,attempts_before=3)
            task.save()
            task.combat=Mock()
            with patch('pcrscript.tasks.strategy_video.acquire_strategies',return_value=dict(parties=[raw])), \
                 patch('pcrscript.game_ui.avatar_assets.ensure_avatar_index',return_value=(Mock(),{})):
                report=task.run()
            self.assertEqual(report['status'],'partial',report)
            self.assertEqual(report['battles'],0)
            self.assertEqual(report['history'][0]['outcome'],'recovered_failed')
            self.assertEqual(report['history'][0]['attempts_after'],3)
            self.assertIn('result_evidence',report['history'][0])
            self.assertFalse(task.state)
            self.assertEqual((game.tickets,game.remaining[game.area]),(100,3))
            self.assertFalse(any(name=='挑战' for _,name,_ in game.clicks))
            task.combat.run.assert_not_called()

    def test_failure_result_with_changed_attempts_keeps_pending_battle(self):
        with TemporaryDirectory() as root:
            game=Game();game.area=field.AREAS['kaiser'];game.floor=3;game.page='failed'
            game.remaining[game.area]=2
            task=self.make_task(root,game,RecollectionFirstClear,areas=['kaiser'])
            task.state['pending_battle']=dict(area=game.area,floor=3,party='synthetic',attempts_before=3)
            task.save();task.combat=Mock()
            self.assertEqual(task.run()['status'],'blocked')
            self.assertIn('pending_battle',task.state)
            self.assertEqual(task.state['pending_battle']['result_outcome'],'failed')
            self.assertFalse(any(name=='挑战' for _,name,_ in game.clicks))
            task.combat.run.assert_not_called()

    def test_untracked_failure_result_is_preserved(self):
        for cls in (Recollection,RecollectionFirstClear):
            with self.subTest(task=cls.name), TemporaryDirectory() as root:
                game=Game();game.page='failed'
                task=self.make_task(root,game,cls)
                self.assertEqual(task.run()['status'],'blocked')
                self.assertEqual(game.page,'failed')
                self.assertFalse(game.clicks)


class RecognitionAndStrategyTests(TestCase):
    def test_failure_return_button_requires_visible_result_and_confident_label(self):
        s=screen(('战斗失败',480,50),('前往追忆战·霸',809,493))
        self.assertEqual(field.battle_outcome(s),'failed')
        self.assertEqual(field.battle_result_button(s).text,'前往追忆战·霸')
        self.assertIsNone(field.battle_result_button(screen(('前往追忆战·霸',809,493))))
        self.assertIsNone(field.battle_result_button(screen(('战斗失败',480,50),('前往追忆战·霸',809,250))))
        s.items[-1].score=.94
        self.assertIsNone(field.battle_result_button(s))
        s.items[0].score=.94
        self.assertIsNone(field.battle_outcome(s))

    def test_unknown_badge_refreshes_full_party_after_character_page(self):
        task=object.__new__(RecollectionFirstClear)
        party=parties_for_floor(dict(parties=[source_party()]),'记忆领域',9)[0]
        unknown=CharacterStatus(party.members[0].name,identity_verified=True)
        task.formation=Mock(observed={unknown.name:unknown})
        task.formation.select.side_effect=[(False,dict(unready=[dict(character=unknown.name,reasons=['装备未知'])])),
                                           (True,dict(order=[m.name for m in party.members]))]
        task.ui=Mock();task.robot=Mock()
        task.capture=Mock();task.click=Mock();task.wait=Mock();task.check_deadline=Mock();task.report_progress=Mock()
        task.select_floor=Mock(return_value=detail('记忆领域',9))
        with patch('pcrscript.game_ui.character_equipment.inspect_unreleased_equipment',return_value=None), \
             patch('pcrscript.tasks.task_home.ToHomePage'):
            ready,details=task.select_party('记忆领域',9,party)
        self.assertTrue(ready)
        self.assertEqual(details['order'],[m.name for m in party.members])
        self.assertEqual(task.formation.select.call_count,2)

    def test_compilation_context_requires_hp_countdown_and_observed_detail(self):
        context=RecollectionScopeContext()
        scope=dict(area=field.AREAS['kaiser'],floor=3)
        def labels(*values):return [GuideText(text,1,(0,0,100,20)) for text in values]
        proof=dict(source='https://example.com/synthetic',image='synthetic.jpg')
        context.resolve(scope,True,labels('难度变更','80000000/80000000'),0,False,proof)
        linked=context.resolve({},False,labels('队伍编组','战斗开始'),2,False,proof)
        self.assertEqual(linked[:2],(scope,True))
        self.assertFalse(context.resolve({},False,labels('角色详情','确认'),3,False,proof)[1])
        linked=context.resolve({},False,labels('79700000/80000000','1:26'),5,True,proof)
        self.assertEqual(linked[:2],(scope,True))
        self.assertEqual(linked[2]['image'],'synthetic.jpg')
        self.assertFalse(context.resolve({},False,[],8,True,proof)[1])
        self.assertTrue(context.resolve({},False,labels('78000000/80000000','1:20'),10,True,proof)[1])
        # A restarted timer can belong to a different unlabelled fight.
        self.assertFalse(context.resolve({},False,labels('78000000/80000000','1:29'),12,True,proof)[1])
        self.assertFalse(context.resolve({},False,labels('78000000/80000000','1:15'),15,True,proof)[1])
        context.resolve(scope,True,labels('难度变更','80000000/80000000'),20,False,proof)
        self.assertFalse(context.resolve({},False,labels('59000000/60000000','1:26'),25,True,proof)[1])
        context.resolve(scope,True,labels('难度变更','80000000/80000000'),30,False,proof)
        self.assertFalse(context.resolve({},False,labels('80000000/80000000','1:26'),46,True,proof)[1])
        context.resolve(scope,True,labels('难度变更','80000000/80000000'),50,False,proof)
        context.resolve({},False,labels('WIN!'),52,False,proof)
        self.assertFalse(context.resolve({},False,labels('80000000/80000000','1:26'),54,True,proof)[1])

    def test_compilation_context_preserves_only_known_prebattle_equipment_navigation(self):
        scope=dict(area=field.AREAS['miroku'],floor=1)
        proof=dict(source='https://example.com/synthetic',image='synthetic_detail.jpg')
        def labels(*values):return [GuideText(text,1,(0,0,100,20)) for text in values]
        equipment=labels('特别装备设定','可变更队伍角色的特别装备。','取消','装备确定')
        for valid,delay in ((True,10),(False,10),(True,16)):
            with self.subTest(valid=valid,delay=delay):
                context=RecollectionScopeContext()
                context.resolve(scope,True,labels('难度变更','80000000/80000000'),0,False,proof)
                context.resolve({},False,labels('队伍编组','战斗开始'),2,False,proof)
                # A title alone cannot keep scope through an unknown page.
                self.assertFalse(context.resolve({},False,equipment if valid else equipment[:1],3,False,proof)[1])
                formation=context.resolve({},False,labels('队伍编组','当前的成员','取消'),5,False,proof)
                self.assertEqual(formation[1],valid)
                linked=context.resolve({},False,labels('79700000/80000000','1:26'),delay,True,proof)
                self.assertEqual(linked[1],valid and delay<=15)
                if linked[1]:
                    self.assertEqual(linked[0],scope)
                    self.assertEqual(linked[2]['image'],proof['image'])

    def test_client_region_uses_two_controls_in_their_game_positions(self):
        cn=[GuideText('队伍编组',1,(500,10,260,50)),GuideText('战斗开始',1,(1050,580,120,40))]
        self.assertEqual(recollection_client_region(cn),'cn')
        self.assertEqual(recollection_client_region([cn[0]]),'unknown')
        self.assertEqual(recollection_client_region([GuideText(t.text,1,(0,250,100,30)) for t in cn]),'unknown')
        tw=[GuideText('隊伍編組',1,(500,10,260,50)),GuideText('戰鬥開始',1,(1050,580,120,40))]
        self.assertEqual(recollection_client_region(tw),'tw')

    def test_ranges_and_ambiguous_targets_are_not_exact_floors(self):
        for text in ('日常1~8','记忆领域9-12层','霸瞳1～5','记忆领域9层 泽恩3层',
                     '记忆领域9层和记忆领域10层','记忆领域9层-12层',
                     '记忆领域9层、10层','记忆领域9层到12层','追忆战9~12层 霸瞳3层'):
            self.assertEqual(field.text_scope(text),{},text)
        self.assertEqual(field.text_scope('记忆领域9层'),dict(area='记忆领域',floor=9))
        self.assertEqual(field.text_scope('国服霸瞳3层AUTO'),dict(area=field.AREAS['kaiser'],floor=3))

    def test_completed_stamp_and_unknown_red_stamp(self):
        self.assertIs(field.clear_status(detail('记忆领域',9)),False)
        self.assertIs(field.clear_status(detail('记忆领域',8,True)),True)
        s=detail('记忆领域',8)
        cv.rectangle(s.image,(120,330),(210,390),(30,30,230),-1)
        self.assertIsNone(field.clear_status(s))

    def test_claim_control_requires_readable_enabled_or_disabled_ink(self):
        self.assertIs(field.claim_enabled(detail('记忆领域',9,claim=False)),False)
        self.assertIs(field.claim_enabled(detail('记忆领域',9,claim=True)),True)
        self.assertIsNone(field.claim_enabled(detail(field.AREAS['kaiser'],3)))
        # A white control with strongly colored text has not been verified.
        unknown=detail('记忆领域',9)
        cv.rectangle(unknown.image,(618,422),(638,436),(30,60,120),-1)
        self.assertIsNone(field.claim_enabled(unknown))

    def test_counts_conflicts_and_low_confidence_are_unknown(self):
        s=detail(field.AREAS['kaiser'],3)
        self.assertEqual(field.detail_attempts(s),3)
        s.items.extend(screen(('2/3',660,430)).items)
        self.assertIsNone(field.detail_attempts(s))
        s=detail(field.AREAS['kaiser'],3);s.items[-3].score=.5
        self.assertIsNone(field.detail_attempts(s))

    def test_sources_scope_isolated_by_domain_and_floor(self):
        raw=source_party()
        self.assertEqual(len(parties_for_floor(dict(parties=[raw]),'记忆领域',9)),1)
        self.assertEqual(parties_for_floor(dict(parties=[raw]),'记忆领域',8),[])
        self.assertEqual(parties_for_floor(dict(parties=[raw]),field.AREAS['kaiser'],9),[])
        labels=[GuideText('记忆领域9层',1,(30,70,300,30))]
        self.assertEqual(observed_scope(labels,dict(part='日常9~12'),'recollection'),(dict(area='记忆领域',floor=9),True))
        self.assertEqual(observed_scope(labels,dict(part='日常10层'),'recollection'),({'conflict':True},False))
        self.assertFalse(observed_scope([],dict(part='日常9~12'),'recollection')[1])

    def test_collection_metadata_nominates_only_correct_domain_pages(self):
        options=task_source_options('recollection',{},area='记忆领域',stage=9)
        source=dict(title='国服公主连结追忆战',pages=[dict(cid=5,part='日常1~4'),dict(cid=6,part='日常5~8'),
            dict(cid=1,part='日常9~12'),dict(cid=2,part='霸瞳1~5')])
        self.assertEqual([p['cid'] for p in choose_pages(source,options)],[1])
        bare=dict(title='国服公主连结追忆战1~12层',pages=[dict(cid=3,part='第9层'),dict(cid=4,part='第10层')])
        chosen=choose_pages(bare,options)
        self.assertEqual([p['cid'] for p in chosen],[3])
        self.assertEqual(observed_scope([],chosen[0],'recollection'),({},False))

    def test_scoped_requirements_do_not_contaminate_other_floors_or_domains(self):
        source=dict(title='公主连结追忆战合集',pages=[
            dict(cid=1,part='9-12练度参考MP60'),dict(cid=2,part='泽恩练度'),
            dict(cid=3,part='通用培养'),dict(cid=4,part='霸瞳1-3层'),dict(cid=5,part='日常9-12')])
        options=task_source_options('recollection',{},area=field.AREAS['kaiser'],stage=3)
        self.assertEqual([p['cid'] for p in choose_pages(source,options)],[3,4])
        options=task_source_options('recollection',{},area=field.AREAS['memory'],stage=9)
        self.assertEqual([p['cid'] for p in choose_pages(source,options)],[1,3,5])

    def test_discovery_reviews_target_inside_a_same_domain_range(self):
        from pcrscript.tasks.strategy_sources import discover_sources
        with TemporaryDirectory() as folder:
            api=Mock()
            api.search.return_value={'code':0,'data':{'result':[{'result_type':'video','data':[
                {'bvid':'BV0000000000','title':'公主连结 国服 追忆战 日常9~12'}]}]}}
            api.getVideoInfo.return_value={'code':0,'data':{'bvid':'BV0000000000',
                'title':'公主连结 国服 追忆战 日常9~12','pages':[{'cid':1,'part':'日常9~12'}]}}
            options=task_source_options('recollection',{'sources':{'cache_dir':folder}},area='记忆领域',stage=11)
            found=discover_sources(options,api=api)
            self.assertEqual(len(found['candidates']),1)
            # A range title cannot supply floor 11 to an unlabelled frame.
            self.assertEqual(observed_scope([],found['candidates'][0]['pages'][0],'recollection'),({},False))

    def test_discovery_rechecks_a_recent_compilation_from_another_domain(self):
        from pcrscript.tasks.strategy_sources import discover_sources
        with TemporaryDirectory() as folder:
            video=dict(bvid='BV0000000000',title='公主连结 国服 追忆战合集',
                       pages=[dict(cid=1,part='泽恩4-5')])
            previous=dict(scope=dict(task_type='recollection',area=field.AREAS['kaiser']),
                          fetched_at=time.time(),candidates=[dict(video,pages=[dict(title='泽恩4-5')])])
            (Path(folder)/'synthetic-other-domain.json').write_text(json.dumps(previous),encoding='utf-8')
            api=Mock();api.search.return_value=dict(code=0,data=dict(result=[]))
            api.getVideoInfo.return_value=dict(code=0,data=video)
            options=task_source_options('recollection',{'sources':{'cache_dir':folder}},area=field.AREAS['zen'],stage=4)
            report=discover_sources(options,api=api)
            self.assertEqual([p['bvid'] for p in report['candidates']],['BV0000000000'])
            api.getVideoInfo.assert_called_once_with(bvid='BV0000000000')

    def test_synthetic_video_produces_only_the_observed_floor_party(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),2,(960,540))
            for i in range(10):writer.write(np.full((540,960,3),30+i,np.uint8))
            writer.release()
            members=[dict(name='角色'+str(i),rectangle=[190+i*120,390,100,100],score=.99) for i in range(5)]
            labels=[GuideText('记忆领域9层',1,(30,70,200,30))]+[
                GuideText('角色'+str(i)+':5星Lv100Rank10技能100专武1有专武2无SET开',1,(0,0,100,20)) for i in range(5)]
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',title='公主连结 国服',
                        pages=[dict(cid=1,part='日常9~12',duration=5)])
            index=SimpleNamespace(names=[m['name'] for m in members],matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.read_text',return_value=labels), \
                 patch('pcrscript.tasks.strategy_video.combat_team',return_value=members), \
                 patch('pcrscript.tasks.strategy_video.combat_auto',return_value=True):
                report=parse_video_source(source,dict(task_type='recollection',area='记忆领域',stage='9',
                    parsed_dir=folder),index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
                restricted=parse_video_source(dict(source,description='本关需要特别装备与MP60'),
                    dict(task_type='recollection',area='记忆领域',stage='9',parsed_dir=folder),index,
                    api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual(len(parties_for_floor(report,'记忆领域',9)),1)
            self.assertEqual(parties_for_floor(report,'记忆领域',10),[])
            self.assertTrue(restricted['parties'][0]['global_requirements'])
            self.assertEqual(parties_for_floor(restricted,'记忆领域',9),[])
            self.assertEqual(parties_for_floor(restricted,'记忆领域',9,allow_local_trials=True),[])

    def test_compilation_parser_stops_linking_teams_after_a_result(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),1,(960,540))
            for i in range(14):writer.write(np.full((540,960,3),30+i*10,np.uint8))
            writer.release()
            members=[dict(name='角色'+str(i),rectangle=[190+i*120,390,100,100],score=.99) for i in range(5)]
            different=[dict(m,name='另一个角色'+str(i)) for i,m in enumerate(members)]
            def text_rows(*values):return [GuideText(t,1,(0,0,100,20)) for t in values]
            observations={
                0:[GuideText('霸瞳皇帝的领域3层',1,(30,70,300,30)),
                   GuideText('难度变更',1,(1050,80,120,40)),
                   GuideText('初次通关',1,(150,420,150,30)),*text_rows('80000000/80000000')],
                2:text_rows('队伍编组','战斗开始'),
                4:text_rows('79700000/80000000','1:26'),
                6:text_rows('78000000/80000000','1:20'),
                8:text_rows('WIN!'),
                10:text_rows('79000000/80000000','1:25'),
                12:text_rows('77000000/80000000','1:18'),
            }
            def moment(frame):return round((float(frame.mean())-30)/10)
            def teams(frame,*args,**kwargs):
                second=moment(frame)
                return members if second in (4,6) else different if second in (10,12) else []
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',title='公主连结追忆战合集',
                        pages=[dict(cid=1,part='霸瞳1~5',duration=14)])
            index=SimpleNamespace(names=[m['name'] for m in members+different],matrix=np.ones((10,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.sample_seconds',return_value=list(observations)), \
                 patch('pcrscript.tasks.strategy_video.frame_texts',side_effect=lambda f,p,o:observations[moment(f)]), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles',side_effect=lambda f,**k:[m['rectangle'] for m in teams(f)]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',side_effect=teams), \
                 patch('pcrscript.tasks.strategy_video.formation_team',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_caption_signature',return_value=frozenset()), \
                 patch('pcrscript.tasks.strategy_video.combat_hud_visible',return_value=False), \
                 patch('pcrscript.tasks.strategy_video.combat_set',return_value=True), \
                 patch('pcrscript.tasks.strategy_video.combat_auto',return_value=True):
                report=parse_video_source(source,dict(task_type='recollection',area=field.AREAS['kaiser'],stage='3',
                    parsed_dir=folder),index,api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=14)))
            self.assertEqual(len(report['parties']),1)
            party=report['parties'][0]
            self.assertEqual([m['name'] for m in party['members']],[m['name'] for m in members])
            self.assertEqual([f['seconds'] for f in party['frames']],[4,6])
            self.assertEqual(party['scope_evidence'][0]['seconds'],0)
            self.assertEqual(len(parties_for_floor(report,field.AREAS['kaiser'],3,allow_local_trials=True)),1)

    def test_separated_floor_parts_and_timestamp_named_collection_keep_scope_safe(self):
        options=task_source_options('recollection',{},area=field.AREAS['miroku'],stage=1)
        source=dict(title='公主连结 米洛克合集',pages=[
            dict(cid=1,part='米洛克-1'),dict(cid=2,part='米洛克-2'),
            dict(cid=3,part='米洛克1~3层')])
        chosen=choose_pages(source,options)
        self.assertEqual(chosen[0]['cid'],1)
        self.assertNotIn(2,[p['cid'] for p in chosen])
        self.assertEqual(field.text_scope('米洛克-1'),dict(area=field.AREAS['miroku'],floor=1))
        self.assertEqual(field.text_scope('米洛克-1~3层'),{})
        source=dict(title='公主连结 米洛克1~3层自动刀',pages=[dict(cid=4,part='1786705607416')])
        chosen=choose_pages(source,options)
        self.assertEqual(chosen,source['pages'])
        self.assertEqual(observed_scope([],chosen[0],'recollection'),({},False))
        self.assertEqual(choose_pages(source,dict(options,stage='4')),[])

    def test_single_domain_collection_nominates_bare_ranges_without_assigning_floor(self):
        options=task_source_options('recollection',{},area=field.AREAS['miroku'],stage=1)
        source=dict(title='公主连结 米洛克1~5层AUTO',pages=[
            dict(cid=1,part='火物1~3'),dict(cid=2,part='(纯SET)1~3(暗法)'),
            dict(cid=3,part='光物4~5'),dict(cid=4,part='泽恩1~3')])
        chosen=choose_pages(source,options)
        self.assertEqual([p['cid'] for p in chosen],[1,2])
        for page in chosen:
            self.assertEqual(observed_scope([],page,'recollection'),({},False))
        self.assertEqual([p['cid'] for p in choose_pages(source,dict(options,stage='4'))],[3])
        self.assertEqual(choose_pages(dict(source,title='公主连结 米洛克及泽恩合集'),options),[])
        self.assertEqual([p['cid'] for p in choose_pages(
            dict(source,title='公主连结 追忆战·霸 米洛克1~5层AUTO'),options)],[1,2])
        self.assertEqual(choose_pages(dict(source,title='公主连结 追忆战1~12 米洛克1~5'),options),[])

    def test_local_trials_preserve_unknown_builds_and_reject_unknown_rules(self):
        raw=source_party();raw['members'][0]['rank']['value']=None
        self.assertEqual(parties_for_floor(dict(parties=[raw]),'记忆领域',9),[])
        self.assertEqual(len(parties_for_floor(dict(parties=[raw]),'记忆领域',9,allow_local_trials=True)),1)
        for key,value in [('region','unknown'),('global_requirements',[dict(text='属性等级')]),('manual_actions',[dict(text='手动')])]:
            changed=deepcopy(raw);changed[key]=value
            self.assertEqual(parties_for_floor(dict(parties=[changed]),'记忆领域',9,allow_local_trials=True),[])
        formation=RecollectionFormation(Mock());formation.use_current_build=True
        requirement=parties_for_floor(dict(parties=[raw]),'记忆领域',9,allow_local_trials=True)[0].members[0]
        actual=CharacterStatus(requirement.name,100,10,5,None,False,100,identity_verified=True)
        self.assertIn('账号培养或装备未明确：unique',formation.member_readiness(requirement,actual))

    def test_fixed_auto_off_is_preserved_for_complete_guides_and_audited_trials(self):
        raw=source_party();raw['auto']['value']=False
        party=parties_for_floor(dict(parties=[raw]),'记忆领域',9)[0]
        self.assertIs(party.auto,False)
        raw['members'][0]['rank']['value']=None
        self.assertEqual(parties_for_floor(dict(parties=[raw]),'记忆领域',9),[])
        party=parties_for_floor(dict(parties=[raw]),'记忆领域',9,allow_local_trials=True)[0]
        self.assertIs(party.auto,False)
        for value,conflicts,evidence in ((None,[],[{}]),(False,[dict(value=True)],[{}]),(False,[],[])):
            raw['auto'].update(value=value,conflicts=conflicts,evidence=evidence)
            self.assertEqual(parties_for_floor(dict(parties=[raw]),'记忆领域',9,allow_local_trials=True),[])

    def test_options_validate_before_device_and_do_not_mutate_chinese_scope(self):
        raw=dict(areas=['记忆领域'])
        self.assertEqual(validate_options(raw,first_clear=True)['areas'],['memory'])
        self.assertEqual(raw,dict(areas=['记忆领域']))
        for cls,options in ((Recollection,dict(max_sweeps=True)),(Recollection,dict(areas=['memory'])),
                            (RecollectionFirstClear,dict(areas=[{}])),(RecollectionFirstClear,dict(max_attempts_per_stage=0))):
            with self.assertRaises(ValueError):cls.prepare({cls.config_section:options})
