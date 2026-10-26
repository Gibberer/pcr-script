"""CN collaboration raid: free first clears, existing-ticket sweeps and rewards."""
from hashlib import sha256
import json
from pathlib import Path

from .base import BaseTask
from .registry import register
from .options import validated_options
from .collaboration_strategy import (CollaborationFormation, TITLE, BOSS,
                                     DIFFICULTIES, source_options, parties_for_difficulty)
from .event_battle import EventCombat
from .strategy_inputs import validate_urls
from ..game_ui import collaboration_raid as field
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import atomic_json, checkpoint, RunCancelled, ResumeUnsafe, clock as time


class NoUsableParty(EventUIError):
    pass


def validate_options(options):
    value = validated_options(options, 'CollaborationRaid',
        integers=(('timeout', 5400, 14400), ('battle_timeout', 240, 600),
                  ('max_battles', 6, 30), ('max_tickets', 99, 999), ('max_exchange_batches', 200, 200)),
        flags=(('first_clear', True), ('claim_rewards', True), ('exchange', True),
               ('discover_sources', True), ('allow_local_trials', True), ('auto_equip', False)))
    value['source_urls'] = validate_urls(value.get('source_urls', []))
    if not isinstance(value.setdefault('sources', {}), dict):
        raise ValueError('CollaborationRaid.sources必须为对象')
    if 'account_key' in value and (not isinstance(value['account_key'], str) or not value['account_key'].strip()):
        raise ValueError('CollaborationRaid.account_key必须是非空字符串')
    return value


