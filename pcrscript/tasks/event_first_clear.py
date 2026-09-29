"""First clears through the list event's native, bounded auto-advance flow."""
from dataclasses import asdict
import math
import re

import cv2 as cv
import numpy as np

from pcrscript.run_session import clock as time
from ..game_ui.screen import EventUIError, normalized
from ..game_ui.avatar_assets import ensure_avatar_index


def auto_advance_result(ui, s):
    """Read the native settlement, including after a process restart."""
    if not s.find('自动推进结束', (300, 100, 650, 185), exact=True):
        return None
    ui.save('first_clear_end', s)
    if s.find('战斗失败|体力不足|挑战失败') or not s.find('由于是最终关卡|特别内容.*解锁|解锁.*特别内容'):
        raise EventUIError('自动推进提前停止：' + s.text())
    count = ui.number(s, (525, 180, 590, 220))
    spent = ui.number(s, (635, 290, 715, 335))
    if count is None or spent is None or count <= 0 or spent <= 0:
        raise EventUIError('自动推进结算关卡数或体力消耗未确认')
    return dict(cleared=count, spent=spent, final=bool(s.find('由于是最终关卡')), reason=s.text())


class EventFirstClear:
    def __init__(self, battles):
        self.b = battles
        self.r, self.ui = battles.r, battles.ui
        self.budget = self.r.options.get('max_first_clear_stamina', 200)
        if type(self.budget) is not int or self.budget <= 0:
            raise ValueError('max_first_clear_stamina必须为正整数')
        self.segment_timeout = self.r.options.get('first_clear_timeout', 900)
        if (type(self.segment_timeout) not in (int, float)
                or not math.isfinite(self.segment_timeout) or self.segment_timeout <= 0):
            raise ValueError('first_clear_timeout必须为有限正数')
        # A restart may enter through a native partial settlement. Charge that
        # receipt to this recovery run before authorizing any further stages.
        self.spent = self.r.report.get('recovered_first_clear', {}).get('spent', 0)
        self.target = None
        self.current = None
        self.unreleased = {}

    def audit_party(self):
        self.r.report_progress('活动首通 · 核对保存队伍和装备')
        if self.r.options.get('allow_local_trials', False) is not True:
            raise EventUIError('未允许使用当前账号队伍试打首通，未开战')
        formation = self.b.formation
        s = self.ui.capture()
        if not s.find('队伍编组', (250, 0, 730, 70)):
            raise EventUIError('首通编队页面未确认')
        if len(formation.occupied_slots(s)) != 5:
            raise EventUIError('首通需要已选的完整五人队伍')
        formation.avatars, assets = ensure_avatar_index(
            self.r.options.get('sources', {}).get('avatars'), check=self.r.check_deadline)
        formation.infer_costume_from_skills = True
        members = formation.inspect_current(full=True)
        unknown = [m for m in members if m.identity_verified and m.unique is None]
        if unknown:
            from ..game_ui.character_equipment import inspect_unreleased_equipment
            from .task_home import ToHomePage
            self.r.home()
            for member in unknown:
                if member.name not in self.unreleased:
                    proof = inspect_unreleased_equipment(self.ui, member.name)
                    if proof:
                        self.unreleased[member.name] = proof
                    ToHomePage(self.r.robot).run(timeout=60)
            self.r.enter()
            self.open_formation(self.current)
            confirmed = formation.inspect_current(full=False, expected_names=[m.name for m in members], verify_skills=False)
            if ([m.name for m in confirmed] != [m.name for m in members]
                    or not all(m.identity_verified for m in confirmed)):
                raise EventUIError('专武核验后保存队伍发生变化，未开战')
            for member in unknown:
                if member.name in self.unreleased:
                    member.unique = member.unique2 = False
                    member.equipment_evidence = self.unreleased[member.name]
        self.r.report['first_clear_party'] = [asdict(m) for m in members]
        if (len({m.name for m in members}) != 5 or any(
                not m.identity_verified or m.level is None or m.rank is None or m.stars is None
                or m.unique is None or m.unique2 is None for m in members)):
            raise EventUIError('首通队伍身份、培养或专武状态未确认，未开战')
        self.r.report['first_clear_basis'] = {
            'build_basis': 'local_trial', 'avatar_cache_hit': assets.get('cache_hit', False),
            'assumptions': ['使用已选且核验的当前账号队伍推进普通/困难关卡', '全员立即发动连结爆发'],
        }

    def plan(self, s):
        if not s.find('自动推进设定', (200, 0, 750, 80), exact=True):
            raise EventUIError('未确认列表式活动自动推进设定')
        endpoint = s.find(r'自动推进至活动关卡[HN]-\d+时.*最多消耗', (30, 100, 920, 145))
        if endpoint is None:
            raise EventUIError('自动推进终点未确认')
        target = re.search(r'[HN]-\d+', normalized(endpoint.text))[0]
        cost = self.ui.number(s, (410, 140, 480, 180))
        stamina = self.ui.number(s, (635, 140, 725, 180))
        if cost is None or stamina is None or cost <= 0:
            raise EventUIError('自动推进体力消耗或余额未确认')
        if cost > stamina or self.spent + cost > self.budget:
            raise EventUIError('自动推进体力不足或超出首通体力上限，未开战')
        if self.target is not None and self.target != target:
            raise EventUIError('自动推进终点发生变化，停止追加挑战')
        self.target = target
        return {'target': target, 'max_cost': cost, 'stamina_before': stamina}

    def advance(self):
        self.audit_party()
        self.ui.expect_click('下一步', (740, 420, 940, 510), exact=True)
        s = self.ui.wait(lambda f: f.find('自动推进设定', (200, 0, 750, 80)), '自动推进设定')
        plan = self.plan(s)
        self.ui.save('first_clear_plan', s)
        setting = s.find('立即发动', (300, 265, 440, 320), exact=True)
        if setting is None:
            raise EventUIError('自动推进立即发动选项无法识别')
        self.ui.click(setting)
        s = self.ui.capture()
        # The radio circle must visibly be selected before committing stamina.
        hsv = cv.cvtColor(s.image[279:306, 274:301], cv.COLOR_BGR2HSV)
        if np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 125)
                   & (hsv[:, :, 1] > 80)) < .3:
            raise EventUIError('自动推进立即发动选项未确认')
        if self.plan(s) != plan:
            raise EventUIError('自动推进确认前体力或终点发生变化')
        start = s.find('战斗开始', (480, 440, 710, 520), exact=True)
        if not s.blue_button(start):
            raise EventUIError('自动推进战斗开始按钮不可用')
        self.r.report.setdefault('first_clear_runs', []).append(plan)
        self.r.report_progress('活动首通 · 自动推进至 ' + plan['target'])
        self.ui.click(start)
        end = time.monotonic() + self.segment_timeout
        while time.monotonic() < end:
            self.r.check_deadline()
            s = self.ui.capture()
            result = auto_advance_result(self.ui, s)
            if result:
                if result['spent'] > plan['max_cost']:
                    raise EventUIError('自动推进结算消耗超出预览')
                plan['result'] = result
                plan['end_reason'] = result['reason']
                self.ui.expect_click('确认', (350, 340, 615, 410), exact=True)
                return plan
            if s.find('体力回复|体力恢复|购买体力|战斗失败|挑战失败'):
                raise EventUIError('自动推进受阻，未追加消费：' + s.text())
            # Native auto-advance owns battle/result buttons. Only known story
            # interruptions are handled here; no replay on an uncertain result.
            if self.b.combat.match('btn_menu_text', s) or s.find(r'\d:\d{2}', (750, 0, 850, 55)):
                time.sleep(1)
                continue
            if self.r.entry_dialog(s) or self.r.story_dialog(s):
                continue
            time.sleep(1)
        self.ui.save('first_clear_timeout')
        raise EventUIError('自动推进超时，保留当前状态，禁止重复开战')

    def open_formation(self, name):
        self.r.quests()
        for _ in range(12):
            s = self.ui.capture()
            row = s.find(re.escape(name), (580, 150, 850, 450), exact=True)
            if row:
                self.ui.click(row)
                break
            self.ui.swipe((840, 180), (840, 430))
        else:
            raise EventUIError('找不到待首通关卡 ' + name)
        s = self.ui.wait(lambda f: f.find(re.escape(name), (30, 20, 570, 85), exact=True), '首通关卡详情')
        if not s.find('自动推进下一个关卡', (640, 265, 940, 320)):
            raise EventUIError('首通关卡未显示已适配的自动推进选项')
        hsv = cv.cvtColor(s.image[316:351, 695:735], cv.COLOR_BGR2HSV)
        if np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 125)
                   & (hsv[:, :, 1] > 80)) < .15:
            self.ui.click((715, 334))
        self.ui.expect_click('挑战', (740, 420, 945, 510), exact=True)
        self.ui.wait(lambda f: f.find('队伍编组', (250, 0, 730, 70)), '首通编队')

    def run(self):
        previous = None
        for _ in range(15):
            self.r.check_deadline()
            catalog = self.b.quest_catalog()
            self.r.report['first_clear_catalog'] = catalog
            missing = [name for name, stars in catalog.items() if stars == 0]
            if not missing:
                if not any('H-' in name for name in catalog):
                    raise EventUIError('尚未观察到困难关卡，不能确认全部首通')
                if self.target and '活动关卡' + self.target not in catalog:
                    raise EventUIError('最终关卡未在通关复核列表中找到')
                recovered = self.r.report.get('recovered_first_clear')
                if recovered and recovered['final'] and len(catalog) < recovered['cleared']:
                    raise EventUIError('首通复核关卡数量少于结算回执')
                self.r.log(f'已核对 {len(catalog)} 个活动关卡全部通关')
                self.r.home()
                return
            signature = tuple(sorted(catalog.items()))
            if signature == previous:
                raise EventUIError('首通后关卡进度未变化，停止重复消费')
            previous = signature
            name = min(missing, key=lambda n: ('H-' in n, int(n.split('-')[-1])))
            self.current = name
            self.r.report_progress('活动首通 · ' + name)
            self.open_formation(name)
            plan = self.advance()
            self.r.home()
            s = self.r.quests()
            balance = s.find(r'\d+/\d+', (650, 0, 785, 45))
            if balance is None:
                raise EventUIError('首通后体力余额无法核对')
            remaining = int(re.search(r'(\d+)/\d+', normalized(balance.text))[1])
            spent = plan['stamina_before'] - remaining
            if not 0 < spent <= plan['max_cost']:
                raise EventUIError('首通后的体力变化与计划不符')
            if spent != plan['result']['spent']:
                raise EventUIError('首通体力余额变化与结算回执不符')
            self.spent += spent
            plan.update(stamina_after=remaining, spent=spent)
        raise EventUIError('首次过图达到步骤上限')
