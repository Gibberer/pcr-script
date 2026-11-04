"""Revised CN tower: current-floor recommendations, simulation, real progress."""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from contextlib import closing
from uuid import uuid4
import sqlite3
import json
import subprocess
import cv2 as cv
import numpy as np

from .base import TimeLimitTask
from .options import validated_options
from .registry import register
from .strategy_formation import StrategyFormation
from .event_strategy import EventParty, MemberRequirement
from .event_battle import EventCombat
from .party_preparation import prepare_character_database, prepare_special
from ..game_ui import tower as field
from ..game_ui.avatars import face_crop
from ..game_ui.character_search import search_character_candidates
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import atomic_json, checkpoint, clock as time, RunCancelled, ResumeUnsafe


class NoTowerCandidate(EventUIError):
    """The current bounded recommendation list has been exhausted."""


def validate_options(options):
    value = validated_options(options, 'LunaTower',
        integers=(('timeout', 3600, 14400), ('battle_timeout', 240, 600),
                  ('max_floors', 10, 100), ('max_candidates', 20, 100), ('max_pages', 12, 100)),
        flags=(('preview_only', False), ('simulation_only', False), ('auto_equip', False),
               ('support_trials',True),('prefer_support',False),('tank_trials',True),('free_recovery',True),
               ('video_guides',True)))
    attacks = value.setdefault('top_attacks_per_run', 1)
    if type(attacks) is not int or not 0 <= attacks <= 100:
        raise ValueError('LunaTower.top_attacks_per_run必须为0到100的整数；0表示不限制')
    trials = value.setdefault('top_trials_per_run', 6)
    if type(trials) is not int or not 0 <= trials <= 100:
        raise ValueError('LunaTower.top_trials_per_run必须为0到100的整数；0表示不限制')
    target = value.setdefault('target_floor', 0)
    if type(target) is not int or not 0 <= target <= 10000:
        raise ValueError('LunaTower.target_floor必须为0到10000的整数；0表示本期最高层')
    from ..game_ui.special_equipment import validate_auto_priorities
    value['auto_equip_priorities']=validate_auto_priorities(value.get('auto_equip_priorities',{}))
    return value


