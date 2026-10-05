"""Daily outpost clears/sweeps and ticket-funded Abyss Subjugation bosses."""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re

from .base import Event, EventNews, TimeLimitTask
from .options import validated_options
from .event_battle import EventCombat
from .abyss_retry import combat_sample, retry_decision
from .registry import register
from .subjugation_party import (SubjugationFormation, prepare_avatars, recover_equipment,
                                require_event_talent, guide_party, trial_stage)
from .party_preparation import source_candidates, prepare_special, party_fingerprint, numeric_equipment_unknown
from ..constants import SERVER_TIMEZONE
from ..game_ui import abyss_subjugation as field
from ..game_ui.dawn_labyrinth import navigation_exit as maze_navigation_exit
from ..game_ui.recollection import navigation_exit as recollection_navigation_exit
from ..game_ui.special_equipment import cancel_special_equipment
from ..game_ui.avatar_assets import read_json
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..game_ui.team_battle import meets_reference
from ..run_session import atomic_json, checkpoint, clock as time, RunCancelled, ResumeUnsafe


class SubjugationBlocked(EventUIError):
    pass


class BossPartyUnavailable(SubjugationBlocked):
    """No usable guide/trial remains; the last live boss state is reconciled."""


def migrate_options(options):
    """Remove retired saved-team settings without expanding old sweep-only runs."""
    value = dict(options)
    value.setdefault('first_clear', value.get('allow_local_trials') is not False)
    value.pop('normal_team', None)
    value.pop('boss_teams', None)
    return value


def validate_options(options):
    if not isinstance(options, dict):
        raise ValueError('AbyssSubjugation必须是配置对象')
    value = validated_options(migrate_options(options), 'AbyssSubjugation',
        integers=(('timeout', 7200, 21600), ('battle_timeout', 240, 600),
                  ('max_stamina', 400, 2000), ('max_boss_tickets', 99, 999),
                  ('max_simulations', 30, 100), ('max_normal_trials', 6, 12),
                  ('max_source_batches', 3, 10)),
        flags=(('preview_only', False), ('first_clear', True), ('allow_local_trials', True),
               ('auto_collect_house_stamina', True), ('discover_sources', True),
               ('auto_equip_special', True), ('allow_five_star_upgrade', False),
               ('allow_divine_amulets', False)))
    if 'avatars' in value and not isinstance(value['avatars'], dict):
        raise ValueError('AbyssSubjugation.avatars必须是配置对象')
    if 'sources' in value and not isinstance(value['sources'], dict):
        raise ValueError('AbyssSubjugation.sources必须是配置对象')
    from .strategy_inputs import validate_urls
    value['source_urls'] = validate_urls(value.get('source_urls', []))
    return value


