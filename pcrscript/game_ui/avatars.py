"""Incremental avatar lookup, independent of a character-class YOLO model.

Only labels confirmed in the game's character-details page enter this index.
All visible cards are queried against one in-memory matrix. New characters add
rows to the index rather than requiring neural-network training.
"""
from pathlib import Path
import os

import cv2 as cv
import numpy as np


def card_rectangles(image):
    """Locate this game's rounded square cards without recognizing identity."""
    area = image[115:372, 40:905]
    contours, _ = cv.findContours(cv.Canny(area, 80, 160), cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
    candidates = [cv.boundingRect(c) for c in contours]
    candidates = [r for r in candidates if 94 <= r[2] <= 104 and 94 <= r[3] <= 106]
    result = []
    for x, y, w, h in sorted(candidates, key=lambda r: -r[2]*r[3]):
        x, y = x+40, y+115
        if any(abs(x-r[0]) < 12 and abs(y-r[1]) < 12 for r in result):
            continue
        result.append((x, y, w, h))
    return sorted(result, key=lambda r: (r[1]//20, r[0]))


def face_crop(image, rectangle):
    x, y, w, h = rectangle
    return image[y+round(h*.23):y+round(h*.73), x+round(w*.18):x+round(w*.82)]


def search_card_rectangles(image, top=177):
    """Search results have a fixed first row. Event bonus arrows can break
    the top outline, so use occupancy inside each slot on this known layout.
    """
    result = []
    for x in (60, 166, 272, 378, 483, 589, 695, 801):
        patch = image[top+15:top+82, x+12:x+88]
        saturation = cv.cvtColor(patch, cv.COLOR_BGR2HSV)[:, :, 1]
        if float(np.mean(saturation > 45)) > .2:
            result.append((x, top, 100, 99))
    return result


def feature(picture):
    result = cv.resize(picture, (24, 24), interpolation=cv.INTER_AREA).astype(np.float32).reshape(-1)-128
    return result/max(np.linalg.norm(result), 1e-6)


class AvatarIndex:
    def __init__(self, directory="cache/game/avatars", load_existing=True):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)
        self.names = []
        self.matrix = np.empty((0, 24*24*3), dtype=np.float32)
        saved = self.path/"index.npz"
        if load_existing and saved.exists():
            with np.load(saved, allow_pickle=False) as data:
                if int(data["version"]) == 1:
                    self.names = list(data["names"].astype(str))
                    self.matrix = data["features"].astype(np.float32)
                    if self.matrix.shape != (len(self.names), 24*24*3) or not np.isfinite(self.matrix).all():
                        raise ValueError('头像索引维度或数值无效')

    def add(self, name, picture, persist=True):
        vector = feature(picture)
        same = [i for i, n in enumerate(self.names) if n == name]
        if same and float((self.matrix[same] @ vector).max()) > .99:
            return
        self.names.append(name)
        self.matrix = np.vstack((self.matrix, vector))
        if persist:
            self.save()

    def save(self):
        if getattr(self, 'read_only', False):
            return
        temporary = self.path/f"index.{os.getpid()}.npz"
        np.savez_compressed(temporary, version=1,
                            names=np.asarray(self.names), features=self.matrix)
        temporary.replace(self.path/"index.npz")

    def query(self, pictures, minimum=.92, margin=.06):
        if not pictures:
            return []
        if not self.names:
            return [None]*len(pictures)
        # No per-file reads or per-character feature extraction here.
        scores = np.stack([feature(p) for p in pictures]) @ self.matrix.T
        result = []
        for row in scores:
            best_by_name = {}
            for index in np.argsort(row)[::-1]:
                best_by_name.setdefault(self.names[index], float(row[index]))
                if len(best_by_name) == 2:
                    break
            ranked = list(best_by_name.items())
            top = ranked[0]
            second = ranked[1][1] if len(ranked) > 1 else -1
            result.append(top[0] if top[1] >= minimum and top[1]-second >= margin else None)
        return result
