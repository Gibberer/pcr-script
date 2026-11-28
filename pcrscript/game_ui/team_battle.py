"""Visible state and conservative planning for the five-lane team battle map."""
from __future__ import annotations

from dataclasses import dataclass, field
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
    # Click point on the boss sprite. Badge height follows the sprite, so
    # the target is derived from the observed "第N轮" badge.
    y: int = field(default=270, compare=False)

    @property
    def full(self) -> bool:
        return self.current_hp is not None and self.current_hp == self.maximum_hp


LANES = (125, 290, 480, 625, 840)
# Observed working clicks lay 68px above to 14px below the badge in every lane.
CLICK_ABOVE_BADGE = 40
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


def map_stage(screen: EventScreen) -> int | None:
    """Stage number from the map header 「目前N轮 第M阶段」."""
    if not isinstance(screen, EventScreen):
        return None
    label = screen.find(r'第\d+阶段', (235, 40, 420, 80), exact=True)
    if label is None or label.score < .95:
        return None
    return int(re.search(r'\d+', normalized(label.text))[0])


def map_bosses(screen: EventScreen) -> list[Boss]:
    if not map_ready(screen):
        raise EventUIError('团队战地图未确认')
    found = {}
    # Badge height follows each boss sprite; the tall middle boss puts its
    # badge near y=214, while the stage header stays above y=80.
    for label in screen.all(r'第\d+轮', (35, 190, 940, 380)):
        match = re.fullmatch(r'第(\d+)轮', normalized(label.text))
        if not match:
            continue
        x = label.center[0]
        lane = min(range(5), key=lambda i: abs(x-LANES[i]))
        if abs(x-LANES[lane]) > 65 or lane in found:
            raise EventUIError('团队战首领位置不明确')
        found[lane] = Boss(lane, int(match[1]), LANES[lane], y=int(label.center[1])-CLICK_ABOVE_BADGE)
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
    # Names change every season and are display-only: lane, lap and HP
    # identify the boss. Read the title line left of the weakness badge (a
    # long name can merge with "等级.100" into one box) and fall back to the
    # lane label instead of blocking on an unread name.
    line = sorted(screen.all('.*', (270, 260, 560, 300)), key=lambda item: item.center[0])
    name = re.sub(r'等级.*$', '', normalized(''.join(item.text for item in line)))
    name = name or f'{boss.lane+1}号首领'
    return Boss(boss.lane, boss.lap, boss.x, current, maximum, name, boss.y)


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


def damage_simulation_ready(boss: Boss, simulation: dict, reference: int | None, percent: int) -> bool:
    """Stage D and above: a damage attack passes on a kill or on simulated
    damage within ``percent`` of the recommendation's reference damage."""
    if simulation.get('win') is True:
        return True
    actual = simulation.get('actual_damage')
    if type(actual) is not int or type(reference) is not int or reference <= 0:
        return False
    return actual*100 >= min(reference, boss.current_hp)*percent


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
    """Read the reference damage belonging to one recommendation row.

    The label's place beside 「使用」 depends on the layout: stage D rows have
    no clear-time line and sit about 13 px lower (observed 2026-11-28). The
    number is always about 21 px under its label, so the label anchors it."""
    band = (45, use_y-70, 185, use_y+5)
    label = screen.find('参考伤害', band, exact=True)
    if label is None and ui is not None:
        label = ui.read_region(screen, band, classify=False).find('参考伤害', band, exact=True)
    if label is None:
        return None
    top = int(label.center[1])
    roi = (55, top+5, 190, top+38)
    value = numeric_text(screen, r'[\d,]+', roi, ui)
    if value is None and ui is not None:
        # The 3x crop can split a long number or score it just below .95
        # (2026-11-28); the 4x/3x line read is the project's sturdier read.
        for window in ((55, top+10, 190, top+34), roi):
            number = ui.number_crop(screen, window)
            if isinstance(number, int):
                value = str(number)
                break
    if value is None and ui is not None:
        # Two independent reads agreeing settles it. A full-frame number with
        # an empty crop stays unknown: the frame can truncate wide numbers.
        full = screen.find(r'[\d,]+', roi, exact=True)
        crop = ui.read_region(screen, roi, classify=False).find(r'[\d,]+', roi, exact=True)
        if (full is not None and full.score >= .95 and crop is not None
                and normalized(crop.text) == normalized(full.text)):
            value = normalized(full.text)
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
