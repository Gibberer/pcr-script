"""Read-only recognition for Dawn Labyrinth ticket sweeps, in design coordinates."""
from __future__ import annotations

import re

from .screen import EventScreen, EventUIError, normalized

import cv2 as cv
import numpy as np


TITLE = r'黎明界迷宫'
SWEEP = r'跳过|扫荡'
LOCKED = r'通关1次难度\d+后可解锁|尚未通关|未通关|未解锁|无法(?:跳过|扫荡)'


def home(screen: EventScreen) -> bool:
    return bool(screen.find(TITLE, (45, 0, 270, 75), exact=True)
                and screen.find('持有通行证', (430, 280, 715, 385)))


def guild_selection(screen: EventScreen) -> bool:
    return bool(screen.find(TITLE, (45, 0, 270, 75), exact=True)
                and screen.find('请选择要同行的公会', (250, 65, 730, 120)))


def mission_reward_hint(screen: EventScreen) -> bool:
    return bool(home(screen) and (
        screen.counter_badge((905, 212, 949, 240))
        or screen.find(r'[1-9]\d*', (905, 212, 949, 240), exact=True)))


def missions_page(screen: EventScreen) -> bool:
    return bool(screen.find('任务', (240, 0, 720, 75), exact=True)
                and screen.find('全部', (40, 60, 325, 115), exact=True)
                and screen.find('普通', (325, 60, 650, 115), exact=True)
                and screen.find('公会', (650, 60, 930, 115), exact=True)
                and screen.find('取消', (255, 440, 465, 515), exact=True)
                and screen.find('全部收取', (480, 440, 705, 515), exact=True))


def mission_receipt(screen: EventScreen) -> bool:
    return bool(screen.find('收取报酬', (240, 0, 720, 75), exact=True)
                and screen.find('获得了以下报酬|收取了以下道具', (250, 55, 730, 110)))


def sweep_confirmation(screen: EventScreen) -> bool:
    return bool(screen.find(r'(?:迷宫)?(?:跳过|扫荡)(?:确认)?', (240, 0, 720, 100), exact=True)
                and screen.find('通行证', (200, 75, 760, 445)))


def sweep_guild_selection(screen: EventScreen) -> bool:
    """Only sweep-labelled controls can select a guild; ordinary departure cannot."""
    return sweep_catalogue(screen) or bool(screen.find('公会') and sweep_choices(screen))


def sweep_catalogue(screen: EventScreen) -> bool:
    return bool(screen.find('可跳过的公会一览', (240, 0, 760, 100), exact=True)
                and screen.find('通行证使用数量', (470, 390, 620, 445))
                and screen.find('一键扫荡', (700, 440, 930, 520), exact=True))


def catalogue_guilds(screen: EventScreen) -> list:
    if not sweep_catalogue(screen):
        return []
    result = []
    for marker in screen.all(TITLE, (40, 140, 250, 370)):
        if normalized(marker.text) != TITLE:
            continue
        y = marker.center[1]
        name = screen.find('.+', (40, y-50, 250, y-10))
        if marker.score >= .95 and name and name.score >= .95:
            result.append(name)
    return sorted(result, key=lambda item: item.center[1])


def catalogue_selected(screen: EventScreen, guild) -> bool:
    if not sweep_catalogue(screen) or guild is None:
        return False
    y = guild.center[1]
    patch = cv.cvtColor(screen.image[y-4:y+28, 832:869], cv.COLOR_BGR2HSV)
    return bool(np.mean((patch[:, :, 0] > 85) & (patch[:, :, 0] < 125)
                        & (patch[:, :, 1] > 70) & (patch[:, :, 2] > 150)) > .30)


def catalogue_preview(ui, screen: EventScreen) -> tuple[int, int] | None:
    if not sweep_catalogue(screen) or not screen.find('通行证', (40, 405, 170, 450), exact=True):
        return None
    before = ui.number(screen, (224, 411, 268, 452))
    after = ui.number(screen, (323, 411, 371, 452))
    quantity = ui.number(screen, (740, 397, 792, 432))
    if (before is None or after is None or quantity is None
            or not 0 <= after < before <= 99 or not 1 <= quantity <= before
            or before-after != quantity):
        return None
    return before, after


