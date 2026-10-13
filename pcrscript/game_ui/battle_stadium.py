"""Observed CN battle stadium pages (LeiDian 960 x 540)."""
from dataclasses import dataclass
import re

import cv2 as cv
import numpy as np

from .screen import normalized

MAP_TITLE = (45, 0, 240, 60)
REWARD_TRACK = (911, 75, 924, 400)


class SourceOutcome:
    """Link result titles to a recently verified combat; never supply a roster."""
    def __init__(self):
        self.key = None
        self.at = float('-inf')

    def bind(self, key, seconds):
        self.key, self.at = key, seconds

    def clear(self):
        self.key = None

    def observe(self, texts, seconds, proof):
        labels = {normalized(t.text) for t in texts if t.score >= .95}
        if ({'编组详情', '挑战目标'} <= labels
                or {'队伍编组', '当前的成员'} <= labels
                or {'队伍编组', '对战对手的队伍'} <= labels):
            self.clear()
        if not self.key or not 0 <= seconds-self.at <= 8:
            return None
        results = []
        for t in texts:
            x,y,w,h = t.rectangle
            if not (t.score >= .95 and 150 <= w <= 650 and h >= 45
                    and 400 <= x+w/2 <= 900 and 50 <= y+h/2 <= 330):
                continue
            label = normalized(t.text).upper()
            outcome = ('win' if re.fullmatch(r'WIN[!！]?',label) else
                       'lose' if re.fullmatch(r'LOSE[!！]?',label) else None)
            if outcome:
                results.append((outcome,t))
        if len(results) != 1:
            return None
        outcome,item = results[0]
        return self.key, dict(outcome=outcome,evidence=dict(proof,
            method='stadium_result_'+outcome,text=item.text,
            rectangle=list(item.rectangle),confidence=item.score))


def source_combat_hud(image, texts):
    """Recognize the two total-HP bars and timer during a dim battle start.

    This retains adjacent formation context only, never supplies identities.
    OCR rectangles refer to the original saved 1280x720 guide frame.
    """
    if not any(t.score >= .95 and re.fullmatch(r'[01]:[0-5]\d', normalized(t.text))
               and 560 <= t.center[0] <= 720 and t.center[1] < 120 for t in texts):
        return False
    hsv = cv.cvtColor(image[:65], cv.COLOR_BGR2HSV)
    mask = (((hsv[:,:,0] >= 20) & (hsv[:,:,0] <= 40)
              & (hsv[:,:,1] > 80) & (hsv[:,:,2] > 25))*255).astype(np.uint8)
    contours,_ = cv.findContours(mask,cv.RETR_EXTERNAL,cv.CHAIN_APPROX_SIMPLE)
    bars = [(x,y,w,h) for x,y,w,h in map(cv.boundingRect,contours)
            if 160 <= w <= 300 and 2 <= h <= 14]
    return any(100 <= a[0]+a[2]/2 <= 380 and 540 <= b[0]+b[2]/2 <= 830
               and abs(a[1]-b[1]) <= 6 for a in bars for b in bars)


