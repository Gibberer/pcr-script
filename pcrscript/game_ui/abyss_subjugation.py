"""Observed CN Abyss Subjugation pages, in the shared 960 x 540 space."""
from __future__ import annotations

import re

import cv2 as cv
import numpy as np

from .screen import normalized


DIFFICULTIES = ('普通', '困难', '高难')
BOSS_DIFFICULTIES = (*DIFFICULTIES, '极难')
OUTPOST_Y = (217, 291, 366)
SELECTOR_Y = (109, 208, 307)


def home(s):
    return bool(s.find('深渊讨伐战', (45, 0, 235, 60), exact=True)
                and s.find('前哨关卡', (80, 110, 245, 165), exact=True)
                and len(s.all('首领', (350, 295, 905, 380))) == 3
                and s.find('讨伐委托证', (700, 385, 820, 430), exact=True))


def outpost_detail(s):
    return bool(s.find('前哨关卡', (45, 25, 195, 85), exact=True)
                and s.find('剩余挑战次数', (315, 440, 465, 480), exact=True))


def boss_selector(s):
    return bool(s.find('首领难度选择', (290, 20, 670, 65), exact=True)
                and s.find('关闭', (365, 450, 600, 510), exact=True)
                and any(selector_difficulty(s, name) for name in BOSS_DIFFICULTIES))


def selector_difficulty(s, name, ui=None):
    roi = (410, 75, 555, 402)
    def visible(screen):
        item = screen.find(re.escape(name), roi, exact=True)
        return item if item and item.score >= .95 and max(p[1] for p in item.box) <= 399 else None
    item = visible(s)
    if item is None and ui is not None:
        # A visible coloured label can be missed by whole-frame OCR. Read
        # the button column before moving a list already at its boundary.
        item = visible(ui.read_region(s, roi, classify=False))
    return item


def boss_detail(s):
    return bool(s.find('BOSS详情', (45, 25, 170, 85), exact=True)
                and s.find('模拟战', (690, 85, 805, 135), exact=True)
                and s.find('实战', (810, 85, 920, 135), exact=True))


def detail_cancel(s):
    """Known navigation-only exit; never act through a confirmation overlay."""
    if (not (boss_detail(s) or outpost_detail(s))
            or s.find('确认|关闭|扫荡券确认|队伍编组|主菜单', exact=True)):
        return None
    cancel = s.find('取消', (580, 430, 755, 510), exact=True)
    challenge = s.find('挑战', (765, 430, 925, 510), exact=True)
    return cancel if cancel and challenge and min(cancel.score, challenge.score) >= .95 else None


def navigation_exit(s):
    """Leave a known selector or unstarted detail before entering another task."""
    if boss_selector(s):
        close = s.find('关闭', (365, 450, 600, 510), exact=True)
        return close if close.score >= .95 else None
    return detail_cancel(s)


def difficulty(s, ui=None):
    roi = (185, 30, 310, 75) if outpost_detail(s) else (150, 30, 285, 75)
    names = DIFFICULTIES if outpost_detail(s) else BOSS_DIFFICULTIES
    labels = [name for name in names if s.find(name, roi, exact=True)]
    if not labels and ui is not None:
        patch = (195, 34, 305, 68) if outpost_detail(s) else (160, 34, 278, 68)
        cropped = ui.read_region(s, patch, classify=False)
        labels = [name for name in names
                  if (item := cropped.find(name, roi, exact=True)) and item.score >= .95]
    return labels[0] if len(labels) == 1 else None


def fraction(s, roi):
    item = s.find(r'\d+/\d+', roi, exact=True)
    if item is None or item.score < .95:
        return None
    current, maximum = map(int, normalized(item.text).split('/'))
    return (current, maximum) if 0 <= current <= maximum and maximum > 0 else None


def attempts(s):
    values = [fraction(s, (190, y+8, 255, y+44)) for y in OUTPOST_Y]
    return dict(zip(DIFFICULTIES, (v[0] for v in values))) if all(v is not None for v in values) else None