def bulk_confirmation(screen: EventScreen) -> bool:
    return bool(screen.find('一?键扫荡确认', (240, 0, 720, 100), exact=True)
                and screen.find('即将消耗通行证.*对以下公会及难度执行跳过操作', (200, 60, 760, 100))
                and screen.find('消耗通行证', (40, 380, 180, 430), exact=True)
                and screen.find('合计扫荡次数', (775, 340, 905, 380), exact=True))


def bulk_guild(screen: EventScreen):
    markers = [m for m in screen.all(TITLE, (40, 130, 250, 330)) if normalized(m.text) == TITLE]
    if not bulk_confirmation(screen) or len(markers) != 1 or markers[0].score < .95:
        return None
    y = markers[0].center[1]
    guild = screen.find('.+', (40, y-50, 250, y-10))
    return guild if guild and guild.score >= .95 else None


def bulk_preview(ui, screen: EventScreen) -> tuple[int, int] | None:
    if not bulk_guild(screen) or not screen.find('通行证', (255, 380, 395, 430), exact=True):
        return None
    cost = ui.number(screen, (235, 382, 268, 426))
    before = ui.number(screen, (443, 382, 490, 427))
    row_quantity = ui.number(screen, (865, 127, 898, 163))
    total = ui.number(screen, (863, 377, 905, 424))
    if (cost is None or before is None or not 1 <= cost <= before <= 99
            or row_quantity != cost or total != cost):
        return None
    return before, before-cost


def sweep_choices(screen: EventScreen) -> list:
    explicit_mode = (screen.find(r'(?:迷宫)?(?:跳过|扫荡)(?:公会)?(?:选择)?',
                                 (240, 0, 720, 100), exact=True)
                     or screen.find(r'请选择(?:要)?(?:跳过|扫荡)的公会'))
    if explicit_mode:
        return screen.all(r'^(?:跳过|扫荡|选择)$', (20, 170, 940, 495))
    if screen.find(TITLE, (45, 0, 270, 75), exact=True):
        return screen.all(r'^(?:跳过|扫荡)$', (20, 170, 940, 495))
    return []


def sweep_guild_controls(screen: EventScreen) -> list:
    """Bind enabled sweep controls to one legible name on the same card.

    An unbound control retains a None label so a sweep cannot silently skip an
    unreadable eligible guild while searching for the preferred one.
    """
    result = []
    for button in sweep_choices(screen):
        if not screen.blue_button(button):
            continue
        x, y = button.center
        card = (max(20, x-125), max(100, y-110), min(940, x+125), y-25)
        if screen.find(LOCKED, card):
            continue
        labels = [item for item in screen.all('.+', card)
                  if normalized(item.text) != TITLE
                  and not re.fullmatch(r'难度[1-5]', normalized(item.text))]
        name = (labels[0] if len(labels) == 1 and labels[0].score >= .95
                and re.search(r'[\u4e00-\u9fffA-Za-z]', normalized(labels[0].text))
                and button.score >= .95 else None)
        result.append((name, button))
    return sorted(result, key=lambda pair: (pair[1].center[0], pair[1].center[1]))


def sweep_guild_evidence(screen: EventScreen, name: str):
    """Bind a cleared guild to its sweep row, card control, or popup body."""
    wanted = normalized(name)
    if sweep_catalogue(screen):
        return next((guild for guild in catalogue_guilds(screen)
                     if normalized(guild.text) == wanted), None)
    if bulk_confirmation(screen):
        guild = bulk_guild(screen)
        return guild if guild and normalized(guild.text) == wanted else None
    pattern = '^'+re.escape(wanted)+'$'
    if sweep_confirmation(screen):
        # Exclude the ordinary guild cards behind the confirmation popup.
        body = (240, 100, 720, 300)
        if screen.find(LOCKED, body):
            return None
        return next((guild for guild in screen.all(pattern, body) if guild.score >= .95), None)
    if sweep_guild_selection(screen):
        return next((guild for guild, _ in sweep_guild_controls(screen)
                     if guild and normalized(guild.text) == wanted), None)
    return None


def locked_notice(screen: EventScreen):
    hint = screen.find(r'通关1次难度\d+后可解锁')
    if hint:
        return hint
    # A sweep chooser may show "未通关" on individual guild cards while
    # another guild is eligible. Those labels are not a global unlock failure.
    if sweep_guild_selection(screen):
        return None
    return screen.find(LOCKED, (230, 85, 800, 380))


