"""Temporary recommendation exclusions, with durable preference restoration."""
import json
from pathlib import Path

import cv2 as cv
import numpy as np

from .screen import EventScreen, EventUIError
from ..run_session import atomic_json, clock as time


SLOTS = tuple((x, y) for y in (225, 307) for x in (637, 717, 797, 877)) + ((637, 390), (717, 390))
CAPACITY = len(SLOTS)
TRACK = (560, 132, 569, 433)
# About 0.55s per sample on the tested device; five cover one pulse.
PULSE_SAMPLES = 5
# Tolerate one misread glyph of the six; 「未持有」 cannot match.
BANNER ='|'.join('限制实战使用'[:i]+'.'+'限制实战使用'[i+1:] for i in range(6))


def hidden_screen(screen):
    return bool(screen.find('隐藏筛选', (360, 15, 600, 70), exact=True))


def selection(screen):
    """Read the contiguous selected-slot prefix, excluding stars and banners."""
    occupied, faces = [], []
    for x, y in SLOTS:
        patch = screen.image[y-28:y+25, x-28:x+28]
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        # White-haired/grayscale portraits still contain face texture. Empty
        # slots have a nearly uniform gray gradient; saturation alone loses
        # legitimate user preferences before restoration even begins.
        texture = float(np.mean(np.std(patch.reshape(-1,3), axis=0)))
        present = float(np.mean(hsv[:, :, 1] > 65)) > .12 or texture > 14
        occupied.append(present)
        if present:
            face = cv.resize(screen.image[y-26:y+14, x-26:x+26], (24, 24), interpolation=cv.INTER_AREA)
            faces.append(face.reshape(-1).tolist())
    if occupied != sorted(occupied, reverse=True):
        raise EventUIError('隐藏角色已选槽位不连续，停止修改筛选')
    return faces


def same_selection(first, second):
    if len(first) != len(second):
        return False
    for a, b in zip(first, second):
        a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
        # Same-size UI crops should be nearly identical; do not infer identity
        # from shared frames, names, or another costume of the same character.
        if float(np.mean(np.abs(a-b))) > 12:
            return False
    return True


