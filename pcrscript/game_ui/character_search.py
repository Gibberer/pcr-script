"""Confirmed character-name input for formation and character-list searches."""
from __future__ import annotations

import subprocess

from .screen import EventUIError, normalized
from ..run_session import clock as time


def search_text_confirmed(base, screen, *, exact=False, area=(300, 110, 640, 165)):
    x1, y1, x2, y2 = area
    entered = normalized(' '.join(item.text for item in screen.items if item.score >= .75
        and x1 <= item.center[0] <= x2 and y1 <= item.center[1] <= y2))
    for expected, mistaken in (('千爱瑠', '干爱瑠'), ('千歌', '干歌'),
                              ('菈比莉斯塔', '莅比莉斯塔')):
        if base == expected:
            entered = entered.replace(mistaken, expected)
    return entered == base if exact else base in entered


def search_reset_confirmed(screen, *, page, page_area, field_area):
    if not screen.find(page, page_area):
        return False
    x1, y1, x2, y2 = field_area
    labels = [normalized(item.text) for item in screen.items if item.score >= .75
              and x1 <= item.center[0] <= x2 and y1 <= item.center[1] <= y2]
    return not labels or all(text in ('用角色名搜索', '请输入角色名') for text in labels)


def search_input_confirmation(base, screen, *, page='队伍编组', page_area=(300, 0, 650, 70)):
    if not screen.find(page, page_area):
        return None
    if normalized(screen.text((0, 440, 750, 540))) != base:
        return None
    return screen.find('确定', (800, 450, 940, 530), exact=True)


def search_character(ui, name, *, page='队伍编组', page_area=(300, 0, 650, 70),
                     field_area=(300, 110, 640, 165), reset=(691, 135),
                     field=(480, 136), defocus=(190, 390)):
    """Reset before retries; commit Android's edit before trusting game results."""
    base = normalized(name).split('(')[0].split('=')[0]
    failed = False
    for _ in range(3):
        screen = ui.capture()
        confirm = search_input_confirmation(base, screen, page=page, page_area=page_area)
        if confirm:
            ui.click(confirm)
            screen = ui.capture()
        if search_text_confirmed(base, screen, exact=True, area=field_area):
            ui.click(defocus, delay=1)
            screen = ui.capture()
            if search_text_confirmed(base, screen, exact=True, area=field_area):
                return screen
        ui.click(reset)
        # Reset and Android focus can finish after the click is acknowledged.
        # Wait for the old query to disappear before requesting a new editor.
        ui.wait(lambda s: search_reset_confirmed(s, page=page, page_area=page_area,
                    field_area=field_area), '角色搜索重置', timeout=5)
        ui.click(field, delay=1)
        # Observe the newly opened editor before delivering Unicode. Sending
        # while the preceding reset is closing it can silently discard text.
        focused = ui.capture()
        if not focused.find(page, page_area):
            raise EventUIError('搜索聚焦后未处于'+page+'页面')
        time.sleep(.3)
        try:
            ui.driver.input(base)
        except (subprocess.SubprocessError, OSError):
            failed = True
            continue
        # Acknowledgement can precede focus or delivery. A bounded retry starts
        # from an observed reset, so a queued name is never blindly appended.
        deadline = time.monotonic()+8
        while True:
            time.sleep(.5)
            screen = ui.capture()
            if not screen.find(page, page_area):
                raise EventUIError('角色搜索后未处于'+page+'页面')
            confirm = search_input_confirmation(base, screen, page=page, page_area=page_area)
            if confirm and time.monotonic() < deadline:
                ui.click(confirm)
                continue
            if search_text_confirmed(base, screen, exact=True, area=field_area):
                ui.click(defocus, delay=1)
                screen = ui.capture()
                if search_text_confirmed(base, screen, exact=True, area=field_area):
                    return screen
            if time.monotonic() >= deadline:
                break
    ui.save('search_input_unconfirmed_'+normalized(name), ui.capture())
    reason = '后台角色搜索输入失败' if failed else '搜索词未确认写入'
    raise EventUIError(reason+'，不能判断缺少角色：'+name)
