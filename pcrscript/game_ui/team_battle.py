"""Visible state and conservative planning for the five-lane team battle map."""
from __future__ import annotations

from dataclasses import dataclass
import re

from .screen import EventScreen, EventUIError, normalized


@dataclass(frozen=True)
class Boss:
    lane: int
    lap: int
    x: int
    current_hp: int | None = None
    maximum_hp: int | None = None
    name: str = ''

    @property
    def full(self) -> bool:
        return self.current_hp is not None and self.current_hp == self.maximum_hp


LANES = (125, 290, 480, 625, 840)
NORMAL_SECONDS = 90
RETURN_BONUS_SECONDS = 20
REPEAT_MARGIN_SECONDS = 8


def numeric_text(screen, pattern, roi, ui=None):
    """Read one known upright field; never rescue a failed crop with old OCR."""
    observed = ui.read_region(screen, roi, classify=False) if ui is not None else screen
    item = observed.find(pattern, roi, exact=True)
    return normalized(item.text) if item is not None and item.score >= .95 else None


def seconds_field(screen, roi, ui=None):
    text = numeric_text(screen, r'\d:\d{2}', roi, ui)
    if text is None:
        return None
    minutes, seconds = map(int, text.split(':'))
    value = minutes*60+seconds
    return value if seconds < 60 and 0 <= value <= NORMAL_SECONDS else None


def map_ready(screen: EventScreen) -> bool:
    return bool(screen.find('团队战', (45, 0, 170, 70), exact=True)
                and screen.find('剩余挑战次数', (285, 382, 440, 425), exact=True)
                and screen.find('讨伐信息', (180, 425, 310, 475), exact=True))


def map_bosses(screen: EventScreen) -> list[Boss]:
    if not map_ready(screen):
        raise EventUIError('团队战地图未确认')
    found = {}
    for label in screen.all(r'第\d+轮', (35, 220, 940, 380)):
        match = re.fullmatch(r'第(\d+)轮', normalized(label.text))
        if not match:
            continue
        x = label.center[0]
        lane = min(range(5), key=lambda i: abs(x-LANES[i]))
        if abs(x-LANES[lane]) > 65 or lane in found:
            raise EventUIError('团队战首领位置不明确')
        found[lane] = Boss(lane, int(match[1]), LANES[lane])
    return list(found.values())


def boss_detail(screen: EventScreen, boss: Boss, ui=None) -> Boss:
    if not screen.find('魔物详情', (25, 15, 245, 78), exact=True):
        raise EventUIError('团队战魔物详情未确认')
    # Whole-frame direction classification can rotate this numeric line by
    # 180 degrees (90000000 becomes 00000006). Read the fixed field upright,
    # independent of the whole-frame OCR, before using HP to reject a team.
    region = (490, 300, 705, 330)
    hp = numeric_text(screen, r'[\d,]+/[\d,]+', region, ui)
    if hp is None:
        raise EventUIError('团队战首领血量无法识别')
    numbers = [n.replace(',', '') for n in hp.split('/')]
    if any(len(n) > 1 and n.startswith('0') for n in numbers):
        raise EventUIError('团队战首领血量数字方向或格式异常')
    current, maximum = map(int, numbers)
    if not 0 < current <= maximum:
        raise EventUIError('团队战首领血量无效')
    name = normalized(screen.text((270, 260, 395, 305)))
    if not name:
        raise EventUIError('团队战首领身份无法识别')
    return Boss(boss.lane, boss.lap, boss.x, current, maximum, name)


def priority(boss: Boss, minimum_lap: int) -> tuple[int, int, int, int]:
    """Full HP, a visible next lap, and the oldest lane are preferred."""
    next_visible = boss.lap + 1 <= minimum_lap + 2
    return (int(boss.full), int(next_visible), -boss.lap, -boss.lane)


def can_repeat_clear_time(clear_seconds: int, *, margin: int = REPEAT_MARGIN_SECONDS) -> bool:
    if type(clear_seconds) is not int or not 1 <= clear_seconds <= NORMAL_SECONDS:
        return False
    if type(margin) is not int or margin < 0:
        return False
    returned = min(NORMAL_SECONDS, NORMAL_SECONDS+RETURN_BONUS_SECONDS-clear_seconds)
    return clear_seconds+margin <= returned


def can_repeat(sim_remaining: int, *, margin: int = REPEAT_MARGIN_SECONDS) -> bool:
    """Returned time includes a 20s bonus, capped at the 90s battle limit."""
    return (type(sim_remaining) is int and 0 <= sim_remaining <= NORMAL_SECONDS
            and can_repeat_clear_time(NORMAL_SECONDS+RETURN_BONUS_SECONDS-sim_remaining, margin=margin))


def normal_simulation_ready(boss: Boss, simulation: dict) -> bool:
    """Normal attacks must kill; a full-HP kill must also fit the double-kill budget.

    The task only covers low stages (A/B/C) where such a team exists, so a
    damage-only target is never accepted for a normal attack.
    """
    if simulation.get('win') is not True:
        return False
    return not boss.full or can_repeat(simulation.get('remaining'))


def validate_counter_transition(before, after, *, extension: bool, won: bool, returned=None):
    """A settled result must agree with both counters before another attack."""
    if any(type(n) is not int or not 0 <= n <= 3 for n in (*before, *after)):
        raise EventUIError('团队战次数状态无效')
    cp, extra = before
    expected = ((cp, extra-1) if extension else
                (cp-1, extra+int(won and type(returned) is int and returned > 0)))
    if after != expected:
        mode = '延长' if extension else '普通'
        raise EventUIError(f'{mode}挑战后次数变化与预期不符：预期{expected}，实际{after}；停止后续实战')


def parse_remaining_time(screen: EventScreen, ui=None) -> int | None:
    return seconds_field(screen, (825, 435, 925, 470), ui)


def recommendation_time(screen: EventScreen, use_y: int, ui=None) -> int | None:
    """Read the displayed estimated clear time for one visible recommendation."""
    label = screen.find('讨伐时间', (45, use_y+4, 125, use_y+42), exact=True)
    if label is None:
        return None
    return seconds_field(screen, (125, use_y+4, 180, use_y+42), ui)


def recommendation_damage(screen: EventScreen, use_y: int, ui=None) -> int | None:
    """Read the reference damage belonging to one recommendation row."""
    label = screen.find('参考伤害', (45, use_y-48, 185, use_y-15), exact=True)
    if label is None:
        return None
    value = numeric_text(screen, r'[\d,]+', (55, use_y-20, 190, use_y+12), ui)
    if value is None:
        return None
    digits = value.replace(',', '')
    if len(digits) > 1 and digits.startswith('0'):
        return None
    damage = int(digits)
    return damage if damage > 0 else None


def result_damage(screen: EventScreen) -> int | None:
    """Read damage, excluding the score multiplier shown beside it."""
    if not screen.find('伤害合计', (35, 0, 160, 42), exact=True):
        return None
    value = screen.find(r'\d[\d,]*(?:[×xX*][\d.]+)?', (45, 30, 300, 78), exact=True)
    if value is None or value.score < .95:
        return None
    match = re.match(r'([\d,]+)', normalized(value.text))
    if match is None:
        return None
    damage = int(match[1].replace(',', ''))
    return damage if damage > 0 else None


def meets_reference(actual: int | None, expected: int | None,
                    boss_hp: int | None, defeated: bool) -> bool:
    if expected is None or boss_hp is None or not 0 < expected <= boss_hp:
        return False
    if expected == boss_hp:
        return defeated
    return defeated or (actual is not None and actual >= expected)
