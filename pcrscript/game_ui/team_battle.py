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


def map_ready(screen: EventScreen) -> bool:
    return bool(screen.find('团队战', (45, 0, 170, 70), exact=True)
                and screen.find('剩余挑战次数', (285, 382, 440, 425), exact=True)
                and screen.find('讨伐信息', (180, 425, 310, 475), exact=True))


def map_bosses(screen: EventScreen) -> list[Boss]:
    if not map_ready(screen):
        raise EventUIError('团队战地图未确认')
    found = {}
    for label in screen.all(r'第\d+轮', (35, 250, 940, 380)):
        match = re.fullmatch(r'第(\d+)轮', normalized(label.text))
        if not match:
            continue
        x = label.center[0]
        lane = min(range(5), key=lambda i: abs(x-LANES[i]))
        if abs(x-LANES[lane]) > 65 or lane in found:
            raise EventUIError('团队战首领位置不明确')
        found[lane] = Boss(lane, int(match[1]), LANES[lane])
    return list(found.values())


def boss_detail(screen: EventScreen, boss: Boss) -> Boss:
    if not screen.find('魔物详情', (25, 15, 245, 78), exact=True):
        raise EventUIError('团队战魔物详情未确认')
    hp = screen.find(r'[\d,]+/[\d,]+', (490, 275, 705, 330), exact=True)
    if hp is None:
        raise EventUIError('团队战首领血量无法识别')
    current, maximum = (int(n.replace(',', '')) for n in normalized(hp.text).split('/'))
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


def can_repeat(sim_remaining: int, *, margin: int = 8) -> bool:
    """The displayed returned time must cover a second similar kill."""
    return 0 <= sim_remaining <= 90 and (90-sim_remaining) + margin <= sim_remaining


def parse_remaining_time(screen: EventScreen) -> int | None:
    value = screen.find(r'\d:\d{2}', (825, 435, 925, 470), exact=True)
    if not value:
        return None
    match = re.fullmatch(r'(\d+):(\d{2})', normalized(value.text))
    if not match or int(match[2]) >= 60:
        return None
    return int(match[1])*60+int(match[2])


def recommendation_time(screen: EventScreen, use_y: int) -> int | None:
    """Read the displayed estimated clear time for one visible recommendation."""
    label = screen.find('讨伐时间', (45, use_y+4, 125, use_y+42), exact=True)
    value = screen.find(r'\d:\d{2}', (125, use_y+4, 180, use_y+42), exact=True)
    if label is None or value is None:
        return None
    match = re.fullmatch(r'(\d+):(\d{2})', normalized(value.text))
    if match is None or int(match[2]) >= 60:
        return None
    return int(match[1])*60+int(match[2])


def recommendation_damage(screen: EventScreen, use_y: int) -> int | None:
    """Read the reference damage belonging to one recommendation row."""
    label = screen.find('参考伤害', (45, use_y-48, 185, use_y-15), exact=True)
    value = screen.find(r'[\d,]+', (55, use_y-20, 190, use_y+12), exact=True)
    if label is None or value is None or value.score < .95:
        return None
    damage = int(normalized(value.text).replace(',', ''))
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
