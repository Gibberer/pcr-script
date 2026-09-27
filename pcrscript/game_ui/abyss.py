"""Deep-area observations; only the observed 960x540 layout is verified."""
from dataclasses import dataclass
from pathlib import Path
import re
import cv2 as cv
import numpy as np
from .screen import EventScreen, TextBox, normalized


AREAS = {'fire': ('红焰深域', '火属性'), 'water': ('苍波深域', '水属性'),
         'wind': ('翠岚深域', '风属性'), 'light': ('珀天深域', '光属性'),
         'dark': ('紫冥深域', '暗属性')}


@dataclass(frozen=True)
class AbyssStage:
    element: str
    chapter: int
    number: int

    @property
    def key(self) -> str:
        return f'{self.chapter}-{self.number}'

    @property
    def title(self) -> str:
        return AREAS[self.element][0]+self.key


def map_element(screen: EventScreen) -> str | None:
    if not screen.find('深域关卡', (45, 0, 210, 55), exact=True):
        return None
    return next((key for key, (name, _) in AREAS.items()
                 if screen.find(name, (45, 50, 210, 80), exact=True)), None)


def next_stage(screen: EventScreen) -> tuple[AbyssStage, TextBox] | None:
    element = map_element(screen)
    markers = screen.all('NEXT', (0, 100, 960, 340))
    if not element or len(markers) > 1:
        return None
    if markers:
        x, y = markers[0].center
    else:
        # OCR can miss the NEXT letters both under the attribute tabs and on
        # the map artwork (observed dark 3-4). Match the unique yellow arrow
        # across the map, then still require one nearby stage label.
        source = cv.imread(str(Path(__file__).resolve().parents[2]/'images/revival_next.png'))
        if source is None:
            return None
        template = source[18:35, 17:38]
        arrow_top = 99
        scores = cv.matchTemplate(screen.image[arrow_top:340], template, cv.TM_CCOEFF_NORMED)
        _, best, _, point = cv.minMaxLoc(scores)
        px, py = point
        scores[max(0, py-14):py+15, max(0, px-20):px+21] = -1
        runner_up=cv.minMaxLoc(scores)[1]
        # On the far chapter-3 map the arrow sits partly under the attribute
        # tabs. Its true match can be around .69 with one artwork decoy near
        # .56; the yellow-pixel and unique-stage checks below still apply.
        ordinary = best >= .56 and best-runner_up >= .16
        occluded = best >= .68 and runner_up < .57 and best-runner_up >= .12
        if not (ordinary or occluded):
            return None
        patch = cv.cvtColor(screen.image[arrow_top+py:arrow_top+py+17, px:px+21], cv.COLOR_BGR2HSV)
        yellow = (patch[:, :, 0] >= 12) & (patch[:, :, 0] <= 38) & (patch[:, :, 1] > 90) & (patch[:, :, 2] > 170)
        if not .06 <= float(np.mean(yellow)) <= .4:
            return None
        x, y = px+10, py+arrow_top+8
    # Boss artwork is taller: its stage label sits below the BOSS banner.
    boss = screen.find('BOSS', (max(0, x-45), y+60, min(960, x+45), min(412, y+190)), exact=True)
    labels = screen.all(r'\d+[-=]\d+', (max(0, x-45), y+60, min(960, x+45), min(412, y+(220 if boss else 190))))
    if len(labels) != 1:
        return None
    # The map label may gain a stray dot from animated artwork (".5-3").
    # Accept surrounding punctuation only; never infer a stage from a longer
    # number or unrelated OCR sentence.
    match = re.fullmatch(r'[.·:。,\s]*(\d+)[-=](\d+)[.·:。,\s]*', normalized(labels[0].text))
    if match is None:
        return None
    chapter, number = map(int, match.groups())
    if chapter < 1 or not 1 <= number <= 10:
        return None
    return AbyssStage(element, chapter, number), labels[0]


def detail_stage(screen: EventScreen) -> AbyssStage | None:
    for element, (area, _) in AREAS.items():
        item = screen.find(area+r'\d+-\d+', (30, 20, 510, 75), exact=True)
        if item:
            match = re.fullmatch(re.escape(area)+r'(\d+)-(\d+)', normalized(item.text))
            if int(match[1]) >= 1 and 1 <= int(match[2]) <= 10:
                return AbyssStage(element, int(match[1]), int(match[2]))
    return None


def remaining(screen: EventScreen, *, detail: bool = False) -> int | None:
    roi = (490, 432, 575, 478) if detail else (640, 425, 710, 465)
    item = screen.find(r'\d+/10', roi, exact=True)
    if item:
        value = int(normalized(item.text).split('/')[0])
        return value if 0 <= value <= 10 else None
    return None


def advanced(before: AbyssStage, after: AbyssStage) -> bool:
    return before.element == after.element and (after.chapter, after.number) > (before.chapter, before.number)