def cards(screen):
    edges = cv.Canny(screen.image[125:425, 40:545], 80, 160)
    contours, _ = cv.findContours(edges, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    centers = []
    for contour in contours:
        x, y, w, h = cv.boundingRect(contour)
        if 88 <= w <= 94 and 85 <= h <= 94:
            center = (x+40+w//2, y+125+h//2)
            if not any(abs(center[0]-a) < 12 and abs(center[1]-b) < 12 for a, b in centers):
                centers.append(center)
    return sorted(centers, key=lambda p: (p[1], p[0]))


def checked(screen, x, y):
    """The selection tick's upper arm crosses the card's right border into
    the white column gap. Hair or costume colour never reaches that gap."""
    patch = cv.cvtColor(screen.image[y-46:y-28, x+47:x+54], cv.COLOR_BGR2HSV)
    return float(np.mean((patch[:, :, 2] < 200) | (patch[:, :, 1] > 60))) > .15


def restricted_cards(ui, screen, positions):
    """Read all small banners in one OCR batch, including merged adjacent text.

    Packing separated upright strips avoids repeated OCR setup and the long
    negative-recognition fallback for every card without a banner.
    """
    strip_width, strip_height, step = 88, 25, 33
    canvas = np.full((len(positions)*step, strip_width, 3), 255, np.uint8)
    for index, (x, y) in enumerate(positions):
        canvas[index*step:index*step+strip_height] = screen.image[y+22:y+47, x-44:x+44]
    observed = ui.read_region(EventScreen(canvas, []), (0, 0, strip_width, len(canvas)), classify=False)
    result = []
    for index, (x, y) in enumerate(positions):
        direct = screen.find(BANNER, (x-44,y+22,x+44,y+47), exact=True)
        packed = observed.find(BANNER, (0,index*step,strip_width,index*step+strip_height), exact=True)
        if any(item is not None and item.score >= .9 for item in (direct, packed)):
            result.append((x,y))
    return result


class HiddenFilter:
    def __init__(self, ui, path, check_deadline=lambda: None):
        self.ui, self.path, self.check_deadline = ui, Path(path), check_deadline

    def journal(self):
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except (ValueError, OSError) as error:
            raise EventUIError('隐藏筛选恢复记录无法读取，停止修改偏好') from error
        if not isinstance(state, dict):
            raise EventUIError('隐藏筛选恢复记录格式错误')
        if state and (state.get('version') != 1 or not isinstance(state.get('original'), list)
                      or type(state.get('maximum')) is not int
                      or not 0 <= len(state['original']) <= state['maximum'] <= CAPACITY
                      or any(not isinstance(row, list) or len(row) != 1728
                             or any(type(v) is not int or not 0 <= v <= 255 for v in row)
                             for row in state['original'])):
            raise EventUIError('隐藏筛选恢复记录格式错误')
        return state

    def open(self):
        self.ui.expect_click('隐藏角色', (95, 80, 265, 145), exact=True)
        return self.ui.wait(hidden_screen, '隐藏筛选')

    def close(self, apply):
        self.ui.expect_click('显示更新' if apply else '取消',
                             (485, 445, 695, 510) if apply else (265, 445, 475, 510), exact=True)
        return self.ui.wait(lambda s: s.find('推荐编组', (380, 15, 570, 70), exact=True), '隐藏筛选返回推荐')

    def scroll(self, screen, direction):
        before = self.ui.scrollbar_bounds(screen, TRACK)
        if before is None:
            raise EventUIError('隐藏筛选角色滚动条未识别')
        self.ui.swipe((245, 405 if direction > 0 else 235),
                      (245, 235 if direction > 0 else 405), duration=450)
        screen = self.ui.wait(lambda s: hidden_screen(s)
                              and (bounds := self.ui.scrollbar_bounds(s, TRACK)) is not None
                              and direction*(bounds[0]-before[0]) > 0,
                              '隐藏筛选角色列表滚动', timeout=8)
        # The list keeps gliding after the bar first moves; banners read on a
        # moving frame are missed and those cards may scroll past unseen.
        for _ in range(10):
            moving = self.ui.scrollbar_bounds(screen, TRACK)
            settled = self.ui.capture()
            if hidden_screen(settled) and self.ui.scrollbar_bounds(settled, TRACK) == moving:
                return settled
            screen = settled
        raise EventUIError('隐藏筛选角色列表滚动未停止')

    def banners(self, screen):
        """The banner pulses: absent, shown, then fading, about every two
        seconds, and a fading banner is often unreadable. It also changes the
        card edge, so card positions from one frame are neither complete nor
        a stillness test. Sample one pulse of the still grid (same scrollbar)
        and keep every card read with a banner in any sample."""
        bar = self.ui.scrollbar_bounds(screen, TRACK)
        frames, positions = [screen], cards(screen)
        for _ in range(PULSE_SAMPLES):
            time.sleep(.35)
            frame = self.ui.capture(ocr=False)
            if self.ui.scrollbar_bounds(frame, TRACK) != bar:
                raise EventUIError('隐藏筛选角色网格在读取受限角色期间移动')
            frames.append(frame)
            positions += [(x, y) for x, y in cards(frame)
                          if not any(abs(x-a) < 12 and abs(y-b) < 12 for a, b in positions)]
        if not positions:
            raise EventUIError('隐藏筛选角色网格未识别')
        found = []
        for frame in frames:
            found += [p for p in restricted_cards(self.ui, frame, positions) if p not in found]
        # The unchanged scrollbar keeps this OCR-free frame on the same page.
        return frames[-1], sorted(found, key=lambda p: (p[1], p[0]))

    def tap(self, position, done, unchanged, description):
        """The grid can drop a tap during its update animation. Repeat only
        after a fresh frame still shows the state from before the tap."""
        def settled(check):
            def observe(screen):
                # Slots can be briefly non-contiguous while the grid animates.
                try:
                    return hidden_screen(screen) and check(screen)
                except EventUIError:
                    return False
            return observe
        for attempt in range(3):
            self.ui.click(position)
            try:
                return self.ui.wait(settled(done), description, timeout=4)
            except EventUIError:
                if attempt == 2 or not settled(unchanged)(self.ui.capture()):
                    raise

    def restore(self):
        state = self.journal()
        if not state:
            return
        screen = self.open()
        original = state['original']
        current = selection(screen)
        if not len(original) <= len(current) <= state['maximum'] or not same_selection(current[:len(original)], original):
            raise EventUIError('隐藏筛选已被外部修改，保留恢复记录并停止')
        while len(current) > len(original):
            size = len(current)-1
            before = current
            screen = self.tap(SLOTS[size], lambda s: len(selection(s)) == size,
                              lambda s: same_selection(selection(s), before), '移除临时隐藏角色')
            current = selection(screen)
            if not same_selection(current[:len(original)], original):
                raise EventUIError('恢复隐藏筛选时原角色发生变化')
        self.close(True)
        screen = self.open()
        if not same_selection(selection(screen), original):
            raise EventUIError('隐藏角色原设置恢复未确认')
        self.close(False)
        atomic_json(self.path, {})

    def apply(self, from_end=False):
        """Hide restricted roles in list order; from_end walks upward from
        the bottom, choosing a different subset when the slots overflow."""
        step = -1 if from_end else 1
        def at_start(bounds):
            return bounds[1] >= TRACK[3]-5 if from_end else bounds[0] <= TRACK[1]+4
        def at_end(bounds):
            return bounds[0] <= TRACK[1]+4 if from_end else bounds[1] >= TRACK[3]-5
        if self.journal():
            raise EventUIError('隐藏筛选存在未恢复设置，须先恢复')
        screen = self.open()
        original = selection(screen)
        state = dict(version=1, original=original, maximum=len(original))
        result = dict(original=len(original), added=0, capacity_limited=False, scanned_to_end=False)
        # Record before any card click; interruption can occur before its reply.
        atomic_json(self.path, state)
        try:
            for _ in range(150):
                self.check_deadline()
                bounds = self.ui.scrollbar_bounds(screen, TRACK)
                if bounds is None:
                    raise EventUIError('隐藏筛选角色滚动条未识别')
                if at_start(bounds):
                    break
                screen = self.scroll(screen, -step)
            else:
                raise EventUIError('隐藏筛选列表无法回到扫描起点')
            for _ in range(150):
                self.check_deadline()
                # Selected cards keep the pulsing banner; the tick tells them apart.
                screen, found = self.banners(screen)
                for x, y in (found[::-1] if from_end else found):
                    self.check_deadline()
                    if checked(screen, x, y):
                        continue
                    current = selection(screen)
                    if len(current) == CAPACITY:
                        result['capacity_limited'] = True
                        break
                    state['maximum'] = len(current)+1
                    atomic_json(self.path, state)
                    count = len(current)+1
                    screen = self.tap((x, y),
                        lambda s: len(selection(s)) == count and checked(s, x, y),
                        lambda s: same_selection(selection(s), current), '选中受限角色')
                    if not same_selection(selection(screen)[:len(current)], current):
                        raise EventUIError('隐藏筛选选中后原角色顺序变化')
                    result['added'] += 1
                    if count == CAPACITY:
                        result['capacity_limited'] = True
                        break
                if result['capacity_limited']:
                    break
                before = self.ui.scrollbar_bounds(screen, TRACK)
                if before is None:
                    raise EventUIError('隐藏筛选角色滚动条未识别')
                if at_end(before):
                    result['scanned_to_end'] = True
                    break
                # Inter-column gutter avoids character long-press; overlap retains
                # complete cards even when the previous bottom row was clipped.
                screen = self.scroll(screen, step)
            else:
                raise EventUIError('隐藏筛选超过扫描上限，未确认列表终点')
            expected = selection(screen)
            self.close(True)
            screen = self.open()
            if not same_selection(selection(screen), expected):
                raise EventUIError('隐藏角色显示更新未确认')
            self.close(False)
            return result
        except Exception:
            # Keep the journal if navigation is uncertain. Startup restores it
            # before searching or attacking, including after process death.
            raise
