"""Read Recollection Battlefield pages in the shared 960 x 540 space."""
from __future__ import annotations

from dataclasses import dataclass
import re

import cv2 as cv
import numpy as np

from .screen import EventScreen, TextBox, normalized


AREAS = {'memory': '记忆领域', 'kaiser': '霸瞳皇帝的领域',
         'zen': '泽恩的领域', 'miroku': '米洛克的领域'}
ALIASES = {'memory': ('记忆领域', '日常', '追忆战'),
           'kaiser': ('霸瞳皇帝的领域', '霸瞳皇帝', '霸瞳'),
           'zen': ('泽恩的领域', '泽恩', '赞恩'),
           'miroku': ('米洛克的领域', '米洛克')}


def text_scope(text: str) -> dict:
    """A collection range is never an exact floor, nor an ordinary boss name."""
    text = normalized(text)
    found = []
    for key, names in ALIASES.items():
        for name in names:
            for match in re.finditer(re.escape(name) + r'[-－:：]?(?:第)?([1-9]\d?)(?:层|阶)?(?!\d)', text):
                if re.match(r'(?:[~～至到\-－、,/+&]|和|及)(?:第)?\d', text[match.end():]):
                    return {}
                found.append({'area': AREAS[key], 'floor': int(match[1])})
    unique = {(row['area'], row['floor']) for row in found}
    return found[0] if len(unique) == 1 else {}


def home(s: EventScreen) -> bool:
    labels = [s.find(pattern, roi, exact=True) for pattern, roi in (
        ('追忆的战场', (45, 0, 300, 65)), ('追忆战', (100, 310, 350, 440)),
        ('追忆战[·・]霸', (650, 310, 890, 440)))]
    return all(label and label.score >= .9 for label in labels)


def bulk_catalogue(s: EventScreen) -> bool:
    return bool(s.find('关卡一览', (250, 0, 720, 80), exact=True)
                and s.find('1个关卡的使用券张数', (480, 340, 720, 415), exact=True)
                and s.find('一?键扫荡', (475, 435, 715, 525), exact=True))


def bulk_confirmation(s: EventScreen) -> bool:
    return bool(s.find('一?键扫荡确认', (250, 0, 720, 80), exact=True)
                and s.find('将消耗扫荡券', (100, 55, 900, 105))
                and s.find('合计扫荡次数', (700, 335, 925, 400), exact=True))


def difficulty_selector(s: EventScreen) -> bool:
    ordinary = s.find('难度变更', (250, 0, 720, 80), exact=True)
    dominion = (s.find('取消', (250, 440, 470, 520), exact=True)
                and s.find('确认', (480, 440, 710, 520), exact=True)
                and s.find(r'[1-9]\d?层', (285, 85, 675, 430), exact=True))
    return bool(ordinary or dominion)


def single_floor(s: EventScreen) -> bool:
    """The first unlocked dominion floor has a visibly disabled selector."""
    scope = detail_scope(s)
    if not scope or scope['area'] == AREAS['memory'] or scope['floor'] != 1:
        return False
    hsv = cv.cvtColor(s.image[82:110, 790:913], cv.COLOR_BGR2HSV)
    grey = (hsv[:, :, 1] < 65) & (hsv[:, :, 2] >= 100) & (hsv[:, :, 2] < 220)
    white = (hsv[:, :, 1] < 35) & (hsv[:, :, 2] >= 230)
    return float(np.mean(grey)) > .65 and float(np.mean(white)) < .08


def detail_scope(s: EventScreen) -> dict:
    if (home(s) or bulk_catalogue(s) or bulk_confirmation(s) or difficulty_selector(s)
            or s.find('队伍编组', (250, 0, 710, 80), exact=True)):
        return {}
    if not (s.find('追忆战(?:[·・]霸)?', (40, 0, 270, 65), exact=True)
            and s.find('难度变更', (760, 65, 950, 130), exact=True)
            and s.find('详情', (630, 235, 730, 310), exact=True)):
        return {}
    scopes = [text_scope(item.text) for item in s.all('.+', (30, 65, 650, 125))]
    scopes = [scope for scope in scopes if scope]
    return scopes[0] if len(scopes) == 1 else {}


