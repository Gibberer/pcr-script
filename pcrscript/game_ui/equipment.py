"""Read the rotating equipment badge on a live party portrait.

Only two shared sword icons and five small orb references are matched. This
does not scan a character-image library or infer equipment from skill names.
"""
from pathlib import Path

import cv2 as cv
import numpy as np


class EquipmentBadges:
    def __init__(self):
        root = Path(__file__).resolve().parents[2] / "images/event"
        self.swords = [cv.imread(str(root / (name + ".png"))) for name in ("unique1", "unique12")]
        self.mask = np.zeros(self.swords[0].shape[:2], np.uint8)
        cv.circle(self.mask, (11, 10), 8, 255, -1)
        self.orbs = [cv.imread(str(root / f"orb{i}.png"), cv.IMREAD_GRAYSCALE) for i in range(5)]

    def read(self, image, rectangle):
        x, y, w, h = rectangle
        card = cv.resize(image[y:y+h, x:x+w], (100, 100), interpolation=cv.INTER_AREA)
        area = card[69:100, 0:37]
        scores = [float(np.nan_to_num(cv.matchTemplate(area, template, cv.TM_CCOEFF_NORMED,
                          mask=self.mask), nan=-1, posinf=-1).max()) for template in self.swords]
        best = int(np.argmax(scores))
        if scores[best] >= .88 and scores[best]-scores[1-best] >= .06:
            return True, bool(best)
        # No sword is only confirmed during the orb-information frame. During
        # the alternating numeric-star frame, the correct answer is unknown.
        gray = cv.cvtColor(card, cv.COLOR_BGR2GRAY)
        orb_scores = []
        for x1, x2 in ((2, 23), (13, 34), (24, 45)):
            area = gray[78:100, x1:x2]
            orb_scores.append(max(float(cv.matchTemplate(area, t, cv.TM_CCOEFF_NORMED).max()) for t in self.orbs))
        if min(orb_scores[:2]) >= .85 and orb_scores[2] >= .60:
            return False, False
        # Filled red/blue/yellow orbs have the same geometry but their portrait
        # backgrounds can lower grayscale correlation (Violet, 2026-09-19).
        # Require all three colors at the information-frame positions; numeric
        # star frames and sword+shifted-orb frames cannot satisfy this pattern.
        hsv = cv.cvtColor(card, cv.COLOR_BGR2HSV)
        expected = ((13, lambda h: (h < 8) | (h > 168)),
                    (22, lambda h: (h > 100) & (h < 125)),
                    (31, lambda h: (h >= 12) & (h < 35)))
        if all(np.mean(check(hsv[87:90, x-1:x+2, 0]) &
                       (hsv[87:90, x-1:x+2, 1] > 90) &
                       (hsv[87:90, x-1:x+2, 2] > 150)) >= .85
               for x, check in expected):
            return False, False
        return None

    def observe(self, ui, rectangle, frames=12):
        from pcrscript.run_session import clock as time
        confirmed = None
        repeats = 0
        for _ in range(frames):
            s = ui.capture(ocr=False)
            result = self.read(s.image, rectangle)
            if result is not None:
                repeats = repeats+1 if result == confirmed else 1
                confirmed = result
                if repeats >= 2:
                    return result, s
            time.sleep(.45)
        return None, ui.last
