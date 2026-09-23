"""Bounded deep-area progression through the normal Task/RunSession pipeline."""
from __future__ import annotations

from dataclasses import asdict
from collections import Counter
import json
from pathlib import Path
import re
from .base import BaseTask, TaskReport
from .registry import register
from .abyss_party import AbyssFormation
from .event_battle import EventCombat
from .abyss_history import AbyssHistory, team_key
from .abyss_retry import combat_sample, retry_decision
from .strategy_video import acquire_strategies, task_source_options
from .strategy_document import abyss_candidate
from ..game_ui.character_stars import upgrade_to_five
from ..game_ui.character_equipment import inspect_unreleased_equipment
from ..game_ui.special_equipment import inspect_special_equipment, auto_equip_special
from ..game_ui.abyss import AREAS, AbyssStage, map_element, next_stage, detail_stage, remaining, advanced
from ..game_ui.screen import EventScreen, EventUI, EventUIError
from ..run_session import clock as time, atomic_json


def source_set_alternative(source,trials):
    match=re.search(r'伤害不够[^\n]*?([OX]{5})',source.get('notes',''))
    if not match:return None
    flags=match[1]
    if any(t.get('formation',{}).get('set_adjustment',{}).get('flags')==flags
           and team_key(t['order'])==team_key(source['names']) for t in trials):return None
    return flags


def equipment_retrial(names,trials):
    """One fresh try is useful after EX gear was missing in every prior loss."""
    failures=[t for t in trials if team_key(t['order'])==team_key(names) and t.get('progressed') is not True]
    return bool(failures and all(not t.get('formation',{}).get('special_equipment') for t in failures))


def repeated_casualty(trials):
    """Name the repeatedly fallen member from actual slot order, if known."""
    fallen=[]
    for trial in trials:
        match=re.search(r'减员\d+人，位置\[(\d+)\]',trial.get('reason',''))
        order=trial.get('order',[])
        if match and int(match[1])<len(order):
            fallen.append(order[int(match[1])])
    if not fallen:return None
    counts=Counter(fallen)
    return max(reversed(fallen),key=lambda name:counts[name])


def source_for_stage(parties, stage, failed, previous):
    applicable=[p for p in parties if p['element']==stage.element and p.get('chapters')
                and p['chapters'][0]<=stage.chapter<=p['chapters'][1]
                and (not p.get('stages') or stage.key in p['stages'])
                and (not p.get('document') or p['document'].get('readiness') == 'ready')
                and stage.key not in p.get('excluded_stages',[])]
    return next((p for p in applicable if team_key(p['names']) not in failed
                 or source_set_alternative(p,previous)
                 or equipment_retrial(p['names'],previous)),None) or (applicable[0] if applicable else None)


def recent_unreleased(path, now, lifetime):
    """Reuse short-lived screenshot proof; live badges still gate every battle."""
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {}
    if data.get('version')!=1 or not isinstance(data.get('proofs'),dict):
        return {}
    result={}
    for name,row in data['proofs'].items():
        if not isinstance(name,str) or not isinstance(row,dict):continue
        stamp,evidence=row.get('time'),row.get('evidence')
        if (isinstance(stamp,(int,float)) and isinstance(evidence,str)
                and Path(evidence).is_file() and 0<=now-stamp<lifetime):
            result[name]=(stamp,evidence)
    return result


def validate_options(options: dict) -> dict:
    value = dict(options)
    for key, default, high in [('max_failures_per_stage', 6, 50), ('max_repeat_failures_per_stage', 2, 50), ('max_battles', 100, 300),
                                ('timeout', 3600, 14400), ('battle_timeout', 220, 600)]:
        number = value.setdefault(key, default)
        if type(number) is not int or not 1 <= number <= high:
            raise ValueError(f'Abyss.{key}必须为1到{high}的整数')
    elements = value.setdefault('elements', list(AREAS))
    if not isinstance(elements, list) or not elements or any(e not in AREAS for e in elements) or len(set(elements)) != len(elements):
        raise ValueError('Abyss.elements必须为不重复的fire/water/wind/light/dark列表')
    for key, default in [('allow_local_trials', False), ('audit_only', False), ('discover_sources', True),
                         ('prepare_only', False),
                         ('allow_five_star_upgrade',False),('allow_divine_amulets',False)]:
        if type(value.setdefault(key, default)) is not bool:
            raise ValueError(f'Abyss.{key}必须为布尔值')
    return value