def dominion_index(s: EventScreen) -> bool:
    return bool(s.find('追忆战[·・]霸', (40, 0, 270, 65), exact=True)
                and s.find('一?键扫荡', (700, 400, 945, 470), exact=True)
                and not detail_scope(s) and not bulk_catalogue(s)
                and not bulk_confirmation(s))


def clear_status(s: EventScreen) -> bool | None:
    if not detail_scope(s):
        return None
    if s.find('已完成', (110, 300, 360, 450), exact=True):
        return True
    # A red completion stamp missed by OCR is unknown, never "uncleared".
    hsv = cv.cvtColor(s.image[310:450, 110:320], cv.COLOR_BGR2HSV)
    red = ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 175)) & (hsv[:, :, 1] > 130) & (hsv[:, :, 2] > 140)
    if float(np.mean(red)) > .04:
        return None
    return False if s.find('初次通关', (110, 300, 360, 420), exact=True) else None


def count_pair(s: EventScreen, roi) -> tuple[int, int] | None:
    values = set()
    for item in s.all(r'\d+/\d+', roi):
        if item.score < .95:
            continue
        match = re.search(r'(?<!\d)(\d+)/(\d+)(?!\d)', normalized(item.text))
        if match and 0 <= int(match[1]) <= int(match[2]) <= 99 and int(match[2]) > 0:
            values.add((int(match[1]), int(match[2])))
    return next(iter(values)) if len(values) == 1 else None


def detail_attempts(s: EventScreen) -> int | None:
    scope = detail_scope(s)
    pair = count_pair(s, (615, 400, 715, 465))
    return pair[0] if scope and scope['area'] != AREAS['memory'] and pair else None


def boss_signature(s: EventScreen) -> dict | None:
    """Read the live floor and its boss, never infer a floor from a guide range."""
    scope = detail_scope(s)
    if not scope:
        return None
    header = s.find(re.escape(scope['area'])+str(scope['floor'])+'层', (30, 65, 650, 125), exact=True)
    # Ordinary multipart bosses have a longer name; the level is farther right,
    # while the weakness label remains outside the name/level region.
    labels = s.all('.+', (220, 230, 500 if scope['area'] == AREAS['memory'] else 440, 272))
    if not header or header.score < .95 or not labels or any(t.score < .95 for t in labels):
        return None
    name = ''.join(normalized(t.text) for t in sorted(labels, key=lambda t: t.center[0]))
    match = re.fullmatch(r'(.+?)(?:等级[.．:：]?|Lv\.?)([1-9]\d*)', name, re.I)
    health = {int(m[2]) for t in s.all('.+', (290, 275, 715, 318)) if t.score >= .95
              and (m := re.fullmatch(r'(\d{7,11})/(\d{7,11})', normalized(t.text)))
              and int(m[1]) == int(m[2])}
    if not match or len(health) != 1:
        return None
    return dict(scope=scope, boss=match[1], level=int(match[2]), maximum_hp=health.pop())


def battle_outcome(s: EventScreen) -> str | None:
    failed = s.find('战斗失败|挑战失败|LOSE|DEFEAT', (250, 0, 720, 125), exact=True)
    won = s.find('WIN|战斗胜利|胜利', (250, 0, 720, 125), exact=True)
    if failed and failed.score >= .95 and not won:
        return 'failed'
    if won and won.score >= .95 and not failed:
        return 'won'
    return None


def battle_result_button(s: EventScreen) -> TextBox | None:
    if not (battle_outcome(s) or s.find('伤害报告|战斗结果', exact=True)):
        return None
    button = s.find('前往追忆战[·・]霸|下一步|返回|确认|关闭', (250, 350, 950, 525), exact=True)
    return button if button and button.score >= .95 else None


def index_attempts(s: EventScreen) -> dict[str, int]:
    if not dominion_index(s):
        return {}
    values = {}
    for key, name in AREAS.items():
        if key == 'memory':
            continue
        row = s.find(re.escape(name), (100, 310, 850, 375), exact=True)
        if row:
            x, y = row.center
            pair = count_pair(s, (x-110, y+15, x+110, y+55))
            if pair:
                values[name] = pair[0]
    return values


