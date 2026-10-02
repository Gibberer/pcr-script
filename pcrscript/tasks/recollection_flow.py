"""Shared navigation, budgets and recovery for Recollection tasks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .base import BaseTask
from ..game_ui import recollection as field
from ..game_ui.screen import EventUI, EventUIError
from ..run_session import atomic_json, checkpoint, clock as time


class RecollectionBlocked(EventUIError):
    pass


def validate_options(options, *, first_clear=False):
    section = 'RecollectionFirstClear' if first_clear else 'Recollection'
    if not isinstance(options, dict):
        raise ValueError(section+'必须是配置对象')
    value = dict(options)
    defaults = [('timeout', 3600 if first_clear else 600, 7200)]
    if first_clear:
        defaults += [('battle_timeout', 220, 600), ('max_battles', 30, 100),
                     ('max_attempts_per_stage', 2, 5)]
    else:
        defaults += [('max_sweeps', 9, 99)]
    for key, default, upper in defaults:
        number = value.setdefault(key, default)
        if type(number) is not int or not 1 <= number <= upper:
            raise ValueError(f'{section}.{key}必须是1到{upper}的整数')
    flags = ('discover_sources', 'allow_local_trials', 'auto_equip') if first_clear else ('claim_rewards', 'sweep_dominion', 'preview_only')
    for key in flags:
        flag = value.setdefault(key, key not in ('allow_local_trials', 'auto_equip', 'preview_only'))
        if type(flag) is not bool:
            raise ValueError(f'{section}.{key}必须为布尔值')
    areas = value.setdefault('areas', list(field.AREAS) if first_clear else ['kaiser', 'zen', 'miroku'])
    reverse = {name: key for key, name in field.AREAS.items()}
    if not isinstance(areas, list) or not areas or any(not isinstance(a, str) for a in areas):
        raise ValueError(section+'.areas必须为领域名称列表')
    areas = [reverse.get(a, a) for a in areas]
    if (len(set(areas)) != len(areas) or any(a not in field.AREAS for a in areas)
            or not first_clear and 'memory' in areas):
        raise ValueError(section+'.areas必须为不同的领域名称：'+', '.join(field.AREAS.values() if first_clear else list(field.AREAS.values())[1:]))
    value['areas'] = areas
    if first_clear:
        from .strategy_inputs import validate_urls
        validate_urls(value.setdefault('source_urls', []))
        if not isinstance(value.setdefault('sources', {}), dict):
            raise ValueError(section+'.sources必须为配置对象')
    return value


class RecollectionTask(BaseTask):
    first_clear = False

    @classmethod
    def prepare(cls, config, *args, **kwargs):
        if args or kwargs:
            raise ValueError(cls.name+'使用'+cls.config_section+'配置')
        validate_options(config.get(cls.config_section, {}), first_clear=cls.first_clear)
        return (), {}, None

    def __init__(self, robot):
        super().__init__(robot)
        self.options = validate_options(self.task_options(), first_clear=self.first_clear)
        self.ui = EventUI(self.driver, self.options.get('output', 'cache/daily/'+self.name))
        self.report_path = self.ui.output/'report.json'
        self.deadline = time.monotonic()+self.options['timeout']
        self.report = dict(status='running', pending=[], history=[])
        account = self.options.get('account_key', str(getattr(self.driver, 'device_name', getattr(self.driver, 'index', 'default'))))
        key = hashlib.sha256(str(account).encode()).hexdigest()[:24]
        self.state_path = Path(self.options.get('state_dir', 'cache/daily/recollection_state'))/(key+'.json')
        self.state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {}

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(self.report_path, self.report)
        atomic_json(self.state_path, self.state)

    def log(self, message):
        print('[追忆战场] '+message, flush=True)

    def check_deadline(self):
        checkpoint()
        if time.monotonic() >= self.deadline:
            raise RecollectionBlocked('追忆战场达到任务时限，未追加消费')

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
        raise RecollectionBlocked(description+'超时，未重复提交')

    def click(self, screen, pattern, roi):
        item = screen.find(pattern, roi, exact=True)
        if item is None or item.score < .95:
            screen = self.wait(lambda s: (item := s.find(pattern, roi, exact=True)) is not None
                               and item.score >= .95, '按钮无法核对：'+pattern, timeout=5)
            item = screen.find(pattern, roi, exact=True)
        self.ui.click(item)

    def settle_battle_result(self, screen):
        raise RecollectionBlocked('存在未结算首通战斗，请先运行追忆战场首通核对结果')

    def enter(self):
        for _ in range(30):
            s = self.capture()
            if field.home(s):
                return s
            if field.battle_result_button(s):
                self.settle_battle_result(s)
            elif field.receipt(s):
                self.ui.save('resumed_receipt', s)
                self.click(s, '确认|关闭|确定', (250, 430, 720, 525))
            elif field.bulk_confirmation(s) or field.bulk_catalogue(s) or field.difficulty_selector(s):
                self.click(s, '取消|关闭', (250, 440, 615, 525))
            elif s.find('队伍编组', (250, 0, 710, 80), exact=True):
                self.click(s, '取消', (630, 410, 780, 500))
            elif field.detail_scope(s) or field.dominion_index(s):
                self.ui.click((30, 30))
            elif s.find('追忆战宝箱详情', (250, 0, 720, 80), exact=True):
                self.click(s, '关闭', (350, 440, 615, 525))
            elif s.find('冒险', (30, 0, 175, 65), exact=True):
                entry = s.find('追忆的战场', (100, 65, 950, 470), exact=True)
                if not entry:
                    return None
                self.ui.click(entry)
            elif (s.find('菜单', (840, 0, 960, 60), exact=True)
                  or s.find(r'\d:\d{2}', (750, 0, 850, 55))):
                raise RecollectionBlocked('存在未结算战斗；保留现场，不开始新挑战')
            elif s.find('日程表', (650, 390, 810, 475), exact=True) or s.find('出发', (500, 260, 690, 330), exact=True):
                self.click(s, '冒险', (475, 475, 595, 535))
            elif s.find('正在进行数据连接|加载'):
                time.sleep(.5)
            else:
                # Only a visible bottom navigation tab authorizes navigation.
                tab = s.find('冒险', (475, 475, 595, 535), exact=True)
                if (tab and s.text((0, 0, 960, 470))
                        and not s.find('取消|确认|关闭', (250, 400, 900, 525), exact=True)):
                    self.ui.click(tab)
                else:
                    time.sleep(.5)
        raise RecollectionBlocked('追忆战场入口无法确认')

    def index(self):
        s = self.enter()
        if s is None:
            return None
        # All three entry labels jointly identify this navigation-only page.
        # Its purple card text can have lower OCR confidence than blue buttons.
        self.ui.click(s.find('追忆战[·・]霸', (650, 310, 890, 440), exact=True))
        return self.wait(field.dominion_index, '追忆战·霸领域列表')

    def detail(self, area):
        if area == field.AREAS['memory']:
            s = self.enter()
            if s is None:
                return None
            self.click(s, '追忆战', (100, 310, 350, 440))
        else:
            s = self.index()
            if s is None:
                return None
            row = s.find(re.escape(area), (100, 310, 850, 375), exact=True)
            if row is None:
                raise RecollectionBlocked('目标领域卡片无法核对：'+area)
            if field.card_locked(s, row):
                return None
            self.ui.click(row)
        return self.wait(lambda s: field.detail_scope(s).get('area') == area, '领域详情')

    def select_floor(self, area, floor=None):
        s = self.detail(area)
        if s is None:
            return None
        if field.single_floor(s):
            if floor not in (None, 1):
                raise RecollectionBlocked('目标层数未解锁：'+area)
            self.ui.save('single_unlocked_floor', s)
            return s
        self.click(s, '难度变更', (760, 65, 950, 130))
        s = self.wait(field.difficulty_selector, '领域难度列表')
        ordinary = area == field.AREAS['memory']
        if ordinary:
            # Reset the list to its highest unlocked entry, even after a manual scroll.
            for _ in range(4):
                self.ui.swipe((645, 150), (645, 410))
            s = self.capture()
        previous = None
        for _ in range(12):
            labels = s.all(r'.*\d+层', (285, 100, 680, 435))
            rows = [(item, text_scope) for item in labels
                    if (text_scope := field.text_scope(item.text)).get('area') == area] if ordinary else [
                        (item, dict(area=area, floor=int(re.fullmatch(r'(\d+)层', item.text)[1])))
                        for item in labels if re.fullmatch(r'\d+层', item.text)]
            if not rows:
                raise RecollectionBlocked('难度列表缺少明确层数')
            target = max(rows, key=lambda row: row[1]['floor']) if floor is None else next((r for r in rows if r[1]['floor'] == floor), None)
            if target:
                self.ui.click(target[0])
                if not ordinary:
                    s = self.capture()
                    self.click(s, '确认', (480, 440, 710, 520))
                wanted = target[1]
                return self.wait(lambda s: field.detail_scope(s) == wanted, '选中领域层数')
            signature = tuple(r[1]['floor'] for r in rows)
            if signature == previous or not ordinary:
                break
            previous = signature
            self.ui.swipe((645, 410), (645, 150))
            s = self.capture()
        raise RecollectionBlocked('目标层数未解锁或未能核对')

    def finish(self):
        self.save()
        return self.report

    def blocked(self, error):
        self.report['pending'].append(str(error))
        self.report['status'] = 'partial' if self.report['history'] else 'blocked'
        self.ui.save('blocked')
        return self.finish()