def receipt(screen: EventScreen) -> bool:
    return bool(screen.find(
        r'(?:迷宫)?(?:跳过|扫荡)结果|报酬确认|获得报酬|获得奖励|获得道具|'
        r'宝箱开启|开启宝箱|开启结果|宝箱开封结果', (140, 0, 820, 110), exact=True))


def chest_receipt(screen: EventScreen) -> bool:
    return bool(screen.find('宝箱开封结果', (240, 0, 720, 100), exact=True)
                and screen.find('已开封从迷宫带回的宝箱', (180, 60, 780, 140)))


def _row(screen: EventScreen, label) -> list:
    x1 = min(point[0] for point in label.box)
    y = label.center[1]
    return sorted((item for item in screen.items if item.score >= .95
                   and abs(item.center[1] - y) <= 18
                   and item.center[0] >= x1 - 5 and item.center[0] <= 760),
                  key=lambda item: item.center[0])


def held_passes(screen: EventScreen) -> int | None:
    """Missing or conflicting numbers stay unknown, including an unreadable zero."""
    if not home(screen):
        return None
    label = screen.find('持有通行证', (430, 280, 715, 385))
    if label.score < .95:
        return None
    values = []
    for item in _row(screen, label):
        values.extend(int(value) for value in re.findall(r'(?<!\d)(\d+)/99(?!\d)', normalized(item.text)))
    return values[0] if len(values) == 1 and 0 <= values[0] <= 99 else None


def read_held_passes(ui, screen: EventScreen) -> int | None:
    value = held_passes(screen)
    if value is not None:
        return value
    label = screen.find('持有通行证', (430, 280, 715, 385))
    if not home(screen) or label is None or label.score < .95:
        return None
    if any(re.search(r'(?<!\d)\d+/99(?!\d)', normalized(item.text)) for item in _row(screen, label)):
        # Conflicting or invalid explicit counters cannot be overwritten.
        return None
    # The angle classifier can turn the upright 9/99 into 66/6. The field's
    # orientation is known; reread it without rotation, requiring the /99 label.
    region = ui.read_region(screen, (630, 318, 695, 355), classify=False)
    if not isinstance(region, EventScreen):
        return None
    values = [int(match[1]) for item in region.all('.+', (630, 318, 695, 355))
              if item.score >= .95 and (match := re.fullmatch(r'(\d{1,2})/99', normalized(item.text)))]
    return values[0] if len(values) == 1 else None


def departure_confirmation(screen: EventScreen) -> bool:
    return bool(screen.find('公会选择确认', (240, 0, 720, 75), exact=True)
                and screen.find(r'将消耗1张迷宫通行证和.*美食殿堂.*一同出发', (170, 65, 800, 115)))


def invitation_animation(screen: EventScreen) -> bool:
    items = screen.all('.+')
    caption = bool(1 <= len(items) <= 3
                and all(620 <= item.center[0] <= 950 and 380 <= item.center[1] <= 520
                        for item in items)
                and screen.find(r'[\u4e00-\u9fff]{1,10}', (620, 380, 950, 520), exact=True))
    if caption:
        return True
    if items or screen.find('菜单|地图|确认|取消|选择'):
        return False
    # The one-character caption "忍" can disappear in full-frame OCR. Require
    # the invitation's cyan pixel frame and dark violet inset together.
    patch = cv.cvtColor(screen.image[384:496, 622:932], cv.COLOR_BGR2HSV)
    cyan = np.mean((patch[:, :, 0] > 75) & (patch[:, :, 0] < 105)
                   & (patch[:, :, 1] > 80) & (patch[:, :, 2] > 160))
    violet = np.mean((patch[:, :, 0] > 105) & (patch[:, :, 0] < 145)
                     & (patch[:, :, 1] > 65) & (patch[:, :, 2] < 140))
    return bool(cyan > .12 and violet > .15)


def exploration_map(screen: EventScreen) -> bool:
    return bool(screen.find(TITLE, (45, 0, 280, 75), exact=True)
                and screen.find('撤退', (590, 450, 750, 525))
                and screen.find('返回', (775, 450, 935, 525))
                and screen.find('区域', (300, 0, 375, 70)))