@register('abyss_subjugation', requires_home=False)
class AbyssSubjugation(TimeLimitTask):
    config_section = 'AbyssSubjugation'

    @staticmethod
    def event_active(event):
        return bool(event and event.startTimestamp <= time.time() < event.endTimestamp)

    @staticmethod
    def valid(event_news: EventNews, args=None):
        event = event_news.abyssSubjugation
        return (AbyssSubjugation, [event]) if AbyssSubjugation.event_active(event) else None

    @classmethod
    def prepare(cls, config, event: Event | None = None):
        validate_options(config.get(cls.config_section, {}))
        if event is None:
            from ..news import fetch_event_news
            event = fetch_event_news().abyssSubjugation
        return (event,), {}, None if cls.event_active(event) else dict(status='unavailable')

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/abyss_subjugation'))
        self.formation = SubjugationFormation(self.ui)
        self.combat = EventCombat(self)
        self.deadline = time.monotonic()+self.options['timeout']
        self.report = dict(status='running', history=[], pending=[], stamina_spent=0,
                           tickets_spent=0, simulations=[], bosses={}, outposts={}, all_bosses_cleared=False)
        self.state = {}
        self.state_path = None
        self.event = None
        self.last_result = {}
        self.house_checked = False
        self.simulation_count = 0
        self.source_pools = {}
        self.guide_streams = {}
        self.inspected_sources = {}
        self.boss_unlocks = {}
        self.failed_boss_teams = {}
        self._battle_samples = []
        self._next_sample = 0
        self.simulated_loadout = None

    def log(self, message):
        print('[深渊讨伐战] '+message, flush=True)

    def save(self):
        atomic_json(self.ui.output/'report.json', self.report)
        if self.state_path is not None:
            atomic_json(self.state_path, self.state)

    def day(self):
        return (datetime.fromtimestamp(time.time(), SERVER_TIMEZONE)-timedelta(hours=5)).date().isoformat()

    def check_deadline(self):
        checkpoint()
        if time.monotonic() >= self.deadline:
            raise SubjugationBlocked('深渊讨伐战达到任务时限；未追加消费')
        if self.event and not self.event_active(self.event):
            raise SubjugationBlocked('深渊讨伐战已结束；未追加消费')

    def capture(self):
        self.check_deadline()
        return self.ui.capture()

    def wait(self, predicate, description, timeout=30):
        deadline = min(self.deadline, time.monotonic()+timeout)
        while time.monotonic() < deadline:
            s = self.capture()
            if predicate(s):
                return s
            time.sleep(.3)
        self.ui.save('timeout_'+description)
        raise SubjugationBlocked(description+'超时；未重复提交')

    def click(self, screen, pattern, roi):
        item = screen.find(pattern, roi, exact=True)
        if item is None or item.score < .95:
            raise SubjugationBlocked('按钮未确认：'+pattern)
        self.check_deadline()
        self.ui.click(item)

    def enter(self):
        adventure_requested = activity_requested = False
        for _ in range(45):
            s = self.capture()
            if field.sweep_confirmation(s):
                plan = self.state.get('pending')
                if plan and plan['kind'].endswith('_sweep'):
                    if field.sweep_cost(self.ui, s, '消耗券') != plan['quantity']:
                        raise SubjugationBlocked('待核对扫荡确认与记录不符')
                    plan['cancelled_preview'] = str(self.ui.save('cancelled_sweep_preview', s))
                    self.save()
                self.click(s, '取消', (290, 340, 445, 405))
            elif field.limited_shop(s):
                self.click(s, '取消', (500, 430, 690, 520))
            elif cancel_special_equipment(self.ui, s):
                continue
            elif s.find('角色详情', (300, 0, 650, 70), exact=True):
                self.click(s, self.formation.detail_close_pattern, (320, 450, 650, 515))
            elif field.saved_teams(s) or field.boss_selector(s):
                self.click(s, '关闭', (360, 445, 620, 515))
                self.wait(lambda frame: not frame.find('我的队伍一览|首领难度选择', (280, 15, 700, 70), exact=True),
                          '关闭队伍或难度列表', timeout=10)
            elif field.formation(s):
                self.click(s, '取消', (635, 415, 785, 500))
                self.wait(lambda frame: not frame.find('队伍编组', (300, 15, 650, 70), exact=True),
                          '取消编队', timeout=10)
            elif (cancel := field.detail_cancel(s)) is not None:
                self.ui.click(cancel)
                self.wait(lambda frame: not frame.find('BOSS详情|前哨关卡', (45, 25, 195, 85), exact=True),
                          '关闭关卡详情', timeout=10)
            elif field.sweep_receipt(s) or field.result_button(s):
                button = field.result_button(s) or s.find('关闭|确认|下一步', (250, 330, 945, 525), exact=True)
                if button is None:
                    raise SubjugationBlocked('未结算回执的关闭按钮未知')
                if s.find('战斗失败|挑战失败|LOSE|DEFEAT') and self.state.get('pending', {}).get('kind', '').endswith('_battle'):
                    self.state['pending'].update(outcome='failed', outcome_evidence=str(self.ui.save('resumed_failure', s)))
                    self.save()
                self.ui.save('resumed_receipt', s)
                self.ui.click(button)
            elif s.find('角色详情', (300, 0, 650, 70), exact=True):
                self.click(s, '确认', (320, 450, 650, 515))
            elif field.home(s):
                return self.verify_home(s)
            elif s.find('进行中战斗') and s.find('主菜单', (300, 30, 660, 150), exact=True):
                if not self.state.get('pending', {}).get('kind', '').endswith('_battle'):
                    raise SubjugationBlocked('存在未知的暂停战斗；保留现场')
                self.click(s, '返回', (260, 405, 410, 465))
                self.wait(lambda frame: not frame.find('进行中战斗'), '接续暂停战斗', timeout=10)
            elif s.find('冒险', (30, 0, 180, 65), exact=True):
                entry = s.find('深渊讨伐战', (0, 60, 955, 470), exact=True)
                if entry is None or activity_requested:
                    time.sleep(.5)
                    continue
                self.ui.click(entry)
                activity_requested = True
            elif (cancel := maze_navigation_exit(s) or recollection_navigation_exit(s)) is not None:
                self.ui.click(cancel)
            elif ((s.find('菜单', (840, 0, 960, 65), exact=True) and not s.expedition_home)
                  or s.find(r'\d:\d{2}', (750, 0, 850, 55))):
                if self.state.get('pending', {}).get('kind', '').endswith('_battle'):
                    self.wait(lambda frame: self.combat_return(frame) or field.result_button(frame),
                              '待核对战斗自然结算', timeout=self.options['battle_timeout']+60)
                    continue
                raise SubjugationBlocked('存在尚未结算的战斗；保留现场，不开始新挑战')
            elif s.find('冒险', (475, 475, 595, 540), exact=True) and not s.find('取消|确认|关闭', (200, 300, 950, 525), exact=True):
                if not adventure_requested and not activity_requested:
                    self.click(s, '冒险', (475, 475, 595, 540))
                    adventure_requested = True
                else:
                    time.sleep(.5)
            else:
                time.sleep(.5)
        raise SubjugationBlocked('深渊讨伐战入口或覆盖页面未知')

    def verify_home(self, s):
        start = datetime.fromtimestamp(self.event.startTimestamp, SERVER_TIMEZONE)
        end = datetime.fromtimestamp(self.event.endTimestamp, SERVER_TIMEZONE)
        expected = (start.month, start.day, start.hour, start.minute, end.month, end.day, end.hour, end.minute)
        title = self.event.extras.get('title')
        if not title or not s.find(re.escape(normalized(title)), (30, 50, 280, 85), exact=True) or field.dates(s) != expected:
            raise SubjugationBlocked('游戏活动名称/时间与数据库不一致；未消费')
        counts, tickets = field.attempts(s), field.tickets(self.ui, s)
        if counts is None or tickets is None:
            raise SubjugationBlocked('前哨剩余次数或讨伐委托证余额未知')
        self.report.update(remaining_attempts=counts, remaining_tickets=tickets)
        return s

    def normal_detail(self, difficulty, *, home=None):
        s = home if home is not None else self.enter()
        if s is None:
            raise SubjugationBlocked('活动入口不可用')
        index = field.DIFFICULTIES.index(difficulty)
        self.click(s, re.escape(difficulty), (90, field.OUTPOST_Y[index]-20, 230, field.OUTPOST_Y[index]+20))
        s = self.wait(field.outpost_detail, '前哨关卡详情')
        if field.difficulty(s, self.ui) != difficulty or field.detail_attempts(s) is None:
            raise SubjugationBlocked('前哨难度或次数不符')
        return s

    def boss_detail(self, index, difficulty, *, simulation=False):
        s = self.enter()
        if s is None:
            raise SubjugationBlocked('活动入口不可用')
        rows = sorted(s.all('首领', (350, 295, 905, 380)), key=lambda r: r.center[0])
        self.ui.click(rows[index])
        s = self.wait(lambda frame: field.boss_selector(frame) or (field.boss_detail(frame)
                      and field.difficulty(frame, self.ui) == difficulty), '首领入口')
        if field.boss_selector(s):
            item = field.selector_difficulty(s, difficulty)
            # Clearing High adds Extreme above the three existing rows.
            # Locate the observed label, using the shared verified scrollbar.
            for direction in (-1, 1):
                for _ in range(3):
                    if item is not None or not self.ui.scrollbar(s, (696, 75, 708, 402), direction):
                        break
                    s = self.capture()
                    if not field.boss_selector(s):
                        raise SubjugationBlocked('首领难度列表滚动后页面未知')
                    item = field.selector_difficulty(s, difficulty)
            if item is None:
                if difficulty == '极难' and str(index)+':高难' not in self.state.get('boss_clears', {}):
                    return None
                raise SubjugationBlocked('目标首领难度未完整显示')
            number = field.BOSS_DIFFICULTIES.index(difficulty)
            if number < len(field.BOSS_DIFFICULTIES)-1:
                following = field.selector_difficulty(s, field.BOSS_DIFFICULTIES[number+1])
                if following is not None:
                    self.boss_unlocks[str(index)+':'+difficulty] = not field.selector_locked(s, following)
            if field.selector_locked(s, item):
                return None
            self.ui.click(item)
        # The old detail can remain visible while the newly selected tier
        # loads. Its header must match before reading HP or enabling combat.
        s = self.wait(lambda frame: field.boss_detail(frame) and field.difficulty(frame, self.ui) == difficulty,
                      '首领'+difficulty+'详情')
        wanted = 'simulation' if simulation else 'real'
        if field.mode(s) != wanted:
            self.click(s, '模拟战' if simulation else '实战', (690, 85, 925, 135))
            s = self.wait(lambda s: field.boss_detail(s) and field.mode(s) == wanted, '首领战斗类型')
        if field.boss_name(s) is None or field.boss_health(self.ui, s) is None:
            raise SubjugationBlocked('首领身份或生命值未知')
        return s

    def open_formation(self, detail):
        button = detail.find('挑战', (755, 428, 925, 508), exact=True)
        if not detail.blue_button(button):
            raise SubjugationBlocked('挑战按钮不可用；未回复资源')
        self.ui.click(button)
        return self.wait(field.formation, '队伍编组')

    def commit(self, plan):
        if self.state.get('pending'):
            raise SubjugationBlocked('上次消费尚未核对；未重复提交')
        self.state['pending'] = dict(plan, day=self.day(), before_evidence=str(self.ui.save('before_'+str(len(self.report['history'])))))
        self.save()

    def reconcile(self):
        plan = self.state.get('pending')
        if not plan:
            return
        s = self.enter()
        if s is None:
            raise SubjugationBlocked('待核对消费时活动入口不可用')
        counts, tickets = field.attempts(s), field.tickets(self.ui, s)
        can_cancel = bool(plan.get('cancelled_preview') or plan.get('outcome') in ('failed', 'retreated', 'blocked'))
        if plan['kind'].startswith('outpost'):
            if plan['day'] != self.day():
                raise SubjugationBlocked('未核对的前哨消费已跨05:00刷新；保留记录，未重放')
            expected = dict(plan['attempts'])
            expected[plan['difficulty']] -= plan['quantity']
            if can_cancel and counts == plan['attempts'] and tickets == plan['tickets_before']:
                self.clear_unspent(plan)
                return
            if counts != expected or tickets is None or tickets <= plan['tickets_before']:
                raise SubjugationBlocked('前哨次数扣除或讨伐委托证增加未确认；未重复提交')
            self.report['stamina_spent'] += plan['stamina_cost']
            self.report['outposts'][plan['difficulty']] = dict(cleared=True, gained_tickets=tickets-plan['tickets_before'])
        else:
            detail = self.boss_detail(plan['index'], plan['difficulty'])
            if detail is None or field.boss_name(detail) != plan['boss']:
                raise SubjugationBlocked('待核对消费的首领身份不符')
            health = field.boss_health(self.ui, detail)
            cleared = self.boss_cleared(detail, plan['index'], plan['difficulty'])
            if can_cancel and tickets == plan['tickets_before'] and health == tuple(plan['health']):
                self.clear_unspent(plan)
                return
            if tickets != plan['tickets_before']-plan['quantity'] or health is None:
                raise SubjugationBlocked('讨伐委托证未按预览扣除；未重复提交')
            if plan['kind'] == 'boss_battle' and not (cleared is True or health[0] < plan['health'][0] or plan.get('result', {}).get('win')):
                raise SubjugationBlocked('实战消费后未确认首领进度；停止追加挑战')
            if plan['kind'] == 'boss_sweep' and cleared is not True:
                raise SubjugationBlocked('扫荡后首领通关状态无法核对')
            if plan['kind'] == 'boss_battle' and plan.get('result', {}).get('win'):
                self.record_boss_clear(detail, plan['index'], plan['difficulty'])
                cleared = True
            self.report['tickets_spent'] += plan['quantity']
            self.report['bosses'][str(plan['index'])+':'+plan['difficulty']] = dict(name=plan['boss'], cleared=cleared, health=health)
        self.report['history'].append(dict(plan, tickets_after=tickets, attempts_after=counts,
                                          after_evidence=str(self.ui.save('after_'+str(len(self.report['history']))))))
        self.state.pop('pending')
        self.save()

    def clear_unspent(self, plan):
        self.report.setdefault('unspent_actions', []).append(dict(plan,
            after_evidence=str(self.ui.save('unspent_'+str(len(self.report.get('unspent_actions', [])))))))
        self.state.pop('pending')
        self.save()

    def combat_return(self, s):
        return field.home(s) or field.boss_detail(s) or field.outpost_detail(s)

    def combat_result_button(self, s):
        if field.limited_shop(s):
            return s.find('取消', (500, 430, 690, 520), exact=True)
        button = field.result_button(s)
        if button:
            self.last_result = dict(self.last_result, win=bool(self.last_result.get('win') or s.find('WIN|战斗胜利|胜利')), text=s.text(),
                                    evidence=str(self.ui.save('battle_result_'+str(len(self.report['history'])))))
            damage = field.result_damage(self.ui, s)
            if damage is not None:
                self.last_result['damage'] = damage
        return button

    def story_dialog(self, s):
        return False

    def observe_battle(self, screen):
        if time.monotonic() < self._next_sample:
            return
        sample = combat_sample(screen, self.combat.portraits,
                               maximum_hp=getattr(self, '_expected_battle_hp', None))
        if sample is None:
            return
        self._next_sample = time.monotonic()+2
        sample['evidence'] = str(self.ui.save(
            f'battle_{len(self.report["history"])}_{self.simulation_count}_sample_{len(self._battle_samples)}', screen))
        self._battle_samples.append(sample)

    def battle(self, party, order, plan=None):
        expected = self.simulated_loadout if plan and plan.get('kind') == 'boss_battle' else None
        if plan and plan.get('kind') == 'boss_battle' and expected is None:
            raise SubjugationBlocked('缺少本次模拟的特别装备记录，未实战')
        prepared = self.prepare_party(party, order, expected=expected)
        s = self.capture()
        button = s.find('战斗开始', (780, 410, 935, 505), exact=True)
        if not field.formation(s) or not s.blue_button(button):
            raise SubjugationBlocked('战斗开始按钮未确认')
        require_event_talent(self, party)
        # Old cached trials allowed every member to die. Restore the shared
        # combat default before either a free simulation or a real attack.
        party.allow_deaths = 0
        self.last_result = dict(preparation=prepared)
        self._battle_samples = []
        self._next_sample = 0
        if plan is not None:
            health = plan.get('health')
            self._expected_battle_hp = health[1] if health else None
            self.commit(plan)
        result = self.combat.run(party, order)
        self.last_result.update(samples=list(self._battle_samples),
                                retry=retry_decision(self._battle_samples, result.reason, 1))
        if plan is not None:
            self.state['pending'].update(outcome=result.outcome, result=dict(self.last_result))
            self.save()
            self.reconcile()
        return result

    def prepare_party(self, party, order, *, expected=None):
        self.report_progress('战前准备 · 特别装备分配与五人复核')
        result = prepare_special(self.formation, party, order,
                                 auto=self.options['auto_equip_special'], expected=expected)
        self.report.setdefault('party_preparations', []).append(result)
        self.save()
        return result

    def guide_candidates(self, kind, difficulty, reopen, boss='', boss_number=None):
        key = (kind, difficulty, boss)
        def available():
            stage = trial_stage(self)
            if stage.element not in getattr(self.formation, '_owned_candidates', {}):
                reopen()
            return self.formation.owned_candidates(stage.element)
        if key not in self.guide_streams:
            self.guide_streams[key] = source_candidates(
                lambda **kw: self.source_parties(kind, boss, boss_number, difficulty=difficulty, **kw),
                lambda: self.formation.observed, available=available,
                max_batches=self.options['max_source_batches'],
                allow_substitutions=self.options['allow_local_trials'])
        return self.guide_streams[key]

    def ensure_stamina(self, difficulty, detail):
        # Cleared stages already select their remaining attempts. Derive the
        # unit cost from that preview instead of reducing and restoring it.
        quantity = field.quantity(detail)
        preview = field.stamina_preview(self.ui, detail)
        if (quantity is not None and 1 <= quantity <= 99 and preview is not None
                and preview[0] > preview[1] >= 0
                and (preview[0]-preview[1]) % quantity == 0
                and detail.blue_button(detail.find('挑战', (755, 428, 925, 508), exact=True))):
            return detail, (preview[0]-preview[1])//quantity
        # An unaffordable bulk preview may still permit one attempt.
        detail = self.adjust_quantity(detail, 1)
        preview = field.stamina_preview(self.ui, detail)
        if preview is not None and preview[1] >= 0 and detail.blue_button(detail.find('挑战', (755, 428, 925, 508), exact=True)):
            if preview[0] <= preview[1]:
                raise SubjugationBlocked('前哨单次体力预览未知')
            return detail, preview[0]-preview[1]
        # Insufficient stamina leaves a blue challenge button and a red
        # negative preview which full-frame OCR can omit. Collection is safe;
        # require a fresh complete nonnegative preview before any challenge.
        if preview is None and self.ui.number(detail, (165, 446, 211, 476)) is None:
            raise SubjugationBlocked('前哨现有体力未知')
        if self.options['auto_collect_house_stamina'] and not self.house_checked:
            from ..game_ui.guild_house import collect_produced_stamina
            self.house_checked = True
            s = self.enter()
            self.report['house_stamina'] = collect_produced_stamina(self.ui, s)
            detail = self.normal_detail(difficulty)
            detail = self.adjust_quantity(detail, 1)
            preview = field.stamina_preview(self.ui, detail)
            if preview and preview[0] > preview[1] >= 0 and detail.blue_button(detail.find('挑战', (755, 428, 925, 508), exact=True)):
                return detail, preview[0]-preview[1]
        raise SubjugationBlocked('现有体力不足；未购买体力')

    def select_verified_party(self, party, reopen):
        prepare_avatars(self)
        ready, selection = self.formation.select(party)
        if ready:
            return party, selection['order']
        reasons = [reason for row in selection.get('unready', [])
                   for reason in (row.get('reasons', []) if isinstance(row, dict) else [str(row)])]
        equipment_unknown = bool(reasons) and all(
            ('专武' in reason and '未知' in reason)
            or reason.startswith('账号培养或装备未知：') and reason.rsplit('：', 1)[-1] in ('unique', 'unique2')
            for reason in reasons)
        if equipment_unknown:
            # Re-establish missing evidence without replacing the simulated
            # build or running cultivation between simulation and paid combat.
            self.formation.numeric_equipment_names = numeric_equipment_unknown(party, self.formation.observed)
            try:
                recover_equipment(self, [m.name for m in party.members])
            finally:
                self.formation.numeric_equipment_names = ()
            reopen()
            ready, selection = self.formation.select(party)
            if ready:
                return party, selection['order']
        raise SubjugationBlocked('队伍核验失败：'+str(selection))

    def choose_normal_party(self, difficulty, reopen, failed):
        for candidate in self.guide_candidates('outpost', difficulty, reopen):
            seed = candidate.party
            try:
                reopen()
                party, order = guide_party(self, seed, reopen,
                                          allow_substitutions=candidate.allow_substitutions)
                if party_fingerprint(party) in failed:
                    continue
            except EventUIError as error:
                self.report.setdefault('candidate_rejections', []).append(dict(candidate=seed.name, source=seed.source, reason=str(error)))
                continue
            self.report.setdefault('outpost_parties', {})[difficulty] = dict(
                party=party.name, source=party.source, assumptions=party.assumptions)
            return party, order
        raise SubjugationBlocked('没有核验通过的本期前哨攻略；未开战')

    def source_parties(self, kind, boss='', boss_number=None, *, difficulty, advance=False):
        if not self.options['discover_sources'] and not self.options['source_urls']:
            return []
        key = (kind, difficulty, boss)
        if key not in self.source_pools or advance:
            from .subjugation_guides import source_options, parties_for_target
            from .strategy_video import acquire_strategies
            prepare_avatars(self)
            options = source_options(self.options, self.event, kind=kind, boss=boss, boss_number=boss_number,
                                     difficulty=difficulty)
            if self.options['allow_local_trials'] and kind == 'boss':
                target = getattr(self, 'source_targets', {}).get(key)
                if target:
                    options['observed_target'] = target
            self.report_progress('检索并解析本期攻略 · '+difficulty+('前哨' if kind == 'outpost' else boss))
            report = acquire_strategies(options, index=self.formation.avatars, check=self.check_deadline,
                exclude_sources=self.inspected_sources.get(key, set()),
                accept=lambda report: bool(parties_for_target(report, options,
                    allow_local_trials=self.options['allow_local_trials'])))
            self.inspected_sources.setdefault(key, set()).update(report.get('inspected_sources', []))
            self.report.setdefault('sources', []).append(dict(kind=kind, difficulty=difficulty, boss=boss, report=report))
            self.source_pools[key] = parties_for_target(report, options,
                                                allow_local_trials=self.options['allow_local_trials'])
            self.save()
        return self.source_pools[key]

    def normal_first_clear(self, difficulty, detail, cost):
        if not self.options['first_clear']:
            raise SubjugationBlocked('前哨尚未通关，已关闭首次通关')
        if self.report['stamina_spent']+cost > self.options['max_stamina']:
            raise SubjugationBlocked('前哨体力消费达到本次上限')
        failures = self.state.setdefault('failed_outpost_teams', {})
        if failures.get('day') != self.day() or failures.get('version') != 2:
            failures.clear()
            failures.update(day=self.day(), version=2, difficulties={})
        failed = set(failures['difficulties'].get(difficulty, []))
        def reopen():
            return self.open_formation(self.normal_detail(difficulty))
        for trial in range(self.options['max_normal_trials']):
            before = self.enter()
            plan = dict(kind='outpost_battle', difficulty=difficulty, quantity=1, stamina_cost=cost,
                        attempts=field.attempts(before), tickets_before=field.tickets(self.ui, before))
            reopen()
            self.report_progress('前哨'+difficulty+'首通 · 核验适用攻略队伍')
            party, order = self.choose_normal_party(difficulty, reopen, failed)
            prior = len(self.report['history'])
            self.report_progress('前哨'+difficulty+' · 首通实战')
            result = self.battle(party, order, plan)
            if len(self.report['history']) > prior:
                detail, _ = self.ensure_stamina(difficulty, self.normal_detail(difficulty))
                if field.sweep_enabled(detail) is not True:
                    raise SubjugationBlocked('前哨首通后扫荡未解锁；未重复战斗')
                return detail
            if result.outcome != 'failed':
                raise SubjugationBlocked('前哨未通过，结算不是已核实失败；未追加试打')
            # Reconciliation must have confirmed unchanged attempts and tickets.
            if self.state.get('pending'):
                raise SubjugationBlocked('前哨失败资源尚未核对；未追加试打')
            failed.add(party_fingerprint(party))
            failures['difficulties'][difficulty] = sorted(failed)
            self.report.setdefault('normal_trials', []).append(dict(difficulty=difficulty,
                party=party.name, outcome='failed', resources_unchanged=True))
            self.save()
        raise SubjugationBlocked('前哨达到本次候选试打上限；未训练角色或追加消费')

    def adjust_quantity(self, detail, wanted, *, boss=False):
        for _ in range(100):
            quantity = field.quantity(detail)
            if quantity is None or not 1 <= quantity <= 99:
                raise SubjugationBlocked('扫荡数量未知')
            if quantity == wanted:
                return detail
            self.ui.click((880 if boss else 831, 377) if quantity < wanted else (630 if boss else 676, 377))
            detail = self.capture()
            if not (field.boss_detail(detail) if boss else field.outpost_detail(detail)):
                raise SubjugationBlocked('调整数量时关卡发生变化')
        raise SubjugationBlocked('扫荡数量调整达到上限')

    def submit_sweep(self, detail, plan):
        preview_evidence = str(self.ui.save('sweep_detail_'+str(len(self.report['history'])), detail))
        self.ui.click(field.sweep_button(detail))
        confirmation = self.wait(field.sweep_confirmation, '扫荡确认')
        confirmation_evidence = str(self.ui.save('sweep_confirmation_'+str(len(self.report['history'])), confirmation))
        if field.sweep_cost(self.ui, confirmation, '消耗券') != plan['quantity']:
            raise SubjugationBlocked('扫荡最终确认次数不符；未确认消费')
        if plan['kind'] == 'outpost_sweep' and field.sweep_cost(self.ui, confirmation, '消耗体力') != plan['stamina_cost']:
            raise SubjugationBlocked('扫荡最终体力消费不符；未确认消费')
        if plan['kind'] == 'boss_sweep' and field.sweep_cost(self.ui, confirmation, '消耗讨伐委托证') != plan['quantity']:
            raise SubjugationBlocked('扫荡最终讨伐委托证消费不符；未确认消费')
        button = confirmation.find('确认', (520, 340, 665, 405), exact=True)
        if not confirmation.blue_button(button):
            raise SubjugationBlocked('扫荡最终确认按钮未知或不可用')
        self.commit(dict(plan, detail_evidence=preview_evidence,
            confirmation=confirmation_evidence))
        self.check_deadline()
        self.ui.click(button)
        receipt = self.wait(field.sweep_receipt, '扫荡结果')
        self.state['pending']['receipt'] = str(self.ui.save('sweep_receipt_'+str(len(self.report['history'])), receipt))
        self.save()
        self.reconcile()

    def outposts(self):
        for difficulty in field.DIFFICULTIES:
            self.report_progress('前哨'+difficulty+' · 首通后消耗剩余次数')
            before = self.enter()
            counts, tickets = field.attempts(before), field.tickets(self.ui, before)
            if counts[difficulty] == 0:
                continue
            detail = self.normal_detail(difficulty, home=before)
            detail, unit_cost = self.ensure_stamina(difficulty, detail)
            if field.sweep_enabled(detail) is False:
                self.normal_first_clear(difficulty, detail, unit_cost)
                before = self.enter()
                counts, tickets = field.attempts(before), field.tickets(self.ui, before)
                detail = self.normal_detail(difficulty, home=before)
                detail, unit_cost = self.ensure_stamina(difficulty, detail)
            if field.sweep_enabled(detail) is not True:
                raise SubjugationBlocked('前哨通关/扫荡状态未知')
            if field.detail_attempts(detail) != counts[difficulty]:
                raise SubjugationBlocked('前哨详情与首页剩余次数不符；未提交扫荡')
            preview = field.stamina_preview(self.ui, detail)
            quantity = min(counts[difficulty], (self.options['max_stamina']-self.report['stamina_spent'])//unit_cost,
                           preview[0]//unit_cost)
            if quantity <= 0:
                raise SubjugationBlocked('前哨现有体力或本次体力上限不足')
            detail = self.adjust_quantity(detail, quantity)
            preview = field.stamina_preview(self.ui, detail)
            if preview is None or preview[0]-preview[1] != quantity*unit_cost:
                raise SubjugationBlocked('扫荡体力预览与次数不符')
            self.submit_sweep(detail, dict(kind='outpost_sweep', difficulty=difficulty, quantity=quantity,
                stamina_cost=quantity*unit_cost, attempts=counts, tickets_before=tickets))
            if quantity != counts[difficulty]:
                raise SubjugationBlocked('前哨仍有次数，现有体力或本次上限不足')

    def boss_trial_readiness(self, party, reference, result):
        retry = self.last_result['retry']
        if result.outcome != 'settled':
            return dict(accepted=False, reason=result.reason or '模拟战未正常结算')
        if retry['action'] in ('change_survival', 'retry_once'):
            return dict(accepted=False, reason='模拟战出现持续减员，需按深域判断重试或换队')
        if self.last_result.get('win'):
            return dict(accepted=True, reason='免费模拟已击杀')
        source = party.damage_reference
        expected = source.get('damage')
        if (type(expected) is not int or expected <= 0 or not source.get('evidence')
                or source.get('scope', {}).get('boss') != reference['boss']):
            return dict(accepted=False, reason='非击杀模拟缺少本首领攻略的参考伤害或刀数，未仅凭正数伤害实战')
        expected = min(expected, reference['health'][1])
        samples = self.last_result['samples']
        timed_alive = (len(samples) >= 3 and min(s['seconds'] for s in samples) <= 8
                       and all(s.get('living_portraits') == 5 for s in samples[-3:]))
        met = meets_reference(self.last_result.get('damage'), expected, reference['health'][1], False)
        return dict(accepted=timed_alive and met, expected_damage=expected,
                    source_reference=source,
                    reason=('存活至时限并达到攻略参考伤害' if timed_alive and met else
                            '模拟伤害未达到攻略参考值' if not met else '未确认队伍存活至时限'))

    def simulate_boss(self, index, difficulty, reference):
        if not self.options['first_clear']:
            raise SubjugationBlocked('首领尚未通关，已关闭首次通关')
        if self.options['allow_local_trials']:
            detail = self.boss_detail(index, difficulty, simulation=True)
            target = field.boss_signature(self.ui, detail)
            for _ in range(6):
                if target:
                    break
                time.sleep(.3)
                detail = self.capture()
                target = field.boss_signature(self.ui, detail)
            # Keep an unsuccessful observation for diagnosis as well; absence
            # of this proof must never become permission to guess a target.
            evidence = str(self.ui.save(f'source_target_{index}_{difficulty}', detail))
            if (target and target['boss'] == reference['boss']
                    and target['maximum_hp'] == reference['health'][1]):
                target.update(scope=dict(kind='boss', difficulty=difficulty, boss=target['boss']),
                              image=evidence)
                if not hasattr(self, 'source_targets'):
                    self.source_targets = {}
                self.source_targets[('boss', difficulty, reference['boss'])] = target
        def reopen():
            return self.open_formation(self.boss_detail(index, difficulty, simulation=True))
        candidates = self.guide_candidates('boss', difficulty, reopen, reference['boss'], index+1)
        failed = self.failed_boss_teams.setdefault((index, difficulty), set())
        attempts = {}
        retry_party = None
        while True:
            retrying = retry_party is not None
            if retrying:
                party, retry_party = retry_party, None
                candidate_name = party.name
            else:
                candidate = next(candidates, None)
                if candidate is None:
                    break
                candidate_name = candidate.party.name
            if self.simulation_count >= self.options['max_simulations']:
                raise SubjugationBlocked('模拟战达到本次上限；未使用未经验证的队伍实战')
            reopen()
            try:
                if retrying:
                    party, order = self.select_verified_party(party, reopen)
                else:
                    party, order = guide_party(self, candidate.party, reopen,
                                              allow_substitutions=candidate.allow_substitutions)
                signature = party_fingerprint(party)
                if signature in failed and not retrying:
                    raise EventUIError('已失败的五人队伍不重复模拟')
            except EventUIError as error:
                self.report.setdefault('candidate_rejections', []).append(dict(
                    kind='boss', index=index, difficulty=difficulty,
                    candidate=candidate_name, reason=str(error)))
                continue
            self.simulation_count += 1
            attempts[signature] = attempts.get(signature, 0)+1
            self.report_progress('首领'+difficulty+' · 模拟战')
            self._expected_battle_hp = reference['health'][1]
            result = self.battle(party, order)
            self.last_result['retry'] = retry_decision(self._battle_samples, result.reason, attempts[signature])
            actual = self.boss_detail(index, difficulty)
            if (actual is None or field.boss_name(actual) != reference['boss']
                    or field.boss_health(self.ui, actual) != tuple(reference['health'])
                    or field.tickets(self.ui, actual) != reference['tickets_before']):
                raise SubjugationBlocked('模拟战后实战首领进度或券余额变化')
            record = dict(index=index, difficulty=difficulty, party=party.name, source=party.source, outcome=result.outcome,
                          result=self.last_result, build_basis=party.build_basis, assumptions=party.assumptions)
            record['readiness'] = self.boss_trial_readiness(party, reference, result)
            self.report['simulations'].append(record)
            self.save()
            if record['readiness']['accepted']:
                self.simulated_loadout = self.last_result['preparation']
                return party, order
            failed.add(signature)
            retry = self.last_result['retry']
            if retry['action'] == 'retry_once' and attempts[signature] < 2:
                retry_party = party
        raise BossPartyUnavailable('没有通过本期首领攻略核验及模拟的队伍；未追加实战消费')

    def bosses(self):
        for difficulty in field.BOSS_DIFFICULTIES:
            for index in range(3):
                self.report_progress(f'首领{index+1} · {difficulty}首通核对')
                try:
                    self.clear_boss(index, difficulty)
                except BossPartyUnavailable as error:
                    # Independent bosses can still progress when this guide
                    # pool is exhausted. Never continue uncertain consumption
                    # or navigation/combat failures through this path.
                    if self.state.get('pending'):
                        raise
                    self.report['pending'].append(f'首领{index+1} {difficulty}：{error}')
                    self.save()
                s = self.enter()
                if field.tickets(self.ui, s) == 0:
                    self.report['all_bosses_cleared'] = all(self.report['bosses'].get(str(i)+':'+d, {}).get('cleared') is True
                                                         for i in range(3) for d in field.BOSS_DIFFICULTIES)
                    return
        if not all(self.report['bosses'].get(str(i)+':'+d, {}).get('cleared') is True for i in range(3) for d in field.BOSS_DIFFICULTIES):
            raise SubjugationBlocked('仍有未通关首领；不以最高难度扫荡替代首通')
        self.report['all_bosses_cleared'] = True
        while True:
            detail = self.boss_detail(0, field.BOSS_DIFFICULTIES[-1])
            tickets = field.tickets(self.ui, detail)
            if tickets == 0:
                return
            if tickets is None or self.boss_cleared(detail, 0, field.BOSS_DIFFICULTIES[-1]) is not True or field.sweep_enabled(detail) is not True:
                raise SubjugationBlocked('最高难度首领扫荡条件未知')
            quantity = min(tickets, 99, self.options['max_boss_tickets']-self.report['tickets_spent'])
            if quantity <= 0:
                raise SubjugationBlocked('首领消费达到本次上限')
            detail = self.adjust_quantity(detail, quantity, boss=True)
            self.submit_sweep(detail, dict(kind='boss_sweep', index=0, difficulty=field.BOSS_DIFFICULTIES[-1],
                quantity=quantity, tickets_before=tickets, boss=field.boss_name(detail), health=field.boss_health(self.ui, detail)))

    def record_boss_clear(self, detail, index, difficulty):
        health, name = field.boss_health(self.ui, detail), field.boss_name(detail)
        if health is None or name is None:
            raise SubjugationBlocked('首领通关证据缺少身份或生命值')
        self.state.setdefault('boss_clears', {})[str(index)+':'+difficulty] = dict(name=name, maximum=health[1])

    def boss_cleared(self, detail, index, difficulty):
        key = str(index)+':'+difficulty
        raw = field.cleared_boss(self.ui, detail)
        health, name = field.boss_health(self.ui, detail), field.boss_name(detail)
        recorded = self.state.get('boss_clears', {}).get(key)
        known = recorded and health is not None and recorded == dict(name=name, maximum=health[1])
        unlocked = self.boss_unlocks.get(key)
        if (known and (raw is False or unlocked is False)) or (raw is False and unlocked is True):
            raise SubjugationBlocked('首领首通记录与当前页面冲突；未消费或重置进度')
        if raw is True or unlocked is True or known or (health is not None and health[0] == 0):
            self.record_boss_clear(detail, index, difficulty)
            return True
        return raw

    def clear_boss(self, index, difficulty):
        party = None
        reference = None
        key = str(index)+':'+difficulty
        while True:
            self.check_deadline()
            detail = self.boss_detail(index, difficulty)
            if detail is None:
                self.report['bosses'][key] = dict(cleared=False, locked=True)
                return
            cleared = self.boss_cleared(detail, index, difficulty)
            tickets = field.tickets(self.ui, detail)
            if cleared is None and tickets == 0:
                self.report['bosses'][key] = dict(name=field.boss_name(detail), cleared=None, health=field.boss_health(self.ui, detail))
                return
            if cleared is None:
                raise SubjugationBlocked('首领通关标记/历史扫荡伤害未知')
            self.report['bosses'][key] = dict(name=field.boss_name(detail), cleared=cleared,
                                            health=field.boss_health(self.ui, detail))
            if cleared:
                return
            tickets = field.tickets(self.ui, detail)
            if tickets is None:
                raise SubjugationBlocked('首领实战券余额未知')
            if tickets == 0:
                return
            if self.report['tickets_spent'] >= self.options['max_boss_tickets']:
                raise SubjugationBlocked('首领消费达到本次上限')
            plan = dict(kind='boss_battle', index=index, difficulty=difficulty, quantity=1,
                        tickets_before=tickets, boss=field.boss_name(detail), health=field.boss_health(self.ui, detail))
            if party is None:
                party, _ = self.simulate_boss(index, difficulty, plan)
                reference = (plan['boss'], plan['health'][1])
                simulated_damage = self.last_result.get('damage') or plan['health'][0]
            elif reference != (plan['boss'], plan['health'][1]):
                raise SubjugationBlocked('接续首领的身份或最大生命值变化')
            detail = self.boss_detail(index, difficulty)
            if field.boss_health(self.ui, detail) != tuple(plan['health']) or field.tickets(self.ui, detail) != tickets:
                raise SubjugationBlocked('实战前首领或券余额变化')
            self.open_formation(detail)
            party, order = self.select_verified_party(party,
                lambda: self.open_formation(self.boss_detail(index, difficulty)))
            prior = len(self.report['history'])
            self.report_progress(f'首领{index+1} · {difficulty}实战')
            result = self.battle(party, order, plan)
            if len(self.report['history']) == prior:
                raise SubjugationBlocked('实战未产生已核对进度；不重复使用同一队伍消费')
            defeated = self.report['bosses'][key]['cleared'] is True
            expected = min(party.damage_reference.get('damage') or simulated_damage, plan['health'][0])
            # Like dungeon attempts, use reconciled before/after HP for real
            # damage; a result OCR miss must not discard verified progress.
            actual_damage = plan['health'][0]-self.report['bosses'][key]['health'][0] if not defeated else plan['health'][0]
            if (not defeated and (self.last_result['retry']['action'] in ('change_survival', 'retry_once')
                    or not meets_reference(actual_damage, expected, plan['health'][0], False))):
                self.failed_boss_teams.setdefault((index, difficulty), set()).add(party_fingerprint(party))
                self.report.setdefault('real_rejections', []).append(dict(index=index, difficulty=difficulty,
                    expected_damage=expected, actual_damage=actual_damage, result=dict(self.last_result), reason='实战减员或伤害低于模拟/攻略，先换队重新模拟'))
                self.save()
                party = None

    def run(self, event: Event | None = None):
        try:
            if event is None:
                from ..news import fetch_event_news
                event = fetch_event_news().abyssSubjugation
            if not self.event_active(event):
                self.report['status'] = 'unavailable'
                return self.report
            if not event.extras.get('abyss_id') or not event.extras.get('boss_ticket_id'):
                raise SubjugationBlocked('活动编号或讨伐委托证身份未知')
            self.event = event
            self.report['event'] = dict(id=event.extras['abyss_id'], title=event.extras.get('title'),
                                       start=event.startTimestamp, end=event.endTimestamp)
            account = self.options.get('account_key', getattr(self.driver, 'device_name', getattr(self.driver, 'index', 'default')))
            key = sha256((str(account)+'|'+str(event.extras['abyss_id'])).encode()).hexdigest()[:24]
            self.state_path = Path(self.options.get('state_dir', 'cache/daily/abyss_subjugation_state'))/(key+'.json')
            self.state = read_json(self.state_path) or {}
            if self.state.get('clear_proof_version') != 1:
                # Earlier blue-border hints can misread a disabled boss
                # sweep. Rebuild clear proofs from live pages; keep pending
                # consumption and party audits for normal recovery.
                self.state.pop('boss_clears', None)
                self.state['clear_proof_version'] = 1
            s = self.enter()
            if s is None:
                self.report['status'] = 'unavailable'
                return self.report
            self.ui.save('event_home_before', s)
            self.reconcile()
            # Account snapshots from old runs are not guide evidence. Public
            # source caches remain reusable after normal source validation.
            self.state.pop('normal_party', None)
            if self.options['preview_only']:
                self.report['status'] = 'preview'
                return self.report
            try:
                self.outposts()
            except EventUIError as error:
                if self.state.get('pending'):
                    raise
                self.report['pending'].append(str(error))
                self.log('前哨未完成：'+str(error))
                self.save()
            self.bosses()
            s = self.enter()
            self.report['status'] = 'complete' if not any(field.attempts(s).values()) and field.tickets(self.ui, s) == 0 else 'partial'
            self.ui.save('event_home_after', s)
            return self.report
        except (RunCancelled, ResumeUnsafe):
            self.report['status'] = 'cancelled'
            raise
        except EventUIError as error:
            self.report['status'] = 'partial' if self.report['history'] else 'blocked'
            self.report['pending'].append(str(error))
            self.ui.save('blocked')
            return self.report
        except Exception:
            self.report['status'] = 'error'
            raise
        finally:
            self.save()