def detail_attempts(s):
    value = fraction(s, (495, 440, 580, 480))
    return value[0] if value is not None else None


def stamina(s):
    item = s.find(r'\d+/\d+', (705, 0, 785, 45), exact=True)
    return int(normalized(item.text).split('/')[0]) if item and item.score >= .95 else None


def dates(s):
    text = normalized(s.text((30, 85, 290, 115)))
    match = re.fullmatch(r'举办时间[:：](\d{1,2})/(\d{2})(\d{2}):(\d{2})[～~至-]'
                         r'(\d{1,2})/(\d{2})(\d{2}):(\d{2})', text)
    return tuple(map(int, match.groups())) if match else None


def yellow(s, roi):
    x1, y1, x2, y2 = roi
    hsv = cv.cvtColor(s.image[y1:y2, x1:x2], cv.COLOR_BGR2HSV)
    return float(np.mean((hsv[:, :, 0] >= 15) & (hsv[:, :, 0] <= 40)
                         & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 170))) > .2


def selector_cleared(s, item):
    y = item.center[1]
    return bool(s.find('通关', (260, y-50, 340, y-5), exact=True))


def selector_locked(s, item):
    if selector_cleared(s, item):
        return False
    y = item.center[1]
    return yellow(s, (260, y-38, 300, y+5))


def mode(s):
    if not boss_detail(s):
        return None
    if s.find('现在的设定为模拟战', (620, 350, 925, 410)):
        return 'simulation'
    selected = [name for name, roi in (
        ('simulation', (711, 94, 785, 118)), ('real', (831, 94, 904, 118))) if yellow(s, roi)]
    return selected[0] if len(selected) == 1 else None


def quantity(s):
    item = s.find(r'使用\d+张', (655, 350, 845, 410), exact=True)
    return int(re.search(r'\d+', normalized(item.text))[0]) if item and item.score >= .95 else None


def sweep_button(s):
    return s.find(r'使用\d+张', (655, 350, 845, 410), exact=True)


def sweep_enabled(s):
    button = sweep_button(s)
    if button is None:
        return None
    if not s.blue_button(button):
        return False
    if boss_detail(s):
        # Disabled boss sweeps retain a dark blue background. Check the
        # bright interior above the label, not just its blue border.
        hsv = cv.cvtColor(s.image[357:366, 700:816], cv.COLOR_BGR2HSV)
        bright = float(np.mean((hsv[:, :, 0] >= 90) & (hsv[:, :, 0] <= 120)
                               & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] >= 195)))
        return True if bright >= .65 else False if bright <= .2 else None
    return True


def tickets(ui, s):
    if home(s):
        return ui.number(s, (825, 390, 875, 425))
    if boss_selector(s):
        return ui.number(s, (655, 415, 705, 447))
    if boss_detail(s):
        amount = quantity(s)
        value = s.find(r'\d+(?:[▶►→>]\d+)?', (775, 407, 925, 445), exact=True)
        spans_preview = value is not None and (max(p[0] for p in value.box) >= 902 or re.search('[▶►→>]', value.text))
        if mode(s) == 'real' and amount is not None and spans_preview and value.score >= .95:
            before = preview_balance(normalized(value.text), amount)
            if before is not None:
                return before
        # Keep the full width for multi-digit balances, but trim vertical
        # padding so an isolated small digit is recognized with confidence.
        return ui.number(s, (816, 414, 880, 439))
    return None


def preview_balance(text, amount):
    raw = re.sub('[▶►→>]', '', text)
    if not raw.isdigit():
        return None
    matches = []
    for split in range(1, len(raw)):
        left, right = raw[:split], raw[split:]
        if (len(left) > 1 and left.startswith('0')) or (len(right) > 1 and right.startswith('0')):
            continue
        before, after = int(left), int(right)
        if after == max(0, before-amount):
            matches.append(before)
    return matches[0] if len(matches) == 1 else None


