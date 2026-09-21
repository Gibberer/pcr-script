"""Standalone caravan dice spending; no purchases or daily-list changes."""
from __future__ import annotations
from .registry import register
import json
from typing import TYPE_CHECKING
from .base import BaseTask, TaskOptions, TaskReport, Region
from ..game_ui.screen import EventScreen
if TYPE_CHECKING:
    from pcrscript import Robot
import re
from pcrscript.run_session import clock as time, emit
from ..game_ui.screen import EventUI, EventUIError
from ..game_ui.caravan import board, triple_mode, disabled_roll, progress, fastest_turn, helpful_food, surplus_food


@register("caravan")
class Caravan(BaseTask):
    config_section = 'Caravan'
    config_attribute = 'caravan_options'

    def __init__(self, robot: Robot, options: TaskOptions | None = None) -> None:
        super().__init__(robot)
        self.options = self.task_options() if options is None else options
        self.ui = EventUI(robot.driver, self.options.get('output', 'cache/daily/caravan'))
        self.deadline = time.monotonic() + self.options.get('timeout', 1800)
        self.limit = self.options.get('max_rolls', 200)
        self.report: TaskReport = dict(status='running', initial_dice=None, remaining_dice=None,
                           rolls=0, skips=0, spent=0, gained=0, foods=0, pending=[], history=[])
        self.pending: tuple[int, int, str, float] | None = None
        self.locked = False
        self.last_distance: int | None = None
        self.food_checked: int | None = None
        self.probe = False
        self.reward_visible = False
        self.bonus = 0
        self.food_scrolls = 0
        self.food_declined = False
        self.sale_before: int | None = None
        self.sale_confirmed = False
        self.sale_scrolls = 0
        self.empty_probe: float | None = None
        self.empty_confirmed = False

    def save_report(self) -> None:
        (self.ui.output / 'report.json').write_text(
            json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')

    def click_text(self, s: EventScreen, pattern: str, roi: Region=(200, 350, 760, 515)) -> bool:
        button = s.find(pattern, roi, exact=True)
        if button:
            self.ui.click(button)
            return True
        return False

    def modal(self, s: EventScreen) -> bool:
        if s.find('跳过确认', (250, 15, 710, 75), exact=True):
            if self.pending:
                if time.monotonic()-self.pending[3] > 45:
                    raise EventUIError('区间跳过确认后无进展，未重复消费')
                time.sleep(.6)
                return True
            if not self.probe:
                return self.click_text(s, '返回')
            before = self.ui.number(s, (638, 330, 668, 354))
            after = self.ui.number(s, (686, 330, 714, 354))
            if (before is None or after is None or before != self.report['remaining_dice']
                    or before-after != 15 or after < 0):
                raise EventUIError('区间跳过消费预览无法确认，未消费')
            button = s.find('跳过', (450, 440, 710, 515), exact=True)
            if button is None:
                raise EventUIError('区间跳过确认按钮无法识别')
            self.ui.save('skip_preview', s)
            self.pending = (before, 15, 'skips', time.monotonic())
            self.bonus = 0
            self.probe = False
            self.report['pending_spend'] = dict(before=before, cost=15, kind='skips')
            self.save_report()
            emit('caravan.spend', before=before, cost=15)
            self.ui.click(button)
            return True
        if s.find('确认食用', (250, 15, 710, 180), exact=True) and s.find('生效中的效果将被覆盖'):
            self.food_declined = True
            return self.click_text(s, '取消', (200, 300, 800, 515))
        if s.find('出售完毕', (250, 15, 710, 180), exact=True) and s.find('获得了500里程'):
            return self.click_text(s, '确认', (200, 300, 800, 515))
        if s.find('出售确认', (250, 15, 710, 180), exact=True):
            if self.sale_before is None:
                return self.click_text(s, '取消', (200, 300, 800, 515))
            if not s.find('获得500里程'):
                raise EventUIError('料理出售预览不符，未确认')
            if not self.sale_confirmed and self.click_text(s, '确认', (200, 300, 800, 515)):
                self.sale_confirmed = True
            return True
        if s.find('持有数已满.*请选择要出售的料理'):
            match = re.search(r'料理持有数\s*(\d+)/10', s.text())
            if not match:
                raise EventUIError('料理满仓数量无法确认')
            count = int(match[1])
            if self.sale_before is not None:
                if not self.sale_confirmed or count != self.sale_before - 1:
                    raise EventUIError('料理出售后持有数不符')
                self.report['foods_sold'] = self.report.get('foods_sold', 0) + 1
                self.sale_before = None
                self.sale_confirmed = False
                self.sale_scrolls = 0
            if count <= 10:
                return self.click_text(s, '关闭|确认')
            for button in s.all('^出售$', (35, 145, 930, 440)):
                x, y = button.center
                if surplus_food(s.text((int(x)-250, max(140, int(y)-130), int(x)+65, int(y)+10))):
                    self.sale_before = count
                    self.ui.save('food_surplus_before', s)
                    self.ui.click(button)
                    return True
            if self.sale_scrolls >= 8:
                raise EventUIError('料理满仓，未找到可确认的不利赶路料理，未一键出售')
            self.sale_scrolls += 1
            if self.sale_scrolls <= 4:
                self.ui.swipe((700, 410), (700, 210))
            else:
                self.ui.swipe((700, 180), (700, 420))
            return True
        if s.find('抽奖结果', (250, 15, 710, 180), exact=True) and s.find('用持有的抽奖券进行了抽奖'):
            return self.click_text(s, '确认')
        if s.find('收取了以下宝藏') and s.find('合计获得金币'):
            return self.click_text(s, '关闭')
        if s.find('鉴定结果', (250, 10, 710, 85), exact=True):
            return self.click_text(s, '下一步')
        if s.find('跳过奖励', (250, 15, 710, 75), exact=True) and s.find('赛季最快到达回合数'):
            self.ui.save('skip_rewards', s)
            return self.click_text(s, '确认')
        if s.find('回合数奖励|奖励一览', (250, 15, 710, 75), exact=True):
            if s.find('到达所花费的回合数'):
                self.ui.save(f"checkpoint_{self.report['spent']:03d}", s)
                return self.click_text(s, '确认')
        if s.find('里程扭蛋目前正在开放'):
            return self.click_text(s, '投骰子' if self.pending else '取消')
        if s.find('里程扭蛋', (250, 15, 710, 180), exact=True):
            return self.click_text(s, '关闭')
        reward = s.find(r'获得\d+个骰子[。.]?', (280, 200, 720, 340), exact=True)
        if s.find('活动加成', (250, 100, 720, 220)) and reward:
            if not self.reward_visible:
                amount = int(re.search(r'\d+', reward.text)[0])
                self.bonus += amount
                self.report['gained'] += amount
                self.ui.save(f"dice_reward_{self.report['gained']:03d}", s)
                self.reward_visible = True
            self.ui.click((480, 280))
            return True
        self.reward_visible = False
        if s.find('活动加成', (250, 100, 720, 220)):
            self.ui.save('event_bonus', s)
            self.ui.click((480, 280))
            return True
        if s.find('将不开启.*近道.*直接离开'):
            return self.click_text(s, '离开', (200, 300, 800, 515))
        if s.find('是否支付里程通过', (100, 100, 860, 400)):
            return self.click_text(s, '不通过', (100, 200, 860, 510))
        if s.find('同伴效果发生', (0, 0, 440, 130)):
            if s.find('应用骰子的正面或反面', (100, 40, 350, 110)):
                if not s.find('or', (420, 345, 530, 430), exact=True):
                    return False  # The dice animation precedes the choice buttons.
                left = self.ui.number(s, (285, 340, 400, 445))
                right = self.ui.number(s, (565, 340, 680, 445))
                left = left if left in range(1, 7) else None
                right = right if right in range(1, 7) else None
                if left is None and right is None:
                    raise EventUIError('骰子正反面点数无法确认')
                if left is not None and right is not None and left+right != 7:
                    raise EventUIError('骰子正反面点数不符')
                self.ui.save('companion_faces', s)
                # A recognized side is still usable when the other stylized
                # digit cannot be read; never invent the missing value.
                self.ui.click((339, 388) if (left or 0) > (right or 0) else (620, 388))
                return True
            reroll = s.find('重新投掷', (480, 300, 750, 485), exact=True)
            if reroll and s.find('可重掷1次骰子', (100, 40, 330, 110)):
                value = self.ui.number(s, (285, 340, 400, 445))
                if value not in range(1, 7):
                    raise EventUIError('同伴重掷当前点数无法确认')
                retry = value < 4 and self.last_distance is not None and self.last_distance > value
                self.ui.save('companion_reroll', s)
                self.ui.click(reroll if retry else (339, 388))
                return True
            extra = s.find('增加投掷次数', (480, 250, 740, 430), exact=True)
            if extra:
                self.ui.save('companion_extra', s)
                self.ui.click(extra)
                return True
        if s.find('里程商店', (0, 0, 960, 100), exact=True):
            return self.click_text(s, '返回地图', (0, 400, 960, 540))
        forks = s.all('距离检查点', (0, 70, 960, 400))
        if len(forks) >= 2 and not board(s):
            choices = []
            for label in forks:
                x, y = label.center
                distance = self.ui.number(s, (max(0, x-50), y+10, min(960, x+50), y+43))
                if distance is None:
                    raise EventUIError('岔路距离无法确认')
                choices.append((distance, -int(x), (int(x), int(y)+70)))
            self.ui.save('fork', s)
            self.ui.click(min(choices)[2])
            return True
        if (s.find('跳过报酬', (250, 15, 710, 180), exact=True)
                and s.find('跳过小游戏')):
            return self.click_text(s, '关闭')
        if s.find('挑战.*游戏', (140, 0, 760, 100)):
            return self.click_text(s, '跳过', (800, 180, 950, 385))
        if s.find('TOUCH[!！]?', (100, 100, 850, 440)):
            self.ui.click(s.find('TOUCH[!！]?', (100, 100, 850, 440)))
            return True
        if s.find('获得料理|获得宝藏|获得抽奖券', (250, 15, 710, 180), exact=True):
            return self.click_text(s, '关闭')
        if s.find('食用确认', (250, 15, 710, 100), exact=True):
            if not helpful_food(s.text((240, 100, 720, 390))):
                raise EventUIError('未知料理效果，未确认食用')
            if self.click_text(s, '确认'):
                self.report['foods'] += 1
                return True
        if s.find('持有的料理', (250, 15, 710, 75), exact=True):
            if self.food_declined:
                return self.click_text(s, '关闭')
            self.ui.save(f'food_page_{self.food_scrolls}', s)
            for button in s.all('^食用$', (35, 145, 930, 440)):
                x, y = button.center
                if helpful_food(s.text((int(x)-250, max(140, int(y)-135), int(x)+65, int(y)+10))):
                    self.ui.click(button)
                    return True
            if self.food_scrolls < 4:
                self.food_scrolls += 1
                self.ui.swipe((700, 414), (700, 214))
                return True
            return self.click_text(s, '关闭')
        return False

    def run(self) -> TaskReport:
        last_progress = time.monotonic()
        zero_seen = 0
        try:
            while time.monotonic() < self.deadline:
                s = self.ui.capture()
                if s.find('正在.*连接|加载中|下载中', (0, 0, 960, 540)):
                    time.sleep(.6)
                    continue
                if self.modal(s):
                    last_progress = time.monotonic()
                    continue
                if board(s):
                    if self.sale_before is not None:
                        food_count = s.find(r'\d+/10', (750, 317, 809, 350), exact=True)
                        if not self.sale_confirmed or food_count is None or int(food_count.text.split('/')[0]) != self.sale_before-1:
                            raise EventUIError('料理出售后地图库存无法核实')
                        self.report['foods_sold'] = self.report.get('foods_sold', 0)+1
                        self.sale_before = None
                        self.sale_confirmed = False
                    if s.find('15回合内到达检查点后即可解锁'):
                        self.locked = True
                        self.probe = False
                        time.sleep(2)
                        continue
                    count = self.ui.number(s, (890, 300, 941, 334))
                    if count is None:
                        count = self.ui.number(s, (899, 307, 929, 328))
                    turn, distance = progress(s)
                    if turn is None or distance is None:
                        local = self.ui.read_region(s, (150, 165, 235, 291))
                        local_turn, local_distance = progress(local)
                        turn = turn if turn is not None else local_turn
                        distance = distance if distance is not None else local_distance
                    if count is None and disabled_roll(s):
                        if s.find('未持有骰子[。.]?', (250, 150, 750, 350), exact=True):
                            self.empty_confirmed = True
                            self.ui.save('empty_tooltip', s)
                        if self.empty_confirmed:
                            count = 0
                        elif self.empty_probe is None:
                            self.empty_probe = time.monotonic()
                            self.ui.click((874, 372))
                            continue
                        elif time.monotonic()-self.empty_probe < 5:
                            time.sleep(.3)
                            continue
                    if count is None or turn is None or distance is None:
                        raise EventUIError('骰子/回合/检查点距离无法确认')
                    if self.report['initial_dice'] is None:
                        self.report['initial_dice'] = count
                    self.report['remaining_dice'] = count
                    if self.pending:
                        before, cost, kind, since = self.pending
                        expected = before-cost+self.bonus
                        if count == before and expected != before:
                            if time.monotonic()-since > 45:
                                raise EventUIError('投骰后余额未变化，停止重复消费')
                            time.sleep(.6)
                            continue
                        if count != expected:
                            raise EventUIError(f'骰子消费不符：{before}→{count}，预期{cost}')
                        self.report['spent'] += cost
                        self.report[kind] += 1
                        self.report['history'].append(dict(before=before, after=count, kind=kind,
                                                           turn=turn, distance=distance, gained=self.bonus))
                        self.ui.save(f"settled_{len(self.report['history']):03d}", s)
                        self.pending = None
                        self.report.pop('pending_spend', None)
                        last_progress = time.monotonic()
                        self.save_report()
                        print(f'[驾车游] 骰子{count}，第{turn}回合，距离{distance}', flush=True)
                    if self.last_distance is not None and distance > self.last_distance:
                        self.locked = False
                    self.last_distance = distance
                    if count == 0:
                        zero_seen += 1
                        if zero_seen >= 2:
                            self.report['status'] = 'complete'
                            self.ui.save('empty', s)
                            return self.report
                        time.sleep(.6)
                        continue
                    zero_seen = 0
                    if self.report['rolls'] + self.report['skips'] >= self.limit:
                        raise EventUIError('达到消费批次上限')
                    mode = triple_mode(s)
                    if mode is None:
                        raise EventUIError('无法确认同时掷3个开关，未投骰')
                    if mode:
                        self.ui.save('triple_before_disable', s)
                        self.ui.click((821, 443))
                        continue
                    if count >= 15 and not self.locked:
                        if self.probe:
                            raise EventUIError('区间跳过响应无法确认')
                        self.probe = True
                        self.ui.click((644, 382))
                        last_progress = time.monotonic()
                        continue
                    food = s.find(r'[1-9]/10|10/10', (750, 317, 809, 350), exact=True)
                    record = fastest_turn(s)
                    needs_target = record is None or record > 15
                    if needs_target and food and self.food_checked != count:
                        self.food_checked = count
                        self.food_scrolls = 0
                        self.food_declined = False
                        self.ui.click((746, 379))
                        continue
                    self.ui.save(f"spend_{len(self.report['history']):03d}", s)
                    emit('caravan.spend', before=count, cost=1)
                    self.pending = (count, 1, 'rolls', time.monotonic())
                    self.bonus = 0
                    self.report['pending_spend'] = dict(before=count, cost=1, kind='rolls')
                    self.save_report()
                    self.ui.click((874, 372))
                    last_progress = time.monotonic()
                    continue
                if not self.pending and s.find('驾车游', (65, 360, 195, 465)):
                    self.ui.click(s.find('驾车游', (65, 360, 195, 465)))
                    last_progress = time.monotonic()
                    continue
                if (not self.pending and not s.find('驾车游', (45, 0, 180, 65))
                        and s.find('冒险', (475, 480, 605, 539), exact=True)):
                    self.ui.click(s.find('冒险', (475, 480, 605, 539), exact=True))
                    last_progress = time.monotonic()
                    continue
                if time.monotonic() - last_progress > 40:
                    raise EventUIError('驾车游未知页面或无进展，保留现场')
                time.sleep(.6)
            raise EventUIError('驾车游达到运行时限')
        except Exception as error:
            self.report['status'] = 'error'
            self.report['pending'].append(str(error))
            self.ui.save('error')
            raise
        finally:
            self.save_report()
