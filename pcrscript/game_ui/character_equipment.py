"""Read-only fallback for characters without a rotating equipment frame."""
from __future__ import annotations

import re
import cv2 as cv
import numpy as np

from .screen import EventUI, EventUIError, normalized
from ..run_session import clock as time


def open_character_memory(ui: EventUI, name: str):
    """Open the memory page and confirm the full costume name, without spending."""
    attempts = 0
    def open_list(s):
        nonlocal attempts
        button = s.find('角色', (130, 480, 250, 540), exact=True)
        if button and attempts < 3:
            attempts += 1
            ui.click(button, delay=1.5)
    ui.wait(lambda s: s.find('角色一览', (40, 0, 250, 65)), '角色一览', handle=open_list)
    for _ in range(8):
        s = ui.capture()
        if s.find('重置', (635, 65, 760, 110), exact=True):
            break
        ui.swipe((480, 170), (480, 390))
    else:
        raise EventUIError('角色一览搜索栏未确认')
    ui.click((689, 90))
    ui.click((480, 90))
    # Composite names can use a full-width equals sign in the database, while
    # the game's character search accepts the first component. The memory
    # shard label below still has to verify the exact full identity.
    ui.driver.input(normalized(name).split('(')[0].split('=')[0])
    time.sleep(1)
    ui.click((480, 115))
    s = ui.capture()
    ui.save('equipment_search_'+name,s)
    positions = []
    for y in (200, 347):
        for x in (175, 475, 775):
            patch = s.image[y-55:y+55, x-130:x+130]
            if np.mean(cv.cvtColor(patch, cv.COLOR_BGR2HSV)[:, :, 1] > 60) > .2:
                positions.append((x, y))
    for position in positions:
        ui.click(position)
        ui.wait(lambda s: s.find('角色强化', (40, 0, 250, 65)), '角色强化')
        ui.expect_click('才能开花', (680, 55, 775, 95), exact=True)
        s = ui.wait(lambda s: s.find('记忆碎片', (470, 105, 925, 160)), '角色衣装记忆碎片')
        ui.save('equipment_candidate_'+name,s)
        shard=s.find(re.escape(normalized(name)+'的记忆碎片'), (470, 105, 925, 160), exact=True)
        if not shard and normalized(name)=='涅妃=涅菈':
            # 2026-09-23 account evidence: memory label OCR reads 菈 as 莅,
            # and the title may read 菈 as 拉. Confirm the indexed portrait too.
            from .avatars import AvatarIndex,face_crop
            title=s.find(r'涅妃=涅[菈拉]',(145,65,385,102),exact=True)
            label=normalized(s.text((470,105,925,160))).replace('涅莅','涅菈')
            avatar=AvatarIndex().query([face_crop(s.image,(37,390,73,74))])[0]
            if title and avatar==normalized(name) and label==normalized(name)+'的记忆碎片':shard=title
        if shard:
            ui.save('equipment_identity_'+name, s)
            return s
        ui.click((30, 30))
        ui.wait(lambda s: s.find('角色一览', (40, 0, 250, 65)), '返回角色一览')
    return None


def inspect_unreleased_equipment(ui: EventUI, name: str) -> str | None:
    if open_character_memory(ui,name) is None:
        return None
    ui.expect_click('专用装备', (775, 55, 860, 95), exact=True)
    s = ui.capture()
    if s.find('此专用装备1预定今后登场[。.]?', (470, 300, 925, 370), exact=True):
        return str(ui.save('equipment_unreleased_'+name, s))
    return None