@register('abyss_push')
class AbyssPush(BaseTask):
    config_section = 'Abyss'

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        if args or kwargs:
            raise ValueError('abyss_push使用Abyss配置')
        options = validate_options(config.get(cls.config_section, {}))
        if options['prepare_only']:
            return (), {}, acquire_strategies(task_source_options('abyss', options))
        return (), {}, None

    def __init__(self, robot, options: dict | None = None) -> None:
        super().__init__(robot)
        self.options = validate_options(self.task_options() if options is None else options)
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/abyss'))
        self.formation = AbyssFormation(self.ui)
        self.combat = EventCombat(self)
        self.deadline = time.monotonic()+self.options['timeout']
        self.formation.check_deadline=self.check_deadline
        self.formation.recover_equipment=self.recover_equipment
        self.report: TaskReport = dict(status='running', battles=[], areas={}, pending=[], source_searches=[])
        self.total_battles = 0
        self.history = AbyssHistory(self.options.get('history_dir','cache/game/strategies/abyss_history'),
                                    self.options.get('account_key','default'))
        self.unreleased_path=self.history.path.with_name(self.history.path.stem+'-unreleased.json')
        self.formation.unreleased=recent_unreleased(self.unreleased_path,time.time(),
                                                     self.formation.unreleased_proof_seconds)
        self._battle_samples = []
        self._next_sample = 0
        self.source_parties=[]

    def recover_equipment(self,stage,names):
        self.enter(stage.element)
        known=getattr(self.formation,'unreleased',{})
        # Refresh the other recently verified unreleased slots in the same
        # visit. Otherwise they can expire while the five-member selection is
        # rebuilt, creating a loop of one newly stale member per visit.
        together=list(dict.fromkeys(list(names)+list(known)))
        for name in together:
            proof=inspect_unreleased_equipment(self.ui,name)
            if proof:
                if not hasattr(self.formation,'unreleased'):self.formation.unreleased={}
                self.formation.unreleased[name]=(time.time(),proof)
                self.unreleased_path.parent.mkdir(parents=True,exist_ok=True)
                atomic_json(self.unreleased_path,dict(version=1,proofs={name:dict(time=stamp,evidence=evidence)
                    for name,(stamp,evidence) in self.formation.unreleased.items()}))
        screen=self.enter(stage.element);_,detail=self.open_stage(screen)
        self.ui.click(detail.find('挑战',(750,420,940,490),exact=True))
        self.wait_formation('专武核验后编队')

    def wait_formation(self, description):
        def known_blocker(screen):
            if not (screen.find('体力不足',(400,220,550,275))
                    and screen.find('要回复吗',(400,255,550,310))):
                return
            self.ui.save('abyss_stamina_insufficient',screen)
            cancel=screen.find('取消',(260,335,480,410),exact=True)
            if cancel:
                self.ui.click(cancel)
                raise EventUIError('体力不足，已取消回复体力；保留剩余挑战次数')
            raise EventUIError('体力不足且取消按钮未知，未确认回复体力')
        return self.ui.wait(lambda s:s.find('队伍编组',(300,0,650,70),exact=True),
                            description,handle=known_blocker)

    def observe_battle(self, screen):
        if time.monotonic()<self._next_sample:return
        sample=combat_sample(screen,self.combat.portraits)
        if sample is None:return
        self._next_sample=time.monotonic()+2
        sample['evidence']=str(self.ui.save(f'{self._battle_evidence_id}_sample_{len(self._battle_samples)}',screen))
        self._battle_samples.append(sample)

    def upgrade_trial(self,stage,party,audit):
        if not self.options['allow_five_star_upgrade'] or self.options['audit_only']:
            return party,audit
        names=[a['name'] for a in audit.get('observed',[]) if a.get('stars') and a['stars']<5]
        if not names:return party,audit
        self.enter(stage.element)
        for name in names:
            upgrade={};self.report.setdefault('star_upgrades',[]).append(upgrade)
            self.log('拟上场角色升至5星：'+name)
            upgrade_to_five(self.ui,name,upgrade,self.save_report,allow_amulets=self.options['allow_divine_amulets'])
            self.formation.observed.pop(name,None)
        screen=self.enter(stage.element);_,detail=self.open_stage(screen)
        self.ui.click(detail.find('挑战',(750,420,940,490),exact=True))
        self.wait_formation('升星后返回编队')
        ready,selection=self.formation.select(party)
        if not ready:return None,dict(unready=['升星后编队未恢复'],selection=selection)
        new_party,new_audit=self.formation.current_trial(stage)
        if new_party:
            settings={m.name:m.instant for m in party.members}
            for member in new_party.members:member.instant=settings[member.name]
        for key in ('source','adjustment','set_adjustment'):
            if key in audit:new_audit[key]=audit[key]
        return new_party,new_audit

    def equip_special(self, order):
        return (inspect_special_equipment(self.ui,order) if self.options['audit_only']
                else auto_equip_special(self.ui,order))

    def log(self, message: str) -> None:
        print('[深域] '+message, flush=True)

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline and not getattr(self, '_in_combat', False):
            raise EventUIError('深域任务时间上限，停止后续挑战')

    def save_report(self) -> None:
        (self.ui.output/'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    def story_dialog(self, screen: EventScreen) -> bool:
        # Unknown popups are not dismissed by a generic Confirm click.
        return False

    def combat_pre_dialog(self, screen: EventScreen) -> bool:
        if screen.find('限定商店', (300, 0, 660, 75), exact=True):
            cancel = screen.find('取消', (470, 435, 705, 510), exact=True)
            if cancel:
                self.ui.save('limited_shop_cancel', screen)
                self.ui.click(cancel)
                return True
        return False

    def combat_result_button(self, screen: EventScreen):
        if screen.find('战斗失败|挑战失败'):
            return screen.find('前往深域关卡', (650, 420, 950, 530), exact=True)
        if screen.find('WIN|获得道具|战斗失败|挑战失败'):
            return screen.find('下一步', (740, 450, 940, 525), exact=True)
        return None

    def combat_return(self, screen: EventScreen) -> bool:
        return map_element(screen) is not None or self.read_detail(screen) is not None

    def read_detail(self, screen: EventScreen) -> AbyssStage | None:
        stage = detail_stage(screen)
        if (stage is None and screen.find('推荐公主骑士品级', (630, 20, 860, 75))
                and screen.find('取消', (570, 425, 750, 490), exact=True)
                and screen.find('挑战', (750, 420, 940, 490), exact=True)):
            # Observed 3-6: full-frame OCR drops the final digit. Re-read only
            # the title, preserving all other observations and exact matching.
            local = self.ui.read_region(screen, (50, 27, 265, 70))
            stage = detail_stage(local)
            if stage:
                screen.items.extend(local.items)
        return stage

    def enter(self, element: str) -> EventScreen:
        for _ in range(35):
            self.check_deadline()
            screen = self.ui.capture()
            if self.combat_pre_dialog(screen):
                continue
            result_button = self.combat_result_button(screen)
            if result_button:
                self.ui.click(result_button)
                continue
            current = map_element(screen)
            if current == element:
                # Wait for NEXT and stage labels to settle after the map pans.
                previous = None
                stable = 0
                misses = 0
                def settled(s):
                    nonlocal previous, stable, misses
                    target = next_stage(s)
                    key = (target[0], tuple(target[1].center)) if target else None
                    if key is None:
                        misses += 1
                        if misses >= 3:
                            previous = None
                            stable = 0
                        return False
                    misses = 0
                    close = (key is not None and previous is not None and key[0] == previous[0]
                             and max(abs(a-b) for a, b in zip(key[1], previous[1])) <= 3)
                    stable = stable+1 if close else 0
                    previous = key
                    return stable >= 2
                return self.ui.wait(settled, '深域NEXT稳定', timeout=25)
            if current:
                self.ui.expect_click(AREAS[element][1], (280, 60, 900, 110), exact=True)
            elif self.read_detail(screen):
                self.ui.expect_click('取消', (570, 425, 750, 490), exact=True)
            elif screen.find('队伍编组', (300, 0, 650, 70), exact=True):
                self.ui.expect_click('取消', (630, 420, 785, 490), exact=True)
            elif screen.find('深域关卡', (45, 0, 210, 55), exact=True):
                button = screen.find(AREAS[element][0], (0, 120, 950, 450), exact=True)
                if button:
                    self.ui.click(button)
                else:
                    time.sleep(.5)
            elif screen.find('冒险', (45, 0, 220, 65), exact=True):
                button = screen.find('深域关卡', (660, 210, 810, 350), exact=True)
                if button:
                    self.ui.click(button)
                else:
                    time.sleep(.5)
            elif screen.find('我的主页|主菜单', (0, 480, 960, 540)):
                self.ui.click((532, 515))
            else:
                time.sleep(.5)
        raise EventUIError('无法从已知页面进入深域，未猜测未知弹窗')

    def open_stage(self, screen: EventScreen) -> tuple[AbyssStage, EventScreen]:
        target = next_stage(screen)
        if not target:
            raise EventUIError('没有明确NEXT目标，不能当作全部通关')
        stage, label = target
        if self.read_remaining(screen) is None:
            raise EventUIError('未确认剩余挑战次数')
        self.ui.click(label)
        detail = self.ui.wait(lambda s: self.read_detail(s) == stage, '深域目标详情')
        if self.read_remaining(detail, detail=True) is None:
            raise EventUIError('详情剩余挑战次数未知')
        return stage, detail

    def read_remaining(self,screen,*,detail=False):
        value=remaining(screen,detail=detail)
        if value is None:
            roi=(490,432,575,478) if detail else (640,425,710,465)
            local=self.ui.read_region(screen,roi)
            value=remaining(local,detail=detail)
            if value is not None:screen.items.extend(local.items)
        if value is None and not detail:
            import cv2 as cv
            import re
            from ..game_ui.screen import TextBox,normalized
            patch=cv.resize(screen.image[420:470,620:730],None,fx=4,fy=4)
            result=self.ui._ocr(patch,use_det=False,use_cls=True,use_rec=True)
            if result.txts and result.scores[0]>=.9 and re.fullmatch(r'\d+/10',normalized(result.txts[0])):
                candidate=int(normalized(result.txts[0]).split('/')[0])
                if 0<=candidate<=10:
                    value=candidate
                    screen.items.append(TextBox(result.txts[0],float(result.scores[0]),[[640,425],[710,425],[710,465],[640,465]]))
        return value

    def search(self, stage: AbyssStage) -> None:
        if not self.options['discover_sources']:
            return
        if source_for_stage(self.source_parties, stage, set(), []):
            return
        self.log('自动获取并解析攻略：'+stage.title)
        report = acquire_strategies(task_source_options('abyss', self.options, stage=stage),
                                    check=self.check_deadline)
        self.report['source_searches'].append(report)
        self.source_parties.extend(abyss_candidate(p) for p in report['parties'])
        # The same public references can identify current game cards without an
        # Agent-built account index. Observed account labels remain in memory.
        if report.get('avatar_assets'):
            from ..game_ui.avatar_assets import ensure_avatar_index
            self.formation.avatars, _ = ensure_avatar_index(self.options.get('sources', {}).get('avatars'))
        self.save_report()

    def push_area(self, element: str) -> None:
        record = self.report['areas'][element] = dict(cleared=[], failures={}, status='running')
        searched = set()
        while self.total_battles < self.options['max_battles']:
            self.check_deadline()
            screen = self.enter(element)
            count = self.read_remaining(screen)
            if count == 0:
                record.update(status='stopped', reason='剩余挑战次数为零')
                return
            stage, detail = self.open_stage(screen)
            record['next'] = stage.key
            record.setdefault('initial', stage.key)
            budget=self.history.budget(stage,self.options['max_failures_per_stage'],self.options['max_repeat_failures_per_stage'])
            record.setdefault('budgets',{})[stage.key]=budget
            if record['failures'].get(stage.key,0)>=budget:
                record.update(status='stopped',reason='本关失败预算用完，继续其他属性')
                return
            if stage.key not in searched:
                self.search(stage)
                searched.add(stage.key)
            if not self.options['allow_local_trials'] and not source_for_stage(self.source_parties, stage, set(), []):
                record.update(status='blocked', reason='已解析来源尚无完整且适用的作业；详见source_searches逐字段证据与pending')
                return
            if self.read_remaining(detail, detail=True) == 0:
                record.update(status='stopped', reason='详情剩余挑战次数为零')
                return
            challenge = detail.find('挑战', (750, 420, 940, 490), exact=True)
            if not detail.blue_button(challenge):
                record.update(status='stopped', reason='挑战按钮不可用')
                return
            self.ui.click(challenge)
            self.wait_formation('深域编队')
            failed=self.history.failed_teams(stage)
            previous=self.history.trials(stage)
            source=source_for_stage(self.source_parties,stage,failed,previous)
            # A failed guide team is still useful as a verified starting point
            # for choosing a different member. Re-entering an attribute may
            # otherwise use the previous attribute's saved five as a trial.
            if source:
                self.log('优先核验用户攻略阵容：'+stage.title)
                party,audit=self.formation.source_trial(stage,source)
                if party is None:
                    unready=list(audit.get('unready',[]))+list(audit.get('selection',{}).get('unready',[]))
                    unresolved=[f['character'] for f in unready if isinstance(f,dict) and f.get('character')
                                and any('专武' in reason for reason in f.get('reasons',[]))]
                    if unresolved:
                        self.recover_equipment(stage,unresolved)
                        party,audit=self.formation.source_trial(stage,source,recover=False)
            else:
                self.log('检查保存的属性队：'+stage.title)
                party, audit = self.formation.current_trial(stage)
                if party is None:
                    unresolved=[f['character'] for f in audit.get('unready',[]) if isinstance(f,dict) and f.get('character')
                                and any('专武' in reason for reason in f.get('reasons',[]))]
                    if unresolved:
                        self.recover_equipment(stage,unresolved)
                        party,audit=self.formation.current_trial(stage)
            retry=previous[-1].get('retry',{}) if previous else {}
            same=team_key(audit.get('order',[]))
            same_attempts=sum(team_key(t['order'])==same for t in previous)
            retry_same=(retry.get('action')=='retry_once' and same_attempts<2)
            retry_equipped=equipment_retrial(audit.get('order',[]),previous)
            strict_source = bool(source and source.get('document'))
            alternative=source_set_alternative(source,previous) if source and not strict_source and retry.get('action')=='change_damage' else None
            if party is not None and same in failed and alternative:
                settings=dict(zip(source['names'],[c=='O' for c in alternative]))
                for member in party.members:member.instant=settings[member.name]
                audit['set_adjustment']=dict(flags=alternative,source=source['source'],reason='来源明确建议伤害不足时调整SET')
                self.log('按来源伤害不足备注调整SET：'+alternative)
            elif party is not None and same in failed and not retry_same and not retry_equipped:
                if strict_source:
                    record.update(status='stopped', reason='来源阵容失败；保留证据，未擅自替换来源培养/成员')
                    return
                self.log('失败阵容不原样重试，选择同属性替代成员：'+stage.title)
                focus=repeated_casualty(previous) if retry.get('action')=='change_survival' else None
                party,audit=self.formation.alternative_trial(stage,audit,failed,
                                   survival=retry.get('action')=='change_survival',focus=focus)
            elif party is not None and same in failed and retry_equipped:
                audit['retrial_reason']='此前失败时未执行特别装备自动装备；本次补齐后仅重试一次'
            record['last_audit'] = audit
            self.save_report()
            if party is None:
                record.update(status='blocked', reason='保存队伍的身份或培养状态未确认，见last_audit')
                return
            if not strict_source:
                party,audit=self.upgrade_trial(stage,party,audit)
            record['last_audit']=audit
            if party is None:
                record.update(status='blocked',reason='升星后队伍未核验，未开战');return
            special=self.equip_special(audit['order'])
            audit['special_equipment']=special
            record['last_audit']=audit
            self.save_report()
            if self.options['audit_only']:
                record.update(status='audited', reason='已检查，未开战')
                return
            self.check_deadline()
            self.total_battles += 1
            self._battle_evidence_id = f'abyss_{element}_{stage.key}_{self.total_battles}'
            battle = dict(stage=asdict(stage), attempt=self.total_battles, formation=audit,
                          outcome='in_flight', before_remaining=count, started_at=time.time())
            self.report['battles'].append(battle)
            trial=self.history.start(stage,audit,self.ui.output/'report.json')
            battle['history_id']=trial['id']
            self._battle_samples=[];self._next_sample=0
            self.save_report()
            self.log(f'本地试打 {stage.title}，本关已失败{record["failures"].get(stage.key, 0)}次')
            # Combat owns its timeout and retreats via its battle menu. Do not
            # throw the task deadline through that cleanup path mid-battle.
            configured_timeout = self.options['battle_timeout']
            self.options['battle_timeout'] = min(configured_timeout, max(1, self.deadline-time.monotonic()))
            self._in_combat = True
            try:
                result = self.combat.run(party, audit['order'])
            finally:
                self._in_combat = False
                self.options['battle_timeout'] = configured_timeout
            battle.update(outcome=result.outcome, reason=result.reason)
            battle['samples']=self._battle_samples
            battle['retry']=retry_decision(self._battle_samples,result.reason,
                       sum(team_key(t['order'])==team_key(audit['order']) for t in self.history.trials(stage)))
            self.save_report()
            # A victory animation is not a progress receipt.
            after = self.enter(element)
            target = next_stage(after)
            if target is None:
                raise EventUIError('战后NEXT未知，未确认通关，停止')
            following = target[0]
            battle.update(after_stage=asdict(following), after_remaining=remaining(after),
                          evidence=str(self.ui.save('after_'+self._battle_evidence_id, after)))
            if advanced(stage, following):
                record['cleared'].append(stage.key)
                battle['progressed'] = True
                battle.pop('retry',None)
                record['next']=following.key
            elif following == stage:
                battle['progressed'] = False
                record['failures'][stage.key] = record['failures'].get(stage.key, 0)+1
                if result.outcome == 'blocked' or record['failures'][stage.key] >= budget:
                    record.update(status='stopped', reason=result.reason if result.outcome == 'blocked' else '本关失败达到上限，继续其他属性')
                    self.history.finish(trial,battle)
                    return
            else:
                raise EventUIError('战后关卡回退或属性变化，停止')
            self.history.finish(trial,battle)
            self.save_report()
        record.update(status='stopped', reason='全局战斗次数达到上限')

    def run(self) -> TaskReport:
        try:
            for element in self.options['elements']:
                if self.total_battles >= self.options['max_battles']:
                    self.report['pending'].append('全局战斗上限，剩余属性未执行')
                    break
                self.push_area(element)
                self.save_report()
            self.report['status'] = 'partial' if any(a['status'] != 'audited' for a in self.report['areas'].values()) else 'audited'
            # Leave a verified map, never a battle or a purchase confirmation.
            if self.report['areas']:
                self.enter(next(reversed(self.report['areas'])))
        except EventUIError as error:
            self.report['status'] = 'blocked'
            self.report['pending'].append(str(error))
            for record in self.report['areas'].values():
                if record['status'] == 'running':
                    record.update(status='blocked', reason=str(error))
            self.ui.save('stopped')
        finally:
            self.save_report()
        return self.report
