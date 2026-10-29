"""Observed CN Zombie Land Saga collaboration controls (960 x 540)."""
from datetime import datetime
import re

from ..constants import SERVER_TIMEZONE
from .screen import normalized

TITLE = '僵尸乐园连结'
BOSS = '佐贺陶洛斯'
DIFFICULTIES = ('普通', '困难', '高难')


def confident(s, text, roi=(0, 0, 960, 540)):
    item = s.find(text, roi, exact=True)
    return item if item is not None and item.score >= .95 else None


def home(s):
    return bool((confident(s, TITLE+'[!！]?', (55, 15, 280, 85))
                 or (s.find(TITLE+'[!！]?', (55, 15, 280, 85), exact=True)
                     and confident(s, 'Re:DIEve', (55, 65, 280, 110))))
                and confident(s, '讨伐券', (650, 410, 750, 450))
                and confident(s, '挑战', (650, 360, 840, 420))
                and confident(s, '全体报酬', (560, 375, 640, 420)))


def tickets(ui, s):
    if not home(s):
        return None
    value = ui.number(s, (795, 413, 840, 450))
    return value if value is not None and 0 <= value <= 999 else None


def missions(s):
    return bool(confident(s, '任务', (390, 15, 560, 65))
                and confident(s, '全部收取', (490, 450, 700, 505))
                and confident(s, '取消', (265, 450, 470, 505))
                and s.find('限时任务', (200, 65, 800, 105)))


def period(s):
    if not missions(s):
        return None
    text = normalized(s.text((200, 65, 800, 105)))
    match = re.search(r'(20\d{2}/\d{1,2}/\d{1,2}\d{2}:\d{2})[~～〜](20\d{2}/\d{1,2}/\d{1,2}\d{2}:\d{2})', text)
    if not match:
        return None
    try:
        start, end = [datetime.strptime(value, '%Y/%m/%d%H:%M').replace(tzinfo=SERVER_TIMEZONE).timestamp()
                      for value in match.groups()]
        return (start, end+59) if 0 < end-start <= 31*86400 else None
    except ValueError:
        return None


def detail(s):
    return bool(confident(s, 'BOSS详情', (45, 25, 170, 75))
                and confident(s, '模拟战', (690, 105, 800, 145))
                and confident(s, '实战', (810, 105, 920, 145))
                and confident(s, '挑战', (765, 440, 925, 500)))


def difficulty(s):
    names = [name for name in DIFFICULTIES if confident(s, name, (175, 25, 295, 65))]
    return names[0] if detail(s) and len(names) == 1 else None


def first_clear_free(s):
    return bool(detail(s) and s.find('完成初次讨伐前不消耗', (440, 460, 590, 500)))


def target(s):
    if not detail(s):
        return None
    text = normalized(s.text((200, 250, 560, 285)))
    match = re.fullmatch(BOSS+r'等级[.。:]?(\d+)', text)
    hp = confident(s, r'[\d,]+/[\d,]+', (565, 320, 700, 355))
    if not match or hp is None or difficulty(s) is None:
        return None
    current, maximum = map(int, normalized(hp.text).replace(',', '').split('/'))
    if not 0 <= current <= maximum < 10**12:
        return None
    return dict(boss=BOSS, difficulty=difficulty(s), level=int(match[1]), current_hp=current, maximum_hp=maximum)


def formation(s):
    return bool(confident(s, '队伍编组', (250, 0, 730, 70))
                and confident(s, '战斗开始', (740, 390, 950, 510)))


def sweep_button(s):
    return confident(s, r'使用\d+张', (705, 380, 815, 430)) if detail(s) else None


def quantity(s):
    button = sweep_button(s)
    return int(re.search(r'\d+', normalized(button.text))[0]) if button else None


def skip_confirmation(s):
    return bool(confident(s, '跳过确认', (300, 120, 660, 175))
                and confident(s, '消耗讨伐券', (250, 250, 405, 285))
                and confident(s, '击破次数', (250, 305, 405, 340))
                and confident(s, '确认', (480, 340, 700, 405)))


def skip_result(s):
    """Return the defeat count; the animated title is often misread."""
    defeated = confident(s, r'(\d+)只击破!?', (370, 100, 600, 170))
    if (defeated and confident(s, '跳过次数', (370, 65, 530, 115))
            and confident(s, '确认', (370, 450, 590, 510))):
        return int(re.match(r'\d+', normalized(defeated.text))[0])
    return None


