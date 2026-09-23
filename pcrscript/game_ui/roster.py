"""Read-only formation roster sampling for candidate route planning.

Avatar matches establish a candidate inventory, not cultivation readiness.
Every selected team still requires live name/skill/equipment verification.
"""
from __future__ import annotations

import json
import time
import cv2 as cv

from .avatars import AvatarIndex, card_rectangles, face_crop, search_card_rectangles
from .screen import EventUI, EventUIError, normalized


def probe_formation_names(ui: EventUI, names: list[str]) -> dict:
    """Search shortlisted identities cheaply before full cultivation audits.

    Unknown portraits remain unknown; this does not authorize a battle.
    """
    ui.wait(lambda s: s.find('队伍编组', (300, 0, 650, 70)), '候选角色搜索')
    ui.expect_click('全部', (30, 65, 115, 108), exact=True)
    for _ in range(10):
        if ui.capture().find('重置', (640, 105, 755, 165), exact=True):
            break
        ui.swipe((480, 170), (480, 350))
    else:
        raise EventUIError('候选搜索栏未知')
    index = AvatarIndex()
    results = {}
    for name in names:
        base = normalized(name).split('(')[0]
        for _ in range(3):
            ui.click((691, 135))
            ui.click((480, 136), delay=.3)
            ui.driver.input(base)
            time.sleep(1)
            ui.click((580, 356), delay=1)
            s = ui.capture()
            if base in normalized(s.text((300, 110, 640, 165))).replace('干爱瑠', '千爱瑠'):
                break
        input_verified = base in normalized(s.text((300, 110, 640, 165))).replace('干爱瑠', '千爱瑠')
        if not s.find('队伍编组', (300, 0, 650, 70)):
            raise EventUIError('候选搜索后未处于编队页')
        rects = search_card_rectangles(s.image, top=180) if input_verified else []
        recognized = index.query([face_crop(s.image, r) for r in rects])
        wanted = normalized(name)
        results[name] = dict(candidate_matched=wanted in recognized, recognized=recognized,
                             input_verified=input_verified,
                             unknown_cards=recognized.count(None),
                             evidence=str(ui.save('candidate_'+name, s)), cultivation_verified=False)
        (ui.output/'candidate_search.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('[候选搜索]', name, recognized, flush=True)
    return results


def scan_formation_roster(ui: EventUI, max_pages: int = 65) -> dict:
    ui.wait(lambda s: s.find('队伍编组', (300, 0, 650, 70)), '角色盘点编队页')
    ui.expect_click('全部', (30, 65, 115, 108), exact=True)
    for _ in range(10):
        s = ui.capture()
        if s.find('重置', (640, 105, 755, 165), exact=True):
            ui.click((691, 135))
            break
        ui.swipe((480, 170), (480, 350))
    else:
        raise EventUIError('盘点搜索栏未知')
    index = AvatarIndex()
    result = {'observed_at': time.time(), 'scope': 'formation_candidate_inventory',
              'characters': {}, 'pages': [], 'reached_bottom': False}
    previous = None
    repeated = 0
    for page in range(max_pages):
        s = ui.capture(ocr=False)
        rects = card_rectangles(s.image)
        faces = [face_crop(s.image, rect) for rect in rects]
        names = index.query(faces)
        evidence = str(ui.save(f'roster_page_{page:02d}', s))
        result['pages'].append({'evidence': evidence, 'recognized': names, 'rectangles': rects})
        for name in names:
            if name:
                result['characters'].setdefault(name, {'evidence': evidence, 'cultivation_verified': False})
        # Ignore rotating stars/badges when detecting a stable last page.
        signature = b''.join(cv.resize(face,(12,12)).tobytes() for face in faces)
        if signature and signature == previous:
            repeated += 1
            if repeated >= 2:
                result['reached_bottom'] = True
                break
        else:
            repeated = 0
        previous = signature
        ui.swipe((850, 325), (850, 135))
    result['warning'] = '未匹配头像不代表未持有；缺失候选须用角色搜索再核实。'
    (ui.output/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