def exploration_menu(screen: EventScreen) -> bool:
    return bool(screen.find('难度详情', (680, 85, 805, 265), exact=True)
                and screen.find('设定', (770, 85, 865, 265), exact=True)
                and screen.find('玩法', (680, 190, 800, 375), exact=True))


def battle_detail(screen: EventScreen) -> bool:
    return bool(screen.find(r'战斗格子\((?:普通|强敌|BOSS)\)|首领战格子', (30, 15, 500, 90), exact=True)
                and screen.find('挑战', (715, 415, 930, 510), exact=True))


def selected_boss_team(screen: EventScreen) -> int | None:
    if not screen.find('队伍编组', (300, 0, 650, 70), exact=True):
        return None
    labels = screen.all(r'^队伍[1-3]$', (40, 65, 390, 110))
    if len(labels) != 3:
        return None
    selected = []
    for label in labels:
        x, y = label.center
        patch = cv.cvtColor(screen.image[y-8:y+9, x-30:x+31], cv.COLOR_BGR2HSV)
        if float(np.mean((patch[:, :, 0] > 10) & (patch[:, :, 0] < 35)
                         & (patch[:, :, 1] > 70) & (patch[:, :, 2] > 150))) > .35:
            selected.append(int(normalized(label.text)[-1]))
    return selected[0] if len(selected) == 1 else None


def enemy_information(screen: EventScreen) -> list[tuple[int, int]]:
    """Locate every pale round information button, independently of level OCR."""
    if not battle_detail(screen):
        return []
    hsv = cv.cvtColor(screen.image[295:338, 50:925], cv.COLOR_BGR2HSV)
    mask = cv.inRange(hsv, np.array([90, 25, 130]), np.array([115, 205, 255]))
    _, _, stats, centers = cv.connectedComponentsWithStats(mask)
    stems = [(s, c) for s, c in zip(stats[1:], centers[1:])
             if 3 <= s[2] <= 6 and 10 <= s[3] <= 17 and s[4] >= 25]
    dots = [c for s, c in zip(stats[1:], centers[1:])
            if 3 <= s[2] <= 6 and 3 <= s[3] <= 6 and s[4] >= 9]
    result = []
    for _, center in stems:
        if not any(abs(center[0]-dot[0]) <= 3 and 8 <= center[1]-dot[1] <= 14 for dot in dots):
            continue
        x, y = map(int, np.rint(center+(50, 292)))
        patch = cv.cvtColor(screen.image[y-12:y+14, x-12:x+13], cv.COLOR_BGR2HSV)
        if float(np.mean((patch[:, :, 1] < 45) & (patch[:, :, 2] > 155))) > .6:
            result.append((x, y))
    return sorted(result) if 1 <= len(result) <= 5 else []


def invitation_reward(screen: EventScreen) -> bool:
    return bool(screen.find('角色加入奖励!?', (250, 0, 720, 110), exact=True)
                and screen.find('邀请选择的角色成为伙伴', (190, 60, 780, 115)))


def reachable_battles(screen: EventScreen) -> list:
    if not exploration_map(screen):
        return []
    return [item for item in screen.all(r'^(?:普通|强敌|BOSS)$', (180, 85, 925, 440))
            if screen.blue_button(item)]


def reachable_nodes(screen: EventScreen) -> list:
    nodes = reachable_battles(screen)
    if not exploration_map(screen):
        return nodes
    for item in screen.all('^EVENT$', (180, 85, 925, 430)):
        x, y = item.center
        patch = screen.image[max(75, y-40):min(455, y+120), x-70:x+70]
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        if float(np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 110)
                         & (hsv[:, :, 1] > 95) & (hsv[:, :, 2] > 220))) > .1:
            nodes.append(item)
    for item in screen.all('^首领$', (375, 85, 600, 430)):
        x, y = item.center
        patch = screen.image[max(75, y-20):min(455, y+90), x-80:x+80]
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        if float(np.mean((hsv[:, :, 0] > 125) & (hsv[:, :, 0] < 165)
                         & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 190))) > .18:
            nodes.append(item)
    return nodes


def movement_confirmation(screen: EventScreen) -> bool:
    return bool(screen.find('移动目标确认', (240, 95, 720, 185), exact=True)
                and screen.find(r'将移动到(?:战斗格子\((?:普通|强敌|BOSS)\)|事件格子|迷宫遗物格子|商店格子|首领战格子)', (250, 265, 710, 335)))