def card_locked(s: EventScreen, row: TextBox) -> bool:
    x, y = row.center
    hsv = cv.cvtColor(s.image[y-132:y-85, x-24:x+24], cv.COLOR_BGR2HSV)
    gold = (hsv[:, :, 0] >= 12) & (hsv[:, :, 0] <= 40) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)
    return float(np.mean(gold)) > .18


@dataclass
class SweepRow:
    area: str
    floor: int
    remaining: int
    selected: bool
    label: TextBox


def checked(s: EventScreen, row: TextBox) -> bool:
    y = row.center[1]+14
    hsv = cv.cvtColor(s.image[y-22:y+22, 825:875], cv.COLOR_BGR2HSV)
    blue = (hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 120) & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 140)
    return float(np.mean(blue)) > .10


def sweep_rows(s: EventScreen) -> list[SweepRow] | None:
    if not (bulk_catalogue(s) or bulk_confirmation(s)):
        return None
    result = []
    labels = s.all(r'.+领域\d+层', (40, 70, 500, 325))
    for label in labels:
        scope = text_scope(label.text)
        if label.score < .95 or not scope or scope['area'] == AREAS['memory']:
            return None
        y = label.center[1]
        pair = count_pair(s, (300, y+10, 495, y+42))
        if not pair:
            return None
        result.append(SweepRow(scope['area'], scope['floor'], pair[0], checked(s, label), label))
    if not result or len({r.area for r in result}) != len(result):
        return None
    # Unknown future domains must never be omitted from a selected sweep.
    if len(s.all(r'.+\d+层', (40, 70, 500, 325))) != len(labels):
        return None
    return result


def receipt(s: EventScreen) -> bool:
    return bool(s.find('一?键扫荡结果|扫荡结果|扫荡完毕|报酬领取|收取报酬', (250, 0, 720, 80), exact=True)
                and s.find('获得|报酬|道具', (50, 65, 920, 425))
                and s.find('确认|关闭|确定', (250, 430, 720, 525), exact=True))


def sweep_summary(screen: EventScreen):
    title = screen.find('扫荡结果', (300, 0, 660, 70), exact=True)
    quantity = screen.find(r'扫荡次数\d+次', (300, 65, 660, 115), exact=True)
    stages = screen.find(r'\d+只击破[!！]', (300, 95, 660, 165), exact=True)
    button = screen.find('确认', (350, 440, 615, 525), exact=True)
    if not all(box and box.score >= .95 for box in (title, quantity, stages, button)):
        return None
    return dict(quantity=int(re.search(r'\d+', normalized(quantity.text))[0]),
                stages=int(re.search(r'\d+', normalized(stages.text))[0]))


def sweep_stage_count(ui, screen: EventScreen):
    """The orange count and unit may be separate OCR boxes at one stage."""
    if not bulk_confirmation(screen):
        return None
    roi = (690, 360, 770, 400)
    item = screen.find(r'\d+处', roi, exact=True)
    if item and item.score >= .95:
        return int(normalized(item.text)[:-1])
    local = ui.read_region(screen, roi, classify=False)
    items = sorted(local.items, key=lambda box: box.center[0])
    if not 1 <= len(items) <= 2 or any(box.score < .95 for box in items):
        return None
    text = ''.join(normalized(box.text) for box in items)
    return int(text[:-1]) if re.fullmatch(r'\d+处', text) else None


def claim_enabled(s: EventScreen) -> bool | None:
    if detail_scope(s).get('area') != AREAS['memory']:
        return None
    item = s.find('领取', (580, 395, 685, 460), exact=True)
    if not item or item.score < .95:
        return None
    if s.blue_button(item):
        return True
    x, y = item.center
    hsv = cv.cvtColor(s.image[y-11:y+11, x-20:x+20], cv.COLOR_BGR2HSV)
    ink = hsv[:, :, 2] < 180
    if np.count_nonzero(ink) < 20:
        return None
    saturation = hsv[:, :, 1][ink]
    # The settled disabled label has a faint blue shadow; a fading label is
    # lighter, so hue alone cannot distinguish these two empty-box frames.
    if float(np.mean(saturation < 80)) > .90:
        return False
    return None
