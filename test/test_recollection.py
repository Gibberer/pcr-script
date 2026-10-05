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
from pcrscript.tasks.event_battle import BattleResult, EventCombat
from pcrscript.tasks.recollection_flow import validate_options
from pcrscript.tasks.recollection_strategy import parties_for_floor, RecollectionFormation
from pcrscript.tasks.strategy_document import Evidence, empty_member, finalize
from pcrscript.tasks.strategy_video import (choose_pages, observed_scope, task_source_options,
    parse_video_source, RecollectionScopeContext, recollection_client_region, live_target_scope)
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


class LiveTargetTests(TestCase):
    def test_diagnostic_hp_does_not_treat_truncated_digits_as_a_new_maximum(self):
        from pcrscript.tasks.abyss_retry import combat_sample
        s = screen(('1:20',800,25),('8/8',650,80))
        sample = combat_sample(s, [], maximum_hp=80000000)
        self.assertEqual(sample['seconds'],80)
        self.assertIsNone(sample['hp'])
        self.assertIsNone(sample['max_hp'])
        s.items[1].text = '70000000/80000000'
        self.assertEqual(combat_sample(s, [], maximum_hp=80000000)['hp'],70000000)

    def test_combat_observation_persists_without_settling_or_authorizing_retry(self):
        task = object.__new__(RecollectionFirstClear)
        task.state = dict(pending_battle=dict(attempts_before=3))
        task._next_sample = 0
        task.combat = Mock(portraits=[])
        task.ui = Mock()
        task.ui.save.return_value = Path('synthetic.png')
        task.save = Mock()
        frame = screen(('未知画面', 480, 50))
        with patch('pcrscript.tasks.task_recollection_first_clear.combat_sample',
                   side_effect=[None, dict(seconds=80, hp=50, max_hp=100, dark_portraits=0)]), \
             patch('pcrscript.tasks.task_recollection_first_clear.time.monotonic', return_value=10):
            task.observe_battle(frame)
            task.save.assert_not_called()
            task.observe_battle(frame)
            task.observe_battle(frame)
        task.save.assert_called_once()
        pending = task.state['pending_battle']
        self.assertEqual(pending['samples'][0]['hp'], 50)
        self.assertEqual(pending['samples'][0]['evidence'], 'synthetic.png')
        self.assertEqual(pending['attempts_before'], 3)
        self.assertNotIn('outcome', pending)

    def test_battle_start_observation_is_saved_even_when_sampling_is_throttled(self):
        task = object.__new__(RecollectionFirstClear)
        task.state = dict(pending_battle=dict(submitted=True, submission_tracked=True))
        task._next_sample = float('inf')
        task.ui = Mock(save=Mock(return_value=Path('synthetic.png')))
        task.save = Mock()
        task.observe_battle(screen(('1:20', 800, 25), ('菜单', 900, 25)))
        self.assertEqual(task.state['pending_battle']['battle_started'], 'synthetic.png')
        self.assertFalse(task.unstarted_battle(task.state['pending_battle']))
        task.save.assert_called_once()

    def test_live_signature_requires_detail_floor_name_level_and_full_health(self):
        s = detail(field.AREAS['miroku'], 1)
        s.items += screen(('合成首领',265,259),('等级.100',340,259),
                          ('80000000/80000000',550,295)).items
        expected = dict(scope=dict(area=field.AREAS['miroku'], floor=1),
                        boss='合成首领', level=100, maximum_hp=80000000)
        self.assertEqual(field.boss_signature(s), expected)
        s.items[-1].text = '70000000/80000000'
        self.assertIsNone(field.boss_signature(s))
        s.items[-1].text = '80000000/80000000'; s.items[-2].score = .94
        self.assertIsNone(field.boss_signature(s))

    def test_combat_target_requires_matching_name_level_health_and_timer(self):
        target = dict(scope=dict(area=field.AREAS['miroku'], floor=1),
                      boss='合成首领', level=100, maximum_hp=80000000, image='live_target.png')
        proof = dict(source='https://example.com/synthetic', image='guide.png')
        labels = [GuideText(text, .99, (100, 10, 250, 20))
                  for text in ('合成首领等级.100', '79000000/80000000', '1:25')]
        scope, verified, evidence = live_target_scope(labels, target, proof)
        self.assertEqual(scope, target['scope']); self.assertTrue(verified)
        self.assertEqual(evidence['target']['image'], 'live_target.png')
        self.assertEqual(evidence['image'], 'guide.png')
        for changed in ('其他首领等级.100', '合成首领等级.101'):
            self.assertFalse(live_target_scope([GuideText(changed,.99,(0,10,200,20))]+labels[1:],target,proof)[1])
        for changed in ('79000000/90000000', '90000000/80000000'):
            self.assertFalse(live_target_scope([labels[0],GuideText(changed,.99,(0,10,200,20)),labels[2]],target,proof)[1])
        self.assertFalse(live_target_scope(labels[:-1],target,proof)[1])
        self.assertFalse(live_target_scope(labels,dict(target,image=''),proof)[1])
        self.assertFalse(live_target_scope([GuideText(t.text,.94,t.rectangle) for t in labels],target,proof)[1])

    def test_ordinary_signature_reads_long_boss_name_and_level_without_weakness(self):
        s=detail(field.AREAS['memory'],9)
        s.items+=screen(('合成首领（多部位）',323,258),('等级.100',446,258),
                        ('弱点',539,258),('80000000/80000000',552,295)).items
        signature=field.boss_signature(s)
        self.assertEqual(signature,dict(scope=dict(area=field.AREAS['memory'],floor=9),
            boss='合成首领(多部位)',level=100,maximum_hp=80000000))
        for index in (1,-4,-3,-1):
            uncertain=deepcopy(s);uncertain.items[index].score=.94
            self.assertIsNone(field.boss_signature(uncertain))
        # Weakness text is a separate field, never part of the target identity.
        s.items[-2].score=.83
        self.assertEqual(field.boss_signature(s),signature)
        s.items[-1].text='70000000/80000000'
        self.assertIsNone(field.boss_signature(s))

    def test_live_target_evidence_always_requires_explicit_account_trials(self):
        raw = source_party(field.AREAS['miroku'], 1)
        raw['scope_evidence'] = [dict(method='combat_matches_live_target')]
        report = dict(parties=[raw])
        self.assertEqual(parties_for_floor(report,field.AREAS['miroku'],1), [])
        party = parties_for_floor(report,field.AREAS['miroku'],1,allow_local_trials=True)[0]
        self.assertEqual(party.build_basis, 'local_trial')
        self.assertTrue(party.assumptions)
        options = task_source_options('recollection', dict(sources=dict(observed_target=dict(fake=True))),
                                      area=field.AREAS['miroku'], stage=1)
        self.assertNotIn('observed_target', options)

    def test_separate_hud_name_and_level_must_be_adjacent_and_same_row(self):
        target = dict(scope=dict(kind='boss', difficulty='普通', boss='合成首领'),
                      boss='合成首领', level=100, maximum_hp=80000000, image='live.png')
        header = [GuideText('合成首领', .99, (0, 10, 120, 20)),
                  GuideText('等级.100', .99, (125, 10, 80, 20)),
                  GuideText('80000000/80000000', .99, (210, 10, 240, 20)),
                  GuideText('1:29', .99, (1100, 10, 80, 20))]
        self.assertTrue(live_target_scope(header, target, dict(image='source.png'))[1])
        for rectangle in ((170, 10, 80, 20), (125, 25, 80, 20), (125, 140, 80, 20)):
            invalid = header[:1] + [GuideText('等级.100', .99, rectangle)] + header[2:]
            self.assertFalse(live_target_scope(invalid, target, dict(image='source.png'))[1])

    def test_short_combat_gets_two_confirmations_without_exceeding_frame_budget(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as folder:
            path=Path(folder)/'short-combat.avi'
            writer=cv.VideoWriter(str(path),cv.VideoWriter_fourcc(*'MJPG'),4,(960,540))
            for i in range(80):writer.write(np.full((540,960,3),30+i,np.uint8))
            writer.release()
            members=[dict(name='合成角色'+str(i),rectangle=[190+i*120,390,100,100],score=.99) for i in range(5)]
            def tick(frame):return round(float(frame.mean())-30)
            def labels(frame,*args):
                if tick(frame)==0:
                    return [GuideText('队伍编组',1,(400,20,200,30)),GuideText('战斗开始',1,(1080,600,150,30))]
                return [GuideText(t,1,(100,10,300,20)) for t in ('合成首领等级.100','80000000/80000000','1:29')]
            def team(frame,*args,**kwargs):return members if 16<=tick(frame)<=18 else []
            source=dict(bvid='BV0000000000',url='https://example.com/synthetic',
                title='公主连结 米洛克1~3层自动刀',pages=[dict(cid=1,part='合成合集',duration=20)])
            target=dict(scope=dict(area=field.AREAS['miroku'],floor=1),boss='合成首领',
                        level=100,maximum_hp=80000000,image='live.png')
            options=dict(task_type='recollection',area=field.AREAS['miroku'],stage='1',
                         parsed_dir=folder,observed_target=target,max_frames_per_page=5)
            index=SimpleNamespace(names=[m['name'] for m in members],matrix=np.ones((5,1728),np.float32))
            with patch('pcrscript.tasks.strategy_video.sample_seconds',side_effect=lambda *a,**k:[0,4,8,12,16]), \
                 patch('pcrscript.tasks.strategy_video.frame_texts',side_effect=labels), \
                 patch('pcrscript.tasks.strategy_video.battle_rectangles',side_effect=lambda f,**k:[m['rectangle'] for m in team(f)]), \
                 patch('pcrscript.tasks.strategy_video.combat_team',side_effect=team), \
                 patch('pcrscript.tasks.strategy_video.formation_team',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.formation_fields',return_value=[]), \
                 patch('pcrscript.tasks.strategy_video.combat_caption_signature',return_value=frozenset()), \
                 patch('pcrscript.tasks.strategy_video.combat_hud_visible',return_value=False), \
                 patch('pcrscript.tasks.strategy_video.combat_set',return_value=True), \
                 patch('pcrscript.tasks.strategy_video.combat_auto',return_value=True):
                report=parse_video_source(source,options,index,api=Mock(),ocr=Mock(),
                                          media_fetcher=lambda *a,**k:(path,dict(duration=20)))
                # The mocked OCR worker does not save frames. Supply the
                # synthetic evidence files required by the real cache gate.
                for member in report['parties'][0]['members']:
                    for key in ('stars','unique','unique2','instant'):
                        for proof in member[key].get('evidence',[]):
                            if proof.get('image'):
                                cv.imwrite(proof['image'],np.zeros((540,960,3),np.uint8))
                fresh=parse_video_source(source,dict(options,observed_target=dict(target,image='new_run.png')),index,
                    api=Mock(),ocr=Mock(),media_fetcher=Mock(side_effect=AssertionError('same target should reuse source media')))
                no_proof=parse_video_source(source,dict(options,observed_target=dict(target,image='')),index,
                    api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=20)))
                changed=parse_video_source(source,dict(options,observed_target=dict(target,level=101)),index,
                    api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=20)))
            self.assertEqual(len(parties_for_floor(report,field.AREAS['miroku'],1,allow_local_trials=True)),1)
            self.assertEqual([f['seconds'] for f in report['parties'][0]['frames']],[4,4.25,4.5])
            self.assertEqual(report['pages'][0]['frames'],5)
            self.assertTrue(fresh['cache_hit'])
            self.assertEqual(fresh['parties'][0]['scope_evidence'][0]['target']['image'],'new_run.png')
            self.assertEqual(report['parties'][0]['scope_evidence'][0]['target']['image'],'live.png')
            self.assertEqual(parties_for_floor(no_proof,field.AREAS['miroku'],1,allow_local_trials=True),[])
            self.assertEqual(parties_for_floor(changed,field.AREAS['miroku'],1,allow_local_trials=True),[])



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
        self.native_sweep_summary = False

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
        if self.page == 'sweep_summary':
            total=self.quantity*len(self.selected)
            return screen(('扫荡结果',480,42),(f'扫荡次数{total}次',480,91),
                          (f'{total}只击破！',480,136),('确认',480,480))
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
                self.tickets-=self.quantity*len(self.selected)
                self.page='sweep_summary' if self.native_sweep_summary else 'receipt'
        elif self.page=='sweep_summary' and name=='确认':
            self.page='receipt'
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


