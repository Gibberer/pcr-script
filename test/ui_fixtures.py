"""Synthetic observation/input boundaries; never bypass production decisions."""
from pathlib import Path
from unittest.mock import Mock

import cv2 as cv
import numpy as np

from pcrscript.game_ui.screen import EventScreen, TextBox


def screen(*labels, blue=(), yellow=(), background=245, score=.999,
           box_half_size=(25, 10), button_half_size=(50, 24)):
    image = np.full((540, 960, 3), background, np.uint8)
    items = []
    w, h = box_half_size
    bw, bh = button_half_size
    for text, x, y in labels:
        items.append(TextBox(text, score, [[x-w, y-h], [x+w, y-h], [x+w, y+h], [x-w, y+h]]))
        if text in blue:
            cv.rectangle(image, (x-bw, y-bh), (x+bw, y+bh), (230, 155, 25), -1)
    for x1, y1, x2, y2 in yellow:
        cv.rectangle(image, (x1, y1), (x2, y2), (25, 200, 245), -1)
    return EventScreen(image, items)


def replay_ui(output):
    ui = Mock(output=Path(output), last=None)
    ui.save.return_value = ui.output / 'synthetic.png'
    return ui


class TaskReplayMixin:
    def frames(self, values):
        """Repeat the last observation while the real task handles time/budgets."""
        iterator = iter(values)

        def capture():
            value = next(iterator, values[-1])
            self.task.ui.last = value
            return value

        self.task.ui.capture.side_effect = capture

    def clicks(self):
        return [getattr(call.args[0], 'text', call.args[0]) for call in self.task.ui.click.call_args_list]
