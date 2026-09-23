"""First-clear dungeon task; local plans, verified progress and bounded parties."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re

from .base import BaseTask, TaskOptions, TaskReport
from .registry import register
from .dungeon_party import DungeonFormation, load_plan, next_party, route_conflicts
from .event_battle import EventCombat
from .task_story_event import CampaignClean
from ..game_ui.dungeon import completed_card, dungeon_map, floor_number, progress, auto_equip_party
from ..game_ui.screen import EventScreen, EventUI, EventUIError, normalized
from ..game_ui.character_equipment import inspect_unreleased_equipment
from ..run_session import clock as time, emit


@register('dungeon_first_clear')
class DungeonFirstClear(BaseTask):
    config_section = 'Dungeon'

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        if args or kwargs:
            raise ValueError('dungeon_first_clear使用Dungeon配置')
        options = config.get(cls.config_section, {})
        if type(options.get('prepare_only', False)) is not bool:
            raise ValueError('Dungeon.prepare_only必须为布尔值')
        if options.get('prepare_only'):
            from .strategy_video import acquire_strategies, task_source_options
            return (), {}, acquire_strategies(task_source_options('dungeon', options))
        return (), {}, None

    def __init__(self, robot, options: TaskOptions | None = None) -> None:
        super().__init__(robot)
        self.options = self.task_options() if options is None else dict(options)
        self.area = self.options.get('area', '四彩的灵峰')
        self.ui = EventUI(robot.driver, self.options.get('output', 'cache/daily/dungeon'))
        self.deadline = time.monotonic() + self.options.get('timeout', 3600)
        self.report: TaskReport = dict(status='running', area=self.area, history=[], pending=[])
        self.formation = DungeonFormation(self.ui)
        self.combat = EventCombat(self)
        account = self.options.get('account_key', str(getattr(robot.driver, 'index', 'default')))
        key = hashlib.sha256(f'{account}:{self.area}'.encode()).hexdigest()[:24]
        self.state_path = Path(self.options.get('state_dir', 'cache/daily/dungeon_state')) / (key+'.json')
        self.state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {'used': [], 'in_flight': None}

    def log(self, message: str) -> None:
        print('[地下城] '+message, flush=True)

    def check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise EventUIError('地下城任务超时')

    def save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.state_path)

    def ensure_plan(self):
        if self.plan is None:
            plan_path = self.options.get('teams', 'cache/game/strategies/dungeon_teams.yml')
            if not Path(plan_path).exists() and self.options.get('discover_sources', True):
                from .strategy_video import acquire_strategies, task_source_options
                from .strategy_document import dungeon_plan
                report = acquire_strategies(task_source_options('dungeon', self.options), check=self.check_deadline)
                self.report['source_search'] = report
                self.plan = dungeon_plan(report, self.area)
                if not self.plan:
                    self.report['pending'].append('自动解析尚未得到完整且不冲突的来源路线；见source_search字段证据，未开战')
                else:
                    from ..game_ui.avatar_assets import ensure_avatar_index
                    self.formation.avatars, _ = ensure_avatar_index(self.options.get('sources', {}).get('avatars'))
                return self.plan
            self.plan = load_plan(self.options.get('teams', 'cache/game/strategies/dungeon_teams.yml'), self.area,
                                  allow_local_trials=self.options.get('allow_local_trials', False))
        return self.plan

    def begin_attempt(self) -> None:
        """Rotate state only at a verified new-area entry confirmation."""
        if self.state.get('entry_pending'):
            return
        if self.state.get('in_flight'):
            raise EventUIError('旧战斗尚未核对，不能开始新的地下城轮次')
        if self.state.get('used') or self.state.get('history') or self.state.get('complete'):
            archive = self.state_path.parent/'archive'
            archive.mkdir(parents=True, exist_ok=True)
            from uuid import uuid4
            (archive/(self.state_path.stem+'-'+uuid4().hex+'.json')).write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        self.state = {'used': [], 'in_flight': None, 'history': [], 'entry_pending': True,
                      'started_at': time.time()}
        self.save_state()

    def audit_route(self) -> None:
        """Check the remaining boss route before committing any boss party."""
        remaining = [p for p in self.ensure_plan() if p.floor == 5 and p.key not in self.state['used']]
        conflicts = route_conflicts(remaining)
        for record in self.state.get('history', []):
            if record.get('characters_consumed', 0) <= 0:
                continue
            spent = {normalized(name) for name in record.get('formation', {}).get('order', [])}
            for entry in remaining:
                for member in entry.party.members:
                    if normalized(member.name) in spent:
                        conflicts.setdefault(normalized(member.name), []).extend([record['party'], entry.key])
        self.report['route_conflicts'] = conflicts
        if conflicts:
            raise EventUIError('首领路线重复占用角色，请先选择不冲突的组合：'+str(conflicts))
        audits = self.report.setdefault('route_audit', [])
        for entry in remaining:
            self.check_deadline()
            self.log('整条路线预检：'+entry.key)
            self.detail(self.enter())
            self.ui.expect_click('挑战', (750, 430, 940, 490), exact=True)
            ready, details = self.select_party(entry.party, entry.use_current_build)
            audits.append(dict(party=entry.key, ready=ready, role=entry.role, source=entry.party.source,
                               source_damage=entry.source_damage, formation=details))
            (self.ui.output/'route_audit.json').write_text(json.dumps(audits,ensure_ascii=False,indent=2),encoding='utf-8')
        self.detail(self.enter())
        blocked = [a['party'] for a in audits if not a['ready']]
        if blocked:
            raise EventUIError('路线预检存在未就绪队伍，未开始战斗：'+', '.join(blocked))

    def archive_battle(self, record: dict) -> None:
        """Persist measured attempts before clearing recovery state."""
        before, after = record['before'], record.get('after')
        if after and before['floor'] == after['floor']:
            record['damage'] = before['hp']-after['hp']
            record['characters_consumed'] = before['available']-after['available']
        elif record.get('first_clear_verified') and before['floor'] == 5:
            # The cleared area card proves the remaining HP was removed, but
            # does not expose a post-clear available-character count.
            record['damage'] = before['hp']
            record['damage_basis'] = 'remaining_hp_to_verified_first_clear'
        record['recorded_at'] = time.time()
        self.state.setdefault('history', []).append(record)
        self.state['in_flight'] = None
        self.save_state()

    def observe_battle(self, screen: EventScreen) -> None:
        now = time.monotonic()
        if now < self._next_battle_sample:
            return
        self._next_battle_sample = now+10
        index = len(self._battle_trace)
        path = self.ui.save(f'battle_{len(self.state["used"]):03d}_{index:03d}', screen)
        timer = screen.find(r'\d:\d{2}', (750, 0, 850, 55))
        self._battle_trace.append(dict(wall_time=time.time(), timer=timer.text if timer else None,
                                       screenshot=str(path)))

    def finish_clear(self, screen: EventScreen) -> TaskReport:
        evidence = str(self.ui.save('first_clear_verified', screen))
        if self.state.get('in_flight'):
            recovered = self.state['in_flight']
            recovered.update(outcome='recovered_clear', first_clear_verified=True, progressed=True,
                             clear_evidence=evidence)
            self.archive_battle(recovered)
            self.report['history'].append(recovered)
        self.report['status'] = 'complete' if self.report['history'] else 'already_complete'
        self.state['complete'] = True
        self.state['in_flight'] = None
        self.save_state()
        return self.report

    def story_dialog(self, screen: EventScreen) -> bool:
        if ('每次战斗环境都会变化的首领战' in normalized(screen.text())
                and screen.find('可可萝', (180, 380, 400, 430), exact=True)):
            self.ui.click((780, 490))
            return True
        if screen.find('收取报酬', (250, 0, 710, 80), exact=True):
            button = screen.find('确认', (350, 450, 610, 510), exact=True)
            if button:
                self.ui.click(button)
                return True
        return CampaignClean.story_dialog(self, screen)

    def combat_return(self, screen: EventScreen) -> bool:
        return dungeon_map(screen, self.area) or progress(screen) is not None or completed_card(screen, self.area) is True

    def combat_result_button(self, screen: EventScreen):
        if screen.find('战斗失败|战斗胜利|WIN|伤害报告'):
            return screen.find('前往地下城', (700, 460, 940, 530), exact=True)
        return None

    def select_party(self, party, use_current_build=False, checked=None):
        if use_current_build and not self.options.get('allow_local_trials', False):
            raise EventUIError('按账号状态试打未获本次启用')
        self.formation.use_current_build = use_current_build
        checked = set() if checked is None else checked
        ready, details = self.formation.select(party)
        if any(isinstance(item, dict) and any('未在搜索结果中确认' in reason for reason in item.get('reasons', []))
               for item in details.get('unready', [])):
            # Resolve missing members before expensive character-page build
            # lookups for the rest of a party that cannot currently be formed.
            return ready, details
        unknown = [m.name for m in party.members
                   if (a := self.formation.observed.get(normalized(m.name)))
                   and a.identity_verified and a.unique is None and m.name not in checked]
        if ready or not unknown:
            return ready, details
        self.ui.expect_click('取消', (630, 420, 780, 490), exact=True)
        self.ui.expect_click('取消', (600, 430, 780, 495), exact=True)
        confirmed = False
        for name in unknown:
            checked.add(name)
            evidence = inspect_unreleased_equipment(self.ui, name)
            if evidence:
                self.formation.unreleased[normalized(name)] = (time.time(), evidence)
                confirmed = True
        self.ui.click((532, 515))
        self.detail(self.enter())
        self.ui.expect_click('挑战', (750, 430, 940, 490), exact=True)
        # A later audit may resolve a previously unknown identity and expose
        # another missing badge. Each member gets at most one page lookup.
        return self.select_party(party, use_current_build, checked) if confirmed else (ready, details)

    def enter(self) -> EventScreen:
        """Navigate known pages only; never click the dungeon-wide retreat."""
        for _ in range(35):
            self.check_deadline()
            s = self.ui.capture()
            if s.find('自动特别装备设定', (250, 0, 710, 80), exact=True):
                self.ui.expect_click('取消', (260, 440, 480, 515), exact=True)
                continue
            if s.find('特别装备设定', (250, 0, 710, 80), exact=True):
                self.ui.expect_click('取消', (30, 440, 260, 515), exact=True)
                continue
            if s.find('角色详情', (300, 0, 650, 70), exact=True):
                button = s.find('确认', (320, 450, 650, 515), exact=True)
                if button:
                    self.ui.click(button)
                continue
            if progress(s) or dungeon_map(s, self.area):
                if not s.find(re.escape(normalized(self.area)), (40, 0, 290, 80), exact=True):
                    raise EventUIError('正在进行的地下城与配置区域不符')
                if self.state.pop('entry_pending', False):
                    self.save_state()
                return s
            complete = completed_card(s, self.area)
            if complete is True:
                return s
            if complete is False:
                if not self.ensure_plan():
                    raise EventUIError('本地地下城队伍方案缺失；未消耗区域挑战次数')
                if not s.find(r'1/1', (820, 410, 935, 460), exact=True):
                    raise EventUIError('剩余区域挑战次数不是1/1，未进入')
                self.ui.click(s.find(re.escape(normalized(self.area)), (20, 305, 940, 345), exact=True))
                continue
            if s.find('区域选择确认', (250, 0, 710, 130), exact=True):
                if normalized(self.area) not in normalized(s.text()) or not self.ensure_plan():
                    raise EventUIError('区域确认与本地方案不符')
                self.begin_attempt()
                self.ui.expect_click('确认', (460, 300, 800, 510), exact=True)
                continue
            if s.find('队伍编组', (300, 0, 650, 70)):
                self.ui.expect_click('取消', (630, 420, 780, 490), exact=True)
                continue
            if self.story_dialog(s):
                continue
            if s.find('特别关卡', (40, 0, 300, 70)):
                button = s.find('地下城', exact=True)
                if button:
                    self.ui.click(button)
                else:
                    time.sleep(.5)
                continue
            if s.find('冒险', (40, 0, 220, 70), exact=True):
                button = s.find('特别关卡|特别', (670, 80, 810, 210))
                if button:
                    self.ui.click(button)
                else:
                    time.sleep(.5)
                continue
            if s.find('我的主页|主菜单', (0, 480, 960, 540)) and not s.find('地下城', (40, 0, 240, 70)):
                self.ui.click((532, 515))
                continue
            time.sleep(.5)
        raise EventUIError('未能从已知页面进入目标地下城')

    def detail(self, screen: EventScreen, tutorial_retry: bool = True) -> EventScreen:
        if progress(screen):
            return screen
        if not dungeon_map(screen, self.area):
            raise EventUIError('未确认地下城地图，停止定位关卡')
        # Floor number advances before the treasure animation/reward dialog
        # finishes. Wait for the actual next enemy label before navigating.
        last = None
        stable = 0
        def ready(s):
            nonlocal last, stable
            floor = floor_number(s)
            label = (s.find(rf'{floor[0]}层', (80, 90, 900, 420), exact=True)
                     if dungeon_map(s, self.area) and floor else None)
            key = (floor, tuple(label.center)) if label else None
            stable = stable+1 if key is not None and key == last else 0
            last = key
            return stable >= 2
        screen = self.ui.wait(lambda s: completed_card(s, self.area) is True or ready(s),
                              '当前层地图标记', timeout=30, handle=self.story_dialog)
        if completed_card(screen, self.area) is True:
            return screen
        floor, _ = floor_number(screen)
        label = screen.find(rf'{floor}层', (80, 90, 900, 420), exact=True)
        # The floor label itself opens details; offsets can hit top navigation
        # while the map scrolls to the next enemy.
        self.ui.click(label)
        handled = False
        clicks = 1
        last_click = time.monotonic()
        def dialog(s):
            nonlocal handled, clicks, last_click
            handled = self.story_dialog(s) or handled
            # A background click can be dropped after navigation. Retry only
            # the same observed floor label while still on this dungeon map.
            if (not handled and clicks < 3 and time.monotonic()-last_click >= 3
                    and dungeon_map(s, self.area) and floor_number(s) == (floor, 5)):
                current = s.find(rf'{floor}层', (80, 90, 900, 420), exact=True)
                if current and tuple(current.center) == tuple(label.center):
                    self.ui.click(current)
                    clicks += 1
                    last_click = time.monotonic()
        result = self.ui.wait(lambda s: progress(s) is not None or completed_card(s, self.area) is True
                              or (handled and dungeon_map(s, self.area)),
                              '地下城敌人详情', timeout=20, handle=dialog)
        if progress(result) or completed_card(result, self.area) is True:
            return result
        if tutorial_retry:
            return self.detail(result, tutorial_retry=False)
        raise EventUIError('首领教学后仍未进入详情')

    def run(self) -> TaskReport:
        try:
            self.plan = None
            s = self.enter()
            route_audited = False
            unready_this_run: set[str] = set()
            limit = self.options.get('max_battles', 30)
            for attempt in range(limit+1):
                self.check_deadline()
                if completed_card(s, self.area) is True:
                    return self.finish_clear(s)
                if attempt == limit:
                    break
                s = self.detail(s)
                if completed_card(s, self.area) is True:
                    return self.finish_clear(s)
                before = progress(s)
                self.report['progress'] = asdict(before)
                if self.state.get('in_flight'):
                    previous = self.state['in_flight']
                    old = previous['before']
                    if before.floor > old['floor']:
                        self.ui.save('recovered_floor_progress', s)
                        previous.update(after=asdict(before), outcome='recovered', progressed=True)
                        self.report['history'].append(previous)
                        self.state['in_flight'] = None
                        self.save_state()
                    else:
                        raise EventUIError('上次战斗中断且未确认跨层，需核对in_flight证据；不自动重放')
                if before.floor == 5 and not route_audited and self.options.get('preflight', True):
                    self.audit_route()
                    route_audited = True
                    s = self.detail(self.enter())
                    before = progress(s)
                    if self.options.get('audit_only', False):
                        self.report['status'] = 'audited'
                        return self.report
                if self.options.get('audit_only', False):
                    raise EventUIError('只核验模式不允许开战；请启用preflight并停在首领层')
                entry = next_party(self.ensure_plan(), before.floor, s.text(), set(self.state['used']) | unready_this_run, before.hp)
                if entry is None:
                    raise EventUIError(f'第{before.floor}层/当前阶段没有剩余适用队伍')
                self.ui.save(f'before_{len(self.state["used"]):03d}', s)
                self.ui.expect_click('挑战', (750, 430, 940, 490), exact=True)
                ready, details = self.select_party(entry.party, entry.use_current_build)
                record = dict(party=entry.key, source=entry.party.source, before=asdict(before), formation=details,
                              phase_before=s.text(), role=entry.role, source_damage=entry.source_damage,
                              set={m.name:m.instant for m in entry.party.members})
                self.report['history'].append(record)
                if not ready:
                    record['outcome'] = 'unready'
                    unready_this_run.add(entry.key)
                    self.state.setdefault('audits', []).append(record)
                    self.save_state()
                    self.ui.expect_click('取消', (630, 420, 780, 490), exact=True)
                    s = self.ui.wait(lambda f: progress(f) is not None, '返回地下城详情')
                    continue
                if self.deadline-time.monotonic() < self.options.get('battle_timeout', 220)+30:
                    raise EventUIError('剩余任务时间不足以安全完成一次战斗，未开战')
                if self.options.get('auto_equip', False):
                    record['special_equipment'] = auto_equip_party(self.ui, entry.key)
                self.state['used'].append(entry.key)
                self.state['in_flight'] = record
                self.save_state()
                emit('dungeon.battle', party=entry.key, before=asdict(before))
                started = time.monotonic()
                self._battle_evidence_id = entry.key
                self._battle_trace = []
                self._next_battle_sample = 0
                result = self.combat.run(entry.party, details['order'])
                record.update(outcome=result.outcome, reason=result.reason, elapsed_seconds=round(time.monotonic()-started,2),
                              battle_trace=self._battle_trace)
                if result.outcome in ('blocked', 'retreated', 'failed'):
                    self.log(f'{entry.key}: {result.outcome}，核对进度后选择下一队')
                if result.outcome in ('blocked', 'retreated'):
                    returned = self.ui.capture()
                    if returned.find('队伍编组', (300, 0, 650, 70)):
                        self.ui.expect_click('取消', (630, 420, 780, 490), exact=True)
                s = self.ui.wait(lambda f: self.combat_return(f), '地下城战斗结算返回', timeout=30,
                                 handle=self.story_dialog)
                if completed_card(s, self.area) is not True:
                    s = self.detail(s)
                if completed_card(s, self.area) is True:
                    record.update(first_clear_verified=True, progressed=True,
                                  clear_evidence=str(self.ui.save('first_clear_verified', s)))
                else:
                    after = progress(s)
                    record['after'] = asdict(after)
                    record['phase_after'] = s.text()
                    if after.floor < before.floor or (after.floor == before.floor and after.hp > before.hp):
                        raise EventUIError('地下城进度回退或重置，停止后续队伍')
                    record['progressed'] = after.floor > before.floor or after.hp < before.hp
                    if not record['progressed']:
                        record['reason'] = '无血量/层数进展，本队不再重试'
                self.archive_battle(record)
                if (self.options.get('review_on_unexpected', True) and record.get('after')
                        and (not record.get('progressed') or result.outcome == 'retreated'
                             or (entry.role == 'bridge' and entry.phase in normalized(s.text())))):
                    raise EventUIError('已保存本队试验数据；未达到预期进展/换季，请根据减员和配装证据调整后继续，未自动投入预留队')
            self.report['status'] = 'partial'
            self.report['pending'].append('达到本次最大编队/战斗次数，已保留地下城进度和试验记录')
            return self.report
        except (EventUIError, ValueError) as error:
            self.report['status'] = 'blocked'
            self.report['pending'].append(str(error))
            self.ui.save('blocked')
            return self.report
        finally:
            (self.ui.output/'report.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
