"""Map revival flow shared by every map-style edition.

Stage counts, memory titles and boss names are read live; coordinates are
normalized; unknown branches stop."""
import re
from dataclasses import replace
from pcrscript.run_session import clock as time

import cv2 as cv
import numpy as np

from ..game_ui.event_layout import event_layout, map_dialogue, legacy_hub
from ..game_ui.screen import EventUIError, normalized
from .event_battle import EventCombat
from .strategy_trial import TrialFormation
from .strategy_party_pool import boss_parties, next_boss_party
from ..game_ui.abyss_subjugation import sweep_confirmation, sweep_cost
from ..templates import ImageTemplate


class StaminaShort(EventUIError):
    """The native auto-advance dialog says stamina must be refilled."""


# Each edition names its memory list after its own story ("水都的回忆"...).
MEMORIES = r'.{1,10}的回忆'


class RevivalMap:
    def __init__(self, runner):
        self.r = runner
        self.ui = runner.ui
        self.formation = TrialFormation(self.ui)
        self.memory_title = MEMORIES  # Replaced by the live card title.
        self.special_open = False  # SP row seen on the hub (VH already cleared).
        runner.combat_return = lambda s: event_layout(s) == 'map'
        runner.combat_dialog = self.dialog

    def dialog(self, s):
        if s.find('收取报酬', (250, 0, 710, 70), exact=True):
            self.ui.expect_click('关闭', (350, 445, 615, 515), exact=True)
            return True
        if map_dialogue(s):
            self.ui.click((775, 495))
            return True
        return False

    def home(self):
        hubs = 0
        for _ in range(45):
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find('正在进行数据连接|加载中'):
                time.sleep(.6)
                continue
            if self.dialog(s) or self.r.entry_dialog(s) or self.r.story_dialog(s):
                continue
            if legacy_hub(s):
                hubs += 1
                # Clearing VH dims the hub and points at the SP row; only that
                # row accepts taps until the guide is followed (2026-11-15).
                guide = s.find('特别', (680, 130, 920, 200)) if hubs > 2 and hubs % 2 else None
                self.ui.click(guide or s.find('活动关卡', (450, 150, 670, 235)))
                continue
            if event_layout(s) == 'map':
                time.sleep(.6)
                stable = self.ui.capture()
                if event_layout(stable) == 'map' and not map_dialogue(stable):
                    return stable
                continue
            if s.find('BOSS详情|自动推进设定|队伍编组', (0, 0, 750, 80)) or s.find('剩余挑战次数'):
                self.ui.expect_click('取消', (200, 420, 930, 525), exact=True)
            elif s.find('自动推进报酬一览|自动推进结束|区域解锁|活动任务'):
                item = s.find('关闭|确认|确定', (200, 300, 800, 525), exact=True)
                if item:
                    self.ui.click(item)
                elif s.find('活动任务', (0, 0, 300, 70)):
                    self.ui.click((32, 30))
            elif s.find('获得道具|伤害报告|战斗胜利'):
                self.ui.expect_click('下一步', (700, 400, 950, 530), exact=True)
            else:
                time.sleep(.6)
        self.ui.save('map_home_unknown')
        raise EventUIError('无法返回复刻地图')

    STAGE = re.compile(r'(\d{1,2})-(\d{1,2})')

    # Outlined node labels are mostly missed by full-frame OCR; overlapping
    # tiles read them reliably (2026-11-14, two different map editions).
    LABEL_TILES = [(x, y, min(x+260, 960), y+110) for y in range(150, 400, 90) for x in range(0, 760, 200)]

    def stage_labels(self, s):
        """Stage numbers visible on the map, keyed by (chapter, stage)."""
        found = {}
        items = list(s.all(r'^\d{1,2}-\d{1,2}$', (0, 120, 960, 470)))
        for roi in self.LABEL_TILES:
            items += self.ui.read_region(s, roi, classify=False).all(r'^\d{1,2}-\d{1,2}$')
        for item in items:
            m = self.STAGE.fullmatch(normalized(item.text))
            if m:
                found.setdefault((int(m[1]), int(m[2])), item)
        return found

    def map_label(self, s, label):
        """Outlined boss-node names need the same tiled re-read as stages."""
        for roi in self.LABEL_TILES:
            item = self.ui.read_region(s, roi, classify=False).find(label, roi, exact=True)
            if item:
                return item
        return None

    @staticmethod
    def map_signature(labels):
        # The highest node and where it sits; tolerant of a missed label.
        if not labels:
            return None
        key = max(labels)
        return key, round(labels[key].center[0]/40)

    def scan_pages(self, swipe_from, swipe_to, limit=10):
        """Swipe until the stage labels stop moving; yield each settled page."""
        previous = None
        for _ in range(limit):
            s = self.home()
            labels = self.stage_labels(s)
            signature = self.map_signature(labels)
            yield s, labels
            if signature and signature == previous:
                return
            previous = signature
            self.ui.swipe(swipe_from, swipe_to)

    def clear_quests(self, difficulty):
        """Auto-advance from the game's "next stage" marker, then prove the
        highest stage on this map is cleared. Works for any stage count."""
        self.home()
        self.ui.expect_click(difficulty, (700, 55, 950, 105), exact=True)
        self.home()
        next_marker = ImageTemplate('revival_next', threshold=.8)
        for _ in self.scan_pages((220, 250), (760, 250)):
            pass  # Rewind to the start of the map.
        for s, _ in self.scan_pages((760, 250), (220, 250)):
            marker_text = s.find('下一关', (0, 110, 960, 400), exact=True)
            marker = marker_text.center if marker_text else next_marker.match(s.image)
            if marker:
                self.ui.click((marker[0], marker[1]+80))
                self.ui.wait(lambda f: f.find('自动推进下一个关卡'), '未通关关卡详情')
                # Require the blue check rather than toggling remembered settings.
                f = self.ui.capture()
                check = cv.cvtColor(f.image[316:351, 695:735], cv.COLOR_BGR2HSV)
                enabled = np.mean((check[:, :, 0] > 85) & (check[:, :, 0] < 125) & (check[:, :, 1] > 80)) > .15
                if not enabled:
                    self.ui.click((715, 334))
                self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
                self.ui.wait(lambda f: f.find('队伍编组'), '首通编队')
                self.ui.expect_click('下一步', (720, 420, 950, 525), exact=True)
                self.ui.wait(lambda f: f.find('自动推进设定'), '自动推进')
                try:
                    self.auto_advance()
                except StaminaShort:
                    if getattr(self, 'house_collected', False):
                        raise
                    if self.collect_house_stamina().get('empty'):
                        raise
                    return self.clear_quests(difficulty)
                break
        return self.verify_last()

    def collect_house_stamina(self):
        """Once per task: take produced Guild House stamina, then re-enter."""
        from ..game_ui.guild_house import collect_produced_stamina
        self.house_collected = True
        result = collect_produced_stamina(self.ui, self.home())
        self.r.report.setdefault('house_stamina', []).append(result)
        self.r.log(f'公会之家体力：{result}')
        self.r.enter()
        return result

    def verify_last(self):
        """The highest numbered stage on the map must show stars in its detail."""
        last = None
        for _, labels in self.scan_pages((760, 250), (220, 250)):
            # Keep the latest position: later pages scroll the same node.
            if labels and (last is None or max(labels) >= last[0]):
                key = max(labels)
                last = (key, labels[key].center)
        if last is None:
            raise EventUIError('未读到地图关卡编号，无法复核最终关卡')
        (chapter, number), center = last
        stage = f'{chapter}-{number}'
        self.ui.click((center[0], center[1]-55))
        s = self.ui.wait(lambda f: f.find('剩余挑战次数'), '最终关卡详情')
        if not s.find(re.escape(stage), (40,25,560,80)):
            raise EventUIError('关卡详情编号与最终关卡不一致')
        hsv = cv.cvtColor(s.image, cv.COLOR_BGR2HSV)
        stars = sum(np.mean((hsv[25:48, x-8:x+9, 0] >= 15) &
                           (hsv[25:48, x-8:x+9, 0] <= 40) &
                           (hsv[25:48, x-8:x+9, 1] > 100)) > .5 for x in (765, 827, 890))
        self.ui.save('last_stage_verified', s)
        self.ui.expect_click('取消', (550, 420, 755, 525), exact=True)
        if not stars:
            raise EventUIError('最终关卡星数未确认，保留待完成')
        self.r.log(f'{stage} 最终关卡已通过，实测星数 {stars}')
        return self.home()

    def normal_boss_from_detail(self):
        s = self.ui.capture()
        if not s.find('BOSS详情', (0, 0, 750, 80)) or not s.find('普通', (0, 0, 300, 90), exact=True):
            raise EventUIError('未确认普通首领详情，不能用当前队伍开战')
        defeated = self.ui.number(s, (891, 28, 926, 56))
        if defeated is None:
            raise EventUIError('普通首领讨伐数未知')
        if defeated > 0:
            return self.home()
        self.ui.save('normal_boss_plan', s)
        self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
        self.ui.wait(lambda f: f.find('队伍编组', (250, 0, 750, 80)), '普通首领编队')
        result = EventCombat(self.r).run()
        self.r.report['battles'].append({'boss': 'normal', **vars(result)})
        if result.outcome != 'settled':
            raise EventUIError('普通首领未成功：'+result.reason)
        self.verify_boss_defeated('普通')
        return self.home()

    def hard_trial_from_detail(self):
        s = self.ui.capture()
        if not s.find('BOSS详情', (0, 0, 750, 80)):
            raise EventUIError('未确认困难首领详情')
        count = self.ui.number(s, (891, 28, 926, 56))
        if count is None:
            raise EventUIError('首领已讨伐次数未知')
        if count > 0:
            return self.home()
        if self.r.state.data.get('hard_trial_started'):
            raise EventUIError('本期困难首领已试打过，不能重复开战')
        if self.r.event.extras['event_id'] != self.r.options.get('hard_trial_event_id'):
            # Not authorized for this edition: leave it, keep the rest going.
            self.r.report['pending'].append('困难首领未讨伐：本期未授权当前队伍试打（RevivalEvent.hard_trial_event_id）')
            self.hard_boss_open = True
            return self.home()
        self.r.report['hard_trial_started'] = True
        self.r.state.save(self.r.report)
        self.ui.save('hard_trial_plan', s)
        self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
        self.ui.wait(lambda f: f.find('队伍编组'), '困难首领编队')
        result = EventCombat(self.r).run()
        self.r.report['battles'].append({'boss': 'hard', 'source': '用户授权本期一次试打', **vars(result)})
        self.r.state.save(self.r.report)
        if result.outcome != 'settled':
            raise EventUIError('困难首领试打未成功：'+result.reason)
        self.verify_boss_defeated('困难')
        return self.home()

    def verify_boss_defeated(self, label):
        detail = self.boss_detail(label)
        count = self.ui.number(detail, (891,28,926,56))
        if count is None or count < 1:
            raise EventUIError(label+'首领结算后未确认讨伐数增加')

    def auto_advance(self):
        """Start only from a visible native auto-advance settings dialog."""
        s = self.ui.capture()
        if not s.find('自动推进设定', (200, 0, 750, 80)):
            raise EventUIError('未确认自动推进设置')
        if not s.find('自动推进至活动关卡') or not s.find('消耗体力'):
            raise EventUIError('自动推进范围和消费无法确认')
        self.ui.save('auto_plan', s)
        if (not s.find('战斗开始', (480, 450, 710, 520), exact=True)
                and s.find('必须回复体力')):
            # Never refill: the only options left are buying stamina or a
            # partial run. Back out and let the caller decide.
            self.ui.expect_click('取消', (150, 450, 370, 520), exact=True)
            raise StaminaShort('复刻推进体力不足：'+s.text((40, 110, 920, 200)))
        self.ui.expect_click('不停止', (470, 265, 625, 320), exact=True)
        self.ui.expect_click('立即发动', (260, 360, 450, 425), exact=True)
        self.ui.expect_click('战斗开始', (480, 450, 710, 520), exact=True)
        end = time.monotonic()+600
        while time.monotonic() < end:
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find('自动推进结束'):
                self.ui.save('auto_finished', s)
                if not s.find('由于是最终关卡'):
                    raise EventUIError('自动推进提前停止：'+s.text())
                self.ui.expect_click('确认', (250, 350, 750, 525), exact=True)
                return self.home()
            if s.find('体力回复|体力恢复|战斗失败|挑战失败'):
                raise EventUIError('自动推进受阻：'+s.text())
            # The game itself advances through victory and next-step screens.
            time.sleep(1)
        self.ui.save('auto_timeout')
        raise EventUIError('自动推进超时，停止追加操作')

    def sweep_hard(self):
        """Spend each hard stage's daily attempts with sweep tickets: hard
        stages drop the boss challenge tickets VH/SP consume (2026-11-15).
        Walk the stages with the detail's own next arrow instead of OCR-ing
        every map label; past the last stage the tap closes the detail."""
        self.ui.expect_click('困难', (700, 55, 950, 105), exact=True)
        first = None
        for _, labels in self.scan_pages((220, 250), (760, 250)):
            if labels:
                key = min(labels)
                if first is None or key <= first[0]:
                    first = (key, labels[key].center)
        if first is None:
            raise EventUIError('困难地图未读到关卡编号，无法扫荡')
        self.ui.click((first[1][0], first[1][1]-55))
        s = self.ui.wait(lambda f: f.find('剩余挑战次数'), '困难关卡详情')
        for _ in range(10):
            if self.detail_stage(s)[1] == 1:
                break
            self.ui.click((25, 275))  # Previous stage.
            s = self.ui.wait(lambda f: f.find('剩余挑战次数'), '上一困难关卡')
        else:
            raise EventUIError('未能定位困难第一关')
        swept = {}
        for _ in range(40):
            self.r.check_deadline()
            chapter, number = self.detail_stage(s)
            stage = f'{chapter}-{number}'
            try:
                count = self.sweep_stage(s, stage)
            except StaminaShort:
                # The purchase prompt is cancelled; close the stage detail too.
                self.record_sweeps(swept)
                self.ui.wait(lambda f: f.find('剩余挑战次数') and not f.find('体力回复|购买体力'),
                             '困难关卡详情')
                self.ui.expect_click('取消', (550, 420, 755, 525), exact=True)
                raise
            if count:
                swept[stage] = count
            if count and self.short_sweep:
                # MAX was capped by stamina: this stage still has attempts.
                short, self.short_sweep = self.short_sweep, None
                self.record_sweeps(swept)
                self.ui.expect_click('取消', (550, 420, 755, 525), exact=True)
                raise StaminaShort(short)
            self.ui.click((940, 275))  # Next stage; closes the detail after the last.
            s = self.ui.wait(lambda f: event_layout(f) == 'map' or (
                f.find('剩余挑战次数') and self.detail_stage(f) != (chapter, number)), '下一困难关卡')
            if not s.find('剩余挑战次数'):
                break
        else:
            raise EventUIError('困难扫荡达到步骤上限')
        self.record_sweeps(swept)
        return self.home()

    def record_sweeps(self, swept):
        if not swept:
            return
        total = self.r.report.setdefault('hard_sweeps', {})
        for stage, count in swept.items():
            total[stage] = total.get(stage, 0)+count
        self.r.log('困难扫荡 ' + '、'.join(f'{k} × {v}' for k, v in swept.items()))
        swept.clear()

    def detail_stage(self, s):
        title = s.find(r'\d{1,2}-\d{1,2}', (40, 25, 560, 80))
        m = self.STAGE.search(normalized(title.text)) if title else None
        if not m:
            raise EventUIError('困难关卡详情编号无法读取')
        return int(m[1]), int(m[2])

    REMAINING = (845, 400, 935, 428)
    short_sweep = None

    def sweep_stage(self, s, stage):
        """Sweep one opened hard-stage detail; returns the sweep count."""
        remaining = s.find(r'[0-3]/3', self.REMAINING)
        if remaining is None:
            remaining = self.ui.read_region(s, self.REMAINING, classify=False).find(r'[0-3]/3')
        if remaining is None:
            raise EventUIError(f'{stage} 剩余挑战次数无法确认')
        left = int(normalized(remaining.text)[0])
        if left == 0:
            return 0
        self.ui.expect_click('MAX', (840, 305, 925, 360), exact=True)
        s = self.ui.wait(lambda f: f.find(r'使用\d+张', (690, 310, 830, 355)), '扫荡次数')
        time.sleep(.4)
        s = self.ui.capture()
        button = s.find(r'使用\d+张', (690, 310, 830, 355))
        quantity = int(re.search(r'\d+', normalized(button.text))[0]) if button else 0
        if not 1 <= quantity <= left or not s.blue_button(button):
            # MAX is capped by stamina; never refill, never exceed the counter.
            self.ui.expect_click('取消', (550, 420, 755, 525), exact=True)
            raise StaminaShort(f'困难 {stage} 扫荡体力不足')
        self.ui.save(f'hard_sweep_plan_{stage}', s)
        self.ui.click(button)
        confirmed = False
        for _ in range(60):
            self.r.check_deadline()
            f = self.ui.capture()
            if f.find('正在进行数据连接|加载中'):
                time.sleep(.5)
            elif not confirmed and sweep_confirmation(f):
                # 扫荡券确认 lists 消耗体力/消耗券; the tickets must equal the plan.
                self.ui.save(f'hard_sweep_confirm_{stage}', f)
                if sweep_cost(self.ui, f, '消耗券') != quantity:
                    self.ui.expect_click('取消', (290, 340, 445, 405), exact=True)
                    raise EventUIError(f'{stage} 扫荡确认的扫荡券数量与计划不符，未确认')
                self.ui.expect_click('确认', (520, 340, 665, 405), exact=True)
                confirmed = True
            elif not confirmed and f.find('体力回复|购买体力'):
                self.ui.save('hard_sweep_purchase', f)
                self.ui.expect_click('取消', (200, 300, 760, 520), exact=True)
                # Never buy; the caller collects Guild House stamina once.
                raise StaminaShort(f'困难 {stage} 扫荡体力不足，已取消购买')
            elif f.find('限定商店|限时商店'):
                self.ui.expect_click('取消|关闭', (200, 300, 800, 525), exact=True)
            elif (confirmed and f.find('剩余挑战次数') and f.find('取消', (550, 420, 755, 525), exact=True)
                    and not f.find(r'扫荡结果|扫荡完成|跳过完毕|合计获得报酬|第\d+次')):
                # The detail behind the receipt already shows 0/3; wait until
                # the receipt is closed and the detail's own cancel is back.
                after = f.find(r'[0-3]/3', self.REMAINING) or self.ui.read_region(
                    f, self.REMAINING, classify=False).find(r'[0-3]/3')
                if after is None or int(normalized(after.text)[0]) != left-quantity:
                    time.sleep(.5)  # Counter refreshes a moment after receipts.
                    continue
                self.ui.save(f'hard_sweep_done_{stage}', f)
                self.short_sweep = (f'困难 {stage} 体力只够扫荡 {quantity}/{left} 次'
                                    if quantity < left else None)
                return quantity
            elif confirmed:
                button_ = f.find('跳过完毕|跳过|确认|确定|关闭|OK|下一步', (200, 300, 950, 535), exact=True)
                if button_ and (normalized(button_.text) == '跳过完毕' or f.find('扫荡|获得道具|报酬|升级|等级')):
                    self.ui.click(button_)
                else:
                    time.sleep(.5)
            else:
                time.sleep(.5)
        self.ui.save('hard_sweep_timeout')
        raise EventUIError(f'{stage} 扫荡结算未确认，停止重复扫荡')

    def run(self):
        self.r.report_progress('复刻地图 · 普通关卡')
        try:
            self.clear_quests('普通')
        except StaminaShort as error:
            # Stories, missions and exchange cost no stamina; keep them.
            self.r.report['pending'].append(str(error)+'；普通关卡及之后的困难、高难、特别留待体力恢复后接续')
            self.home()
            self.r.report_progress('复刻地图 · 领取奖励')
            return self.rewards()
        normal = self.boss_detail('普通')
        count = self.ui.number(normal, (891, 28, 926, 56))
        if count is None:
            raise EventUIError('普通首领讨伐次数未知')
        if count == 0:
            self.normal_boss_from_detail()
        else:
            self.home()
        self.r.report_progress('复刻地图 · 困难关卡')
        try:
            self.clear_quests('困难')
        except StaminaShort as error:
            self.r.report['pending'].append(str(error)+'；困难关卡与困难首领留待体力恢复后接续')
            # VH/SP stay locked until Hard is cleared: go straight to rewards.
            self.r.report['pending'].append('高难与特别首领需先通关困难，留待接续')
            self.home()
            self.r.report_progress('复刻地图 · 领取奖励')
            return self.rewards()
        self.boss_detail('困难')
        self.hard_boss_open = False
        self.hard_trial_from_detail()
        # Cleared Hard stages are swept even while the Hard boss stays
        # unauthorized: the tickets they drop wait for VH/SP.
        self.r.report_progress('复刻地图 · 困难扫荡')
        try:
            self.sweep_hard()
        except StaminaShort as error:
            if not getattr(self, 'house_collected', False) and not self.collect_house_stamina().get('empty'):
                try:
                    self.sweep_hard()
                except StaminaShort as again:
                    self.r.report['pending'].append(str(again)+'；未购买体力')
            else:
                self.r.report['pending'].append(str(error)+'；未购买体力')
            self.home()
        if self.hard_boss_open:
            # Observed 2026-11-14: VH stays padlocked until Hard is beaten.
            self.r.report['pending'].append('高难与特别首领需先讨伐困难首领，留待接续')
            self.r.report_progress('复刻地图 · 领取奖励')
            return self.rewards()
        if self.special_complete():
            # In this event SP unlocks after VH; VH becomes locked after its
            # daily clear and cannot be reopened just to inspect the counter.
            self.r.log('特别首领已通过，表演赛已解锁；前置高难亦已完成')
            self.r.report_progress('复刻地图 · 领取奖励')
            return self.rewards()
        for label, difficulty in [('高难', 'very_hard'), ('特别', 'special')]:
            if difficulty == 'very_hard' and self.special_open:
                # The SP row appears only after VH is cleared, and the VH node
                # is padlocked again afterwards (2026-11-15).
                self.r.log('特别首领已出现，高难已通过，跳过')
                continue
            self.r.report_progress(f'复刻地图 · {label}首领')
            try:
                self.sourced_boss(label, difficulty)
            except EventUIError as error:
                if self.r.report.get('pending_boss'):
                    raise  # Ticket spent, result unknown: keep the scene.
                from pcrscript.run_session import failure
                failure(error)
                self.r.report['pending'].append(str(error))
                self.hub()  # Continue rewards only after a known safe return.
        self.r.report_progress('复刻地图 · 领取奖励')
        self.rewards()

    def special_complete(self):
        self.special_open = False
        self.hub()
        for _ in range(4):
            s = self.ui.capture()
            if s.find('表演赛', (675,120,950,305)):
                self.ui.save('special_complete', s)
                return True
            if s.find('特别', (675,120,950,305), exact=True):
                self.special_open = True
                return False
            # The boss list has its own scroll; re-entry resets it to Normal.
            self.ui.swipe((820,285), (820,145))
        return False  # Not yet unlocked is not proof of completion.

    def rewards(self):
        self.read_stories(False)
        self.read_stories(True)
        for round_index in range(5):
            self.missions()
            self.exchange()
            if round_index > 0 and self.mission_claims == 0:
                return
        raise EventUIError('兑换后活动任务仍有新奖励，达到结算循环上限')

    def read_stories(self, memories=False, already_open=False):
        if not already_open:
            s = self.hub()
            if memories:
                # The card below 活动关卡 is named per edition ("水都的回忆",
                # "阿尔凯斯炼金堂 业务日志"); its first line titles the list.
                card = s.all('.+', (450, 240, 680, 310))
                if not card:
                    raise EventUIError('活动首页回忆入口卡片未识别')
                self.memory_title = re.escape(normalized(card[0].text))
                self.ui.click((559, 274))
            else:
                self.ui.click((818, 348))
        previous = None
        unchanged = 0
        opened = 0
        prepared = False
        hub_seen = 0
        for step in range(400):
            self.r.check_deadline()
            s = self.ui.capture()
            in_list = (s.find(self.memory_title, (0, 0, 400, 70)) if memories else
                       s.find('活动剧情一览', (250, 0, 710, 70)))
            # The list's instructional text says 获得奖励; it is not a reward
            # popup and must not be closed by the generic story dialog handler.
            if self.dialog(s) or (not in_list and self.r.story_dialog(s)):
                continue
            if s.find('加载中|下载中|正在进行数据连接'):
                time.sleep(.7)
                continue
            if s.find('即将下载新增数据') and s.find('是否播放语音'):
                # A new story first asks to download its data. Without an
                # answer the list looked unchanged and the story stayed unread
                # (2026-11-15). Take the smaller voiceless download.
                self.ui.save('story_download', s)
                self.ui.expect_click('无语音', (200, 250, 760, 520), exact=True)
                continue
            if memories and in_list and s.find('前往一览', (840, 400, 960, 500)):
                # Reading view: a 新内容 badge over 上页/下页 marks the adjacent
                # entry unread; otherwise go back to the book (2026-11-15).
                side = next((x for x, roi in ((915, (860, 170, 960, 235)), (45, (0, 170, 100, 235)))
                             if s.find('新内容', roi)), None)
                if side:
                    self.ui.save(f'memory_{opened:02}', s)
                    self.ui.click((side, 255))
                    opened += 1
                else:
                    self.ui.expect_click('前往一览', (840, 400, 960, 500), exact=True)
                previous = None
                unchanged = 0
                time.sleep(.6)
                continue
            if in_list:
                if not prepared:
                    for _ in range(6):
                        self.ui.swipe((830,180) if memories else (650,170), (830,460) if memories else (650,400))
                    prepared = True
                    continue
                # The memory book's newest entry can sit on the left page as
                # a note card, the rest on the right (2026-11-15).
                roi = (150, 60, 960, 510) if memories else (250, 115, 690, 435)
                new = s.find('新内容|NEW|未读', roi)
                if new:
                    self.ui.save(f'{"memory" if memories else "story"}_{opened:02}', s)
                    # A badge over 下页 flags an unread entry on the next page.
                    x = (915 if new.center[0] > 860 else new.center[0]+80) if memories else 500
                    self.ui.click((x, 255 if x == 915 else min(new.center[1]+40, roi[3]-15)))
                    opened += 1
                    previous = None
                    unchanged = 0
                    continue
                signature = s.text(roi)
                unchanged = unchanged+1 if signature == previous else 0
                if unchanged >= 2:
                    self.ui.save('memories_checked' if memories else 'stories_checked', s)
                    if memories:
                        self.ui.click((32,30))
                    else:
                        self.ui.expect_click('关闭', (350, 445, 615, 515), exact=True)
                    self.r.log(f'{"活动回忆" if memories else "活动剧情"}已检查，本轮打开{opened}篇')
                    return self.hub()
                previous = signature
                self.ui.swipe((830, 460) if memories else (650,400), (830,170) if memories else (650,170))
            elif legacy_hub(s):
                hub_seen += 1
                if memories and not prepared and hub_seen >= 3:
                    # A locked card (heart padlock) simply does not open.
                    self.ui.save('memories_locked', s)
                    self.r.report['pending'].append('活动回忆入口尚未解锁，留待接续')
                    return s
                self.ui.click((559,274) if memories else (818,348))
            else:
                time.sleep(.5)
        raise EventUIError('复刻剧情达到步骤上限，保留未完成状态')

    def missions(self, already_open=False):
        self.mission_claims = 0
        if not already_open:
            self.hub()
            self.ui.click((910,437))
        self.ui.wait(lambda s: s.find('活动任务', (0,0,300,70)), '活动任务', handle=self.dialog)
        for tab in ('每日','普通','特别','称号'):
            s = self.ui.capture()
            if self.dialog(s):
                s = self.ui.capture()
            self.ui.expect_click(tab, (300,0,950,50), exact=True)
            for _ in range(12):
                s = self.ui.capture()
                if self.dialog(s):
                    continue
                if s.find('正在进行数据连接'):
                    time.sleep(.5)
                    continue
                button = s.find('全部收取', (700,405,955,475), exact=True)
                if not button:
                    raise EventUIError('无法确认活动任务全部收取按钮')
                if not s.blue_button(button):
                    self.ui.save('missions_'+tab, s)
                    break
                self.ui.click(button, delay=1.5)
                self.mission_claims += 1
            else:
                raise EventUIError(tab+'任务领取达到上限')
        self.r.log('每日、普通、特别、称号的可领取任务已清空')
        return self.hub()

    def exchange(self, already_open=False):
        if not already_open:
            self.hub()
            self.ui.click((574,347))
        before = None
        consume = None
        total = 0
        for _ in range(240):
            self.r.check_deadline()
            s = self.ui.capture()
            if s.find('正在进行数据连接|加载中'):
                time.sleep(.7)
                continue
            if s.find('重置完毕') and s.find('重置了报酬列表'):
                self.ui.expect_click('确认', (250,300,730,515), exact=True)
                continue
            if s.find(r'已获得第\d+轮报酬列表中的全部报酬') and s.find('切换到下一个报酬列表'):
                self.ui.expect_click('确认', (250,350,730,515), exact=True)
                continue
            if s.find('当前的列表', (250,15,710,65), exact=True):
                remaining = s.all(r'剩余\d+/\d+', (590,85,705,430))
                if len(remaining) != 2 or any(not normalized(item.text).startswith('剩余0/') for item in remaining):
                    raise EventUIError('奖池未确认全部抽空，不提前重置报酬')
                self.ui.save('exchange_round_empty', s)
                self.ui.expect_click('重置', (350,445,615,515), exact=True)
                continue
            if s.find('查看已获得道具', (300,390,660,465)):
                self.ui.expect_click('查看已获得道具', (300,390,660,465), exact=True)
                continue
            if s.find('获得的报酬将会直接增加到持有道具中'):
                cancel = s.find('取消|确认', (250,390,710,465), exact=True)
                if cancel:
                    self.ui.click(cancel)
                else:
                    time.sleep(.7)  # Pool completion can replace this result mid-transition.
                continue
            if s.find('讨伐证交换', (0,0,300,65)) and s.find('讨伐证', (725,420,845,470), exact=True):
                current = self.ui.number(s, (850,425,943,462))
                if current is None:
                    single = s.find('1次交换', (520,330,710,385), exact=True)
                    batch = s.find(r'\d+次交换', (730,330,932,385))
                    if single and batch and not s.blue_button(single) and not s.blue_button(batch):
                        zero = self.ui.number(s, (909,431,929,454))
                        if zero == 0:
                            current = 0
                if current is None:
                    raise EventUIError('讨伐证余额无法确认')
                if before is not None:
                    if before-current != consume:
                        raise EventUIError('实际讨伐证扣除与按钮消费不一致，停止追加兑换')
                    total += consume
                if current == 0:
                    self.ui.save('exchange_empty', s)
                    self.r.log(f'本轮兑换 {total} 张讨伐证，余额已确认 0')
                    return self.hub()
                amount = s.find(r'使用\d+张', (730,383,932,419))
                button = s.find(r'\d+次交换', (730,330,932,385))
                if button and int(re.search(r'\d+', normalized(button.text))[0]) > current:
                    # Below one batch the batch button greys out at 100 and
                    # only the single exchange stays live (2026-11-15).
                    amount = s.find('使用1张', (520,383,710,419), exact=True)
                    button = s.find('1次交换', (520,330,710,385), exact=True)
                    if not (button and s.blue_button(button)):
                        raise EventUIError('讨伐证不足一批且单次交换不可用')
                if not amount or not button:
                    raise EventUIError('无法核验批量兑换次数和讨伐证消费')
                consume = int(re.search(r'\d+', normalized(amount.text))[0])
                if consume <= 0 or consume > min(current, 100) or int(re.search(r'\d+', normalized(button.text))[0]) != consume:
                    raise EventUIError('批量兑换消费超出余额')
                before = current
                self.ui.save('exchange_plan', s)
                self.ui.click(button, delay=1.5)
            else:
                time.sleep(.7)
        raise EventUIError('讨伐证兑换达到步骤上限')

    def boss_detail(self, label):
        # A boss defeat can start an unlock story on the map right after the
        # tap; advance it and tap the entry again instead of waiting blindly.
        for attempt in range(3):
            s = self.hub() if label == '特别' else self.home()
            target = s.find(label, (680, 130, 940, 305) if label == '特别' else (0, 120, 960, 380), exact=True)
            if not target and label != '特别':
                target = self.map_label(s, label)
            if not target and label != '特别':
                # Hard and VH nodes sit on the Hard tab's map (2026-11-14).
                tab = s.find('困难' if label != '普通' else '普通', (700, 55, 950, 105), exact=True)
                if tab:
                    self.ui.click(tab)
                    s = self.home()
                    target = s.find(label, (0, 120, 960, 380), exact=True) or self.map_label(s, label)
            if not target:
                raise EventUIError(f'未发现{label}首领入口')
            self.ui.click(target if label == '特别' else (target.center[0], target.center[1]-60))
            try:
                s = self.ui.wait(lambda f: f.find('BOSS详情', (0, 0, 300, 80)), '首领详情', timeout=10,
                                 handle=lambda f: self.dialog(f) or self.r.story_dialog(f))
                break
            except EventUIError:
                if attempt == 2:
                    raise
        pattern = label + (r'难度/阶段[123]' if label == '特别' else '')
        badge = s.find(pattern, (185,25,425,65), exact=True)
        if not badge:
            badge = self.ui.read_region(s, (185,25,425 if label == '特别' else 290,65)).find(pattern, exact=True)
        if not badge:
            raise EventUIError(f'未确认首领难度为{label}')
        return s

    def hub(self):
        for _ in range(60):
            self.r.check_deadline()
            s = self.ui.capture()
            if self.dialog(s) or self.r.story_dialog(s) or self.r.entry_dialog(s):
                continue
            if legacy_hub(s):
                return s
            if s.find('活动剧情一览', (250, 0, 710, 70)):
                self.ui.expect_click('关闭', (350, 445, 615, 515), exact=True)
                continue
            if s.find('BOSS详情|队伍编组', (0, 0, 750, 80)):
                self.ui.expect_click('取消', (250, 420, 950, 525), exact=True)
            elif event_layout(s) == 'map' or s.find('活动任务|讨伐证交换|活动剧情|'+MEMORIES+'|'+self.memory_title, (0, 0, 400, 80)):
                self.ui.click((32, 30))
            elif s.find('WIN|获得道具|伤害报告|战斗胜利'):
                self.ui.expect_click('下一步', (700, 400, 950, 530), exact=True)
            else:
                time.sleep(.5)
        raise EventUIError('无法返回复刻活动首页')

    @staticmethod
    def sp_progress(detail):
        """(phase, cleared enemies, HP text); phase None when unreadable."""
        box = detail.find(r'(?:模式|MODE|阶段)[123]', (0, 0, 960, 170))
        hp = detail.find(r'\d+/\d+', (250, 265, 720, 315))
        phase = int(re.search('[123]', normalized(box.text))[0]) if box else None
        return phase, len(detail.all('已攻略', (100, 230, 860, 320))), hp.text if hp else None

    def sourced_boss(self, label, difficulty):
        attempts = {}
        source_pools = {}
        battles = 0
        while battles < self.r.options.get('max_boss_attempts', 6):
            self.r.check_deadline()
            if difficulty == 'special':
                if self.special_complete():
                    self.r.log('特别首领已通过，表演赛已解锁')
                    return self.hub()
            detail = self.boss_detail(label)
            # SP has a different header; only VH exposes this kill counter.
            defeated = self.ui.number(detail, (891, 28, 926, 56)) if difficulty == 'very_hard' else None
            if defeated is not None and defeated > 0:
                self.r.log(f'{label}首领已讨伐，跳过')
                return self.home()
            if difficulty == 'very_hard' and defeated is None:
                raise EventUIError('高难首领讨伐次数无法确认')
            mode_box = detail.find(r'(?:模式|MODE|阶段)[123]', (0, 0, 960, 170))
            mode = int(re.search('[123]', normalized(mode_box.text))[0]) if mode_box else 1
            if difficulty == 'special' and not mode_box:
                raise EventUIError('特别战斗模式未知，不能套用作业')
            key = (difficulty, mode)
            if key not in source_pools:
                # Video titles use the main title, not the full-width-space subtitle.
                area = re.split(r'[　\s]+', self.r.event.name.strip())[0]
                found, search = boss_parties(self.r.options, kind='revival', area=area,
                    difficulty=difficulty, mode=mode,
                    default_path='cache/game/strategies/revival_teams.yml',
                    check=self.r.check_deadline)
                searches = [search]
                if not found and (difficulty == 'very_hard' or mode > 1):
                    # VH and later SP phases rarely get their own videos. An
                    # SP phase-1 party out-guns VH and is the user's chosen
                    # trial for later phases; no-progress checks still stop it.
                    note = ('高难无专属作业，借用特别首领模式1阵容' if difficulty == 'very_hard'
                            else f'特别模式{mode}无专属作业，借用模式1阵容试打')
                    borrowed, search = boss_parties(self.r.options, kind='revival', area=area,
                        difficulty='special', mode=1,
                        default_path='cache/game/strategies/revival_teams.yml',
                        check=self.r.check_deadline)
                    searches.append(search)
                    found = [replace(party, assumptions=party.assumptions+[note]) for party in borrowed]
                source_pools[key] = found
                for search in filter(None, searches):
                    self.r.report.setdefault('source_searches', []).append(search)
                    if search.get('avatar_assets'):
                        from ..game_ui.avatar_assets import ensure_avatar_index
                        self.formation.avatars, _ = ensure_avatar_index(
                            self.r.options.get('sources', {}).get('avatars'), check=self.r.check_deadline)
            party = next_boss_party(source_pools[key], attempts, mode)
            if party is None:
                self.r.report['pending'].append(f'{label}模式{mode}没有对应作业')
                return self.home()
            challenge = detail.find('挑战', (720, 420, 950, 525), exact=True)
            if not detail.blue_button(challenge):
                self.r.report['pending'].append(label+'挑战不可用，未购买或追加消费')
                return self.home()
            self.ui.expect_click('挑战', (720, 420, 950, 525), exact=True)
            # Too few tickets only flashes a toast over the detail (2026-11-15).
            opened = self.ui.wait(lambda s: s.find('队伍编组', (0, 0, 750, 80)) or s.find('挑战券数量不足'), '首领编队')
            if opened.find('挑战券数量不足'):
                self.r.report['pending'].append(label+'首领挑战券不足，不购买，留待接续')
                return self.home()
            ready, selection = self.formation.select(party)
            if not ready:
                attempts[(mode, party.name)] = party.max_attempts
                self.r.report['battles'].append({'boss': difficulty, 'mode': mode,
                    'party': party.name, 'source': party.source, 'build_basis': party.build_basis,
                    'assumptions': party.assumptions, 'unready': selection})
                self.home()
                continue
            attempts[(mode, party.name)] = attempts.get((mode, party.name), 0)+1
            # Journal the ticket until the result is recorded: an error in
            # between leaves the spend unknown and must stop the chain.
            self.r.report['pending_boss'] = {'boss': difficulty, 'mode': mode, 'party': party.name}
            result = EventCombat(self.r).run(party, selection['order'])
            battles += 1
            self.r.report['battles'].append({'boss': difficulty, 'mode': mode, 'party': party.name,
                'source': party.source, 'build_basis': party.build_basis,
                'assumptions': party.assumptions, **vars(result)})
            self.r.report.pop('pending_boss')
            if result.outcome != 'settled':
                self.r.report['pending'].append(label+'未成功：'+result.reason)
                if result.outcome == 'blocked':
                    return self.home()
                if result.outcome in ('retreated', 'failed'):
                    attempts[(mode, party.name)] = party.max_attempts
                self.home()
                continue
            self.home()
            if difficulty == 'very_hard':
                # VH locks its entry immediately after success. Verify the
                # newly accessible SP details instead of reopening that lock.
                self.special_complete()
                self.boss_detail('特别')
                self.r.log('高难已通过，特别首领详情已解锁')
                return self.home()
            if difficulty == 'special':
                if self.special_complete():
                    return self.hub()
                after = self.boss_detail(label)
                # Multi-enemy SP shows bars without numbers; progress is a
                # higher phase, more "已攻略" stamps, or a changed HP reading.
                before, now = self.sp_progress(detail), self.sp_progress(after)
                if before[0] is None or now[0] is None:
                    self.r.report['pending'].append(label+'血量进度未确认，停止重试')
                    return self.home()
                if before == now:
                    attempts[(mode, party.name)] = party.max_attempts
                    self.r.report['battles'][-1]['progressed'] = False
                    self.home()
                    continue
                self.home()
        self.r.report['pending'].append(label+'达到尝试上限')
