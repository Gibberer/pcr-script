"""Once-per-period full-star clear and reward collection, with live verification."""
from hashlib import sha256
import json
from pathlib import Path

from .base import EventNews, TimeLimitTask
from .options import validated_options
from .registry import register
from .stadium_strategy import StadiumFormation, source_options, parties_for_round
from .strategy_inputs import validate_urls
from ..constants import SERVER_TIMEZONE
from ..game_ui import battle_stadium as field
from ..game_ui.screen import EventUI, EventUIError, normalized
from ..run_session import atomic_json, checkpoint, RunCancelled, clock as time


def validate_options(options):
    value = validated_options(options, 'BattleStadium',
        integers=(('timeout', 7200, 14400), ('battle_timeout', 180, 600),
                  ('max_battles', 36, 100), ('max_attempts_per_round', 2, 5)),
        flags=(('claim_rewards', True), ('discover_sources', True),
               ('allow_local_trials', True), ('auto_equip', False)))
    value['source_urls'] = validate_urls(value.get('source_urls', []))
    if not isinstance(value.setdefault('sources', {}), dict):
        raise ValueError('BattleStadium.sources必须为对象')
    if type(value['sources'].get('refresh_media', False)) is not bool:
        raise ValueError('BattleStadium.sources.refresh_media必须为布尔值')
    from ..game_ui.special_equipment import validate_auto_priorities
    value['auto_equip_priorities'] = validate_auto_priorities(value.get('auto_equip_priorities', {}))
    if value['auto_equip_priorities'] and not value['auto_equip']:
        raise ValueError('auto_equip_priorities需要开启auto_equip')
    key = value.setdefault('account_key', 'default')
    if not isinstance(key, str) or not key.strip():
        raise ValueError('BattleStadium.account_key必须是非空字符串')
    return value