def stamina_preview(ui, s):
    if not outpost_detail(s):
        return None
    before = ui.number(s, (165, 446, 211, 476))
    after = ui.number(s, (272, 446, 323, 476))
    if after is None:
        local = ui.read_region(s, (267, 442, 327, 480), classify=False)
        item = local.find(r'-\d+', (267, 442, 327, 480), exact=True)
        if item and item.score >= .95:
            after = int(normalized(item.text))
    return (before, after) if before is not None and after is not None and before >= after else None


def boss_health(ui, s):
    # Full-frame orientation classification can reverse an all-digit HP field.
    # Read its own box without orientation classification instead.
    local = ui.read_region(s, (499, 260, 703, 285), classify=False)
    return fraction(local, (499, 260, 703, 285))


def boss_name(s):
    text = normalized(s.text((275, 217, 550, 249)))
    match = re.fullmatch(r'(.{2,30}?)(?:等级[.．:：]?|Lv\.?)([1-9]\d*)', text, re.I)
    return match[1] if match else None


def boss_signature(ui, s):
    if not boss_detail(s):
        return None
    # Multi-part boss names push the separately recognized level beyond the
    # short-name area. Both labels still belong to the same fixed info row.
    labels = s.all('.+', (275, 217, 690, 249))
    def identity(rows):
        rows = [t for t in rows if normalized(t.text) != '弱点']
        if not rows or any(t.score < .95 for t in rows):
            return None
        text = normalized(''.join(t.text for t in sorted(rows, key=lambda t: t.center[0])))
        return re.fullmatch(r'(.{2,30}?)(?:等级[.．:：]?|Lv\.?)([1-9]\d*)', text, re.I)
    match = identity(labels)
    if match is None:
        local = ui.read_region(s, (275, 215, 690, 253), classify=False)
        match = identity(local.all('.+', (275, 217, 690, 249)))
    resolved = (match[1], int(match[2])) if match else None
    if resolved is None:
        rows = [t for t in labels if normalized(t.text) != '弱点']
        levels = [(t, re.fullmatch(r'(?:等级[.．:：]?|Lv\.?)([1-9]\d*)',
                                  normalized(t.text), re.I)) for t in rows]
        levels = [(t, m) for t, m in levels if m]
        names = [t for t in rows if not any(t is level for level, _ in levels)]
        if len(names) == len(levels) == 1 and names[0].score >= .95:
            name, (level, value) = names[0], levels[0]
            nx = max(p[0] for p in name.box)
            x1, x2 = min(p[0] for p in level.box), max(p[0] for p in level.box)
            y1, y2 = min(p[1] for p in level.box), max(p[1] for p in level.box)
            if abs(name.center[1]-level.center[1]) <= 10 and 0 <= x1-nx <= 40:
                # A combined label can have an uncertain separator while its
                # numeric suffix is clear. Independently confirm those digits
                # at high confidence; agreement with the original is required.
                roi = (round(x2-(x2-x1)*.4), round(y1+1), round(x2), round(y2-1))
                number = int(value[1]) if level.score >= .95 else ui.number(s, roi)
                if number == int(value[1]):
                    resolved = normalized(name.text), number
    health = boss_health(ui, s)
    if not resolved or health is None:
        return None
    return dict(boss=resolved[0], level=resolved[1], maximum_hp=health[1])


def cleared_boss(ui, s):
    damage = ui.number(s, (815, 319, 923, 347))
    if damage is not None and damage > 0:
        if sweep_enabled(s) is True:
            return True
        amount, owned = quantity(s), tickets(ui, s)
        skips = ui.number(s, (765, 295, 837, 327))
        if amount is not None and owned is not None and skips is not None and owned >= amount and skips >= amount:
            return False
        return None
    dash = s.find('[-—]', (875, 320, 925, 350), exact=True)
    if dash:
        return False
    local = ui.read_region(s, (865, 318, 925, 349), classify=False)
    if local.find('[-—]', (865, 318, 925, 349), exact=True):
        return False
    # OCR commonly omits this tiny standalone dash. Require its own dark,
    # short horizontal component; a disabled button alone is insufficient.
    patch = cv.cvtColor(s.image[321:348, 875:922], cv.COLOR_BGR2GRAY)
    _, _, stats, centers = cv.connectedComponentsWithStats((patch < 110).astype(np.uint8))
    parts = [(stat, center) for stat, center in zip(stats[1:], centers[1:]) if stat[4] >= 3]
    if len(parts) == 1:
        (_, _, width, height, _), (x, y) = parts[0]
        if 4 <= width <= 18 and 1 <= height <= 5 and width >= 2*height and 5 <= y <= 19:
            return False
    return None