class TowerFormation(StrategyFormation):
    slots = [(96+109*i, 426) for i in range(5)]
    slot_top = 378
    require_current_skills = True
    defocus = (590, 356)

    def current_names(self,screen,manifest):
        from .tower_guides import recognize_icon
        names=[]
        for x,_ in self.occupied_slots(screen):
            rect=(x-48,self.slot_top,96,96)
            name=self.avatars.query([face_crop(screen.image,rect)])[0]
            if name is None:
                name=recognize_icon(screen.image[self.slot_top:self.slot_top+96,x-48:x+48],self.avatars,manifest)
            names.append(normalized(name) if name else None)
        return names

    def matching_cards(self,screen,name,manifest):
        from .tower_guides import recognize_icon
        matches=[]
        rects=self.search_rectangles(screen.image)
        known=self.avatars.query([face_crop(screen.image,r) for r in rects])
        for rect,identity in zip(rects,known):
            x,y,w,h=rect
            if identity is None:
                identity=recognize_icon(screen.image[y:y+h,x:x+w],self.avatars,manifest)
            if identity and normalized(identity)==name:matches.append(rect)
        return matches

    def settled_names(self,frame,manifest,names):
        """Slot crops can miss a card its search matched; only the picked members can fill the gaps."""
        order=self.current_names(frame,manifest)
        gaps=[i for i,name in enumerate(order) if name is None]
        missing=sorted(set(names)-set(order))
        if not gaps or len(gaps)!=len(missing) or len(order)!=len(names):return order
        if len(gaps)==1:
            order[gaps[0]]=missing[0]
            return order
        slots=self.occupied_slots(frame)
        crops=[face_crop(frame.image,(slots[i][0]-48,self.slot_top,96,96)) for i in gaps]
        found=self.avatars.assign_expected(crops,missing)
        if found:
            for i,name in zip(gaps,found):order[i]=name
        return order

    def select_fast(self,names,manifest,*,support_name=None):
        """Select exact public identities; never open character detail pages."""
        names=[n for n in names if n!=support_name]
        self.ui.expect_click('全部',self.all_filter_area,exact=True)
        for _ in range(5):
            screen=self.ui.capture()
            current=self.current_names(screen,manifest)
            occupied=self.occupied_slots(screen)
            unwanted=[position for position,name in zip(occupied,current) if name not in names
                      or screen.find('支援',(position[0]-48,440,position[0]+48,475))]
            if not unwanted:break
            self.ui.click(unwanted[-1],delay=.5)
            self.ui.wait(lambda s:len(self.occupied_slots(s))<len(occupied),'移除非目标角色',timeout=5)
        for name in names:
            current=self.current_names(self.ui.capture(ocr=False),manifest)
            if name in current:continue
            print('[露娜塔] 选择阶段角色 '+name,flush=True)
            for _ in range(6):
                screen=self.ui.capture()
                if screen.find('重置',self.search_reset_area,exact=True):break
                self.ui.swipe(*self.search_reveal)
            else:raise EventUIError('编队角色搜索入口未出现')
            screen=search_character_candidates(self.ui,name,defocus=self.defocus,
                field_area=self.search_field_area,reset=self.search_reset,field=self.search_field)
            matches=self.matching_cards(screen,name,manifest)
            until=time.monotonic()+5
            while len(matches)!=1 and time.monotonic()<until:
                time.sleep(.3)
                screen=self.ui.capture()
                matches=self.matching_cards(screen,name,manifest)
            if len(matches)!=1:
                self.ui.save('unconfirmed_identity_'+name,screen)
                raise EventUIError(name+'的可用衣装未唯一确认，未开战')
            x,y,w,h=matches[0]
            self.select_card((x+w//2,y+h//2))
        screen=self.ui.capture()
        if reset:=screen.find('重置',self.search_reset_area,exact=True):
            self.ui.click(reset,delay=.3)
        screen=self.ui.capture()
        order=[]
        def ready(frame):
            nonlocal order
            if not field.formation(frame):return False
            order=self.settled_names(frame,manifest,names)
            return len(order)==len(names) and set(order)==set(names)
        if not ready(screen):
            try:screen=self.ui.wait(ready,'塔顶原五人选人回执',timeout=5)
            except EventUIError:
                self.ui.save('phase_formation_mismatch')
                raise EventUIError('塔顶阶段队伍不符，观察到'+str(order)+'，未开战')
        return screen,order

    def select_support(self,name,manifest,*,wanted=None):
        """Bind one observed support provider, not just the unit illustration."""
        screen=self.ui.capture()
        order=self.current_names(screen,manifest)
        if name in order:
            self.ui.click(self.slots[order.index(name)],delay=.5)
        elif len(order)!=4:raise EventUIError('支援编入前未确认四名原角色')
        self.ui.wait(lambda s:len(self.occupied_slots(s))==4,'支援空位',timeout=5)
        self.ui.expect_click('支援',(540,65,625,108),exact=True)
        for _ in range(6):
            screen=self.ui.capture()
            if screen.find('重置',self.search_reset_area,exact=True):break
            self.ui.swipe(*self.search_reveal)
        screen=search_character_candidates(self.ui,name,defocus=self.defocus,
            field_area=self.search_field_area,reset=self.search_reset,field=self.search_field)
        if screen.find('未搜索到该角色[。.]?',(50,170,900,400)):
            raise EventUIError(name+'当前没有同衣装支援')
        from .tower_guides import recognize_icon
        choices=[]
        self.ui.wait(lambda s:any(not normalized(o.text).isdigit() and o.score>=.95
            for o in s.all('.+',(45,300,920,333))),'支援提供者加载',timeout=8)
        screen=self.ui.capture()
        for rect in self.search_rectangles(screen.image):
            x,y,w,h=rect
            identity=self.avatars.query([face_crop(screen.image,rect)])[0]
            if identity is None:identity=recognize_icon(screen.image[y:y+h,x:x+w],self.avatars,manifest)
            if not identity or normalized(identity)!=name:continue
            owners=screen.all('.+',(x,y+h+29,x+w,y+h+57))
            owners=[o for o in owners if o.score>=.95 and not normalized(o.text).isdigit()]
            if len(owners)!=1:continue
            provider=normalized(owners[0].text)
            if wanted and provider!=wanted['provider']:continue
            choices.append((rect,provider))
        if not choices:raise EventUIError(name+'没有可确认的同衣装支援')
        rect,provider=choices[0]
        x,y,w,h=rect
        self.ui.click((x+w//2,y+h//2))
        screen=self.ui.wait(lambda s:len(self.occupied_slots(s))==5,'支援编入',timeout=8)
        order=self.current_names(screen,manifest)
        if len(order)!=5 or name not in order:raise EventUIError('支援编入身份未确认')
        # Removing the old unit, clicking the exact provider in the support
        # tab and observing five matching identities binds the rental. The
        # tiny animated badge can OCR as “…支援C”; it is not another gate.
        return screen,order,dict(name=name,provider=provider)



class TowerTask(TimeLimitTask):
    config_section = 'LunaTower'

    @classmethod
    def valid(cls, news, args=None):
        if cls.event_valid(news.tower):
            return cls, args

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        if args or kwargs:
            raise ValueError(cls.name+'使用LunaTower配置，不接受位置参数')
        validate_options(config.get(cls.config_section, {}))
        from ..news import fetch_event_news
        event = fetch_event_news().tower
        if not cls.event_valid(event):
            return (), {}, dict(status='unavailable', reason='静态资料中没有当前露娜塔配置')
        if type(event.extras.get('max_floor')) is not int:
            return (), {}, dict(status='unavailable', reason=event.extras.get('reason', '当前露娜塔区域或最高层未知'))
        if cls.name == 'luna_tower_clean' and event.extras.get('cloister_quest_id') == 0:
            return (), {}, dict(status='unavailable', reason='当前露娜塔区域没有回廊，跳过回廊扫荡')
        return (), {}, None

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/tower'))
        self.deadline = time.monotonic()+self.options['timeout']
        self.report = dict(status='running', cleared=[], simulations=[], rejected=[], pending=[])
        raw_capture=self.ui.capture
        def contextual_capture(*args,**kwargs):
            screen=raw_capture(*args,**kwargs)
            screen.tower_max_floor=self.report.get('schedule',{}).get('max_floor')
            return screen
        self.ui.capture=contextual_capture
        self.formation = TowerFormation(self.ui)
        self.formation.unreleased = {}
        self.equipment_checked = set()
        self.combat = EventCombat(self)
        self.state, self.state_path = {}, None
        self.state_writable = True
        self.source_portraits = []

    def check_deadline(self):
        checkpoint()
        if time.monotonic() >= self.deadline:
            raise EventUIError('露娜塔任务达到运行时限')

    def log(self, message):
        print('[露娜塔] '+message, flush=True)

    def save(self):
        if self.state_path and self.state_writable:
            atomic_json(self.state_path, self.state)
        atomic_json(self.ui.output/'report.json', self.report)

    def capture(self):
        self.check_deadline()
        screen = self.ui.capture()
        if field.home(screen) and field.floor_number(screen) is None:
            local = self.ui.read_region(screen, (315, 83, 445, 124), classify=False)
            screen = type(screen)(screen.image, screen.items+local.items)
        return screen

    def wait(self, predicate, label, timeout=30):
        return self.ui.wait(predicate, label, timeout=timeout, handle=lambda s: self.check_deadline())

    def story_dialog(self, screen):
        # UB animations can hide the timer while retaining the combat menu.
        # The generic story navigator opens any top-right menu; doing that in
        # a tower battle repeatedly pauses combat and exhausts its time budget.
        if not screen.find('跳过这个剧情|跳过这个视频|跳过剧情吗|剧情梗概'):
            return False
        from .task_story_event import CampaignClean
        return CampaignClean.story_dialog(self, screen)

    def enter(self):
        missing_special = 0
        for _ in range(65):
            s = self.capture()
            if field.busy(s):
                time.sleep(.5)
                continue
            if field.home(s):
                if request:=self.state.get('role_recovery_request'):
                    if field.target_signature(s)!=request['target']:
                        raise EventUIError('回复接续时敌方状态变化，停止开战')
                    if s.find('还剩.*使用',(440,405,710,455)):
                        self.state['role_recovery_battle_count']=request['battle_count']
                    self.state.pop('role_recovery_request',None)
                    self.save()
                return s
            if field.recovery_receipt(s):
                if request:=self.state.get('role_recovery_request'):
                    request['receipt']=str(self.ui.save('role_recovery_resumed',s))
                    self.save()
                self.ui.expect_click('确认',(365,345,595,405),exact=True)
                continue
            if field.recovery_confirmation(s):
                self.ui.expect_click('取消',(265,345,475,405),exact=True)
                continue
            if field.title(s):
                from .task_home import ToHomePage
                self.log('游戏返回标题页，复用首页登录导航后重新读取实际楼层')
                ToHomePage(self.robot).run(timeout=120)
                continue
            if (s.find('剧情解锁', (300, 100, 680, 190), exact=True)
                    and s.find('关闭', (350, 330, 615, 415), exact=True)):
                self.ui.click(s.find('关闭', (350, 330, 615, 415), exact=True))
                continue
            if target := field.navigation_exit(s):
                self.ui.click(target)
                continue
            if s.find('菜单', (840, 0, 960, 65), exact=True) and s.find(r'\d:\d{2}', (750, 0, 850, 65)):
                raise EventUIError('露娜塔存在未结算战斗，保留现场')
            if (s.find('特别关卡', (45, 0, 250, 70), exact=True)
                    and s.find('地下城', (480, 350, 700, 455), exact=True)):
                entry = field.confident(s, '露娜之塔', (710, 350, 930, 455))
                if entry:
                    self.ui.click(entry)
                    continue
            if (s.find('冒险', (45, 0, 180, 70), exact=True)
                    and s.find('主线关卡', (460, 70, 680, 250), exact=True)):
                entry = s.find('特别.*关卡', (675, 65, 805, 210))
                if entry is None:
                    local = self.ui.read_region(s, (710, 150, 785, 207), classify=False)
                    top = field.confident(local, '特别', (710,150,785,180))
                    bottom = field.confident(local, '关卡', (710,175,785,207))
                    if top and bottom and abs(top.center[0]-bottom.center[0]) < 25:
                        entry = (round((top.center[0]+bottom.center[0])/2),
                                 round((top.center[1]+bottom.center[1])/2))
                if entry:
                    self.ui.click(entry)
                    continue
                missing_special += 1
                if missing_special >= 3:
                    raise EventUIError('冒险页特别关卡卡片未确认，未盲点其他入口')
                time.sleep(.5)
                continue
            if s.find('我的主页|主菜单', (0, 470, 960, 540)):
                self.ui.click((532, 515))
            else:
                time.sleep(.5)
        raise EventUIError('未确认冒险→特别关卡→露娜之塔，未开战')

    def catalogue(self):
        from ..news import fetch_event_news
        snapshot = getattr(self.robot, '_event_news', None) or fetch_event_news()
        event = snapshot.tower
        if not self.event_valid(event) or type(event.extras.get('max_floor')) is not int:
            raise EventUIError('当前露娜塔区域或最高层未知')
        self.report['schedule'] = dict(event.extras)
        return event

    def state_path_for(self,event):
        account=self.options.get('account_key',getattr(self.driver,'device_name',getattr(self.driver,'index','default')))
        key=sha256(str((account,event.extras['schedule_id'])).encode()).hexdigest()[:24]
        return Path(self.options.get('state_dir','cache/daily/tower_state'))/(key+'.json')

    def note_profile_change(self,name,record):
        self.state['profile_generation']=self.state.get('profile_generation',0)+1
        self.state.setdefault('profile_changes',[]).append(dict(record,name=name))
        self.state.pop('phase_trial',None)
        self.state.pop('phase_simulation',None)
        self.save()

    def remember_party(self,names,instant,source,floor,*,auto=True):
        if (not isinstance(names,list) or not isinstance(instant,dict) or len(names)!=5
                or any(not isinstance(n,str) or n.startswith(('slot:','unit:')) for n in names)
                or len(set(names))!=5 or set(names)!=set(instant)
                or any(type(v) is not bool for v in instant.values())):return
        entry=dict(names=list(names),instant=dict(instant),source=source,floor=floor,auto=auto,
                   outcome='win',at=time.time())
        previous=self.state.get('winning_parties',[])
        self.state['winning_parties']=([entry]+[w for w in previous if
            w.get('names')!=entry['names'] or w.get('instant')!=entry['instant']])[:12]

    def recover_roles(self,screen):
        """Daily free HP recovery only; enemy progress must stay unchanged."""
        if self.state.get('pending_battle') or not field.recovery_ready(screen):return False
        before=field.target_signature(screen)
        self.ui.expect_click('角色全回复',(315,405,455,455),exact=True)
        dialog=self.ui.wait(field.recovery_confirmation,'免费角色全回复说明',timeout=5)
        button=dialog.find('确认',(485,345,705,400),exact=True)
        if not dialog.blue_button(button):raise EventUIError('免费角色回复确认按钮未核实')
        request=dict(kind='free_daily_recovery_requested',cost=0,target=before,
            battle_count=len(self.state.get('phase_battles',[])),at=time.time(),
            evidence=str(self.ui.save('role_recovery_before',dialog)))
        self.state['role_recovery_request']=request
        self.note_profile_change('*',request)
        self.ui.click(button)
        receipt=self.ui.wait(field.recovery_receipt,'角色全回复完成',timeout=10)
        evidence=str(self.ui.save('role_recovery_complete',receipt))
        self.ui.expect_click('确认',(365,345,595,405),exact=True)
        after=self.ui.wait(field.home,'角色回复后塔顶',timeout=10)
        if field.target_signature(after)!=before:raise EventUIError('角色回复后敌方进度变化，停止开战')
        self.state['role_recovery_battle_count']=request['battle_count']
        self.state.pop('role_recovery_request',None)
        self.report.setdefault('free_recoveries',[]).append(dict(target=before,evidence=evidence,cost=0))
        self.save()
        return True

    def combat_return(self, screen):
        return field.home(screen)

    def combat_pre_dialog(self, screen):
        if field.title(screen):
            self._combat_interrupted=True
            self._phase_trace=None
            raise EventUIError('游戏返回标题页，本次战斗未完整结算')
        return False

    def combat_result_button(self, screen):
        outcome=field.battle_result(screen)
        if outcome=='failed':
            return field.confident(screen,'前往露娜之塔',(600,390,950,535))
        return screen.find('下一步', (700, 420, 940, 530), exact=True) if outcome else None


@register('luna_tower_clean')
class LunaTowerClean(TowerTask):
    """Compatibility daily: never sweep old coordinates in the revised tower."""
    def run(self):
        try:
            event = self.catalogue()
            if event.extras.get('cloister_quest_id') == 0:
                self.report.update(status='unavailable', reason='当前露娜塔区域没有回廊，跳过回廊扫荡')
            else:
                self.enter()
                self.report.update(status='blocked', reason='此区域有回廊定义，现场扫荡条件尚未核实，未消费')
            return self.report
        finally:
            self.save()


@register('luna_tower_climb')
class LunaTowerClimb(TowerTask):
    """Climb normal floors using this floor's in-game winning recommendations."""

    def open_recommendations(self, floor):
        s = self.enter()
        if field.floor_number(s) != floor:
            raise EventUIError('推荐入口的目标楼层发生变化')
        self._recommendation_target=field.target_signature(s)
        self.ui.click(s.find('通关队伍', (775, 80, 925, 125), exact=True))
        retries=0
        def retry_entry(frame):
            nonlocal retries
            self.check_deadline()
            if retries<2 and field.floor_number(frame)==floor:
                button=field.confident(frame,'通关队伍',(775,80,925,125))
                if button:
                    retries+=1
                    self.ui.click(button,delay=1.5)
        s = self.ui.wait(lambda f: field.recommendations(f, floor), '当前楼层通关队伍',handle=retry_entry)
        for _ in range(self.options['max_pages']):
            if not self.ui.scrollbar(s, (918,75,927,426), -1, content_distance=230,
                                     content_roi=(260,80,820,429)):
                return s
            s = self.capture()
            if not field.recommendations(s,floor):
                raise EventUIError('推荐列表回顶部时楼层未知')
        raise EventUIError('推荐列表回顶部达到翻页上限')

    def candidate(self, floor, tried, wanted=None, *, simulate=True):
        self.open_recommendations(floor)
        for page in range(self.options['max_pages']):
            s = self.capture()
            if not field.recommendations(s, floor):
                raise EventUIError('露娜塔推荐列表楼层未核实')
            for row in field.recommendation_rows(s,grouped=floor==self.report.get('schedule',{}).get('max_floor')):
                names = self.formation.avatars.query(row.portraits)
                names = [normalized(n) if n and not str(n).startswith('unit:') else None for n in names]
                key = self.source_key(row)
                rejected=False
                for failed in (self.state.get('retreated',[])+self.state.get('failed_parties',[])
                               +self.state.get('failed_phase_parties',[])):
                    if (failed.get('floor')!=floor or failed.get('target')!=getattr(self,'_recommendation_target',None)
                            or failed.get('profile_generation',0)!=self.state.get('profile_generation',0)
                            or not 0<=time.time()-failed.get('at',0)<900):continue
                    prior=cv.imread(str(failed.get('before','')))
                    if prior is not None and field.matches_formation(type(s)(prior,[]),row.portraits,self.formation.avatars):
                        rejected=True;break
                if rejected:
                    tried.add(key)
                    continue
                if wanted and key != wanted['key'] or not wanted and key in tried:
                    continue
                if not wanted and len(tried) >= self.options['max_candidates']:
                    raise EventUIError('达到本层通关队伍候选上限')
                fresh = self.capture()
                matching = [r for r in field.recommendation_rows(fresh,
                            grouped=floor==self.report.get('schedule',{}).get('max_floor')) if r.mode == row.mode
                            and field.same_faces(row.portraits,r.portraits)]
                if len(matching) != 1:
                    continue
                self.ui.save('recommendation_'+str(floor)+'_'+str(len(tried)), fresh)
                self.ui.click(matching[0].button)
                previous, previous_faces, repeats = None, None, 0
                def stable_preview(frame):
                    nonlocal previous, previous_faces, repeats
                    slots = field.preview_slots(frame)
                    faces=field.preview_faces(frame) if slots and all(slots) else None
                    same_faces=(faces is None and previous_faces is None or faces is not None and previous_faces is not None
                        and (field.same_faces(faces,previous_faces) or all(cv.norm(a,b,cv.NORM_INF)<1 for a,b in zip(faces,previous_faces))))
                    repeats = repeats+1 if slots is not None and slots == previous and same_faces else int(slots is not None)
                    previous = slots
                    previous_faces=faces
                    return repeats >= 2
                preview = self.wait(stable_preview, '通关队伍预览转场完成')
                if not field.preview_complete(preview):
                    tried.add(key)
                    self.report['rejected'].append(dict(floor=floor, reason='推荐预览缺员', names=names,
                        evidence=str(self.ui.save('missing_preview_'+str(floor)+'_'+str(len(tried)),preview))))
                    self.ui.click(preview.find('取消', (260, 340, 410, 410), exact=True))
                    self.wait(lambda f: field.recommendations(f, floor), '取消缺员推荐')
                    continue
                confirmed_faces=field.preview_faces(preview)
                names=[normalized(n) if n and not str(n).startswith('unit:') else None
                       for n in self.formation.avatars.query(confirmed_faces)]
                self.ui.save('team_confirmation_'+str(floor)+'_'+str(len(tried)),preview)
                if wanted and not simulate and wanted.get('simulated') is not True:
                    raise EventUIError('没有当前进程通过的模拟结果，拒绝实战')
                label = '在模拟战中使用' if simulate else '在实战中使用'
                button = preview.find(label, (410, 340, 700, 410), exact=True)
                if not preview.blue_button(button):
                    raise EventUIError('通关队伍的挑战方式按钮不可用')
                self.ui.click(button)
                stable = 0
                def ready(frame):
                    nonlocal stable
                    try:
                        self.verify_members(frame, names, simulate=simulate, portraits=confirmed_faces)
                    except EventUIError:
                        stable = 0
                        return False
                    stable += 1
                    return stable >= 2
                formation = self.wait(ready, '露娜塔五人编队转场完成')
                if wanted and field.party_vitals(formation) != wanted['vitals']:
                    raise EventUIError('实战队伍的生命或技能值状态与模拟起点不同，未开战')
                return dict(key=key, names=names, mode=row.mode,
                            multi_party=row.multi_party,
                            source='游戏内'+str(floor)+'层通关队伍', floor=floor,
                            vitals=field.party_vitals(formation), source_portraits=row.portraits,
                            formation_portraits=field.formation_faces(formation))
            s = self.capture()
            if not field.recommendations(s, floor):
                raise EventUIError('露娜塔推荐翻页前页面未知')
            if not self.ui.scrollbar(s, (918, 75, 927, 426), 1, content_distance=230,
                                     content_roi=(260, 80, 820, 429)):
                break
        self.ui.expect_click('关闭', (375, 445, 590, 515), exact=True)
        return None

    def verify_members(self, screen, names, *, simulate, portraits=None):
        if (not field.formation(screen) or len(self.formation.occupied_slots(screen)) != 5
                or simulate != field.simulation_formation(screen)):
            raise EventUIError('露娜塔五人编队或模拟／实战方式不符')
        if portraits is not None:
            if not field.matches_formation(screen,portraits,self.formation.avatars):
                raise EventUIError('实际五人衣装或顺序与通关队伍不一致')
        else:
            observed = self.formation.avatars.query([face_crop(screen.image, (x-48, 378, 96, 96))
                                                    for x, _ in self.formation.slots])
            if [normalized(n) if n else None for n in observed] != names:
                raise EventUIError('实际五人衣装或顺序与通关队伍不一致')
        if screen.find('无法战斗|限制实战|未持有', (30, 350, 930, 525)):
            raise EventUIError('编队角色不可用，未开战')

    def audit(self, candidate):
        self.report_progress(f"露娜塔 · {candidate['floor']}层 · 核对五人培养与装备")
        actual = self.formation.inspect_current(full=True, expected_names=[n for n in candidate['names'] if n])
        unknown = [a.name for a in actual if a.identity_verified and a.unique is None
                   and a.unique2 is None and a.name not in self.equipment_checked]
        if unknown:
            # Missing badges are not proof that a weapon is absent. Reuse the
            # shared read-only character page, then reopen this exact source.
            from ..game_ui.character_equipment import inspect_unreleased_equipment
            from .task_home import ToHomePage
            self.enter()
            confirmed = False
            for name in unknown:
                self.report_progress('露娜塔 · 补查专武状态 · '+name)
                self.equipment_checked.add(name)
                # Each lookup can end on the character-strengthening page, which
                # neither the next lookup nor the tower entry can leave.
                ToHomePage(self.robot).run(timeout=60)
                proof = inspect_unreleased_equipment(self.ui, name)
                ToHomePage(self.robot).run(timeout=60)
                if proof:
                    self.formation.unreleased[normalized(name)] = (time.time(), proof)
                    confirmed = True
            if confirmed:
                refreshed = self.candidate(candidate['floor'],set(),wanted=candidate,
                                           simulate=not candidate.get('real',False))
                if refreshed is None:
                    raise EventUIError('专武只读核验后原通关队伍不再可用')
                candidate.update(refreshed)
                return self.audit(candidate)
        if (len(actual) != 5 or any(n and normalized(a.name) != n for a,n in zip(actual,candidate['names']))
                or any(not a.identity_verified or any(getattr(a, k) is None for k in
                       ('level', 'rank', 'stars', 'skill_level', 'unique', 'unique2'))
                       or any(type(getattr(a,k)) is not int or getattr(a,k) <= 0
                              for k in ('level','rank','stars','skill_level'))
                       or a.stars > 6 or type(a.unique) is not bool or type(a.unique2) is not bool
                       for a in actual)):
            raise EventUIError('露娜塔推荐队伍身份、培养或独立专武未核实，未开战')
        candidate['names'] = [normalized(a.name) for a in actual]
        self.report.setdefault('audits', []).append(dict(floor=candidate['floor'], observed=[asdict(a) for a in actual]))
        return EventParty('楼层通关队伍', candidate['source'], [MemberRequirement(
            a.name, a.level, a.rank, a.stars, a.unique, a.unique2,
            candidate['mode'] == '立即发动', a.skill_level) for a in actual],
            auto=True, max_attempts=1, build_basis='game_recommendation_current_account')

    def simulation_party(self,candidate):
        # Source-to-formation portrait matching already establishes the five
        # slots. Unknown public names do not require opening character pages.
        order=[name or 'slot:'+str(i+1) for i,name in enumerate(candidate['names'])]
        if len(order)!=5 or len(set(order))!=5:
            raise EventUIError('露娜塔五个出战位置未确认')
        candidate['combat_order']=order
        return EventParty('楼层通关队伍',candidate['source'],[
            MemberRequirement(name,0,0,0,None,None,candidate['mode']=='立即发动',0)
            for name in order],auto=True,max_attempts=1,allow_deaths=4,build_basis='game_recommendation_simulation')

    def battle(self, candidate, party, *, simulate):
        self.report_progress(f"露娜塔 · {candidate['floor']}层 · "+('免费模拟' if simulate else '实战核验'))
        s = self.capture()
        self.verify_members(s, candidate['names'], simulate=simulate, portraits=candidate.get('formation_portraits'))
        button = s.find('模拟战开始' if simulate else '战斗开始', (780, 420, 930, 490), exact=True)
        if not s.blue_button(button):
            raise EventUIError('露娜塔开战按钮不可用')
        if not simulate:
            if self.state.get('pending_battle'):
                raise EventUIError('上次露娜塔实战未核账，未重复开战')
            self.state['pending_battle'] = dict(floor=candidate['floor'], names=candidate['names'],
                                              instant={m.name:m.instant for m in getattr(party,'members',[])},
                                              auto=getattr(party,'auto',True),
                                              source=candidate.get('source','游戏内当前层通关队伍'),
                                              vitals=field.party_vitals(s),target=candidate.get('target_before'),
                                              before=str(self.ui.save('real_before_'+str(candidate['floor'])+'_'+
                                                  str(len(self.state.get('retreated',[]))), s)))
            self.save()
        self._result = None
        if simulate:
            simulation_before=str(self.ui.save('simulation_before_'+str(candidate['floor'])+'_'+
                str(len(self.state.get('failed_parties',[]))),s))
        self.ui.click(button)
        result = self.combat.run(party, candidate.get('combat_order',candidate['names']), resume=True)
        after = self.enter()
        self.report.setdefault('combat_results',[]).append(dict(floor=candidate['floor'],simulate=simulate,
            outcome=result.outcome,reason=result.reason))
        if simulate:
            if field.floor_number(after) != candidate['floor']:
                raise EventUIError('模拟战后目标楼层改变，未实战')
            self.report.setdefault('simulation_targets',[]).append(dict(floor=candidate['floor'],
                after=field.target_signature(after)))
            won=self._result == 'win' and result.outcome == 'settled'
            if not won and not candidate.get('multi_party'):
                self.state.setdefault('failed_parties',[]).append(dict(floor=candidate['floor'],before=simulation_before,
                    target=field.target_signature(after),at=time.time(),profile_generation=self.state.get('profile_generation',0)))
                self.save()
            return won
        if result.outcome=='retreated':
            self.state['pending_battle']['outcome']='retreated'
            self.save()
            self.recover_retreat(after,self.state['pending_battle'])
            return None
        if self._result != 'win' or not self.progressed(after, candidate['floor']):
            raise EventUIError('实战未确认胜利和楼层推进，保留待核账记录')
        self.report['cleared'].append(dict(floor=candidate['floor'], names=candidate['names'],
                                           after=str(self.ui.save('clear_'+str(candidate['floor']), after))))
        self.remember_party(candidate['names'],{m.name:m.instant for m in getattr(party,'members',[])},
                            candidate.get('source','游戏内当前层通关队伍'),candidate['floor'],auto=getattr(party,'auto',True))
        self.state.pop('pending_battle')
        self.save()
        return after

    def recover_retreat(self,screen,pending):
        """Release only a confirmed retreat whose enemy and party were restored."""
        before=cv.imread(str(pending.get('before','')))
        if (pending.get('outcome')!='retreated' or before is None
                or field.target_signature(screen)!=pending.get('target')
                or field.floor_number(screen)!=pending['floor']):
            raise EventUIError('撤退后的楼层或敌方状态未核实，保留待核账记录')
        button=field.confident(screen,'挑战',(700,395,930,465))
        if button is None:raise EventUIError('撤退后挑战入口未确认，未追加挑战')
        self.ui.click(button)
        current=self.wait(lambda s: field.formation(s) and not field.simulation_formation(s),'撤退后队伍状态')
        if (not field.same_faces(field.formation_faces(type(current)(before,[])),field.formation_faces(current))
                or [list(v) for v in field.party_vitals(current)]!=[list(v) for v in pending.get('vitals',[]) ]):
            raise EventUIError('撤退后五人生命或TP未恢复，保留待核账记录')
        pending['at']=time.time()
        pending['profile_generation']=self.state.get('profile_generation',0)
        self.state.setdefault('retreated',[]).append(dict(pending))
        self.state.pop('pending_battle')
        self.save()
        self.enter()

    def recover_phase_result(self,screen,pending):
        from .tower_guides import phase_progress
        if (pending.get('outcome')!='failed' or pending.get('phase') not in (1,2,3)
                or not isinstance(pending.get('target'),dict)
                or field.floor_number(screen)!=pending.get('floor')):
            raise EventUIError('塔顶上刀结算或目标未知，保留待核账记录')
        after=field.target_signature(screen)
        progressed=phase_progress(pending['target'],after,pending['phase'])
        # Keep the ordinary ledger schema; the pending screenshot path is evidence, not a target.
        self.state.setdefault('phase_battles',[]).append(dict(simulate=False,phase=pending['phase'],
            names=pending.get('names',[]),outcome=pending['outcome'],result=pending['outcome'],
            passed=progressed,before=pending['target'],after=after,hp_samples=[],shadow_samples=[],
            initial_boss_hp=None,recovered=True,before_evidence=pending.get('before'),
            result_evidence=pending.get('result')))
        self.state.pop('pending_battle')
        self.state.pop('phase_trial',None)
        self.save()
        if not progressed:raise EventUIError('上刀已完整结算但未确认净削血，停止追加实战')

    def observe_battle(self, screen):
        if trace:=getattr(self,'_phase_trace',None):
            count=len(trace.shadow_samples)
            trace.observe(screen)
            if len(trace.shadow_samples)>count and trace.shadow_samples[-1]['seconds']<=25:
                sample=trace.shadow_samples[-1]
                sample['evidence']=str(self.ui.save('phase_shadow_'+str(len(self.report.get('phase_battles',[])))+
                    '_'+str(sample['seconds']),screen))
        outcome = field.battle_result(screen)
        if outcome:
            self._result = outcome
            if self.state.get('pending_battle'):
                self.state['pending_battle'].update(outcome=outcome, result=str(self.ui.save('real_result', screen)))
                self.save()

    @staticmethod
    def progressed(screen, floor):
        current = field.floor_number(screen)
        return current is not None and (current > floor or current == floor and field.selected_cleared(screen))

    def advance(self, screen, floor):
        if field.floor_number(screen) == floor and field.selected_cleared(screen):
            next_row = field.confident(screen, str(floor+1)+'阶', (55, 75, 250, 460))
            if not next_row:
                raise EventUIError('下一层入口未知，未点击锁定楼层')
            self.ui.click(next_row)
            return self.wait(lambda s: field.floor_number(s) == floor+1, '下一层楼层核验')
        return screen

    def phase_formation(self, plan, *, simulate):
        if plan.get('game_record'):
            candidate=self.candidate(plan['floor'],plan['tried'],wanted=plan.get('candidate') if not simulate else None,
                                     simulate=simulate)
            if candidate is None:raise NoTowerCandidate('没有新的完整游戏通关分队')
            plan['tried'].add(candidate['key'])
            plan['candidate']=candidate
            order=[name or 'slot:'+str(i+1) for i,name in enumerate(candidate['names'])]
            plan.update(names=order,source=candidate['source'],
                        instant={n:candidate['mode']=='立即发动' for n in order})
            return self.phase_equipment(self.capture(),order,plan,simulate=simulate),order
        screen=self.enter()
        mode=field.confident(screen,'模拟战' if simulate else '实战',(700,325,930,380))
        if not mode:raise EventUIError('塔顶模拟／实战切换未确认')
        self.ui.click(mode)
        self.ui.expect_click('挑战',(700,395,930,465),exact=True)
        self.wait(lambda s: field.formation(s) and field.simulation_formation(s)==simulate,'塔顶阶段编队')
        screen,order=self.formation.select_fast(plan['names'],self.avatar_manifest,support_name=plan.get('support'))
        if plan.get('support'):
            self.log('使用同衣装支援 '+plan['support'])
            screen,order,support=self.formation.select_support(plan['support'],self.avatar_manifest,
                wanted=plan.get('support_proof') if not simulate else None)
            plan['support_proof']=support
        if len(order)!=5 or set(order)!=set(plan['names']):raise EventUIError('塔顶五人身份与阶段计划不符')
        return self.phase_equipment(screen,order,plan,simulate=simulate),order

    def phase_equipment(self,screen,order,plan,*,simulate):
        if simulate and self.options['auto_equip'] and not plan.get('support'):
            from ..game_ui.special_equipment import auto_equip_special
            # Another party may borrow equipment from the previously tested
            # five. Their HP/TP alone cannot preserve that older battle proof.
            self.state.pop('phase_trial',None)
            self.state.pop('phase_simulation',None)
            self.save()
            original_faces=field.formation_faces(screen)
            priorities=dict(weapon='rarity')
            priorities.update(self.options['auto_equip_priorities'])
            self.report.setdefault('phase_equipment',[]).append(
                auto_equip_special(self.ui,order,priorities=priorities,verify_slots=False))
            # Rebind the already identified five portraits after the panel
            # closes; no need to recognize every outfit from scratch again.
            screen=self.ui.wait(lambda s:field.formation(s) and
                field.same_faces(original_faces,field.formation_faces(s)),
                '特别装备返回后原五人编队',timeout=5)
        return screen

    def pause_battle_early(self):
        until=time.monotonic()+30
        while time.monotonic()<until:
            self.check_deadline()
            screen=self.ui.capture(ocr=False)
            menu=self.combat.match('btn_menu_text',screen)
            if menu and 840<=menu[0]<=960 and 0<=menu[1]<=65:
                self.ui.click(menu,delay=.1)
                return True
            time.sleep(.1)
        return False

    def repair_temporary_stars(self,plan,formation,order):
        # Only a failed frontline with an explicit reduced-star badge is
        # visited. Passing simulations never enter character pages.
        name=order[-1]
        if (plan.get('stars',{}).get(name)!=5 or plan.get('support')==name
                or not field.reduced_star_badge(formation,4)):
            return False
        from ..game_ui.character_stars import restore_unlocked_five
        from .task_home import ToHomePage
        changed=restore_unlocked_five(self.ui,name,self.report,self.save)
        if changed:
            self.note_profile_change(name,self.report['star_changes'][-1])
        # The star page ends on character strengthening, which the tower's own exits cannot leave.
        ToHomePage(self.robot).run(timeout=60)
        self.enter()
        return changed

    def proof_token(self):
        """Between runs other tasks can move special equipment, and portraits and vitals would not show it."""
        if not hasattr(self,'_proof_token'):
            self._proof_token=uuid4().hex
        return self._proof_token

    def phase_battle(self, plan, *, simulate, expected=None):
        from .tower_guides import PhaseTrace, phase_progress, PHASE_GOAL_VERSION,carried_boss_hp
        if not simulate and (not expected or not expected.get('passed')):
            raise EventUIError('本阶段尚未通过完整免费模拟，未实战')
        before=field.target_signature(self.enter())
        screen,order=self.phase_formation(plan,simulate=simulate)
        vitals=field.party_vitals(screen)
        faces=field.formation_faces(screen)
        evidence=str(self.ui.save('phase_simulation_before_'+str(len(self.report.get('phase_battles',[]))),screen)) if simulate else None
        if expected and (order!=expected['order'] or vitals!=expected['vitals']
                or not field.same_faces(faces,expected['faces']) or before!=expected['target']):
            raise EventUIError('实战五人、生命TP或敌方状态与阶段模拟起点不同，未开战')
        if not simulate and plan.get('support'):
            if plan.get('support_proof')!=expected.get('support_proof'):
                raise EventUIError('实战支援提供者与模拟不同，未开战')
            raise EventUIError('支援实战费用尚未核验，未开战')
        party=EventParty('塔顶阶段'+str(plan['phase']),plan['source'],[
            MemberRequirement(n,0,0,0,None,None,plan['instant'][n],0) for n in order],
            auto=True,max_attempts=1,allow_deaths=4,build_basis='phase_simulation')
        button=screen.find('模拟战开始' if simulate else '战斗开始',(780,420,930,490),exact=True)
        if not screen.blue_button(button):raise EventUIError('塔顶阶段开战按钮不可用')
        if not simulate:
            if self.state.get('pending_battle'):raise EventUIError('塔顶上刀未核账，未追加实战')
            self.state['pending_battle']=dict(floor=before['floor'],phase=plan['phase'],
                target=before,names=order,before=str(self.ui.save('phase_real_before_'+
                    str(len(self.state.get('phase_battles',[]))),screen)))
            self.save()
        self._result=None
        initial_hp=carried_boss_hp(self.state.get('phase_battles',[]),before)
        self._phase_trace=PhaseTrace(plan['goal'],before,initial_hp=initial_hp)
        try:
            self.ui.click(button,delay=.1)
            self.pause_battle_early()
            result=self.combat.run(party,order,resume=True)
        except (OSError,subprocess.SubprocessError) as error:
            if simulate:
                self.state.setdefault('runtime_failed_phase_trials',[]).append(dict(
                    target=before,names=order,instant=dict(plan['instant']),support=plan.get('support'),
                    phase=plan['phase'],at=time.time(),error=type(error).__name__,
                    profile_generation=self.state.get('profile_generation',0)))
                self.save()
            raise
        after=self.enter()
        won=self._result=='win' and self.progressed(after,before['floor']) if not simulate else self._result=='win'
        passed=result.outcome!='retreated' and self._phase_trace.passed(
            won=won,settled=self._result in ('failed','win'))
        record=dict(simulate=simulate,phase=plan['phase'],names=order,source=plan['source'],
            support=plan.get('support'),support_proof=plan.get('support_proof'),
            trial_reason=plan.get('trial_reason'),
            outcome=result.outcome,result=self._result,passed=passed,before=before,
            after=field.target_signature(after),initial_boss_hp=initial_hp,hp_samples=self._phase_trace.samples,
            shadow_samples=self._phase_trace.shadow_samples)
        self.report.setdefault('phase_battles',[]).append(record)
        self._phase_trace=None
        if simulate:
            if before!=field.target_signature(after):raise EventUIError('阶段模拟改变敌方状态，未提交实战')
            if passed and plan.get('candidate'):
                plan['candidate']['simulated']=True
            if self._result in ('failed','win') and not any(n.startswith('slot:') for n in order):
                proof=dict(passed=passed,order=order,vitals=vitals,target=before,run_token=self.proof_token(),
                    before=evidence,at=time.time(),support_proof=plan.get('support_proof'),
                    result=self._result,hp_samples=record['hp_samples'],shadow_samples=record['shadow_samples'],
                    initial_boss_hp=initial_hp,
                    plan={k:plan[k] for k in ('phase','goal','source','names','instant','stars','support','support_proof',
                                             'trial_reason','outgoing','incoming') if k in plan})
                self.state['phase_simulation']=proof
                if passed:self.state['phase_trial']=proof
            if not passed and result.outcome!='retreated':
                self.state.setdefault('failed_phase_parties',[]).append(dict(floor=before['floor'],target=before,
                    before=evidence,at=time.time(),names=order,support=plan.get('support'),
                    instant=dict(plan['instant']),
                    hp_samples=record['hp_samples'],shadow_samples=record['shadow_samples'],
                    equipment_mode=self.options['auto_equip'],
                    gear_policy=({'weapon':'rarity',**self.options.get('auto_equip_priorities',{})}
                                 if self.options['auto_equip'] else None),
                    goal_version=PHASE_GOAL_VERSION,
                    profile_generation=self.state.get('profile_generation',0)))
        else:
            if self._result not in ('win','failed'):
                raise EventUIError('塔顶本刀未完整结算，保留待核账记录')
            self.state.setdefault('phase_battles',[]).append(record)
            self.state.pop('pending_battle')
            self.state.pop('phase_trial',None)
            if won:
                self.report['cleared'].append(dict(floor=before['floor'],after=str(self.ui.save('clear_top',after))))
            elif not phase_progress(before,record['after'],plan['phase']):
                self.save()
                raise EventUIError('实战未确认敌方生命继承进展，停止追加实战')
        self.save()
        changed=(self.repair_temporary_stars(plan,screen,order) if simulate and not passed
                 and self._result=='failed' else False)
        return dict(passed=passed,won=won,order=order,vitals=vitals,faces=faces,target=before,
                    support_proof=plan.get('support_proof'),profile_changed=changed)

    def climb_top(self, screen):
        """A settled partial defeat can complete a phase of the cumulative boss."""
        from .tower_guides import load_guides,prefer_proven,with_support_trials,with_tank_trials,with_shadow_followups,prefer_untried,remembered_trials,trial_key,phase_progress,PHASE_GOAL_VERSION,IDENTITY_VERSION,PhaseTrace,top_phase
        floor=field.floor_number(screen)
        with closing(sqlite3.connect('cache/redive_cn.db')) as conn:
            costs=conn.execute('SELECT stamina,stamina_start FROM tower_quest_data WHERE floor_num=?',(floor,)).fetchall()
        if not costs or any(row!=(0,0) for row in costs):raise EventUIError('塔顶体力消耗未知或非零')
        plans=load_guides(self.options,floor,self.formation.avatars,self.avatar_manifest,check=self.check_deadline)
        if self.options['video_guides']:
            from .tower_boards import board_plans
            self.report_progress('露娜塔 · 解析国服练度表')
            boards,notes=board_plans(self.options,floor,self.formation.avatars,check=self.check_deadline)
            self.report['board_sources']=notes
            # This server's own daily plans come before cross-server articles.
            plans=boards+plans
        plans=prefer_proven(plans,self.state.get('phase_battles',[]))
        spent={n for b in self.state.get('phase_battles',[])[self.state.get('role_recovery_battle_count',0):]
               if b.get('result')=='failed'
               for n in b.get('names',[]) if n!=b.get('support')}
        plans=with_shadow_followups(plans,spent)
        if self.options.get('support_trials',True) or self.options.get('tank_trials',True):
            from .party_variants import character_roles
            roles=character_roles()
            if self.options['support_trials']:
                plans=with_support_trials(plans,roles,prefer=self.options['prefer_support'])
            if self.options.get('tank_trials',True):
                with closing(sqlite3.connect('cache/redive_cn.db')) as conn:
                    talents={normalized(n):t for n,t in conn.execute('SELECT p.unit_name,t.talent_id FROM unit_profile p '
                        'JOIN unit_talent t ON p.unit_id=t.unit_id')}
                plans=with_tank_trials(plans,roles,talents)
        tried=set();record_tried={};trials=0
        for _ in range(self.options['max_candidates']):
            screen=self.enter()
            if field.selected_cleared(screen):
                self.report['status']='complete'
                return self.report
            target=field.target_signature(screen)
            phase=top_phase(target)
            last=self.state.get('phase_battles',[])[-1:]
            spent_battles=self.state.get('phase_battles',[])[self.state.get('role_recovery_battle_count',0):]
            needs_recovery=any(b.get('result')=='failed' for b in spent_battles)
            if (self.options['free_recovery'] and not self.options['simulation_only']
                    and not getattr(self,'_recovery_checked',False) and needs_recovery):
                self._recovery_checked=True
                if self.recover_roles(screen):return self.climb_top(self.enter())
            recent_trial=self.state.get('phase_simulation',{})
            if (recent_trial.get('target')==target and recent_trial.get('plan',{}).get('phase')==phase
                    and recent_trial.get('result') in ('failed','win')
                    and 0<=time.time()-recent_trial.get('at',0)<1800):
                trace=PhaseTrace(recent_trial['plan']['goal'],target,initial_hp=recent_trial.get('initial_boss_hp'))
                trace.samples=recent_trial.get('hp_samples',[])
                trace.shadow_samples=recent_trial.get('shadow_samples',[])
                if trace.passed(won=recent_trial['result']=='win',settled=True):
                    self.state['phase_trial']=dict(recent_trial,passed=True)
            proof=self.state.get('phase_trial',{})
            if (not self.options['simulation_only'] and proof.get('passed') and proof.get('target')==target
                    and proof.get('run_token')==self.proof_token()
                    and proof.get('plan',{}).get('phase')==phase and 0<=time.time()-proof.get('at',0)<1800
                    and Path(proof.get('before','')).is_file()):
                before=cv.imdecode(np.frombuffer(Path(proof['before']).read_bytes(),np.uint8),cv.IMREAD_COLOR)
                if before is not None:
                    proof=dict(proof,faces=field.formation_faces(type(screen)(before,[])),
                               vitals=[tuple(v) for v in proof['vitals']])
                    real=self.phase_battle(proof['plan'],simulate=False,expected=proof)
                    if real['won']:
                        self.report['status']='complete'
                        return self.report
                    if self.attack_budget_spent():return self.report
                    continue
            failed=[f for f in self.state.get('failed_phase_parties',[]) if f.get('target')==target
                    and f.get('goal_version')==PHASE_GOAL_VERSION
                    and f.get('profile_generation',0)==self.state.get('profile_generation',0)
                    and f.get('equipment_mode',False)==self.options['auto_equip']
                    and (not self.options['auto_equip'] or f.get('gear_policy')==
                         {'weapon':'rarity',**self.options.get('auto_equip_priorities',{})})]
            recent=[f for f in failed if 0<=time.time()-f.get('at',0)<3600]
            interrupted=[f for f in self.state.get('runtime_failed_phase_trials',[])
                if f.get('target')==target and f.get('profile_generation',0)==self.state.get('profile_generation',0)
                and 0<=time.time()-f.get('at',0)<3600]
            unconfirmed={name for name,e in self.state.get('unconfirmed_phase_roles',{}).items()
                if e.get('profile_generation',0)==self.state.get('profile_generation',0)
                and e.get('identity_version')==IDENTITY_VERSION
                and 0<=time.time()-e.get('at',0)<3600}
            local=remembered_trials(self.state.get('winning_parties',[]),phase)
            spent={n for b in self.state.get('phase_battles',[])[self.state.get('role_recovery_battle_count',0):]
                   if b.get('result')=='failed' for n in b.get('names',[]) if n!=b.get('support')}
            available_plans=[p for p in plans+local
                             if not (set(p['names'])-{p.get('support')})&spent]
            plan=next((p for p in prefer_untried(available_plans,failed+interrupted) if p['phase']==phase and trial_key(p,target) not in tried
                       and not (set(p['names'])-{p.get('support')})&unconfirmed
                       and not any(set(p['names'])==set(f.get('names',[])) and p.get('support')==f.get('support')
                                   and (f.get('instant') is None or p['instant']==f['instant'])
                                   for f in recent)),None)
            if plan:
                tried.add(trial_key(plan,target))
            else:
                plan=dict(phase=phase,floor=floor,game_record=True,
                          source='游戏内当前层通关队伍',
                          tried=record_tried.setdefault(str(target),set()),
                          goal='shadows' if phase==1 else 'boss_damage')
            self.report_progress('露娜塔 · 塔顶阶段'+str(phase)+' · 免费模拟')
            trials+=1
            if trials>self.options['top_trials_per_run']>0:
                self.report['status']='partial'
                self.report['pending'].append(f"塔顶本次已试 {trials-1} 队未通过，按 top_trials_per_run 留待下次接续")
                return self.report
            try:
                trial=self.phase_battle(plan,simulate=True)
            except EventUIError as error:
                self.report['rejected'].append(dict(phase=phase,source=plan['source'],support=plan.get('support'),reason=str(error)))
                if isinstance(error,NoTowerCandidate):
                    self.save()
                    raise
                # A failed outfit search is shared across source formations.
                # Cache only briefly; this does not assert the role is unowned.
                name=next((n for n in plan.get('names',[])
                    if str(error)==n+'的可用衣装未唯一确认，未开战'),None)
                if name:
                    self.state.setdefault('unconfirmed_phase_roles',{})[name]=dict(at=time.time(),
                        identity_version=IDENTITY_VERSION,
                        profile_generation=self.state.get('profile_generation',0))
                self.save()
                self.enter()
                if getattr(self,'_combat_interrupted',False):
                    self._combat_interrupted=False
                    self.state.pop('phase_trial',None)
                    if plan.get('candidate'):plan['tried'].discard(plan['candidate']['key'])
                    else:tried.discard(trial_key(plan,target))
                continue
            if trial.get('profile_changed'):
                tried.discard(trial_key(plan,target))
                continue
            if not trial['passed']:continue
            if self.options['simulation_only']:
                self.report.update(status='complete',simulation_only=True,phase=phase)
                return self.report
            self.report_progress('露娜塔 · 塔顶阶段'+str(phase)+' · 模拟目标通过，实战接续')
            real=self.phase_battle(plan,simulate=False,expected=trial)
            if real['won']:
                self.report['status']='complete'
                return self.report
            if self.attack_budget_spent():return self.report
        raise EventUIError('达到塔顶阶段模拟上限，可从实际生命状态接续')

    def attack_budget_spent(self):
        """The boss heals back whatever a weak second team leaves; tomorrow's recovery resets the party."""
        self._top_attacks=getattr(self,'_top_attacks',0)+1
        limit=self.options['top_attacks_per_run']
        if not limit or self._top_attacks<limit:return False
        self.report['status']='partial'
        self.report['pending'].append(f'塔顶本次已实战 {self._top_attacks} 刀，按 top_attacks_per_run 留待下次接续')
        return True

    def run(self):
        try:
            event = self.catalogue()
            self.state_path = self.state_path_for(event)
            if self.state_path.exists():
                try:
                    self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
                    if not isinstance(self.state, dict):
                        raise ValueError('state must be an object')
                except (ValueError, OSError) as error:
                    self.state_writable = False
                    raise EventUIError('露娜塔状态文件无法核对，未追加挑战') from error
            s = self.enter()
            if pending := self.state.get('pending_battle'):
                if pending.get('outcome')=='retreated':
                    self.recover_retreat(s,pending)
                    s=self.enter()
                elif pending.get('outcome') == 'win' and self.progressed(s, pending['floor']):
                    self.report['cleared'].append(dict(floor=pending['floor'], recovered=True))
                    self.remember_party(pending.get('names',[]),pending.get('instant',{}),
                        pending.get('source','此前普通楼层实战队伍'),pending['floor'],auto=pending.get('auto',True))
                    self.state.pop('pending_battle')
                    self.save()
                elif pending.get('phase') and pending.get('outcome')=='failed':
                    self.recover_phase_result(s,pending)
                else:
                    raise EventUIError('上次露娜塔实战尚未核账，未追加挑战')
            target = self.options['target_floor'] or event.extras['max_floor']
            if target > event.extras['max_floor']:
                raise EventUIError('目标层超出本期开放层数')
            self.report['target_floor'] = target
            if self.options['preview_only']:
                self.report.update(status='complete', current_floor=field.floor_number(s), preview=True)
                return self.report
            from ..game_ui.avatar_assets import ensure_avatar_index
            self.formation.avatars, avatar_manifest = ensure_avatar_index(self.options.get('avatars'), check=self.check_deadline)
            self.avatar_manifest=avatar_manifest
            if self.options['auto_equip']:
                prepare_character_database(self.formation, self.options, check=self.check_deadline)
            for _ in range(self.options['max_floors']):
                s = self.enter()
                floor = field.floor_number(s)
                if floor is None:
                    raise EventUIError('当前页面不是已适配的普通楼层，未挑战特别关卡')
                if floor > target or floor == target and field.selected_cleared(s):
                    self.report['status'] = 'complete'
                    return self.report
                if field.selected_cleared(s):
                    s = self.advance(s, floor)
                    floor = field.floor_number(s)
                if field.top_floor(s) and self.options.get('phase_guides',True):
                    return self.climb_top(s)
                before = field.target_signature(s)
                with closing(sqlite3.connect('cache/redive_cn.db')) as conn:
                    costs = conn.execute('SELECT stamina,stamina_start FROM tower_quest_data WHERE floor_num=?', (floor,)).fetchall()
                if not costs or any(row != (0, 0) for row in costs):
                    raise EventUIError('本层体力消耗未知或非零，未开战')
                tried, won = set(), False
                while len(tried) < self.options['max_candidates']:
                    self.report_progress(f'露娜塔 · {floor}层 · 查找模拟队伍')
                    candidate = self.candidate(floor, tried)
                    if candidate is None:
                        break
                    tried.add(candidate['key'])
                    try:
                        party = self.audit(candidate) if self.options['auto_equip'] else self.simulation_party(candidate)
                        gear = (prepare_special(self.formation,party,candidate['names'],auto=True)
                                if self.options['auto_equip'] else None)
                    except EventUIError as error:
                        self.report['rejected'].append(dict(floor=floor, names=candidate['names'], reason=str(error)))
                        self.save()
                        self.enter()  # Continue only from a newly verified map.
                        continue
                    self.save()
                    won = self.battle(candidate, party, simulate=True)
                    self.report['simulations'].append(dict(floor=floor, names=candidate['names'], win=won))
                    self.save()
                    if won:
                        candidate['simulated'] = True
                        break
                if not won:
                    raise EventUIError('没有已核验且模拟获胜的完整队伍，未实战')
                if self.options['simulation_only']:
                    self.report.update(status='complete', simulation_only=True)
                    return self.report
                after = field.target_signature(self.enter())
                self.report.setdefault('target_checks', []).append(dict(floor=floor,before=before,after=after))
                self.save()
                if after != before:
                    raise EventUIError('模拟后目标楼层或敌方生命状态变化，必须重新核验')
                real = self.candidate(floor, set(), wanted=candidate, simulate=False)
                if real is None:
                    raise EventUIError('模拟队伍不再可用，未实战')
                real['real'] = True
                real['simulated'] = True
                real['target_before']=before
                if self.options['auto_equip']:
                    real_party = self.audit(real)
                    if [asdict(m) for m in real_party.members] != [asdict(m) for m in party.members]:
                        raise EventUIError('模拟后角色培养或专武状态变化，必须重新模拟')
                    prepare_special(self.formation, party, candidate['names'], auto=False, expected=gear)
                else:
                    if not field.same_faces(candidate['formation_portraits'],real['formation_portraits']):
                        raise EventUIError('实战五人头像或顺序与模拟不同，未开战')
                    real['combat_order']=candidate['combat_order']
                self.report_progress(f'露娜塔 · {floor}层 · 模拟通过，实战推进')
                s = self.battle(real, party, simulate=False)
                if s is None:
                    continue
                if floor >= target:
                    self.report['status'] = 'complete'
                    return self.report
                self.advance(s, floor)
            self.report.update(status='partial', reason='达到本次楼层推进上限，可从实际楼层接续')
            return self.report
        except (RunCancelled, ResumeUnsafe):
            self.report['status'] = 'cancelled'
            raise
        except EventUIError as error:
            self.report.update(status='partial' if self.report['cleared'] else 'blocked', reason=str(error))
            self.report['pending'].append(str(error))
            self.ui.save('blocked')
            return self.report
        finally:
            self.save()
    def source_key(self, row):
        for index, (mode, faces) in enumerate(self.source_portraits):
            if mode == row.mode and field.same_faces(faces,row.portraits):
                return row.mode+':'+str(index)
        self.source_portraits.append((row.mode,row.portraits))
        return row.mode+':'+str(len(self.source_portraits)-1)
