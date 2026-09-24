"""Read the five EX-equipment panels in a deep-area formation."""
from __future__ import annotations

import cv2 as cv
import numpy as np
from uuid import uuid4

from .screen import EventUI, EventUIError, normalized


SPECIAL_COLUMNS = (158, 337, 516, 694, 873)
SPECIAL_ROWS = (218, 291, 365)


def occupied_slots(image) -> list[list[bool | None]]:
    """Colored item art is distinct from the monochrome empty-slot icon."""
    result=[]
    for x in SPECIAL_COLUMNS:
        column=[]
        for y in SPECIAL_ROWS:
            hsv=cv.cvtColor(image[y-30:y+30,x-30:x+30],cv.COLOR_BGR2HSV)
            colored=float(np.mean((hsv[:,:,1]>100)&(hsv[:,:,2]>100)))
            column.append(True if colored>.08 else False if colored<.02 else None)
        result.append(column)
    return result


def equipment_changed(before, selected) -> bool:
    """Compare item art, since auto-equip can swap gear without filling a slot."""
    for x in SPECIAL_COLUMNS:
        for y in SPECIAL_ROWS:
            first=before[y-30:y+30,x-30:x+30].astype(np.int16)
            second=selected[y-30:y+30,x-30:x+30].astype(np.int16)
            if float(np.mean(np.abs(first-second)))>5:
                return True
    return False


def preview_slots(before_image, preview_image, before):
    """Resolve dimmed borrowed-item art against the same empty slot before auto-select."""
    selected=occupied_slots(preview_image)
    for i,x in enumerate(SPECIAL_COLUMNS):
        for j,y in enumerate(SPECIAL_ROWS):
            if selected[i][j] is not None:
                continue
            first=before_image[y-30:y+30,x-30:x+30].astype(np.int16)
            second=preview_image[y-30:y+30,x-30:x+30].astype(np.int16)
            difference=float(np.mean(np.abs(first[12:48,12:48]-second[12:48,12:48])))
            if before[i][j] is False and difference>30:
                selected[i][j]=True
            elif before[i][j] is True and difference<5:
                selected[i][j]=True
    return selected


def inspect_special_equipment(ui: EventUI, order: list[str]) -> dict:
    """Open and cancel the read-only panel; never equip or auto-equip."""
    screen=ui.capture()
    if not screen.find('队伍编组',(300,0,650,70),exact=True):
        raise EventUIError('特别装备检查起点不是编队')
    if '特别装备' not in normalized(screen.text((582,416,646,485))):
        raise EventUIError('编队特别装备入口未确认')
    ui.click((615,454))
    panel=ui.wait(lambda s:s.find('特别装备设定',(320,15,650,65),exact=True),'特别装备设定')
    slots=occupied_slots(panel.image)
    evidence=str(ui.save('abyss_special_equipment_'+uuid4().hex[:8],panel))
    ui.expect_click('取消',(35,445,265,520),exact=True)
    ui.wait(lambda s:s.find('队伍编组',(300,0,650,70),exact=True),'特别装备返回编队')
    return dict(order=list(order),slots=slots,empty=sum(v is False for col in slots for v in col),
                unknown=sum(v is None for col in slots for v in col),evidence=evidence)


def auto_equip_special(ui: EventUI, order: list[str]) -> dict:
    """Use the game's automatic EX loadout and verify the committed slots."""
    screen=ui.capture()
    tag=uuid4().hex[:8]
    if not screen.find('队伍编组',(300,0,650,70),exact=True):
        raise EventUIError('特别装备自动装备起点不是编队')
    if '特别装备' not in normalized(screen.text((582,416,646,485))):
        raise EventUIError('编队特别装备入口未确认')
    before_power=screen.number((505,375,590,402))
    ui.click((615,454))
    panel=ui.wait(lambda s:s.find('特别装备设定',(320,15,650,65),exact=True),'特别装备设定')
    before=occupied_slots(panel.image)
    before_evidence=str(ui.save('abyss_special_before_'+tag,panel))
    ui.expect_click('自动装备',(485,447,705,515),exact=True)
    settings=ui.wait(lambda s:s.find('自动特别装备设定',(320,15,650,65),exact=True),'自动特别装备设定')
    settings_evidence=str(ui.save('abyss_special_auto_settings_'+tag,settings))
    ui.expect_click('确认',(480,447,705,515),exact=True)
    preview=ui.wait(lambda s:s.find('特别装备设定',(320,15,650,65),exact=True)
                    and not s.find('自动特别装备设定',(320,15,650,65),exact=True),'自动装备预览')
    selected=preview_slots(panel.image,preview.image,before)
    selected_evidence=str(ui.save('abyss_special_selected_'+tag,preview))
    if any(v is None for col in selected for v in col):
        raise EventUIError('特别装备自动选择后槽位无法识别，未提交')
    changed=equipment_changed(panel.image,preview.image)
    if changed:
        ui.expect_click('装备确定',(705,447,925,515),exact=True)
        formation=ui.wait(lambda s:s.find('队伍编组',(300,0,650,70),exact=True),'特别装备提交后编队')
    else:
        ui.expect_click('取消',(35,445,265,520),exact=True)
        formation=ui.wait(lambda s:s.find('队伍编组',(300,0,650,70),exact=True),'特别装备无变化返回编队')
    after_power=formation.number((505,375,590,402))
    ui.click((615,454))
    committed=ui.wait(lambda s:s.find('特别装备设定',(320,15,650,65),exact=True),'特别装备提交复核')
    final=occupied_slots(committed.image)
    evidence=str(ui.save('abyss_special_committed_'+tag,committed))
    ui.expect_click('取消',(35,445,265,520),exact=True)
    ui.wait(lambda s:s.find('队伍编组',(300,0,650,70),exact=True),'特别装备复核后编队')
    if final!=selected:
        raise EventUIError('特别装备提交前后槽位状态不一致，停止开战')
    return dict(order=list(order),before=before,selected=selected,slots=final,
                empty=sum(v is False for col in final for v in col),
                unknown=sum(v is None for col in final for v in col),
                before_power=before_power,after_power=after_power,changed=changed,
                evidence=evidence,before_evidence=before_evidence,
                settings_evidence=settings_evidence,selected_evidence=selected_evidence)