def formation(s):
    return bool(s.find('队伍编组', (300, 15, 650, 70), exact=True)
                and s.find('当前的成员', (35, 370, 190, 410), exact=True))


def saved_teams(s):
    return bool(s.find('我的队伍一览', (280, 15, 700, 70), exact=True)
                and s.find('调用已完成登记的队伍进行战斗', (280, 105, 715, 145)))


def sweep_confirmation(s):
    return bool(s.find('扫荡券确认', (300, 115, 650, 185), exact=True)
                and s.find('取消', (290, 340, 445, 405), exact=True)
                and s.find('确认', (520, 340, 665, 405), exact=True))


def sweep_cost(ui, s, label):
    row = s.find(label, (240, 245, 410, 340), exact=True)
    if row is None or row.score < .95:
        return None
    y = row.center[1]
    value = ui.number(s, (432, y-15, 484, y+15))
    if value is not None:
        return value
    # The dotted row divider lowers recognition confidence for a thin "1".
    # A tighter crop is safe only when the full field contains one thin glyph;
    # otherwise cropping could discard a leading digit from a larger cost.
    patch = cv.cvtColor(s.image[y-15:y+15, 432:484], cv.COLOR_BGR2GRAY)
    _, _, stats, _ = cv.connectedComponentsWithStats((patch < 140).astype(np.uint8))
    glyphs = [stat for stat in stats[1:] if stat[4] >= 4]
    if len(glyphs) != 1 or not (1 <= glyphs[0][2] <= 8 and 8 <= glyphs[0][3] <= 22):
        return None
    roi = (452, y-12, 479, y+12)
    local = ui.read_region(s, roi, classify=False)
    one = local.find('1', roi, exact=True)
    return 1 if one is not None and one.score >= .95 else None


def limited_shop(s):
    return bool(s.find('限定商店', (340, 0, 620, 75), exact=True)
                and s.find('取消', (500, 430, 690, 520), exact=True))


def sweep_receipt(s):
    return bool(s.find('扫荡结果|扫荡完成|扫荡结束', (230, 0, 740, 110))
                or s.find('获得道具', (260, 0, 730, 100), exact=True))


def result_button(s):
    if sweep_receipt(s) or s.find('WIN|RESULT|TIMEUP|战斗结束|战斗失败|战斗胜利|伤害报告|伤害合计|获得道具|获得经验'):
        return s.find('下一步|确认|确定|关闭|跳过完毕|前往深渊讨伐战', (250, 335, 945, 525), exact=True)
    return None


def result_win(ui, s):
    if not result_button(s) or sweep_receipt(s):
        return False
    roi = (275, 70, 685, 250)
    pattern = r'WIN[!！]?|战斗胜利|胜利'
    won = s.find(pattern, roi, exact=True)
    if won is None or won.score < .95:
        # Orientation classification can rotate the stylized WIN into NIM.
        # Re-read the upright banner; never treat that misread as victory.
        won = ui.read_region(s, roi, classify=False).find(pattern, roi, exact=True)
    return won is not None and won.score >= .95


def result_damage(ui, s):
    # Shared battle-result layout; a score/bonus is never a damage observation.
    from .team_battle import result_damage as read_damage
    if not s.find('伤害合计', (35, 0, 160, 42), exact=True):
        return None
    local = ui.read_region(s, (30, 0, 305, 85), classify=False)
    return read_damage(local)
