"""Read the six ordinary equipment slots without equipping or strengthening."""
from __future__ import annotations

import re
import cv2 as cv
import numpy as np

from .character_equipment import open_character_memory
from .screen import EventScreen, EventUIError, normalized
from ..run_session import clock as time


SLOT_CENTERS = ((130, 141), (96, 229), (129, 317),
                (365, 141), (402, 229), (365, 317))


def ordinary_page(screen):
    return bool(screen.find('角色强化', (40, 0, 250, 65), exact=True)
                and screen.find('一键装备', (185, 300, 315, 370), exact=True)
                and screen.find('装备', (465, 55, 545, 95), exact=True))


def selected_slot(screen, index):
    """Four white corner brackets identify the slot whose detail is visible."""
    if type(index) is not int or not 0 <= index < 6 or not ordinary_page(screen):
        return False
    x, y = SLOT_CENTERS[index]
    patch = screen.image[y-46:y+46, x-46:x+46]
    if patch.shape[:2] != (92, 92):
        return False
    hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 35) & (hsv[:, :, 2] > 230)).astype(np.uint8)
    _, _, components, _ = cv.connectedComponentsWithStats(mask)
    corners = set()
    for left, top, width, height, area in components[1:]:
        if not (14 <= width <= 22 and 14 <= height <= 22 and 90 <= area <= 210):
            continue
        horizontal = 0 if 0 <= left <= 14 else 1 if 60 <= left <= 74 else None
        vertical = 0 if 0 <= top <= 14 else 1 if 60 <= top <= 74 else None
        if horizontal is not None and vertical is not None:
            corners.add((horizontal, vertical))
    return len(corners) == 4


def slot_fields(screen, index):
    if not selected_slot(screen, index):
        return None
    future = screen.find('这件装备预定今后登场[。.]?', (475, 300, 925, 410), exact=True)
    if future and future.score >= .95:
        return dict(index=index, available=False, equipped=False, strengthened=None)
    title = screen.all('.+', (475, 105, 920, 145))
    attributes = screen.find('装备属性值', (475, 245, 640, 285), exact=True)
    enhance = screen.find('强化', (705, 410, 925, 470), exact=True)
    equip = screen.find('装备', (705, 410, 925, 470), exact=True)
    maximum = screen.find('这件装备的强化阶段已达极限[。.]?', (475, 355, 925, 410), exact=True)
    max_known = bool(maximum and maximum.score >= .95)
    name_known = bool(len(title) == 1 and title[0].score >= .95
                      and re.search(r'[\u4e00-\u9fff]', title[0].text))
    if (not attributes or attributes.score < .95
            or (enhance is None) == (equip is None)
            or (enhance or equip).score < .95
            or not (name_known or enhance is not None and max_known)):
        return None
    # The explicit maximum-enhancement phrase plus the selected slot and
    # Enhance control proves installation even when the rare item name is
    # unreadable. Its name remains unknown and cannot satisfy an item match.
    return dict(index=index, available=True, equipped=enhance is not None,
                strengthened=True if max_known else None,
                name=normalized(title[0].text) if name_known else None)


def summarize_slots(rows):
    if (not isinstance(rows, list) or len(rows) != 6
            or {row.get('index') for row in rows if isinstance(row, dict)} != set(range(6))
            or any(type(row.get('index')) is not int for row in rows)
            or any(type(row.get(key)) is not bool for row in rows for key in ('available', 'equipped'))
            or any(row['equipped'] and not row['available'] for row in rows)):
        raise EventUIError('六个普通装备槽的状态尚未完整核验')
    available = sum(row['available'] for row in rows)
    equipped = sum(row['equipped'] for row in rows)
    if available < 1:
        raise EventUIError('普通装备开放槽数未知')
    return dict(equipment=equipped, equipment_available=available)


def read_slot_fields(ui, screen, index):
    result = slot_fields(screen, index)
    if result is not None or not selected_slot(screen, index):
        return result
    # A rare item-name glyph may be weak in whole-frame OCR. Re-read only
    # the observed title from the same pixels; all other evidence stays live.
    roi = (475, 105, 920, 145)
    local = ui.read_region(screen, roi, classify=False)
    kept = [item for item in screen.items if not
            (roi[0] <= item.center[0] <= roi[2] and roi[1] <= item.center[1] <= roi[3])]
    return slot_fields(EventScreen(screen.image, kept+local.items), index)


def inspect_ordinary_equipment(ui, name, *, check=lambda: None, inspect_training=False):
    check()
    memory = open_character_memory(ui, name)
    if memory is None:
        return None
    observed_at = time.time()
    ui.expect_click('装备', (465, 55, 545, 95), exact=True)
    screen = ui.wait(ordinary_page, '普通装备页')
    rank = ui.number(screen, (400, 380, 442, 414))
    level = ui.number(screen, (250, 410, 300, 444))
    if type(rank) is not int or rank < 1 or type(level) is not int or level < 1:
        raise EventUIError('普通装备所属人物的等级与Rank未明确')
    rows = []
    for index, point in enumerate(SLOT_CENTERS):
        check()
        ui.click(point)
        screen = ui.wait(lambda s: selected_slot(s, index), '普通装备槽'+str(index+1), timeout=8)
        if (ui.number(screen, (400, 380, 442, 414)) != rank
                or ui.number(screen, (250, 410, 300, 444)) != level):
            raise EventUIError('读取普通装备时人物培养发生变化')
        row = read_slot_fields(ui, screen, index)
        if row is None:
            raise EventUIError('普通装备槽'+str(index+1)+'的说明或穿戴状态未明确')
        row['evidence'] = str(ui.save('ordinary_slot_'+normalized(name)+'_'+str(index), screen))
        rows.append(row)
    result = dict(name=normalized(name), observed_at=observed_at, level=level, rank=rank,
                  values=summarize_slots(rows), slots=rows, evidence=[row['evidence'] for row in rows])
    if inspect_training:
        from .character_training import inspect_owned_training
        result.update(inspect_owned_training(ui, name, memory, check=check))
    return result
