"""Dungeon observations in the 960x540 design coordinate space."""
from dataclasses import dataclass
import re
import cv2 as cv
import numpy as np
from .screen import EventScreen, EventUI, EventUIError, normalized


def equipped_special_slots(screen: EventScreen) -> int:
    """Count colored equipment in the observed five-column EX preview.

    Gray empty placeholders are not proof of equipped items. This deliberately
    rejects ambiguous low-rarity gray icons instead of declaring them filled.
    """
    return sum(float(np.mean(cv.cvtColor(screen.image[y-27:y+27, x-27:x+27],
               cv.COLOR_BGR2HSV)[:, :, 1] > 60)) > .15
               for x in (164, 343, 521, 699, 877) for y in (219, 291, 363))


def auto_equip_party(ui: EventUI, label: str = 'party') -> dict:
    """Opt-in assignment of existing EX items to an already verified party."""
    ui.wait(lambda s:s.find('队伍编组',(300,0,650,70)), '已核验编队')
    ui.click((613,451))
    page = lambda s:(s.find('特别装备设定',(250,0,710,80),exact=True)
                     and not s.find('正在进行数据连接'))
    before = ui.wait(page, '特别装备设定')
    prefix='special_equipment_'+label
    report = dict(before_slots=equipped_special_slots(before), before_evidence=str(ui.save(prefix+'_before',before)))
    ui.expect_click('自动装备',(475,440,710,515),exact=True)
    settings=ui.wait(lambda s:s.find('自动特别装备设定',(250,0,710,80),exact=True), '自动特别装备条件')
    if len(settings.all('^稀有度$',(470,155,700,355))) != 4:
        raise EventUIError('自动EX装备优先条件不是已验证的四项稀有度，保留设置不改动')
    def checked(s):
        hsv=cv.cvtColor(s.image[382:420,306:345],cv.COLOR_BGR2HSV)
        return float(np.mean((hsv[:,:,0]>85)&(hsv[:,:,0]<125)&(hsv[:,:,1]>70))) > .12
    if not checked(settings):
        ui.click((325,400))
        settings=ui.capture()
        if not checked(settings):
            raise EventUIError('未确认允许分配其他角色装备')
    report['settings_evidence']=str(ui.save(prefix+'_settings',settings))
    ui.expect_click('确认',(480,440,710,515),exact=True)
    preview=ui.wait(page,'特别装备分配预览')
    report.update(after_slots=equipped_special_slots(preview), preview_evidence=str(ui.save(prefix+'_preview',preview)),
                  policy='rarity; existing items including other characters')
    if report['after_slots'] != 15:
        raise EventUIError('未确认十五个特别装备槽全部有装备，未应用预览')
    button=preview.find('装备确定',(700,440,930,515),exact=True)
    if preview.blue_button(button):
        ui.click(button)
        report['applied']=True
    else:
        ui.expect_click('取消',(30,440,260,515),exact=True)
        report['applied']=False
    ui.wait(lambda s:s.find('队伍编组',(300,0,650,70)),'返回配装后的编队')
    return report


@dataclass(frozen=True)
class DungeonProgress:
    floor: int
    floors: int
    hp: int
    max_hp: int
    available: int


def floor_number(screen: EventScreen) -> tuple[int, int] | None:
    text = normalized(screen.text((370, 390, 950, 455)))
    match = re.search(r'(\d+)/(\d+)阶', text)
    if match and 1 <= int(match[1]) <= int(match[2]) <= 20:
        return int(match[1]), int(match[2])
    return None


def progress(screen: EventScreen) -> DungeonProgress | None:
    floor = floor_number(screen)
    hp = re.search(r'(\d+)/(\d+)', normalized(screen.text((270, 320, 700, 354))))
    available = re.search(r'(\d+)/(\d+)', normalized(screen.text((810, 368, 935, 404))))
    if not floor or not hp or not available:
        return None
    current, maximum = int(hp[1]), int(hp[2])
    if not 0 <= current <= maximum or maximum == 0:
        return None
    return DungeonProgress(*floor, current, maximum, int(available[1]))


def completed_card(screen: EventScreen, area: str) -> bool | None:
    """Only a mark belonging to this card is a first-clear receipt."""
    name = screen.find(re.escape(normalized(area)), (20, 305, 940, 345), exact=True)
    if name is None or not screen.find('地下城', (45, 0, 210, 65)):
        return None
    x = int(name.center[0])
    return bool(screen.find('已完成[!！]?', (x-110, 60, x+110, 100), exact=True))


def dungeon_map(screen: EventScreen, area: str) -> bool:
    return bool(screen.find(re.escape(normalized(area)), (45, 0, 280, 70), exact=True)
                and floor_number(screen) and screen.find('撤退', (750, 400, 865, 455), exact=True)
                and not screen.find('挑战', (750, 430, 940, 490), exact=True))
