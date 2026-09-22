"""Read-only fallback for characters without a rotating equipment frame."""
from __future__ import annotations

import re
import cv2 as cv
import numpy as np

from .screen import EventUI, EventUIError, normalized
from ..run_session import clock as time


def inspect_unreleased_equipment(ui: EventUI, name: str) -> str | None:
    """Confirm full identity by memory shard name, then an unreleased slot.

    Starts from a page with the standard bottom navigation. Returns fresh
    evidence only for the known single, not-yet-released equipment layout.
    Other equipment states deliberately remain unknown.
    """
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
    ui.driver.input(normalized(name).split('(')[0])
    time.sleep(1)
    ui.click((480, 115))
    s = ui.capture()
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
        if s.find(re.escape(normalized(name)+'的记忆碎片'), (470, 105, 925, 160), exact=True):
            ui.save('equipment_identity_'+name, s)
            ui.expect_click('专用装备', (775, 55, 860, 95), exact=True)
            s = ui.capture()
            if s.find('此专用装备1预定今后登场[。.]?', (470, 300, 925, 370), exact=True):
                return str(ui.save('equipment_unreleased_'+name, s))
            return None
        ui.click((30, 30))
        ui.wait(lambda s: s.find('角色一览', (40, 0, 250, 65)), '返回角色一览')
    return None