def unlabelled_node(screen: EventScreen):
    if not exploration_map(screen):
        return None
    hsv = cv.cvtColor(screen.image[85:450, 380:600], cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 110)
            & (hsv[:, :, 1] > 95) & (hsv[:, :, 2] > 220)).astype(np.uint8)*255
    mask = cv.morphologyEx(mask, cv.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, _, stats, centers = cv.connectedComponentsWithStats(mask)
    nodes = [tuple(np.rint(center+(380, 85)).astype(int))
             for (x, y, w, h, area), center in zip(stats[1:], centers[1:])
             if 90 <= w <= 145 and 60 <= h <= 200 and area >= 4000 and area/(w*h) > .35]
    return nodes[0] if len(nodes) == 1 else None


def event_screen(screen: EventScreen) -> bool:
    return bool(screen.find('触发事件!?', (250, 0, 720, 110), exact=True))


def shop(screen: EventScreen) -> bool:
    return bool(screen.find('商店', (240, 0, 720, 75), exact=True)
                and screen.find('可使用阿尔法金币购买道具', (190, 50, 780, 115)))


def shop_exit(screen: EventScreen) -> bool:
    return bool(screen.find('商店确认', (240, 95, 720, 185), exact=True)
                and screen.find('将退出商店', (300, 200, 660, 260)))


def boss_failure(screen: EventScreen) -> bool:
    return bool(screen.find('战斗失败', (240, 0, 720, 110), exact=True)
                and screen.find('第[123]?战', (40, 105, 225, 220), exact=True)
                and screen.find('重新挑战', (700, 470, 930, 535), exact=True)
                and screen.find('结束', (470, 470, 690, 535), exact=True))


def damage_report(screen: EventScreen) -> bool:
    return bool(screen.find('伤害报告', (300, 0, 650, 75), exact=True)
                and screen.find('造成的伤害', (230, 55, 400, 100), exact=True)
                and screen.find('受到的伤害', (450, 55, 630, 100), exact=True)
                and screen.find('确认', (320, 440, 650, 520), exact=True))


def inventory_result(screen: EventScreen) -> bool:
    return bool(screen.find('RESULT', (300, 25, 660, 100), exact=True)
                and screen.find('难度1', (400, 0, 570, 50), exact=True)
                and screen.find('加入的角色', (90, 75, 300, 130), exact=True)
                and screen.find('已获得的迷宫遗物', (90, 200, 350, 330), exact=True)
                and screen.find('下一步', (320, 450, 650, 525), exact=True))


def score_result(screen: EventScreen) -> bool:
    return bool(screen.find('RESULT', (300, 25, 660, 100), exact=True)
                and screen.find('难度1', (400, 0, 570, 50), exact=True)
                and screen.find('分数明细', (90, 205, 310, 265), exact=True)
                and screen.find('难度奖励', (300, 390, 470, 450), exact=True)
                and screen.find('关闭', (320, 450, 650, 525), exact=True))


def difficulty_unlock(screen: EventScreen) -> bool:
    return bool(screen.find('难度解锁', (240, 100, 720, 185), exact=True)
                and screen.find('难度2已解锁', (200, 220, 760, 310))
                and screen.find('关闭', (320, 335, 650, 415), exact=True))


def settlement_screen(screen: EventScreen) -> bool:
    return inventory_result(screen) or score_result(screen) or chest_receipt(screen) or difficulty_unlock(screen)


def clear_receipt(screen: EventScreen) -> bool:
    return bool(screen.find('探索结果|探索完成|探索结束|迷宫通关|通关结果',
                            (140, 0, 820, 110), exact=True)
                and screen.find('通关|CLEAR|报酬|宝箱'))


def free_event_choice(screen: EventScreen):
    if (not event_screen(screen)
            or screen.find('消耗|失去|扣除|损失|受到.*伤害|战斗|购买')):
        return None
    for button in sorted(screen.all('^选择$', (200, 410, 770, 490)), key=lambda item: item.center[0]):
        x, _ = button.center
        if (screen.blue_button(button)
                and screen.find('随机印记[×x][1-3]', (x-125, 350, x+125, 410))
                and screen.find(r'\+阿尔法金币[×x]\d+', (x-125, 350, x+125, 415))):
            if screen.find('这里是公会管理协会'):
                return button
        if (screen.find('在地下城迷路了|能听到从箱子里传出的声音|活动会场出现了魔物') and screen.blue_button(button)
                and screen.find(r'^阿尔法金币[×x]\d+$', (x-125, 350, x+125, 415), exact=True)
                and len(screen.all('.+', (x-125, 350, x+125, 415))) == 1):
            return button
    return None


def relic_reward(screen: EventScreen) -> bool:
    return bool(screen.find('获得道具的机会!?', (200, 0, 760, 110), exact=True)
                and screen.find('请选择要获得的迷宫遗物', (190, 60, 780, 115)))


def positive_relic_choice(screen: EventScreen):
    if not relic_reward(screen) or not screen.find('还剩[1-3]次', (400, 105, 560, 145), exact=True):
        return None
    choices = []
    for button in screen.all('^选择$', (90, 420, 875, 510)):
        if not screen.blue_button(button):
            continue
        x, _ = button.center
        effects = screen.all('.+', (x-110, 350, x+110, 425))
        if len(effects) != 1 or effects[0].score < .95:
            continue
        effect = normalized(effects[0].text)
        match = re.fullmatch(r'(物理/魔法攻击力|物理/魔法防御力|物理/魔法暴击|HP)\+(\d+)%', effect)
        if match:
            priority = {'HP': 4, '物理/魔法防御力': 3, '物理/魔法攻击力': 2, '物理/魔法暴击': 1}[match[1]]
            choices.append((priority, int(match[2]), button))
        elif match := re.fullmatch(r'(生命值吸收|技能值上升量|技能值消耗减轻)\+(\d+)', effect):
            priority = {'生命值吸收': 4, '技能值上升量': 3, '技能值消耗减轻': 3}[match[1]]
            choices.append((priority, int(match[2]), button))
        elif match := re.fullmatch(r'战斗开始时技能值回复(\d+)', effect):
            choices.append((2, int(match[1]), button))
    return max(choices, key=lambda value: value[:2])[2] if choices else None


# Known Food Hall difficulty-1 profiles, including final-boss companions.
# Match all bullet clauses; a missing or additional mechanic is unsupported.
NORMAL_ENEMY_DESCRIPTION_ROI = (260, 205, 700, 450)
_TP_REDUCTION = '造成伤害所获得的技能值回复量降低80%'
_THROUGH_IMMUNITY = '(在伤害免疫的情况下也会成功赋予)'
_NORMAL_ENEMY_SKILLS = dict.fromkeys(
    ('雪原山羊', '啫喱怪', '丛林守护者', '野性角鹿', '北海狮首领',
     '会动的战士雕像', '会动的剑士雕像'), ('近身攻击', _TP_REDUCTION))
_NORMAL_ENEMY_SKILLS.update({
    '快乐兽人': ('近身攻击、击退'+_THROUGH_IMMUNITY, _TP_REDUCTION),
    '气鼓蛙': ('近身攻击、撞飞、击退'+_THROUGH_IMMUNITY, _TP_REDUCTION),
    '愤怒章鱼': ('近身攻击、降低行动速度'+_THROUGH_IMMUNITY, _TP_REDUCTION),
    '水獭混混': ('攻击后方第二名角色，使其眩晕'+_THROUGH_IMMUNITY, _TP_REDUCTION),
    '气球鸟': ('全体回复',),
    '洞穴蜗牛': ('全体回复',),
    '狂乱花': ('以后方第二名角色为中心进行范围攻击、中毒', _TP_REDUCTION, '中毒伤害不回复技能值'),
    '魔界守门人': ('近身攻击两个目标，将其烧伤', _TP_REDUCTION, '烧伤伤害无法回复技能值'),
})


def normal_enemy_description(screen: EventScreen) -> str | None:
    """Read every description box, rejecting partial or low-confidence OCR."""
    roi = NORMAL_ENEMY_DESCRIPTION_ROI
    items = [item for item in screen.items if item.text.strip()
             and roi[0] <= item.center[0] <= roi[2] and roi[1] <= item.center[1] <= roi[3]]
    if (not screen.find('魔物详情', (240, 0, 720, 100), exact=True) or not items
            or any(item.score < .95 or any(not (roi[0] <= x <= roi[2] and roi[1] <= y <= roi[3])
                                          for x, y in item.box) for item in items)):
        return None
    return normalized(''.join(item.text for item in sorted(items, key=lambda item: (item.center[1], item.center[0]))))


def supported_normal_enemy(maximum_hp: int, description: str, *, name: str | None = None) -> bool:
    text = normalized(description).replace(',', '，')
    profile = _NORMAL_ENEMY_SKILLS.get(name)
    clauses = tuple(clause.rstrip('。') for clause in text.split('·')[1:])
    return bool(0 < maximum_hp <= 3000000 and profile and clauses == profile
                and not re.search(r'比例|百分比|即死|只(?:受|会受到)|免疫|无效|无法.*(?:魔法|物理)',
                                  text.replace(_THROUGH_IMMUNITY, '')))


def supported_boss(name, level, maximum_hp, effects, description):
    text = normalized(description)
    required = ('技能伤害无法回复技能值', '烧伤状态', '物理防御力越高',
                '魔法防御力越高', '降低敌方全体生命值吸收量', '对敌方全体造成魔法伤害',
                '击退敌方全体', '对前方一名敌人造成魔法固定伤害')
    return bool(name == '暗黑滴水嘴兽' and level == 350 and maximum_hp == 60000000
                and all(effect in effects for effect in ('坦克型', '物防下降', '魔防下降'))
                and all(phrase in text for phrase in required)
                and not re.search('比例|百分比|即死|免疫|无效', text))


def departure_preview(ui, screen: EventScreen) -> tuple[int, int]:
    if not departure_confirmation(screen) or not screen.find('持有迷宫通行证', (260, 405, 485, 445)):
        raise EventUIError('迷宫首通的公会或通行证消费确认无法核对')
    before = ui.number(screen, (530, 400, 586, 449))
    after = ui.number(screen, (659, 400, 723, 449))
    if before is None or after is None or not 1 <= before <= 99 or after != before - 1:
        raise EventUIError('迷宫首通的通行证消费前后数量无法核对')
    return before, after


def selected_difficulty(screen: EventScreen) -> int | None:
    if not screen.find('难度变更', (240, 0, 720, 75), exact=True):
        return None
    selected = []
    for label in screen.all(r'^难度[1-5]$', (285, 65, 400, 395)):
        _, y = label.center
        patch = screen.image[y+22:y+40, 274:292]
        if not patch.size:
            continue
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        if float(np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 120)
                         & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 180))) > .35:
            selected.append(int(normalized(label.text)[-1]))
    return selected[0] if len(selected) == 1 else None