@register('collaboration_raid')
class CollaborationRaid(BaseTask):
    config_section = 'CollaborationRaid'

    @classmethod
    def prepare(cls, config):
        validate_options(config.get(cls.config_section, {}))
        return (), {}, None

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/collaboration_raid'))
        self.formation = CollaborationFormation(self.ui)
        self.combat = EventCombat(self)
        self.deadline = time.monotonic()+self.options['timeout']
        self.period = None
        self.state_path = None
        self.state = {}
        account = self.options.get('account_key', getattr(self.driver, 'device_name', getattr(self.driver, 'index', 'default')))
        cancellation_key = sha256(str((account, TITLE, 'exchange_cancellation')).encode()).hexdigest()[:24]
        self.cancellation_path = Path(self.options.get('state_dir', 'cache/daily/collaboration_raid_state'))/(cancellation_key+'.json')
        self.sources = None
        self.excluded_sources = set()
        self.report = dict(status='running', battles=0, spent=0, history=[], audits=[], pending=[])

    def save(self):
        if self.state_path is not None:
            atomic_json(self.state_path, self.state)
        atomic_json(self.ui.output/'report.json', self.report)

    def check_deadline(self):
        checkpoint()
        if time.monotonic() >= self.deadline:
            raise EventUIError('联动讨伐达到运行时限')
        if self.period and not self.period[0] <= time.time() <= self.period[1]:
            raise EventUIError('联动讨伐已不在核实的开放期间')

    def capture(self):
        self.check_deadline()
        s = self.ui.capture()
        if (not field.home(s) and field.confident(s, '讨伐券', (650, 410, 750, 450))
                and field.confident(s, '挑战', (650, 360, 840, 420))
                and field.confident(s, '全体报酬', (560, 375, 640, 420))):
            local = self.ui.read_region(s, (55, 15, 280, 85))
            title = field.confident(local, TITLE+'[!！]?', (55, 15, 280, 85))
            if title:
                s.items = [item for item in s.items if not (55 <= item.center[0] <= 280
                           and 15 <= item.center[1] <= 85)] + [title]
        if field.detail(s) and not field.difficulty_menu(s) and field.difficulty(s) is None:
            local = self.ui.read_region(s, (175, 25, 295, 65))
            labels = [field.confident(local, name, (175, 25, 295, 65)) for name in DIFFICULTIES]
            labels = [label for label in labels if label is not None]
            if len(labels) == 1:
                s.items = [item for item in s.items if not (175 <= item.center[0] <= 295
                           and 25 <= item.center[1] <= 65 and normalized(item.text) in DIFFICULTIES)]
                s.items.extend(labels)
        return s

    def wait(self, predicate, description, timeout=30):
        until = time.monotonic()+timeout
        while time.monotonic() < until:
            s = self.capture()
            if predicate(s):
                return s
            time.sleep(.4)
        raise EventUIError(description+'未确认；未重复提交')

    def click(self, s, text, roi):
        button = field.confident(s, text, roi)
        if button is None:
            raise EventUIError('联动按钮未核实：'+text)
        self.check_deadline()
        self.ui.click(button)

    def log(self, message):
        print('[联动讨伐] '+message, flush=True)

    def story_dialog(self, s):
        from .task_story_event import CampaignClean
        return CampaignClean.story_dialog(self, s)

    def combat_return(self, s):
        return field.home(s) or field.detail(s)

    def combat_pre_dialog(self, s):
        if field.confident(s, '获得活动登录奖励', (300, 115, 660, 175)):
            # The daily ticket receipt can cover an already rendered home.
            # Wait for its body/button instead of navigating through the veil.
            close = field.confident(s, '关闭', (370, 340, 590, 405))
            if (close and field.confident(s, '已领取以下道具作为登录奖励[。.]?',
                                          (300, 170, 680, 210))):
                self.ui.save('daily_login_reward', s)
                self.ui.click(close)
            else:
                time.sleep(.5)
            return True
        if s.find('获得的报酬将会直接增加到持有道具中', (250, 350, 800, 420)):
            # The receipt closes with 取消 (more left) or a lone 确认; wait
            # while its buttons fade in.
            button = field.exchange_receipt_close(s)
            if button is None:
                time.sleep(.5)
                return True
            self.exchange_evidence('exchange_receipt', s)
            self.ui.click(button)
            return True
        item_result = field.confident(s, '查看已获得道具', (300, 390, 680, 465))
        if item_result and field.confident(s, '报酬交换', (50, 0, 245, 65)):
            self.exchange_evidence('exchange_jackpot', s)
            self.ui.click(item_result)
            return True
        if (field.confident(s, '当前的列表', (300, 15, 660, 65))
                and field.confident(s, r'剩余0/\d+', (590, 95, 700, 140))
                and field.confident(s, r'剩余0/\d+', (590, 195, 700, 235))):
            self.ui.save('exchange_pool_empty', s)
            self.click(s, '重置', (370, 445, 590, 510))
            return True
        if (field.confident(s, r'已获得第\d+轮报酬列表中的全部报酬[。.]?', (280, 260, 700, 305))
                and field.confident(s, '切换到下一个报酬列表[。.]?', (280, 300, 700, 335))):
            self.exchange_evidence('exchange_pool_complete', s)
            self.click(s, '确认', (370, 340, 590, 400))
            return True
        if (field.confident(s, '重置完毕', (300, 115, 660, 175))
                and field.confident(s, '重置了报酬列表[。.]?', (300, 225, 660, 285))):
            self.exchange_evidence('exchange_pool_reset', s)
            self.click(s, '确认', (370, 340, 590, 400))
            return True
        if (field.confident(s, r'获得了宝石[×xX]\d+', (300, 330, 700, 405))
                and field.confident(s, '挑战', (650, 360, 840, 425))
                and field.gem_reward(s) is None):
            local = self.ui.read_region(s, (450, 270, 575, 320))
            s.items = [item for item in s.items if not (450 <= item.center[0] <= 575
                       and 270 <= item.center[1] <= 320)] + local.items
        if (field.confident(s, r'获得了佐贺偶像是传奇联动纪念10次扭蛋券[×xX]\d+', (280, 335, 700, 425))
                and field.collective_reward(s) is None):
            for roi in ((300, 270, 375, 320), (495, 270, 570, 320), (670, 270, 765, 320)):
                local = self.ui.read_region(s, roi, classify=False)
                x1, y1, x2, y2 = roi
                s.items = [item for item in s.items if not (x1 <= item.center[0] <= x2
                           and y1 <= item.center[1] <= y2)] + local.items
        body = field.gem_reward(s) or field.collective_reward(s)
        if body is None:
            return False
        rows = self.report.setdefault('automatic_rewards', [])
        rows.append(dict(text=body.text, evidence=str(self.ui.save('automatic_reward_'+str(len(rows)), s))))
        self.save()
        self.ui.click(body)
        self.wait(lambda f: field.gem_reward(f) is None and field.collective_reward(f) is None,
                  '自动奖励展示结束', timeout=8)
        return True

    def exchange_evidence(self, name, s):
        # Pool completion and reset follow only a submitted exchange; the
        # balance must still match before the pending record is released.
        self._exchange_receipt = str(self.ui.save(name, s))
        if self.state.get('pending_exchange'):
            self.state['pending_exchange']['receipt'] = self._exchange_receipt
            self.save()

    def cancel_exchange_confirmation(self, s, confirmation):
        self._cancelled_exchange_confirmation = dict(
            quantity=confirmation['quantity'], observed_at=time.time(),
            evidence=str(self.ui.save('exchange_cancelled_confirmation', s)))
        atomic_json(self.cancellation_path, self._cancelled_exchange_confirmation)
        self.click(s, '取消', (260, 400, 480, 465))
        return self.wait(field.exchange, '取消确认后返回兑换页')

    def combat_result_button(self, s):
        return field.confident(s, '前往联动讨伐|前往活动', (550, 420, 945, 525))

    def combat_starting(self, s):
        record = self.state.get('pending_battle')
        if not record or record.get('submitted') is not False:
            raise EventUIError('首通提交状态未知')
        record.update(submitted=True, dispatch=str(self.ui.save('battle_dispatch', s)))
        self.save()

    def combat_settings_confirmed(self, evidence):
        self.state['pending_battle'].update(settings_verified=True, settings_evidence=evidence)
        self.save()

    def enter(self):
        missing = 0
        requested = False
        for _ in range(60):
            s = self.capture()
            if field.confident(s, '一键交换确认', (300, 60, 660, 115)):
                confirmation = field.exchange_confirmation(self.ui, s)
                if confirmation is None:
                    s = self.wait(lambda f: field.exchange_confirmation(self.ui, f) is not None,
                                  '一键兑换确认数量与重置数', timeout=10)
                    confirmation = field.exchange_confirmation(self.ui, s)
                # A visible, unsubmitted confirmation may be cancelled safely.
                # Its quantity and unchanged balance must match the saved plan
                # before that plan is released during initialization.
                self.cancel_exchange_confirmation(s, confirmation)
                self.ui.click((30, 30))
                requested = True
                continue
            if self.combat_pre_dialog(s):
                requested = True
                continue
            if field.skip_confirmation(s) and not self.state.get('pending_spend'):
                self.click(s, '取消', (260, 340, 480, 405))
                continue
            if (field.confident(s, '收取报酬', (300, 0, 700, 100))
                    and s.find('获得了以下报酬[。.]?|收取了以下道具', (250, 55, 730, 105), exact=True)):
                self._claim_receipt = str(self.ui.save('recovered_mission_receipt', s))
                self.click(s, '关闭', (300, 425, 660, 525))
                continue
            if self.skip_receipt(s):
                # Closing a result spends nothing; reconciliation still
                # requires the ticket balance to match the recorded plan.
                self._sweep_receipts = getattr(self, '_sweep_receipts', [])
                self._sweep_receipts.append(str(self.ui.save('recovered_sweep_receipt_'+str(len(self._sweep_receipts)), s)))
                self.click(s, '关闭|确认|下一步|跳过完毕', (250, 335, 945, 525))
                continue
            if s.find('扫荡券确认|跳过确认|扫荡结果|收取报酬|交换结果', (250, 0, 750, 210)):
                raise EventUIError('存在未归属或未核账的消费/领奖页面；保留现场')
            if field.home(s):
                return s
            if field.unlock_dialog(s):
                self.ui.save('difficulty_unlocked', s)
                self.ui.click(field.unlock_dialog(s))
                requested = True
            elif field.tutorial(s):
                self.ui.click((779, 488))
                requested = True
            elif field.navigation_exit(s):
                self.ui.click(field.navigation_exit(s))
                requested = True
            elif field.formation(s):
                self.click(s, '取消', (590, 410, 790, 510))
                requested = True
            elif field.exchange_settings(s):
                self.click(s, '关闭', (370, 445, 590, 515))
                requested = True
            elif field.confident(s, '报酬交换', (50, 0, 245, 65)):
                self.ui.click((30, 30))
                requested = True
            elif field.confident(s, '冒险', (40, 0, 165, 65)):
                entry = field.confident(s, '联动讨伐', (260, 350, 460, 465))
                if entry and not requested:
                    # The decorative caption lies below the circular hit area.
                    self.ui.click((int(entry.center[0]), int(entry.center[1])-34))
                    requested = True
                elif not entry:
                    missing += 1
                    if missing >= 3:
                        return None
                    time.sleep(1)
                else:
                    time.sleep(.5)
            elif s.find('加载中|正在进行数据连接'):
                time.sleep(.5)
            elif requested:
                # The event can expose the persistent footer before its home
                # controls fade in. Do not send Adventure again during entry.
                time.sleep(.5)
            elif s.find(TITLE) and s.find('任务|讨伐券'):
                time.sleep(.5)
            elif field.confident(s, '冒险', (475, 475, 595, 540)):
                self.click(s, '冒险', (475, 475, 595, 540))
            else:
                raise EventUIError('联动讨伐遇到未识别的页面或回执；保留现场')
        raise EventUIError('联动讨伐入口加载超时')

    def open_missions(self, s):
        # A tap during the home fade-in can be swallowed. Opening the list
        # consumes nothing, so re-tap only while the event home is verified.
        for _ in range(3):
            self.click(s, '任务', (755, 0, 820, 65))
            try:
                return self.wait(field.missions, '联动任务列表', timeout=8)
            except EventUIError:
                s = self.capture()
                if field.missions(s):
                    return s
                if not field.home(s):
                    raise
        raise EventUIError('联动任务列表未确认；未重复提交')

    def initialize(self, s):
        missions = self.open_missions(s)
        self.period = field.period(missions)
        if self.period is None:
            raise EventUIError('活动完整开放时间未知')
        self.check_deadline()
        account = self.options.get('account_key', getattr(self.driver, 'device_name', getattr(self.driver, 'index', 'default')))
        key = sha256(str((account, TITLE, self.period)).encode()).hexdigest()[:24]
        self.state_path = Path(self.options.get('state_dir', 'cache/daily/collaboration_raid_state'))/(key+'.json')
        self.state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {}
        if not isinstance(self.state, dict):
            raise EventUIError('联动消费状态文件无效')
        if self.cancellation_path.exists() and self.state.get('pending_exchange'):
            cancelled = json.loads(self.cancellation_path.read_text(encoding='utf-8'))
            created = self.state['pending_exchange'].get('created_at', self.state_path.stat().st_mtime)
            if (isinstance(cancelled, dict) and type(cancelled.get('observed_at')) in (int, float)
                    and type(created) in (int, float) and cancelled['observed_at'] >= created):
                self._cancelled_exchange_confirmation = cancelled
        if self.state.get('pending_claim') and getattr(self, '_claim_receipt', None):
            self.state['pending_claim']['receipt'] = self._claim_receipt
        if self.state.get('pending_exchange') and getattr(self, '_exchange_receipt', None):
            self.state['pending_exchange']['receipt'] = self._exchange_receipt
        self.report.update(event=TITLE, period=self.period)
        self.click(missions, '取消', (265, 450, 470, 505))
        s = self.wait(field.home, '返回联动首页')
        return self.reconcile_pending(s, missions)

    def reconcile_pending(self, s, missions):
        current = self.balance(s)
        if plan := self.state.get('pending_battle'):
            target = plan.get('signature', {}).get('target', {})
            difficulty = target.get('difficulty')
            if difficulty not in DIFFICULTIES or type(plan.get('submitted')) is not bool:
                raise EventUIError('上次未核对的战斗记录无效')
            if plan['submitted'] is False:
                plan['outcome'] = 'cancelled_before_submission'
            else:
                detail = self.open_detail(difficulty)
                actual = field.target(detail)
                expected_balance = plan.get('tickets_before', plan.get('tickets_after'))
                if (not actual or any(actual[k] != target.get(k) for k in ('boss', 'level', 'maximum_hp'))
                        or field.cleared(self.ui, detail) is not True
                        or type(expected_balance) is not int or current != expected_balance):
                    raise EventUIError('上次未核对的首通或讨伐券状态仍未知；未重新开战')
                plan.update(cleared=True, recovered=True, evidence=str(self.ui.save('recovered_clear', detail)))
                self.state['preferred_roster'] = plan.get('signature', {}).get('members')
                s = self.enter()
            self.report['history'].append(plan)
            self.state.pop('pending_battle')
            self.save()
        if plan := self.state.get('pending_spend'):
            if not plan.get('receipts') and getattr(self, '_sweep_receipts', None):
                plan['receipts'] = list(self._sweep_receipts)
            if (plan.get('kind') != 'sweep' or type(plan.get('after')) is not int
                    or current != plan['after'] or not plan.get('receipts')):
                raise EventUIError('上次未核对的扫荡消费仍未知；未重新提交')
            self.report['history'].append(dict(plan, recovered=True))
            self.state.pop('pending_spend')
            self.save()
        if plan := self.state.get('pending_claim'):
            button = field.confident(missions, '全部收取', (490, 450, 700, 505))
            if not plan.get('receipt') or missions.blue_button(button):
                raise EventUIError('上次未核对的奖励仍未知；未重新领取')
            self.state.pop('pending_claim')
            self.report['missions'] = 'recovered_claim'
            self.save()
        if plan := self.state.get('pending_exchange'):
            page = self.open_exchange()
            cancelled = getattr(self, '_cancelled_exchange_confirmation', {})
            if (cancelled.get('quantity') == plan.get('quantity') and not plan.get('receipt')
                    and not plan.get('final_submitted')
                    and type(plan.get('before')) is int and type(plan.get('after')) is int
                    and plan['before']-plan['after'] == plan['quantity']
                    and field.exchange_balance(self.ui, page) == plan.get('before')):
                self.report['history'].append(dict(plan, outcome='cancelled_before_submission',
                                                   confirmation=cancelled['evidence']))
                self.state.pop('pending_exchange')
                self.save()
                atomic_json(self.cancellation_path, {})
                if any(k.startswith('pending_') for k in self.state):
                    raise EventUIError('有上次未核对的联动操作，未追加消费')
                self.ui.click((30, 30))
                return self.wait(field.home, '未提交兑换取消后返回活动')
            if plan.get('receipt') and field.exchange_balance(self.ui, page) != plan.get('after'):
                page = self.wait(lambda f: field.exchange_balance(self.ui, f) == plan.get('after'),
                                 '兑换后余额刷新', timeout=10)
            if (type(plan.get('after')) is not int or not plan.get('receipt')
                    or field.exchange_balance(self.ui, page) != plan['after']):
                raise EventUIError('上次奖励券兑换仍未核对；未重复兑换')
            self.report.setdefault('exchanges', []).append(dict(plan, recovered=True))
            self.state.pop('pending_exchange')
            self.save()
            self.ui.click((30, 30))
            s = self.wait(field.home, '兑换核对后返回活动')
        if any(k.startswith('pending_') for k in self.state):
            raise EventUIError('有上次未核对的联动操作，未追加消费')
        return s

    def skip_receipt(self, s):
        from ..game_ui import abyss_subjugation as sweep_ui
        return sweep_ui.sweep_receipt(s) or field.skip_result(s) is not None

    def balance(self, s):
        value = field.tickets(self.ui, s)
        if value is None:
            raise EventUIError('讨伐券余额未知')
        return value

    def open_detail(self, difficulty=None):
        s = self.enter()
        if s is None:
            raise EventUIError('活动入口已不可用')
        self.click(s, '挑战', (650, 360, 840, 420))
        s = self.wait(field.detail, '联动首领详情')
        if difficulty is None or field.difficulty(s) == difficulty:
            return s
        button = field.confident(s, '难度变更', (150, 15, 430, 85))
        if button is None:
            raise EventUIError('当前难度尚不能变更，须先完成已解锁首通')
        self.ui.click(button)
        s = self.wait(field.difficulty_menu, '难度选择')
        self.ui.click({'普通': (279, 229), '困难': (499, 229), '高难': (279, 300)}[difficulty])
        s = self.wait(lambda f: field.selected_difficulty(f, difficulty), '所选难度或解锁状态', timeout=8)
        self.click(s, '确认', (480, 340, 700, 400))
        return self.wait(lambda f: field.detail(f) and field.difficulty(f) == difficulty, '目标难度')

    def acquire(self, difficulty, target):
        from .strategy_video import acquire_strategies
        if self.sources is None:
            self.report_progress('联动讨伐 · 搜索并解析本期攻略')
            self.sources = acquire_strategies(source_options(self.options, self.period), check=self.check_deadline,
                exclude_sources=self.excluded_sources,
                accept=lambda r: bool(parties_for_difficulty(r, difficulty,
                    target=target, allow_local_trials=self.options['allow_local_trials'])))
            path = self.ui.output/('sources.json' if not self.excluded_sources else 'sources_'+str(len(self.excluded_sources))+'.json')
            atomic_json(path, self.sources)
            self.report['sources'] = dict(path=str(path), status=self.sources.get('status'),
                parties=len(self.sources.get('parties', [])),
                errors=self.sources.get('errors', []), pending=self.sources.get('pending', []))
            self.save()
        parties = parties_for_difficulty(self.sources, difficulty,
                                        target=target, allow_local_trials=self.options['allow_local_trials'])
        preferred = self.state.get('preferred_roster')
        return sorted(parties, key=lambda p: [m.name for m in p.members] != preferred)

    def select_party(self, difficulty, party):
        from ..game_ui.avatar_assets import ensure_avatar_index
        from .party_preparation import prepare_character_database, numeric_equipment_unknown, read_numeric_equipment
        from .task_home import ToHomePage
        from ..game_ui.character_equipment import inspect_unreleased_equipment
        self.formation.avatars, _ = ensure_avatar_index(self.options['sources'].get('avatars'), check=self.check_deadline)
        prepare_character_database(self.formation, self.options['sources'].get('avatars'), check=self.check_deadline)
        ready, audit = self.formation.select(party)
        unknown = [m.name for m in party.members
                   if (a := self.formation.observed.get(normalized(m.name))) and a.identity_verified
                   and a.unique is None and a.unique2 is None]
        numeric = [n for n in numeric_equipment_unknown(party, self.formation.observed)
                   if (a := self.formation.observed.get(normalized(n))) and a.identity_verified]
        identities_ready = all((a := self.formation.observed.get(normalized(m.name))) and a.identity_verified
                               for m in party.members)
        if not ready and identities_ready and (unknown or numeric):
            s = self.capture()
            self.click(s, '取消', (590, 410, 790, 510))
            ToHomePage(self.robot).run(timeout=60)
            for name in unknown:
                self.check_deadline()
                proof = inspect_unreleased_equipment(self.ui, name)
                if proof:
                    self.formation.unreleased[normalized(name)] = (time.time(), proof)
                ToHomePage(self.robot).run(timeout=60)
            for name in numeric:
                read_numeric_equipment(self.formation, name)
                ToHomePage(self.robot).run(timeout=60)
            s = self.open_detail(difficulty)
            if not field.first_clear_free(s):
                raise EventUIError('人物页返回后首通免费状态变化')
            self.click(s, '挑战', (765, 440, 925, 500))
            self.wait(field.formation, '重新编队')
            ready, audit = self.formation.select(party)
        self.report['audits'].append(dict(difficulty=difficulty, source=party.source, ready=ready, details=audit))
        self.save()
        return ready, audit

    def first_clear(self, s):
        # A parseable guide can still require heroes absent from this account.
        # Continue source discovery after exhausting its account audits.
        for _ in range(self.options['sources'].get('max_videos', 8)):
            try:
                return self.try_first_clear(s)
            except NoUsableParty:
                urls = {p.get('source') for p in self.sources.get('parties', []) if p.get('source')}
                if not urls-self.excluded_sources or not self.options['discover_sources']:
                    raise
                self.excluded_sources.update(urls)
                self.report.setdefault('unusable_sources', []).extend(sorted(urls))
                self.sources = None
                self.save()
                s = self.open_detail(field.difficulty(s))
        raise EventUIError('来源搜索达到上限，尚无可核验阵容')

    def try_first_clear(self, s):
        difficulty = field.difficulty(s)
        if difficulty is None or field.target(s) is None or not field.first_clear_free(s):
            raise EventUIError('首通目标或零讨伐券消费未确认')
        if not self.options['first_clear']:
            raise EventUIError(difficulty+'尚未首通；首通开关关闭')
        target = field.target(s)
        parties = self.acquire(difficulty, target)
        if not parties:
            raise EventUIError('没有通过本期身份、难度、五人及操作条件筛选的攻略')
        for party in parties:
            self.check_deadline()
            if self.report['battles'] >= self.options['max_battles']:
                raise EventUIError('达到本次首通战斗上限')
            signature = dict(target=target, source=party.source, members=[m.name for m in party.members])
            s = self.open_detail(difficulty)
            if field.target(s) != target or not field.first_clear_free(s):
                raise EventUIError('获取攻略后首通目标或免费条件变化')
            # The selected real-battle tab must retain the observed yellow fill.
            from ..game_ui.abyss_subjugation import yellow
            if not yellow(s, (820, 110, 910, 140)):
                self.click(s, '实战', (810, 105, 920, 145))
                s = self.capture()
                if not yellow(s, (820, 110, 910, 140)) or not field.first_clear_free(s):
                    raise EventUIError('实战首通零消耗状态未确认')
            self.click(s, '挑战', (765, 440, 925, 500))
            self.wait(field.formation, '联动编队')
            self.report_progress('联动讨伐 · '+difficulty+'阵容身份、培养与装备核验')
            ready, audit = self.select_party(difficulty, party)
            if not ready:
                self.enter()
                continue
            from ..game_ui.special_equipment import inspect_special_equipment, auto_equip_special
            special = inspect_special_equipment(self.ui, audit['order'])
            if special.get('unknown'):
                raise EventUIError('特别装备状态未知')
            if self.options['auto_equip']:
                special = auto_equip_special(self.ui, audit['order'])
                if special.get('unknown'):
                    raise EventUIError('分配现有特别装备后的状态未知')
            from .recollection_retry import trial_context, same_trial, same_roster
            audit['special_equipment'] = special
            scope = dict(area=TITLE, floor=DIFFICULTIES.index(difficulty)+1)
            context = trial_context(dict(target, scope=scope), party, audit,
                                    self.capture().number((505, 375, 590, 402)))
            prior = [row.get('context') for row in self.state.get('failed_trials', [])
                     if same_roster(row.get('context'), scope, audit['order'])]
            if prior and (context is None or any(same_trial(old, context) for old in prior)):
                self.enter()
                continue
            current = self.formation.inspect_current(full=False, expected_names=[m.name for m in party.members], verify_skills=False)
            if ([normalized(m.name) for m in current] != audit['order'] or not all(m.identity_verified for m in current)):
                raise EventUIError('即将开战的阵容与核验结果不符')
            record = dict(signature=signature, submitted=False, formation=audit, special=special, context=context,
                          tickets_before=self.report['remaining_tickets'])
            self.state['pending_battle'] = record
            self.report['battles'] += 1
            self.save()
            self.report_progress('联动讨伐 · '+difficulty+'免费首通战斗')
            result = self.combat.run(party, audit['order'])
            s = self.enter()
            if s is None:
                raise EventUIError('战后活动首页未确认')
            after = self.balance(s)
            s = self.open_detail(difficulty)
            cleared = field.cleared(self.ui, s) is True
            record.update(outcome=result.outcome, cleared=cleared, tickets_after=after,
                          evidence=str(self.ui.save('first_clear_after_'+difficulty, s)))
            self.save()
            # A receipt alone never proves a clear. The detail must expose
            # the unlocked sweep and the explicit free-first-clear text gone.
            if not cleared and not field.first_clear_free(s):
                raise EventUIError('首通结果未知；保留待核对记录')
            if after != self.report['remaining_tickets']:
                raise EventUIError('免费首通后讨伐券变化；未追加战斗')
            self.state.pop('pending_battle')
            self.report['history'].append(record)
            if not cleared and context is not None and record.get('settings_verified'):
                self.state.setdefault('failed_trials', []).append(dict(context=context, evidence=record['evidence']))
            self.save()
            if cleared:
                self.state['preferred_roster'] = signature['members']
                self.save()
                return s
        raise NoUsableParty(difficulty+'没有剩余可核验且未失败的来源阵容')

    def sweep(self, s):
        from ..game_ui import abyss_subjugation as sweep_ui
        if field.difficulty(s) != '高难' or field.cleared(self.ui, s) is not True:
            raise EventUIError('高难首通或跳过解锁状态未知')
        before = self.report['remaining_tickets']
        wanted = min(before, self.options['max_tickets']-self.report['spent'], 99)
        if wanted < 1:
            return
        for _ in range(200):
            amount = field.quantity(s)
            if amount is None or not 1 <= amount <= 999 or field.difficulty(s) != '高难':
                raise EventUIError('跳过数量或目标未知')
            if amount == wanted:
                break
            self.ui.click((835 if amount < wanted else 675, 405))
            s = self.wait(lambda f: field.detail(f) and field.quantity(f) != amount, '调整跳过数量', timeout=8)
        else:
            raise EventUIError('跳过数量调整达到上限')
        if field.ticket_preview(self.ui, s) != (before, before-wanted):
            raise EventUIError('详情讨伐券预览与预算不符')
        self.ui.save('sweep_detail', s)
        self.ui.click(field.sweep_button(s))
        confirmation = self.wait(lambda f: field.skip_confirmation(f) or sweep_ui.sweep_confirmation(f), '联动扫荡最终确认')
        if field.skip_confirmation(confirmation):
            valid = (self.ui.number(confirmation, (432, 252, 484, 285)) == wanted
                     and self.ui.number(confirmation, (660, 252, 705, 285)) == before
                     and self.ui.number(confirmation, (660, 308, 705, 340)) == wanted)
            if not valid:
                raise EventUIError('最终跳过确认的消费、持有数或击败次数不符')
        elif (sweep_ui.sweep_cost(self.ui, confirmation, '消耗讨伐券') != wanted
                or sweep_ui.sweep_cost(self.ui, confirmation, '消耗券') != wanted):
            raise EventUIError('最终确认中的讨伐券或扫荡券消费不符')
        button = field.confident(confirmation, '确认', (520, 340, 665, 405))
        if not confirmation.blue_button(button):
            raise EventUIError('扫荡确认按钮不可用')
        self.state['pending_spend'] = dict(kind='sweep', before=before, after=before-wanted,
            quantity=wanted, confirmation=str(self.ui.save('sweep_confirmation', confirmation)))
        self.save()
        self.check_deadline()
        self.ui.click(button)
        self.settle_sweep()

    def settle_sweep(self):
        plan = self.state['pending_spend']
        for _ in range(60):
            s = self.capture()
            if self.skip_receipt(s):
                plan.setdefault('receipts', []).append(str(self.ui.save('sweep_receipt_'+str(len(plan.get('receipts', []))), s)))
                self.save()
                self.click(s, '关闭|确认|下一步|跳过完毕', (250, 335, 945, 525))
            elif field.detail(s):
                self.click(s, '取消', (590, 440, 750, 500))
            elif field.home(s):
                after = self.balance(s)
                if after != plan['after'] and plan.get('receipts'):
                    s = self.wait(lambda f: field.home(f) and field.tickets(self.ui, f) == plan['after'],
                                  '跳过后余额刷新', timeout=10)
                    after = self.balance(s)
                if after != plan['after'] or not plan.get('receipts'):
                    raise EventUIError('扫荡回执或讨伐券扣除未确认；保留待核对消费')
                self.report['spent'] += plan['quantity']
                self.report['remaining_tickets'] = after
                self.report['history'].append(dict(plan))
                self.state.pop('pending_spend')
                self.save()
                return s
            elif s.find('加载中|正在进行数据连接'):
                time.sleep(.5)
            else:
                time.sleep(.5)
        raise EventUIError('联动跳过结算超时；未重复提交')

    def collect(self):
        if not self.options['claim_rewards']:
            return
        s = self.open_missions(self.enter())
        button = field.confident(s, '全部收取', (490, 450, 700, 505))
        if not s.blue_button(button):
            self.report['missions'] = 'no_claimable_rewards'
            self.click(s, '取消', (265, 450, 470, 505))
            return
        self.state['pending_claim'] = dict(before=str(self.ui.save('missions_before', s)))
        self.save()
        self.ui.click(button)
        s = self.wait(lambda f: f.find('收取报酬', (300, 0, 700, 100), exact=True)
                      and f.find('收取了以下道具|获得了以下报酬'), '任务奖励回执')
        self.state['pending_claim']['receipt'] = str(self.ui.save('mission_receipt', s))
        self.save()
        self.click(s, '关闭', (300, 425, 660, 525))
        s = self.wait(field.missions, '领奖后任务列表')
        if s.blue_button(field.confident(s, '全部收取', (490, 450, 700, 505))):
            raise EventUIError('领取后仍有可领标记；未重复领取')
        self.state.pop('pending_claim')
        self.report['missions'] = 'claimed'
        self.save()
        self.click(s, '取消', (265, 450, 470, 505))

    def open_exchange(self):
        s = self.enter()
        self.click(s, '报酬交换', (850, 385, 950, 465))
        for _ in range(30):
            s = self.capture()
            if self.combat_pre_dialog(s):
                continue
            if field.exchange(s):
                return s
            if (s.find('可可萝', (180, 380, 400, 430), exact=True)
                    and s.find('在报酬兑换处', (180, 420, 800, 505))):
                self.ui.click((779, 488))
            else:
                time.sleep(.5)
        raise EventUIError('奖励券兑换页面未确认')

    def exchange(self):
        if not self.options['exchange']:
            return
        self.report_progress('联动讨伐 · 兑换已有讨伐奖励券')
        s = self.open_exchange()
        for _ in range(self.options['max_exchange_batches']):
            before = field.exchange_balance(self.ui, s)
            if before is None:
                raise EventUIError('讨伐奖励券余额未知')
            if before == 0:
                self.report['remaining_reward_tickets'] = 0
                self.finish_exchange(s)
                return
            action = field.exchange_action(s, before)
            if action is None:
                s = self.wait(lambda f: field.exchange_action(f, before) is not None,
                              '奖励券兑换按钮与消费', timeout=10)
                if field.exchange_balance(self.ui, s) != before:
                    raise EventUIError('等待兑换按钮时余额变化；未追加兑换')
                action = field.exchange_action(s, before)
            button, amount = action
            self.state['pending_exchange'] = dict(before=before, after=before-amount, quantity=amount, created_at=time.time(),
                before_evidence=str(self.ui.save('exchange_before', s)))
            self.save()
            self.check_deadline()
            self.ui.click(button)
            s = self.settle_exchange()
            if field.exchange_balance(self.ui, s) == 0:
                self.finish_exchange(s)
                return
        raise EventUIError('达到奖励券兑换批次上限；保留余额')

    def set_exchange_mode(self, s, mode, *, remember=False):
        if mode not in field.EXCHANGE_MODE_POINTS or not field.exchange(s):
            raise EventUIError('兑换设定或起始页面未确认')
        before = field.exchange_balance(self.ui, s)
        if before is None:
            raise EventUIError('切换兑换设定前奖励券余额未知')
        self.click(s, '便利设定', (740, 0, 840, 70))
        s = self.wait(lambda f: field.exchange_mode(f) is not None, '兑换设定与选中状态', timeout=10)
        original = field.exchange_mode(s)
        if remember and 'exchange_mode_restore' not in self.state:
            self.state['exchange_mode_restore'] = original
            self.save()
        if original != mode:
            self.ui.click(field.EXCHANGE_MODE_POINTS[mode])
            s = self.wait(lambda f: field.exchange_mode(f) == mode, '兑换设定已切换', timeout=10)
        self.ui.save('exchange_mode_'+mode, s)
        self.click(s, '关闭', (370, 445, 590, 515))
        s = self.wait(field.exchange, '兑换设定返回兑换页')
        if field.exchange_balance(self.ui, s) != before:
            raise EventUIError('切换兑换设定时奖励券余额变化，保留现场')
        return s

    def finish_exchange(self, s):
        if mode := self.state.get('exchange_mode_restore'):
            s = self.set_exchange_mode(s, mode)
            self.state.pop('exchange_mode_restore')
            self.report['exchange_mode_restored'] = mode
            self.save()
        self.ui.click((30, 30))
        self.wait(field.home, '兑换后返回活动')

    def settle_exchange(self):
        plan = self.state['pending_exchange']
        for _ in range(45):
            s = self.capture()
            if field.confident(s, '一键交换确认', (300, 60, 660, 115)):
                confirmation = field.exchange_confirmation(self.ui, s)
                if confirmation is None:
                    s = self.wait(lambda f: field.exchange_confirmation(self.ui, f) is not None,
                                  '一键兑换确认数量与重置数', timeout=10)
                    confirmation = field.exchange_confirmation(self.ui, s)
                if confirmation['quantity'] != plan['quantity'] or plan.get('final_submitted'):
                    raise EventUIError('一键兑换数量、奖池重置或提交状态不符；未确认兑换')
                if confirmation['resets'] > 0:
                    page = self.cancel_exchange_confirmation(s, confirmation)
                    if field.exchange_balance(self.ui, page) != plan['before']:
                        raise EventUIError('取消跨池兑换后余额变化；保留待核对计划')
                    self.report['history'].append(dict(plan, outcome='cancelled_for_batch_exchange'))
                    self.state.pop('pending_exchange')
                    self.save()
                    atomic_json(self.cancellation_path, {})
                    if any(k.startswith('pending_') for k in self.state):
                        raise EventUIError('有上次未核对的联动操作，未追加消费')
                    return self.set_exchange_mode(page, '100次', remember=True)
                plan.update(final_submitted=True, confirmation=str(self.ui.save('exchange_confirmation', s)))
                self.save()
                self.check_deadline()
                self.ui.click(confirmation['button'])
                continue
            if self.combat_pre_dialog(s):
                continue
            if s.find('报酬确认|交换结果|一键交换完毕|获得报酬', (200, 0, 780, 250)):
                plan['receipt'] = str(self.ui.save('exchange_receipt', s))
                self.save()
                self.click(s, '确认|确定|关闭', (250, 300, 730, 515))
            elif field.exchange(s) and plan.get('receipt'):
                after = field.exchange_balance(self.ui, s)
                if after != plan['after']:
                    raise EventUIError('奖励券扣除与兑换按钮的消费不符；保留记录')
                self.report.setdefault('exchanges', []).append(dict(plan))
                self.report['remaining_reward_tickets'] = after
                self.state.pop('pending_exchange')
                self.save()
                return s
            else:
                time.sleep(.5)
        raise EventUIError('兑换回执或奖励券余额未确认；未重新提交')

    def run(self):
        try:
            self.report_progress('联动讨伐 · 确认本期活动与资源')
            s = self.enter()
            if s is None:
                self.report['status'] = 'unavailable'
                return self.report
            s = self.initialize(s)
            before = self.balance(s)
            self.report.update(initial_tickets=before, remaining_tickets=before)
            for name in DIFFICULTIES:
                s = self.open_detail(name)
                if field.first_clear_free(s):
                    s = self.first_clear(s)
                if field.cleared(self.ui, s) is not True:
                    raise EventUIError(name+'通关状态无法核实')
                self.report.setdefault('cleared', []).append(name)
            while self.report['remaining_tickets'] > 0 and self.report['spent'] < self.options['max_tickets']:
                self.sweep(s)
                if self.report['remaining_tickets'] > 0 and self.report['spent'] < self.options['max_tickets']:
                    s = self.open_detail('高难')
            self.collect()
            self.exchange()
            # A configured ticket budget is a deliberate stop, not an
            # unreconciled state; it must not block later activity types.
            self.report['status'] = 'complete'
            if self.report['remaining_tickets']:
                self.report['budget_limited'] = True
        except EventUIError as error:
            self.report['status'] = 'partial' if self.report['history'] or any(k.startswith('pending_') for k in self.state) else 'blocked'
            self.report['pending'].append(str(error))
            if self.ui.last is not None:
                self.ui.save('blocked', self.ui.last)
            if self.period and not any(k.startswith('pending_') for k in self.state):
                # Verified finished battles can still unlock daily rewards
                # when a later source/target is blocked. Never leave an
                # unknown submitted battle or spend to attempt a claim.
                try:
                    self.collect()
                    self.exchange()
                except EventUIError as claim_error:
                    self.report['pending'].append('活动奖励：'+str(claim_error))
        except (RunCancelled, ResumeUnsafe) as error:
            self.report['status'] = 'cancelled' if isinstance(error, RunCancelled) else 'error'
            raise
        except Exception:
            self.report['status'] = 'error'
            raise
        finally:
            self.save()
        return self.report
