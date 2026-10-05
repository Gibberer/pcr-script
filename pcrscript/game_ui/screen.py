"""Background UI primitives using a normalized 960 x 540 coordinate space.

No game network API or foreground input is used. OCR is loaded only by this task.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import re
import subprocess
from pcrscript.run_session import clock as time
import unicodedata

import cv2 as cv
import numpy as np


class EventUIError(RuntimeError):
    pass


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("−", "-")


@dataclass
class TextBox:
    text: str
    score: float
    box: list

    @property
    def center(self):
        points = np.asarray(self.box)
        return tuple(points.mean(axis=0).astype(int))


def claimable_task_snapshot(screen, roi):
    """Keep confident task content and enabled row controls for claim recovery."""
    if screen.find('正在进行数据连接|连接中|加载中'):
        return None
    items = [item for item in screen.items
             if roi[0] <= item.center[0] <= roi[2] and roi[1] <= item.center[1] <= roi[3]]
    if (not items or any(item.score < .95 for item in items)
            or not any(normalized(item.text) == '收取' and screen.blue_button(item) for item in items)
            or not any(len(normalized(item.text)) > 4 and re.search(r'[\u4e00-\u9fff]',item.text)
                       for item in items)):
        return None
    rows = [[normalized(item.text), *map(int,item.center),
             screen.blue_button(item) if normalized(item.text) == '收取' else None]
            for item in items]
    return dict(version=1, rows=sorted(rows,key=lambda row:(row[2],row[1],row[0])))


class EventScreen:
    def __init__(self, image, items):
        self.image = image
        self.items = items

    def find(self, pattern, roi=(0, 0, 960, 540), exact=False):
        for item in self.items:
            x, y = item.center
            if item.score < .82 or not (roi[0] <= x <= roi[2] and roi[1] <= y <= roi[3]):
                continue
            text = normalized(item.text)
            if (re.fullmatch if exact else re.search)(pattern, text):
                return item
        return None

    def all(self, pattern, roi=(0, 0, 960, 540)):
        return [item for item in self.items if item.score >= .82
                and roi[0] <= item.center[0] <= roi[2] and roi[1] <= item.center[1] <= roi[3]
                and re.search(pattern, normalized(item.text))]

    def text(self, roi=(0, 0, 960, 540)):
        return " ".join(item.text for item in self.all(".*", roi))

    def number(self, roi, pattern=r"\d+"):
        item = self.find(pattern, roi, exact=True)
        return int(normalized(item.text)) if item and normalized(item.text).isdigit() else None

    def blue_button(self, item):
        """Require a bright blue fill, not the dark disabled variant."""
        if not item:
            return False
        x, y = item.center
        patch = self.image[max(0, y-18):min(540, y+18), max(0, x-40):min(960, x+40)]
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        return float(np.mean((hsv[:, :, 0] > 85) & (hsv[:, :, 0] < 120)
                             & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 180))) > .15

    def notification(self, roi):
        """Pink diamond notification, checked only at an entry's known badge."""
        x1, y1, x2, y2 = roi
        hsv = cv.cvtColor(self.image[y1:y2, x1:x2], cv.COLOR_BGR2HSV)
        mask = cv.inRange(hsv, np.array([145, 70, 140]), np.array([179, 255, 255]))
        _, _, stats, _ = cv.connectedComponentsWithStats(mask)
        return any(10 <= w <= 22 and 10 <= h <= 22 and 60 <= area <= 250
                   and .35 <= area/(w*h) <= .75 for _, _, w, h, area in stats[1:])

    def gray_story_control(self, item):
        """Recognize the disabled gray fill of an opened story-menu control."""
        if not item:
            return False
        x, y = item.center
        patch = self.image[max(0, y-18):min(540, y+12), max(0, x-35):min(960, x+35)]
        hsv = cv.cvtColor(patch, cv.COLOR_BGR2HSV)
        return float(np.mean((hsv[:, :, 1] < 90) & (hsv[:, :, 2] > 75)
                             & (hsv[:, :, 2] < 190))) > .65

    def letterboxed_movie(self):
        """The event ending fills the centre with black bands above and below."""
        if self.find('菜单|帮助|关卡|队伍编组|活动剧情|取消|关闭|加载|下载'):
            return False
        return (float(np.mean(self.image[:42])) < 8
                and float(np.mean(self.image[500:530])) < 8
                and float(np.mean(self.image[90:450])) > 30)

    def battle_dialogue(self):
        """In-battle story overlay: pink speaker tab over a pale text panel."""
        if (self.find('主菜单|队伍编组|取消|确认|跳过这个剧情')
                or not self.find('.+', (180, 390, 380, 418))
                or not self.find('.+', (180, 418, 795, 505))):
            return False
        hsv = cv.cvtColor(self.image, cv.COLOR_BGR2HSV)
        tab = hsv[393:412, 190:365]
        panel = hsv[420:490, 185:790]
        return (float(np.mean((tab[:, :, 0] > 145) & (tab[:, :, 1] > 70)
                              & (tab[:, :, 2] > 140))) > .4
                and float(np.mean((panel[:, :, 1] < 65) & (panel[:, :, 2] > 180))) > .65)

    def counter_badge(self, roi):
        """Pink numeric badges remain visible when OCR misses a single digit."""
        x1, y1, x2, y2 = roi
        hsv = cv.cvtColor(self.image[y1:y2, x1:x2], cv.COLOR_BGR2HSV)
        mask = cv.inRange(hsv, np.array([145, 70, 140]), np.array([179, 255, 255]))
        return float(np.mean(mask > 0)) > .25

    @property
    def event_home(self):
        return bool(self.find("活动剧情", (650, 280, 960, 465)) and self.find("报酬[交兑]换", (0, 280, 400, 465)))

    @property
    def event_quests(self):
        return bool(self.find("活动关卡.*首领", (0, 0, 330, 65)))

    @property
    def story_list(self):
        return bool(self.find("活动剧情", (0, 0, 250, 60)))

    @property
    def expedition_home(self):
        # Expedition has a top-right menu too; it is not an active battle.
        return all((item := self.find(text, roi, exact=True)) and item.score >= .95
                   for text, roi in (("探险", (45, 0, 180, 65)),
                                     ("冒险目的地", (20, 415, 190, 480)),
                                     ("冒险", (475, 475, 595, 540))))


