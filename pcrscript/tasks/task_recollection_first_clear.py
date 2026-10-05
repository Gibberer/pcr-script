"""Bounded first clears using exact-floor sources and audited five-person teams."""
from __future__ import annotations

from uuid import uuid4

from .registry import register
from .recollection_flow import RecollectionTask, RecollectionBlocked
from .recollection_strategy import RecollectionFormation, parties_for_floor
from .event_battle import EventCombat
from .abyss_retry import combat_sample
from .recollection_retry import trial_context, same_trial, same_roster, remember_failure
from ..game_ui import recollection as field
from ..game_ui.screen import EventUIError, normalized
from ..run_session import RunCancelled, ResumeUnsafe, clock as time


@register('recollection_first_clear', requires_home=False)
class RecollectionFirstClear(RecollectionTask):
    config_section = 'RecollectionFirstClear'
    first_clear = True

    def __init__(self, robot):
        super().__init__(robot)
        self.formation = RecollectionFormation(self.ui)
        self.combat = EventCombat(self)
        self.pools = {}
        self.inspected_sources = {}
        self._next_sample = 0
        self.report.update(battles=0, areas={})

    def story_dialog(self, screen):
        # Only the shared, recognized in-battle story skip controls.
        from .task_story_event import CampaignClean
        return CampaignClean.story_dialog(self, screen)

    def combat_return(self, screen):
        return bool(field.detail_scope(screen) or field.home(screen) or field.dominion_index(screen))

    def observe_battle(self, screen):
        record = self.state.get('pending_battle')
        if not record:
            return
        marker = (screen.find('菜单', (840, 0, 960, 60), exact=True)
                  or screen.find(r'\d:\d{2}', (750, 0, 850, 55), exact=True)
                  or (screen.find('进行中战斗') and screen.find('主菜单')))
        if marker and marker.score >= .95 and not record.get('battle_started'):
            record['battle_started'] = str(self.ui.save('battle_started', screen))
            self.save()
        if time.monotonic() < self._next_sample:
            return
        samples = record.setdefault('samples', [])
        if len(samples) >= 120:
            return
        sample = combat_sample(screen, self.combat.portraits,
                               maximum_hp=record.get('maximum_hp'))
        if sample is None:
            return
        self._next_sample = time.monotonic()+2
        sample['evidence'] = str(self.ui.save(f'battle_sample_{len(samples):03d}', screen))
        samples.append(sample)
        # Observations survive interruption but never authorize a retry.
        # The completed stamp and actual attempts still settle the battle.
        self.save()

    def combat_settings_confirmed(self, evidence):
        if record := self.state.get('pending_battle'):
            record.update(settings_verified=True, settings_evidence=evidence)
            self.save()

    def combat_starting(self, screen):
        record = self.state.get('pending_battle')
        if not record or record.get('submission_tracked') is not True or record.get('submitted') is not False:
            raise RecollectionBlocked('首通开战提交阶段未知，未重复开战')
        record.update(submitted=True, dispatch_evidence=str(self.ui.save('battle_dispatch', screen)))
        self.save()

    @staticmethod
    def unstarted_battle(record):
        return (record.get('submission_tracked') is True and type(record.get('submitted')) is bool
                and not any(record.get(key) for key in ('battle_started', 'samples', 'settings_verified',
                    'settings_evidence', 'result_outcome', 'result_evidence', 'outcome')))

    def leave_formation(self, screen):
        record = self.state.get('pending_battle')
        if record and self.unstarted_battle(record):
            # A requested start may never reach the device. Prove the original
            # battle is still unstarted before leaving this formation; save the
            # proof before cancellation so an interrupted cancel can resume.
            for step in range(3):
                if step:
                    time.sleep(1)
                    screen = self.capture()
                title = screen.find('队伍编组', (250, 0, 710, 80), exact=True)
                start = screen.find('战斗开始', (740, 390, 950, 510), exact=True)
                cancel = screen.find('取消', (630, 410, 780, 500), exact=True)
                if (not title or title.score < .95 or not start or start.score < .95
                        or not screen.blue_button(start) or not cancel or cancel.score < .95
                        or screen.find('正在进行数据连接|连接中|加载|进行中战斗|主菜单|战斗失败|WIN')
                        or screen.find(r'菜单|\d:\d{2}', (750, 0, 960, 60))):
                    raise RecollectionBlocked('首通恢复编队状态不稳定，保留待核对战斗')
            record['unsubmitted_formation'] = str(self.ui.save('battle_unsubmitted_formation', screen))
            self.save()
        super().leave_formation(screen)

    def combat_result_button(self, screen):
        button = field.battle_result_button(screen)
        if button and (record := self.state.get('pending_battle')):
            if outcome := field.battle_outcome(screen):
                record.update(result_outcome=outcome,
                              result_evidence=str(self.ui.save('battle_result', screen)))
                self.save()
        return button

    def settle_battle_result(self, screen):
        if not self.state.get('pending_battle'):
            raise RecollectionBlocked('结算页缺少对应首通记录，保留现场并停止')
        self.ui.click(self.combat_result_button(screen))

    def select_party(self, area, floor, party):
        ready, details = self.formation.select(party)
        if ready:
            return ready, details
        if any('未在搜索结果中确认该版本的角色' in reason
               for row in details.get('unready', []) for reason in row.get('reasons', [])):
            # An equipment trip cannot supply a missing party member. Keep
            # the audit and move to the next source instead of reselecting it.
            return ready, details
        unknown = [m.name for m in party.members
                   if (actual := self.formation.observed.get(normalized(m.name)))
                   and actual.identity_verified and actual.unique is None and actual.unique2 is None]
        from .party_preparation import numeric_equipment_unknown, read_numeric_equipment
        numeric = [name for name in numeric_equipment_unknown(party, self.formation.observed)
                   if (actual := self.formation.observed.get(normalized(name)))
                   and actual.identity_verified]
        if not unknown and not numeric:
            return ready, details
        from ..game_ui.character_equipment import inspect_unreleased_equipment
        from .task_home import ToHomePage
        s = self.capture()
        self.click(s, '取消', (630, 410, 780, 500))
        ToHomePage(self.robot).run(timeout=60)
        self.report_progress('追忆战首通 · 人物页核验专武')
        for name in unknown:
            self.check_deadline()
            proof = inspect_unreleased_equipment(self.ui, name)
            if proof:
                self.formation.unreleased[normalized(name)] = (time.time(), proof)
            ToHomePage(self.robot).run(timeout=60)
        for name in numeric:
            self.check_deadline()
            read_numeric_equipment(self.formation, name)
            ToHomePage(self.robot).run(timeout=60)
        s = self.select_floor(area, floor)
        if s is None or field.clear_status(s) is not False:
            raise RecollectionBlocked('专武核验后首通目标发生变化，未开战')
        self.click(s, '挑战', (700, 300 if area == field.AREAS['memory'] else 390, 950, 470))
        self.wait(lambda s: s.find('队伍编组', (250, 0, 710, 80), exact=True), '专武核验后重新编队')
        # Leaving an unstarted formation can restore an older saved party.
        # Only a new full selection may authorize the subsequent battle.
        # Even an equipped character can have an unreadable rotating badge.
        # Refresh every selected member after returning; absence of an
        # unreleased-equipment proof cannot authorize or skip this audit.
        return self.formation.select(party)

    def source_parties(self, area, floor, *, advance=False):
        key = (area, floor)
        if key not in self.pools or advance:
            from .strategy_video import acquire_strategies, task_source_options
            self.report_progress(f'获取追忆战攻略 · {area}{floor}层')
            options = task_source_options('recollection', self.options, area=area, stage=floor)
            # Only an explicitly authorized account trial may use a guide
            # starting in combat. Bind it to the freshly read live boss.
            if self.options['allow_local_trials']:
                s = self.capture()
                signature = field.boss_signature(s)
                if signature and signature['scope'] == dict(area=area, floor=floor):
                    signature['image'] = str(self.ui.save('source_target', s))
                    options['observed_target'] = signature
            source = acquire_strategies(options, check=self.check_deadline,
                exclude_sources=self.inspected_sources.get(key, set()),
                accept=lambda report: bool(parties_for_floor(report, area, floor,
                    allow_local_trials=self.options['allow_local_trials'])))
            self.inspected_sources.setdefault(key, set()).update(source.get('inspected_sources', []))
            self.report.setdefault('sources', []).append(dict(area=area, floor=floor, report=source))
            self.save()
            self.pools[key] = parties_for_floor(source, area, floor,
                                                allow_local_trials=self.options['allow_local_trials'])
            if self.pools[key]:
                from ..game_ui.avatar_assets import ensure_avatar_index
                self.formation.avatars, _ = ensure_avatar_index(self.options['sources'].get('avatars'), check=self.check_deadline)
        return self.pools[key]

    def reconcile_battle(self):
        record = self.state['pending_battle']
        s = self.select_floor(record['area'], record['floor'])
        clear = field.clear_status(s) if s is not None else None
        if (clear is False and self.unstarted_battle(record)
                and (record['submitted'] is False or record.get('unsubmitted_formation'))):
            target = record.get('target')
            scope = dict(area=record['area'], floor=record['floor'])
            if (not isinstance(target, dict) or target.get('scope') != scope
                    or record['area'] != field.AREAS['memory']
                    and type(record.get('attempts_before')) is not int):
                raise RecollectionBlocked('未提交首通的原目标或次数证据不完整，保留记录')
            for step in range(3):
                if step:
                    time.sleep(1)
                    s = self.capture()
                stamp = s.find('初次通关', (110, 300, 360, 420), exact=True)
                if (field.detail_scope(s) != scope or field.clear_status(s) is not False
                        or not stamp or stamp.score < .95 or field.boss_signature(s) != target
                        or field.detail_attempts(s) != record.get('attempts_before')
                        or s.find('正在进行数据连接|连接中|加载|确认|取消|关闭')):
                    raise RecollectionBlocked('未提交首通的层数、首领或次数不稳定，保留记录')
            record.update(outcome='cancelled_unsubmitted_battle', progressed=False,
                          attempts_after=field.detail_attempts(s),
                          after=str(self.ui.save('battle_unsubmitted_detail', s)))
            self.report['history'].append(record)
            self.state.pop('pending_battle')
            self.save()
            return
        if clear is None or (not clear and record.get('result_outcome') != 'failed'):
            raise RecollectionBlocked('上次首通战斗尚未确认结果，保留进度并停止自动重试')
        remaining = field.detail_attempts(s)
        if (record['area'] != field.AREAS['memory']
                and remaining != record['attempts_before']-int(clear)):
            raise RecollectionBlocked('上次首通的挑战次数变化尚未核对，未追加挑战')
        outcome = 'recovered_clear' if clear else 'recovered_failed'
        record.update(outcome=outcome, progressed=clear, attempts_after=remaining,
                      after=str(self.ui.save(outcome, s)))
        self.report['history'].append(record)
        remember_failure(self.state, record)
        self.state.pop('pending_battle')
        self.save()

    def battle(self, area, floor, party):
        output = self.ui.output
        self.ui.output = output/('battle_'+uuid4().hex[:12])
        self.ui.output.mkdir(parents=True, exist_ok=True)
        try:
            return self._battle(area, floor, party)
        finally:
            self.ui.output = output

    def _battle(self, area, floor, party):
        s = self.select_floor(area, floor)
        if s is None or field.clear_status(s) is not False:
            raise RecollectionBlocked('开战前不能证明目标层尚未通关')
        remaining = field.detail_attempts(s)
        signature = field.boss_signature(s)
        if area != field.AREAS['memory'] and (remaining is None or remaining <= 0):
            raise RecollectionBlocked('追忆战·霸剩余次数不足或未知')
        self.click(s, '挑战', (700, 300 if area == field.AREAS['memory'] else 390, 950, 470))
        self.wait(lambda s: s.find('队伍编组', (250, 0, 710, 80), exact=True), '追忆战编队')
        self.report_progress(f'核验首通编队 · {area}{floor}层')
        ready, details = self.select_party(area, floor, party)
        self.report.setdefault('audits', []).append(dict(area=area, floor=floor, party=party.name,
                                                        source=party.source, ready=ready, formation=details))
        self.save()
        if not ready:
            return dict(outcome='blocked', progressed=False, reason='编队身份、培养或装备未通过核验')
        from ..game_ui.special_equipment import inspect_special_equipment, auto_equip_special
        special = inspect_special_equipment(self.ui, details['order'])
        details['special_equipment'] = special
        self.save()
        if special.get('unknown'):
            raise RecollectionBlocked('特别装备槽位状态未知，未开战')
        if self.options['auto_equip']:
            details['special_equipment_before'] = special
            self.report_progress('追忆战首通 · 分配现有特别装备')
            priorities = self.options['auto_equip_priorities']
            special = (auto_equip_special(self.ui, details['order'], priorities=priorities)
                       if priorities else auto_equip_special(self.ui, details['order']))
            details['special_equipment'] = special
            self.save()
            if special.get('unknown'):
                raise RecollectionBlocked('特别装备分配后的槽位状态未知，未开战')
        context = trial_context(signature, party, details,
                                self.capture().number((505,375,590,402)),
                                mastery=self.report.get('mastery_preparation', {}).get('nodes') or None)
        prior = [row.get('context') for row in self.state.get('failed_trials', [])
                 if same_roster(row.get('context'), dict(area=area,floor=floor), details['order'])]
        if prior and not self.options['retry_failed_parties']:
            if context is None:
                return dict(outcome='blocked', progressed=False,
                            reason='失败队伍的当前目标、培养、战力或装备复核不完整，未追加试打')
            if any(same_trial(old, context) for old in prior):
                return dict(outcome='blocked', progressed=False,
                            reason='已核验的失败队伍、培养、特别装备与设置未变化，未重复开战')
        current = self.formation.inspect_current(full=False, expected_names=[m.name for m in party.members], verify_skills=False)
        if (len(current) != 5 or [normalized(m.name) for m in current] != details.get('order')
                or not all(m.identity_verified for m in current)):
            raise RecollectionBlocked('即将开战的五人顺序与核验编队不一致')
        record = dict(area=area, floor=floor, party=party.name, source=party.source,
                      maximum_hp=signature.get('maximum_hp') if signature else None,
                      build_basis=party.build_basis, formation=details, attempts_before=remaining,
                      trial_context=context, target=signature, submitted=False, submission_tracked=True,
                      before=str(self.ui.save(f'battle_before_{len(self.report["history"])}', self.capture())))
        self.state['pending_battle'] = record
        self._next_sample = 0
        self.report['battles'] += 1
        self.save()
        self.report_progress(f'追忆战首通战斗 · {area}{floor}层', self.report['battles'], self.options['max_battles'])
        result = self.combat.run(party, details['order'])
        s = self.select_floor(area, floor)
        clear = field.clear_status(s) if s is not None else None
        after = field.detail_attempts(s) if s is not None else None
        record.update(outcome=result.outcome, reason=result.reason, progressed=clear is True,
                      attempts_after=after, after=str(self.ui.save(f'battle_after_{len(self.report["history"])}', s)) if s is not None else '')
        self.save()
        if clear is None:
            raise RecollectionBlocked('战后首通标记未知，保留待核对战斗，不重放')
        if area != field.AREAS['memory'] and after != remaining-int(clear):
            raise RecollectionBlocked('战后挑战次数与首通结果不一致，未追加挑战')
        self.state.pop('pending_battle')
        remember_failure(self.state, record)
        self.report['history'].append(record)
        self.save()
        return record

    def advance_area(self, area):
        last_floor = None
        while self.report['battles'] < self.options['max_battles']:
            self.check_deadline()
            self.report_progress('核对追忆战首通进度 · '+area)
            s = self.select_floor(area)
            if s is None:
                self.report['areas'][area] = dict(status='locked')
                self.report['pending'].append(area+'未解锁')
                return
            scope = field.detail_scope(s)
            floor = scope['floor']
            clear = field.clear_status(s)
            if clear is True:
                self.report['areas'][area] = dict(status='complete', highest_floor=floor,
                                                 evidence=str(self.ui.save('area_complete', s)))
                return
            if clear is None or last_floor == floor:
                raise RecollectionBlocked('首通目标或进展不能确认：'+area)
            if area != field.AREAS['memory'] and field.detail_attempts(s) == 0:
                self.report['areas'][area] = dict(status='attempts_exhausted', next_floor=floor)
                self.report['pending'].append(area+'本周次数已用完，保留首通进度')
                return
            attempted = {row['party'] for row in self.report['history']
                         if row['area'] == area and row['floor'] == floor and not row['progressed']
                         and row.get('outcome') != 'cancelled_unsubmitted_battle'}
            progressed = False
            blocked = []
            any_candidates = False
            battles_before = self.report['battles']
            for batch in range(self.options['max_source_batches']):
                # A source fetch must start on the exact live detail, even
                # when a previous candidate left the task in formation.
                if batch:
                    self.select_floor(area, floor)
                prior_sources = set(self.inspected_sources.get((area, floor), set()))
                parties = self.source_parties(area, floor, advance=batch > 0)
                any_candidates |= bool(parties)
                fresh = [p for p in parties if p.name not in attempted]
                for party in fresh:
                    if (self.report['battles'] >= self.options['max_battles']
                            or self.report['battles']-battles_before >= self.options['max_attempts_per_stage']):
                        break
                    attempted.add(party.name)
                    result = self.battle(area, floor, party)
                    if result['progressed']:
                        progressed = True
                        break
                    if result['outcome'] == 'blocked':
                        audit = self.report['audits'][-1]['formation']
                        blocked.extend(row['character']+'：'+', '.join(row['reasons'])
                                       for row in audit.get('unready', []))
                        if not audit.get('unready'):
                            blocked.append(result['reason'])
                    if self.state.get('pending_battle'):
                        raise RecollectionBlocked('战斗结果尚未结算，未重试')
                if (progressed or self.report['battles'] >= self.options['max_battles']
                        or self.report['battles']-battles_before >= self.options['max_attempts_per_stage']
                        or not fresh and prior_sources == self.inspected_sources.get((area, floor), set())):
                    break
            if not progressed:
                self.report['areas'][area] = dict(status='blocked' if blocked or not any_candidates else 'partial', next_floor=floor)
                reason = ('; '.join(dict.fromkeys(blocked)) if blocked else
                          '达到本关候选或尝试上限' if any_candidates else
                          '没有范围、五人和战斗设置均明确的可核验队伍')
                self.report['pending'].append(f'{area}{floor}层未通关：'+reason)
                return
            last_floor = floor
        self.report['pending'].append('达到本次首通战斗次数上限')

    def run(self):
        try:
            if self.state.get('pending_sweep'):
                raise RecollectionBlocked('日常扫荡尚未核对，请先运行追忆战场日常复核消费')
            prepared = False
            if self.state.get('pending_mastery'):
                if self.state.get('pending_battle'):
                    raise RecollectionBlocked('同时存在未核对战斗与精通消费，保留记录')
                from .role_mastery_preparation import prepare_role_mastery
                prepare_role_mastery(self,self.options['mastery_preparation'])
                prepared = True
                if self.report['pending']:
                    raise RecollectionBlocked('精通准备未达到指定目标，未开战')
            if self.enter() is None:
                self.report['status'] = 'unavailable'
                return self.finish()
            if self.state.get('pending_battle'):
                self.reconcile_battle()
            if not prepared and self.options['mastery_preparation']['roles']:
                from .role_mastery_preparation import prepare_role_mastery
                prepare_role_mastery(self,self.options['mastery_preparation'])
                if self.report['pending']:
                    raise RecollectionBlocked('精通准备未达到指定目标，未开战')
                if self.enter() is None:
                    raise RecollectionBlocked('精通准备后追忆入口无法核对，未开战')
            for key in self.options['areas']:
                self.advance_area(field.AREAS[key])
                self.save()
                if self.report['battles'] >= self.options['max_battles']:
                    break
            self.report['status'] = ('partial' if self.report['pending'] and self.report['history'] else
                                     'blocked' if self.report['pending'] else
                                     'complete' if self.report['history'] else 'already_complete')
            return self.finish()
        except (RunCancelled, ResumeUnsafe) as error:
            self.report['status'] = 'cancelled' if isinstance(error, RunCancelled) else 'blocked'
            self.save()
            raise
        except EventUIError as error:
            return self.blocked(error)
