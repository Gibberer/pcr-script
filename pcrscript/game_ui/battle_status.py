"""Read battle portraits together with their visible HP bars."""
import cv2 as cv
import numpy as np


def portrait_states(image, portraits):
    """Return positive living/fallen cues; an obscured portrait stays unknown.

    CN 960x540 battle portraits retain their original colors after a KO.
    Desaturation alone therefore misses fallen members. A dark face must
    also have an empty HP bar; a darkened opening with green HP is not a KO.
    """
    living, fallen = [], []
    for index, (x1, y1, x2, y2) in enumerate(portraits):
        if not (0 <= x1 < x2 <= image.shape[1] and 0 <= y1 < y2+22 <= image.shape[0]):
            continue
        face = image[y1:y2, x1:x2]
        bar = image[y2+10:y2+22, x1:x2].astype(np.int16)
        green = (bar[:, :, 1] > bar[:, :, 2]+22) & (bar[:, :, 1] > bar[:, :, 0]+30)
        if np.any(green):
            living.append(index)
        elif cv.cvtColor(face, cv.COLOR_BGR2HSV)[:, :, 2].mean() < 110:
            # A missing/covered bar cannot establish survival. Require the
            # visible light outline of the empty bar before reporting a KO.
            neutral = (bar.max(axis=2)-bar.min(axis=2) < 45) & (bar.max(axis=2) > 140)
            if np.mean(neutral) > .04:
                fallen.append(index)
    return dict(living=living, fallen=fallen)
