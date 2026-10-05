"""Consume existing Dawn Labyrinth passes through unlocked sweeps only."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from .base import BaseTask
from .registry import register
from ..game_ui import dawn_labyrinth as maze
from ..game_ui.abyss_subjugation import navigation_exit as subjugation_navigation_exit
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import RunCancelled, ResumeUnsafe, atomic_json, clock as time, emit


def validate_options(options: dict) -> dict:
    if not isinstance(options, dict):
        raise ValueError('DawnLabyrinth必须是配置对象')
    value = dict(options)
    if 'account_key' in value and (not isinstance(value['account_key'], str) or not value['account_key'].strip()):
        raise ValueError('DawnLabyrinth.account_key必须是非空字符串')
    for key, default, upper in (('timeout', 600, 3600), ('max_passes', 99, 99)):
        number = value.setdefault(key, default)
        if type(number) is not int or not 1 <= number <= upper:
            raise ValueError(f'DawnLabyrinth.{key}必须是1到{upper}的整数')
    return value


class SweepBlocked(EventUIError):
    """A visible prerequisite prevents spending any further passes."""


def load_daily_state(driver, options):
    account = options.get('account_key', getattr(driver, 'device_name', getattr(driver, 'index', 'default')))
    key = sha256(str(account).encode()).hexdigest()[:24]
    path = Path(options.get('state_dir', 'cache/daily/dawn_labyrinth_state')) / (key + '.json')
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(state, dict):
        raise ValueError('迷宫消费状态必须是对象，未开始新消费')
    pending = {}
    for name in ('pending_spend', 'pending_mission_claim'):
        if name in state:
            if not isinstance(state[name], dict) or not state[name]:
                raise ValueError('迷宫待核对记录无效，未开始新消费')
            pending[name] = state[name]
    spend = pending.get('pending_spend')
    if spend and (any(type(spend.get(k)) is not int for k in ('before', 'after', 'cost'))
                  or not 0 <= spend['after'] < spend['before'] <= 99
                  or spend['cost'] != spend['before'] - spend['after']):
        raise ValueError('迷宫待核对消费数量无效，未开始新消费')
    return path, pending


@register('dawn_labyrinth', requires_home=False)
class DawnLabyrinth(BaseTask):
    config_section = 'DawnLabyrinth'
    mission_limit = 20

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        validate_options(config.get(cls.config_section, {}))
        return args, kwargs, None

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/dawn_labyrinth'))
        self.deadline = time.monotonic() + self.options['timeout']
        self.report = dict(status='running', initial_passes=None, remaining_passes=None,
                           spent=0, sweeps=0, pending=[], history=[])
        self.state_path, state = load_daily_state(self.driver, self.options)
        self.report.update(state)

    def save_report(self):
        # First-clear exploration has a separate, conservative recovery flow.
        # Daily sweeps need a device/account record outside per-run evidence.
        if getattr(self, 'state_path', None) is not None:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(self.state_path, {name: self.report[name] for name in
                        ('pending_spend', 'pending_mission_claim') if name in self.report})
        atomic_json(self.ui.output / 'report.json', self.report)

    def capture(self):
        if time.monotonic() >= self.deadline:
            raise EventUIError('黎明界迷宫达到运行时限，未重复消费')
        return self.ui.capture()

    def wait(self, predicate, description, timeout=30):
        deadline = min(self.deadline, time.monotonic() + timeout)
        while time.monotonic() < deadline:
            screen = self.capture()
            if predicate(screen):
                return screen
            time.sleep(.5)
        raise EventUIError(description + '超时，未重复消费')

    def enter(self):
        for _ in range(30):
            screen = self.capture()
            if maze.mission_receipt(screen):
                path = self.ui.save('missions_resumed_receipt', screen)
                self.report.setdefault('resumed_mission_receipts', []).append(str(path))
                if self.report.get('pending_mission_claim'):
                    self.report['pending_mission_claim']['receipt'] = str(path)
                self.save_report()
                close = screen.find('确认|关闭', (320, 430, 650, 520), exact=True)
                if not close:
                    raise SweepBlocked('迷宫任务领取回执无法关闭')
                self.ui.click(close)
                continue
            if maze.missions_page(screen):
                self.ui.save('missions_resumed_list', screen)
                self.ui.click(screen.find('取消', (255, 440, 465, 515), exact=True))
                continue
            if maze.receipt(screen):
                if self.report.get('pending_spend'):
                    self.record_sweep_result('sweep_resumed_receipt', screen)
                close = screen.find('确认|关闭', (320, 395, 750, 520), exact=True)
                if close:
                    self.ui.click(close)
                else:
                    time.sleep(.5)
                continue
            if maze.home(screen):
                return screen
            if (cancel := subjugation_navigation_exit(screen)) is not None:
                self.ui.click(cancel)
                continue
            if maze.bulk_confirmation(screen) or maze.sweep_confirmation(screen):
                cancel = screen.find('取消', (255, 440, 465, 520), exact=True)
                if not cancel:
                    raise SweepBlocked('扫荡确认无法安全关闭')
                pending = self.report.get('pending_spend')
                if pending:
                    preview = (maze.bulk_preview(self.ui, screen) if maze.bulk_confirmation(screen)
                               else maze.pass_preview(screen))
                    if (preview == (pending['before'], pending['after'])
                            and (not pending.get('guild') or maze.sweep_guild_evidence(screen, pending['guild']))):
                        pending['cancelled_confirmation'] = str(self.ui.save('sweep_resumed_cancel', screen))
                        self.save_report()
                self.ui.click(cancel)
                continue
            if maze.sweep_catalogue(screen):
                cancel = screen.find('取消', (480, 440, 695, 520), exact=True)
                if not cancel:
                    raise SweepBlocked('跳过公会列表无法安全关闭')
                self.ui.click(cancel)
                continue
            if maze.guild_selection(screen):
                self.ui.click((30, 30))
                continue
            if screen.find(maze.TITLE, (45, 0, 270, 75), exact=True):
                raise SweepBlocked('迷宫不在出发首页；请先手动处理正在进行的探索或弹窗')
            if screen.find('冒险', (30, 0, 175, 65), exact=True):
                entry = screen.find(maze.TITLE, (650, 290, 950, 475), exact=True)
                if not entry:
                    return None
                self.ui.click(entry)
            else:
                tab = screen.find('冒险', (475, 475, 595, 535), exact=True)
                if tab:
                    self.ui.click(tab)
                else:
                    time.sleep(.5)
        raise EventUIError('黎明界迷宫入口无法确认')

    def reconcile_spend(self, screen):
        pending = self.report.get('pending_spend')
        if not pending:
            return
        remaining = self.balance(screen)
        self.report['remaining_passes'] = remaining
        if (remaining == pending['before'] and not pending.get('receipt') and not pending.get('result_evidence')
                and pending.get('cancelled_confirmation')):
            outcome = 'cancelled_sweep'
        elif (remaining == pending['before'] and not pending.get('receipt') and not pending.get('result_evidence')
                and pending.get('submission_tracked') is True and type(pending.get('submitted')) is bool):
            # The dispatch journal is saved before input, so either phase may
            # survive an undelivered click. Recovery alone verifies fresh stable
            # home frames; normal settlement still waits for a result. A saved
            # result forbids cancellation even if the home balance is stale.
            for step in range(3):
                if step:
                    time.sleep(1)
                    screen = self.capture()
                title = screen.find(maze.TITLE, (45, 0, 270, 75), exact=True)
                departure = screen.find('出发', (480, 250, 695, 330), exact=True)
                if (not maze.home(screen) or not title or title.score < .95
                        or not departure or departure.score < .95
                        or screen.find('确认|关闭|取消|确定|正在进行数据连接|连接中|加载中')
                        or self.balance(screen) != pending['before']):
                    raise SweepBlocked('迷宫跳过恢复时首页或余额不稳定，保留待核对记录')
            pending['unsubmitted_balance'] = str(self.ui.save('sweep_unsubmitted_balance', screen))
            outcome = 'cancelled_unsubmitted_sweep'
        elif remaining == pending['after'] and pending.get('receipt'):
            outcome = 'recovered_sweep'
            self.report['spent'] += pending['cost']
            self.report['sweeps'] += 1
        else:
            raise SweepBlocked('上次迷宫跳过的回执或通行证余额尚未核对，未重复消费或领取奖励')
        self.report['history'].append(dict(self.report.pop('pending_spend'), outcome=outcome,
                                            remaining=remaining,
                                            balance_evidence=str(self.ui.save('sweep_recovered_balance', screen))))
        self.save_report()

    def record_sweep_result(self, name, screen):
        proof = str(self.ui.save(name, screen))
        pending = self.report.get('pending_spend')
        if pending:
            # Persist any result observation before dismissing it. A generic
            # reward page cannot settle a sweep, but prevents treating a later
            # unchanged balance as proof that input was never delivered.
            pending.setdefault('result_evidence', proof)
            if screen.find(r'(?:迷宫)?(?:跳过|扫荡)结果', (140, 0, 820, 110), exact=True):
                pending['receipt'] = proof
            self.save_report()

    def balance(self, screen):
        value = maze.read_held_passes(self.ui, screen)
        if value is None:
            raise EventUIError('持有通行证数量无法确认，未追加消费')
        return value

    def open_mission_list(self, screen):
        if not maze.home(screen) or maze.mission_receipt(screen):
            raise EventUIError('迷宫任务奖励入口上下文未知')
        entry = screen.find('任务', (790, 220, 935, 285), exact=True)
        if not entry or entry.score < .95:
            raise EventUIError('迷宫任务奖励入口无法核对')
        self.ui.click(entry)
        screen = self.wait(maze.missions_page, '迷宫任务列表')
        self.ui.click(screen.find('全部',(40,60,325,115),exact=True))
        return self.wait(lambda s: maze.missions_page(s)
                         and s.blue_button(s.find('全部', (40, 60, 325, 115), exact=True)),
                         '迷宫全部任务')

    def collect_mission_rewards(self, screen=None):
        """Claim free maze missions only after the exploration/sweep has settled."""
        screen = screen if screen is not None else self.capture()
        if (not maze.home(screen) or maze.receipt(screen) or maze.missions_page(screen)
                or maze.mission_receipt(screen) or self.report.get('pending_spend')
                or self.report.get('pending_battle')):
            raise EventUIError('不在迷宫结算后的首页，未领取任务奖励')
        before = self.balance(screen)
        pending_claim = self.report.get('pending_mission_claim')
        if pending_claim and pending_claim.get('receipt'):
            self.report['history'].append(dict(self.report.pop('pending_mission_claim'),
                                                outcome='recovered_mission_claim'))
            self.save_report()
            pending_claim = None
        missions = self.report.setdefault('missions', dict(batches=0, receipts=[], passes_before=before))
        missions.update(status='running')
        if not maze.mission_reward_hint(screen) and not pending_claim:
            missions.update(status='complete', passes_after=before)
            return screen
        self.report_progress('领取黎明界迷宫任务奖励')
        screen = self.open_mission_list(screen)
        claim_before = before
        for _ in range(self.mission_limit):
            button = screen.find('全部收取', (480, 440, 705, 515), exact=True)
            if button is None or button.score < .95:
                raise EventUIError('迷宫任务全部收取按钮无法核对')
            if not screen.blue_button(button):
                if any(screen.blue_button(item) for item in screen.all(r'^收取$', (775, 120, 915, 405))):
                    raise EventUIError('迷宫任务单项与全部收取状态不符，未重复领取')
                self.ui.save('missions_empty', screen)
                self.ui.click(screen.find('取消', (255, 440, 465, 515), exact=True))
                screen = self.wait(lambda s: maze.home(s) and not maze.missions_page(s)
                                   and not maze.mission_receipt(s), '返回迷宫首页')
                after = self.balance(screen)
                self.report['remaining_passes'] = after
                missions['passes_after'] = after
                if after < before:
                    raise EventUIError('领取任务奖励后通行证减少，停止追加操作')
                if maze.mission_reward_hint(screen):
                    raise EventUIError('迷宫首页仍有可领取任务提示，未确认奖励清空')
                if self.report.get('pending_mission_claim'):
                    self.report['history'].append(dict(self.report.pop('pending_mission_claim'),
                                                        outcome='recovered_empty_missions'))
                    self.save_report()
                missions['status'] = 'complete'
                self.ui.save('missions_home', screen)
                return screen
            if self.report.get('pending_mission_claim'):
                pending = self.report['pending_mission_claim']
                snapshot = pending.get('missions_view')
                if (not snapshot or type(pending.get('passes_before')) is not int
                        or pending['passes_before'] != before
                        or maze.mission_claim_snapshot(screen) != snapshot):
                    raise EventUIError('上次迷宫任务领奖尚未核对，未重复领取')
                # A durable preview can precede the actual input. Only the
                # same still-unclaimed task content and unchanged balance
                # across fresh, non-loading observations release that record.
                for _ in range(2):
                    time.sleep(1)
                    screen = self.capture()
                    if maze.mission_claim_snapshot(screen) != snapshot:
                        raise EventUIError('迷宫领奖恢复时任务内容或状态变化，保留待核对记录')
                self.report['history'].append(dict(self.report.pop('pending_mission_claim'),
                    outcome='recovered_unclaimed_missions',
                    recovery_evidence=str(self.ui.save('missions_unclaimed_recovered',screen))))
                self.save_report()
                button = screen.find('全部收取',(480,440,705,515),exact=True)
            if missions['batches']:
                # Earlier free rewards can add passes. Observe the actual
                # balance before journaling each subsequent claim as well.
                snapshot = maze.mission_claim_snapshot(screen)
                self.ui.click(screen.find('取消',(255,440,465,515),exact=True))
                home = self.wait(lambda s:maze.home(s) and not maze.missions_page(s)
                                 and not maze.mission_receipt(s),'核对后续领奖前的通行证')
                claim_before = self.balance(home)
                if claim_before < before:
                    raise EventUIError('后续领奖前通行证减少，停止追加操作')
                screen = self.open_mission_list(home)
                if snapshot and maze.mission_claim_snapshot(screen) != snapshot:
                    raise EventUIError('后续领奖前任务内容变化，未领取')
                button = screen.find('全部收取',(480,440,705,515),exact=True)
                if not button or button.score < .95:
                    raise EventUIError('后续迷宫领奖按钮无法核对')
                if not screen.blue_button(button):
                    continue
            snapshot = maze.mission_claim_snapshot(screen)
            if snapshot is None:
                raise EventUIError('迷宫任务内容或可领取状态不完整，未保存领奖记录或领取')
            preview = self.ui.save(f"missions_{missions['batches'] + 1:02d}_preview", screen)
            self.report['pending_mission_claim'] = dict(preview=str(preview),
                missions_view=snapshot,
                passes_before=claim_before)
            self.save_report()
            self.ui.click(button)
            receipt = self.wait(maze.mission_receipt, '迷宫任务领取回执')
            proof = self.ui.save(f"missions_{missions['batches'] + 1:02d}_receipt", receipt)
            self.report['pending_mission_claim']['receipt'] = str(proof)
            self.save_report()
            close = receipt.find('确认|关闭', (320, 430, 650, 520), exact=True)
            if not close:
                raise EventUIError('迷宫任务领取回执关闭按钮无法核对')
            self.ui.click(close)
            screen = self.wait(lambda s: maze.missions_page(s) and not maze.mission_receipt(s),
                               '领取后的迷宫任务列表')
            missions['batches'] += 1
            missions['receipts'].append(dict(self.report.pop('pending_mission_claim'), receipt=str(proof)))
            self.save_report()
        raise EventUIError('迷宫任务领取达到批次上限，保留剩余奖励')

    def open_sweep(self, screen, budget=None):
        departure = screen.find('出发', (480, 250, 695, 330), exact=True)
        if not departure:
            raise SweepBlocked('迷宫已有进行中的探索，请先手动处理；任务只执行跳过')
        self.ui.click(departure)
        screen = self.wait(maze.guild_selection, '迷宫公会选择')
        button = screen.find(maze.SWEEP, (870, 0, 955, 100), exact=True)
        if not button:
            raise SweepBlocked('未识别到迷宫跳过入口，请先确认已完成首通')
        self.ui.click(button)
        screen = self.wait(lambda s: maze.locked_notice(s) or maze.sweep_confirmation(s)
                           or maze.sweep_guild_selection(s), '迷宫跳过选择或解锁提示', timeout=15)
        if maze.locked_notice(screen):
            self.ui.save('sweep_locked', screen)
            raise SweepBlocked('当前难度尚未解锁跳过，请先完成首通；可运行 dawn_labyrinth_first_clear 首通任务')
        if maze.sweep_catalogue(screen):
            return self.prepare_catalogue(screen, budget or self.options['max_passes'])
        if maze.sweep_confirmation(screen):
            return screen
        return self.select_sweep_guild(screen)

    def sweep_guild_controls(self, screen):
        if not maze.sweep_guild_selection(screen) or maze.sweep_catalogue(screen):
            raise SweepBlocked('未确认独立跳过公会选择页，未进入探索或战斗')
        controls = maze.sweep_guild_controls(screen)
        has_preferred = any(guild and normalized(guild.text) == '美食殿堂' for guild, _ in controls)
        if not has_preferred and any(guild is None for guild, _ in controls):
            raise SweepBlocked('跳过按钮对应的公会名称无法核对，未消费')
        return [(guild, button) for guild, button in controls if guild is not None]

    def confirm_sweep_guild(self, guild, button):
        self.ui.click(button)
        screen = self.wait(lambda s: maze.sweep_confirmation(s) or maze.locked_notice(s),
                           '迷宫跳过确认')
        if maze.locked_notice(screen):
            raise SweepBlocked('所选公会未通关当前难度，请先手动首通')
        if not maze.sweep_guild_evidence(screen, guild.text):
            raise SweepBlocked('跳过确认的公会与已选目标不符或无法核对，未消费')
        return screen

    def select_sweep_guild(self, screen):
        fallback = None
        seen = {}
        for page in range(6):
            controls = self.sweep_guild_controls(screen)
            preferred = next((pair for pair in controls if normalized(pair[0].text) == '美食殿堂'), None)
            if preferred:
                return self.confirm_sweep_guild(*preferred)
            if fallback is None and controls:
                fallback = normalized(controls[0][0].text)
            # Disabled cards still distinguish pages. Repeated eligible
            # controls alone cannot prove that the carousel reached its end.
            signature = tuple((normalized(item.text), tuple(item.center))
                              for item in screen.all('.+', (20, 170, 940, 495)))
            viewport = screen.image[170:495, 20:940]
            if page == 5 or (signature in seen and (seen[signature] == viewport).all()):
                break
            seen[signature] = viewport.copy()
            self.ui.swipe((830, 300), (200, 300))
            screen = self.capture()
        if fallback is None:
            raise SweepBlocked('当前难度没有可用的跳过公会，请先手动首通')
        # Re-read the fallback on the current page; cached coordinates from an
        # earlier page cannot authorize a click after horizontal navigation.
        for page in range(6):
            controls = self.sweep_guild_controls(screen)
            choice = (next((pair for pair in controls if normalized(pair[0].text) == '美食殿堂'), None)
                      or next((pair for pair in controls if normalized(pair[0].text) == fallback), None))
            if choice:
                return self.confirm_sweep_guild(*choice)
            if page < 5:
                self.ui.swipe((200, 300), (830, 300))
                screen = self.capture()
        raise SweepBlocked('翻页后无法重新核对备用公会，未消费')

    def prepare_catalogue(self, screen, budget):
        guilds = maze.catalogue_guilds(screen)
        if not guilds:
            raise SweepBlocked('没有已核对的迷宫跳过公会，未消费')
        guild = next((g for g in guilds if normalized(g.text) == '美食殿堂'), guilds[0])
        clear = screen.find('解除所有勾选', (745, 80, 930, 140), exact=True)
        if not clear:
            raise SweepBlocked('跳过公会的勾选清理入口无法核对')
        self.ui.click(clear)
        screen = self.wait(maze.sweep_catalogue, '清空跳过公会勾选')
        if maze.catalogue_selected(screen, guild):
            raise SweepBlocked('跳过公会勾选未清空，未消费')
        self.ui.click((849, guild.center[1]+13))
        screen = self.wait(lambda s: maze.catalogue_selected(s, guild), '勾选已通关公会')
        preview = maze.catalogue_preview(self.ui, screen)
        if preview is None:
            raise SweepBlocked('单个公会的通行证预览无法核对')
        target = min(preview[0], budget)
        button = screen.find('MIN' if target == 1 else 'MAX', (615, 380, 930, 450), exact=True)
        if not button:
            raise SweepBlocked('跳过数量控件无法核对')
        self.ui.click(button)
        screen = self.capture()
        quantity = self.ui.number(screen, (740, 397, 792, 432))
        if quantity is not None and quantity > target:
            minimum = screen.find('MIN', (615, 380, 690, 450), exact=True)
            if not minimum:
                raise SweepBlocked('跳过数量的最小值控件无法核对')
            self.ui.click(minimum)
            screen = self.capture()
            quantity = self.ui.number(screen, (740, 397, 792, 432))
        for _ in range(99):
            if quantity == target:
                break
            if quantity is None or not 1 <= quantity < target:
                raise SweepBlocked('跳过数量无法核对，未消费')
            self.ui.click((832, 414))
            screen = self.capture()
            updated = self.ui.number(screen, (740, 397, 792, 432))
            if updated != quantity+1:
                raise SweepBlocked('跳过数量变化与操作不符，未消费')
            quantity = updated
        preview = maze.catalogue_preview(self.ui, screen)
        if preview is None or preview[0]-preview[1] != target or not maze.catalogue_selected(screen, guild):
            raise SweepBlocked('跳过公会、数量或消费预算无法核对，未消费')
        return screen

    def confirm(self, screen, before, budget):
        if screen.find('购买|宝石.*消耗|消耗.*宝石|回复|重置|撤退'):
            raise SweepBlocked('跳过确认出现其他资源或进度操作，未消费')
        catalogue = maze.sweep_catalogue(screen)
        bulk = maze.bulk_confirmation(screen)
        preview = (maze.catalogue_preview(self.ui, screen) if catalogue else
                   maze.bulk_preview(self.ui, screen) if bulk else maze.pass_preview(screen))
        if preview is None or preview[0] != before:
            raise SweepBlocked('跳过确认的通行证消费前后数量无法核对，未消费')
        cost = before - preview[1]
        if cost > budget:
            raise SweepBlocked('跳过预览超过本次通行证消费上限，未消费；请在游戏内调低跳过数量')
        button = (screen.find('一键扫荡', (700, 440, 930, 520), exact=True) if catalogue else
                  screen.find('挑战', (480, 440, 705, 520), exact=True) if bulk else
                  screen.find('跳过|扫荡|确认', (400, 430, 750, 520), exact=True))
        if not button or not screen.blue_button(button):
            raise SweepBlocked('跳过确认按钮不可用，未消费')
        selected = []
        if catalogue:
            selected = [g for g in maze.catalogue_guilds(screen) if maze.catalogue_selected(screen, g)]
            if len(selected) != 1:
                raise SweepBlocked('扫荡公会勾选数量无法核对，未消费')
        suffix = 'confirmation' if bulk else 'preview'
        path = self.ui.save(f"sweep_{self.report['sweeps'] + 1:03d}_{suffix}", screen)
        previous = self.report.get('pending_spend', {})
        self.report['pending_spend'] = dict(before=before, after=preview[1], cost=cost,
                                            preview=str(path), submitted=False, submission_tracked=True)
        if catalogue:
            self.report['pending_spend']['catalogue'] = True
            self.report['pending_spend']['guild'] = normalized(selected[0].text)
        elif bulk:
            self.report['pending_spend']['guild'] = normalized(maze.bulk_guild(screen).text)
            self.report['pending_spend']['catalogue_preview'] = previous.get('preview')
        # Catalogue input only opens a second preview. Track the actual spend
        # separately, and persist its dispatch phase before the irreversible click.
        self.save_report()
        if not catalogue:
            self.report['pending_spend']['submitted'] = True
            self.save_report()
        emit('dawn_labyrinth.spend', before=before, after=preview[1], cost=cost)
        self.ui.click(button)
        return preview[1]

    def settle(self, before, expected):
        result_seen = False
        deadline = min(self.deadline, time.monotonic() + 60)
        for step in range(60):
            if time.monotonic() >= deadline:
                break
            screen = self.capture()
            if ((maze.sweep_confirmation(screen) or maze.bulk_confirmation(screen))
                    and self.report.get('pending_spend', {}).get('catalogue')):
                preview = (maze.bulk_preview(self.ui, screen) if maze.bulk_confirmation(screen)
                           else maze.pass_preview(screen))
                guild = maze.bulk_guild(screen)
                if (preview != (before, expected)
                        or (maze.bulk_confirmation(screen)
                            and (guild is None or normalized(guild.text) != self.report['pending_spend']['guild']))):
                    raise EventUIError('跳过二次确认与已核对预览不符，未继续消费')
                self.confirm(screen, before, before-expected)
                continue
            if maze.home(screen) and not maze.receipt(screen):
                remaining = self.balance(screen)
                self.report['remaining_passes'] = remaining
                if remaining == before:
                    # A stale frame may precede the server response. Never
                    # open/confirm a second sweep while the first is unresolved.
                    time.sleep(.5)
                    continue
                if remaining != expected:
                    raise EventUIError('跳过后的通行证余额与预览不符，停止追加消费')
                if not result_seen:
                    raise EventUIError('通行证已扣除但未确认跳过结果，停止追加消费')
                self.ui.save(f"sweep_{self.report['sweeps'] + 1:03d}_balance", screen)
                cost = before - expected
                self.report['spent'] += cost
                self.report['sweeps'] += 1
                self.report['history'].append(dict(self.report.pop('pending_spend'), remaining=remaining))
                self.save_report()
                return screen
            if screen.find('持有上限|持有数已满|库存已满'):
                raise EventUIError('跳过结算遇到持有上限，请手动处理后核对消费回执')
            if result_seen and maze.sweep_catalogue(screen):
                cancel = screen.find('取消', (480, 440, 695, 520), exact=True)
                if not cancel:
                    raise EventUIError('跳过结果后的公会列表无法关闭，停止追加消费')
                self.ui.click(cancel)
                continue
            if result_seen and (maze.guild_selection(screen)
                                or (maze.sweep_guild_selection(screen)
                                    and screen.find(maze.TITLE, (45, 0, 270, 75), exact=True))):
                # Verified guild-selection back arrow returns to the ticket
                # balance card. Never leave exploration or a pending confirmation.
                self.ui.click((30, 30))
                continue
            if maze.receipt(screen):
                result_seen = True
                self.record_sweep_result(f"sweep_{self.report['sweeps'] + 1:03d}_result_{step:02d}", screen)
                button = screen.find('全部开启|全部打开|开启全部|打开全部|确认|关闭|返回迷宫|返回',
                                     (200, 395, 930, 525), exact=True)
                if button:
                    self.ui.click(button)
                    continue
            time.sleep(.5)
        raise EventUIError('迷宫跳过结算或通行证扣除未确认，停止追加消费')

    def run(self):
        try:
            self.report_progress('进入黎明界迷宫并读取通行证')
            screen = self.enter()
            if screen is None:
                self.report.update(status='unavailable', reason='冒险页未找到黎明界迷宫入口')
                return self.report
            self.reconcile_spend(screen)
            before = self.balance(screen)
            self.report.update(initial_passes=before, remaining_passes=before)
            budget = min(before + self.report['spent'], self.options['max_passes'])
            if self.report.get('pending_mission_claim'):
                screen = self.collect_mission_rewards(screen)
                before = self.balance(screen)
            while self.report['spent'] < budget:
                self.report_progress('消耗迷宫通行证', self.report['spent'], budget)
                preview = self.open_sweep(screen, budget - self.report['spent'])
                expected = self.confirm(preview, before, budget - self.report['spent'])
                self.report_progress('核对迷宫跳过结果与通行证余额')
                screen = self.settle(before, expected)
                before = expected
            screen = self.collect_mission_rewards(screen)
            before = self.balance(screen)
            self.report['status'] = 'complete' if before == 0 else 'partial'
            if before:
                self.report['pending'].append(
                    '任务奖励增加了通行证，留待下次运行' if before > self.report['missions']['passes_before']
                    else '已达到本次通行证消费上限，仍有通行证留待下次运行')
        except EventUIError as error:
            self.report['status'] = ('partial' if self.report.get('pending_spend') or self.report['spent']
                                     or self.report.get('pending_mission_claim')
                                     or self.report.get('missions', {}).get('batches')
                                     else 'blocked')
            if self.report.get('missions'):
                self.report['missions']['status'] = self.report['status']
            self.report['pending'].append(str(error))
            if self.ui.last is not None:
                self.ui.save('blocked', self.ui.last)
        except (RunCancelled, ResumeUnsafe) as error:
            self.report['status'] = 'cancelled' if isinstance(error, RunCancelled) else 'error'
            if self.report.get('missions'):
                self.report['missions']['status'] = self.report['status']
            self.report['pending'].append(str(error))
            raise
        except Exception as error:
            self.report['status'] = 'error'
            if self.report.get('missions'):
                self.report['missions']['status'] = 'error'
            self.report['pending'].append(str(error))
            raise
        finally:
            self.save_report()
        return self.report