class EventUI:
    def __init__(self, driver, output="cache/agent/ui", timeout=45):
        self.driver = driver
        # The captured frame, rather than wm size or emulator metadata, is
        # authoritative for design-coordinate conversion.
        self.width, self.height = 0, 0
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._ocr = None
        self.last = None

    def capture(self, ocr=True):
        return self.observe(self.driver.screenshot(), ocr=ocr)

    def observe(self, img, ocr=True):
        """Recognize a frame already captured by the shared action runner."""
        if img is None or not img.size:
            raise EventUIError("模拟器截图失败")
        # Capture size is authoritative (the emulator can change resolution
        # after driver construction). OCR, templates and ROIs stay normalized.
        self.height, self.width = img.shape[:2]
        img = cv.resize(img, (960, 540), interpolation=cv.INTER_AREA)
        items = []
        if ocr:
            if self._ocr is None:
                try:
                    from rapidocr import RapidOCR
                except ImportError as error:
                    raise EventUIError("活动任务需要安装 requirements.txt 中的 OCR 依赖") from error
                self._ocr = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                                              "EngineConfig.onnxruntime.inter_op_num_threads": 1})
            # RapidOCR remembers per-call mode flags. Restore detection after
            # a number-only recognition so the next frame still has boxes.
            result = self._ocr(img, use_det=True, use_cls=True, use_rec=True)
            if result.txts:
                items = [TextBox(t, float(s), b.tolist()) for t, s, b in
                         zip(result.txts, result.scores, result.boxes)]
        from pcrscript.run_session import emit
        emit("ocr", items=[dict(text=i.text, score=i.score, box=i.box) for i in items])
        self.last = EventScreen(img, items)
        self.save("current", self.last)
        return self.last

    def save(self, name, screen=None):
        screen = screen or self.last or self.capture()
        name = re.sub(r"[^\w.-]", "_", name)
        ok, encoded = cv.imencode(".png", screen.image)
        if not ok:
            raise EventUIError("截图编码失败")
        encoded.tofile(self.output / f"{name}.png")
        (self.output / f"{name}.json").write_text(json.dumps([
            {"text": i.text, "score": i.score, "box": i.box} for i in screen.items
        ], ensure_ascii=False, indent=2), encoding="utf-8")
        return self.output / f"{name}.png"

    def click(self, pos, delay=.8):
        if not self.width or not self.height:
            self.capture(ocr=False)
        if isinstance(pos, TextBox):
            pos = pos.center
        x, y = pos
        self.driver.click(round(x*self.width/960), round(y*self.height/540))
        time.sleep(delay)

    def number(self, screen, roi):
        value = screen.number(roi)
        if value is not None:
            return value
        # Full-frame detection sometimes omits an isolated 0. Retry only the
        # known numeric field at higher resolution, never treat missing as zero.
        x1, y1, x2, y2 = roi
        # A thin "1" can disappear at 4x and be read reliably at 3x. Require
        # high confidence for either scale; an uncertain field must stay unknown.
        for scale in (4, 3):
            patch = cv.resize(screen.image[y1:y2, x1:x2], None, fx=scale, fy=scale)
            # Numeric fields are upright; classification can rotate 9 into 6.
            result = self._ocr(patch, use_det=True, use_cls=False, use_rec=True)
            scores = result.scores if result.scores is not None else []
            if result.txts is None or len(result.txts) == 0 or not any(score >= .95 for score in scores):
                result = self._ocr(patch, use_det=False, use_cls=False)
            raw_texts = result.txts if result.txts is not None else []
            raw_scores = result.scores if result.scores is not None else []
            texts = [normalized(t) for t, score in zip(raw_texts, raw_scores) if score >= .95]
            if len(texts) == 1 and texts[0].isdigit():
                return int(texts[0])
        return None

    def read_region(self, screen, roi, *, classify=True):
        """Retry small missed labels at 3x, retaining baseline coordinates."""
        x1, y1, x2, y2 = roi
        patch = cv.resize(screen.image[y1:y2, x1:x2], None, fx=3, fy=3)
        result = self._ocr(patch, use_det=True, use_cls=classify, use_rec=True)
        items = []
        if result.txts:
            items = [TextBox(t, float(score), (np.asarray(box)/3 + (x1, y1)).tolist())
                     for t, score, box in zip(result.txts, result.scores, result.boxes)]
        elif y2-y1 <= 40:
            # A short label can be readable even when its tightly cropped
            # field has no detected box. Recognition still needs the caller's
            # exact label and confidence check; do not apply this to paragraphs.
            result = self._ocr(patch, use_det=False, use_cls=False, use_rec=True)
            if result.txts and len(result.txts) == 1:
                items = [TextBox(result.txts[0], float(result.scores[0]),
                                 [[x1,y1],[x2,y1],[x2,y2],[x1,y2]])]
        return EventScreen(screen.image, items)

    def swipe(self, start, end, duration=450):
        if not self.width or not self.height:
            self.capture(ocr=False)
        conv = lambda p: (round(p[0]*self.width/960), round(p[1]*self.height/540))
        self.driver.swipe(conv(start), conv(end), duration)
        time.sleep(.8)

    @staticmethod
    def scrollbar_bounds(screen, roi):
        x1, y1, x2, y2 = roi
        hsv = cv.cvtColor(screen.image[y1:y2, x1:x2], cv.COLOR_BGR2HSV)
        rows = np.nonzero(((hsv[:, :, 0] > 90) & (hsv[:, :, 0] < 115)
                           & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 140)).any(axis=1))[0]
        if len(rows) < 15:
            return None
        # Touch sparkles can remove a few thumb rows or add isolated blue
        # pixels elsewhere on the track. Use the main interval, tolerating
        # short occlusions without treating those stray pixels as the thumb.
        intervals = np.split(rows, np.nonzero(np.diff(rows) > 5)[0]+1)
        thumb = max(intervals, key=len)
        if len(thumb) < 15:
            return None
        return int(thumb[0]+y1), int(thumb[-1]+y1)

    def scrollbar(self, screen, roi, direction):
        """Verify a list drag before using its background input fallback."""
        bounds = self.scrollbar_bounds(screen, roi)
        if bounds is None:
            raise EventUIError('列表滚动条未确认')
        x1, y1, x2, y2 = roi
        if direction < 0 and bounds[0] <= y1+2 or direction > 0 and bounds[1] >= y2-2:
            return False
        center = sum(bounds)//2
        body_roi = (max(0,x1-430), y1-15, x1-12, y2+24)
        before_text = normalized(screen.text(body_roi))
        # Near the lower end, dragging from the thumb's bottom leaves too
        # little travel for Android to recognize a swipe. Its center retains
        # room to reach the end of the verified track.
        start = ((x1+x2)//2, center)
        end = (start[0], max(y1, min(y2-1, start[1]+direction*max(120, round((bounds[1]-bounds[0])*.8)))))
        convert = lambda p: (round(p[0]*self.width/960), round(p[1]*self.height/540))
        def changed(timeout):
            until = time.monotonic()+timeout
            while time.monotonic() < until:
                after = self.capture()
                actual = self.scrollbar_bounds(after, roi)
                if actual is None:
                    # The game's touch highlight briefly covers the thumb.
                    # Wait for its colour to settle before reading its position.
                    time.sleep(.3)
                    continue
                same_height = abs((actual[1]-actual[0])-(bounds[1]-bounds[0])) <= max(5,(bounds[1]-bounds[0])*.12)
                if (same_height and direction*(sum(actual)//2-center) >= 5
                        and (not before_text or normalized(after.text(body_roi)) != before_text)):
                    return True
                time.sleep(.3)
            return False
        self.swipe(start, end, duration=500)
        if changed(3):
            return True
        if not getattr(self.driver, 'supports_scrollbar_fallback', False):
            raise EventUIError('列表后台滑动未生效')
        try:
            self.driver.swipe(convert(start), convert(end), 500, fallback=True)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            raise EventUIError('列表后台滑动回退失败：'+str(error)) from error
        if not changed(8):
            # A newly opened detail can render before its scroll view accepts
            # input. Retry once only when both position and content stayed put.
            latest = self.capture()
            if (self.scrollbar_bounds(latest, roi) == bounds
                    and normalized(latest.text(body_roi)) == before_text):
                self.swipe(start, end, duration=500)
                if changed(3):
                    return True
            raise EventUIError('列表后台滑动回退后未确认变化')
        return True

    def wait(self, predicate, description, timeout=None, handle=None):
        from pcrscript.run_session import emit
        emit("wait", description=description, timeout=timeout or self.timeout)
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            s = self.capture()
            if predicate(s):
                return s
            if handle:
                handle(s)
            time.sleep(.3)
        self.save("timeout_" + description)
        raise EventUIError(f"{description}超时；截图保存在 {self.output}")

    def expect_click(self, pattern, roi=(0, 0, 960, 540), exact=False):
        s = self.wait(lambda s: s.find(pattern, roi, exact), pattern)
        self.click(s.find(pattern, roi, exact))