def cleared(ui, s):
    if not detail(s) or first_clear_free(s):
        return False
    label = confident(s, '跳过伤害', (450, 375, 585, 405))
    damage = ui.number(s, (480, 400, 595, 427)) if label else None
    button = sweep_button(s)
    completed = (confident(s, '已完成', (100, 430, 215, 490))
                 or confident(s, '通关', (160, 0, 235, 40)))
    return True if damage is not None and damage > 0 and button and (s.blue_button(button) or completed) else None


def ticket_preview(ui, s):
    if not detail(s) or not confident(s, '讨伐券', (460, 440, 585, 470)):
        return None
    before = ui.number(s, (485, 470, 520, 500))
    after = ui.number(s, (560, 470, 585, 493))
    return (before, after) if before is not None and after is not None and 0 <= after < before else None


def exchange(s):
    return bool(confident(s, '报酬交换', (50, 0, 245, 65))
                and confident(s, '奖励券', (710, 420, 835, 470))
                and confident(s, r'当前的列表|重置第\d+轮的报酬', (540, 280, 725, 330)))


def exchange_balance(ui, s):
    if not exchange(s):
        return None
    local = ui.read_region(s, (855, 423, 945, 465), classify=False)
    return ui.number(local if isinstance(local, type(s)) else s, (855, 423, 945, 465))


def exchange_receipt_close(s):
    if not s.find('获得的报酬将会直接增加到持有道具中', (250, 350, 800, 420)):
        return None
    return confident(s, '取消', (250, 390, 480, 470)) or confident(s, '确认', (370, 395, 590, 465))


def exchange_confirmation(ui, s):
    if not confident(s, '一键交换确认', (300, 60, 660, 115)):
        return None
    cost = confident(s, r'要批量兑换\d+张讨伐奖励券吗[？?]', (300, 135, 670, 190))
    label = confident(s, '即将重置的BOX数', (280, 205, 485, 245))
    button = confident(s, '交换', (480, 400, 710, 465))
    resets = ui.number(s, (602, 216, 625, 240)) if label else None
    if not cost or resets is None or button is None or not s.blue_button(button):
        return None
    return dict(quantity=int(re.search(r'\d+', cost.text)[0]), resets=resets, button=button)


EXCHANGE_MODE_POINTS = {'10次': (287, 161), '100次': (504, 161), '一键交换': (725, 161)}


def exchange_settings(s):
    return bool(confident(s, '便利设定', (300, 15, 660, 70))
                and all(confident(s, label, roi) for label, roi in (
                    ('10次', (305, 135, 375, 185)), ('100次', (525, 135, 600, 185)),
                    ('一键交换', (750, 135, 850, 185)))))


def exchange_mode(s):
    if not exchange_settings(s):
        return None
    import cv2 as cv
    import numpy as np
    selected = []
    for mode, (x, y) in EXCHANGE_MODE_POINTS.items():
        patch = cv.cvtColor(s.image[y-7:y+8, x-7:x+8], cv.COLOR_BGR2HSV)
        if float(np.mean((patch[:, :, 0] > 90) & (patch[:, :, 0] < 130)
                         & (patch[:, :, 1] > 80) & (patch[:, :, 2] > 140))) > .5:
            selected.append(mode)
    return selected[0] if len(selected) == 1 else None


def exchange_pool_empty(s):
    if not confident(s, '当前的列表', (300, 15, 660, 65)):
        return False
    target = confident(s, '重置目标报酬', (250, 95, 430, 140))
    ordinary = confident(s, '普通报酬', (250, 170, 430, 360))
    if target and ordinary:
        headings = [target, ordinary]
    else:
        # From pool six onward the observed layout has only ordinary rewards.
        # Require its heading at the very top and an explicit pool number;
        # a missed target heading in the earlier two-section layout is unsafe.
        ordinary = confident(s, '普通报酬', (250, 95, 430, 140))
        pool = confident(s, r'第\d+次报酬交换的阵容', (300, 65, 660, 95))
        if (not ordinary or not pool or int(re.search(r'\d+', pool.text)[0]) < 6
                or s.find('目标报酬')):
            return False
        headings = [ordinary]
    # More than one target reward pushes the ordinary-reward heading down.
    # Match each section total on its own heading row, never an item count.
    if not all(confident(s, r'剩余0/[1-9]\d*', (590, int(h.center[1])-15, 705, int(h.center[1])+15))
               for h in headings):
        return False
    reset = confident(s, '重置', (370, 445, 590, 510))
    return bool(reset and s.blue_button(reset))