def pass_preview(screen: EventScreen) -> tuple[int, int] | None:
    """Require two ordered balances on an explicitly labelled ticket row."""
    if not sweep_confirmation(screen):
        return None
    previews = []
    for label in screen.all('通行证', (200, 75, 760, 445)):
        if label.score < .95:
            continue
        fields = _row(screen, label)
        # The row must contain only its label and balance fields, never an
        # unrelated quantity or multiplier from the rewards/usage description.
        text = ' '.join(normalized(item.text) for item in fields)
        match = re.fullmatch(r'(?:持有|所持)?(?:迷宫)?通行证(?:持有数|数量|持有量)?'
                             r'[:：]?\s*(\d+)(?:/99)?\s*(?:→|⇒|>|▶)\s*(\d+)(?:/99)?', text)
        if match:
            pair = tuple(map(int, match.groups()))
        else:
            # The game may draw the arrow as an icon omitted by OCR. Retain
            # only two distinct numeric boxes next to the ticket balance label.
            if not re.fullmatch(r'(?:持有|所持)?(?:迷宫)?通行证(?:持有数|数量|持有量)?[:：]?', normalized(label.text)):
                continue
            others = [normalized(item.text) for item in fields if item is not label]
            if any(not re.fullmatch(r'(\d+)(?:/99)?|→|⇒|>|▶', text) for text in others):
                continue
            numbers = [re.fullmatch(r'(\d+)(?:/99)?', text) for text in others]
            numbers = [match for match in numbers if match]
            if len(numbers) != 2:
                continue
            pair = tuple(int(match[1]) for match in numbers)
        if 0 <= pair[1] < pair[0] <= 99:
            previews.append(pair)
    return previews[0] if len(previews) == 1 else None
