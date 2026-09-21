"""Background UI primitives using a normalized 960 x 540 coordinate space.

No game network API or foreground input is used. OCR is loaded only by this task.
"""
from dataclasses import dataclass
from pathlib import Path
import json
import re
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

    @property
    def event_home(self):
        return bool(self.find("活动剧情", (650, 280, 960, 465)) and self.find("报酬[交兑]换", (0, 280, 400, 465)))

    @property
    def event_quests(self):
        return bool(self.find("活动关卡.*首领", (0, 0, 330, 65)))

    @property
    def story_list(self):
        return bool(self.find("活动剧情", (0, 0, 250, 60)))


class EventUI:
    def __init__(self, driver, output="cache/agent/ui", timeout=45):
        self.driver = driver
        self.width, self.height = driver.get_screen_size()
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._ocr = None
        self.last = None

    def capture(self, ocr=True):
        img = self.driver.screenshot()
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
                    raise EventUIError("活动任务需要安装 requirements-event.txt 中的 OCR 依赖") from error
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
        patch = cv.resize(screen.image[y1:y2, x1:x2], None, fx=4, fy=4)
        result = self._ocr(patch, use_det=True, use_cls=True, use_rec=True)
        # The detector can drop a thin "1" even at 4x. Only when no text was
        # detected, send the already-localized field straight to recognition.
        # Keep detection for "0": it removes padding that lowers confidence.
        if result.txts is None or len(result.txts) == 0:
            result = self._ocr(patch, use_det=False, use_cls=False)
        raw_texts = result.txts if result.txts is not None else []
        raw_scores = result.scores if result.scores is not None else []
        texts = [normalized(t) for t, score in zip(raw_texts, raw_scores) if score >= .95]
        return int(texts[0]) if len(texts) == 1 and texts[0].isdigit() else None

    def read_region(self, screen, roi):
        """Retry small missed labels at 3x, retaining baseline coordinates."""
        x1, y1, x2, y2 = roi
        patch = cv.resize(screen.image[y1:y2, x1:x2], None, fx=3, fy=3)
        result = self._ocr(patch, use_det=True, use_cls=True, use_rec=True)
        items = []
        if result.txts:
            items = [TextBox(t, float(score), (np.asarray(box)/3 + (x1, y1)).tolist())
                     for t, score, box in zip(result.txts, result.scores, result.boxes)]
        return EventScreen(screen.image, items)

    def swipe(self, start, end, duration=450):
        conv = lambda p: (round(p[0]*self.width/960), round(p[1]*self.height/540))
        self.driver.swipe(conv(start), conv(end), duration)
        time.sleep(.8)

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