class BattleDispatchGame(Game):
    """Known target and start-input boundary, with no live device or assets."""
    def __init__(self, area):
        super().__init__()
        self.area = area
        self.floor = self.max_floor[area]
        self.starts = 0

    def capture(self, **kwargs):
        if self.page == 'battle':
            return screen(('1:20', 800, 25), ('菜单', 900, 25))
        value = super().capture(**kwargs)
        if self.page == 'detail':
            value.items += screen(('合成首领', 265, 259), ('等级.100', 340, 259),
                                  ('80000000/80000000', 550, 295)).items
        return value

    def click(self, value, **kwargs):
        if self.page == 'formation' and getattr(value, 'text', '') == '战斗开始':
            self.clicks.append((self.page, value.text, value.center))
            self.starts += 1
            self.page = 'battle'
        else:
            super().click(value, **kwargs)


class RecollectionTests(TestCase):
    def test_native_sweep_summary_then_rewards_settles_one_bounded_sweep(self):
        with TemporaryDirectory() as root:
            game=Game();game.native_sweep_summary=True
            task=self.make_task(root,game,areas=['kaiser'],max_sweeps=1)
            report=task.run()
            self.assertEqual((report['status'],report['spent']),('partial',1),report)
            self.assertEqual((game.commits,game.tickets,game.remaining[field.AREAS['kaiser']]),(1,99,2))
            self.assertIn('summary_receipt',report['history'][0])
            self.assertNotIn('pending_sweep',task.state)

    def test_interrupted_native_summary_recovers_without_second_sweep(self):
        for areas,budget in ((['kaiser'],1),(['kaiser','zen'],6)):
            with self.subTest(areas=areas,budget=budget),TemporaryDirectory() as root:
                game=Game();game.native_sweep_summary=True
                original=game.click
                def interrupt(value,**kwargs):
                    if game.page=='sweep_summary':
                        raise EventUIError('synthetic interruption before closing summary')
                    return original(value,**kwargs)
                game.click=interrupt
                first=self.make_task(root,game,areas=areas,max_sweeps=budget)
                self.assertEqual(first.run()['status'],'blocked')
                self.assertIn('pending_sweep',first.state)
                self.assertEqual((game.commits,game.tickets),(1,100-budget))
                game.click=original
                recovered=self.make_task(root,game,areas=areas,sweep_dominion=False,claim_rewards=False)
                report=recovered.run()
                self.assertEqual((report['status'],report['spent']),('complete',budget),report)
                self.assertEqual((game.commits,game.tickets),(1,100-budget))
                self.assertNotIn('pending_sweep',recovered.state)

    def test_multiple_dominion_summary_settles_aggregate_executions_and_defeats(self):
        with TemporaryDirectory() as root:
            game=Game();game.native_sweep_summary=True
            task=self.make_task(root,game,max_sweeps=6)
            report=task.run()
            self.assertEqual((report['status'],report['spent']),('complete',6),report)
            self.assertEqual((game.commits,game.tickets),(1,94))
            self.assertEqual([game.remaining[field.AREAS[key]] for key in ('kaiser','zen')],[0,0])
            self.assertEqual((report['history'][0]['quantity'],report['history'][0]['cost']),(3,6))
            self.assertIn('summary_receipt',report['history'][0])
            self.assertNotIn('pending_sweep',task.state)

    def test_wrong_summary_total_preserves_consumption_record_across_restarts(self):
        for executions,defeats in ((3,2),(6,2),(3,6),(7,7)):
            with self.subTest(executions=executions,defeats=defeats),TemporaryDirectory() as root:
                game=Game();game.native_sweep_summary=True;capture=game.capture
                def wrong_summary(**kwargs):
                    if game.page=='sweep_summary':
                        return screen(('扫荡结果',480,42),(f'扫荡次数{executions}次',480,91),
                                      (f'{defeats}只击破！',480,136),('确认',480,480))
                    return capture(**kwargs)
                game.capture=wrong_summary
                for _ in range(2):
                    task=self.make_task(root,game,max_sweeps=6)
                    self.assertEqual(task.run()['status'],'blocked')
                    self.assertEqual((game.commits,game.tickets,game.page),(1,94,'sweep_summary'))
                    self.assertIn('pending_sweep',task.state)
                self.assertFalse(any(page=='sweep_summary' and name=='确认' for page,name,_ in game.clicks))

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

    def test_entry_leaves_known_subjugation_detail_without_challenging(self):
        with TemporaryDirectory() as root:
            task = self.make_task(root, Game())
            task.ui = Mock(output=Path(root))
            task.ui.capture.side_effect = [
                screen(('BOSS详情',109,52),('模拟战',748,109),('实战',866,109),
                       ('取消',668,469),('挑战',840,469)),
                screen(('深渊讨伐战',135,30),('冒险',537,526)),
                screen(('冒险',100,30),('追忆的战场',800,365)),
                screen(('追忆的战场',160,30),('追忆战',210,375),('追忆战·霸',760,375))]
            self.assertTrue(field.home(task.enter()))
            self.assertEqual([call.args[0].text for call in task.ui.click.call_args_list],
                             ['取消','冒险','追忆的战场'])

    def test_entry_closes_subjugation_selector_before_other_task_navigation(self):
        with TemporaryDirectory() as root:
            task = self.make_task(root, Game())
            task.ui = Mock(output=Path(root))
            task.ui.capture.side_effect = [
                screen(('首领难度选择',480,42),('普通',480,109),('关闭',480,480)),
                screen(('深渊讨伐战',135,30),('冒险',537,526)),
                screen(('冒险',100,30),('追忆的战场',800,365)),
                screen(('追忆的战场',160,30),('追忆战',210,375),('追忆战·霸',760,375))]
            self.assertTrue(field.home(task.enter()))
            self.assertEqual([call.args[0].text for call in task.ui.click.call_args_list],
                             ['关闭','冒险','追忆的战场'])

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

    def test_empty_sweep_notice_does_not_mark_exhausted_domains_as_uncleared(self):
        with TemporaryDirectory() as root:
            game=Game()
            game.remaining[field.AREAS['kaiser']]=0
            game.remaining[field.AREAS['zen']]=0
            original_capture=game.capture
            def capture(**kwargs):
                empty=game.page=='catalogue'
                if empty:game.page='index'
                value=original_capture(**kwargs)
                if game.page=='index':
                    value.image[240:291,680:721]=245
                if empty:
                    value.items+=screen(('没有可扫荡的关卡',480,220)).items
                return value
            game.capture=capture
            for _ in range(2):
                report=self.make_task(root,game,areas=['kaiser','zen','miroku']).run()
                self.assertEqual(report['status'],'partial',report)
                self.assertEqual(report['unsweepable'],[field.AREAS['miroku']])
                self.assertEqual(report['pending'],['部分领域尚未解锁扫荡：'+field.AREAS['miroku']])
                self.assertEqual((game.commits,game.claims,game.tickets),(0,0,100))

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

    def test_pending_sweep_recovers_when_new_sweeps_are_disabled(self):
        for preview in (False, True):
            with self.subTest(preview=preview), TemporaryDirectory() as root:
                game=Game();game.lose_receipt=True
                task=self.make_task(root,game,max_sweeps=1)
                self.assertEqual(task.run()['status'],'blocked')
                game.page='index';game.lose_receipt=False
                again=self.make_task(root,game,claim_rewards=False,sweep_dominion=False,
                                     preview_only=preview,areas=['zen'])
                report=again.run()
                self.assertEqual(report['status'],'prepared' if preview else 'complete',report)
                self.assertEqual(report['spent'],1)
                self.assertEqual(report['history'][0]['targets'],
                                 [dict(area=field.AREAS['kaiser'],floor=2,remaining=3)])
                self.assertEqual((game.claims,game.commits,game.tickets),(0,1,99))
                self.assertFalse(again.state)
                game.cleared[field.AREAS['memory']]=game.max_floor[field.AREAS['memory']]
                first_clear=self.make_task(root,game,RecollectionFirstClear)
                self.assertEqual(first_clear.run()['status'],'already_complete')

    def test_disabled_sweeps_keep_pending_when_attempts_or_tickets_disagree(self):
        for mismatch in ('attempts', 'tickets'):
            with self.subTest(mismatch=mismatch), TemporaryDirectory() as root:
                game=Game();game.lose_receipt=True
                task=self.make_task(root,game,max_sweeps=1)
                self.assertEqual(task.run()['status'],'blocked')
                pending=deepcopy(task.state['pending_sweep'])
                game.page='index';game.lose_receipt=False
                if mismatch=='attempts':game.remaining[field.AREAS['kaiser']]+=1
                else:game.tickets+=1
                before=(deepcopy(game.remaining),game.tickets)
                again=self.make_task(root,game,claim_rewards=False,sweep_dominion=False,preview_only=True)
                report=again.run()
                self.assertEqual(report['status'],'blocked',report)
                self.assertEqual(again.state['pending_sweep'],pending)
                self.assertEqual((game.remaining,game.tickets),before)
                self.assertEqual(game.commits,1)
                self.assertEqual(json.loads(again.state_path.read_text(encoding='utf-8'))['pending_sweep'],pending)

    def test_pending_claim_recovers_when_new_claims_are_disabled(self):
        for preview in (False, True):
            with self.subTest(preview=preview), TemporaryDirectory() as root:
                game=Game();game.claim=True
                original_capture=game.capture
                game.capture=lambda **kw: (screen(('未知状态',480,40)) if game.page=='claim_receipt'
                                          else original_capture(**kw))
                task=self.make_task(root,game,sweep_dominion=False)
                self.assertEqual(task.run()['status'],'blocked')
                self.assertIn('pending_claim',task.state)
                game.capture=original_capture
                again=self.make_task(root,game,claim_rewards=False,sweep_dominion=False,preview_only=preview)
                report=again.run()
                self.assertEqual(report['status'],'prepared' if preview else 'complete',report)
                self.assertEqual(report['rewards'],'recovered_claim')
                self.assertEqual((game.claims,game.commits,game.tickets),(1,0,100))
                self.assertFalse(self.make_task(root,game).state)

    def test_pending_claim_with_nonempty_box_blocks_disabled_and_preview_modes(self):
        for preview in (False, True):
            with self.subTest(preview=preview), TemporaryDirectory() as root:
                game=Game();game.claim=True
                original_click=game.click
                def click(value, **kwargs):
                    if isinstance(value,TextBox) and value.text=='领取':
                        raise RunCancelled('synthetic interruption before claim input')
                    return original_click(value, **kwargs)
                game.click=click
                task=self.make_task(root,game,sweep_dominion=False)
                with self.assertRaises(RunCancelled):task.run()
                pending=deepcopy(task.state['pending_claim'])
                game.click=original_click
                again=self.make_task(root,game,claim_rewards=False,sweep_dominion=False,preview_only=preview)
                report=again.run()
                self.assertEqual(report['status'],'blocked',report)
                self.assertEqual(again.state['pending_claim'],pending)
                self.assertEqual((game.claims,game.commits,game.tickets),(0,0,100))

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

    def test_unready_candidates_continue_to_next_source_without_using_battle_budget(self):
        with TemporaryDirectory() as root:
            task=self.make_task(root,Game(),RecollectionFirstClear,
                                max_battles=1,max_attempts_per_stage=1,max_source_batches=3)
            party=parties_for_floor(dict(parties=[source_party()]),'记忆领域',9)[0]
            parties=[deepcopy(party) for _ in range(3)]
            for i,p in enumerate(parties):p.name=f'synthetic-{i}'
            task.source_parties=Mock(side_effect=[[p] for p in parties])
            task.select_floor=Mock(return_value=detail('记忆领域',9))
            def battle(area,floor,p):
                if p.name!='synthetic-2':
                    task.report.setdefault('audits',[]).append(dict(formation=dict(
                        unready=[dict(character='合成角色',reasons=['未在搜索结果中找到角色'])])))
                    return dict(outcome='blocked',progressed=False)
                task.report['battles']+=1
                return dict(outcome='cleared',progressed=True)
            task.battle=Mock(side_effect=battle)
            task.advance_area('记忆领域')
            self.assertEqual(task.battle.call_count,3)
            self.assertEqual(task.report['battles'],1)
            self.assertEqual([c.kwargs['advance'] for c in task.source_parties.call_args_list],[False,True,True])

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

    def test_verified_failure_survives_restart_and_changed_conditions_can_retry(self):
        from test_recollection_retry import synthetic_trial, RecollectionRetryTests
        _,_,details=synthetic_trial()
        raw=source_party();party=parties_for_floor(dict(parties=[raw]),'记忆领域',9)[0]
        names=details['order']
        with TemporaryDirectory() as root:
            game=Game()
            original_capture=game.capture
            def capture(**kwargs):
                s=original_capture(**kwargs)
                if game.page=='detail' and game.area==field.AREAS['memory']:
                    s.items+=screen(('合成首领（多部位）',323,258),('等级.100',446,258),
                                    ('弱点',539,258),('80000000/80000000',552,295)).items
                return s
            game.capture=capture
            def make_task(**options):
                task=self.make_task(root,game,RecollectionFirstClear,**options)
                task.formation=Mock()
                task.formation.select.side_effect=lambda p:(True,deepcopy(details))
                task.formation.inspect_current.return_value=[CharacterStatus(n,identity_verified=True) for n in names]
                return task
            task=make_task()
            def fail(*args):
                task.combat_settings_confirmed('synthetic_settings.png')
                game.page='detail'
                return BattleResult('retreated','减员超出队伍容许值，尝试下一队')
            task.combat=Mock(run=Mock(side_effect=fail))
            with patch('pcrscript.game_ui.screen.EventScreen.number',return_value=500000), \
                 patch('pcrscript.game_ui.special_equipment.inspect_special_equipment',
                       return_value=details['special_equipment']):
                first=task.battle('记忆领域',9,party)
                self.assertFalse(first['progressed'])
                self.assertEqual(len(task.state['failed_trials']),1)
                self.assertEqual(first['trial_context']['target'],dict(
                    scope=dict(area=field.AREAS['memory'],floor=9),boss='合成首领(多部位)',
                    level=100,maximum_hp=80000000))
                self.assertIsNone(first['attempts_before'])
                self.assertIsNone(first['attempts_after'])
                same=make_task();same.combat=Mock()
                result=same.battle('记忆领域',9,party)
                self.assertEqual(result['outcome'],'blocked')
                same.combat.run.assert_not_called()
                same.formation.inspect_current.assert_not_called()
                self.assertEqual(same.report['battles'],0)
                self.assertNotIn('pending_battle',same.state)
                with patch('pcrscript.game_ui.screen.EventScreen.number',return_value=None):
                    self.assertIn('复核不完整',same.battle('记忆领域',9,party)['reason'])
                same.combat.run.assert_not_called()
                explicit=make_task(retry_failed_parties=True)
                nodes=RecollectionRetryTests().mastery()
                explicit.report['mastery_preparation']=dict(nodes=deepcopy(nodes))
                def explicit_failure(*args):
                    explicit.combat_settings_confirmed('synthetic_settings.png')
                    game.page='detail'
                    return BattleResult('retreated','减员超出队伍容许值，尝试下一队')
                explicit.combat=Mock(run=Mock(side_effect=explicit_failure))
                explicit.battle('记忆领域',9,party)
                explicit.combat.run.assert_called_once()
                repeated=make_task();repeated.combat=Mock()
                repeated.report['mastery_preparation']=dict(nodes=deepcopy(nodes))
                self.assertEqual(repeated.battle('记忆领域',9,party)['outcome'],'blocked')
                repeated.combat.run.assert_not_called()
                # All otherwise identical stats/settings, but fresh mastery changed.
                changed_mastery=make_task();changed_mastery.combat=Mock(run=Mock(side_effect=game.win))
                nodes[0]['state']['value']='8.1'
                changed_mastery.report['mastery_preparation']=dict(nodes=nodes)
                self.assertTrue(changed_mastery.battle('记忆领域',9,party)['progressed'])
                changed_mastery.combat.run.assert_called_once()
                changed_mastery.formation.inspect_current.assert_called_once()
                game.cleared[field.AREAS['memory']]=False
                changed=make_task();changed.combat=Mock(run=Mock(side_effect=game.win))
                with patch('pcrscript.game_ui.screen.EventScreen.number',return_value=500001):
                    self.assertTrue(changed.battle('记忆领域',9,party)['progressed'])
                changed.combat.run.assert_called_once()
                self.assertEqual((game.tickets,game.remaining[field.AREAS['kaiser']]),(100,3))

    def test_auto_equip_is_optional_and_requires_known_before_and_after_slots(self):
        cases=[(False,0,0,True,15),(True,0,0,True,15),(True,1,0,False,15),
               (True,0,1,False,15),(True,0,0,True,0),(False,0,0,True,0)]
        for enabled,before_unknown,after_unknown,can_battle,before_empty in cases:
            with self.subTest(auto_equip=enabled,before=before_unknown,after=after_unknown), TemporaryDirectory() as root:
                game=Game();task=self.make_task(root,game,RecollectionFirstClear,auto_equip=enabled)
                party=parties_for_floor(dict(parties=[source_party()]),field.AREAS['memory'],9)[0]
                names=[m.name for m in party.members]
                task.formation=Mock()
                task.formation.select.return_value=(True,dict(order=names))
                task.formation.inspect_current.return_value=[CharacterStatus(n,identity_verified=True) for n in names]
                task.combat=Mock(run=Mock(side_effect=game.win))
                before=dict(unknown=before_unknown,empty=before_empty,evidence='synthetic_before.png')
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

    def dispatch_task(self, root, game):
        key = next(k for k, v in field.AREAS.items() if v == game.area)
        task = self.make_task(root, game, RecollectionFirstClear, areas=[key])
        party = parties_for_floor(dict(parties=[source_party(game.area, game.floor)]), game.area, game.floor)[0]
        names = [m.name for m in party.members]
        task.formation = Mock()
        task.formation.select.return_value = (True, dict(order=names))
        task.formation.inspect_current.return_value = [CharacterStatus(n, identity_verified=True) for n in names]
        task.source_parties = Mock(return_value=[party])
        task.combat = EventCombat(task)
        task.combat.match = Mock(return_value=None)
        # Battle settings are covered separately; retain the production start,
        # observation, dispatch journal and post-battle progress checks here.
        def configure(*args, **kwargs):
            task.combat_settings_confirmed('synthetic-settings.png')
            game.win()
            return True
        task.combat.configure_paused = Mock(side_effect=configure)
        return task

    def test_unsubmitted_first_clear_restores_and_reaudits_the_same_party(self):
        for area in (field.AREAS['memory'], field.AREAS['kaiser']):
            for phase, restored_page in ((False, 'formation'), (False, 'home'), (True, 'formation')):
                with self.subTest(area=area, phase=phase, page=restored_page), TemporaryDirectory() as root:
                    game = BattleDispatchGame(area)
                    task = self.dispatch_task(root, game)
                    save = task.save
                    interrupted = False
                    def stop_before_input():
                        nonlocal interrupted
                        save()
                        if not interrupted and task.state.get('pending_battle', {}).get('submitted') is phase:
                            interrupted = True
                            raise RunCancelled('synthetic stop after battle journal, before start input')
                    with patch.object(task, 'save', side_effect=stop_before_input):
                        with self.assertRaises(RunCancelled):
                            task.run()
                    saved = json.loads(task.state_path.read_text(encoding='utf-8'))['pending_battle']
                    self.assertIs(saved['submitted'], phase)
                    self.assertIs(saved['submission_tracked'], True)
                    self.assertEqual((game.starts, game.tickets), (0, 100))
                    game.page = restored_page
                    resumed = self.dispatch_task(root, game)
                    report = resumed.run()
                    self.assertEqual(report['status'], 'complete', report)
                    self.assertEqual((report['battles'], game.starts), (1, 1))
                    self.assertEqual(report['history'][0]['outcome'], 'cancelled_unsubmitted_battle')
                    self.assertFalse(report['history'][0]['progressed'])
                    self.assertTrue(report['history'][1]['progressed'])
                    self.assertIs(report['history'][1]['submitted'], True)
                    self.assertEqual(game.tickets, 100)
                    self.assertFalse(resumed.state)
                    resumed.formation.select.assert_called_once()

    def test_unsubmitted_formation_cancel_survives_a_second_interruption(self):
        with TemporaryDirectory() as root:
            game = BattleDispatchGame(field.AREAS['kaiser'])
            task = self.dispatch_task(root, game)
            original = game.click
            def stop_start(value, **kwargs):
                if getattr(value, 'text', '') == '战斗开始':
                    raise RunCancelled('synthetic undelivered start')
                return original(value, **kwargs)
            game.click = stop_start
            with self.assertRaises(RunCancelled):
                task.run()
            resumed = self.dispatch_task(root, game)
            def stop_cancel(value, **kwargs):
                if game.page == 'formation' and getattr(value, 'text', '') == '取消':
                    saved = json.loads(resumed.state_path.read_text(encoding='utf-8'))['pending_battle']
                    self.assertIn('unsubmitted_formation', saved)
                    original(value, **kwargs)
                    raise RunCancelled('synthetic stop after formation cancel delivery')
                return original(value, **kwargs)
            game.click = stop_cancel
            with self.assertRaises(RunCancelled):
                resumed.run()
            self.assertEqual(game.starts, 0)
            game.page = 'home'
            game.click = original
            final = self.dispatch_task(root, game)
            report = final.run()
            self.assertEqual(report['status'], 'complete', report)
            self.assertEqual((game.starts, report['battles']), (1, 1))
            self.assertEqual(report['history'][0]['outcome'], 'cancelled_unsubmitted_battle')
            self.assertFalse(final.state)

    def test_unchanged_floor_cannot_release_submitted_legacy_or_observed_battles(self):
        flags = [dict(submitted=True, submission_tracked=True), dict(submitted=False), {},
                 dict(submitted=1, submission_tracked=True)]
        flags += [dict(submitted=False, submission_tracked=True, **{key: proof}) for key, proof in (
            ('battle_started', 'synthetic.png'), ('samples', [dict(seconds=80)]),
            ('settings_verified', True), ('settings_evidence', 'synthetic.png'),
            ('result_evidence', 'synthetic.png'), ('outcome', 'settled'))]
        for flag in flags:
            with self.subTest(flag=flag), TemporaryDirectory() as root:
                game = BattleDispatchGame(field.AREAS['kaiser'])
                game.page = 'detail'
                task = self.dispatch_task(root, game)
                record = dict(area=game.area, floor=game.floor, attempts_before=3, party='synthetic',
                              target=field.boss_signature(game.capture()), **flag)
                task.state['pending_battle'] = record
                task.save()
                for _ in range(2):
                    resumed = self.dispatch_task(root, game)
                    self.assertEqual(resumed.run()['status'], 'blocked')
                    self.assertEqual(resumed.state['pending_battle'], record)
                    resumed.formation.select.assert_not_called()
                    self.assertEqual(game.starts, 0)

    def test_unsubmitted_battle_recovery_requires_stable_target_and_counters(self):
        with TemporaryDirectory() as root:
            game = BattleDispatchGame(field.AREAS['kaiser'])
            game.page = 'detail'
            before = game.capture()
            cases = [deepcopy(before) for _ in range(5)]
            cases[0].items += screen(('已完成', 156, 421)).items
            next(item for item in cases[1].items if item.text == '3/3').text = '2/3'
            next(item for item in cases[2].items if item.text == '合成首领').text = '另一首领'
            cases[3].items += screen(('正在进行数据连接', 480, 45)).items
            next(item for item in cases[4].items if item.text == '初次通关').score = .94
            for changed in cases:
                with self.subTest(changed=changed.text()):
                    task = self.dispatch_task(root, game)
                    record = dict(area=game.area, floor=game.floor, attempts_before=3, party='synthetic',
                                  target=field.boss_signature(before), submitted=False, submission_tracked=True)
                    task.state['pending_battle'] = record
                    task.save()
                    task.select_floor = Mock(return_value=before)
                    task.ui.capture = Mock(side_effect=[before, changed])
                    with self.assertRaises(EventUIError):
                        task.reconcile_battle()
                    self.assertEqual(task.state['pending_battle'], record)
                    self.assertEqual(game.starts, 0)

    def test_unsubmitted_formation_recovery_requires_three_nonloading_frames(self):
        with TemporaryDirectory() as root:
            game = BattleDispatchGame(field.AREAS['kaiser'])
            task = self.dispatch_task(root, game)
            game.page = 'detail'
            record = dict(area=game.area, floor=game.floor, attempts_before=3, party='synthetic',
                          target=field.boss_signature(game.capture()), submitted=True, submission_tracked=True)
            game.page = 'formation'
            before = game.capture()
            changed = [deepcopy(before) for _ in range(4)]
            changed[0].items += screen(('正在进行数据连接', 480, 60)).items
            changed[1].items += screen(('菜单', 900, 25)).items
            changed[2].image[429:478, 800:901] = 140
            changed[3].items[0].score = .94
            for value in changed:
                with self.subTest(value=value.text()):
                    task = self.dispatch_task(root, game)
                    task.state['pending_battle'] = record
                    task.save()
                    task.ui.capture = Mock(side_effect=[before, before, value])
                    self.assertEqual(task.run()['status'], 'blocked')
                    self.assertEqual(task.state['pending_battle'], record)
                    self.assertFalse(game.clicks)

    def test_unsubmitted_battle_without_original_target_or_attempts_stays_pending(self):
        for missing in ('target', 'attempts_before'):
            with self.subTest(missing=missing), TemporaryDirectory() as root:
                game = BattleDispatchGame(field.AREAS['kaiser'])
                game.page = 'detail'
                task = self.dispatch_task(root, game)
                record = dict(area=game.area, floor=game.floor, attempts_before=3, party='synthetic',
                              target=field.boss_signature(game.capture()), submitted=False, submission_tracked=True)
                record.pop(missing)
                task.state['pending_battle'] = record
                task.save()
                resumed = self.dispatch_task(root, game)
                self.assertEqual(resumed.run()['status'], 'blocked')
                self.assertEqual(resumed.state['pending_battle'], record)
                resumed.formation.select.assert_not_called()
                self.assertEqual(game.starts, 0)

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
    def test_native_sweep_summary_requires_all_confident_fields(self):
        summary=screen(('扫荡结果',480,42),('扫荡次数1次',480,91),
                       ('1只击破！',480,136),('确认',480,480))
        self.assertEqual(field.sweep_summary(summary),dict(quantity=1,defeats=1))
        for index in range(4):
            uncertain=deepcopy(summary);uncertain.items[index].score=.94
            self.assertIsNone(field.sweep_summary(uncertain))
        self.assertIsNone(field.sweep_summary(screen(('扫荡结果',480,42),('确认',480,480))))

    def test_sweep_stage_count_recovers_split_number_and_unit(self):
        confirmation=screen(('一键扫荡确认',480,42),
                            ('将消耗扫荡券，执行以下关卡。确定吗？',480,80),
                            ('合计扫荡次数',840,350))
        local=screen(('处',749,381),('1',715,381))
        ui=Mock(read_region=Mock(return_value=local))
        self.assertEqual(field.sweep_stage_count(ui,confirmation),1)
        ui.read_region.assert_called_once()
        combined=screen(*[(x.text,*x.center) for x in confirmation.items],('2处',715,381))
        ui.read_region.reset_mock()
        self.assertEqual(field.sweep_stage_count(ui,combined),2)
        ui.read_region.assert_not_called()

    def test_sweep_stage_count_rejects_uncertain_incomplete_or_wrong_context(self):
        confirmation=screen(('一键扫荡确认',480,42),
                            ('将消耗扫荡券，执行以下关卡。确定吗？',480,80),
                            ('合计扫荡次数',840,350))
        low=screen(('1',715,381),('处',749,381));low.items[0].score=.94
        for local in (low,screen(('处',749,381)),screen(('1',715,381),('次',749,381)),
                      screen(('1处',720,381),('未知',750,381))):
            with self.subTest(labels=[x.text for x in local.items]):
                self.assertIsNone(field.sweep_stage_count(Mock(read_region=Mock(return_value=local)),confirmation))
        ui=Mock()
        self.assertIsNone(field.sweep_stage_count(ui,screen(('1处',715,381))))
        ui.read_region.assert_not_called()

    def test_missing_member_does_not_trigger_unrelated_equipment_round_trip(self):
        task=object.__new__(RecollectionFirstClear)
        party=parties_for_floor(dict(parties=[source_party()]),'记忆领域',9)[0]
        details=dict(unready=[dict(character=party.members[1].name,
            reasons=['未在搜索结果中确认该版本的角色'])])
        task.formation=Mock(observed={party.members[0].name:
            CharacterStatus(party.members[0].name,identity_verified=True)})
        task.formation.select.return_value=(False,details)
        task.capture=Mock()
        self.assertEqual(task.select_party('记忆领域',9,party),(False,details))
        task.capture.assert_not_called()

    def test_declared_numeric_equipment_uses_read_only_audit_and_reselects(self):
        task=object.__new__(RecollectionFirstClear)
        party=parties_for_floor(dict(parties=[source_party()]),'记忆领域',9)[0]
        party.members[0].unique_level=100
        actual=CharacterStatus(party.members[0].name,identity_verified=True,unique=True,unique2=False)
        task.formation=Mock(observed={actual.name:actual})
        task.formation.select.side_effect=[(False,dict(unready=[])),(True,dict(order=[m.name for m in party.members]))]
        task.ui=Mock();task.robot=Mock()
        task.capture=Mock();task.click=Mock();task.wait=Mock();task.check_deadline=Mock();task.report_progress=Mock()
        task.select_floor=Mock(return_value=detail('记忆领域',9))
        with patch('pcrscript.tasks.party_preparation.read_numeric_equipment') as inspect, \
             patch('pcrscript.tasks.task_home.ToHomePage'):
            ready,_=task.select_party('记忆领域',9,party)
        self.assertTrue(ready)
        inspect.assert_called_once_with(task.formation,actual.name)
        self.assertEqual(task.formation.select.call_count,2)

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

    def test_missing_member_does_not_skip_equipment_audit_of_owned_member(self):
        task=object.__new__(RecollectionFirstClear)
        party=parties_for_floor(dict(parties=[source_party()]),'记忆领域',9)[0]
        unknown=CharacterStatus(party.members[0].name,identity_verified=True)
        missing=party.members[1].name
        details=dict(unready=[dict(character=missing,reasons=['未在搜索结果中找到角色']),
                              dict(character=unknown.name,reasons=['专武未知'])])
        task.formation=Mock(observed={unknown.name:unknown},unreleased={})
        task.formation.select.side_effect=[(False,details),(False,details)]
        task.ui=Mock();task.robot=Mock()
        task.capture=Mock();task.click=Mock();task.wait=Mock();task.check_deadline=Mock();task.report_progress=Mock()
        task.select_floor=Mock(return_value=detail('记忆领域',9))
        with patch('pcrscript.game_ui.character_equipment.inspect_unreleased_equipment',return_value=None) as inspect, \
             patch('pcrscript.tasks.task_home.ToHomePage'):
            ready,after=task.select_party('记忆领域',9,party)
        self.assertFalse(ready)
        self.assertIs(after,details)
        inspect.assert_called_once_with(task.ui,unknown.name)
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
                file_title=parse_video_source(dict(source,pages=[dict(cid=1,part='记忆领域9层 synthetic_clip.mp4',duration=5)]),
                    dict(task_type='recollection',area='记忆领域',stage='9',parsed_dir=folder),index,
                    api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
                master_points=parse_video_source(dict(source,pages=[dict(cid=1,part='记忆领域9层 本关要求MP4',duration=5)]),
                    dict(task_type='recollection',area='记忆领域',stage='9',parsed_dir=folder),index,
                    api=Mock(),ocr=Mock(),media_fetcher=lambda *a,**k:(path,dict(duration=5)))
            self.assertEqual(len(parties_for_floor(report,'记忆领域',9)),1)
            self.assertEqual(parties_for_floor(report,'记忆领域',10),[])
            self.assertTrue(restricted['parties'][0]['global_requirements'])
            self.assertEqual(parties_for_floor(restricted,'记忆领域',9),[])
            self.assertEqual(parties_for_floor(restricted,'记忆领域',9,allow_local_trials=True),[])
            self.assertEqual(len(parties_for_floor(file_title,'记忆领域',9)),1)
            self.assertFalse(file_title['global_requirements'])
            self.assertTrue(master_points['global_requirements'])
            self.assertEqual(parties_for_floor(master_points,'记忆领域',9,allow_local_trials=True),[])

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

    def test_partial_source_retains_known_build_requirements_in_account_trials(self):
        raw=source_party();raw['members'][0]['rank']['value']=None
        party=parties_for_floor(dict(parties=[raw]),'记忆领域',9,allow_local_trials=True)[0]
        requirement=party.members[0]
        self.assertIsNone(requirement.rank)
        self.assertEqual(requirement.level,100)
        self.assertEqual(requirement.stars,5)
        formation=RecollectionFormation(Mock());formation.use_current_build=True
        actual=CharacterStatus(requirement.name,100,11,5,True,False,100,identity_verified=True)
        self.assertEqual(formation.member_readiness(requirement,actual),[])
        for key,value in (('level',99),('stars',3),('unique',False),('skill_level',99)):
            changed=deepcopy(actual);setattr(changed,key,value)
            with self.subTest(field=key):
                self.assertTrue(formation.member_readiness(requirement,changed))
        raw['members'][0]['level']['conflicts']=[dict(value=90)]
        self.assertEqual(parties_for_floor(dict(parties=[raw]),'记忆领域',9,allow_local_trials=True),[])

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
                            (RecollectionFirstClear,dict(areas=[{}])),(RecollectionFirstClear,dict(max_attempts_per_stage=0)),
                            (RecollectionFirstClear,dict(auto_equip_priorities={'armor':'hp'})),
                            (RecollectionFirstClear,dict(auto_equip=True,auto_equip_priorities={'armor':True}))):
            with self.assertRaises(ValueError):cls.prepare({cls.config_section:options})