def combat_rectangles(image, count):
    """Nominate stadium cards with their visible life bars, including short teams.

    Stadium has gold portrait borders rather than the cyan PvE borders.
    Callers must match every nominated identity to the preceding formation.
    """
    if not 1 <= count <= 5 or image.shape[:2] != (540, 960):
        return []
    area = image[380:510, 165:800]
    contours, _ = cv.findContours(cv.Canny(area, 30, 60), cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    boxes = [(x+165, y+380, w, h) for x, y, w, h in map(cv.boundingRect, contours)
             if 86 <= w <= 103 and 86 <= h <= 104 and abs(w-h) <= 4]
    # Codec gaps sometimes leave only the inset face outline. Expand that
    # geometric proposal to the card border; identity still uses the original
    # pixels and the caller's full confidence/margin requirements.
    boxes = [(x-4, y-4, w+8, h+8) if w <= 90 and h <= 90 else (x, y, w, h)
             for x, y, w, h in boxes]
    candidates = []
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    for box in sorted(boxes, key=lambda r: -r[2]*r[3]):
        x, y, w, h = box
        if any(abs(x-r[0]) < 12 for r in candidates):
            continue
        candidates.append(box)
    # A badge can join the outer card contour. A full-width life bar nominates
    # its missing square portrait, never an identity or a missing teammate.
    green_mask = (((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85)
                   & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 100))*255).astype(np.uint8)
    # A damaged life bar retains its full-width outline. A badge can join
    # the portrait contour while the green fill is too short to nominate it.
    # The outline supplies only geometry; live green fill and every identity
    # are still checked below and by the caller.
    outlines, _ = cv.findContours(cv.Canny(image[493:519, 165:800], 30, 60),
                                  cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    for bx, by, bw, bh in map(cv.boundingRect, outlines):
        # The second (TP) bar may enter the bottom of this region. Only the
        # upper life outline nominates a portrait. Prefer its fixed width to
        # a partially depleted green fill.
        if not (88 <= bw <= 99 and 5 <= bh <= 12 and by <= 10):
            continue
        x, y, w = bx+165-2, by+493-bw-9, bw+4
        if not any(abs(x+w/2-r[0]-r[2]/2) < 12 for r in candidates):
            candidates.append((x, y, w, w))
    bars, _ = cv.findContours(green_mask[493:514, 165:800], cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    for bx, by, bw, bh in map(cv.boundingRect, bars):
        if not (86 <= bw <= 99 and 3 <= bh <= 14):
            continue
        x, y, w = bx+165-2, by+493-bw-9, bw+4
        if not any(abs(x+w/2-r[0]-r[2]/2) < 12 for r in candidates):
            candidates.append((x, y, w, w))
    candidates.sort()
    if len(candidates) != count or max(r[1] for r in candidates)-min(r[1] for r in candidates) > 8:
        return []
    if count >= 3:
        # Cards share one row. Codec gaps and joined badges can trim one
        # contour's top; the majority provides a bounded common baseline.
        # Recheck the actual life bars after this geometric adjustment.
        top = round(float(np.median([r[1] for r in candidates])))
        candidates = [(x, top, w, h) for x, _, w, h in candidates]
    for x, y, w, h in candidates:
        bar = hsv[y+h+2:min(525, y+h+19), x:x+w]
        green = (bar[:, :, 0] >= 35) & (bar[:, :, 0] <= 85) & (bar[:, :, 1] > 90) & (bar[:, :, 2] > 100)
        if not bar.size or float(np.mean(green)) < .15:
            return []
    if count == 1:
        return candidates if candidates[0][0] > 600 else []
    gaps = np.diff([r[0]+r[2]/2 for r in candidates])
    return candidates if np.all((gaps >= 110) & (gaps <= 130)) else []


class SourceScope:
    """Bind a unique round detail only to its adjacent formation frames."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.scope, self.proof, self.at = {}, None, float('-inf')
        self.names, self.formation_at, self.on_formation = [], float('-inf'), False
        self.loading_at = float('-inf')
        self.equipment_at = float('-inf')
        self.returned_from_equipment = False

    def observe_formation(self, members, seconds):
        if self.on_formation:
            self.names = [normalized(m['name']) for m in members]
            self.formation_at = seconds

    def resolve(self, scope, verified, texts, seconds, proof, *, combat_names=(), combat_scene=False,
                loading_scene=False):
        labels = {normalized(t.text) for t in texts if t.score >= .95}
        detail_page = ({'编组详情', '挑战目标', '战斗效果'} <= labels
                       or {'编组详情', '取消', '挑战', '战斗效果'} <= labels)
        # Scrolling the roster can blur the opponent label; the bottom
        # controls then still identify the same unstarted formation.
        formation_page = ({'队伍编组', '当前的成员', '战斗效果'} <= labels
                          and ('对战对手的队伍' in labels or {'取消', '战斗开始'} <= labels))
        saved_parties = {'我的队伍一览', '呼出此编组'} <= labels
        equipment_page = ({'选择装备', '特别装备替换详情', '取消', '装备确定'} <= labels
                          or {'选择装备', '取消', '全部卸下', '稀有度', '降序'} <= labels
                          or {'选择装备', '特别装备替换确认', '替换特别装备。', '关闭', '装备确定'} <= labels
                          or {'特别装备设定', '可变更队伍角色的特别装备。', '取消', '自动装备'} <= labels)
        self.on_formation = formation_page
        if any(re.search('WIN|LOSE|伤害报告|战斗结果', word, re.I) for word in labels):
            self.reset()
            return {}, False, None
        start_overlay = any(t.score >= .95 and re.fullmatch(r'开始[!！]?', normalized(t.text))
                            and t.rectangle[2] > 400 and t.rectangle[3] > 150
                            and 500 < t.center[0] < 800 and 200 < t.center[1] < 500 for t in texts)
        if (start_overlay and self.scope and self.names
                and 0 <= seconds-self.formation_at <= 8 and seconds-self.at <= 20):
            if scope and verified and scope != self.scope:
                self.reset()
                return {'conflict': True}, False, None
            # The large battle-start animation dims portraits and life bars.
            # Retain the original short deadline, supplying no scope or party
            # proof until a clear combat frame verifies every member.
            return {}, False, None
        if combat_scene:
            names = list(map(normalized, combat_names))
            if scope and verified:
                return scope, verified, None
            if (not names and self.scope and self.names
                    and 0 <= seconds-self.formation_at <= 8 and seconds-self.at <= 20):
                # A recognized combat row with an unreadable face supplies no
                # proof. Keep the short original deadline for a later frame;
                # never authorize a partial or mismatched identity list.
                return {}, False, None
            if (self.scope and names and names == self.names
                    and 0 <= seconds-self.formation_at <= 8 and seconds-self.at <= 20):
                return dict(self.scope), True, dict(self.proof, method='stadium_formation_to_combat')
            self.reset()
            return {}, False, None
        loading_hint = any(t.score >= .85 and re.fullmatch(r'加载(?:中)?[.。…]*', normalized(t.text))
                           and t.rectangle[0] > 850 and t.rectangle[1] > 550 for t in texts)
        if ((loading_hint or any(word.startswith('加载中') or word == '正在进行数据连接' for word in labels))
                and self.scope and seconds-self.at <= 20):
            if scope and verified and scope != self.scope:
                self.reset()
                return {}, False, None
            self.on_formation = False
            self.loading_at = seconds
            return {}, False, None
        if ((loading_scene or not labels) and self.scope and self.names
                and 0 <= seconds-self.loading_at <= 1 and seconds-self.at <= 20):
            # A short black or dimmed, textless fade immediately after an
            # explicit loading frame supplies no scope proof and cannot renew
            # any authorization.
            return {}, False, None
        if (saved_parties and self.scope and not (scope and verified and scope != self.scope)
                and seconds-self.at <= 40):
            # Loading a saved roster keeps the round context only. The
            # following formation frames must still supply the final team.
            self.names = []
            return {}, False, None
        if equipment_page and self.scope and scope and verified and scope != self.scope:
            self.reset()
            return {'conflict': True}, False, None
        if (equipment_page and self.scope
                and 0 <= seconds-self.formation_at <= 20 and seconds-self.at <= 40):
            # This only scopes preparation conditions. It does not renew
            # the shorter formation-to-battle authorization deadline. Known
            # page/round navigation can scope a blocking equipment condition
            # even if the roster cannot supply any executable party proof.
            self.equipment_at = seconds
            return dict(self.scope), True, dict(self.proof, method='stadium_formation_equipment_condition')
        if (not detail_page and self.scope and self.names and verified and scope == self.scope
                and {'挑战目标', '战斗效果', '取消', '挑战'} <= labels
                and any(t.score >= .85 and normalized(t.text) == '编组详情' for t in texts)
                and 0 <= seconds-self.formation_at <= 8 and seconds-self.at <= 20):
            # The same verified round detail flashes again after start. Its
            # decorative title can be blurry while all other controls remain
            # clear. Preserve only the existing roster and original deadlines;
            # this lower-confidence title cannot bind a new round.
            return dict(scope), True, None
        if detail_page:
            if (verified and scope == self.scope and self.names and self.returned_from_equipment
                    and 0 <= seconds-self.formation_at <= 2 and seconds-self.at <= 40):
                # A newly read exact detail can rebind the final roster after
                # a bounded, known equipment round trip. Gear alone cannot
                # renew combat authorization; this fresh round proof can.
                self.proof, self.at = dict(proof), seconds
                self.returned_from_equipment = False
                return dict(scope), True, None
            # Starting a fight briefly renders the same detail behind a
            # connection overlay. Keep the already verified final roster;
            # another round still resets it, and no deadline is renewed.
            if (verified and scope == self.scope and self.names
                    and 0 <= seconds-self.formation_at <= 8 and seconds-self.at <= 20):
                return dict(scope), True, None
            # A dim loading overlay can reduce the already-bound header's
            # confidence. It cannot supply a new round or extend its deadline.
            hints = {int(m[1]) for t in texts if t.score >= .85
                     and (m := re.fullmatch(r'.?合([1-9]\d?)', normalized(t.text)))}
            if (not verified and self.scope and hints == {self.scope['round']}
                    and seconds-self.at <= 15):
                return {}, False, None
            # The post-start flash can leave the badge wholly unreadable.
            # With a bound final roster and no other round, keep it unrenewed.
            if (not verified and not scope and not hints and self.scope and self.names
                    and 0 <= seconds-self.formation_at <= 8 and seconds-self.at <= 20):
                return {}, False, None
            self.reset()
            if verified and set(scope) == {'round'}:
                self.scope, self.proof, self.at = dict(scope), dict(proof), seconds
            return scope, verified, None
        if formation_page:
            if scope and verified:
                # Explicit part/frame labels also remain binding.
                if self.scope and scope != self.scope:
                    self.reset()
                    return {'conflict': True}, False, None
                if not self.scope and set(scope) == {'round'}:
                    self.scope, self.proof, self.at = dict(scope), dict(proof), seconds
                return scope, verified, None
            if (self.scope and 0 <= seconds-self.equipment_at <= 2
                    and seconds-self.at <= 40 and seconds-self.formation_at <= 20):
                self.returned_from_equipment = True
                return dict(self.scope), True, dict(self.proof, method='stadium_equipment_to_formation')
            if self.scope and 0 <= seconds-self.at <= 15:
                return dict(self.scope), True, dict(self.proof, method='stadium_detail_to_formation')
        self.reset()
        return scope, verified, None


def home(s):
    return bool(s.find('斗技场', MAP_TITLE, exact=True)
                and s.find('进度', (420, 0, 520, 65), exact=True)
                and s.find('报酬', (850, 385, 950, 465), exact=True))


def detail(s):
    return bool(s.find('编组详情', (25, 20, 160, 80), exact=True)
                and s.find('挑战目标', (40, 290, 225, 345), exact=True)
                and s.find('战斗效果', (580, 310, 820, 365), exact=True))


def round_number(s, ui=None):
    roi = (140, 20, 300, 80)
    item = s.find(r'回合[1-9]\d?', roi, exact=True)
    if (not item or item.score < .95) and ui is not None and detail(s):
        item = ui.read_region(s, roi, classify=False).find(r'回合[1-9]\d?', exact=True)
    return int(normalized(item.text)[2:]) if item and item.score >= .95 else None


def challenge_goals(s):
    """Require all three visible supported win conditions before a trial."""
    text = normalized(s.text((40, 330, 555, 414))).replace('：', ':')
    patterns = (r'剩余时间(?:为)?[0-2]:[0-5]\d以上(?:的情况下)?获胜',
                r'(?:我方)?总生命值(?:为|在)?(?:100|[1-9]?\d)%以上(?:的情况下|可)?获胜',
                r'无法战斗的角色(?:为)?(?:0人|[0-5]人以下)(?:的情况下)?获胜')
    goals = [m[0] for pattern in patterns for m in re.finditer(pattern, text)]
    return goals if len(goals) == 3 and text.count('获胜') == 3 else None


def formation(s):
    return bool(s.find('队伍编组', (300, 15, 660, 75), exact=True)
                and s.find('对战对手的队伍', (390, 60, 585, 115), exact=True)
                and s.find('战斗效果', (35, 60, 240, 115), exact=True))


def rewards(s):
    return bool(s.find('[★星]获得任务', (300, 15, 665, 70), exact=True)
                and s.find('全部收取', (475, 435, 710, 510), exact=True))


def receipt(s):
    return bool(s.find('收取报酬', (250, 0, 710, 85), exact=True)
                and s.find('收取了以下道具|获得了以下报酬', (150, 70, 810, 210)))


def navigation_exit(s):
    if receipt(s) or s.find('购买确认|回复确认|重置确认'):
        return None
    if detail(s) or formation(s):
        return s.find('取消', (570, 410, 795, 510), exact=True)
    if rewards(s) and s.find('斗技场', (40, 65, 180, 410)):
        return s.find('取消', (250, 425, 470, 510), exact=True)
    return None


def progress(ui, s):
    if not home(s):
        return None
    unlocked = ui.number(s, (548, 17, 574, 49))
    stars = ui.number(s, (662, 17, 693, 49))
    rounds = re.search(r'/(\d+)解锁', normalized(s.text((500, 5, 642, 55))))
    maximum = re.search(r'/(\d+)获得', normalized(s.text((642, 5, 770, 55))))
    # The star icon can join both numbers into one weak full-frame OCR row
    # (e.g. 47/54 -> 47154). Re-read the denominator alone; never repair digits.
    if not rounds:
        item = ui.read_region(s, (575, 16, 638, 49), classify=False).find(r'/\d+解锁', exact=True)
        rounds = re.fullmatch(r'/(\d+)解锁', normalized(item.text)) if item and item.score >= .95 else None
    if not maximum:
        item = ui.read_region(s, (691, 16, 752, 49), classify=False).find(r'/\d+获得', exact=True)
        maximum = re.fullmatch(r'/(\d+)获得', normalized(item.text)) if item and item.score >= .95 else None
    if None in (unlocked, stars) or not rounds or not maximum:
        return None
    count = int(rounds[1])
    total = int(maximum[1])
    if not 1 <= unlocked <= count <= 99 or total != count*3 or not 0 <= stars <= total:
        return None
    return dict(unlocked=unlocked, rounds=count, stars=stars, maximum_stars=total)


@dataclass(frozen=True)
class Round:
    number: int
    stars: int | None
    position: tuple[int, int]


def star_count(image, centers):
    values = []
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    for x, y in centers:
        patch = hsv[y-10:y+10, x-9:x+9]
        gold = np.mean((patch[:, :, 0] > 12) & (patch[:, :, 0] < 40)
                       & (patch[:, :, 1] > 100) & (patch[:, :, 2] > 160))
        blue = np.mean((patch[:, :, 0] > 85) & (patch[:, :, 0] < 120)
                       & (patch[:, :, 1] > 45) & (patch[:, :, 2] > 130))
        if gold > .25:
            values.append(1)
        elif blue > .25:
            values.append(0)
        else:
            return None
    return sum(values)


def rounds(s):
    if not home(s):
        return []
    result = []
    for item in s.all(r'^回合[1-9]\d?$', (80, 310, 900, 360)):
        x, y = item.center
        # Effect icons change the green label's width and text center. Stars
        # stay in the three fixed card columns; label-relative crops can read
        # the gold pedestal as an earned star on an untouched round.
        anchors = (195, 477, 759)
        anchor = min(anchors, key=lambda center: abs(center-x))
        if abs(anchor-x) > 80:
            continue
        result.append(Round(int(normalized(item.text)[2:]),
                            star_count(s.image, [(anchor+3+dx, 305) for dx in (-28, 0, 28)]), (x, y)))
    return sorted(result, key=lambda r: r.number)


def reward_rows(s):
    if not rewards(s):
        return []
    result = []
    for item in s.all(r'累计获得\d+个[★星]', (140, 65, 520, 410)):
        target = int(re.search(r'\d+', item.text)[0])
        _, y = item.center
        state = s.find('收取|已收取|领取完毕', (765, y+25, 905, min(408, y+90)), exact=True)
        completed = (s.find('已完成', (40, y+10, 160, min(408, y+70)), exact=True)
                     and s.find(f'{target}/{target}', (235, y+10, 305, min(408, y+70)), exact=True))
        if state or completed:
            received = bool(completed) or normalized(state.text) in ('已收取', '领取完毕')
            result.append(dict(target=target, received=received,
                               claimable=not received and s.blue_button(state)))
    return result
