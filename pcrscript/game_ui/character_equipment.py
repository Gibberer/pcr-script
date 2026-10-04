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
    # The same confirmed input path is used by combat formation searches.
    # Page-specific geometry is the only difference.
    from .character_search import search_character
    s = search_character(ui, name, page='角色一览', page_area=(40, 0, 250, 65),
        field_area=(330, 65, 640, 110), reset=(689, 90), field=(480, 90), defocus=(480, 115))
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
        # Six-star characters can open on the pure-memory tab. Both labels
        # retain the full costume identity; absence of the ordinary label is
        # not evidence that this is another character.
        shard=s.find(re.escape(normalized(name))+r'的(?:纯净)?记忆碎片', (470, 105, 925, 160), exact=True)
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
    s = ui.wait(lambda frame: frame.find('此专用装备1预定今后登场[。.]?', (470, 300, 925, 370), exact=True)
                or frame.find('专用装备1|专用装备2', (470, 110, 925, 440), exact=True), '专用装备页面')
    if s.find('此专用装备1预定今后登场[。.]?', (470, 300, 925, 370), exact=True):
        return str(ui.save('equipment_unreleased_'+name, s))
    return None


def unique_equipment_fields(screen):
    """Read an explicitly identified slot, never the character's own level."""
    result = {}
    text = normalized(screen.text((470, 105, 925, 445)))
    for slot, flag, stat in ((1, 'unique', 'unique_level'), (2, 'unique2', 'unique2_stars')):
        if re.search(rf'此专用装备{slot}预定今后登场[。.]?', text):
            result.update({flag: False, flag+'_available': False})
            continue
        # The fixed phrase names the currently displayed slot independently of
        # the other slot's icon. A tab label alone does not prove installation.
        if re.search(rf'此专用装备{slot}已强化至', text):
            result.update({flag: True, flag+'_available': True})
            if slot == 1:
                levels = {int(n) for n in re.findall(r'等级(\d+)',
                    normalized(screen.text((640, 195, 755, 250))))}
                if len(levels) == 1:
                    result[stat] = levels.pop()
        explicit = re.search(rf'专用装备{slot}(未装备|已装备)', text)
        if explicit:
            result.update({flag: explicit[1] == '已装备', flag+'_available': True})
        if slot == 2 and result.get(flag) is True:
            stage = re.search(r'(?:强化阶段|强化星级)[:：]?(\d)', text)
            if stage and 0 <= int(stage[1]) <= 5:
                result[stat] = int(stage[1])
            elif '此专用装备2已强化至最强' in text:
                hsv = cv.cvtColor(screen.image, cv.COLOR_BGR2HSV)
                # CN max-stage detail: five gold stars below the central item.
                # Require both the slot-specific phrase and the visible stars.
                stars = [np.mean((hsv[228:238,x-4:x+4,0] >= 12)
                    & (hsv[228:238,x-4:x+4,0] <= 40)
                    & (hsv[228:238,x-4:x+4,1] > 90)
                    & (hsv[228:238,x-4:x+4,2] > 140)) > .3 for x in (662,673,684,695,706)]
                if all(stars):
                    result[stat] = 5
    return result


def second_unique_selector(screen):
    """Recognize the observed two-icon layout, not the next-character arrow."""
    if not screen.find('角色强化', (40, 0, 250, 65)):
        return None
    labelled = screen.find('专用装备2', (100, 90, 460, 385), exact=True)
    if labelled:
        return labelled
    if not screen.find(r'等级\d+', (135, 128, 215, 157)):
        return None
    gray = cv.cvtColor(screen.image[65:170,100:410], cv.COLOR_BGR2GRAY)
    contours, _ = cv.findContours(cv.Canny(gray,80,160), cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv.boundingRect(contour)
        center = (100+x+w/2, 65+y+h/2)
        if 70 <= w <= 82 and 70 <= h <= 82 and 312 <= center[0] <= 335 and 102 <= center[1] <= 125:
            return center
    return None


def inspect_unique_equipment(ui: EventUI, name: str):
    """Read known slot layouts without installing, enhancing or buying items."""
    if open_character_memory(ui, name) is None:
        return None
    ui.expect_click('专用装备', (775, 55, 860, 95), exact=True)
    screen = ui.wait(lambda s: s.find('角色强化', (40, 0, 250, 65))
                     and (unique_equipment_fields(s) or s.find('装备属性值|专用装备1|专用装备2',
                         (470, 105, 925, 445), exact=True)), '专用装备详情')
    values = unique_equipment_fields(screen)
    proofs = [str(ui.save('unique_details_'+name, screen))]
    selector = second_unique_selector(screen)
    if selector:
        ui.click(selector)
        screen = ui.wait(lambda s: 'unique2' in unique_equipment_fields(s), '专用装备2独立详情')
        second = unique_equipment_fields(screen)
        for key, value in second.items():
            if key in values and values[key] != value:
                values[key] = None
            else:
                values[key] = value
        proofs.append(str(ui.save('unique2_details_'+name, screen)))
    return dict(name=normalized(name), observed_at=time.time(), values=values, evidence=proofs)