@register('battle_stadium')
class BattleStadium(TimeLimitTask):
    config_section = 'BattleStadium'

    @staticmethod
    def valid(event_news: EventNews, args=None):
        event = event_news.battleStadium
        return (BattleStadium, [event]) if BattleStadium.event_valid(event) else None

    @classmethod
    def prepare(cls, config, event=None):
        validate_options(config.get(cls.config_section, {}))
        if event is None:
            from ..news import fetch_event_news
            event = fetch_event_news().battleStadium
        return (event,), {}, None if cls.event_valid(event) else {'status': 'unavailable'}

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options())
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/battle_stadium'))
        self.formation = StadiumFormation(self.ui)
        self.deadline = time.monotonic()+self.options['timeout']
        self.report = dict(status='running', battles=0, history=[], audits=[], pending=[])
        self.state = {}
        self.state_path = None
        self.event = None

    def save(self):
        if self.state_path:
            atomic_json(self.state_path, self.state)
        atomic_json(self.ui.output/'report.json', self.report)

    def check(self):
        checkpoint()
        if time.monotonic() >= self.deadline:
            raise EventUIError('斗技场达到运行时限，保留未完成进度')
        if self.event and time.time() >= self.event.endTimestamp:
            raise EventUIError('斗技场报酬领取期已结束')

    def capture(self):
        self.check()
        return self.ui.capture()

    def wait(self, predicate, description, timeout=30):
        until = time.monotonic()+timeout
        while time.monotonic() < until:
            s = self.capture()
            if predicate(s):
                return s
            time.sleep(.4)
        raise EventUIError(description+'未确认，保留现场')

    def click(self, s, text, roi):
        button = s.find(text, roi, exact=True)
        if not button:
            raise EventUIError('未确认斗技场按钮：'+text)
        self.ui.click(button)

    def close_receipt(self, s):
        if not field.receipt(s):
            return False
        claim = self.state.get('pending_claim')
        if not claim:
            raise EventUIError('存在未归属的领奖回执，未继续操作')
        claim['receipt'] = str(self.ui.save('claim_receipt', s))
        self.save()
        self.click(s, '确认|关闭', (300, 425, 660, 525))
        return True

    def enter(self):
        for _ in range(60):
            s = self.capture()
            if field.home(s):
                return s
            if self.close_receipt(s):
                continue
            if s.find('角色详情', (300, 0, 650, 70), exact=True):
                self.click(s, '确认', (320, 450, 650, 515))
            elif (field.formation(s) and s.find('确定', (800, 450, 940, 530), exact=True)
                  and not s.find('取消', (570, 410, 795, 510), exact=True)):
                self.ui.click((190, 390))
            elif field.detail(s) or field.formation(s):
                self.click(s, '取消', (570, 410, 795, 510))
            elif field.rewards(s):
                self.click(s, '取消', (250, 425, 470, 510))
            elif s.find('冒险', (30, 0, 175, 65), exact=True):
                entry = s.find('斗技场', (100, 350, 450, 470), exact=True)
                if not entry:
                    # The circular entry's decorative lettering is often
                    # missed by full-frame OCR. Re-read its observed region.
                    crop = self.ui.read_region(s, (260, 380, 358, 455))
                    entry = crop.find('斗技场', exact=True)
                if entry:
                    self.ui.click(entry)
                else:
                    time.sleep(.5)
            elif s.find('冒险', (475, 475, 595, 540), exact=True):
                self.click(s, '冒险', (475, 475, 595, 540))
            else:
                time.sleep(.5)
        raise EventUIError('斗技场入口或覆盖页面无法确认')

    def progress(self, s):
        value = field.progress(self.ui, s)
        if value is None:
            raise EventUIError('斗技场回合或累计星数未知')
        self.report['progress'] = value
        return value

    def page(self, direction, previous):
        self.ui.click((930 if direction > 0 else 30, 230))
        old = [r.number for r in field.rounds(previous)]
        return self.wait(lambda s: field.home(s) and field.rounds(s)
                         and [r.number for r in field.rounds(s)] != old, '斗技场翻页')

    def find_round(self, number=None, *, exclude_rounds=()):
        s = self.enter()
        p = self.progress(s)
        for _ in range(34):
            rows = field.rounds(s)
            if not rows:
                raise EventUIError('斗技场回合卡片未确认')
            if rows[0].number == 1:
                break
            s = self.page(-1, s)
        else:
            raise EventUIError('斗技场首页回合无法找回')
        seen = set()
        partial = None
        for _ in range(34):
            rows = field.rounds(s)
            if not rows or any(r.number in seen for r in rows):
                raise EventUIError('斗技场回合列表不完整或重复')
            for row in rows:
                seen.add(row.number)
                if number == row.number:
                    if row.stars is None:
                        raise EventUIError('目标回合星级未知')
                    return s, row
                if number is None and row.number <= p['unlocked'] and row.number not in exclude_rounds:
                    if row.stars is None:
                        raise EventUIError('回合星级未知，未开战')
                    if row.stars == 0:
                        return s, row
                    if row.stars < 3 and partial is None:
                        partial = row
            if rows[-1].number >= (p['unlocked'] if number is None else p['rounds']):
                if partial is not None:
                    # Clear untouched unlocked rounds before revisiting a
                    # partial win; later return to the earliest missing star.
                    if partial.number in {r.number for r in rows}:
                        return s, partial
                    return self.find_round(partial.number)
                return s, None
            s = self.page(1, s)
        raise EventUIError('斗技场回合扫描达到上限')

    def collect(self):
        self.report_progress('斗技场 · 核对累计星级报酬')
        s = self.enter()
        p = self.progress(s)
        self.click(s, '报酬', (850, 385, 950, 465))
        s = self.wait(field.rewards, '星级报酬列表')
        rows = {}
        expected = set(range(3, p['maximum_stars']+1, 3))
        def at_top(frame):
            bounds = EventUI.scrollbar_bounds(frame, field.REWARD_TRACK)
            return bounds is not None and bounds[0] <= field.REWARD_TRACK[1]+3
        def all_observed(frame):
            return field.rewards(frame) and expected <= set(rows) | {r['target'] for r in field.reward_rows(frame)}
        # The list can retain its position after closing. Start at its top.
        # Received rows move to the end, so neither target 3 nor 54 is an edge.
        for _ in range(30):
            if at_top(s):
                break
            if not self.ui.scrollbar(s, field.REWARD_TRACK, -1, reached=at_top,
                                     content_roi=(40, 65, 900, 408)):
                break
            s = self.capture()
        else:
            raise EventUIError('报酬列表无法回到顶部')
        for _ in range(30):
            if not field.rewards(s):
                raise EventUIError('报酬列表页面未知')
            visible = field.reward_rows(s)
            if not visible:
                raise EventUIError('报酬行与领取状态未知')
            # Disabled rows may retain blue fill. The actual cumulative
            # stars must meet the reward threshold before any claim.
            for reward in visible:
                reward['claimable'] = reward['claimable'] and reward['target'] <= p['stars']
            rows.update({r['target']: r for r in visible})
            if expected <= set(rows):
                break
            if not self.ui.scrollbar(s, field.REWARD_TRACK, 1, content_distance=150, reached=all_observed,
                                     content_roi=(40, 65, 900, 408)):
                break
            s = self.capture()
        else:
            raise EventUIError('报酬列表扫描达到上限')
        self.report['rewards'] = sorted(rows.values(), key=lambda r: r['target'])
        pending = self.state.get('pending_claim')
        if pending:
            if not all(rows.get(n, {}).get('received') for n in pending['targets']):
                raise EventUIError('上次领奖尚未核对，未重复收取')
            self.report['history'].append(dict(pending, outcome='claim_verified'))
            self.state.pop('pending_claim')
            self.save()
        targets = [r['target'] for r in rows.values() if r['claimable']]
        if targets and self.options['claim_rewards']:
            button = s.find('全部收取', (475, 435, 710, 510), exact=True)
            if not s.blue_button(button):
                raise EventUIError('全部收取按钮状态未知')
            self.state['pending_claim'] = dict(targets=targets, before=str(self.ui.save('claim_before', s)))
            self.save()
            self.ui.click(button)
            receipt = self.wait(field.receipt, '斗技场领奖回执')
            self.close_receipt(receipt)
            self.wait(field.rewards, '领奖后的任务列表')
            return self.collect()
        complete = (set(rows) == set(range(3, p['maximum_stars']+1, 3))
                    and all(r['received'] for r in rows.values())
                    and not s.blue_button(s.find('全部收取', (475, 435, 710, 510), exact=True)))
        self.click(s, '取消', (250, 425, 470, 510))
        self.wait(field.home, '斗技场地图')
        return complete

    def open_detail(self, row):
        s, current = self.find_round(row.number)
        if current is None or current.number > self.progress(s)['unlocked']:
            raise EventUIError('目标回合尚未解锁')
        if current.stars != row.stars or current.stars == 3:
            raise EventUIError('目标回合星级已变化，未提交旧方案')
        self.ui.click(current.position)
        return self.wait(lambda s: field.detail(s) and field.round_number(s, self.ui) == row.number, '目标回合详情')

    def select_party(self, row, party):
        ready, audit = self.formation.select(party)
        if ready or any('未在搜索结果中确认该版本的角色' in reason
                        for item in audit.get('unready', []) for reason in item.get('reasons', [])):
            return ready, audit
        unknown = [m.name for m in party.members
                   if (actual := self.formation.observed.get(normalized(m.name)))
                   and actual.identity_verified and actual.unique is None and actual.unique2 is None]
        from .party_preparation import numeric_equipment_unknown, read_numeric_equipment
        numeric = [name for name in numeric_equipment_unknown(party, self.formation.observed)
                   if (actual := self.formation.observed.get(normalized(name))) and actual.identity_verified]
        if not unknown and not numeric:
            return ready, audit
        from ..game_ui.character_equipment import inspect_unreleased_equipment
        from .task_home import ToHomePage
        self.click(self.capture(), '取消', (570, 410, 795, 510))
        ToHomePage(self.robot).run(timeout=60)
        self.report_progress(f'斗技场 · 回合{row.number}人物页核对专武')
        for name in unknown:
            self.check()
            proof = inspect_unreleased_equipment(self.ui, name)
            if proof:
                self.formation.unreleased[normalized(name)] = (time.time(), proof)
            ToHomePage(self.robot).run(timeout=60)
        for name in numeric:
            self.check()
            read_numeric_equipment(self.formation, name)
            ToHomePage(self.robot).run(timeout=60)
        s = self.open_detail(row)
        if field.challenge_goals(s) != self.report.get('goals', {}).get(str(row.number)):
            raise EventUIError('专武核对后挑战目标不一致，未开战')
        self.click(s, '挑战', (740, 410, 925, 505))
        self.wait(field.formation, '专武核对后重新编队')
        # Leaving an unstarted formation can restore its old saved roster.
        # Fresh full selection and inspection remain mandatory after the trip.
        self.report_progress(f'斗技场 · 专武核对后重新核验回合{row.number}队伍')
        return self.formation.select(party)

    def acquire(self, number, *, exclude_sources=()):
        from .strategy_video import acquire_strategies
        excluded = set(exclude_sources)
        options = source_options(self.options, self.event, number)
        budget = options.get('max_videos', 4)
        if type(budget) is not int or not 1 <= budget <= 30:
            raise ValueError('max_videos必须为1到30的整数')
        options['max_videos'] = budget-len(excluded)
        if options['max_videos'] <= 0:
            return []
        failed_members = {frozenset(normalized(m['name']) for m in old.get('build', [])
                          if isinstance(m, dict) and isinstance(m.get('name'), str))
                          for old in self.state.get('failed', [])
                          if isinstance(old, dict) and old.get('round') == number}
        def member_names(party):
            return frozenset(normalized(m.name) for m in getattr(party, 'members', ()))
        def tried(party):
            names = member_names(party)
            return bool(names) and names in failed_members
        def needs_reinspection(party):
            if not tried(party):
                return True
            priorities = self.options['auto_equip_priorities']
            if not self.options['auto_equip'] or not priorities:
                return False
            previous = [old.get('special', {}).get('priorities')
                        for old in self.state.get('failed', []) if isinstance(old, dict)
                        and old.get('round') == number
                        and frozenset(normalized(m['name']) for m in old.get('build', [])
                                      if isinstance(m, dict) and isinstance(m.get('name'), str)) == member_names(party)]
            # A new requested allocation warrants inspection, not a battle.
            # The existing live same_loadout gate still rejects an unchanged
            # or previously unsuccessful actual allocation before starting.
            return bool(previous) and all(isinstance(p, dict) and p != priorities for p in previous)
        def candidates(report):
            values = [p for p in parties_for_round(report, number,
                      allow_local_trials=self.options['allow_local_trials']) if p.source not in excluded]
            return sorted(values, key=lambda p: (tried(p), not needs_reinspection(p)))
        fallback = []
        for report in self.report.get('sources', {}).values():
            values = candidates(report)
            if any(needs_reinspection(p) for p in values):
                return values
            fallback.extend(values)
        self.report_progress(f'斗技场 · 获取本期回合{number}攻略')
        result = acquire_strategies(options, exclude_sources=excluded,
                    check=self.check, accept=lambda r: any(needs_reinspection(p) for p in candidates(r)))
        self.report.setdefault('sources', {})[f'{number}:{len(excluded)}'] = result
        values = candidates(result)
        # History changes priority only. A previously unsuccessful roster can
        # still be retried after the existing live build/loadout checks.
        return values or fallback

    def battle(self, row, party):
        if time.time() >= self.event.extras['battle_end']:
            raise EventUIError('斗技场挑战期已结束，只可领取已达成奖励')
        if self.state.get('pending_battle'):
            raise EventUIError('上次战斗尚未核对，未重新开战')
        s = self.open_detail(row)
        goals = field.challenge_goals(s)
        if goals is None:
            raise EventUIError('本回合挑战目标布局未知')
        self.report.setdefault('goals', {})[str(row.number)] = goals
        self.click(s, '挑战', (740, 410, 925, 505))
        self.wait(field.formation, '斗技场队伍编组')
        from ..game_ui.avatar_assets import ensure_avatar_index
        self.formation.avatars, _ = ensure_avatar_index(self.options['sources'].get('avatars'), check=self.check)
        self.report_progress(f'斗技场 · 核验回合{row.number}出战成员及装备')
        ready, audit = self.select_party(row, party)
        self.report['audits'].append(dict(round=row.number, source=party.source, ready=ready, details=audit))
        self.save()
        if not ready:
            self.enter()
            return False
        from ..game_ui.special_equipment import inspect_special_equipment, auto_equip_special
        special = inspect_special_equipment(self.ui, audit['order'])
        audit['special_equipment'] = special
        if special.get('unknown'):
            raise EventUIError('特别装备状态未知，未开战')
        if self.options['auto_equip']:
            audit['special_equipment_before'] = special
            self.report_progress(f'斗技场 · 回合{row.number}分配现有特别装备')
            special = auto_equip_special(self.ui, audit['order'], priorities=self.options['auto_equip_priorities'])
            audit['special_equipment'] = special
            self.save()
            if special.get('unknown'):
                raise EventUIError('特别装备分配后的状态未知，未开战')
        build = [{k: a.get(k) for k in ('name', 'level', 'rank', 'stars', 'skill_level',
                  'unique', 'unique2', 'unique_level', 'unique2_stars', 'equipment')}
                 for a in audit.get('observed', {}).values()]
        build.sort(key=lambda a: a['name'])
        context = dict(round=row.number, build=build, special=special)
        signature = sha256(json.dumps([row.number, build], sort_keys=True).encode()).hexdigest()
        from ..game_ui.special_equipment import same_loadout
        if any(isinstance(old, dict) and old.get('round') == row.number
               and old.get('build') == build and same_loadout(old.get('special', {}), special)
               for old in self.state.get('failed', [])):
            self.enter()
            return False
        s = self.capture()
        current = self.formation.inspect_current(full=False, expected_names=audit['order'], verify_skills=False)
        if not field.formation(s) or [normalized(a.name) for a in current] != audit['order'] or not all(a.identity_verified for a in current):
            raise EventUIError('开战前成员或页面不一致')
        button = s.find('战斗开始', (770, 410, 930, 500), exact=True)
        if not s.blue_button(button):
            raise EventUIError('斗技场战斗开始按钮不可用')
        self.check()
        if time.time() >= self.event.extras['battle_end']:
            raise EventUIError('斗技场挑战期已结束')
        record = dict(round=row.number, stars_before=row.stars, signature=signature, context=context, source=party.source,
                      before=str(self.ui.save('battle_before_'+str(self.report['battles']), s)))
        self.state['pending_battle'] = record
        self.report['battles'] += 1
        self.save()
        self.report_progress(f'斗技场 · 回合{row.number}自动战斗',
                             self.report['battles'], self.options['max_battles'])
        self.ui.click(button)
        self.finish_battle()
        return True

    def finish_battle(self):
        record = self.state['pending_battle']
        until = time.monotonic()+self.options['battle_timeout']
        while time.monotonic() < until:
            s = self.capture()
            if field.home(s):
                break
            if s.find('战斗胜利|战斗失败|WIN|LOSE', (0, 0, 960, 450)):
                results = record.setdefault('result_images', [])
                result = str(self.ui.save(f'battle_result_{record["round"]}_{self.report["battles"]}_{len(results)}', s))
                results.append(result)
                record.setdefault('result', result)
                self.save()
                button = s.find('前往斗技场|返回斗技场|下一步', (650, 425, 945, 535), exact=True)
                if button:
                    self.ui.click(button)
                    continue
            time.sleep(.5)
        else:
            raise EventUIError('战斗结算未知，保留待核对战斗')
        _, row = self.find_round(record['round'])
        if row is None or row.stars is None or (row.stars <= record['stars_before'] and not record.get('result')):
            raise EventUIError('战后星级变化未确认，未重放战斗')
        record['stars_after'] = row.stars
        if row.stars < 3:
            self.state.setdefault('failed', []).append(record.get('context', record['signature']))
        self.report['history'].append(dict(record, outcome='stars_verified'))
        self.state.pop('pending_battle')
        self.save()

    def run(self, event=None):
        try:
            if not self.event_valid(event):
                self.report['status'] = 'unavailable'
                return self.report
            if type(event.extras.get('schedule_id')) is not int or type(event.extras.get('battle_end')) not in (int, float):
                raise EventUIError('斗技场活动身份或挑战期未知')
            self.event = event
            identity = sha256((self.options['account_key']+':'+str(event.extras['schedule_id'])).encode()).hexdigest()[:24]
            self.state_path = Path(self.options.get('state_dir', 'cache/game/battle_stadium'))/(identity+'.json')
            if self.state_path.exists():
                self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
                if not isinstance(self.state, dict):
                    raise EventUIError('斗技场恢复记录无效')
            self.report['event_id'] = event.extras['schedule_id']
            self.report_progress('斗技场 · 核对活动与已有星级')
            if self.state.get('pending_battle'):
                self.finish_battle()
            s = self.enter()
            # The event identity is never inferred from a cached completion.
            from datetime import datetime
            start = datetime.fromtimestamp(event.startTimestamp, SERVER_TIMEZONE)
            end = datetime.fromtimestamp(event.extras['battle_end'], SERVER_TIMEZONE)
            banner = normalized(s.text((30, 50, 425, 90)))
            if start.strftime('%m/%d%H:%M') not in banner or end.strftime('%m/%d%H:%M') not in banner:
                raise EventUIError('游戏举办时间与本期数据库不一致')
            self.progress(s)
            blocked_rounds = set()
            while self.report['battles'] < self.options['max_battles']:
                collected = self.collect()
                s = self.enter()
                p = self.progress(s)
                if p['stars'] == p['maximum_stars']:
                    if not collected:
                        raise EventUIError('星级已满，累计报酬尚未全部领取')
                    self.report['status'] = 'complete' if self.report['battles'] or self.report['history'] else 'already_complete'
                    return self.report
                if time.time() >= event.extras['battle_end']:
                    raise EventUIError('挑战期已结束，星级奖励尚未全部达成')
                _, row = self.find_round(exclude_rounds=blocked_rounds)
                if row is None:
                    if blocked_rounds:
                        raise EventUIError('已解锁回合没有可核验的新方案，保留未满星回合：'
                                           + ','.join(map(str,sorted(blocked_rounds))))
                    raise EventUIError('已解锁回合均满星，后续回合待解锁')
                attempts = 0
                checked_sources = set()
                while attempts < self.options['max_attempts_per_round']:
                    candidates = self.acquire(row.number, exclude_sources=frozenset(checked_sources))
                    if not candidates:
                        break
                    for party in candidates:
                        self.check()
                        checked_sources.add(party.source)
                        if attempts >= self.options['max_attempts_per_round'] or self.report['battles'] >= self.options['max_battles']:
                            break
                        if self.battle(row, party):
                            attempts += 1
                            _, row = self.find_round(row.number)
                            if row.stars == 3:
                                break
                    # Include failed metadata/comment inspections: retrying
                    # those can otherwise hide later candidates behind them.
                    # All inspected sources share the same round's budget.
                    for key, report in self.report.get('sources', {}).items():
                        if key.split(':')[0] == str(row.number):
                            checked_sources.update(report.get('inspected_sources', []))
                            checked_sources.update(report.get('parsed_source_attempts', []))
                            checked_sources.update(p['source'] for p in report.get('parsed_sources', [])
                                                   if isinstance(p.get('source'), str))
                    if row.stars == 3 or self.report['battles'] >= self.options['max_battles']:
                        break
                if row.stars < 3:
                    blocked_rounds.add(row.number)
                    self.report['pending'].append(f'回合{row.number}尚未满星：没有已核验的可用新方案或达到尝试上限')
                    self.save()
            collected = self.collect()
            p = self.progress(self.enter())
            if p['stars'] == p['maximum_stars'] and collected:
                self.report['status'] = 'complete'
                return self.report
            raise EventUIError('斗技场达到本次战斗上限，保留进度')
        except RunCancelled:
            self.report['status'] = 'cancelled'
            raise
        except EventUIError as error:
            self.report['status'] = 'partial'
            self.report['pending'].append(str(error))
            self.ui.save('blocked')
            return self.report
        finally:
            self.save()
