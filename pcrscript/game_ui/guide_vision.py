"""Avatar and labeled-field observations from guide frames, never game actions."""
from __future__ import annotations

from dataclasses import dataclass
import re

import cv2 as cv
import numpy as np

from .avatars import AvatarIndex, face_crop, feature, card_rectangles


@dataclass
class GuideText:
    text: str
    score: float
    rectangle: tuple[int, int, int, int]

    @property
    def center(self):
        x, y, w, h = self.rectangle
        return x+w/2, y+h/2


def read_text(image, ocr) -> list[GuideText]:
    result = ocr(image, use_det=True, use_cls=True, use_rec=True)
    if result.txts is None or result.boxes is None:
        return []
    texts = []
    for value, score, box in zip(result.txts, result.scores, result.boxes):
        x, y = np.asarray(box).min(axis=0)
        x2, y2 = np.asarray(box).max(axis=0)
        texts.append(GuideText(re.sub(r'\s+', '', value).replace('（', '(').replace('）', ')'),
                               float(score), (int(x), int(y), int(x2-x), int(y2-y))))
    return texts


def battle_rectangles(image, *, relaxed=False) -> list[tuple[int, int, int, int]]:
    """Find a regular five-card cyan combat row; no character-specific coordinates."""
    height, width = image.shape[:2]
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    mask = (((hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 105)
             & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 150))*255).astype(np.uint8)
    mask[:round(height*.65)] = 0
    contours, _ = cv.findContours(mask, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    boxes = [cv.boundingRect(c) for c in contours]
    boxes = [r for r in boxes if .075*width <= r[2] <= .12*width
             and (.86 if relaxed else .9) <= r[2]/r[3] <= 1.12
             and r[1]+r[3] < height*(.96 if relaxed else .94)]
    # Nested outlines should contribute only one anchor each.
    anchors = []
    for r in sorted(boxes, key=lambda r: -r[2]*r[3]):
        if not any(abs(r[0]+r[2]/2-a[0]-a[2]/2) < width*.03 for a in anchors):
            anchors.append(r)
    if not 3 <= len(anchors) <= 6:
        return []
    size = float(np.median([r[2] for r in anchors]))
    tolerance = .15 if relaxed else .08
    anchors = [r for r in anchors if abs(r[2]-size) < size*tolerance and abs(r[3]-size) < size*tolerance]
    if len(anchors) < 3:
        return []
    anchors.sort(key=lambda r: r[0])
    centers = np.array([r[0]+r[2]/2 for r in anchors])
    differences = np.diff(centers)
    step = float(np.min(differences))
    if not 1.1*size < step < 1.5*size:
        return []
    positions = np.rint((centers-centers[0])/step).astype(int)
    if np.max(np.abs(centers-(centers[0]+positions*step))) > size*.06 or positions[-1] != 4:
        return []
    top = float(np.median([r[1] for r in anchors]))
    if max(abs(r[1]-top) for r in anchors) > size*tolerance:
        return []
    result = [(round(centers[0]+i*step-size/2), round(top), round(size), round(size)) for i in range(5)]
    for x, y, w, h in result:
        if x < 0 or y < 0 or x+w > width or y+h > height:
            return []
        # Require actual border pixels for inferred positions, not just a grid guess.
        border = np.concatenate([mask[y:y+h, x:x+max(2, w//14)].ravel(),
                                 mask[y+h-max(2, h//14):y+h, x:x+w].ravel()])
        if np.mean(border > 0) < .22:
            return []
    return result


def match_portrait(image, rectangle, index: AvatarIndex, *, align=True,
                   minimum=.92, margin=.06) -> dict | None:
    x, y, w, h = rectangle
    initial = face_crop(image, rectangle)
    if not initial.size or float(cv.cvtColor(initial, cv.COLOR_BGR2GRAY).std()) < 16:
        return None
    if not index.names:
        return None
    delta = max(1, round(w*.02))
    boxes = [(x+dx, y+dy, w+ds, h+ds) for dx in (-delta, 0, delta)
             for dy in (-delta, 0, delta) for ds in (-2*delta, 0, 2*delta)] if align else [rectangle]
    boxes = [r for r in boxes if r[0] >= 0 and r[1] >= 0 and r[0]+r[2] <= image.shape[1]
             and r[1]+r[3] <= image.shape[0]]
    scores = np.stack([feature(face_crop(image, r)) for r in boxes]) @ index.matrix.T
    # Use one aligned crop for both winner and runner-up; geometry cannot differ by identity.
    chosen = int(np.max(scores, axis=1).argmax())
    row = scores[chosen]
    ranked = {}
    for i in np.argsort(row)[::-1]:
        ranked.setdefault(str(index.names[i]), float(row[i]))
        if len(ranked) == 2:
            break
    if len(ranked) < 2:
        return None
    best, second = list(ranked.items())
    if best[0].startswith('unit:') or best[1] < minimum or best[1]-second[1] < margin:
        return None
    return dict(name=best[0], score=best[1], margin=best[1]-second[1], rectangle=list(boxes[chosen]))


def combat_team(image, index: AvatarIndex, *, relaxed=False) -> list[dict]:
    boxes = battle_rectangles(image, relaxed=relaxed)
    if len(boxes) != 5:
        return []
    matched = [match_portrait(image, r, index) for r in boxes]
    if any(m is None for m in matched) or len({m['name'] for m in matched}) != 5:
        return []
    for match, rectangle in zip(matched, boxes):
        match['card_rectangle'] = rectangle
    return matched


def formation_team(image, texts: list[GuideText], index: AvatarIndex) -> list[dict]:
    """Read the five selected cards only on a confirmed formation page."""
    if not (any(t.score >= .95 and t.text == '队伍编组' for t in texts)
            and any(t.score >= .95 and t.text == '当前的成员' for t in texts)):
        return []
    boxes = [(96+109*i-48, 405, 96, 96) for i in range(5)]
    matched = [match_portrait(image, box, index, align=False,
                              minimum=.80, margin=.04) for box in boxes]
    if any(m is None for m in matched) or len({m['name'] for m in matched}) != 5:
        return []
    return matched


def wide_special_equipment_team(image, texts: list[GuideText], index: AvatarIndex) -> list[dict]:
    """Read five portraits in a confirmed wide-video special-equipment dialog."""
    if not (any(t.score >= .95 and t.text == '特别装备设定' for t in texts)
            and any(t.score >= .95 and '可变更队伍角色的特别装备' in t.text for t in texts)):
        return []
    boxes = [(round(88+178.5*i), 108, 72, 72) for i in range(5)]
    matched = [match_portrait(image, box, index, align=False, margin=.04) for box in boxes]
    if any(m is None for m in matched) or len({m['name'] for m in matched}) != 5:
        return []
    return matched


def labeled_fields(text: str) -> dict:
    """Parse explicit labels only. An empty cell never means equipment absent."""
    text = re.sub(r'\s+', '', text).replace('：', ':').replace('★', '星')
    result = {}
    # A UE2 star level describes the weapon, not the character's rarity.
    rarity_text = re.sub(r'专武?[2二][:=]?\d+星', '', text)
    patterns = {
        'stars': r'(?<!\d)([1-6])星',
        'level': r'(?<!属性)(?:等级|[Ll][Vv]\.?)[:=]?(\d{1,3})(?!\d)',
        'rank': r'(?:[Rr][Aa][Nn][Kk]|(?<![A-Za-z])[Rr])[:=]?(\d{1,2})(?!\d)',
        'skill_level': r'技能(?:等级)?[:=]?(\d{1,3})(?!\d)',
    }
    for key, pattern in patterns.items():
        values = {int(v) for v in re.findall(pattern, rarity_text if key == 'stars' else text)}
        if len(values) == 1:
            result[key] = values.pop()
    for key, label in (('unique2', r'(?:专武?2|专武?二)'), ('unique', r'(?:专武?1|专武?一)')):
        match = re.search(label+r'(?:[:=](\d+)|(未开启|未装备|未实装|未开放|无|关闭|有|开启|已装备|装备))', text)
        if match:
            value = match[1] or match[2]
            result[key] = value not in ('未开启', '未装备', '未实装', '未开放', '无', '关闭', '0')
    # Common guide notation "专310" explicitly proves UE1, says nothing about UE2.
    match = re.search(r'(?<!无)(?:专武[:=]|专[:=]?)(\d{2,3})(?!\d)', text)
    if match:
        result['unique'] = int(match[1]) > 0
    if re.search(r'(?:无专武|未装备专武)(?:[。;,，；]|$)', text):
        result['unique'] = False
    if re.search(r'(?:SET|立即发动)[:=]?(?:开启|开|ON|O)(?![A-Za-z])', text, re.I):
        result['instant'] = True
    elif re.search(r'(?:SET|立即发动)[:=]?(?:关闭|关|OFF|X)(?![A-Za-z])', text, re.I):
        result['instant'] = False
    return result


def requirement_cells(image, texts: list[GuideText], index: AvatarIndex) -> list[dict]:
    """Associate repeated star-label cells with the avatar directly above them."""
    labels = [t for t in texts if t.score >= .95 and re.fullmatch('[1-6]星', t.text)]
    rows: list[list[GuideText]] = []
    for t in sorted(labels, key=lambda t: t.center[1]):
        row = next((r for r in rows if abs(r[0].center[1]-t.center[1]) < t.rectangle[3]*.6), None)
        if row is None:
            rows.append([t])
        else:
            row.append(t)
    result = []
    for row in rows:
        if len(row) < 2:
            continue
        row.sort(key=lambda t: t.center[0])
        spacing = float(np.median(np.diff([t.center[0] for t in row])))
        if not 35 <= spacing <= image.shape[1]*.25:
            continue
        for t in row:
            size = round(spacing)
            box = (round(t.center[0]-size/2), round(t.rectangle[1]-size), size, size)
            if box[1] < 0:
                continue
            identity = match_portrait(image, box, index)
            if identity is None:
                continue
            texts_below = [v for v in texts if v.score >= .95 and abs(v.center[0]-t.center[0]) < size*.43
                           and t.rectangle[1] <= v.center[1] < t.center[1]+size*.65]
            for v in texts_below:
                for key, value in labeled_fields(v.text).items():
                    result.append(dict(name=identity['name'], field=key, value=value, text=v.text,
                                       rectangle=list(v.rectangle), avatar=identity,
                                       confidence=min(v.score, identity['score'])))
    return result


def combat_set(image, member: dict, texts: list[GuideText]) -> bool | None:
    x, y, w, h = member['rectangle']
    combined = list(texts)
    for top in texts:
        if top.text != '立即' or top.score < .95:
            continue
        bottom = next((t for t in texts if t.text == '发动' and t.score >= .95
                       and abs(t.center[0]-top.center[0]) < top.rectangle[2]*.25
                       and 0 < t.center[1]-top.center[1] < top.rectangle[3]*1.8), None)
        if bottom:
            tx, ty, tw, th = top.rectangle
            combined.append(GuideText('立即发动', min(top.score, bottom.score),
                                      (tx, ty, tw, bottom.rectangle[1]+bottom.rectangle[3]-ty)))
    labels = [t for t in combined if t.score >= .9 and t.text.upper() in ('SET', '立即发动')
              and x+w*.65 < t.center[0] < x+w*1.35 and y-h*.3 < t.center[1] < y+h*.35]
    if not labels:
        return None
    t = labels[0]
    tx, ty, tw, th = t.rectangle
    patch = image[max(0, ty-3):ty+th+3, max(0, tx-3):tx+tw+3]
    hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
    blue = (hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 115) & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 140)
    return True if np.mean(blue) > .25 else None


def formation_fields(image, texts, index, badges) -> list[dict]:
    """The sword/orb recognizer is valid only on a confirmed formation page."""
    if not any(t.score >= .95 and t.text == '队伍编组' for t in texts):
        return []
    normalized = cv.resize(image, (960, 540))
    result = []
    for rectangle in card_rectangles(normalized):
        identity = match_portrait(normalized, rectangle, index)
        if identity is None:
            continue
        # Badge coordinates use the detected outer card, not the face alignment.
        value = badges.read(normalized, rectangle)
        if value is not None:
            for key, flag in zip(('unique', 'unique2'), value):
                result.append(dict(name=identity['name'], field=key, value=flag,
                                   rectangle=[round(v*image.shape[1]/960) for v in rectangle],
                                   confidence=identity['score'], text='剑徽/信息帧'))
    return result


def combat_auto(image, texts: list[GuideText]) -> bool | None:
    """Read the labeled combat AUTO button, independently from member SET."""
    height, width = image.shape[:2]
    labels = [t for t in texts if t.score >= .95 and t.text.upper() in ('自动', 'AUTO')
              and t.center[0] > width*.9 and height*.70 < t.center[1] < height*.85]
    if len(labels) != 1:
        return None
    x, y, w, h = labels[0].rectangle
    patch = image[max(0,y-4):min(height,y+h+4),max(0,x-4):min(width,x+w+4)]
    hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
    blue = (hsv[:,:,0] >= 75) & (hsv[:,:,0] <= 115) & (hsv[:,:,1] > 100) & (hsv[:,:,2] > 140)
    if np.mean(blue) > .3:
        return True
    if np.mean((hsv[:,:,1] < 45) & (hsv[:,:,2] > 180)) > .5:
        return False
    return None