def exchange_action(s, balance, ui=None):
    if not exchange(s) or balance < 1:
        return None
    one = confident(s, '一键交换', (710, 325, 940, 390))
    if one:
        # 便利设定 one-key exchange replaces the variable batch; never fall
        # back to single exchanges. The cost may be capped by the pool.
        cost = confident(s, r'(?:消耗|使用)\d+张', (710, 385, 940, 420))
        amount = int(re.search(r'\d+', cost.text)[0]) if cost else 0
        return (one, amount) if s.blue_button(one) and 1 <= amount <= balance else None
    def batch(page):
        button = confident(page, r'\d+次交换', (735, 335, 940, 385))
        count = int(re.search(r'\d+', button.text)[0]) if button else 0
        cost = confident(page, '使用'+str(count)+'张', (735, 385, 940, 420))
        if 1 <= count <= min(100, balance) and cost and s.blue_button(button):
            return button, count
        return None
    action = batch(s)
    if action is not None:
        return action
    if ui is not None:
        local = ui.read_region(s, (735, 335, 940, 420), classify=False)
        if isinstance(local, type(s)):
            return batch(local)
    return None


def navigation_exit(s):
    if exchange_pool_empty(s):
        return confident(s, '重置', (370, 445, 590, 510))
    if (confident(s, '重置完毕', (300, 115, 660, 175))
            and confident(s, '重置了报酬列表[。.]?', (300, 225, 660, 285))):
        return confident(s, '确认', (370, 340, 590, 400))
    if difficulty_menu(s):
        return confident(s, '取消', (260, 340, 480, 400))
    if detail(s) and not s.find('确认|关闭|扫荡券确认', exact=True):
        return confident(s, '取消', (590, 440, 750, 500))
    if missions(s):
        return confident(s, '取消', (265, 450, 470, 505))
    return None


def difficulty_menu(s):
    return bool(confident(s, '难度变更', (300, 120, 660, 170))
                and confident(s, '确认', (480, 340, 700, 400))
                and confident(s, '取消', (260, 340, 480, 400)))


def selected_difficulty(s, name):
    import cv2 as cv
    import numpy as np
    if not difficulty_menu(s) or name not in DIFFICULTIES:
        return False
    x, y = {'普通': (279, 229), '困难': (499, 229), '高难': (279, 300)}[name]
    hsv = cv.cvtColor(s.image[y-9:y+10, x-9:x+10], cv.COLOR_BGR2HSV)
    return bool(np.mean((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 120)
                        & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 140)) > .5)


def unlock_dialog(s):
    if (confident(s, '剧情解锁', (300, 120, 660, 170))
            and confident(s, 'Re:StartSAGA', (415, 245, 700, 300))
            and confident(s, '已解锁[。.]?', (415, 245, 700, 300))):
        return confident(s, '关闭', (370, 340, 590, 400))
    for name in DIFFICULTIES:
        if (confident(s, name+'解锁', (300, 120, 660, 170))
                and confident(s, name+'已解锁[。.]?', (300, 240, 660, 300))):
            return confident(s, '关闭', (370, 340, 590, 400))
    return None


def gem_reward(s):
    body = confident(s, r'获得了宝石[×xX]\d+', (300, 330, 700, 405))
    icon = confident(s, r'[×xX]\d+', (450, 270, 575, 320))
    if (body and icon and re.search(r'\d+', body.text)[0] == re.search(r'\d+', icon.text)[0]
            and confident(s, '挑战', (650, 360, 840, 425))):
        return body
    return None


def collective_reward(s):
    bodies = [confident(s, pattern, (280, 335, 700, 425)) for pattern in (
        r'获得了佐贺偶像是传奇联动纪念10次扭蛋券[×xX]\d+',
        r'超级不得了呢☆[×xX]\d+', r'宝石[×xX]\d+')]
    icons = [confident(s, r'[×xX]\d+', roi) for roi in (
        (300, 270, 375, 320), (495, 270, 570, 320), (670, 270, 765, 320))]
    if (all(bodies) and all(icons) and confident(s, '挑战', (650, 360, 840, 425))
            and all(re.search(r'[×xX](\d+)$', normalized(body.text))[1]
                    == re.search(r'[×xX](\d+)$', normalized(icon.text))[1]
                    for body, icon in zip(bodies, icons))):
        return bodies[0]
    return None


def tutorial(s):
    return bool(confident(s, '可可萝', (180, 380, 400, 430))
                and (s.find('在联动讨伐活动', (180, 420, 800, 505))
                     or s.find('总生命值|每日发放的讨伐券', (25, 20, 800, 505))))
